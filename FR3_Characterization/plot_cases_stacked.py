"""Both sideband cases in one image, one below the other, showing the desired
and the undesired sideband of each as conversion gain vs. RF frequency.

  Case 1 (top):    upper sideband - desired at LO+IF (14 GHz), undesired (image) at LO-IF (10 GHz)
  Case 2 (bottom): lower sideband - desired at LO-IF (10 GHz), undesired (image) at LO+IF (14 GHz)

Each row has two panels sharing one gain axis: the ~10 GHz band on the left and the ~14 GHz band on
the right (the empty middle of the spectrum is cut out). The 500 MHz signal band is shaded. Sideband
suppression at a given IF frequency is the desired gain minus the undesired gain at the mirrored RF
frequency (2 x LO - RF); the row heading gives its mean and range over the band.

    python plot_cases_stacked.py [--unit N] [--lo-ghz 12] [--upper <run>] [--lower <run>] [--no-open]

Default: the newest upper and newest lower flatness run at the newest LO frequency that has both.
Local only: writes one PNG into the unit's folder and opens it in the default image viewer."""

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

from flatness_metrics import flatness_metrics  # noqa: E402
from plot_flatness_compare import default_pair, flatness_runs, meta_of  # noqa: E402
from plot_power_sweep import BASELINE, BLUE, INK, INK2, MUTED, ORANGE, SURFACE, fmt, style_axes  # noqa: E402
from results_layout import unit_dir, unit_of  # noqa: E402


