"""Compare two gain-flatness runs of one unit on the same axes, against IF
frequency: wanted-sideband conversion gain, and sideband suppression.

  * upper vs. lower sideband at the same LO (the default) shows whether the
    frequency dependence lives on the IF side (IF amplifier, 90 degree hybrid,
    sideband switch: same shape versus IF) or on the RF side (different shapes);
  * the same sideband at two LO frequencies (--a / --b) shows the same thing from
    the other direction: an IF-side response does not move when the RF band does.

    python plot_flatness_compare.py [--unit N] [--a <run>] [--b <run>] [--no-open]

Default: for the newest LO frequency that has both sidebands measured, its newest
upper run (drawn first, blue) and newest lower run (orange). --a/--b pick any two
runs of the same unit. Local only: writes one PNG into that unit's folder and
opens it in the default image viewer."""

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

from plot_power_sweep import BLUE, INK, INK2, MUTED, ORANGE, SURFACE, fmt, style_axes  # noqa: E402
from flatness_metrics import flatness_metrics  # noqa: E402
from results_layout import unit_dir, unit_dirs, unit_of  # noqa: E402


def flatness_runs(unit: int | None) -> list[Path]:
    dirs = unit_dirs() if unit is None else [unit_dir(unit)]
    return sorted((r for d in dirs if d.exists() for r in d.iterdir()
                   if r.is_dir() and (r / "flatness.csv").exists() and (r / "metadata.json").exists()),
                  key=lambda r: r.name)


def meta_of(run: Path) -> dict:
    return json.loads((run / "metadata.json").read_text())


def default_pair(runs: list[Path]) -> tuple[Path, Path]:
    """Newest LO frequency with both sidebands measured; its newest upper and newest lower run."""
    by_lo: dict[float, dict[str, Path]] = {}
    for r in runs:  # oldest first, so later runs overwrite earlier ones
        m = meta_of(r)
        by_lo.setdefault(m["f_lo_hz"], {})[m["args"]["sideband"]] = r
    both = [(max(x["upper"].name, x["lower"].name), x) for x in by_lo.values() if "upper" in x and "lower" in x]
    if not both:
        sys.exit("no LO frequency has both an upper and a lower flatness run; pass --a and --b explicitly")
    best = max(both, key=lambda t: t[0])[1]
    return best["upper"], best["lower"]


