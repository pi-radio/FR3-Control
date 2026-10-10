"""Single-point RX NF measurement: FR1=2 GHz, FR3=8 GHz, low-side LO (LO=6 GHz).
Run with --step noise first (FR3 In terminated), then --step gain after
swapping the FieldFox source onto RX-side FR3 RF In."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from board import MeasurementSession
from cables import CableLoss
from fieldfox import FieldFox

FF_HOST = "192.168.137.61"
FR1_HZ = 2.0e9
FR3_HZ = 10.0e9
LO_HZ = FR3_HZ - FR1_HZ  # low-side
SOURCE_DBM = -40.0
RX_FILTER_BYPASS = 0x00
STATE_FILE = Path("_rx_nf_point_state.json")


def must(ok: bool, what: str) -> None:
    if not ok:
        raise RuntimeError(f"board rejected: {what}")


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def configure_board_rx(board) -> None:
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
    must(board.set_rx_filter(RX_FILTER_BYPASS), "SET RXFILTER bypass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", choices=("noise", "source-on", "gain"), required=True)
    args = parser.parse_args()

    fr1_cable = CableLoss("fr1_cable")
    fr3_cable = CableLoss("fr3_cable")
    s21_fr1 = fr1_cable.s21_db(FR1_HZ)
    s21_fr3 = fr3_cable.s21_db(FR3_HZ)

    state = load_state()

    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        print(f"Board: {board.get_idn()}  serial #{board.get_board_serial()}")
        configure_board_rx(board)
        print(f"Board configured: LO {LO_HZ/1e9:g} GHz {board.get_lmx_lock()}, "
              f"RX filter 0x{board.get_rx_filter():02X} (bypass), "
              f"LMX temp {board.get_lmx_temperature_c():.1f} C")

        ff.setup_spectrum_analyzer(ref_level_dbm=-30.0)
        ff.source_enable(False)
        # Noise step needs minimum attenuation for sensitivity (DUT noise is very weak).
        # Source-on/gain steps drive a real tone that can be strong at the FieldFox input
        # (already overloaded the ADC once at 0 dB) - use a much higher, fixed attenuation
        # there instead, the same way the project's existing TX gain scripts protect against
        # overload with a fixed attenuator rather than 0 dB.
        atten_db = 0.0 if args.step == "noise" else 20.0
        ff.set_attenuation(atten_db)
        print(f"FieldFox: SA mode, span {ff.span_hz/1e6:g} MHz, RBW {ff.rbw_hz/1e3:g} kHz, "
              f"attenuation {ff.attenuation_db:.0f} dB")

        try:
            if args.step == "noise":
                print("\n--- NOISE step: RX-side FR3 RF In must be 50-ohm terminated. "
                      "FieldFox source will stay OFF. ---")
                ff.tune(FR1_HZ)
                ff.write("CALC:MARK1:NOIS:STAT ON")
                ff.check("enable noise marker")

                n_reads = 10
                readings_dbm_hz = []
                for i in range(n_reads):
                    ff.wait_fresh_sweeps()  # continuous sweep (never INIT:CONT OFF / INIT:IMM)
                    y = float(ff.query("CALC:MARK1:Y?"))
                    readings_dbm_hz.append(y)
                    print(f"  sweep {i+1:2d}/{n_reads}: {y:8.2f} dBm/Hz")
                ff.check("read noise marker")
                ff.write("CALC:MARK1:NOIS:STAT OFF")
                ff.check("disable noise marker")

                # Average in linear power (mW/Hz), not naively averaging dB values.
                lin = [10 ** (y / 10.0) for y in readings_dbm_hz]
                mean_lin = sum(lin) / len(lin)
                noise_y = 10.0 * __import__("math").log10(mean_lin)
                spread = max(readings_dbm_hz) - min(readings_dbm_hz)

                noise_at_dut = noise_y - s21_fr1
                print(f"\n{n_reads} sweeps: min {min(readings_dbm_hz):.2f}, max {max(readings_dbm_hz):.2f} "
                      f"dBm/Hz (spread {spread:.2f} dB)")
                print(f"Mean (averaged in linear power): {noise_y:.2f} dBm/Hz")
                print(f"FR1 cable S21 @ {FR1_HZ/1e9:g} GHz: {s21_fr1:.3f} dB")
                print(f"Noise referred to board's RX-side FR1 IF Out connector: {noise_at_dut:.2f} dBm/Hz")

                state["noise_y_dbm_hz"] = noise_y
                state["noise_at_dut_dbm_hz"] = noise_at_dut
                state["s21_fr1_db"] = s21_fr1
                save_state(state)
                print(f"\nSaved to {STATE_FILE}. Next: swap the FieldFox source onto "
                      f"RX-side FR3 RF In (replacing the termination), then run --step gain.")

            elif args.step == "source-on":
                hold_s = 30
                print(f"\n--- SOURCE-ON step: enabling the tone and holding the board/FieldFox "
                      f"state for {hold_s} s so you can actually look at the display. ---")
                ff.set_ref_level(10.0)
                ff.source_configure(FR3_HZ, SOURCE_DBM)
                ff.source_enable(True)
                time.sleep(0.3)
                print(f"Source ON: {SOURCE_DBM:.1f} dBm at {FR3_HZ/1e9:g} GHz into "
                      f"RX-side FR3 RF In. Reference level +10 dBm, nominal {FR1_HZ/1e9:g} GHz, "
                      f"span {ff.span_hz/1e6:g} MHz.\n"
                      f"Using the project's real measure_at() every 2s (fresh triggered sweep, "
                      f"peak search, then re-centers and searches again if the tone is far from "
                      f"center) - not a free-running display, so it correctly tracks drift "
                      f"between the FieldFox's and the board's independent clocks:")
                n_updates = hold_s // 2
                for i in range(n_updates):
                    r = ff.measure_at(FR1_HZ)
                    print(f"  [{i+1:2d}/{n_updates}] peak at {r.freq_hz/1e9:.6f} GHz "
                          f"(nominal {FR1_HZ/1e9:g}, offset {(r.freq_hz-FR1_HZ)/1e3:+.2f} kHz), "
                          f"{r.power_dbm:+7.2f} dBm")
                    time.sleep(1.5)
                print("Window closed - switching source back off and restoring instruments.")

            else:  # gain
                print("\n--- GAIN step: FieldFox source must be connected to "
                      "RX-side FR3 RF In (termination removed). ---")
                # The noise-step reference level (-30 dBm) is far too low for this strong a
                # tone (expected well above 0 dBm at the FieldFox) - raise it first so the
                # peak is actually visible on-screen and nothing is clipped/overloaded.
                ref_level = 10.0
                ff.set_ref_level(ref_level)
                print(f"Reference level raised to {ref_level:+.0f} dBm before driving the tone.")
                ff.source_configure(FR3_HZ, SOURCE_DBM)
                ff.source_enable(True)
                time.sleep(0.3)
                r = ff.measure_at(FR1_HZ)
                ff.source_enable(False)

                p_in_at_dut = SOURCE_DBM + s21_fr3
                p_out_at_dut = r.power_dbm - s21_fr1
                gain_db = p_out_at_dut - p_in_at_dut
                print(f"\nFieldFox source: {SOURCE_DBM:.1f} dBm at {FR3_HZ/1e9:g} GHz")
                print(f"FR3 cable S21 @ {FR3_HZ/1e9:g} GHz: {s21_fr3:.3f} dB -> "
                      f"in at DUT connector: {p_in_at_dut:.2f} dBm")
                print(f"FieldFox reads: {r.power_dbm:.2f} dBm at {r.freq_hz/1e9:.4f} GHz "
                      f"(nominal {FR1_HZ/1e9:g} GHz)")
                print(f"FR1 cable S21 @ {FR1_HZ/1e9:g} GHz: {s21_fr1:.3f} dB -> "
                      f"out at DUT connector: {p_out_at_dut:.2f} dBm")
                print(f"\nConversion gain (corrected): {gain_db:.2f} dB")

                if "noise_at_dut_dbm_hz" not in state:
                    print("\n*** No saved noise reading found - run --step noise first. "
                          "Gain-only result not combined into NF.")
                else:
                    noise_at_dut = state["noise_at_dut_dbm_hz"]
                    nf_db = noise_at_dut - gain_db + 174.0
                    print(f"\nUsing saved cold-noise reading: {noise_at_dut:.2f} dBm/Hz")
                    print(f"NF = {noise_at_dut:.2f} - {gain_db:.2f} + 174 = {nf_db:.2f} dB")
                state["gain_db"] = gain_db
                state["gain_measured_ff_dbm"] = r.power_dbm
                save_state(state)
        finally:
            ff.source_enable(False)
            ff.restore_instrument_state()
            time.sleep(0.1)
            print(f"\nFieldFox source OFF confirmed: {not ff.source_state()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
