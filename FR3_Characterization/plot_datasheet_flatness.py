"""Datasheet figures for in-channel gain flatness (user spec 2026-10-05): heatmaps and histograms only.

    python plot_datasheet_flatness.py [--unit 5] [--tx-campaign flatness_tx_YYYYMMDD] [--rx-campaign flatness_rx_YYYYMMDD]

For each chain (TX: upper / lower sideband; RX: low-side / high-side LO) and each filter (bypassed / optimal): one
heatmap of the flatness (RMS deviation of the gain from the window's RMS power level, dB) over the (FR1, FR3) grid, and its
histogram (in-spec points only, median marked) -- 16 figures, images/flat_<chain>_<config>_<filter>_{map,hist}.pdf, plus sections/flatness_numbers.tex.
Styled like the NF figures (IBM Plex, darker = better, grey = not measured). Out-of-spec points are shown and boxed in
red, as on the gain heatmaps: FR3 > 24 GHz, and the FR1 = 4.0 GHz column, whose 3.75-4.25 GHz window runs 250 MHz past
the 0.7-4.0 GHz IF spec ("partly out of design spec"). Statistics are over in-spec points only (FR3 <= 24, FR1 <= 3.5).
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
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from plot_datasheet_nf import (BAR, CELL_LABEL_PT, DATASHEET, EMPTY, GRID_GREY, IMAGES, INK, INK2, OOS_RED,  # noqa: E402
                               use_plex)
from results_layout import unit_dir  # noqa: E402

FR1_GHZ = [1.0 + 0.5 * k for k in range(7)]
FR3_GHZ = [6.0 + 0.5 * k for k in range(42)]
FR3_MAX, FR1_MAX = 24.0, 3.5
SCALE_MAX_DB = 4.0     # heatmap colour bars fixed at 0-4 dB (user, 2026-10-05)
HIST_BIN_DB = 0.25     # histogram bin width (user, 2026-10-05)
HIST_X_MAX = {"rx": 4.0}               # fixed x-axis (dB) where set; otherwise it ends at the data (user, 2026-10-05)
HIST_Y_MAX = {"tx": 35, "rx": 60}   # count axis per chain, same on all four of a chain's histograms (user, 2026-10-05)
NAMES = {("tx", "upper"): ("TX", "Upper Sideband"), ("tx", "lower"): ("TX", "Lower Sideband"),
         ("rx", "low"): ("RX", "Low-Side LO"), ("rx", "high"): ("RX", "High-Side LO")}
FILT = {"bypass": "Filter Bypassed", "optimal": "Filter Optimal"}
CONFIGS_OF = {"tx": ("upper", "lower"), "rx": ("low", "high")}
TABLE_NAMES = {"upper": "Upper sideband", "lower": "Lower sideband", "low": "Low-side LO", "high": "High-side LO"}
MINUS = "−"


def in_spec(r) -> bool:
    return r["fr3"] <= FR3_MAX and r["fr1"] <= FR1_MAX


def rms_flatness(gain_db: np.ndarray) -> float:
    """Flatness metric (user, 2026-10-05): RMS deviation in dB of the gain from the window's RMS power level
    (10 log10 of the mean linear power gain across the 500 MHz window)."""
    ref = 10 * np.log10(np.mean(10 ** (gain_db / 10)))
    return float(np.sqrt(np.mean((gain_db - ref) ** 2)))


def load(path: Path) -> list[dict]:
    rows = [r for r in csv.DictReader(open(path / "points.csv", newline="")) if r["status"] == "ok"]
    gains: dict[str, list[float]] = {}
    for t in csv.DictReader(open(path / "traces.csv", newline="")):
        gains.setdefault(t["key"], []).append(float(t["gain_db"]))
    return [{"chain": r["chain"], "config": r["config"], "filter": r["filter"], "fr1": float(r["fr1_hz"]) / 1e9,
             "fr3": float(r["fr3_hz"]) / 1e9, "flat": rms_flatness(np.array(gains[r["key"]])),
             "pp": float(np.ptp(gains[r["key"]]))} for r in rows]


def heatmap(rows, title, vmin, vmax, path, fr1_axis_label, fr3_axis_label):
    grid = np.full((len(FR3_GHZ), len(FR1_GHZ)), np.nan)
    for r in rows:
        grid[FR3_GHZ.index(r["fr3"]), FR1_GHZ.index(r["fr1"])] = r["flat"]
    fig, ax = plt.subplots(figsize=(6.4, 5.6))
    ax.set_facecolor(EMPTY)
    mesh = ax.pcolormesh(np.arange(len(FR1_GHZ) + 1) * 0.5 + 0.75, np.array(FR3_GHZ + [26.75]) - 0.25,
                         np.ma.masked_invalid(grid), cmap="Blues_r", vmin=vmin, vmax=vmax,
                         edgecolors=(1, 1, 1, 0.35), linewidth=0.4)
    cmap, norm = mesh.get_cmap(), mesh.norm
    for i, fr3 in enumerate(FR3_GHZ):
        for j, fr1 in enumerate(FR1_GHZ):
            v = grid[i, j]
            if np.isnan(v):
                continue
            r_, g_, b_, _ = cmap(norm(v))
            ink = "white" if 0.2126 * r_ + 0.7152 * g_ + 0.0722 * b_ < 0.55 else INK
            ax.text(fr1, fr3, f"{fr1:.1f}, {fr3:.1f}, {v:.2f}", ha="center", va="center", fontsize=CELL_LABEL_PT, color=ink)
    y0 = FR3_MAX + 0.25                                   # FR3 > 24 GHz: out of design spec
    ax.add_patch(Rectangle((0.75, y0), 3.5, 26.75 - y0, facecolor=OOS_RED, alpha=0.08, edgecolor="none"))
    ax.add_patch(Rectangle((0.75, y0), 3.5, 26.75 - y0, facecolor="none", edgecolor=OOS_RED, lw=1.4, clip_on=False))
    ax.text(0.82, 26.55, "FR3 > 24 GHz: out of design spec", color=OOS_RED, fontsize=7, ha="left", va="top",
            fontweight="semibold")
    x0 = FR1_GHZ[-1] - 0.25                               # FR1 = 4 GHz: the 500 MHz window runs past the IF spec
    ax.add_patch(Rectangle((x0, 5.75), 0.5, 21.0, facecolor=OOS_RED, alpha=0.08, edgecolor="none"))
    ax.add_patch(Rectangle((x0, 5.75), 0.5, 21.0, facecolor="none", edgecolor=OOS_RED, lw=1.4, clip_on=False))
    col = grid[:, -1]
    runs, start = [], None
    for i, v in enumerate(list(col) + [0.0]):
        if np.isnan(v) and start is None:
            start = i
        elif not np.isnan(v) and start is not None:
            runs.append((start, i - 1))
            start = None
    a, b = max(runs, key=lambda r: r[1] - r[0]) if runs else (0, 0)
    ax.text(FR1_GHZ[-1], (FR3_GHZ[a] + FR3_GHZ[b]) / 2, "Partly out\nof design\nspec", color=OOS_RED, fontsize=7,
            ha="center", va="center", fontweight="semibold", linespacing=1.1)
    ax.set_xticks(FR1_GHZ)
    ax.set_xlim(0.75, 4.25)
    ax.set_ylim(5.75, 26.75)
    ax.set_xlabel(fr1_axis_label)
    ax.set_ylabel(fr3_axis_label)
    ax.set_title(title, loc="left", color=INK)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(mesh, ax=ax, fraction=0.06, pad=0.03)
    cb.set_label("Gain Flatness, RMS across 500 MHz (dB)", color=INK2)
    cb.outline.set_edgecolor(INK)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def histogram(rows, title, path, y_max, x_max=None):
    vals = [r["flat"] for r in rows if in_spec(r)]          # in design spec only (FR3 <= 24 GHz, FR1 <= 3.5 GHz)
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    top = x_max if x_max is not None else np.ceil(max(vals) * 4) / 4
    bins = np.arange(0, top + HIST_BIN_DB / 2 + (0 if x_max else HIST_BIN_DB / 2), HIST_BIN_DB)
    counts, _, _ = ax.hist(vals, bins=bins, color=BAR, edgecolor="white", linewidth=0.6,
            label="In design spec (FR3 ≤ 24 GHz, FR1 ≤ 3.5 GHz)")
    med = statistics.median(vals)
    ax.axvline(med, color="#c62828", ls="--", lw=1.4, label=f"Median: {med:.2f}dB")
    ax.legend(frameon=False, fontsize=8)
    ax.set_xlabel("Gain Flatness, RMS across 500 MHz (dB)")
    ax.set_ylabel("Number of (FR1, FR3) Points")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylim(0, y_max)
    if x_max is not None:
        ax.set_xlim(0, x_max)
    if counts.max() > y_max:
        print(f"*** WARNING: {title}: a bin holds {counts.max():.0f} points, above the fixed y-limit {y_max}")
    ax.set_title(title, loc="left", color=INK)
    ax.grid(color=GRID_GREY, lw=0.8)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=5)
    ap.add_argument("--tx-campaign", default=None)
    ap.add_argument("--rx-campaign", default=None)
    args = ap.parse_args()
    use_plex()
    base = unit_dir(args.unit)
    rows = []
    for chain, camp in (("tx", args.tx_campaign), ("rx", args.rx_campaign)):
        if camp is None:
            found = sorted(base.glob(f"flatness_{chain}_*"))
            camp = found[-1].name if found else None
        if camp and (base / camp / "points.csv").exists():
            rows += load(base / camp)
            print(f"{chain}: {camp}")
    if not rows:
        print("no flatness data yet")
        return 1
    every = [r["flat"] for r in rows]
    vmin, vmax = 0.0, SCALE_MAX_DB                       # one fixed colour scale for all 8 heatmaps
    macros = ["% Generated by FR3_Characterization/plot_datasheet_flatness.py -- do not edit by hand."]
    for (chain, config), (cname, cdesc) in NAMES.items():
        for filt in ("bypass", "optimal"):
            sel = [r for r in rows if r["chain"] == chain and r["config"] == config and r["filter"] == filt]
            tag = f"flat{chain.capitalize()}{config.capitalize()}{filt.capitalize()}"
            if not sel:                                  # not measured yet: placeholders so the datasheet compiles
                for name in ("Median", "Pninety", "Min", "Max"):
                    macros.append(f"\\newcommand{{\\{tag}{name}}}{{\\textbf{{??}}}}")
                continue
            title = f"{cname} Gain Flatness, {cdesc}, {FILT[filt]}"
            if chain == "tx":
                xl, yl = "Input FR1 Center Frequency (GHz)", "FR3 Output Center Frequency (GHz)"
            else:
                xl, yl = "Output FR1 Center Frequency (GHz)", "FR3 Input Center Frequency (GHz)"
            stem = f"flat_{chain}_{config}_{filt}"
            heatmap(sel, title, vmin, vmax, IMAGES / f"{stem}_map.pdf", xl, yl)
            histogram(sel, title, IMAGES / f"{stem}_hist.pdf", HIST_Y_MAX[chain], HIST_X_MAX.get(chain))
            v = sorted(r["flat"] for r in sel if in_spec(r))
            for name, val in (("Median", statistics.median(v)), ("Pninety", v[int(0.9 * (len(v) - 1))]),
                              ("Min", v[0]), ("Max", v[-1])):
                macros.append(f"\\newcommand{{\\{tag}{name}}}{{{val:.2f}}}")
            print(f"{title}: n={len(v)} in spec, median {statistics.median(v):.2f}, p90 {v[int(0.9 * (len(v) - 1))]:.2f}, "
                  f"max {v[-1]:.2f} dB")
    for chain in ("tx", "rx"):                       # how peak-to-peak relates to RMS, for the reader's intuition
        ratio = [r["pp"] / r["flat"] for r in rows if r["chain"] == chain and in_spec(r) and r["flat"] > 0]
        tag = f"flat{chain.capitalize()}PpRatio"
        if ratio:
            macros += [f"\\newcommand{{\\{tag}}}{{{np.median(ratio):.1f}}}",
                       f"\\newcommand{{\\{tag}Low}}{{{np.percentile(ratio, 10):.1f}}}",
                       f"\\newcommand{{\\{tag}High}}{{{np.percentile(ratio, 90):.1f}}}"]
        else:
            macros += [f"\\newcommand{{\\{tag}{x}}}{{\\textbf{{??}}}}" for x in ("", "Low", "High")]
    (DATASHEET / "sections" / "flatness_numbers.tex").write_text("\n".join(macros) + "\n", encoding="utf-8")
    for chain in ("tx", "rx"):
        write_by_fr1(rows, chain, DATASHEET / "sections" / f"flatness_{chain}_by_fr1.tex")
    return 0


def write_by_fr1(rows, chain, path) -> None:
    """Table: median RMS flatness per FR1 centre (over FR3 <= 24 GHz), one column per configuration and filter."""
    cols = [(config, filt) for config in CONFIGS_OF[chain] for filt in ("bypass", "optimal")]
    head = " & ".join(f"{TABLE_NAMES[c]}, {('bypassed' if f == 'bypass' else 'optimal')}" for c, f in cols)
    lines = ["% Generated by FR3_Characterization/plot_datasheet_flatness.py -- do not edit by hand.",
             "\\begin{tabular}{l" + "c" * len(cols) + "}", "\\toprule",
             f"FR1 centre & {head} \\\\", "\\midrule"]
    for fr1 in FR1_GHZ:
        cells = []
        for c, f in cols:
            v = [r["flat"] for r in rows if r["chain"] == chain and r["config"] == c and r["filter"] == f
                 and r["fr1"] == fr1 and r["fr3"] <= FR3_MAX]
            cells.append(f"{statistics.median(v):.2f}\\,dB" if v else "\\textbf{??}")
        mark = "\\textsuperscript{*}" if fr1 > FR1_MAX else ""
        lines.append(f"{fr1:.1f}\\,GHz{mark} & " + " & ".join(cells) + " \\\\")
    lines += ["\\bottomrule",
              f"\\multicolumn{{{len(cols) + 1}}}{{l}}{{\\footnotesize\\textsuperscript{{*}}Its 500\\,MHz window "
              f"(3.75--4.25\\,GHz) runs 250\\,MHz past the IF design spec.}}",
              "\\end{tabular}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
