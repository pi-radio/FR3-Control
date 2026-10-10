"""LO leakage and LO suppression vs LO frequency for the "interpolated" run (unit 5). Top: leakage uncalibrated (I_V = Q_V = 0 V)
and with the interpolated bias. Bottom: LO suppression = uncalibrated leakage - interpolated leakage (dB), same LO frequency.
Output: <interpolated campaign>/lo_suppression_vs_freq.png

    python plot_interpolated_vs_freq.py
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
    sup = lu - li
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True, gridspec_kw={"height_ratios": [1, 1]})
    a1.plot(f, lu, lw=0.8, color="0.3", label=f"uncalibrated (I_V = Q_V = 0 V): median {np.median(lu):.1f} dBm")
    a1.plot(f, li, lw=0.6, color="tab:green", label=f"interpolated bias: median {np.median(li):.1f} dBm")
    a1.set_ylabel("LO leakage (dBm)")
    a1.legend(fontsize=8, loc="lower left")
    a1.grid(alpha=0.3)
    a1.set_title("Unit 5: LO leakage at the \"TX-side FR3 RF Out\" connector, interpolated bias (2026-10-05)", fontsize=10)
    a2.plot(f, sup, lw=0.6, color="tab:purple")
    a2.axhline(np.median(sup), color="tab:purple", ls="--", lw=1, label=f"median {np.median(sup):.1f} dB")
    a2.set_ylabel("LO suppression (dB)\n= uncalibrated - interpolated")
    a2.set_xlabel("LO frequency (GHz)")
    a2.legend(fontsize=8, loc="lower left")
    a2.grid(alpha=0.3)
    a1.set_xlim(f.min(), f.max())
    fig.tight_layout()
    out = u / INTERP / "lo_suppression_vs_freq.png"
    fig.savefig(out, dpi=150)
    print(out)
    for a, b in ((7, 9), (9, 11.3), (11.3, 15), (15, 19), (19, 22.61)):
        m = (f >= a) & (f < b)
        print(f"{a:5.1f}-{b:5.1f} GHz: suppression median {np.median(sup[m]):5.1f} dB (min {sup[m].min():5.1f}), "
              f"interpolated leakage median {np.median(li[m]):6.1f} dBm")


if __name__ == "__main__":
    main()
