"""Plot a FieldFox source-only loopback (source_loopback_check.py):
generated (commanded) power vs. measured power, and the deviation from a
straight line, alongside the TX board's gain-vs-drive curve for comparison.

    python plot_source_loopback.py [results/<loopback folder>] [--sweep results/<TX sweep folder>]

Defaults: newest loopback run, and newest TX power sweep. Local only: reads
the CSV/JSON files, writes source_loopback.png beside the loopback data and
opens it in the default image viewer (--no-open to skip)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt

from plot_power_sweep import (BASELINE, BLUE, GRID, INK, INK2, MUTED, ORANGE,  # noqa: F401
                              SURFACE, fmt, style_axes)
from results_layout import INSTRUMENT_CHECKS_DIR, sweep_runs


def newest_loopback() -> Path:
    runs = sorted(d for d in INSTRUMENT_CHECKS_DIR.glob("*_source_loopback_*") if (d / "loopback.csv").exists())
    if not runs:
        sys.exit(f"no loopback run found under {INSTRUMENT_CHECKS_DIR}")
    return runs[-1]


def newest_sweep() -> Path:
    runs = sweep_runs()
    if not runs:
        sys.exit("no finished TX power sweep found under results/unit_*/")
    return runs[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", nargs="?", type=Path)
    parser.add_argument("--sweep", type=Path, help="TX power-sweep folder to compare against")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    run = args.run or newest_loopback()
    with open(run / "loopback.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    if "usable" not in rows[0]:
        sys.exit(f"{run.name} is from the first version of the test (no noise-floor screening); "
                 "rerun source_loopback_check.py")
    meta = json.loads((run / "metadata.json").read_text())
    base = meta["reference_loss_db"]
    floor = meta["noise_floor_dbm"]
    setp = [float(r["ff_source_dbm"]) for r in rows]
    meas = [float(r["measured_dbm"]) for r in rows]
    delta = [-float(r["deviation_db"]) for r in rows]      # + = more output than the straight line
    usable = [r["usable"] == "1" for r in rows]

    sweep_dir = args.sweep or newest_sweep()
    with open(sweep_dir / "power_sweep.csv", newline="") as f:
        sw = [r for r in csv.DictReader(f) if r["valid"] == "1"]
    g0 = json.loads((sweep_dir / "metadata.json").read_text())["power_sweep"]["small_signal_gain_db"]
    sw_x = [float(r["ff_source_dbm"]) for r in sw]
    sw_y = [float(r["corrected_gain_db"]) - g0 for r in sw]

    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 6.0), gridspec_kw={"width_ratios": [3, 2.4]})
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.80, bottom=0.14, wspace=0.16)
    xlim = (min(setp) - 2, max(setp) + 2)

    # --- left: generated vs measured ---
    style_axes(ax1)
    ax1.plot(xlim, [xlim[0] - base, xlim[1] - base], color=MUTED, linewidth=1.5, linestyle=(0, (5, 4)),
             label=f"Ideal: generated − {base:.2f} dB (the cable)", zorder=1)
    ax1.axhline(floor, color=BASELINE, linewidth=1.0, zorder=1)
    ax1.text(xlim[1] - 0.4, floor + 0.8, f"Noise floor with source off: {fmt(floor, 1)} dBm",
             color=MUTED, fontsize=9.5, ha="right", va="bottom")
    ux = [x for x, u in zip(setp, usable) if u]
    uy = [y for y, u in zip(meas, usable) if u]
    ax1.plot(ux, uy, color=BLUE, linewidth=2, solid_joinstyle="round", solid_capstyle="round", marker="o",
             markersize=6, markerfacecolor=BLUE, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=3,
             label="Measured")
    nx = [x for x, u in zip(setp, usable) if not u]
    ny = [y for y, u in zip(meas, usable) if not u]
    ax1.plot(nx, ny, linestyle="none", marker="o", markersize=6, markerfacecolor=SURFACE,
             markeredgecolor=MUTED, markeredgewidth=1.4, zorder=3,
             label="Within 25 dB of the noise floor (not judged)")
    ax1.set_xlim(*xlim)
    ax1.set_ylim(min(floor, min(meas)) - 4, max(meas) + 5)
    ax1.set_xlabel("Generated power: FieldFox source setting (dBm)", fontsize=11, labelpad=8)
    ax1.set_ylabel("Measured power at the FieldFox analyzer (dBm)", fontsize=11, labelpad=8)
    ax1.set_title("Generated vs. measured power", loc="left", fontsize=12.5, color=INK,
                  fontweight="semibold", pad=12)
    ax1.legend(loc="upper left", frameon=False, fontsize=10.5, labelcolor=INK2, handlelength=2.6)

    # --- right: deviation from the straight line, against the TX board's gain change ---
    style_axes(ax2)
    ax2.axhline(0, color=MUTED, linewidth=1.5, linestyle=(0, (5, 4)), zorder=1)
    ax2.plot(nx, [d for d, u in zip(delta, usable) if not u], linestyle="none", marker="o", markersize=6,
             markerfacecolor=SURFACE, markeredgecolor=MUTED, markeredgewidth=1.4, zorder=3)
    ax2.plot(ux, [d for d, u in zip(delta, usable) if u], color=BLUE, linewidth=2, solid_joinstyle="round",
             solid_capstyle="round", marker="o", markersize=6, markerfacecolor=BLUE,
             markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=3, label="FieldFox loopback (this test)")
    ax2.plot(sw_x, sw_y, color=ORANGE, linewidth=2, solid_joinstyle="round", solid_capstyle="round",
             marker="o", markersize=6, markerfacecolor=ORANGE, markeredgecolor=SURFACE,
             markeredgewidth=1.2, zorder=4, label="TX board sweep: gain minus small-signal gain")
    peak = max(range(len(sw_y)), key=sw_y.__getitem__)
    # Labels sit in empty regions: the peak label to the right of the board's bump, the FieldFox
    # label above its flat line at the right, clear of the legend (top left) and of every data point.
    ax2.annotate(f"board: {fmt(sw_y[peak], 2)} dB", xy=(sw_x[peak], sw_y[peak]),
                 xytext=(sw_x[peak] + 1.6, sw_y[peak] + 0.02), color=INK2, fontsize=9.5, ha="left",
                 va="center", arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 1.0,
                                          "shrinkA": 2, "shrinkB": 5})
    worst = max((abs(d) for d, u in zip(delta, usable) if u))
    ax2.text(xlim[1] - 0.4, 0.22, f"FieldFox loopback\nwithin ±{worst:.2f} dB", color=INK2, fontsize=9.5,
             ha="right", va="bottom", linespacing=1.3)
    ax2.set_xlim(*xlim)
    ax2.set_ylim(min(min(delta), min(sw_y)) - 0.25, max(sw_y) + 1.3)
    ax2.set_xlabel("Generated power: FieldFox source setting (dBm)", fontsize=11, labelpad=8)
    ax2.set_ylabel("Level change vs. a straight line (dB)", fontsize=11, labelpad=8)
    ax2.set_title("Deviation from a straight line", loc="left", fontsize=12.5, color=INK,
                  fontweight="semibold", pad=12)
    ax2.legend(loc="upper left", frameon=False, fontsize=10, labelcolor=INK2, handlelength=2.2)

    fig.text(0.065, 0.945, f"FieldFox source-only loopback at {meta['args']['ghz']:g} GHz", fontsize=16,
             color=INK, fontweight="semibold", ha="left", va="center")
    fig.text(0.065, 0.895,
             f"FR1 cable from Port 1 to Port 2. {meta['ff_span_hz']/1e6:g} MHz span, RBW "
             f"{meta['ff_rbw_hz']/1e3:g} kHz, input attenuation fixed at {meta['ff_attenuation_db']:.0f} dB. "
             f"The board is not in this measurement.",
             fontsize=11, color=INK2, ha="left", va="center")
    fig.text(0.065, 0.03,
             "Hollow points are within 25 dB of the analyzer's noise floor and are not used to judge linearity. "
             "Board curve: LO 12 GHz, IF 2 GHz, upper sideband, filters in bypass, cable-corrected, vs. the same source setting.",
             fontsize=8.8, color=MUTED, ha="left", va="center")

    out = run / "source_loopback.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(f"Saved {out}")
    if not args.no_open:
        os.startfile(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
