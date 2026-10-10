"""Datasheet figures for TX sideband suppression (Section 6), from a sideband_campaign.py run (CW tones; suppression =
desired - undesired, cables removed).

    python plot_datasheet_sideband.py [--campaign sideband_tx_20261009]

Writes FR3-1ch-Datasheet/images/sec3_fig{1..8}.pdf, the same order as before: for (upper, bypassed), (upper, optimal),
(lower, bypassed), (lower, optimal) a heatmap over the (FR1, FR3) grid (zoom-to-read cell labels, out-of-spec regions boxed
in red) and a histogram of the in-spec points (FR3 <= 24 GHz; CW, so FR1 = 4.0 GHz is in spec) with the median marked; plus
FR3-1ch-Datasheet/sections/sec_sideband_numbers.tex (medians, 10th percentiles, worst, temperatures).
"""
from __future__ import annotations

import argparse
import csv
import statistics

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from plot_datasheet_nf import ACCENT, BAR, DATASHEET, EMPTY, GRID_GREY, IMAGES, INK, INK2, OOS_RED, use_plex  # noqa: E402
from results_layout import unit_dir  # noqa: E402

FR1_GHZ = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
FR3_GHZ = [6.0 + 0.5 * k for k in range(42)]
CELL_LABEL_PT = 2.4
VMAX = 80.0
ORDER = [("upper", "bypass"), ("upper", "optimal"), ("lower", "bypass"), ("lower", "optimal")]
NAME = {"upper": "Upper", "lower": "Lower"}
FILT = {"bypass": "Filter Bypassed", "optimal": "Filter Optimal"}
TAG = {("upper", "bypass"): "UpperBypass", ("upper", "optimal"): "UpperOptimal", ("lower", "bypass"): "LowerBypass",
       ("lower", "optimal"): "LowerOptimal"}


def in_spec(fr1: float, fr3: float) -> bool:
    """CW measurement (one tone at the FR1 centre), so FR1 = 4.0 GHz is inside the 0.7-4.0 GHz IF spec -- unlike the swept
    500 MHz gain/flatness windows (same reasoning as the NF section). Only FR3 > 24 GHz is out of spec."""
    return fr3 <= 24.0 + 1e-9


def heatmap(sel: dict, title: str, path) -> None:
    grid = np.full((len(FR3_GHZ), len(FR1_GHZ)), np.nan)
    for (fr1, fr3), v in sel.items():
        grid[FR3_GHZ.index(fr3), FR1_GHZ.index(fr1)] = v
    fig, ax = plt.subplots(figsize=(6.4, 5.6))
    ax.set_facecolor(EMPTY)
    mesh = ax.pcolormesh(np.arange(len(FR1_GHZ) + 1) * 0.5 + 0.75, np.array(FR3_GHZ + [26.75]) - 0.25,
                         np.ma.masked_invalid(grid), cmap="viridis", vmin=0, vmax=VMAX, edgecolors=(1, 1, 1, 0.35),
                         linewidth=0.4)
    cmap, norm = mesh.get_cmap(), mesh.norm
    for i, fr3 in enumerate(FR3_GHZ):
        for j, fr1 in enumerate(FR1_GHZ):
            v = grid[i, j]
            if np.isnan(v):
                continue
            r, g, b, _ = cmap(norm(v))
            ink = "white" if 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.55 else INK
            ax.text(fr1, fr3, f"{fr1:.1f}, {fr3:.1f}, {v:.1f}", ha="center", va="center", fontsize=CELL_LABEL_PT, color=ink)
    y0 = 24.25
    ax.add_patch(Rectangle((0.75, y0), 3.5, 26.75 - y0, facecolor=OOS_RED, alpha=0.06, edgecolor="none"))
    ax.add_patch(Rectangle((0.75, y0), 3.5, 26.75 - y0, facecolor="none", edgecolor=OOS_RED, lw=1.4, clip_on=False))
    ax.text(0.82, 26.55, "FR3 > 24 GHz: out of design spec", color=OOS_RED, fontsize=7, ha="left", va="top", fontweight="semibold")
    ax.set_xticks(FR1_GHZ)
    ax.set_xlim(0.75, 4.25)
    ax.set_ylim(5.75, 26.75)
    ax.set_xlabel("Input FR1 Center Frequency (GHz)")
    ax.set_ylabel("Output FR3 Center Frequency (GHz)")
    ax.set_title(title, loc="left", color=INK, fontsize=11)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(mesh, ax=ax, fraction=0.06, pad=0.03)
    cb.set_label("Sideband Suppression (dB)", color=INK2)
    cb.outline.set_edgecolor(INK)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def histogram(vals: list[float], title: str, path) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.hist(vals, bins=np.arange(0, VMAX + 2.5, 2.5), color=BAR, edgecolor="white", linewidth=0.6,
            label="In design spec (FR3 ≤ 24 GHz)")
    med = statistics.median(vals)
    ax.axvline(med, color=ACCENT, ls="--", lw=1.4, label=f"Median: {med:.1f} dB")
    ax.legend(frameon=False, fontsize=8)
    ax.set_xlim(0, VMAX)
    ax.set_xlabel("Sideband Suppression (dB)")
    ax.set_ylabel("Number of (FR1, FR3) Points")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_title(title, loc="left", color=INK, fontsize=11)
    ax.grid(color=GRID_GREY, lw=0.8)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", default="sideband_tx_20261009")
    args = ap.parse_args()
    use_plex()
    rows = list(csv.DictReader(open(unit_dir(5) / args.campaign / "points.csv", newline="")))
    temps = [float(r["lmx_temp_c"]) for r in rows]
    macros = [f"% generated by FR3_Characterization/plot_datasheet_sideband.py from {args.campaign} -- do not edit",
              f"\\newcommand{{\\sbTxMinC}}{{{min(temps):.0f}}}", f"\\newcommand{{\\sbTxMaxC}}{{{max(temps):.0f}}}"]
    for n, (side, filt) in enumerate(ORDER):
        sel = {(round(float(r["fr1_hz"]) / 1e9, 1), round(float(r["fr3_hz"]) / 1e9, 1)): float(r["suppression_db"])
               for r in rows if r["config"] == side and r["filter"] == filt}
        title = f"TX Sideband Suppression, {NAME[side]} Sideband Desired, {FILT[filt]}"
        heatmap(sel, title, IMAGES / f"sec3_fig{2 * n + 1}.pdf")
        v = sorted(x for (a, b), x in sel.items() if in_spec(a, b))
        histogram(v, title, IMAGES / f"sec3_fig{2 * n + 2}.pdf")
        t = TAG[(side, filt)]
        macros += [f"\\newcommand{{\\sb{t}Median}}{{{statistics.median(v):.0f}}}",
                   f"\\newcommand{{\\sb{t}Pten}}{{{np.percentile(v, 10):.0f}}}",
                   f"\\newcommand{{\\sb{t}Min}}{{{v[0]:.0f}}}", f"\\newcommand{{\\sb{t}Count}}{{{len(v)}}}"]
        print(f"{title}: n {len(v)}, median {statistics.median(v):.1f}, p10 {np.percentile(v, 10):.1f}, worst {v[0]:.1f}")
    (DATASHEET / "sections" / "sec_sideband_numbers.tex").write_text("\n".join(macros) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
