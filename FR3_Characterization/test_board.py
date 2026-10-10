"""Offline tests for board.MeasurementSession against a fake firmware with
real state - no hardware. Verifies the safety ordering: GET PERSIST first,
refuse old firmware / wrong board, SET PERSIST OFF for the sweep, and on the
way out the configuration restored BEFORE persistence is switched back ON
(SET PERSIST ON writes the live state to flash)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from board import FirmwareError, MeasurementSession


class FakeFirmware:
    """Mimics the board's line protocol: echoes the command, answers, then a
    blank line (as app_usbx_device.c does). Keeps live state, models the
    flash copy that persistence writes, and records every command."""

    def __init__(self, has_persist=True, idn="FR3 1CH REV1.4,STM32H573VIT6,FW1.00"):
        self.has_persist = has_persist
        self.idn = idn
        self.persist = True
        self.live = {"lmx_freq": 20_000_000_000, "lmx_pwr": 7, "lmx_mute": False,
                     "i_v": -0.18, "q_v": 0.372, "clock": "INT", "lo": "INT",
                     "iq": "THRU", "tx": 0x31, "rx": 0x00}
        self.flash = dict(self.live)      # what a power cycle would restore
        self.commands: list[str] = []
        self._queue: list[bytes] = []

    def _save(self) -> None:
        if self.persist:
            self.flash = dict(self.live)

    def _handle(self, cmd: str) -> str:
        u = cmd.upper()
        lv = self.live
        if u == "*IDN?":
            return self.idn
        if not self.has_persist and "PERSIST" in u:
            return f"ERR:[{u}]len={len(u)}"
        if u == "GET PERSIST":
            return "ON" if self.persist else "OFF"
        if u in ("SET PERSIST ON", "SET PERSIST OFF"):
            self.persist = u.endswith("ON")
            if self.persist:
                self.flash = dict(lv)     # firmware: enabling writes live state
            return "OK"
        getters = {"LMX FREQ?": lambda: str(lv["lmx_freq"]), "LMX PWR?": lambda: str(lv["lmx_pwr"]),
                   "LMX MUTE?": lambda: "ON" if lv["lmx_mute"] else "OFF",
                   "GET I_V": lambda: f"{lv['i_v']:.6f}", "GET Q_V": lambda: f"{lv['q_v']:.6f}",
                   "GET CLOCK": lambda: lv["clock"], "GET LO": lambda: lv["lo"],
                   "GET IQ": lambda: lv["iq"], "GET TXFILTER": lambda: f"0x{lv['tx']:02X}",
                   "GET RXFILTER": lambda: f"0x{lv['rx']:02X}"}
        if u in getters:
            return getters[u]()
        word = u.split()
        if u.startswith("LMX TUNE "):
            lv["lmx_freq"] = int(float(word[2])); lv["lmx_mute"] = False
        elif u.startswith("LMX PWR "):
            lv["lmx_pwr"] = int(word[2])
        elif u.startswith("LMX MUTE "):
            lv["lmx_mute"] = word[2] == "ON"
        elif u.startswith("SET I_V "):
            lv["i_v"] = float(word[2])
        elif u.startswith("SET Q_V "):
            lv["q_v"] = float(word[2])
        elif u.startswith("SET CLOCK "):
            lv["clock"] = word[2]
        elif u.startswith("SET LO "):
            lv["lo"] = word[2]
            lv["lmx_mute"] = word[2] == "EXT"
        elif u.startswith("SET IQ "):
            lv["iq"] = word[2]
        elif u.startswith("SET TXFILTER "):
            lv["tx"] = int(word[2], 16)
        elif u.startswith("SET RXFILTER "):
            lv["rx"] = int(word[2], 16)
        else:
            return f"ERR:[{u}]len={len(u)}"
        self._save()
        return "OK"

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").rstrip("\r\n")
        self.commands.append(cmd)
        self._queue = [f"{cmd}\r\n".encode(), f"{self._handle(cmd)}\r\n".encode(), b"\r\n"]

    def flush(self): ...
    def reset_input_buffer(self): ...
    def close(self): ...

    def readline(self) -> bytes:
        return self._queue.pop(0) if self._queue else b""


def run_session(fw: FakeFirmware, body=lambda board: None):
    with patch("fr3_gui.device.serial.Serial", return_value=fw):
        with MeasurementSession(port="COM_FAKE") as board:
            body(board)


def scramble(board):
    """What a sweep might leave behind."""
    board.lmx_tune(12e9)
    board.set_i_v(0.111)
    board.set_q_v(-0.222)
    board.set_iq_swap(True)
    board.set_tx_filter(0x00)


def test_get_persist_is_the_very_first_command():
    fw = FakeFirmware()
    run_session(fw)
    assert fw.commands[0] == "GET PERSIST"


def test_persist_is_off_during_the_sweep_and_on_after():
    fw = FakeFirmware()
    seen = {}
    run_session(fw, lambda board: seen.update(during=fw.persist))
    assert seen["during"] is False
    assert fw.persist is True
    assert fw.commands[:2] == ["GET PERSIST", "*IDN?"]
    assert fw.commands.index("SET PERSIST OFF") > fw.commands.index("*IDN?")


def test_sweep_changes_never_reach_flash_and_board_is_left_as_found():
    fw = FakeFirmware()
    original = dict(fw.live)
    run_session(fw, scramble)
    assert fw.live == original            # restored to what it was
    assert fw.flash == original           # and flash holds the original too


def test_configuration_is_restored_before_persist_is_switched_back_on():
    fw = FakeFirmware()
    run_session(fw, scramble)
    last_persist_on = len(fw.commands) - 1 - fw.commands[::-1].index("SET PERSIST ON")
    restore_tune = len(fw.commands) - 1 - fw.commands[::-1].index("LMX TUNE 20000000000")
    assert restore_tune < last_persist_on


def test_a_muted_or_external_lo_board_is_restored_too():
    fw = FakeFirmware()
    fw.live.update(lo="EXT", lmx_mute=True, clock="EXT", tx=0x2A, rx=0x1F)
    fw.flash = dict(fw.live)
    original = dict(fw.live)
    run_session(fw, scramble)
    assert fw.live == original
    assert fw.flash == original


def test_old_firmware_is_refused_and_nothing_else_is_sent():
    fw = FakeFirmware(has_persist=False)
    with pytest.raises(FirmwareError, match="does not have the PERSIST feature"):
        run_session(fw)
    assert fw.commands == ["GET PERSIST"]


def test_wrong_board_revision_is_refused_before_touching_persist():
    fw = FakeFirmware(idn="FR3 1CH REV1.1,STM32H573VIT6,FW1.00")
    with pytest.raises(FirmwareError, match="expected board"):
        run_session(fw)
    assert "SET PERSIST OFF" not in fw.commands
    assert fw.persist is True


def test_error_in_the_middle_of_a_sweep_still_restores_everything():
    fw = FakeFirmware()
    original = dict(fw.live)

    def boom(board):
        scramble(board)
        assert fw.persist is False
        raise RuntimeError("sweep failed")

    with pytest.raises(RuntimeError, match="sweep failed"):
        run_session(fw, boom)
    assert fw.persist is True
    assert fw.live == original
    assert fw.flash == original


def test_ctrl_c_still_restores_everything():
    fw = FakeFirmware()
    original = dict(fw.live)

    def interrupt(board):
        scramble(board)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_session(fw, interrupt)
    assert fw.persist is True
    assert fw.live == original
    assert fw.flash == original
