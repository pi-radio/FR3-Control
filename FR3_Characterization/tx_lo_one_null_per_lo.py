"""What would a one-null-per-LO calibration deliver? (user, 2026-10-07)

    python tx_lo_one_null_per_lo.py --lo-ghz 10 --ref 0x3F --out-dir results/unit_005/<date>

LMX drive 0, IQ THRU, FieldFox source OFF. Null the LO with the reference filter state engaged (lo_null.Nuller). Then for
every filter state used at that LO (100 MHz grid, tx_null_filter_state_test.states_at), back to back, so drift cancels:
  a) the reference null's bias  -> LO leakage a one-null-per-LO table would deliver
  b) I_V = Q_V = 0 V             -> uncalibrated
  c) the state's own fresh null (warm-started from the reference null) -> best case
The reference state is re-read with its own bias at the end, to show the drift over the run.
Readings at "TX-side FR3 RF Out": 1 MHz span, RBW 10 kHz, 30 dB att, no averaging, peak search (FR3 cable corrected).
Output: tx_lo_one_null_per_lo_<stamp>_LO<lo>.csv. Board restored on exit.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import lo_null
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from lo_null import Nuller
from spur_campaign import FF_HOST, restore_ff
from tx_2lo_vs_filter_state import reading_setup
from tx_lo_products import read
from tx_null_filter_state_test import BAND_NAME, states_at


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-ghz", type=float, default=10.0)
    ap.add_argument("--ref", default="auto", help="reference filter byte, or 'auto' = the used state with the least model loss at the LO")
    ap.add_argument("--lmx-power", type=int, default=0)
    ap.add_argument("--start", default="0.0058,0.079")
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--with-zero", action="store_true", help="also read each state at I_V = Q_V = 0 V (extra; ask the user)")
    ap.add_argument("--with-own", action="store_true", help="also null each state itself (slow extra; ask the user)")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    lo = args.lo_ghz * 1e9
    if args.ref == "auto":
        import numpy as np
        from rx_nf_campaign import get_response
        ref = max(states_at(args.lo_ghz), key=lambda b: float(np.interp(lo, get_response(b).freq_hz, get_response(b).s21_db)))
    else:
        ref = int(args.ref, 16)
    fr3c = CableLoss("fr3_cable")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.out_dir) / f"tx_lo_one_null_per_lo_{stamp}_LO{args.lo_ghz:g}.csv"
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
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
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            must(board.set_lmx_power(args.lmx_power), f"LMX PWR {args.lmx_power}")
            must(board.set_iq_swap(False), "SET IQ THRU")
            tune_and_lock(board, lo)

            def null(bits: int, start: tuple[float, float]):
                must(board.set_tx_filter(bits), "SET TXFILTER")
                time.sleep(SETTLE_S)
                ff.set_span(lo_null.NULL_SPAN_HZ)
                n = Nuller(ff, board, lo, fr3c, Path(f"{out.with_suffix('')}_search_0x{bits:02X}.csv"))
                try:
                    res = n.run(start)
                finally:
                    n.close()
                reading_setup(ff)
                return res.i_v, res.q_v

            def level(bits: int, i_v: float, q_v: float) -> float:
                must(board.set_tx_filter(bits), "SET TXFILTER")
                must(board.set_i_v(i_v), "SET I_V")
                must(board.set_q_v(q_v), "SET Q_V")
                time.sleep(SETTLE_S)
                f, p = read(ff, lo)
                return p - fr3c.s21_db(f)

            ri, rq = null(ref, tuple(float(v) for v in args.start.split(",")))
            ref_start = level(ref, ri, rq)
            print(f"reference 0x{ref:02X} null: I {ri:+.5f} Q {rq:+.5f} -> {ref_start:+.1f} dBm", flush=True)
            for bits in states_at(args.lo_ghz):
                a = level(bits, ri, rq)
                b = level(bits, 0.0, 0.0) if args.with_zero else float("nan")
                oi, oq = null(bits, (ri, rq)) if args.with_own else (float("nan"), float("nan"))
                c = level(bits, oi, oq) if args.with_own else float("nan")
                row = {"lo_ghz": args.lo_ghz, "lmx_power": args.lmx_power, "tx_filter": f"0x{bits:02X}", "band": BAND_NAME[bits >> 4],
                       "ref_filter": f"0x{ref:02X}", "lo_dbm_ref_null": round(a, 2), "lo_dbm_zero_bias": round(b, 2),
                       "lo_dbm_own_null": round(c, 2), "own_i_v": round(oi, 5), "own_q_v": round(oq, 5),
                       "bias_distance_mv": round(1000 * ((oi - ri) ** 2 + (oq - rq) ** 2) ** 0.5, 2),
                       "lmx_temp_c": round(board.get_lmx_temperature_c(), 1)}
                new = not out.exists()
                with open(out, "a", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(row))
                    if new:
                        w.writeheader()
                    w.writerow(row)
                print(f"  0x{bits:02X} {BAND_NAME[bits >> 4]}: reference bias -> LO {a:+7.1f} dBm"
                      + (f" | 0 V {b:+7.1f}" if args.with_zero else "")
                      + (f" | own null {c:+7.1f} dBm (bias {row['bias_distance_mv']} mV from ref)" if args.with_own else ""), flush=True)
            ref_end = level(ref, ri, rq)
            print(f"reference 0x{ref:02X} re-read with its own bias at the end: {ref_end:+.1f} dBm (start {ref_start:+.1f})", flush=True)
        finally:
            ff.write("TRAC1:TYPE CLRW")
            off = restore_ff(ff, orig)
            print(f"Saved {out}\n" + ("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
