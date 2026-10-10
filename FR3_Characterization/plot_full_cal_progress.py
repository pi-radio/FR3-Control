"""Median (line) and min-max band (shaded) of the LO leakage over the non-reference filter settings vs LO, for a lo_cal_grid_scan run (also mid-run).

    python plot_full_cal_progress.py [--states <..._states.csv>] [--out <png>]

Default: the newest results/unit_005/2026-10-08/*full_cal_cold_closed_MCS_states.csv. Dashed line at the -25 dBm pass level.
"""
import argparse
import csv
import glob
import statistics as st
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

THRESHOLD_DBM = -20.0

ap = argparse.ArgumentParser()
ap.add_argument("--states", default="")
ap.add_argument("--out", default="")
args = ap.parse_args()
path = Path(args.states or sorted(glob.glob(r"results\unit_005\2026-10-08\lo_cal_grid_100MHz_*_full_cal_cold_closed_MCS_states.csv"))[-1])
rows = list(csv.DictReader(open(path, newline="")))
h, ref = {}, {}
for r in rows:
    lo, v = round(float(r["lo_ghz"]), 3), float(r["lo_dbm_ref_bias"])
    if r["is_reference"] == "1":
        ref[lo] = v
    else:
        h.setdefault(lo, []).append(v)
los = sorted(h)
med = [st.median(h[k]) for k in los]
worst = [max(h[k]) for k in los]
best = [min(h[k]) for k in los]
n_ok = sum(float(r["lo_dbm_ref_bias"]) <= THRESHOLD_DBM for r in rows)

fig, ax = plt.subplots(figsize=(12, 5.8), dpi=130)
ax.fill_between(los, best, worst, color="#1565c0", alpha=0.18, lw=0, label="Min to max over non-reference settings")
ax.plot(los, med, "-o", ms=3, lw=1.6, color="#1565c0", label="Median over non-reference settings")
ax.axhline(THRESHOLD_DBM, color="k", ls="--", lw=1, label=f"{THRESHOLD_DBM:g} dBm pass level")
ax.set_xlabel("LO frequency (GHz)")
ax.set_ylabel("LO leakage (dBm at TX-side FR3 RF Out)")
ax.set_title(f"Unit 5, case closed + MCS, cold: one null per LO (reference setting excluded). {len(los)} LOs, {len(rows)} readings, "
             f"{100 * n_ok / len(rows):.1f}% at or below {THRESHOLD_DBM:g} dBm (all readings)", fontsize=9.5)
ax.grid(alpha=0.4)
ax.set_xlim(6.9, 22.6)
ax.legend(fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, frameon=False)
fig.tight_layout()
out = Path(args.out) if args.out else path.parent / (path.name.replace("_states.csv", "_median_minmax.png"))
fig.savefig(out)
print(out)
