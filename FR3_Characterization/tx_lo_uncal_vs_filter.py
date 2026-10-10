"""Uncalibrated TX LO leakage (I_V = Q_V = 0 V) vs TX filter state at one LO, for several LMX drives (user, 2026-10-07).

    python tx_lo_uncal_vs_filter.py --lo-ghz 10 --drives 0,4,7 --out-dir results/unit_005/<date>

Filter states: every optimal filter of the 100 MHz grid at that LO (FR1 0.7-4.0 GHz in 100 MHz steps, both sidebands,
FR3 6-24 GHz; tx_null_filter_state_test.states_at). IQ THRU, FieldFox source OFF. LO read at "TX-side FR3 RF Out"
(1 MHz span, RBW 10 kHz, 30 dB att, no averaging, peak search; FR3 cable corrected). Also stored: the filter model's
S21 at the LO. Output: tx_lo_uncal_vs_filter_<stamp>.csv. Board restored on exit (MeasurementSession).
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from rx_nf_campaign import get_response
from spur_campaign import FF_HOST, restore_ff
from tx_2lo_vs_filter_state import reading_setup
from tx_lo_products import read
from tx_null_filter_state_test import BAND_NAME, states_at


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-ghz", type=float, default=10.0)
    ap.add_argument("--drives", default="0,4,7")
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    lo = args.lo_ghz * 1e9
    states = states_at(args.lo_ghz)
    fr3c = CableLoss("fr3_cable")
    out = Path(args.out_dir) / f"tx_lo_uncal_vs_filter_{datetime.now():%Y%m%d_%H%M%S}_LO{args.lo_ghz:g}.csv"
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
            reading_setup(ff)
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            must(board.set_iq_swap(False), "SET IQ THRU")
            must(board.set_i_v(0.0), "SET I_V 0")
            must(board.set_q_v(0.0), "SET Q_V 0")
            for drive in (int(d) for d in args.drives.split(",")):
                must(board.set_lmx_power(drive), f"LMX PWR {drive}")
                tune_and_lock(board, lo)
                for bits in states:
                    must(board.set_tx_filter(bits), "SET TXFILTER")
                    time.sleep(SETTLE_S)
                    f, p = read(ff, lo)
                    lv = p - fr3c.s21_db(f)
                    r = get_response(bits)
                    row = {"lo_ghz": args.lo_ghz, "lmx_power": drive, "tx_filter": f"0x{bits:02X}", "band": BAND_NAME[bits >> 4],
                           "filter_model_s21_at_lo_db": round(float(np.interp(lo, r.freq_hz, r.s21_db)), 1),
                           "lo_dbm": round(lv, 2), "lmx_temp_c": round(board.get_lmx_temperature_c(), 1)}
                    new = not out.exists()
                    with open(out, "a", newline="") as fh:
                        w = csv.DictWriter(fh, fieldnames=list(row))
                        if new:
                            w.writeheader()
                        w.writerow(row)
                    print(f"  drive {drive}  0x{bits:02X} {BAND_NAME[bits >> 4]}  model S21@LO {row['filter_model_s21_at_lo_db']:6.1f} dB"
                          f"  ->  LO {lv:+7.2f} dBm", flush=True)
        finally:
            ff.write("TRAC1:TYPE CLRW")
            off = restore_ff(ff, orig)
            print(f"Saved {out}\n" + ("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
