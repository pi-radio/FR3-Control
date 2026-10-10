"""Compare the tracking-generator sweeps (tracking_test.py) with the stepped single-tone measurements.

    python plot_tracking_test.py [results/unit_005/<tracking_test folder>] [--no-open]

Top row: conversion gain vs. RF frequency, stepped tones (blue points, one per 10 MHz) over the tracking
sweep (orange line, one sweep). Bottom row: their difference at the sweep's frequencies. Left column: the
desired sideband, right column: the undesired (image) sideband. Local only; opens the PNG when done."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from plot_power_sweep import BASELINE, BLUE, INK, INK2, MUTED, ORANGE, SURFACE, fmt, style_axes  # noqa: E402
from results_layout import unit_dirs  # noqa: E402


def newest_run() -> Path:
    runs = sorted((r for d in unit_dirs() for r in d.iterdir() if r.is_dir() and (r / "tracking_desired.csv").exists()),
                  key=lambda r: r.name)
    if not runs:
        sys.exit("no tracking_test run found")
    return runs[-1]


def load(path: Path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return {k: np.array([float(r[k]) for r in rows]) for k in
            ("rf_hz", "tracking_gain_db", "stepped_gain_db", "difference_db")}


def stepped_points(meta: dict, unit_folder: Path, image: bool):
    run = unit_folder / meta["stepped_reference_run"]
    with open(run / "flatness.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["pass"] == "1"]
    g = np.array([float(r["gain_corrected_db"]) for r in rows])
    if image:
        return (np.array([float(r["image_hz"]) for r in rows]),
                g - np.array([float(r["suppression_corrected_db"]) for r in rows]))
    return np.array([float(r["rf_hz"]) for r in rows]), g


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", nargs="?", type=Path)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    run = args.run or newest_run()
    meta = json.loads((run / "metadata.json").read_text())
    data = {"desired": load(run / "tracking_desired.csv"), "image": load(run / "tracking_image.csv")}

    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9.2), gridspec_kw={"height_ratios": [3, 1.5]})
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.80, bottom=0.10, wspace=0.16, hspace=0.30)

    titles = {"desired": "Desired sideband (upper), RF 13.75–14.25 GHz",
              "image": "Undesired (image) sideband, RF 9.75–10.25 GHz"}
    how = {"desired": "source forwards: offset −12 GHz, reverse off",
           "image": "source backwards: offset +12 GHz, reverse on"}
    for col, name in enumerate(("desired", "image")):
        d, m = data[name], meta.get(name, {})
        rf = d["rf_hz"] / 1e9
        xs, ys = stepped_points(meta, run.parent, image=(name == "image"))
        inband = (xs >= d["rf_hz"].min() - 5e6) & (xs <= d["rf_hz"].max() + 5e6)
        top, bot = axes[0][col], axes[1][col]
        style_axes(top)
        top.plot(rf, d["tracking_gain_db"], color=ORANGE, linewidth=2, solid_joinstyle="round", zorder=3,
                 label=f"Tracking sweep: {m.get('sweep_seconds', ['?'])[0]} s for one {len(rf)}-point sweep")
        top.plot(xs[inband] / 1e9, ys[inband], linestyle="none", marker="o", markersize=5.5, markerfacecolor=BLUE,
                 markeredgecolor=SURFACE, markeredgewidth=1.0, zorder=4, label="Stepped single tones (10 MHz apart)")
        top.set_xlim(rf.min(), rf.max())
        lo, hi = float(d["tracking_gain_db"].min()), float(d["tracking_gain_db"].max())
        top.set_ylim(lo - 0.6, hi + 0.35 * (hi - lo) + 1.6)
        top.set_ylabel("Conversion gain (dB)", fontsize=11, labelpad=8)
        top.set_title(titles[name], loc="left", fontsize=12.5, color=INK, fontweight="semibold", pad=10)
        top.legend(loc="upper right", frameon=True, facecolor=SURFACE, edgecolor="none", framealpha=0.95,
                   fontsize=9.8, labelcolor=INK2)
        top.text(0.02, 0.04, how[name], transform=top.transAxes, color=MUTED, fontsize=10, ha="left", va="bottom")

        style_axes(bot)
        bot.axhline(0, color=MUTED, linewidth=1.2, zorder=1)
        bot.plot(rf, d["difference_db"], color=ORANGE, linewidth=1.6, zorder=3)
        bot.set_xlim(rf.min(), rf.max())
        span = max(0.4, float(np.abs(d["difference_db"]).max()) * 1.6)
        bot.set_ylim(-span, span)
        bot.set_ylabel("Tracking − stepped (dB)", fontsize=10.5, labelpad=8)
        bot.set_xlabel("RF frequency (GHz)", fontsize=11, labelpad=8)
        bot.text(0.02, 0.93, f"mean {fmt(m.get('diff_mean_db', 0), 2)} dB,  std {m.get('diff_std_db', 0):.2f} dB,  "
                             f"worst {m.get('diff_max_abs_db', 0):.2f} dB", transform=bot.transAxes, color=INK,
                 fontsize=10.5, ha="left", va="top")

    fig.text(0.075, 0.955, f"FieldFox tracking generator vs. stepped tones, unit #{meta.get('unit_serial', '?')}",
             fontsize=16, color=INK, fontweight="semibold", ha="left", va="center")
    fig.text(0.075, 0.915, f"LO 12 GHz, IF 2 GHz center, 500 MHz bandwidth, constant −40 dBm drive, TX filter in bypass. "
             f"Same cable corrections for both methods; the analyzer's RBW was {meta['args']['rbw_khz']:g} kHz for the sweeps.",
             fontsize=11, color=INK2, ha="left", va="center")
    fig.text(0.075, 0.03, "The tracking generator's undocumented convention, found on this instrument: reverse OFF puts the "
             "source at receiver + offset; reverse ON puts it at offset − receiver.\nEach tracking curve is one sweep "
             "read as a full trace (a measurement that needs the whole span).", fontsize=8.8, color=MUTED,
             ha="left", va="center", linespacing=1.5)

    out = run / f"tracking_vs_stepped_unit{meta.get('unit_serial', 0):03d}_{run.name[:15]}.png"
    try:
        fig.savefig(out, dpi=150, facecolor=SURFACE)
    except OSError:
        out = out.with_name(out.stem + "_new" + out.suffix)
        fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(f"Saved {out}")
    if not args.no_open:
        os.startfile(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
