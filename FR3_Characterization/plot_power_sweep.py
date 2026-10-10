"""Plot a power sweep from conversion_gain_small_case.py (--stage C):
output power vs. input power (main panel) and conversion gain vs. input power
(companion panel), at the board's connectors (cable-corrected).

    python plot_power_sweep.py [results/unit_005/<run folder>] [--unit N]
                                            # default: newest run with a sweep (of unit N, if given)

Everything is local: reads the run's CSV/JSON, writes power_sweep.png beside
them, and opens it in the default image viewer (--no-open to skip). Nothing is
uploaded anywhere."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from results_layout import RESULTS_DIR, sweep_runs  # noqa: E402,F401  (RESULTS_DIR re-exported for the other plot scripts)

# Reference palette (light): surface, ink tokens, hairlines, categorical slots 1 and 2.
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
BLUE, ORANGE = "#2a78d6", "#eb6834"


def latest_run(unit: int | None = None) -> Path:
    runs = sweep_runs(unit)
    if not runs:
        sys.exit("no finished power sweep found under results/unit_*/ - run "
                 "conversion_gain_small_case.py --stage C first")
    return runs[-1]


def fmt(value: float, decimals: int) -> str:
    """Signed number with a true minus sign, matching the axis tick labels."""
    return f"{value:+.{decimals}f}".replace("-", "−")


def style_axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASELINE)
    ax.grid(True, color=GRID, linewidth=1.0, linestyle="-")
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=10, length=0)
    ax.xaxis.label.set_color(INK2)
    ax.yaxis.label.set_color(INK2)


def draw_case(ax1, ax2, run: Path) -> dict:
    """Draws one (LO, IF, sideband) sweep: output power vs. input power on ax1 and
    conversion gain vs. input power on ax2. Returns the run's metadata."""
    meta = json.loads((run / "metadata.json").read_text())
    with open(run / "power_sweep.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["valid"] == "1"]
    pin = [float(r["in_at_dut_dbm"]) for r in rows]
    pout = [float(r["out_at_dut_dbm"]) for r in rows]
    gain = [float(r["corrected_gain_db"]) for r in rows]

    sweep = meta["power_sweep"]
    g0 = sweep["small_signal_gain_db"]
    p1, p3 = sweep.get("p1db"), sweep.get("p3db")
    lo_ghz, if_ghz = meta["f_lo_hz"] / 1e9, meta["f_if_hz"] / 1e9
    rf_ghz = meta["f_rf_hz"] / 1e9
    sideband = meta["args"]["sideband"]

    xlim = (min(pin) - 2, max(pin) + 2)

    # --- main panel: output power vs input power ---
    style_axes(ax1)
    ax1.plot(xlim, [xlim[0] + g0, xlim[1] + g0], color=MUTED, linewidth=1.5, linestyle=(0, (5, 4)),
             label=f"Linear response (small-signal gain {fmt(g0, 2)} dB)", zorder=1)
    ax1.plot(pin, pout, color=BLUE, linewidth=2, solid_joinstyle="round", solid_capstyle="round",
             marker="o", markersize=6, markerfacecolor=BLUE, markeredgecolor=SURFACE, markeredgewidth=1.2,
             label="Measured", zorder=3)
    if p1:
        ax1.plot(p1["input_dbm"], p1["output_dbm"], linestyle="none", marker="o", markersize=13,
                 markerfacecolor="none", markeredgecolor=ORANGE, markeredgewidth=2.4, zorder=4,
                 label=f"P1dB: in {fmt(p1['input_dbm'], 2)} dBm, out {fmt(p1['output_dbm'], 2)} dBm")
    if p3:
        ax1.plot(p3["input_dbm"], p3["output_dbm"], linestyle="none", marker="D", markersize=9,
                 markerfacecolor=ORANGE, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=4,
                 label=f"P3dB: in {fmt(p3['input_dbm'], 2)} dBm, out {fmt(p3['output_dbm'], 2)} dBm")
    if not p1:  # never leave a missing P1dB looking like "no compression"
        ax1.text(0.03, 0.965, f"P1dB not reached: sweep stopped ({sweep['stop_reason']}).",
                 transform=ax1.transAxes, color=INK2, fontsize=10, ha="left", va="top", wrap=True)
    ax1.set_xlim(*xlim)
    ax1.set_ylim(min(pout) - 3, max(pout) + 6)
    ax1.set_xlabel("Input power at the board's IF port (dBm)", fontsize=11, labelpad=8)
    ax1.set_ylabel("Output power at the board's RF port (dBm)", fontsize=11, labelpad=8)
    ax1.set_title("Output power vs. input power", loc="left", fontsize=12.5, color=INK,
                  fontweight="semibold", pad=12)
    # Surface-colored backing so gridlines never run through the legend text.
    legend = ax1.legend(loc="lower right", frameon=True, facecolor=SURFACE, edgecolor="none", framealpha=0.95,
                        fontsize=10.5, labelcolor=INK2, handlelength=2.6)
    legend.set_zorder(5)

    # --- companion panel: gain vs input power ---
    style_axes(ax2)
    # Labels sit at the left, where the curve is far away, so no line strikes through them.
    for drop, label in ((1, "1 dB compression"), (3, "3 dB compression")):
        ax2.axhline(g0 - drop, color=BASELINE, linewidth=1.0)
        ax2.text(xlim[0] + 0.4, g0 - drop + 0.08, label, color=MUTED, fontsize=9.5, ha="left", va="bottom")
    ax2.axhline(g0, color=MUTED, linewidth=1.5, linestyle=(0, (5, 4)), zorder=1)
    ax2.text(xlim[0] + 0.4, g0 + 0.16, f"Small-signal gain {fmt(g0, 2)} dB", color=MUTED, fontsize=9.5,
             ha="left", va="bottom")
    ax2.plot(pin, gain, color=BLUE, linewidth=2, solid_joinstyle="round", solid_capstyle="round",
             marker="o", markersize=6, markerfacecolor=BLUE, markeredgecolor=SURFACE, markeredgewidth=1.2,
             zorder=3)
    if p1:
        ax2.plot(p1["input_dbm"], g0 - 1, linestyle="none", marker="o", markersize=13,
                 markerfacecolor="none", markeredgecolor=ORANGE, markeredgewidth=2.4, zorder=4)
    if p3:
        ax2.plot(p3["input_dbm"], g0 - 3, linestyle="none", marker="D", markersize=9,
                 markerfacecolor=ORANGE, markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=4)
    peak = max(range(len(gain)), key=gain.__getitem__)
    ax2.annotate(f"peak {fmt(gain[peak], 2)} dB\n(gain expands {fmt(gain[peak] - g0, 1)} dB)",
                 xy=(pin[peak], gain[peak]), xytext=(pin[peak] - 1.0, gain[peak] + 0.9),
                 color=INK2, fontsize=9.5, ha="right", va="bottom",
                 arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 1.0, "shrinkA": 2, "shrinkB": 5})
    ax2.set_xlim(*xlim)
    ax2.set_ylim(g0 - 4.5, max(gain) + 2.2)
    ax2.set_xlabel("Input power at the board's IF port (dBm)", fontsize=11, labelpad=8)
    ax2.set_ylabel("Conversion gain (dB)", fontsize=11, labelpad=8)
    ax2.set_title("Conversion gain vs. input power", loc="left", fontsize=12.5, color=INK,
                  fontweight="semibold", pad=12)
    return meta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", nargs="?", type=Path)
    parser.add_argument("--unit", type=int, help="pick the newest sweep of this unit (serial number)")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    run = args.run or latest_run(args.unit)
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 6.0), gridspec_kw={"width_ratios": [3, 2.4]})
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.80, bottom=0.14, wspace=0.16)
    meta = draw_case(ax1, ax2, run)
    lo_ghz, if_ghz = meta["f_lo_hz"] / 1e9, meta["f_if_hz"] / 1e9
    rf_ghz = meta["f_rf_hz"] / 1e9
    sideband = meta["args"]["sideband"]

    fig.text(0.065, 0.945, "FR3 1CH rev 1.4: TX conversion gain and compression", fontsize=16,
             color=INK, fontweight="semibold", ha="left", va="center")
    fig.text(0.065, 0.895,
             f"LO {lo_ghz:g} GHz, IF {if_ghz:g} GHz, {sideband} sideband, RF {rf_ghz:g} GHz. "
             f"TX filter in bypass. Board serial {meta['board_state_during'].get('board_serial', '?')}.",
             fontsize=11, color=INK2, ha="left", va="center")
    fig.text(0.065, 0.03,
             "Values are corrected to the board's connectors for cable loss (FR1 cable at the IF, FR3 cable at the RF), "
             "using uncalibrated FieldFox S21 measurements. Uncorrected FieldFox readings are in power_sweep.csv.",
             fontsize=8.8, color=MUTED, ha="left", va="center")

    # Unique, descriptive name: image viewers can confuse two files that share a name.
    out = run / f"power_sweep_{sideband}_LO{lo_ghz:g}GHz_IF{if_ghz:g}GHz_{run.name[:15]}.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(f"Saved {out}")
    if not args.no_open:
        os.startfile(out)  # default image viewer on this machine
    return 0


if __name__ == "__main__":
    sys.exit(main())
