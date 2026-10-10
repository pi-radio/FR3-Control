"""Pick the TX filter state per (LO, IF, sideband) from a filter_lo_scan.py run, and report what it buys compared with bypass.

    python analyze_filter_scan.py [folder] [--csv] [--plot] [--open]

Rule: 1) keep the states whose WANTED level is within --window dB (default 3) of the best wanted level among all 49 states;
2) among those, maximize   R = wanted - max(LO leakage, unwanted sideband),  i.e. the worst unwanted signal relative to the wanted one.
Readings at or below the analyzer noise floor + 6 dB are treated as the floor + 6 dB (the true rejection is at least that good), so a state is
not credited for rejection the analyzer cannot resolve. Writes filter_choice.csv (and filter_scan_map.png with --plot)."""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from results_layout import unit_dir


def load(folder: Path):
    rows = list(csv.DictReader(open(folder / "filter_scan.csv", newline="")))
    for r in rows:
        for k in ("lo_ghz", "if_ghz", "wanted_dbm", "unwanted_dbm", "lo_leak_dbm", "floor_dbm", "gain_db", "lmx_temp_c",
                  "pred_s21_wanted_db", "pred_s21_unwanted_db", "pred_s21_lo_db", "rf_wanted_ghz", "rf_unwanted_ghz"):
            r[k] = float(r[k])
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", nargs="?", type=Path, default=unit_dir(5) / "filter_lo_scan_20260924")
    parser.add_argument("--window", type=float, default=3.0)
    parser.add_argument("--csv", action="store_true")
    parser.add_argument("--plot", action="store_true")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    rows = load(args.folder)
    groups = defaultdict(list)
    for r in rows:
        groups[(r["lo_ghz"], r["iq"], r["if_ghz"])].append(r)

    out, chosen_count = [], defaultdict(int)
    print("| LO (GHz) | wanted | IF (GHz) | RF wanted (GHz) | chosen state | wanted loss vs bypass (dB) | LO leakage: bypass → chosen (dBm) | unwanted sideband: bypass → chosen (dBm) | R = wanted − worst unwanted: bypass → chosen (dB) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (lo, iq, f_if), rs in sorted(groups.items()):
        def floorclip(v, r):
            return max(v, r["floor_dbm"] + 6.0)
        for r in rs:
            r["_L"], r["_U"] = floorclip(r["lo_leak_dbm"], r), floorclip(r["unwanted_dbm"], r)
            r["_R"] = r["wanted_dbm"] - max(r["_L"], r["_U"])
        best_w = max(r["wanted_dbm"] for r in rs)
        cands = [r for r in rs if r["wanted_dbm"] >= best_w - args.window]
        pick = max(cands, key=lambda r: r["_R"])
        byp = next(r for r in rs if r["state_hex"] == "0x00")
        chosen_count[(lo, iq, pick["state_hex"])] += 1
        wanted_name = "upper (LO+IF)" if iq == "THRU" else "lower (LO−IF)"
        print(f"| {lo:g} | {wanted_name} | {f_if:g} | {pick['rf_wanted_ghz']:.3f} | {pick['state_hex']} ({pick['band']}) | {byp['wanted_dbm'] - pick['wanted_dbm']:+.1f} | "
              f"{byp['lo_leak_dbm']:+.1f} → {pick['lo_leak_dbm']:+.1f} | {byp['unwanted_dbm']:+.1f} → {pick['unwanted_dbm']:+.1f} | "
              f"{byp['_R']:+.1f} → {pick['_R']:+.1f} |")
        out.append({"lo_ghz": lo, "iq": iq, "if_ghz": f_if, "rf_wanted_ghz": pick["rf_wanted_ghz"], "state": pick["state_hex"], "band": pick["band"],
                    "wanted_dbm": pick["wanted_dbm"], "wanted_bypass_dbm": byp["wanted_dbm"], "lo_dbm": pick["lo_leak_dbm"], "lo_bypass_dbm": byp["lo_leak_dbm"],
                    "unwanted_dbm": pick["unwanted_dbm"], "unwanted_bypass_dbm": byp["unwanted_dbm"], "R_db": pick["_R"], "R_bypass_db": byp["_R"],
                    "best_wanted_dbm_any_state": best_w})
    print("\nchosen states per LO and sideband (count of IFs):")
    per = defaultdict(list)
    for (lo, iq, st), n in sorted(chosen_count.items()):
        per[(lo, iq)].append(f"{st} x{n}")
    for (lo, iq), v in sorted(per.items()):
        print(f"  LO {lo:g} GHz, {'upper' if iq == 'THRU' else 'lower'} sideband: " + ", ".join(v))

    # how well do the datasheet S21 values predict the measured change relative to bypass?
    dif = []
    for rs in groups.values():
        byp = next(r for r in rs if r["state_hex"] == "0x00")
        for r in rs:
            if r["state_hex"] == "0x00" or r["wanted_dbm"] < r["floor_dbm"] + 12 or byp["wanted_dbm"] < byp["floor_dbm"] + 12:
                continue
            dif.append((r["wanted_dbm"] - byp["wanted_dbm"]) - (r["pred_s21_wanted_db"] - byp["pred_s21_wanted_db"]))
    if dif:
        d = np.array(dif)
        print(f"\nwanted-tone change vs bypass, measured minus datasheet: median {np.median(d):+.1f} dB, 10th to 90th percentile "
              f"{np.percentile(d, 10):+.1f} to {np.percentile(d, 90):+.1f} dB ({d.size} readings above the floor)")
    if args.csv:
        with open(args.folder / "filter_choice.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0]))
            w.writeheader()
            w.writerows(out)
        print("wrote", args.folder / "filter_choice.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
