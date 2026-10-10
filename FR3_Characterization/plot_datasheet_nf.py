"""Datasheet figures for the RX Noise Figure and Sensitivity section, from the dense
rx_nf_campaign.py grid (results/unit_<n>/rx_nf_campaign/nf_results.csv).

    python plot_datasheet_nf.py [--unit 5] [--campaign rx_nf_optimal_20261009] [--filter optimal]

Since 2026-10-09 the datasheet shows the noise figure with the OPTIMAL filter only (user: most users engage it; the text says
the NF is lower with it bypassed). Default campaign: the hot RX re-run at the drive rule, rx_nf_optimal_20261009, whose NF
includes the FieldFox-floor and FR1-cable corrections (rx_nf_campaign.py combine). The old --legacy mode (bypassed +
optimal campaigns of 2026-10-04/05, eight figures) is kept for reference.

Writes FR3-1ch-Datasheet/images/sec12_fig{1..4}.pdf:
    1  low-side LO: NF across the full (FR1, FR3) grid      2  distribution of 1
    3  high-side LO: NF across the full (FR1, FR3) grid     4  distribution of 3
and prints the summary numbers the section text quotes. Styled to match the existing
datasheet figures (IBM Plex Sans, blue scale, grey for unmeasured cells, FR1 across /
FR3 up).
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from results_layout import unit_dir  # noqa: E402

HERE = Path(__file__).resolve().parent
DATASHEET = HERE.parent / "FR3-1ch-Datasheet"
FONTS = DATASHEET / "fonts"
IMAGES = DATASHEET / "images"

FR1_GHZ = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
FR3_GHZ = [6.0 + 0.5 * k for k in range(42)]
RATED_FR3_MAX_GHZ = 24.0


def in_spec(r: dict) -> bool:
    """Within the design spec: FR3 <= 24 GHz. NF is a CW measurement (read at a single IF frequency), so FR1 = 4.0 GHz
    is inside the 0.7-4.0 GHz IF spec -- unlike the gain sections, whose 500 MHz windows run past it (user, 2026-10-05)."""
    return r["fr3"] <= RATED_FR3_MAX_GHZ
INK, INK2, GRID_GREY, EMPTY = "#161616", "#525252", "#e0e0e0", "#dcd8d0"
ACCENT = "#c62828"
OOS_RED = "#c0392b"   # the gain heatmaps' "out of spec" box colour (RGB 0.753, 0.224, 0.169)
BAR = "#2b7bd6"
# Sensitivity-table rows (user spec 2026-10-04); 1 Hz = the "CW tone" row, quoted per 1 Hz of detection bandwidth
SENS_BW_HZ = (1.0, 1e6, 5e6, 10e6, 50e6, 100e6, 500e6)
SENS_TAGS = ("CW", "OneM", "FiveM", "TenM", "FiftyM", "HundredM", "FiveHundredM")
# Figures are shrunk to ~half size in the datasheet's two-up rows, so this prints at ~1.3 pt on the page,
# matching the zoom-to-read labels on the gain heatmaps.
CELL_LABEL_PT = 2.4
# The same campaign repeated with the per-point "optimal" RX filter engaged (2026-10-05)
OPT_CAMPAIGN = "rx_nf_filter_optimal_20261005"


def use_plex() -> None:
    for f in FONTS.glob("IBMPlexSans-*.ttf"):
        font_manager.fontManager.addfont(str(f))
    plt.rcParams.update({"font.family": "IBM Plex Sans", "axes.edgecolor": GRID_GREY,
                         "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                         "axes.titleweight": "semibold", "axes.titlesize": 12})


def load_nf(outdir: Path) -> list[dict]:
    rows = list(csv.DictReader(open(outdir / "nf_results.csv")))
    return [{"fr1": float(r["fr1_hz"]) / 1e9, "fr3": float(r["fr3_hz"]) / 1e9,
             "sideband": r["sideband"], "nf": float(r["nf_db"]),
             "margin": float(r["margin_above_ff_floor_db"])} for r in rows]


def heatmap(rows: list[dict], sideband: str, title: str, vmin: float, vmax: float, path: Path) -> None:
    grid = np.full((len(FR3_GHZ), len(FR1_GHZ)), np.nan)
    for r in rows:
        if r["sideband"] == sideband:
            grid[FR3_GHZ.index(r["fr3"]), FR1_GHZ.index(r["fr1"])] = r["nf"]
    fig, ax = plt.subplots(figsize=(6.4, 5.6))
    ax.set_facecolor(EMPTY)
    # dark = low NF (better), the same "dark is good" sense as the gain figures
    mesh = ax.pcolormesh(np.arange(len(FR1_GHZ) + 1) * 0.5 + 0.75, np.array(FR3_GHZ + [26.75]) - 0.25,
                         np.ma.masked_invalid(grid), cmap="Blues_r", vmin=vmin, vmax=vmax,
                         edgecolors=(1, 1, 1, 0.35), linewidth=0.4)
    # tiny per-cell "(FR1, FR3, NF)" labels: invisible zoomed out, readable zoomed in (same style as the
    # gain heatmaps); white on dark cells, near-black on light ones
    cmap, norm = mesh.get_cmap(), mesh.norm
    for i, fr3 in enumerate(FR3_GHZ):
        for j, fr1 in enumerate(FR1_GHZ):
            v = grid[i, j]
            if np.isnan(v):
                continue
            r, g, b, _ = cmap(norm(v))
            ink = "white" if 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.55 else INK
            ax.text(fr1, fr3, f"{fr1:.1f}, {fr3:.1f}, {v:.1f}", ha="center", va="center",
                    fontsize=CELL_LABEL_PT, color=ink)
    # out-of-spec region (FR3 above the rated 24 GHz): measured and shown, but boxed in red -- same red, tint and
    # line weight as the "Partly out of spec" box on the conversion-gain heatmaps
    y0 = RATED_FR3_MAX_GHZ + 0.25
    ax.add_patch(Rectangle((0.75, y0), 3.5, 26.75 - y0, facecolor=OOS_RED, alpha=0.08, edgecolor="none"))
    ax.add_patch(Rectangle((0.75, y0), 3.5, 26.75 - y0, facecolor="none", edgecolor=OOS_RED, lw=1.4,
                           clip_on=False))
    # label in the top-left corner of the box, which is unmeasured (grey) on both sidebands
    ax.text(0.82, 26.55, "FR3 > 24 GHz: out of design spec", color=OOS_RED, fontsize=7, ha="left", va="top",
            fontweight="semibold", linespacing=1.1)
    ax.set_xticks(FR1_GHZ)
    ax.set_xlim(0.75, 4.25)
    ax.set_ylim(5.75, 26.75)
    ax.set_xlabel("Output FR1 Center Frequency (GHz)")
    ax.set_ylabel("FR3 Input Center Frequency (GHz)")
    ax.set_title(title, loc="left", color=INK)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(mesh, ax=ax, fraction=0.06, pad=0.03)
    cb.set_label("Noise Figure (dB)", color=INK2)
    cb.outline.set_edgecolor(INK)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def histogram(rows: list[dict], sideband: str, title: str, path: Path) -> None:
    # in-spec points only (FR3 <= 24 GHz), median line only -- the same style as the flatness histograms
    # (user, 2026-10-05); the out-of-spec points stay visible, boxed in red, on the heatmaps.
    vals = [r["nf"] for r in rows if r["sideband"] == sideband and in_spec(r)]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    bins = np.arange(np.floor(min(vals)), np.ceil(max(vals)) + 0.5, 0.5)
    ax.hist(vals, bins=bins, color=BAR, edgecolor="white", linewidth=0.6, label="FR3 \u2264 24 GHz (in spec)")
    med = statistics.median(vals)
    ax.axvline(med, color=ACCENT, ls="--", lw=1.4, label=f"Median: {med:.1f}dB".replace("-", "\u2212"))
    ax.legend(frameon=False, fontsize=8)
    ax.set_xlabel("Noise Figure (dB)")
    ax.set_ylabel("Number of (FR1, FR3) Points")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_title(title, loc="left", color=INK)
    ax.grid(color=GRID_GREY, lw=0.8)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def stats(vals):
    v = sorted(vals)
    return v[0], statistics.median(v), v[int(0.9 * (len(v) - 1))], v[-1]


def write_numbers(rows: list[dict], path: Path, opt_rows: list[dict] | None = None) -> None:
    """LaTeX macros for every number the section text quotes, so text and figures can't drift."""
    lines = ["% Generated by FR3_Characterization/plot_datasheet_nf.py -- do not edit by hand."]
    in_spec_all = []
    for sb, tag in (("low", "Low"), ("high", "High")):
        vals = [r["nf"] for r in rows if r["sideband"] == sb and in_spec(r)]
        in_spec_all += vals
        mn, med, p90, mx = stats(vals)
        n_all = sum(r["sideband"] == sb for r in rows)
        for name, val in (("Min", mn), ("Median", med), ("Pninety", p90), ("Max", mx)):
            lines.append(f"\\newcommand{{\\nf{tag}{name}}}{{{val:.1f}}}")
        lines.append(f"\\newcommand{{\\nf{tag}Count}}{{{n_all}}}")
    med = statistics.median(in_spec_all)
    lines.append(f"\\newcommand{{\\nfMedian}}{{{med:.1f}}}")
    lines.append(f"\\newcommand{{\\nfCount}}{{{len(rows)}}}")
    lines.append(f"\\newcommand{{\\nfMinMargin}}{{{int(min(r['margin'] for r in rows))}}}")
    oos = sorted(r["nf"] for r in rows if not in_spec(r))
    if oos:
        lines.append(f"\\newcommand{{\\nfOosCount}}{{{len(oos)}}}")
        lines.append(f"\\newcommand{{\\nfOosMin}}{{{oos[0]:.1f}}}")
        lines.append(f"\\newcommand{{\\nfOosMedian}}{{{statistics.median(oos):.1f}}}")
        lines.append(f"\\newcommand{{\\nfOosMax}}{{{oos[-1]:.1f}}}")
    for bw, tag in zip(SENS_BW_HZ, SENS_TAGS):
        lines.append(f"\\newcommand{{\\sens{tag}}}{{{-174 + med + 10 * np.log10(bw):.1f}}}")
    if not opt_rows:                                              # the LO = 14-14.5 GHz stripe, for this campaign
        for sb, tag in (("low", "Low"), ("high", "High")):
            lines.append(f"\\newcommand{{\\nfStripe{tag}}}{{{stripe_excess(rows, sb):.1f}}}")
    if opt_rows:
        lines += opt_numbers(rows, opt_rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def opt_numbers(rows: list[dict], opt_rows: list[dict]) -> list[str]:
    """Macros \\nfOpt... for the filter-optimal campaign, and how it compares with the bypassed one point by point."""
    out = []
    key = lambda r: (r["fr1"], r["fr3"], r["sideband"])
    byp = {key(r): r for r in rows}
    in_spec_rows = [r for r in opt_rows if in_spec(r) and key(r) in byp]
    for sb, tag in (("low", "Low"), ("high", "High")):
        mn, med, p90, mx = stats([r["nf"] for r in in_spec_rows if r["sideband"] == sb])
        for name, val in (("Min", mn), ("Median", med), ("Pninety", p90), ("Max", mx)):
            out.append(f"\\newcommand{{\\nfOpt{tag}{name}}}{{{val:.1f}}}")
    inc = [r["nf"] - byp[key(r)]["nf"] for r in in_spec_rows]
    out.append(f"\\newcommand{{\\nfOptMedian}}{{{statistics.median([r['nf'] for r in in_spec_rows]):.1f}}}")
    out.append(f"\\newcommand{{\\nfOptIncMedian}}{{{statistics.median(inc):.1f}}}")
    out.append(f"\\newcommand{{\\nfOptIncMin}}{{{min(inc):.1f}}}".replace("-", "\u2212"))
    out.append(f"\\newcommand{{\\nfOptIncMax}}{{{max(inc):.1f}}}")
    out.append(f"\\newcommand{{\\nfOptIncSmallCount}}{{{sum(v < 1 for v in inc)}}}")
    out.append(f"\\newcommand{{\\nfOptIncLargeCount}}{{{sum(v > 6 for v in inc)}}}")
    out.append(f"\\newcommand{{\\nfOptInSpecCount}}{{{len(in_spec_rows)}}}")
    out.append(f"\\newcommand{{\\nfOptMinMargin}}{{{min(r['margin'] for r in opt_rows):.0f}}}")
    med_byp = statistics.median([r["nf"] for r in rows if in_spec(r)])
    med_opt = statistics.median([r["nf"] for r in in_spec_rows])
    out.append(f"\\newcommand{{\\nfOptSensShift}}{{{med_opt - med_byp:.1f}}}")
    for bw, tag in zip(SENS_BW_HZ, SENS_TAGS):                  # the sensitivity table at the filter-optimal median NF
        out.append(f"\\newcommand{{\\sensOpt{tag}}}{{{-174 + med_opt + 10 * np.log10(bw):.1f}}}")
    # the LO = 14-14.5 GHz stripe: median NF there minus the median at the neighbouring LOs (13-13.5, 15-15.5 GHz)
    for data, pre in ((rows, "nf"), (opt_rows, "nfOpt")):
        for sb, tag in (("low", "Low"), ("high", "High")):
            out.append(f"\\newcommand{{\\{pre}Stripe{tag}}}{{{stripe_excess(data, sb):.1f}}}")
    return out


def stripe_excess(rows: list[dict], sb: str) -> float:
    lo = lambda r: round(r["fr3"] - r["fr1"], 3) if r["sideband"] == "low" else round(r["fr3"] + r["fr1"], 3)
    r = [x for x in rows if x["sideband"] == sb and in_spec(x)]
    stripe = [x["nf"] for x in r if lo(x) in (14.0, 14.5)]
    near = [x["nf"] for x in r if lo(x) in (13.0, 13.5, 15.0, 15.5)]
    return statistics.median(stripe) - statistics.median(near)


def summary(rows: list[dict]) -> None:
    for sb in ("low", "high"):
        v = sorted(r["nf"] for r in rows if r["sideband"] == sb)
        if not v:
            continue
        spec_vals = [r["nf"] for r in rows if r["sideband"] == sb and in_spec(r)]
        print(f"{sb:4s}: n={len(v)}  min {v[0]:.1f}  median {statistics.median(v):.1f}  "
              f"p90 {v[int(0.9 * (len(v) - 1))]:.1f}  max {v[-1]:.1f} dB  "
              f"(<=24 GHz: n={len(spec_vals)}, median {statistics.median(spec_vals):.1f})")
    allv = [r["nf"] for r in rows if in_spec(r)]
    med = statistics.median(allv)
    print(f"\nSensitivity at the median NF ({med:.1f} dB), SNR 0 dB: "
          + ", ".join(f"{bw/1e6:g} MHz {-174 + med + 10 * np.log10(bw):.1f} dBm" for bw in SENS_BW_HZ[1:])
          + f", CW (per Hz) {-174 + med:.1f} dBm/Hz")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--unit", type=int, default=5)
    p.add_argument("--campaign", default="rx_nf_optimal_20261009")
    p.add_argument("--filter", choices=("optimal", "bypass"), default="optimal", help="filter setting of --campaign (titles)")
    p.add_argument("--legacy", action="store_true", help="the old two-campaign layout (bypassed + optimal, 8 figures)")
    args = p.parse_args()
    use_plex()
    if not args.legacy:
        rows = load_nf(unit_dir(args.unit) / args.campaign)
        word = "Optimal" if args.filter == "optimal" else "Bypassed"
        v = [r["nf"] for r in rows]
        vmin, vmax = np.floor(min(v)), np.ceil(np.percentile(v, 98))
        for n, (sb, name) in enumerate((("low", "Low-Side LO"), ("high", "High-Side LO"))):
            heatmap(rows, sb, f"RX Noise Figure, {name}, Filter {word}", vmin, vmax, IMAGES / f"sec12_fig{2 * n + 1}.pdf")
            histogram(rows, sb, f"RX Noise Figure, {name}, Filter {word}", IMAGES / f"sec12_fig{2 * n + 2}.pdf")
        for k in range(5, 9):                                        # the old optimal-filter figures: no longer used
            (IMAGES / f"sec12_fig{k}.pdf").unlink(missing_ok=True)
        summary(rows)
        write_numbers(rows, DATASHEET / "sections" / "sec12_numbers.tex")
        print(f"{args.campaign}: written sec12_fig1-4.pdf and sec12_numbers.tex")
        return 0
    rows = load_nf(unit_dir(args.unit) / "rx_nf_campaign")
    opt_dir = unit_dir(args.unit) / OPT_CAMPAIGN
    opt_rows = load_nf(opt_dir) if (opt_dir / "nf_results.csv").exists() else []
    # one colour scale for the bypassed AND filter-optimal heatmaps, so the two can be compared by eye
    every = [r["nf"] for r in rows + opt_rows]
    vmin, vmax = np.floor(min(every)), np.ceil(np.percentile(every, 98))
    IMAGES.mkdir(exist_ok=True)
    heatmap(rows, "low", "RX Noise Figure, Low-Side LO, Filter Bypassed", vmin, vmax, IMAGES / "sec12_fig1.pdf")
    histogram(rows, "low", "RX Noise Figure, Low-Side LO, Filter Bypassed", IMAGES / "sec12_fig2.pdf")
    heatmap(rows, "high", "RX Noise Figure, High-Side LO, Filter Bypassed", vmin, vmax, IMAGES / "sec12_fig3.pdf")
    histogram(rows, "high", "RX Noise Figure, High-Side LO, Filter Bypassed", IMAGES / "sec12_fig4.pdf")
    if opt_rows:
        heatmap(opt_rows, "low", "RX Noise Figure, Low-Side LO, Filter Optimal", vmin, vmax, IMAGES / "sec12_fig5.pdf")
        histogram(opt_rows, "low", "RX Noise Figure, Low-Side LO, Filter Optimal", IMAGES / "sec12_fig6.pdf")
        heatmap(opt_rows, "high", "RX Noise Figure, High-Side LO, Filter Optimal", vmin, vmax, IMAGES / "sec12_fig7.pdf")
        histogram(opt_rows, "high", "RX Noise Figure, High-Side LO, Filter Optimal", IMAGES / "sec12_fig8.pdf")
    summary(rows)
    write_numbers(rows, DATASHEET / "sections" / "sec12_numbers.tex", opt_rows)
    print("written", ", ".join(f"sec12_fig{k}.pdf" for k in range(1, 9 if opt_rows else 5)), "to", IMAGES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
