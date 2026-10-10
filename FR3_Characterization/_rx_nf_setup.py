"""Reconfigure the FieldFox and the Pi-Radio board from scratch for the RX
sensitivity/NF measurement. Does not take any data -- just establishes a
known, clean state on both instruments and reports it back.

RX-side FR3 RF In is assumed terminated (50 ohm, cold source); FieldFox RF
input is assumed connected to RX-side FR1 IF Out."""
from __future__ import annotations

import sys
import time

from board import MeasurementSession
from fieldfox import FieldFox

FF_HOST = "192.168.137.61"
LO_HZ = 12.0e9  # representative point; will match the RX gain sweep grid for the real run


def must(ok: bool, what: str) -> None:
    if not ok:
        raise RuntimeError(f"board rejected: {what}")


def main() -> int:
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        print(f"Board *IDN?: {board.get_idn()}")
        print(f"Board serial: {board.get_board_serial()}")

        must(board.set_clock_internal(True), "SET CLOCK INT")
        must(board.set_lo_internal(True), "SET LO INT")
        must(board.set_lmx_power(7), "LMX PWR 7")
        must(board.lmx_tune(LO_HZ), f"LMX TUNE {LO_HZ:.0f}")
        for _ in range(40):
            if board.get_lmx_lock() == "LOCKED":
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("LMX not LOCKED after tune")
        rx_filter_before = board.get_rx_filter()
        print(f"RX filter read back as: 0x{rx_filter_before:02X}")

        print(f"\nBoard configured: LMX {board.get_lmx_freq_hz()/1e9:g} GHz "
              f"{board.get_lmx_lock()}, clock INT, LO INT, RX filter 0x{board.get_rx_filter():02X}")

        print("\nFieldFox: *IDN? ->", ff.identify())
        ff.setup_spectrum_analyzer(ref_level_dbm=-30.0)
        ff.source_enable(False)
        ff.set_attenuation(0.0)
        print(f"FieldFox configured: SA mode, span {ff.span_hz/1e6:g} MHz, "
              f"RBW {ff.rbw_hz/1e3:g} kHz, attenuation {ff.attenuation_db:.0f} dB, "
              f"source OFF (confirmed: {ff.source_state()})")

        # Correct syntax from SYST:HELP:HEAD?: :CALCulate:MARKer{1:6}:NOISe[:STATe]
        print("\nEnabling marker 1 noise mode (CALC:MARK1:NOIS:STAT ON)...")
        ff.write("CALC:MARK1:NOIS:STAT ON")
        ff.check("enable noise marker")
        ff.tune(LO_HZ)
        ff.wait_fresh_sweeps()  # continuous sweep (never INIT:CONT OFF / INIT:IMM)
        noise_y = float(ff.query("CALC:MARK1:Y?"))
        print(f"  Noise marker at {LO_HZ/1e9:g} GHz reads: {noise_y:.2f} dBm/Hz")
        ff.check("read noise marker")
        ff.write("CALC:MARK1:NOIS:STAT OFF")
        ff.check("disable noise marker")
    print("\nDone. Board and FieldFox restored/closed cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
