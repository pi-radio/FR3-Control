"""Figure from a lo_leakage.py campaign: LO leakage, desired tone and leakage-to-carrier ratio versus LO frequency.

    python plot_lo_leakage.py [campaign folder] [--open]"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from plot_power_sweep import BLUE, INK, INK2, MUTED, ORANGE, SURFACE, style_axes  # noqa: E402
from results_layout import unit_dir  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", nargs="?", type=Path, default=unit_dir(5) / "lo_leakage_20260923")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    rows = list(csv.DictReader(open(args.folder / "lo_leakage.csv", newline="")))
    d = {}
    for iq in ("THRU", "SWAP"):
        r = sorted((x for x in rows if x["iq"] == iq), key=lambda x: float(x["lo_hz"]))
        d[iq] = {k: np.array([float(x[k]) for x in r]) for k in r[0] if k != "iq"}

    fig, axes = plt.subplots(2, 1, figsize=(13.5, 8.6), sharex=True)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.86, bottom=0.085, hspace=0.20)
    a0, a1 = axes
    for ax in axes:
        style_axes(ax)
    a0.plot(d["THRU"]["lo_hz"] / 1e9, d["THRU"]["lo_leak_dbm"], color=BLUE, linewidth=2, label="LO leakage at RF = LO (IQ THRU)")
    a0.plot(d["SWAP"]["lo_hz"] / 1e9, d["SWAP"]["lo_leak_dbm"], color=ORANGE, linewidth=1.4, linestyle=(0, (4, 2)),
            label="LO leakage (IQ SWAP)")
    a0.plot(d["THRU"]["lo_hz"] / 1e9, d["THRU"]["desired_dbm"], color=MUTED, linewidth=1.6, label="desired tone, upper sideband (−40 dBm at 2 GHz in)")
    a0.set_ylabel("Level at the RF output (dBm)", fontsize=11, labelpad=8)
    a0.set_title("Absolute levels", loc="left", fontsize=12.5, color=INK, fontweight="semibold", pad=8)
    a0.legend(loc="lower left", ncol=1, frameon=True, facecolor=SURFACE, edgecolor="none", framealpha=0.95, fontsize=10, labelcolor=INK2)
    a1.plot(d["THRU"]["lo_hz"] / 1e9, d["THRU"]["leak_minus_desired_dbc"], color=BLUE, linewidth=2, label="desired = upper sideband (THRU)")
    a1.plot(d["SWAP"]["lo_hz"] / 1e9, d["SWAP"]["leak_minus_desired_dbc"], color=ORANGE, linewidth=2, label="desired = lower sideband (SWAP)")
    a1.axhline(0, color=MUTED, linewidth=1)
    a1.set_ylabel("LO leakage minus desired tone (dB)", fontsize=11, labelpad=8)
    a1.set_xlabel("LO frequency (GHz)", fontsize=11, labelpad=8)
    a1.set_title("Leakage-to-carrier ratio (positive = LO stronger than the wanted signal)", loc="left", fontsize=12.5, color=INK,
                 fontweight="semibold", pad=8)
    a1.legend(loc="upper left", ncol=2, frameon=True, facecolor=SURFACE, edgecolor="none", framealpha=0.95, fontsize=10, labelcolor=INK2)
    fig.text(0.075, 0.955, "FR3 1CH rev 1.4, unit #5: LO leakage at the RF output", fontsize=16, color=INK, fontweight="semibold",
             ha="left", va="center")
    fig.text(0.075, 0.915, "LO-null table I/Q bias, TX filter bypass, LMX power 7, cable-corrected to the board's connector. "
             "Desired tone from a −40 dBm, 2 GHz IF input.", fontsize=10.5, color=INK2, ha="left", va="center")
    out = args.folder / f"lo_leakage_{args.folder.name}.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    print(f"Saved {out}")
    for iq in ("THRU", "SWAP"):
        x = d[iq]
        print(f"{iq}: LO leakage {x['lo_leak_dbm'].min():+.1f} .. {x['lo_leak_dbm'].max():+.1f} dBm (median {np.median(x['lo_leak_dbm']):+.1f}); "
              f"leak-desired median {np.median(x['leak_minus_desired_dbc']):+.1f} dB, max {x['leak_minus_desired_dbc'].max():+.1f} dB; "
              f"min margin over floor {x['leak_above_floor_db'].min():.0f} dB; temp {x['lmx_temp_c'].min():.0f}-{x['lmx_temp_c'].max():.0f} C")
        w = np.argmax(x["lo_leak_dbm"]); print(f"    worst leakage at LO {x['lo_hz'][w]/1e9:.1f} GHz: {x['lo_leak_dbm'][w]:+.1f} dBm")
        print(f"    LOs with leakage above desired: {int((x['leak_minus_desired_dbc'] > 0).sum())} of {x['lo_hz'].size}")
    if args.open:
        os.startfile(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
