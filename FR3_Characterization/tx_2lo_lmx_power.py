"""TX LO and 2*LO at "TX-side FR3 RF Out" vs. LMX output power, input OFF (diagnostic, 2026-10-06).

    python tx_2lo_lmx_power.py [--lo-ghz 9] [--null-bias 0.0027,0.1538]

Cases (TX filter BYPASSED, IQ THRU): 1A = the given LO-null bias (held fixed while the drive changes), 2A = I_V = Q_V = 0.
LMX PWR 7 -> 0; at each step lock check, then LO and 2LO with the tx_lo_products.py analyzer settings (1 MHz span, no
averaging, RBW 10 kHz, 30 dB attenuation, peak search, continuous sweep ON). LMX PWR is set back to 7 and the board's
pre-run configuration restored on exit. Hookup: "TX-side FR3 RF Out" -> FR3 cable -> FieldFox; nothing into the TX input.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from results_layout import unit_dir
from spur_campaign import FF_HOST, restore_ff
from tx_lo_products import SPAN, read, setup_ff


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-ghz", type=float, default=9.0)
    ap.add_argument("--null-bias", default="0.0027,0.1538")
    ap.add_argument("--expect-unit", type=int, default=5)
    args = ap.parse_args()
    lo = args.lo_ghz * 1e9
    iv1, qv1 = (float(v) for v in args.null_bias.split(","))
    fr3c = CableLoss("fr3_cable")
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=SPAN) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        out = unit_dir(serial) / f"tx_2lo_lmx_power_{datetime.now():%Y%m%d_%H%M%S}.csv"
        orig = None
        try:
            orig = setup_ff(ff)
            ff.source_enable(False)
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            must(board.set_lmx_power(7), "LMX PWR 7")
            tune_and_lock(board, lo)
            must(board.set_iq_swap(False), "SET IQ THRU")
            must(board.set_tx_filter(0x00), "SET TXFILTER bypass")
            rows = []
            for case, iv, qv in (("1A", iv1, qv1), ("2A", 0.0, 0.0)):
                must(board.set_i_v(iv), "SET I_V")
                must(board.set_q_v(qv), "SET Q_V")
                print(f"\nCase {case}: I_V {iv:+.4f} V, Q_V {qv:+.4f} V, TX filter bypass, input OFF", flush=True)
                for pwr in range(7, -1, -1):
                    must(board.set_lmx_power(pwr), f"LMX PWR {pwr}")
                    time.sleep(SETTLE_S)
                    lock = board.get_lmx_lock()
                    row = {"case": case, "i_v": iv, "q_v": qv, "lmx_power": pwr, "lmx_lock": lock,
                           "lmx_temp_c": round(board.get_lmx_temperature_c(), 1)}
                    for name, f in (("LO", lo), ("2LO", 2 * lo)):
                        fx, p = read(ff, f)
                        row[f"{name}_dbm"] = round(p - fr3c.s21_db(fx), 2)
                    rows.append(row)
                    print(f"  LMX PWR {pwr}  {lock:9s}  LO {row['LO_dbm']:+7.2f} dBm   2LO {row['2LO_dbm']:+7.2f} dBm", flush=True)
            with open(out, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            print(f"\nSaved {out}")
        finally:
            board.set_lmx_power(7)
            off = restore_ff(ff, orig)
            print("LMX PWR back to 7; board pre-run configuration restored on exit. " +
                  ("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
