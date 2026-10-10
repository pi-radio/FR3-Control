"""Consistency check of the two-path model of the TX LO leakage (analysis only, 2026-10-08).

    python analyze_two_path_model.py <lo_cal_grid_*_states.csv>

Model: output LO = A + B, A = m * S21(state) * G (mixer leakage through the AM3153 and the post-filter gain), B = a
post-filter component independent of the filter state. The reference null sets A_ref = -B, so with that bias in another
state x:   |output_x| = |B| * |1 - S21_x / S21_ref|   (complex S21 at the LO from the AM3153 Touchstone files).
|B| per LO is estimated from that LO's most strongly blocking state (model loss >= BLOCK_DB, where |1 - r| ~ 1); LOs
without one are skipped. The prediction is compared with the measured reading for every other non-reference state.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from analyze_null_vs_filter_s11 import at, sparams

BLOCK_DB = 40.0


def main() -> None:
    by_lo = defaultdict(list)
    for r in csv.DictReader(open(sys.argv[1], newline="")):
        by_lo[float(r["lo_ghz"])].append(r)
    cache, rows = {}, []
    for lo, rs in sorted(by_lo.items()):
        ref = next(r for r in rs if r["is_reference"] == "1")
        s21 = {}
        for r in rs:
            b = int(r["tx_filter"], 16)
            if b not in cache:
                cache[b] = sparams(b)
            f, s = cache[b]
            s21[r["tx_filter"]] = at(f, s["S21"], lo * 1e9)
        blocking = [r for r in rs if float(r["model_s21_at_lo_db"]) <= -BLOCK_DB]
        if not blocking:
            continue
        bref = min(blocking, key=lambda r: float(r["model_s21_at_lo_db"]))       # the most strongly blocking state
        rb = s21[bref["tx_filter"]] / s21[ref["tx_filter"]]
        b_dbm = float(bref["lo_dbm_ref_bias"]) - 20 * np.log10(abs(1 - rb))      # |B| from that state
        for r in rs:
            if r is ref or r is bref:
                continue
            ratio = s21[r["tx_filter"]] / s21[ref["tx_filter"]]
            pred = b_dbm + 20 * np.log10(max(abs(1 - ratio), 1e-6))
            meas = float(r["lo_dbm_ref_bias"])
            rows.append((lo, r["tx_filter"], ref["tx_filter"], float(r["model_s21_at_lo_db"]), abs(ratio), pred, meas, meas - pred))
    err = np.array([x[-1] for x in rows])
    loss = np.array([x[3] for x in rows])
    print(f"{len(rows)} readings at {len({x[0] for x in rows})} LOs (LOs with a blocking state >= {BLOCK_DB:g} dB)")
    print(f"measured - predicted: median {np.median(err):+.1f} dB, |error| median {np.median(abs(err)):.1f} dB; "
          f"within +-3 dB {100 * np.mean(abs(err) <= 3):.0f}%, within +-6 dB {100 * np.mean(abs(err) <= 6):.0f}%")
    for name, sel in (("blocking (loss >= 25 dB)", loss <= -25), ("in between (10-25 dB)", (loss > -25) & (loss <= -10)),
                      ("passing (loss < 10 dB)", loss > -10)):
        e = err[sel]
        if len(e):
            print(f"  {name:26s}: n {len(e):4d} | median {np.median(e):+5.1f} dB | within +-3 dB {100 * np.mean(abs(e) <= 3):3.0f}% "
                  f"| within +-6 dB {100 * np.mean(abs(e) <= 6):3.0f}% | measured ABOVE prediction by >6 dB: {100 * np.mean(e > 6):3.0f}%")
    print("largest misses (measured above prediction):")
    for x in sorted(rows, key=lambda x: -x[-1])[:12]:
        print(f"  LO {x[0]:7.3f} state {x[1]} (ref {x[2]}) loss {x[3]:6.1f} dB |S21x/S21ref| {x[4]:.2f}: "
              f"predicted {x[5]:6.1f}, measured {x[6]:6.1f} ({x[7]:+.1f} dB)")
    out = Path(sys.argv[1]).with_name(Path(sys.argv[1]).stem.replace("_states", "") + "_two_path_check.csv")
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["lo_ghz", "tx_filter", "ref_filter", "model_s21_db", "abs_ratio", "predicted_dbm", "measured_dbm", "error_db"])
        w.writerows([[f"{v:.4g}" if isinstance(v, float) else v for v in x] for x in rows])
    print(out)


if __name__ == "__main__":
    main()
