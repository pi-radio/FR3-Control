"""Plot a one-null-per-LO calibration scan against its 0 V reference (lo_cal_grid_scan.py outputs).

    python plot_lo_cal_grid.py <lo_cal_grid_*_states.csv> <lo_uncal_grid_*_states.csv> [--out <png>]

Top: LO leakage at "TX-side FR3 RF Out" vs LO -- with the reference bias (median and min-max over the usable filter
states) and at 0 V (median). Bottom: suppression (0 V minus reference bias) per (LO, state): median and min-max.
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("nulled")
ap.add_argument("zero")
ap.add_argument("--out", default="")
ap.add_argument("--exclude-reference", action="store_true",
                help="leave out each LO's reference state (the state the null was found in) from both files")
a = ap.parse_args()
cal, unc = defaultdict(dict), defaultdict(dict)
refs = {(float(r["lo_ghz"]), r["tx_filter"]) for r in csv.DictReader(open(a.nulled, newline="")) if r["is_reference"] == "1"}
for path, dst in ((a.nulled, cal), (a.zero, unc)):
    for r in csv.DictReader(open(path, newline="")):
        if a.exclude_reference and (float(r["lo_ghz"]), r["tx_filter"]) in refs:
            continue
        dst[float(r["lo_ghz"])][r["tx_filter"]] = float(r["lo_dbm_ref_bias"])
los = sorted(x for x in cal if cal[x])
med_c = [np.median(list(cal[x].values())) for x in los]
min_c = [min(cal[x].values()) for x in los]
max_c = [max(cal[x].values()) for x in los]
med_u = [np.median(list(unc[x].values())) if unc.get(x) else np.nan for x in los]
min_u = [min(unc[x].values()) if unc.get(x) else np.nan for x in los]
max_u = [max(unc[x].values()) if unc.get(x) else np.nan for x in los]
sup = [[unc[x][k] - cal[x][k] for k in cal[x] if k in unc.get(x, {})] for x in los]
sup_med = [np.median(s) if s else np.nan for s in sup]
sup_min = [min(s) if s else np.nan for s in sup]
sup_max = [max(s) if s else np.nan for s in sup]

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7.5), dpi=120, sharex=True)
ax1.fill_between(los, min_c, max_c, color="#90caf9", alpha=0.5, label="Reference bias: min-max over the usable filter states")
ax1.plot(los, med_c, color="#1565c0", lw=1.6, label="Reference bias: median over the states")
ax1.fill_between(los, min_u, max_u, color="#ef9a9a", alpha=0.35, label="0 V (uncalibrated): min-max over the usable filter states")
ax1.plot(los, med_u, color="#c62828", lw=1.4, ls="--", label="0 V (uncalibrated): median over the states")
ax1.set_ylabel("LO leakage (dBm at connector)")
ax1.grid(alpha=0.4)
ax1.legend(fontsize=8, loc="lower left")
ax1.set_title("Unit 5, LMX drive 0: one null per LO (reference = least-loss filter state), applied to every usable state"
              + (" -- reference state itself EXCLUDED" if a.exclude_reference else ""), fontsize=10)
ax2.fill_between(los, sup_min, sup_max, color="#a5d6a7", alpha=0.5, label="min-max over the states")
ax2.plot(los, sup_med, color="#2e7d32", lw=1.6, label="median over the states")
ax2.axhline(0, color="black", lw=0.8)
ax2.set_ylabel("Suppression vs 0 V (dB)")
ax2.set_xlabel("LO frequency (GHz)")
ax2.grid(alpha=0.4)
ax2.legend(fontsize=8, loc="upper right")
fig.tight_layout()
out = Path(a.out) if a.out else Path(a.nulled).with_name(Path(a.nulled).stem.replace("_states", "") + "_vs_0V"
                                                        + ("_no_reference" if a.exclude_reference else "") + ".png")
allc = [v for x in los for v in cal[x].values()]
alls = [v for s_ in sup for v in s_]
print(f"{len(allc)} readings at {len(los)} LOs | calibrated: median {np.median(allc):.1f} dBm, worst {max(allc):.1f}, "
      f"<= -30: {100 * np.mean(np.array(allc) <= -30):.1f}%, <= -20: {100 * np.mean(np.array(allc) <= -20):.1f}% | "
      f"suppression vs 0 V: median {np.median(alls):.1f} dB, 10th pct {np.percentile(alls, 10):.1f}, 90th {np.percentile(alls, 90):.1f}")
fig.savefig(out)
print(out)