def load_case(run: Path) -> dict:
    meta = meta_of(run)
    with open(run / "flatness.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    by: dict[float, dict] = {}
    for r in rows:
        d = by.setdefault(float(r["if_hz"]), {"rw": float(r["rf_hz"]), "ri": float(r["image_hz"]), "g": [], "s": []})
        d["g"].append(float(r["gain_corrected_db"]))
        d["s"].append(float(r["suppression_corrected_db"]))
    f_if = np.array(sorted(by))
    g_w = np.array([np.mean(by[f]["g"]) for f in f_if])
    supp = np.array([np.mean(by[f]["s"]) for f in f_if])
    return {"meta": meta, "f_if": f_if, "rf_w": np.array([by[f]["rw"] for f in f_if]),
            "rf_i": np.array([by[f]["ri"] for f in f_if]), "g_w": g_w, "g_i": g_w - supp, "supp": supp}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", type=int)
    parser.add_argument("--lo-ghz", type=float)
    parser.add_argument("--upper", type=Path)
    parser.add_argument("--lower", type=Path)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    if bool(args.upper) != bool(args.lower):
        sys.exit("give both --upper and --lower, or neither")
    if args.upper:
        run_u, run_l = args.upper, args.lower
    else:
        runs = flatness_runs(args.unit)
        if args.lo_ghz is not None:
            runs = [r for r in runs if abs(meta_of(r)["f_lo_hz"] - args.lo_ghz * 1e9) < 1]
        if not runs:
            sys.exit("no flatness runs found")
        run_u, run_l = default_pair(runs)
    if unit_of(run_u) != unit_of(run_l):
        sys.exit("refusing to combine runs from different units")
    unit = unit_of(run_u)
    cu, cl = load_case(run_u), load_case(run_l)
    if cu["meta"]["f_lo_hz"] != cl["meta"]["f_lo_hz"]:
        sys.exit("the two runs use different LO frequencies")
    f_lo = cu["meta"]["f_lo_hz"]
    sig_if = cu["meta"]["signal_band_if_hz"]
    f_ifc = float(np.mean(sig_if))
    bands = [(f_lo - f_ifc, "low"), (f_lo + f_ifc, "high")]     # band centers in RF Hz: 10 and 14 GHz
    half = (sig_if[1] - sig_if[0]) / 2

    cases = [("Case 1: Upper sideband", cu, "upper"), ("Case 2: Lower sideband", cl, "lower")]
    ymin = min(float(min(c["g_w"].min(), c["g_i"].min())) for _, c, _ in cases)
    ymax = max(float(max(c["g_w"].max(), c["g_i"].max())) for _, c, _ in cases)
    ylim = (ymin - 3.0, ymax + 6.5)

    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 10.6), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.79, bottom=0.085, wspace=0.05, hspace=0.42)

    for row, (title, c, side) in enumerate(cases):
        for col, (center, _) in enumerate(bands):
            ax = axes[row][col]
            style_axes(ax)
            desired_here = (side == "upper" and col == 1) or (side == "lower" and col == 0)
            rf = c["rf_w"] if desired_here else c["rf_i"]
            gain = c["g_w"] if desired_here else c["g_i"]
            order = np.argsort(rf)
            rf, gain = rf[order], gain[order]
            color = BLUE if desired_here else ORANGE
            ax.axvspan((center - half) / 1e9, (center + half) / 1e9, color=color, alpha=0.08, linewidth=0, zorder=0)
            ax.plot(rf / 1e9, gain, color=color, linewidth=2, solid_joinstyle="round", solid_capstyle="round", zorder=3)
            m = flatness_metrics(rf, gain, (center - half, center + half))
            ax.text(0.03, 0.965, f"in the 500 MHz band: mean {fmt(m['mean_db'], 1)} dB, peak-to-peak {m['peak_to_peak_db']:.1f} dB",
                    transform=ax.transAxes, color=INK, fontsize=10.5, ha="left", va="top")
            ax.set_xlim(rf[0] / 1e9, rf[-1] / 1e9)
            ax.set_ylim(*ylim)
            ax.set_title(f"{'Desired' if desired_here else 'Undesired (image)'} sideband, RF "
                         f"{(center - half) / 1e9:g}–{(center + half) / 1e9:g} GHz", loc="left", fontsize=11.5,
                         color=INK, pad=8)
            if col == 0:
                ax.set_ylabel("Conversion gain (dB)", fontsize=11, labelpad=8)
                ax.spines["right"].set_visible(False)
            else:
                ax.spines["left"].set_visible(False)
                ax.tick_params(left=False, labelleft=False)
            if row == 1:
                ax.set_xlabel("RF frequency (GHz)", fontsize=10.5, labelpad=6)
        # axis-break marks between the two bands of this row
        for ax, x0 in ((axes[row][0], 1.0), (axes[row][1], 0.0)):
            ax.plot([x0 - 0.012, x0 + 0.012], [-0.02, 0.02], transform=ax.transAxes, color=BASELINE, clip_on=False, linewidth=1.5)
        s = flatness_metrics(c["f_if"], c["supp"], tuple(sig_if))
        span_l, span_r = axes[row][0].get_position(), axes[row][1].get_position()
        fig.text(0.075, span_l.y1 + 0.052, title, fontsize=14, color=INK, fontweight="semibold", ha="left", va="center")
        fig.text(0.075 + 0.205, span_l.y1 + 0.052,
                 f"desired at {(f_lo + f_ifc if side == 'upper' else f_lo - f_ifc) / 1e9:g} GHz, undesired at "
                 f"{(f_lo - f_ifc if side == 'upper' else f_lo + f_ifc) / 1e9:g} GHz.   Sideband suppression in the band: "
                 f"mean {s['mean_db']:.1f} dB, from {s['min_db']:.1f} to {s['max_db']:.1f} dB",
                 fontsize=11, color=INK2, ha="left", va="center")

    fig.text(0.075, 0.955, f"FR3 1CH rev 1.4, unit #{unit}: the two sideband cases, LO {f_lo / 1e9:g} GHz",
             fontsize=16, color=INK, fontweight="semibold", ha="left", va="center")
    fig.text(0.075, 0.915,
             f"IF {f_ifc / 1e9:g} GHz center, {(sig_if[1] - sig_if[0]) / 1e6:g} MHz bandwidth. A constant "
             f"{fmt(cu['meta']['args']['drive_dbm'], 0)} dBm tone stepped across the band, TX filter in bypass.",
             fontsize=11, color=INK2, ha="left", va="center")
    handles = [plt.Line2D([], [], color=BLUE, linewidth=2, label="Desired sideband"),
               plt.Line2D([], [], color=ORANGE, linewidth=2, label="Undesired (image) sideband")]
    fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(0.985, 0.968), frameon=False, fontsize=11,
               labelcolor=INK2, ncol=1)
    fig.text(0.075, 0.022,
             "Corrected to the board's connectors for cable loss, using uncalibrated FieldFox S21 measurements. Scalar magnitude "
             "only. Each curve is the mean of the run's passes.\nSideband suppression at a given IF frequency is the desired gain minus the "
             "undesired gain at the mirrored RF frequency (2 x LO minus RF, e.g. 14.0 GHz and 10.0 GHz).", fontsize=8.8, color=MUTED, ha="left", va="center", linespacing=1.5)

    out = unit_dir(unit) / f"cases_stacked_unit{unit:03d}_LO{f_lo / 1e9:g}GHz_{run_u.name[:15]}_{run_l.name[:15]}.png"
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
