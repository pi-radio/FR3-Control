"""Background device discovery. Polls serial ports, filters by VID/PID, and
probes new candidates with *IDN? to confirm identity. Runs on its own
QThread - only communicates via signals, so a hung device can't freeze the UI.

Ownership rule: once a Device is handed off via device_connected, this
worker never touches it again (or stores a reference) - only bare port
name strings are tracked for already-adopted ports. Doing otherwise once
caused the discovery thread and a device's own worker thread to touch the
same connection concurrently, causing intermittent freezes."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import serial.tools.list_ports
from PySide6.QtCore import QThread, Signal

from .capabilities import BoardCapabilities, get_capabilities
from .device import Device, DeviceError

logger = logging.getLogger(__name__)

# pid.codes shared open-source VID + its "test PID" - fine for bench use,
# but request a real PID before shipping units elsewhere.
TARGET_VID = 0x1209
TARGET_PID = 0x0001

# Matches firmware's *IDN?: "<name> REV<revision>,<mcu>,<fw>"
_IDN_RE = re.compile(r"^(.*) REV([^,]+),(.+)$")

DEFAULT_POLL_INTERVAL_S = 1.0
PROBE_TIMEOUT_S = 0.5

# Set once a device is confirmed real - a full LMX2820 retune can take
# seconds, well past PROBE_TIMEOUT_S. See Device.set_timeout().
OPERATING_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class DeviceInfo:
    port_name: str
    board_name: str
    revision: str
    serial_number: int
    capabilities: BoardCapabilities
    device: Device

    @property
    def tab_key(self) -> str:
        """Identity for a physical unit, independent of COM port."""
        return f"{self.board_name}:{self.serial_number}"


class DiscoveryWorker(QThread):
    device_connected = Signal(object)  # DeviceInfo - .device ownership transfers to receiver
    port_gone = Signal(str)  # port_name of an adopted device that disappeared

    def __init__(self, poll_interval_s: float = DEFAULT_POLL_INTERVAL_S, parent=None):
        super().__init__(parent)
        self._poll_interval_s = poll_interval_s
        self._running = True
        self._adopted_ports: set[str] = set()

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        logger.info("Discovery thread started (VID=0x%04X PID=0x%04X)", TARGET_VID, TARGET_PID)
        while self._running:
            try:
                self._scan_once()
            except Exception:
                logger.exception("Unhandled error during discovery scan cycle")
            self.msleep(int(self._poll_interval_s * 1000))
        logger.info("Discovery thread stopping")

    def _scan_once(self) -> None:
        current_ports = {
            p.device
            for p in serial.tools.list_ports.comports()
            if p.vid == TARGET_VID and p.pid == TARGET_PID
        }

        gone_ports = self._adopted_ports - current_ports
        for port_name in gone_ports:
            self._adopted_ports.discard(port_name)
            logger.info("Port %s no longer present", port_name)
            self.port_gone.emit(port_name)

        candidate_ports = current_ports - self._adopted_ports
        for port_name in candidate_ports:
            if not self._running:
                return
            info = self._probe(port_name)
            if info is not None:
                self._adopted_ports.add(port_name)
                logger.info(
                    "Adopted %s on %s (serial=%s)", info.board_name, port_name, info.serial_number
                )
                self.device_connected.emit(info)

    def _probe(self, port_name: str) -> DeviceInfo | None:
        logger.debug("Probing candidate port %s", port_name)
        try:
            device = Device(port_name, timeout=PROBE_TIMEOUT_S)
        except Exception as exc:
            # Routine (port busy or gone) - retried next cycle.
            logger.debug("Could not open %s (busy or gone): %s", port_name, exc)
            return None

        try:
            idn = device.get_idn()
            match = _IDN_RE.match(idn)
            if not match:
                logger.debug("Port %s responded to *IDN? with unrecognized text: %r", port_name, idn)
                device.close()
                return None

            board_name, revision, _rest = match.groups()
            caps = get_capabilities(board_name, revision)
            if caps is None:
                logger.warning(
                    "Port %s identifies as %r rev %r - no capability entry for this board/revision",
                    port_name, board_name, revision,
                )
                device.close()
                return None

            serial_number = device.get_board_serial()
        except DeviceError as exc:
            logger.debug("Probe of %s failed: %s", port_name, exc)
            device.close()
            return None

        # Confirmed real - switch to the longer operating timeout.
        device.set_timeout(OPERATING_TIMEOUT_S)

        return DeviceInfo(
            port_name=port_name,
            board_name=board_name,
            revision=revision,
            serial_number=serial_number,
            capabilities=caps,
            device=device,
        )
