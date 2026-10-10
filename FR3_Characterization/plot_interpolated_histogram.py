"""Histogram of the LO leakage in the "interpolated" run against the uncalibrated board (I_V = Q_V = 0 V) -- what a user gets with
and without the calibration -- over the same LO frequencies (those the interpolated run has measured so far).
Output: <interpolated campaign>/leakage_histogram.png; with --with-tables also the cold and hot tables at calibration
(-> leakage_histogram_with_tables.png).

    python plot_interpolated_histogram.py [--with-tables]
"""
import csv
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from results_layout import unit_dir

INTERP = "lo_null_interpolated_5MHz_20261005"
COLD = "golden_lo_null_5MHz_20260927"
HOT = "lo_null_hot_5MHz_20261004"
UNCAL = "unsuppressed_lo_leakage_5MHz_20260930"


def main() -> None:
    u = unit_dir(5)
    rows = list(csv.DictReader(open(u / INTERP / "interpolated.csv", newline="")))
    keys = [r["freq_ghz"] for r in rows]
    cold = {r["freq_ghz"]: r for r in csv.DictReader(open(u / COLD / "lo_null_table.csv", newline=""))}
    hot = {r["freq_ghz"]: r for r in csv.DictReader(open(u / HOT / "lo_null_table.csv", newline=""))}
    uncal = {f"{int(r['lo_hz']) / 1e9:.3f}": r for r in csv.DictReader(open(u / UNCAL / "unsuppressed_lo_leakage.csv", newline=""))}
    series = [
        (np.array([float(cold[k]["leakage_dbm_at_board"]) for k in keys]), "tab:blue",
         "cold table at calibration (2026-09-27, LMX ~60 C)"),
        (np.array([float(hot[k]["leakage_dbm_at_board"]) for k in keys]), "tab:red",
         "hot table at calibration (2026-10-04/05, LMX ~83 C)"),
        (np.array([float(uncal[k]["level_dbm_at_board"]) for k in keys]), "0.3",
         "uncalibrated (I_V = Q_V = 0 V, 2026-09-30)"),
        (np.array([float(r["leakage_dbm_at_board"]) for r in rows]), "tab:green",
         "interpolated (2026-10-05)"),
    ]
    user_view = "--with-tables" not in sys.argv                     # default: what a user gets (uncalibrated vs interpolated)
    if user_view:
        series = series[2:]
    allv = np.concatenate([s[0] for s in series])
    bins = np.arange(np.floor(allv.min()), np.ceil(allv.max()) + 1, 1.0)
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for data, c, lab in series:
        ax.hist(data, bins=bins, histtype="step", lw=2, color=c, label=f"{lab}: median {np.median(data):.1f} dBm")
        ax.axvline(np.median(data), color=c, ls="--", lw=1)
    t = np.array([float(r["lmx_temp_c"]) for r in rows])
    ax.set_xlabel("LO leakage at the \"TX-side FR3 RF Out\" connector (dBm)")
    ax.set_ylabel("number of LO frequencies (1 dB bins)")
    ax.set_title(f"Unit 5 LO leakage, {len(rows)} LOs ({keys[0]}-{keys[-1]} GHz, 5 MHz grid); interpolated run at LMX "
                 f"{t.min():.1f}-{t.max():.1f} C", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper center")
    fig.tight_layout()
    out = u / INTERP / ("leakage_histogram.png" if user_view else "leakage_histogram_with_tables.png")
    fig.savefig(out, dpi=150)
    print(out)


if __name__ == "__main__":
    main()
