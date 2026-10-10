"""LO leakage at the RF output versus LO frequency, with the desired tone alongside for a leakage-to-carrier ratio.

    python lo_leakage.py --campaign lo_leakage_20260923 [--lo-start-ghz 7] [--lo-stop-ghz 22.5] [--lo-step-ghz 0.1]

At every LO (I/Q bias from the LO-null table, TX filter bypass, IQ THRU and then SWAP):
  1. FieldFox source OFF: read the LO leakage at RF = LO (marker on a 1 MHz span, re-centered on the peak).
     A second read 50 MHz above the LO (nothing there) is the local analyzer noise floor.
  2. IF tone ON (default 2 GHz, -40 dBm): read the desired tone (THRU: LO + IF, SWAP: LO - IF).
  3. Leakage-to-carrier = LO leakage - desired tone (dBc).
Values are cable-corrected to the board's connectors. Analyzer attenuation 20 dB, reference +10 dBm (as in lo_map.py).
Results: results/unit_<serial>/<campaign>/lo_leakage.csv. The FieldFox source is always switched off and read back."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime

import numpy as np

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import configure_board, must
from fieldfox import SETTLE_S, FieldFox
from results_layout import unit_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--lo-start-ghz", type=float, default=7.0)
    parser.add_argument("--lo-stop-ghz", type=float, default=22.5)
    parser.add_argument("--lo-step-ghz", type=float, default=0.1)
    parser.add_argument("--if-ghz", type=float, default=2.0)
    parser.add_argument("--drive-dbm", type=float, default=-40.0)
    parser.add_argument("--attenuation-db", type=float, default=20.0)
    parser.add_argument("--ref-level-dbm", type=float, default=10.0)
    parser.add_argument("--host", default="192.168.137.61")
    parser.add_argument("--port", default=None)
    args = parser.parse_args()

    f_if = args.if_ghz * 1e9
    n = int(round((args.lo_stop_ghz - args.lo_start_ghz) / args.lo_step_ghz)) + 1
    los = [int(round((args.lo_start_ghz + i * args.lo_step_ghz) * 1e9)) for i in range(n)]
    cable_if, cable_rf = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    s21_if = cable_if.s21_db(f_if)
    for lo in los:
        for f in (lo, lo + 50e6, lo + f_if, lo - f_if):
            cable_rf.s21_db(f)

    t0 = time.monotonic()
    with MeasurementSession(port=args.port) as board, FieldFox(args.host) as ff:
        serial = board.get_board_serial()
        outdir = unit_dir(serial) / args.campaign
        outdir.mkdir(parents=True, exist_ok=True)
        path = outdir / "lo_leakage.csv"
        done = set()
        if path.exists():
            done = {int(float(r["lo_hz"])) for r in csv.DictReader(open(path, newline=""))}
        todo = [lo for lo in los if lo not in done]
        print(f"Unit #{serial}: {len(los)} LOs, {len(todo)} to do. {outdir}")
        try:
            ff.setup_spectrum_analyzer(ref_level_dbm=args.ref_level_dbm)
            ff.source_enable(False)
            ff.set_attenuation(args.attenuation_db)
            new = not path.exists()
            with open(path, "a", newline="") as fh:
                w = csv.writer(fh)
                if new:
                    w.writerow(["lo_hz", "iq", "lo_leak_dbm", "lo_leak_marker_offset_hz", "noise_floor_dbm", "desired_rf_hz",
                                "desired_dbm", "leak_minus_desired_dbc", "leak_above_floor_db", "lmx_temp_c"])
                for k, lo in enumerate(todo):
                    configure_board(board, float(lo), "upper")
                    for iq, swap, rf in (("THRU", False, lo + f_if), ("SWAP", True, lo - f_if)):
                        must(board.set_iq_swap(swap), f"SET IQ {iq}")
                        ff.source_enable(False)
                        time.sleep(SETTLE_S)
                        leak = ff.measure_at(float(lo))
                        floor = ff.measure_at(lo + 50e6, recenter=False)
                        ff.source_configure(f_if, args.drive_dbm)
                        ff.source_enable(True)
                        time.sleep(SETTLE_S)
                        des = ff.measure_at(float(rf))
                        ff.source_enable(False)
                        leak_c = leak.power_dbm - cable_rf.s21_db(lo)
                        des_c = des.power_dbm - cable_rf.s21_db(rf)
                        w.writerow([lo, iq, f"{leak_c:.2f}", f"{leak.freq_hz - lo:.0f}", f"{floor.power_dbm - cable_rf.s21_db(lo + 50e6):.2f}",
                                    rf, f"{des_c:.2f}", f"{leak_c - des_c:.2f}", f"{leak.power_dbm - floor.power_dbm:.2f}",
                                    f"{board.get_lmx_temperature_c():.1f}"])
                    fh.flush()
                    if k % 10 == 0:
                        print(f"  LO {lo / 1e9:6.2f} GHz [{k + 1}/{len(todo)}]  leak {leak_c:+.1f} dBm  desired {des_c:+.1f} dBm  "
                              f"(elapsed {time.monotonic() - t0:.0f} s)")
                    if time.monotonic() - t0 > 520:
                        print("Time budget used; stopping cleanly. Re-run the same command to continue.")
                        break
                if ff.errors():
                    print("FieldFox errors:", ff.errors())
        finally:
            ff.source_enable(False)
            ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            off = not ff.source_state()
            print("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON!")
    print("Board configuration restored, flash persistence back ON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
