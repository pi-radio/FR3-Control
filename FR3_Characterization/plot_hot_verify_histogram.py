"""Histogram of the LO leakage in the "hot verify" run (the hot table re-applied right after the hot scan, board still hot),
with the leakage the hot scan itself recorded at each null for comparison. Output: <verify campaign>/leakage_histogram.png

    python plot_hot_verify_histogram.py
"""
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from results_layout import unit_dir

VERIFY = "lo_null_hot_verify_5MHz_20261004"


def main() -> None:
    d = unit_dir(5) / VERIFY
    rows = list(csv.DictReader(open(d / "verify.csv", newline="")))
    now = np.array([float(r["leakage_dbm_at_board"]) for r in rows])
    table = np.array([float(r["table_leakage_dbm_at_board"]) for r in rows])
    bins = np.arange(np.floor(min(now.min(), table.min())), np.ceil(max(now.max(), table.max())) + 1, 1.0)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(table, bins=bins, alpha=0.55, color="tab:blue",
            label=f"at calibration (hot scan, 10-04 17:49 to 10-05 06:31): median {np.median(table):.1f} dBm")
    ax.hist(now, bins=bins, alpha=0.55, color="tab:red",
            label=f"hot verify (same bias re-applied, 10-05 06:31-08:09): median {np.median(now):.1f} dBm")
    for x, c in ((np.median(table), "tab:blue"), (np.median(now), "tab:red")):
        ax.axvline(x, color=c, ls="--", lw=1)
    ax.set_xlabel("LO leakage at the \"TX-side FR3 RF Out\" connector (dBm)")
    ax.set_ylabel("number of LO frequencies (1 dB bins)")
    ax.set_title(f"Unit 5, hot LO-null table re-applied: LO leakage, {len(rows)} LOs (7-22.6 GHz, 5 MHz grid)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    out = d / "leakage_histogram.png"
    fig.savefig(out, dpi=150)
    print(out)


if __name__ == "__main__":
    main()
