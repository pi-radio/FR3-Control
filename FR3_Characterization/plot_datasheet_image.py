"""Datasheet figures for RX image rejection (Section 16), from an rx_image_campaign.py run (CW tones at the desired FR3 and at
the image, same input level; rejection = output(desired) - output(image), cables removed).

    python plot_datasheet_image.py [--campaign image_rx_20261009]

Writes FR3-1ch-Datasheet/images/sec11_fig{1..8}.pdf, in the order (low, bypassed), (low, optimal), (high, bypassed),
(high, optimal): a heatmap over the (FR1, FR3) grid (zoom-to-read cell labels, FR3 > 24 GHz boxed in red) and a histogram of
the in-spec points (FR3 <= 24 GHz; CW, so FR1 = 4.0 GHz is in spec, as for TX sideband suppression) with the median marked.
Also FR3-1ch-Datasheet/sections/sec_image_numbers.tex: medians, 10th percentiles, worst values and counts per (side, filter),
and the positions (fractions of the image, for the TikZ overlay) of the two low-side cells with LO = 2 x FR1 that the
section's footnote discusses, on the optimal-filter heatmap (Figure 16.3).
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
VMIN, VMAX = -10.0, 80.0
ORDER = [("low", "bypass"), ("low", "optimal"), ("high", "bypass"), ("high", "optimal")]
NAME = {"low": "Low-Side LO", "high": "High-Side LO"}
FILT = {"bypass": "Filter Bypassed", "optimal": "Filter Optimal"}
TAG = {("low", "bypass"): "LowBypass", ("low", "optimal"): "LowOptimal", ("high", "bypass"): "HighBypass",
       ("high", "optimal"): "HighOptimal"}
OUTLIERS = [(3.5, 10.5), (4.0, 12.0)]       # low-side, LO = 2 x FR1 (7 and 8 GHz): the footnote's two points


def in_spec(fr1: float, fr3: float) -> bool:
    return fr3 <= 24.0 + 1e-9


def heatmap(sel: dict, title: str, path, mark: list | None = None) -> list[tuple[float, float]]:
    """Returns, for each cell in `mark`, its centre as fractions (x from the left, y from the bottom) of the saved image."""
    grid = np.full((len(FR3_GHZ), len(FR1_GHZ)), np.nan)
    for (fr1, fr3), v in sel.items():
        grid[FR3_GHZ.index(fr3), FR1_GHZ.index(fr1)] = v
    fig, ax = plt.subplots(figsize=(6.4, 3.1))            # short, so all eight figures fit on one page
    ax.set_facecolor(EMPTY)
    mesh = ax.pcolormesh(np.arange(len(FR1_GHZ) + 1) * 0.5 + 0.75, np.array(FR3_GHZ + [26.75]) - 0.25,
                         np.ma.masked_invalid(grid), cmap="viridis", vmin=VMIN, vmax=VMAX, edgecolors=(1, 1, 1, 0.35),
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
    ax.set_xlabel("Output FR1 Center Frequency (GHz)")
    ax.set_ylabel("Input FR3 Center Frequency (GHz)")
    ax.set_title(title, loc="left", color=INK, fontsize=11)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(mesh, ax=ax, fraction=0.06, pad=0.03)
    cb.set_label("Image Rejection (dB)", color=INK2)
    cb.outline.set_edgecolor(INK)
    fig.canvas.draw()
    bbox = fig.get_tightbbox(fig.canvas.get_renderer()).padded(0.1)       # what bbox_inches="tight" saves (pad 0.1 in)
    pos = []
    for fr1, fr3 in mark or []:
        x_in, y_in = ax.transData.transform((fr1, fr3)) / fig.dpi
        pos.append(((x_in - bbox.x0) / bbox.width, (y_in - bbox.y0) / bbox.height))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return pos


def histogram(vals: list[float], title: str, path) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 3.1))
    ax.hist(vals, bins=np.arange(VMIN, VMAX + 2.5, 2.5), color=BAR, edgecolor="white", linewidth=0.6,
            label="In design spec (FR3 ≤ 24 GHz)")
    med = statistics.median(vals)
    ax.axvline(med, color=ACCENT, ls="--", lw=1.4, label=f"Median: {med:.1f} dB")
    ax.legend(frameon=False, fontsize=8)
    ax.set_xlim(VMIN, VMAX)
    ax.set_xlabel("Image Rejection (dB)")
    ax.set_ylabel("Number of (FR1, FR3) Points")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_title(title, loc="left", color=INK, fontsize=11)
    ax.grid(color=GRID_GREY, lw=0.8)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def m(v: float) -> str:
    return f"{v:.0f}".replace("-", "−")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", default="image_rx_20261009")
    args = ap.parse_args()
    use_plex()
    rows = list(csv.DictReader(open(unit_dir(5) / args.campaign / "points.csv", newline="")))
    macros = [f"% generated by FR3_Characterization/plot_datasheet_image.py from {args.campaign} -- do not edit"]
    for n, (side, filt) in enumerate(ORDER):
        sel = {(round(float(r["fr1_hz"]) / 1e9, 1), round(float(r["fr3_hz"]) / 1e9, 1)): float(r["rejection_db"])
               for r in rows if r["config"] == side and r["filter"] == filt}
        title = f"RX Image Rejection, {NAME[side]}, {FILT[filt]}"
        mark = OUTLIERS if (side, filt) == ("low", "optimal") else None
        pos = heatmap(sel, title, IMAGES / f"sec11_fig{2 * n + 1}.pdf", mark)
        for k, (x, y) in enumerate(pos):
            macros += [f"\\newcommand{{\\imgOutlier{'AB'[k]}X}}{{{x:.4f}}}", f"\\newcommand{{\\imgOutlier{'AB'[k]}Y}}{{{y:.4f}}}"]
        v = sorted(x for (a, b), x in sel.items() if in_spec(a, b))
        histogram(v, title, IMAGES / f"sec11_fig{2 * n + 2}.pdf")
        t = TAG[(side, filt)]
        macros += [f"\\newcommand{{\\img{t}Median}}{{{m(statistics.median(v))}}}",
                   f"\\newcommand{{\\img{t}Pten}}{{{m(np.percentile(v, 10))}}}",
                   f"\\newcommand{{\\img{t}Min}}{{{m(v[0])}}}", f"\\newcommand{{\\img{t}Count}}{{{len(v)}}}"]
        print(f"{title}: n {len(v)}, median {statistics.median(v):.1f}, p10 {np.percentile(v, 10):.1f}, worst {v[0]:.1f}")
    (DATASHEET / "sections" / "sec_image_numbers.tex").write_text("\n".join(macros) + "\n", encoding="utf-8")
    print("\n".join(macros))


if __name__ == "__main__":
    main()
