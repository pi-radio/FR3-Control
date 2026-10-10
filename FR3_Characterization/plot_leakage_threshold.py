"""LO leakage vs LO frequency, unit 5, one panel: uncalibrated (I_V = Q_V = 0 V, 2026-09-30) and interpolated bias (2026-10-05),
with a threshold line and, for each, the percentage of LO frequencies whose leakage is below (better than) the threshold.
Output: <interpolated campaign>/lo_leakage_threshold_<T>dBm.png

    python plot_leakage_threshold.py [--threshold-dbm -25]
"""
import argparse
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from results_layout import unit_dir

INTERP = "lo_null_interpolated_5MHz_20261005"
UNCAL = "unsuppressed_lo_leakage_5MHz_20260930"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--threshold-dbm", type=float, default=-25.0)
    thr = p.parse_args().threshold_dbm
    u = unit_dir(5)
    rows = list(csv.DictReader(open(u / INTERP / "interpolated.csv", newline="")))
    uncal = {f"{int(r['lo_hz']) / 1e9:.3f}": float(r["level_dbm_at_board"])
             for r in csv.DictReader(open(u / UNCAL / "unsuppressed_lo_leakage.csv", newline=""))}
    f = np.array([float(r["freq_ghz"]) for r in rows])
    li = np.array([float(r["leakage_dbm_at_board"]) for r in rows])
    lu = np.array([uncal[r["freq_ghz"]] for r in rows])
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for y, c, name in ((lu, "tab:red", "Uncalibrated"),                 # I_V = Q_V = 0 V, 2026-09-30
                       (li, "tab:green", "Calibrated")):            # interpolated bias, 2026-10-05
        pct = 100.0 * np.mean(y < thr)
        ax.plot(f, y, lw=1.0, color=c, label=f"{name}: {pct:.1f}% of LOs are better (lower) than {thr:g}dBm")
        print(f"{name}: {pct:.1f}% ({np.sum(y < thr)}/{len(y)}) below {thr:g} dBm")
    ax.axhline(thr, color="black", ls="--", lw=1.2, label=f"Threshold: {thr:g}dBm")
    x_arrow, length = 6.85, 20.0                                   # in the empty 6-7 GHz strip, left of the data
    for direction, word in ((+1, "Worse"), (-1, "Better")):
        ax.annotate("", xy=(x_arrow, thr + direction * length), xytext=(x_arrow, thr),
                    arrowprops=dict(arrowstyle="-|>", color="black", lw=1.5))
        ax.text(x_arrow, thr + direction * (length + 1.5), word, color="black", fontsize=10, ha="center",
                va="bottom" if direction > 0 else "top")             # just beyond each arrowhead
    ax.set_xlabel("LO frequency (GHz)")
    ax.set_ylabel("LO leakage (dBm)")
    ax.set_xlim(6, 24)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower left")
    ax.set_title(f"Unit 5: LO leakage at the \"TX-side FR3 RF Out\" connector, {len(f)} LOs (5 MHz grid)", fontsize=10)
    fig.tight_layout()
    out = u / INTERP / f"lo_leakage_threshold_{thr:g}dBm.png"
    fig.savefig(out, dpi=150)
    print(out)


if __name__ == "__main__":
    main()
