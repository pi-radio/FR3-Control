"""Serial access to the FR3 1CH under test, for measurement scripts.

Reuses the GUI's protocol layer (FR3_GUI/fr3_gui/device.py: line echo
handling, timeouts, DeviceError) instead of duplicating it, and adds the
flash-persistence switch on top.

Use MeasurementSession, never a bare Board, for any sweep:

    with MeasurementSession() as board:
        board.lmx_tune(12e9)
        ...

On entry it, in this exact order:
  1. sends GET PERSIST as the very first command - old firmware answers
     with an ERR echo, and the session refuses to continue;
  2. checks *IDN? is the expected board and revision;
  3. snapshots the board's configuration (reads only);
  4. sends SET PERSIST OFF (so thousands of setting changes don't erase and
     reprogram flash) and confirms it took.
On exit - normal, exception or Ctrl-C - it first restores the snapshot, then
sends SET PERSIST ON and confirms. The order matters: SET PERSIST ON writes
the live state to flash, so the board must already be back in the state it
was found in, or the sweep's last settings would become its power-on state.

Caveat: if the process is killed outright (not Ctrl-C), the board stays in
PERSIST OFF until it is reset or power-cycled, or until someone sends
SET PERSIST ON. It is never stored in flash, so a reset always restores ON.

Only one program can hold the COM port: close the GUI (or press its
Disconnect button) first."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import serial.tools.list_ports

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "FR3_GUI"))
from fr3_gui.device import Device, DeviceError  # noqa: E402

TARGET_VID = 0x1209  # same USB IDs the GUI's discovery uses
TARGET_PID = 0x0001
EXPECTED_BOARD = "FR3 1CH"
EXPECTED_REVISION = "1.4"

# A full LMX2820 cold tune can take several seconds (see the firmware's
# retry logic), so use a generous timeout rather than the GUI probe's 0.5 s.
OPERATING_TIMEOUT_S = 15.0

_IDN_RE = re.compile(r"^(.*) REV([^,]+),(.+)$")


class FirmwareError(Exception):
    """The board's firmware or identity is not what the measurement needs."""


class Board(Device):
    """GUI Device plus the persistence switch."""

    def get_persist(self) -> bool:
        reply = self._query("GET PERSIST")
        if reply == "ON":
            return True
        if reply == "OFF":
            return False
        raise FirmwareError(
            f"GET PERSIST returned {reply!r} instead of ON/OFF: this board's firmware "
            "does not have the PERSIST feature. Rebuild the current firmware and flash "
            "it before measuring - on old firmware every setting change wears flash."
        )

    def set_persist(self, on: bool) -> bool:
        return self._query_ok(f"SET PERSIST {'ON' if on else 'OFF'}")

    def snapshot(self) -> dict:
        """Everything a measurement may change (FR3 1CH rev 1.4)."""
        return {
            "lmx_freq_hz": self.get_lmx_freq_hz(),
            "lmx_power": self.get_lmx_power(),
            "lmx_mute": self.get_lmx_mute(),
            "i_v": self.get_i_v(),
            "q_v": self.get_q_v(),
            "clock_internal": self.get_clock_internal(),
            "lo_internal": self.get_lo_internal(),
            "iq_swap": self.get_iq_swap(),
            "tx_filter": self.get_tx_filter(),
            "rx_filter": self.get_rx_filter(),
            **self._lo_modes(),
        }

    def _lo_modes(self) -> dict:
        """Firmware 1.4.1 AUTO modes (drive rule, calibration bias). A measurement that sets a drive or an
        I/Q bias switches them to MANUAL, so they are snapshotted and restored too. Firmware 1.00 does
        not have them (its reply is an ERR echo): nothing to record."""
        if self._query("LMX PWR MODE?") not in ("AUTO", "MANUAL"):
            return {}
        return {"lmx_power_auto": self.get_lmx_power_auto(), "iq_bias_auto": self.get_iq_bias()["auto"]}

    def restore(self, snap: dict) -> list[str]:
        """Puts the board back into a snapshot() state. Returns the names of
        any steps that failed (empty list = all good). Order matters: the LMX
        must be unmuted to retune, and is muted again last if it was muted."""
        failed: list[str] = []

        def step(name: str, ok: bool) -> None:
            if not ok:
                failed.append(name)

        step("clock", self.set_clock_internal(snap["clock_internal"]))
        step("lo->internal", self.set_lo_internal(True))  # unmutes + retunes the LMX
        step("lmx power", self.set_lmx_power(snap["lmx_power"]))
        step("lmx tune", self.lmx_tune(snap["lmx_freq_hz"]))
        step("i_v", self.set_i_v(snap["i_v"]))
        step("q_v", self.set_q_v(snap["q_v"]))
        step("iq", self.set_iq_swap(snap["iq_swap"]))
        step("tx filter", self.set_tx_filter(snap["tx_filter"]))
        step("rx filter", self.set_rx_filter(snap["rx_filter"]))
        # 1.4.1: the explicit LMX PWR / SET I_V / SET Q_V above leave MANUAL modes - back to AUTO if it was
        # (re-applies the drive and the calibration bias for the restored frequency)
        if snap.get("lmx_power_auto"):
            step("lmx power auto", self.set_lmx_power_auto())
        if snap.get("iq_bias_auto"):
            step("iq bias auto", self.set_iq_bias_auto(True))
        if snap["lmx_mute"] and snap["lo_internal"]:
            step("lmx mute", self.set_lmx_mute(True))
        if not snap["lo_internal"]:
            step("lo->external", self.set_lo_internal(False))  # also mutes the LMX
        return failed


