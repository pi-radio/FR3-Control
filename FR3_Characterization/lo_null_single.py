"""Re-null the TX LO leakage at ONE LO frequency with the same algorithm as the calibration tables (lo_null.Nuller), and
compare with the cold/hot tables (diagnostic, 2026-10-06).

    python lo_null_single.py --lo-ghz 9 [--expect-unit 5]

Board as in the calibration (conversion_gain_small_case.configure_board): internal LO, LMX PWR 7, IQ THRU, TX filter
bypass; FieldFox source OFF. FieldFox set up WITHOUT INIT:CONT OFF (never sent; the Nuller keeps continuous sweep ON).
Warm-started from the tables' bias at the current LMX temperature. Hookup: "TX-side FR3 RF Out" -> FR3 cable -> FieldFox;
nothing into "TX-side FR1 IF In". The search log: results/unit_<n>/lo_null_single/lo_<GHz>_<stamp>.csv. On exit the
board's pre-run configuration is restored (MeasurementSession).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

import lo_null
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import configure_board, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from lo_null import Nuller
from results_layout import unit_dir
from spur_campaign import FF_HOST, LoNull, restore_ff


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-ghz", type=float, required=True)
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--tx-filter", default="0x00", help="TX filter byte during the search (calibration used 0x00)")
    ap.add_argument("--lmx-power", type=int, default=7, help="LMX2820 OUTx_PWR during the search (calibration used 7)")
    ap.add_argument("--start", default="", help="warm-start bias I_V,Q_V (V); default: the tables at the LMX temperature")
    args = ap.parse_args()
    f_lo = args.lo_ghz * 1e9
    cable_rf = CableLoss("fr3_cable")
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        outdir = unit_dir(serial) / "lo_null_single"
        outdir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        orig = None
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
            configure_board(board, f_lo, "upper")                 # LO INT, PWR 7, tune+lock, GUI-table bias, IQ THRU, bypass
            temp = board.get_lmx_temperature_c()
            start = (tuple(float(v) for v in args.start.split(",")) if args.start
                     else LoNull(serial).bias(f_lo, temp))
            board.set_i_v(start[0])
            board.set_q_v(start[1])
            board.set_lmx_power(args.lmx_power)
            tune_and_lock(board, f_lo)
            tx_bits = int(args.tx_filter, 16)
            board.set_tx_filter(tx_bits)
            time.sleep(SETTLE_S)
            ff.set_span(lo_null.NULL_SPAN_HZ)
            print(f"Unit #{serial}: LO {args.lo_ghz:g} GHz, LMX {board.get_lmx_lock()} at {temp:.1f} C; warm start from the "
                  f"tables' bias I_V {start[0]:+.4f} V, Q_V {start[1]:+.4f} V", flush=True)
            nuller = Nuller(ff, board, f_lo, cable_rf, outdir / f"lo_{args.lo_ghz:07.3f}GHz_{stamp}.csv")
            try:
                res = nuller.run(start)
            finally:
                nuller.close()
            lock = board.get_lmx_lock()
            summary = {"time": stamp, "unit": serial, "lo_hz": f_lo, "outcome": res.outcome, "lmx_lock": lock,
                       "i_v": res.i_v, "q_v": res.q_v, "level_dbm_at_board": res.level_dbm, "lmx_temp_c": res.lmx_temp_c,
                       "start_bias_i_v": start[0], "start_bias_q_v": start[1], "tx_filter": args.tx_filter, "lmx_power": args.lmx_power, "warm_start": res.warm_start,
                       "start_level_dbm": res.start_dbm, "iterations": res.iterations, "refits": res.refits}
            (outdir / f"lo_{args.lo_ghz:07.3f}GHz_{stamp}.json").write_text(json.dumps(summary, indent=2, default=str))
            print(f"\nRESULT: {res.outcome}; null at I_V {res.i_v:+.4f} V, Q_V {res.q_v:+.4f} V -> LO leakage "
                  f"{res.level_dbm:.1f} dBm at the board (LMX {lock}, {res.lmx_temp_c:.1f} C)")
            print(f"        start bias (TX filter {args.tx_filter}): I_V {start[0]:+.4f} V, Q_V {start[1]:+.4f} V (start level {res.start_dbm:.1f} dBm); "
                  f"shift {1000 * (res.i_v - start[0]):+.1f} / {1000 * (res.q_v - start[1]):+.1f} mV")
        finally:
            ff.write("TRAC1:TYPE CLRW")
            off = restore_ff(ff, orig)
            print("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***")
            print("(Board configuration restored to its pre-run state on exit.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
