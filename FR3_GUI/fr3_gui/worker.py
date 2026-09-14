"""Per-device worker thread. Owns one Device for its tab's lifetime.
Commands go through a queue processed on this thread, so the GUI thread
never blocks on serial I/O. Also polls lock status on a fixed cadence,
interleaved with queued commands."""

from __future__ import annotations

import logging
import queue
import time

from PySide6.QtCore import QThread, Signal

from .capabilities import BoardCapabilities
from .device import LMX_REGISTER_COUNT, Device, DeviceError

logger = logging.getLogger(__name__)

LOCK_POLL_INTERVAL_S = 0.75
_STOP = object()
_SNAPSHOT = object()
_READ_ALL_LMX_REGS = object()


class DeviceWorker(QThread):
    values_read = Signal(dict)  # one-shot snapshot of every persisted value
    lock_status_changed = Signal(str)  # 'LOCKED' / 'UNLOCKED' / 'INVALID'
    command_result = Signal(str, bool)  # (method_name, success) for SET-style calls
    command_error = Signal(str)  # human-readable I/O/timeout error
    connection_lost = Signal()
    lmx_register_read = Signal(int, int)  # (addr, value) - single-register lookup
    # object, not dict: Signal(dict) marshals via Qt's QVariantMap, which
    # requires string keys and silently drops this int-keyed dict.
    all_lmx_registers_read = Signal(object)  # {addr: value} for registers 0-122

    def __init__(self, device: Device, capabilities: BoardCapabilities, parent=None):
        super().__init__(parent)
        self._device = device
        self._caps = capabilities
        self._queue: "queue.Queue" = queue.Queue()
        self._running = True

    def stop(self) -> None:
        self._running = False
        self._queue.put((_STOP, (), {}))

    def submit(self, method_name: str, *args, **kwargs) -> None:
        """Queue a Device method call by name. Safe from the GUI thread;
        result surfaces via command_result/command_error, not a return value."""
        self._queue.put((method_name, args, kwargs))

    def request_snapshot(self) -> None:
        self._queue.put((_SNAPSHOT, (), {}))

    def request_lmx_register(self, addr: int) -> None:
        self._queue.put(("read_lmx_register", (addr,), {}))

    def request_all_lmx_registers(self) -> None:
        self._queue.put((_READ_ALL_LMX_REGS, (), {}))

    def run(self) -> None:
        logger.info("Worker started for %s", self._device.port_name)
        next_lock_poll = 0.0
        while self._running:
            wait_s = max(0.05, next_lock_poll - time.monotonic()) if self._caps.has_lmx2820 else None
            try:
                name, args, kwargs = self._queue.get(timeout=wait_s)
            except queue.Empty:
                name, args, kwargs = None, (), {}

            if name is _STOP:
                break

            if name is not None:
                start = time.monotonic()
                try:
                    if name is _SNAPSHOT:
                        self._read_snapshot()
                    elif name is _READ_ALL_LMX_REGS:
                        self._read_all_lmx_registers()
                    elif name == "read_lmx_register":
                        addr = args[0]
                        value = self._device.read_lmx_register(addr)
                        self.lmx_register_read.emit(addr, value)
                    else:
                        method = getattr(self._device, name)
                        result = method(*args, **kwargs)
                        if isinstance(result, bool):
                            self.command_result.emit(name, result)
                    logger.debug(
                        "%s: %s%r took %.0fms",
                        self._device.port_name, name, args, (time.monotonic() - start) * 1000,
                    )
                except DeviceError as exc:
                    logger.warning("%s: %s failed: %s", self._device.port_name, name, exc)
                    self.command_error.emit(str(exc))
                    self.connection_lost.emit()
                    break
                except Exception:
                    logger.exception("%s: unexpected error running %s", self._device.port_name, name)
                    self.command_error.emit(f"unexpected error running {name}")

            now = time.monotonic()
            if self._caps.has_lmx2820 and now >= next_lock_poll:
                try:
                    status = self._device.get_lmx_lock()
                except DeviceError as exc:
                    logger.warning("%s: lock poll failed: %s", self._device.port_name, exc)
                    self.command_error.emit(str(exc))
                    self.connection_lost.emit()
                    break
                self.lock_status_changed.emit(status)
                next_lock_poll = now + LOCK_POLL_INTERVAL_S

        logger.info("Worker stopping for %s", self._device.port_name)
        self._device.close()

    def _read_snapshot(self) -> None:
        caps = self._caps
        values: dict = {}

        if caps.has_lmx2820:
            values["lmx_freq_hz"] = self._device.get_lmx_freq_hz()
            values["lmx_power"] = self._device.get_lmx_power()
            values["lmx_mute"] = self._device.get_lmx_mute()
            values["lmx_lock"] = self._device.get_lmx_lock()
        if caps.has_ltc2668:
            values["i_v"] = self._device.get_i_v()
            values["q_v"] = self._device.get_q_v()
        if caps.has_clock_switch:
            values["clock_internal"] = self._device.get_clock_internal()
        if caps.has_lo_switch:
            values["lo_internal"] = self._device.get_lo_internal()
        if caps.has_iq_swap:
            values["iq_swap"] = self._device.get_iq_swap()
        if caps.has_rf_filters:
            values["tx_filter"] = self._device.get_tx_filter()
            values["rx_filter"] = self._device.get_rx_filter()

        self.values_read.emit(values)

    def _read_all_lmx_registers(self) -> None:
        values = {addr: self._device.read_lmx_register(addr) for addr in range(LMX_REGISTER_COUNT)}
        self.all_lmx_registers_read.emit(values)
