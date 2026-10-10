"""Plot a gain-flatness run (gain_flatness.py): conversion gain vs. RF frequency
across the wideband signal's band, and sideband suppression vs. RF frequency.

    python plot_flatness.py [results/unit_005/<run folder>] [--unit N] [--no-open]

Default: the newest flatness run (of unit N, if given). Local only: reads the
run's CSV/JSON, writes a PNG beside them, opens it in the default image viewer."""

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

from plot_power_sweep import BASELINE, BLUE, INK, INK2, MUTED, SURFACE, fmt, style_axes  # noqa: E402
from results_layout import unit_dirs, unit_dir, unit_of  # noqa: E402


def latest_flatness_run(unit: int | None) -> Path:
    dirs = unit_dirs() if unit is None else [unit_dir(unit)]
    runs = sorted((r for d in dirs if d.exists() for r in d.iterdir()
                   if r.is_dir() and (r / "flatness.csv").exists()), key=lambda r: r.name)
    if not runs:
        sys.exit("no flatness run found under results/unit_*/ - run gain_flatness.py first")
    return runs[-1]


def panel(ax, x_ghz, mean, lo, hi, band_ghz, ylabel, many_passes, title):
    style_axes(ax)
    ax.axvspan(*band_ghz, color=BLUE, alpha=0.07, linewidth=0, zorder=0)
    if many_passes:
        ax.fill_between(x_ghz, lo, hi, color=BLUE, alpha=0.20, linewidth=0, zorder=1)
    ax.plot(x_ghz, mean, color=BLUE, linewidth=2, solid_joinstyle="round", solid_capstyle="round", zorder=3)
    ax.set_xlim(x_ghz[0], x_ghz[-1])
    ax.set_ylabel(ylabel, fontsize=11, labelpad=8)
    ax.set_title(title, loc="left", fontsize=12.5, color=INK, fontweight="semibold", pad=10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", nargs="?", type=Path)
    parser.add_argument("--unit", type=int)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    run = args.run or latest_flatness_run(args.unit)
    meta = json.loads((run / "metadata.json").read_text())
    with open(run / "flatness.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    f_lo = meta["f_lo_hz"]
    upper = meta["args"]["sideband"] == "upper"
    sig_if = meta["signal_band_if_hz"]
    sig_rf = [(f_lo + x) if upper else (f_lo - x) for x in sig_if]
    band_ghz = (min(sig_rf) / 1e9, max(sig_rf) / 1e9)

    by_rf: dict[float, dict[str, list[float]]] = {}
    for r in rows:
        d = by_rf.setdefault(float(r["rf_hz"]), {"g": [], "s": []})
        d["g"].append(float(r["gain_corrected_db"]))
        d["s"].append(float(r["suppression_corrected_db"]))
    rf = np.array(sorted(by_rf))
    mean_g = np.array([np.mean(by_rf[f]["g"]) for f in rf])
    lo_g = np.array([np.min(by_rf[f]["g"]) for f in rf])
    hi_g = np.array([np.max(by_rf[f]["g"]) for f in rf])
    mean_s = np.array([np.mean(by_rf[f]["s"]) for f in rf])
    lo_s = np.array([np.min(by_rf[f]["s"]) for f in rf])
    hi_s = np.array([np.max(by_rf[f]["s"]) for f in rf])
    x = rf / 1e9
    passes = len({int(r["pass"]) for r in rows})
    many = passes >= 2

    summary = meta.get("summary", {})
    g = summary.get("signal_band_gain")
    s = summary.get("signal_band_suppression_db")
    drive = meta["args"]["drive_dbm"]
    sideband = meta["args"]["sideband"]

    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13.5, 8.9), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.79, bottom=0.115, hspace=0.16)

    panel(ax1, x, mean_g, lo_g, hi_g, band_ghz, "Conversion gain (dB)", many, "Conversion gain vs. RF frequency")
    span_g = float(hi_g.max() - lo_g.min())
    ax1.set_ylim(float(lo_g.min()) - max(0.4, 0.15 * span_g), float(hi_g.max()) + max(1.6, 0.40 * span_g))
    pass_diff = float(np.max(hi_g - lo_g))   # how far apart the passes are, worst case
    ax1.text(band_ghz[0] + 0.01, ax1.get_ylim()[0] + 0.03 * (ax1.get_ylim()[1] - ax1.get_ylim()[0]),
             f"Signal band {band_ghz[0]:g}–{band_ghz[1]:g} GHz", color=MUTED, fontsize=10, ha="left", va="bottom")
    if g:
        note = ""
        if many:
            note = (f"\nThe {passes} passes (up, then down in frequency) agree within {pass_diff:.2f} dB, "
                    "so this is the board's response, not drift.") if pass_diff < 0.15 else \
                   f"\nThe {passes} passes differ by up to {pass_diff:.2f} dB (shaded), so drift may matter."
        ax1.text(0.012, 0.965,
                 f"In the signal band: mean {fmt(g['mean_db'], 2)} dB,  peak-to-peak {g['peak_to_peak_db']:.2f} dB "
                 f"(±{g['plus_minus_db']:.2f} dB),  slope {fmt(g['slope_db_per_100mhz'], 2)} dB per 100 MHz" + note,
                 transform=ax1.transAxes, color=INK, fontsize=11, ha="left", va="top", linespacing=1.5)
    handles = [plt.Line2D([], [], color=BLUE, linewidth=2, label=f"Mean of {passes} pass(es)")]
    if many and pass_diff >= 0.15:   # only advertise the band when it is actually visible
        handles.append(matplotlib.patches.Patch(color=BLUE, alpha=0.20, label="Range between passes"))
    handles.append(matplotlib.patches.Patch(color=BLUE, alpha=0.07, label="Signal band"))
    ax1.legend(handles=handles, loc="upper right", frameon=True, facecolor=SURFACE, edgecolor="none",
               framealpha=0.95, fontsize=10, labelcolor=INK2)
    top = ax1.secondary_xaxis("top", functions=((lambda v: v - f_lo / 1e9), (lambda v: v + f_lo / 1e9)) if upper
                              else ((lambda v: f_lo / 1e9 - v), (lambda v: f_lo / 1e9 - v)))
    top.set_xlabel("Corresponding IF frequency at the board's IF input (GHz)", fontsize=10.5, color=INK2, labelpad=8)
    top.tick_params(colors=MUTED, labelsize=10, length=0)
    top.spines["top"].set_visible(False)

    panel(ax2, x, mean_s, lo_s, hi_s, band_ghz, "Sideband suppression (dB)", many,
          "Sideband suppression (wanted minus image) vs. RF frequency")
    span_s = float(hi_s.max() - lo_s.min())
    ax2.set_ylim(float(lo_s.min()) - max(0.5, 0.3 * span_s), float(hi_s.max()) + max(0.8, 0.5 * span_s))
    if s:
        ax2.text(0.012, 0.93, f"In the signal band: mean {s['mean_db']:.1f} dB,  range {s['min_db']:.1f} to {s['max_db']:.1f} dB",
                 transform=ax2.transAxes, color=INK, fontsize=11, ha="left", va="top")
    ax2.set_xlabel("RF frequency at the board's RF output (GHz)", fontsize=11, labelpad=8)

    unit = meta.get("unit_serial", unit_of(run))
    fig.text(0.075, 0.955, f"FR3 1CH rev 1.4, unit #{unit}: TX gain flatness across a "
             f"{(sig_if[1] - sig_if[0]) / 1e6:g} MHz signal", fontsize=16, color=INK, fontweight="semibold",
             ha="left", va="center")
    fig.text(0.075, 0.915,
             f"LO {f_lo / 1e9:g} GHz, {sideband} sideband: IF {sig_if[0] / 1e9:g}–{sig_if[1] / 1e9:g} GHz "
             f"→ RF {band_ghz[0]:g}–{band_ghz[1]:g} GHz. A constant {fmt(drive, 0)} dBm tone stepped across "
             f"the band, TX filter in bypass.", fontsize=11, color=INK2, ha="left", va="center")
    fig.text(0.075, 0.03,
             "Corrected to the board's connectors for cable loss (FR1 cable at the IF, FR3 cable at the RF), using uncalibrated "
             "FieldFox S21 measurements. Scalar magnitude only: phase and group delay are not measured.\n"
             "The FieldFox's own source and analyzer flatness is included (not yet measured separately). "
             "Output level for this constant input = gain + input level.",
             fontsize=8.8, color=MUTED, ha="left", va="center", linespacing=1.5)

    out = run / f"gain_flatness_unit{unit:03d}_LO{f_lo / 1e9:g}GHz_{sideband}_{run.name[:15]}.png"
    try:
        fig.savefig(out, dpi=150, facecolor=SURFACE)
    except OSError:
        out = out.with_name(out.stem + "_new" + out.suffix)  # the old copy may be open in a viewer
        fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(f"Saved {out}")
    if not args.no_open:
        os.startfile(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
