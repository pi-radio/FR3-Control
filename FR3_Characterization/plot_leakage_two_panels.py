"""LO leakage vs LO frequency, unit 5, two panels: top uncalibrated (I_V = Q_V = 0 V, 2026-09-30), bottom with the interpolated bias
(2026-10-05). Output: <interpolated campaign>/lo_leakage_uncal_vs_interp.png

    python plot_leakage_two_panels.py
"""
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from results_layout import unit_dir

INTERP = "lo_null_interpolated_5MHz_20261005"
UNCAL = "unsuppressed_lo_leakage_5MHz_20260930"


def main() -> None:
    u = unit_dir(5)
    rows = list(csv.DictReader(open(u / INTERP / "interpolated.csv", newline="")))
    uncal = {f"{int(r['lo_hz']) / 1e9:.3f}": float(r["level_dbm_at_board"])
             for r in csv.DictReader(open(u / UNCAL / "unsuppressed_lo_leakage.csv", newline=""))}
    f = np.array([float(r["freq_ghz"]) for r in rows])
    li = np.array([float(r["leakage_dbm_at_board"]) for r in rows])
    lu = np.array([uncal[r["freq_ghz"]] for r in rows])
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for ax, y, c, title in ((a1, lu, "0.3", "Uncalibrated (I_V = Q_V = 0 V, 2026-09-30)"),
                            (a2, li, "tab:green", "Interpolated bias (2026-10-05)")):
        ax.plot(f, y, lw=0.6, color=c)
        ax.axhline(np.median(y), color=c, ls="--", lw=1, label=f"median {np.median(y):.1f} dBm")
        ax.set_title(title, fontsize=10)
        ax.set_ylabel("LO leakage (dBm)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="lower left")
    a2.set_xlabel("LO frequency (GHz)")
    a1.set_xlim(f.min(), f.max())
    fig.suptitle("Unit 5: LO leakage at the \"TX-side FR3 RF Out\" connector", fontsize=11)
    fig.tight_layout()
    out = u / INTERP / "lo_leakage_uncal_vs_interp.png"
    fig.savefig(out, dpi=150)
    print(out)


if __name__ == "__main__":
    main()
