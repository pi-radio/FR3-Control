"""Plot Type 4 sweeps: TX 2LO power at the "TX" connector versus LO (bottom axis) and 2LO (top axis).

    python plot_type4_2lo.py <type 4 csv> [<csv> ...] [--labels "run25,sweep A"] [--out <png>]

Several CSVs are overlaid (e.g. the same sweep before and after re-seating the lid). Points measured so far are plotted.
"""
import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("csv", nargs="+")
ap.add_argument("--labels", default="")
ap.add_argument("--out", default="")
args = ap.parse_args()
paths = [Path(p) for p in args.csv]
labels = args.labels.split(",") if args.labels else [p.stem for p in paths]

fig, ax = plt.subplots(figsize=(11, 5.5), dpi=130)
lo_min, lo_max, n_total = 1e9, 0.0, []
for p, lab, col in zip(paths, labels, ("#1f6fb2", "#d9480f", "#2b8a3e", "#7048e8")):
    meta = json.loads(p.with_suffix(".json").read_text(encoding="utf-8-sig"))
    rows = sorted(csv.DictReader(open(p)), key=lambda r: float(r["lo_ghz"]))
    x = [float(r["lo_ghz"]) for r in rows]
    y = [float(r["two_lo_dbm"]) for r in rows]
    lo_min, lo_max = min(lo_min, x[0]), max(lo_max, x[-1])
    n_total.append(len(rows))
    ax.plot(x, y, "-o", color=col, lw=1.2, ms=4, label=f"{lab} ({len(rows)} points)")
ax.set_xlabel("LO frequency (GHz)")
ax.set_ylabel("2LO power at \"TX\" connector (dBm)")
ax.grid(True, which="major", alpha=0.4)
ax.grid(True, which="minor", alpha=0.15)
ax.minorticks_on()
ax.set_xlim(lo_min - 0.125, lo_max + 0.125)
sec = ax.secondary_xaxis("top", functions=(lambda v: 2 * v, lambda v: v / 2))
sec.set_xlabel("2LO frequency (GHz)")
ax.set_title(f"Unit {meta['unit_serial']}: TX 2LO leakage vs LO (Experiment Type 4)\n"
             f"LMX drive {meta['lmx_power']}, LO nulled with the TX filter engaged, no input, case closed", fontsize=10)
if len(paths) > 1:
    ax.legend(loc="lower left", fontsize=9)
fig.tight_layout()
out = Path(args.out) if args.out else paths[-1].with_name(paths[-1].stem + "_2lo_vs_lo.png")
fig.savefig(out)
print(out)
