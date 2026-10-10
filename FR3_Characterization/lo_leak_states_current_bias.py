"""Read the TX LO leakage in every usable filter state at the CURRENT LO and I/Q bias, without changing the bias
(user, 2026-10-08).

    python lo_leak_states_current_bias.py --out-dir results/unit_005/<date> [--note ...]

States: every optimal filter of the 100 MHz grid at the current LO (tx_null_filter_state_test.states_at). LO read at
"TX-side FR3 RF Out" (1 MHz span, RBW 10 kHz, 30 dB att, no averaging, peak search; FR3 cable corrected). FieldFox
source OFF. PERSIST off while switching; the original filter state is put back and PERSIST restored at the end.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from board import Board, OPERATING_TIMEOUT_S, find_board_ports
from cables import CableLoss
from conversion_gain_small_case import must
from fieldfox import SETTLE_S, FieldFox
from rx_nf_campaign import get_response
from spur_campaign import FF_HOST
from tx_2lo_vs_filter_state import reading_setup
from tx_lo_products import read
from tx_null_filter_state_test import BAND_NAME, states_at


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--note", default="")
    args = ap.parse_args()
    fr3c = CableLoss("fr3_cable")
    b = Board(find_board_ports()[0], timeout=OPERATING_TIMEOUT_S)
    persist = b.get_persist()
    snap = b.snapshot()
    lo, ref = snap["lmx_freq_hz"], snap["tx_filter"]
    out = Path(args.out_dir) / f"lo_leak_states_{datetime.now():%Y%m%d_%H%M%S}_LO{lo / 1e9:g}{('_' + args.note) if args.note else ''}.csv"
    try:
        with FieldFox(FF_HOST, span_hz=1e6) as ff:
            ff.source_enable(False)
            ff.write("CALC:MARK1:STAT NORM")
            ff.write("INIT:CONT ON")
            reading_setup(ff)
            must(b.set_persist(False), "PERSIST OFF")
            print(f"LO {lo / 1e9:g} GHz, bias I_V {snap['i_v']:+.5f} V, Q_V {snap['q_v']:+.5f} V (unchanged), current filter 0x{ref:02X}")
            for bits in states_at(lo / 1e9):
                must(b.set_tx_filter(bits), "SET TXFILTER")
                time.sleep(SETTLE_S)
                f, p = read(ff, lo)
                lv = p - fr3c.s21_db(f)
                r = get_response(bits)
                row = {"lo_ghz": lo / 1e9, "tx_filter": f"0x{bits:02X}", "band": BAND_NAME[bits >> 4],
                       "model_s21_at_lo_db": round(float(np.interp(lo, r.freq_hz, r.s21_db)), 1), "is_null_state": int(bits == ref),
                       "i_v": snap["i_v"], "q_v": snap["q_v"], "lo_dbm": round(lv, 2), "lmx_temp_c": round(b.get_lmx_temperature_c(), 1)}
                new = not out.exists()
                with open(out, "a", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(row))
                    if new:
                        w.writeheader()
                    w.writerow(row)
                print(f"  0x{bits:02X} {BAND_NAME[bits >> 4]} model loss {row['model_s21_at_lo_db']:6.1f} dB -> LO {lv:+7.1f} dBm"
                      + ("   (state the null was found in)" if bits == ref else ""), flush=True)
            ff.write(f"SENS:FREQ:CENT {lo:.0f}")
    finally:
        b.set_tx_filter(ref)
        b.set_persist(persist)
        print(f"filter back to 0x{ref:02X}, PERSIST {b.get_persist()}; saved {out}")
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
