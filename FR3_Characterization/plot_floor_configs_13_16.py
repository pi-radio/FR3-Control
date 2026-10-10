"""Median TX LO leakage over the non-reference filter states vs LO, LO 13-16 GHz, for the case / MCS configurations of
2026-10-07/08 (one null per LO at the reference state, applied to every usable state; FR1 1 GHz, upper sideband).

    python plot_floor_configs_13_16.py

Traces: case closed (original, 10-07 20 MHz scan at the 100 MHz points), case open, case open + MCS near the LVA+mixer,
case closed + MCS by the LVA, mixer and bias tee (points measured so far).
"""
import csv
import glob
import statistics as st
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

D7, D8 = Path(r"results\unit_005\2026-10-07"), Path(r"results\unit_005\2026-10-08")
RUNS = [("Case closed: original (10-07)", D7, "lo_cal_grid_20MHz_*_states.csv", "#c62828", "-"),
        ("Case open", D8, "lo_cal_grid_100MHz_*_case_open_13to16GHz_states.csv", "#6d4c41", "-"),
        ("Case open + MCS pieces near the LVA+Mixer", D8, "lo_cal_grid_100MHz_*_case_open_with_LVA_mixer_MCS_13to16GHz_states.csv", "#2e7d32", "-"),
        ("Case closed + MCS pieces by the LVA, Mixer, Bias-tee", D8, "lo_cal_grid_100MHz_*_case_closed_MCS_pieces_13to16GHz_states.csv", "#1565c0", "-")]


def medians(path):
    h = {}
    for r in csv.DictReader(open(path, newline="")):
        lo = round(float(r["lo_ghz"]), 2)
        if r["is_reference"] != "1" and 12.999 <= lo <= 16.001 and abs(lo * 10 - round(lo * 10)) < 1e-6:
            h.setdefault(lo, []).append(float(r["lo_dbm_ref_bias"]))
    return {k: st.median(v) for k, v in sorted(h.items())}


fig, ax = plt.subplots(figsize=(11, 6.2), dpi=130)
for label, d, pat, col, ls in RUNS:
    files = sorted(glob.glob(str(d / pat)))
    if not files:
        continue
    m = medians(files[-1])
    ax.plot(list(m), list(m.values()), ls, marker="o", ms=3.5, lw=1.6, color=col, label=f"{label} ({len(m)} LOs)")
ax.set_xlabel("LO frequency (GHz)")
ax.set_ylabel("Median LO leakage, non-reference states (dBm at connector)")
ax.set_title("Unit 5, LMX drive 0, FR1 1 GHz upper sideband: LO leakage with one null per LO (reference state excluded)", fontsize=10)
ax.grid(alpha=0.4)
ax.set_xlim(12.95, 16.05)
ax.legend(fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2, frameon=False)
fig.tight_layout()
out = D8 / "lo_floor_13to16GHz_case_and_MCS_configs.png"
fig.savefig(out)
print(out)
