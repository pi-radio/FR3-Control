"""Does the TX output 2LO depend on the I/Q bias when the filter blocks the RF path? (diagnostic, 2026-10-06)

    python tx_2lo_vs_bias.py [--lo-ghz 9] [--tx-filter 0x39] [--start 0.0026,0.0744]

LO 9 GHz, LMX PWR 0, IQ THRU, input OFF, TX filter fixed (default 0x39: 64.8 dB in-board rejection at 18 GHz). Null
the LO with that state, then step I_V and Q_V away from the null one axis at a time (+-1, 2, 4, 8, 16, 32, 64 mV),
reading LO and 2LO at "TX-side FR3 RF Out" (1 MHz span, RBW 10 kHz, 30 dB attenuation, no averaging, peak search).
Points with LO > -30 dBm at the output are flagged (the amplifiers could then generate 2LO from the LO themselves).
Results: results/unit_<n>/tx_2lo_vs_bias_<stamp>.csv. Board restored on exit.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime

import lo_null
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from lo_null import Nuller
from results_layout import unit_dir
from spur_campaign import FF_HOST, restore_ff
from tx_2lo_vs_filter_state import reading_setup
from tx_lo_products import read

STEPS_MV = (1, 2, 4, 8, 16, 32, 64)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-ghz", type=float, default=9.0)
    ap.add_argument("--tx-filter", default="0x39")
    ap.add_argument("--lmx-power", type=int, default=0)
    ap.add_argument("--start", default="0.0026,0.0744")
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--max-temp-c", type=float, default=92.0, help="stop the sweep above this LMX temperature")
    ap.add_argument("--note", default="", help="free text stored in the file name, e.g. out_of_case")
    args = ap.parse_args()
    lo = args.lo_ghz * 1e9
    bits = int(args.tx_filter, 16)
    fr3c = CableLoss("fr3_cable")
    start = tuple(float(v) for v in args.start.split(","))
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{args.note}" if args.note else ""
        out = unit_dir(serial) / f"tx_2lo_vs_bias_{stamp}{suffix}.csv"
        orig, rows = None, []
        try:
            ff.write("*CLS")
            ff.select_mode("SA")
            orig = int(float(ff.query("SENS:SWE:POIN?")))
            ff.source_enable(False)
            for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF"):
                ff.write(c)
            ff._saved_attenuation = (ff.query("SENS:POW:ATT:AUTO?") in ("1", "ON"), ff.attenuation_db)
            ff.write("CALC:MARK1:STAT NORM")
            ff.write("INIT:CONT ON")
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            must(board.set_lmx_power(args.lmx_power), f"LMX PWR {args.lmx_power}")
            tune_and_lock(board, lo)
            must(board.set_iq_swap(False), "SET IQ THRU")
            must(board.set_tx_filter(bits), f"SET TXFILTER 0x{bits:02X}")
            must(board.set_i_v(start[0]), "SET I_V")
            must(board.set_q_v(start[1]), "SET Q_V")
            time.sleep(SETTLE_S)
            ff.set_span(lo_null.NULL_SPAN_HZ)
            nuller = Nuller(ff, board, lo, fr3c, unit_dir(serial) / "lo_null_single" / f"lo_{args.lo_ghz:07.3f}GHz_0x{bits:02X}_{stamp}.csv")
            try:
                res = nuller.run(start)
            finally:
                nuller.close()
            i0, q0 = res.i_v, res.q_v
            print(f"Null with 0x{bits:02X}: {res.level_dbm:.1f} dBm at I_V {i0:+.4f} V, Q_V {q0:+.4f} V ({res.outcome})", flush=True)
            reading_setup(ff)
            points = [("null", 0.0, 0.0)]
            for axis in ("I", "Q"):
                for mv in STEPS_MV:
                    for sgn in (-1, +1):
                        d = sgn * mv / 1000
                        points.append((axis, d if axis == "I" else 0.0, d if axis == "Q" else 0.0))
            points.append(("zero", -i0, -q0))                      # absolute I_V = Q_V = 0 V
            points.append(("null_end", 0.0, 0.0))                  # the null point again, to see drift during the run
            for axis, di, dq in points:
                must(board.set_i_v(i0 + di), "SET I_V")
                must(board.set_q_v(q0 + dq), "SET Q_V")
                time.sleep(SETTLE_S)
                fl, pl = read(ff, lo)
                f2, p2 = read(ff, 2 * lo)
                lo_dbm, two = pl - fr3c.s21_db(fl), p2 - fr3c.s21_db(f2)
                row = {"axis": axis, "di_mv": round(di * 1000, 1), "dq_mv": round(dq * 1000, 1),
                       "i_v": round(i0 + di, 5), "q_v": round(q0 + dq, 5), "lo_dbm": round(lo_dbm, 2),
                       "two_lo_dbm": round(two, 2), "lo_above_minus30": int(lo_dbm > -30),
                       "lmx_temp_c": round(board.get_lmx_temperature_c(), 1)}
                if row["lmx_temp_c"] > args.max_temp_c:
                    print(f"*** LMX at {row['lmx_temp_c']} C > {args.max_temp_c} C: stopping the sweep ***", flush=True)
                    rows.append(row)
                    break
                rows.append(row)
                print(f"  {axis:8s} {row['lmx_temp_c']:5.1f} C  dI {di * 1000:+6.1f} mV  dQ {dq * 1000:+6.1f} mV | LO {lo_dbm:+7.1f} dBm | 2LO {two:+7.1f} dBm"
                      + ("   (LO > -30 dBm)" if lo_dbm > -30 else ""), flush=True)
            with open(out, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            print(f"Saved {out}")
        finally:
            ff.write("TRAC1:TYPE CLRW")
            off = restore_ff(ff, orig)
            print("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***")
    return 0


if __name__ == "__main__":
    sys.exit(main())
