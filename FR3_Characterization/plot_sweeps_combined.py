"""One image with both sidebands: the upper-sideband sweep on top, the lower-
sideband sweep below (each: output power vs. input power, and conversion gain
vs. input power). Draws with the same function as plot_power_sweep.py.

    python plot_sweeps_combined.py [--unit N] [--upper <run folder>] [--lower <run folder>]

Default: the newest upper and newest lower power sweep of one unit (the unit of
the newest sweep, unless --unit is given). Runs from different units are never
combined. Local only: writes one PNG into that unit's folder and opens it in
the default image viewer (--no-open to skip)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt

from plot_power_sweep import INK, INK2, MUTED, SURFACE, draw_case
from results_layout import sweep_runs, unit_dir, unit_of


def newest_run(sideband: str, unit: int | None) -> Path:
    found = [r for r in sweep_runs(unit)
             if json.loads((r / "metadata.json").read_text())["args"]["sideband"] == sideband]
    if not found:
        sys.exit(f"no {sideband}-sideband power sweep found" + ("" if unit is None else f" for unit {unit}"))
    return found[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", type=int, help="unit (serial number); default: the unit of the newest sweep")
    parser.add_argument("--upper", type=Path)
    parser.add_argument("--lower", type=Path)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    unit = args.unit
    if unit is None and not (args.upper and args.lower):
        newest = sweep_runs()
        if not newest:
            sys.exit("no finished power sweep found under results/unit_*/")
        unit = unit_of(newest[-1])
    upper = args.upper or newest_run("upper", unit)
    lower = args.lower or newest_run("lower", unit)
    unit = unit if unit is not None else unit_of(upper)
    if unit_of(upper) != unit_of(lower):
        sys.exit(f"refusing to combine runs from different units: {unit_of(upper)} and {unit_of(lower)}")

    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 12.6), gridspec_kw={"width_ratios": [3, 2.4]})
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.86, bottom=0.07, wspace=0.16, hspace=0.42)

    metas = [draw_case(axes[0][0], axes[0][1], upper), draw_case(axes[1][0], axes[1][1], lower)]
    for row, (label, meta) in enumerate((("Upper sideband", metas[0]), ("Lower sideband", metas[1]))):
        lo, f_if, rf = meta["f_lo_hz"] / 1e9, meta["f_if_hz"] / 1e9, meta["f_rf_hz"] / 1e9
        op = "+" if label.startswith("Upper") else "−"
        top = axes[row][0].get_position().y1
        fig.text(0.065, top + 0.045, f"{label}: LO {lo:g} GHz {op} IF {f_if:g} GHz = RF {rf:g} GHz",
                 fontsize=13.5, color=INK, fontweight="semibold", ha="left", va="center")

    fig.text(0.065, 0.965, "FR3 1CH rev 1.4: TX conversion gain and compression, both sidebands",
             fontsize=16, color=INK, fontweight="semibold", ha="left", va="center")
    fig.text(0.065, 0.937,
             f"LO 12 GHz, IF 2 GHz, TX filter in bypass. Board serial "
             f"{metas[0]['board_state_during'].get('board_serial', '?')}.",
             fontsize=11, color=INK2, ha="left", va="center")
    fig.text(0.065, 0.018,
             "Values are corrected to the board's connectors for cable loss (FR1 cable at the IF, FR3 cable at the RF), "
             "using uncalibrated FieldFox S21 measurements. Uncorrected FieldFox readings are in each run's power_sweep.csv.",
             fontsize=8.8, color=MUTED, ha="left", va="center")

    out = unit_dir(unit) / (f"power_sweeps_upper_and_lower_LO{metas[0]['f_lo_hz']/1e9:g}GHz_"
                            f"IF{metas[0]['f_if_hz']/1e9:g}GHz_{upper.name[:15]}_{lower.name[:15]}.png")
    try:
        fig.savefig(out, dpi=150, facecolor=SURFACE)
    except OSError as err:
        # Typically the previous copy is still open in an image viewer or browser (Windows locks it).
        # Keep the old one untouched and save alongside it instead of failing.
        out = out.with_name(f"{out.stem}_{datetime.now():%H%M%S}{out.suffix}")
        print(f"Could not overwrite the existing figure ({err}); saving as {out.name} instead.")
        fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(f"Saved {out}")
    if not args.no_open:
        os.startfile(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