def find_board_ports() -> list[str]:
    return [p.device for p in serial.tools.list_ports.comports()
            if p.vid == TARGET_VID and p.pid == TARGET_PID]


class MeasurementSession:
    def __init__(self, port: str | None = None,
                 expected_board: str = EXPECTED_BOARD,
                 expected_revision: str = EXPECTED_REVISION):
        self._port = port
        self._expected = (expected_board, expected_revision)
        self.board: Board | None = None
        self.persist_before: bool | None = None
        self.snapshot: dict | None = None

    def __enter__(self) -> Board:
        port = self._port
        if port is None:
            ports = find_board_ports()
            if len(ports) != 1:
                raise FirmwareError(
                    f"expected exactly one board (USB {TARGET_VID:04X}:{TARGET_PID:04X}), "
                    f"found {ports or 'none'} - pass port=... explicitly"
                )
            port = ports[0]

        board = Board(port, timeout=OPERATING_TIMEOUT_S)
        try:
            # 1. Very first command: proves the firmware has the feature.
            self.persist_before = board.get_persist()

            # 2. Right board, right revision.
            idn = board.get_idn()
            match = _IDN_RE.match(idn)
            if not match or (match.group(1), match.group(2)) != self._expected:
                raise FirmwareError(
                    f"*IDN? is {idn!r}, expected board {self._expected[0]!r} "
                    f"rev {self._expected[1]!r}"
                )

            # 3. Remember the configuration we found (reads only), so it can
            #    be put back before persistence is re-enabled.
            self.snapshot = board.snapshot()

            # 4. Suspend flash writes for the duration of the sweep.
            if not board.set_persist(False) or board.get_persist():
                raise FirmwareError("SET PERSIST OFF did not take effect")
        except BaseException:
            board.close()
            raise

        self.board = board
        return board

    def __exit__(self, exc_type, exc, tb) -> None:
        board, self.board = self.board, None
        if board is None:
            return
        # Put the configuration back FIRST: SET PERSIST ON writes the live
        # state to flash, so it must be the state we found, not the sweep's.
        try:
            failed = board.restore(self.snapshot)
            if failed:
                print(f"WARNING: could not restore board settings: {failed}", file=sys.stderr)
        except Exception as err:  # noqa: BLE001 - must not mask the original error
            print(f"WARNING: could not restore board settings: {err}", file=sys.stderr)
        try:
            restored = board.set_persist(True) and board.get_persist()
        except Exception as err:  # noqa: BLE001 - must not mask the original error
            restored = False
            print(f"WARNING: could not restore PERSIST ON: {err}", file=sys.stderr)
        finally:
            board.close()
        if not restored:
            message = ("PERSIST could not be restored to ON - the board stays in PERSIST OFF "
                       "until it is reset/power-cycled or sent SET PERSIST ON")
            print(f"WARNING: {message}", file=sys.stderr)
            if exc_type is None:
                raise FirmwareError(message)