def load(run: Path):
    meta = meta_of(run)
    with open(run / "flatness.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    by_if: dict[float, dict[str, list[float]]] = {}
    for r in rows:
        d = by_if.setdefault(float(r["if_hz"]), {"g": [], "s": []})
        d["g"].append(float(r["gain_corrected_db"]))
        d["s"].append(float(r["suppression_corrected_db"]))
    f_if = np.array(sorted(by_if))
    return (f_if, np.array([np.mean(by_if[f]["g"]) for f in f_if]),
            np.array([np.mean(by_if[f]["s"]) for f in f_if]), meta)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", type=int)
    parser.add_argument("--a", type=Path, help="first run (blue)")
    parser.add_argument("--b", type=Path, help="second run (orange)")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    if bool(args.a) != bool(args.b):
        sys.exit("give both --a and --b, or neither")
    if args.a:
        run_a, run_b = args.a, args.b
    else:
        runs = flatness_runs(args.unit)
        if not runs:
            sys.exit("no flatness runs found under results/unit_*/")
        run_a, run_b = default_pair(runs)
    if unit_of(run_a) != unit_of(run_b):
        sys.exit("refusing to compare runs from different units")
    unit = unit_of(run_a)

    fa, ga, sa, ma = load(run_a)
    fb, gb, sb, mb = load(run_b)
    sig = ma["signal_band_if_hz"]
    lo_a, lo_b = ma["f_lo_hz"] / 1e9, mb["f_lo_hz"] / 1e9
    side_a, side_b = ma["args"]["sideband"], mb["args"]["sideband"]

    def label(f_if, g, lo, side):
        m = flatness_metrics(f_if, g, tuple(sig))
        rf = sorted((lo * 1e9 + x if side == "upper" else lo * 1e9 - x) / 1e9 for x in (f_if[0], f_if[-1]))
        return (f"{side.capitalize()} sideband, LO {lo:g} GHz: RF {rf[0]:.1f}–{rf[1]:.1f} GHz   "
                f"in-band ±{m['plus_minus_db']:.2f} dB, slope {fmt(m['slope_db_per_100mhz'], 2)} dB/100 MHz")

    if lo_a == lo_b and side_a != side_b:
        title, differs = "gain flatness, upper vs. lower sideband", "sideband (IQ THRU vs. SWAP)"
    elif side_a == side_b and lo_a != lo_b:
        title, differs = f"gain flatness, LO {lo_a:g} GHz vs. LO {lo_b:g} GHz ({side_a} sideband)", "LO frequency"
    else:
        title, differs = "gain flatness comparison", "sideband and LO frequency"

    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13.5, 9.0), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.83, bottom=0.11, hspace=0.16)

    lab_a, lab_b = label(fa, ga, lo_a, side_a), label(fb, gb, lo_b, side_b)
    for ax, (ya, yb), ylabel, ttl in (
            (ax1, (ga, gb), "Conversion gain (dB)", "Wanted-sideband conversion gain vs. IF frequency"),
            (ax2, (sa, sb), "Sideband suppression (dB)", "Sideband suppression (wanted minus image) vs. IF frequency")):
        style_axes(ax)
        ax.axvspan(sig[0] / 1e9, sig[1] / 1e9, color=BLUE, alpha=0.07, linewidth=0, zorder=0)
        ax.plot(fa / 1e9, ya, color=BLUE, linewidth=2, solid_joinstyle="round", solid_capstyle="round",
                label=lab_a, zorder=3)
        ax.plot(fb / 1e9, yb, color=ORANGE, linewidth=2, solid_joinstyle="round", solid_capstyle="round",
                label=lab_b, zorder=4)
        ax.set_ylabel(ylabel, fontsize=11, labelpad=8)
        ax.set_title(ttl, loc="left", fontsize=12.5, color=INK, fontweight="semibold", pad=10)
        lo, hi = float(min(ya.min(), yb.min())), float(max(ya.max(), yb.max()))
        ax.set_ylim(lo - 0.08 * (hi - lo) - 0.5, hi + 0.30 * (hi - lo) + 0.5)
    ax1.set_xlim(fa[0] / 1e9, fa[-1] / 1e9)
    ax1.legend(loc="upper right", frameon=True, facecolor=SURFACE, edgecolor="none", framealpha=0.95,
               fontsize=10.5, labelcolor=INK2)
    ax1.text(sig[0] / 1e9 + 0.005, ax1.get_ylim()[0] + 0.03 * (ax1.get_ylim()[1] - ax1.get_ylim()[0]),
             f"Signal band IF {sig[0] / 1e9:g}–{sig[1] / 1e9:g} GHz", color=MUTED, fontsize=10,
             ha="left", va="bottom")
    ax2.set_xlabel("IF frequency at the board's IF input (GHz)", fontsize=11, labelpad=8)

    fig.text(0.075, 0.955, f"FR3 1CH rev 1.4, unit #{unit}: {title}", fontsize=16, color=INK,
             fontweight="semibold", ha="left", va="center")
    fig.text(0.075, 0.915,
             f"Same IF scan {fa[0] / 1e9:g}–{fa[-1] / 1e9:g} GHz, a constant {fmt(ma['args']['drive_dbm'], 0)} dBm "
             f"tone, TX filter in bypass. Only the {differs} differs.",
             fontsize=11, color=INK2, ha="left", va="center")
    fig.text(0.075, 0.028,
             "Corrected to the board's connectors for cable loss, using uncalibrated FieldFox S21 measurements. Scalar magnitude "
             "only. Each curve is the mean of the run's passes.", fontsize=8.8, color=MUTED, ha="left", va="center")

    out = unit_dir(unit) / f"gain_flatness_compare_unit{unit:03d}_{run_a.name[:15]}_{run_b.name[:15]}.png"
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
