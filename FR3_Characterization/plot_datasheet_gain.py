"""Datasheet figures for the conversion-gain sections -- TX (Section 3: upper sideband, Section 4: lower sideband) and, with
--chain rx, RX (Section 11: low-side LO, Section 12: high-side LO; images sec7/sec8_fig1-9, sec_gain_rx_numbers.tex) -- from a
flatness_campaign.py gain run (column mean_gain_db: the power-average gain over each point's 500 MHz swept window).

    python plot_datasheet_gain.py [--campaign gain_tx_20261009]
    python plot_datasheet_gain.py --chain rx [--campaign gain_rx_20261009]

Writes FR3-1ch-Datasheet/images/sec1_fig{1..9}.pdf (upper) and sec2_fig{1..9}.pdf (lower), the same layout as before:
  fig1..7  one panel per FR1 (1.0 ... 4.0 GHz): average conversion gain vs FR3, filter bypassed (grey) and optimal (blue),
           dashed lines at every change of optimal filter, the filter byte written inside each region
  fig8, 9  heatmaps over the full (FR1, FR3) grid, bypassed and optimal, with tiny zoom-to-read cell labels
           "(FR1, FR3, gain)"; FR3 > 24 GHz and FR1 = 4.0 GHz boxed in red (out of / partly out of design spec)
and FR3-1ch-Datasheet/sections/sec_gain_numbers.tex with the run's conditions (LMX temperature range, drives).
Styled like the other datasheet figures (IBM Plex Sans; plot_datasheet_nf.py's palette).
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from plot_datasheet_nf import DATASHEET, EMPTY, GRID_GREY, IMAGES, INK, INK2, OOS_RED, use_plex  # noqa: E402
from results_layout import unit_dir  # noqa: E402

FR1_GHZ = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
FR3_GHZ = [6.0 + 0.5 * k for k in range(42)]
RATED_FR3_MAX = 24.0
GREY, BLUE = "#8a8a8a", "#1f6fd1"
CELL_LABEL_PT = 2.4
SIDE = {"upper": ("Upper Sideband", "LO = FR3 − FR1", "sec1"), "lower": ("Lower Sideband", "LO = FR3 + FR1", "sec2"),
        "low": ("Low-Side LO", "LO = FR3 − FR1", "sec7"), "high": ("High-Side LO", "LO = FR3 + FR1", "sec8")}
# per chain: title prefix, gain axis top, heatmap colour range, FR3 axis label, FR1 axis label
CHAIN = {"tx": ("TX", 50, (10, 50), "FR3 Output Center Frequency (GHz)", "Input FR1 Center Frequency (GHz)"),
         "rx": ("RX", 60, (20, 60), "FR3 Input Center Frequency (GHz)", "Output FR1 Center Frequency (GHz)")}
CH = CHAIN["tx"]


def load(campaign: str) -> dict:
    """{(config, filter): {(fr1, fr3): row}}"""
    out: dict = {}
    for r in csv.DictReader(open(unit_dir(5) / campaign / "points.csv", newline="")):
        k = (round(float(r["fr1_hz"]) / 1e9, 1), round(float(r["fr3_hz"]) / 1e9, 1))
        out.setdefault((r["config"], r["filter"]), {})[k] = r
    return out


def house(ax, title: str, right: str = "") -> None:
    ax.set_title(title, loc="left", color=INK, fontsize=10.5)
    if right:
        ax.set_title(right, loc="right", color=INK, fontsize=10.5)
    ax.grid(color=GRID_GREY, lw=0.8)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)


def slice_panel(data: dict, side: str, fr1: float, path: Path) -> None:
    name, lo_rule, _ = SIDE[side]
    byp = {k[1]: float(r["mean_gain_db"]) for k, r in data[(side, "bypass")].items() if k[0] == fr1}
    opt = {k[1]: (float(r["mean_gain_db"]), r["filter_bits"]) for k, r in data[(side, "optimal")].items() if k[0] == fr1}
    f = sorted(set(byp) & set(opt))
    fig, ax = plt.subplots(figsize=(6.6, 4.6))
    if f and f[-1] > RATED_FR3_MAX:                                   # out-of-spec FR3, shown but shaded
        ax.axvspan(RATED_FR3_MAX + 0.25, 26.5, color=OOS_RED, alpha=0.08, lw=0)
        ax.text(26.3, CH[1] - 1, "FR3 > 24 GHz:\nout of design spec", color=OOS_RED, fontsize=7, ha="right", va="top",
                fontweight="semibold")
    if fr1 >= 4.0:                                                    # the 3.75-4.25 GHz window runs past the IF spec
        ax.text(6.3, CH[1] - 1, ("Input" if CH[0] == "TX" else "Output") + " IF spans 3.75\u20134.25 GHz here: 250 MHz of this\nexceeds the unit's 0.7\u20134.0 GHz IF design spec.",
                color=OOS_RED, fontsize=7, ha="left", va="top", fontweight="semibold")
    ax.plot(f, [byp[x] for x in f], "-o", ms=3.2, lw=1.6, color=GREY, label="Filter: Bypassed")
    ax.plot(f, [opt[x][0] for x in f], "-o", ms=3.2, lw=1.6, color=BLUE, label="Filter: Optimal")
    # filter regions: a dashed line at every change of optimal filter, the byte written inside each region
    bits = [opt[x][1] for x in f]
    starts = [0] + [i for i in range(1, len(f)) if bits[i] != bits[i - 1]]
    for j, i0 in enumerate(starts):
        i1 = (starts[j + 1] if j + 1 < len(starts) else len(f)) - 1
        if i0 > 0:
            ax.axvline((f[i0 - 1] + f[i0]) / 2, color=GREY, ls="--", lw=0.8)
        ax.text((f[i0] + f[i1]) / 2, 1.5, bits[i0], rotation=90, color=BLUE, fontsize=6.5, ha="center", va="bottom")
    ax.set_xlim(6, 26)
    ax.set_xticks(range(6, 27, 4))
    ax.set_ylim(0, CH[1])
    ax.set_xlabel(CH[3])
    ax.set_ylabel("Average Conversion Gain (dB)")
    ax.legend(frameon=False, fontsize=7.5, loc="center left")
    house(ax, f"{CH[0]} Conversion Gain, {name}: FR1 = {fr1:g} GHz", lo_rule)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def heatmap(data: dict, side: str, filt: str, path: Path) -> None:
    name = SIDE[side][0]
    grid = np.full((len(FR3_GHZ), len(FR1_GHZ)), np.nan)
    for (fr1, fr3), r in data[(side, filt)].items():
        grid[FR3_GHZ.index(fr3), FR1_GHZ.index(fr1)] = float(r["mean_gain_db"])
    fig, ax = plt.subplots(figsize=(6.4, 5.6))
    ax.set_facecolor(EMPTY)
    mesh = ax.pcolormesh(np.arange(len(FR1_GHZ) + 1) * 0.5 + 0.75, np.array(FR3_GHZ + [26.75]) - 0.25,
                         np.ma.masked_invalid(grid), cmap="Blues", vmin=CH[2][0], vmax=CH[2][1], edgecolors=(1, 1, 1, 0.35), linewidth=0.4)
    cmap, norm = mesh.get_cmap(), mesh.norm
    for i, fr3 in enumerate(FR3_GHZ):
        for j, fr1 in enumerate(FR1_GHZ):
            v = grid[i, j]
            if np.isnan(v):
                continue
            r, g, b, _ = cmap(norm(v))
            ink = "white" if 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.55 else INK
            ax.text(fr1, fr3, f"{fr1:.1f}, {fr3:.1f}, {v:.1f}", ha="center", va="center", fontsize=CELL_LABEL_PT, color=ink)
    y0 = RATED_FR3_MAX + 0.25                                          # FR3 > 24 GHz: out of design spec
    for x0, w, y, h in ((0.75, 3.5, y0, 26.75 - y0), (3.75, 0.5, 5.75, 21.0)):
        ax.add_patch(Rectangle((x0, y), w, h, facecolor=OOS_RED, alpha=0.06, edgecolor="none"))
        ax.add_patch(Rectangle((x0, y), w, h, facecolor="none", edgecolor=OOS_RED, lw=1.4, clip_on=False))
    ax.text(0.82, 26.55, "FR3 > 24 GHz: out of design spec", color=OOS_RED, fontsize=7, ha="left", va="top", fontweight="semibold")
    ax.text(4.0, 6.2, "FR1 = 4.0 GHz:\npartly out of\ndesign spec", color=OOS_RED, fontsize=6.5, ha="center", va="bottom",
            fontweight="semibold")
    ax.set_xticks(FR1_GHZ)
    ax.set_xlim(0.75, 4.25)
    ax.set_ylim(5.75, 26.75)
    ax.set_xlabel(CH[4])
    ax.set_ylabel(CH[3])
    ax.set_title(f"{CH[0]} Conversion Gain, {name}: All (FR1, FR3) Points, Filter {'Bypassed' if filt == 'bypass' else 'Optimal'}",
                 loc="left", color=INK, fontsize=11)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(mesh, ax=ax, fraction=0.06, pad=0.03)
    cb.set_label("Conversion Gain (dB)", color=INK2)
    cb.outline.set_edgecolor(INK)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", choices=("tx", "rx"), default="tx")
    ap.add_argument("--campaign", default=None)
    args = ap.parse_args()
    global CH
    CH = CHAIN[args.chain]
    args.campaign = args.campaign or f"gain_{args.chain}_20261009"
    use_plex()
    data = load(args.campaign)
    rows = [r for d in data.values() for r in d.values()]
    temps = [float(r["lmx_temp_c"]) for r in rows]
    for side in (("upper", "lower") if args.chain == "tx" else ("low", "high")):
        pre = SIDE[side][2]
        for n, fr1 in enumerate(FR1_GHZ, 1):
            slice_panel(data, side, fr1, IMAGES / f"{pre}_fig{n}.pdf")
        heatmap(data, side, "bypass", IMAGES / f"{pre}_fig8.pdf")
        heatmap(data, side, "optimal", IMAGES / f"{pre}_fig9.pdf")
    tag, name = "Tx", "sec_gain_numbers.tex"                      # RX temperatures: make_rx_conditions.py
    if args.chain == "tx":
        (DATASHEET / "sections" / name).write_text(
        f"% generated by FR3_Characterization/plot_datasheet_gain.py from {args.campaign} -- do not edit\n"
        f"\\newcommand{{\\gain{tag}MinC}}{{{min(temps):.0f}}}\n\\newcommand{{\\gain{tag}MaxC}}{{{max(temps):.0f}}}\n", encoding="utf-8")
    print(f"{args.campaign}: {len(rows)} sweeps, LMX {min(temps):.1f}-{max(temps):.1f} C -> {SIDE[side][2]} figures")


if __name__ == "__main__":
    main()
