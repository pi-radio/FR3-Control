"""Linearity check between two LO x IF campaigns of the same unit at different drive levels.

    python plot_lo_map_linearity.py [hi-drive campaign folder] [lo-drive campaign folder] [--open]

Defaults to the unit-5 -40 dBm and -50 dBm campaigns. For each of the two desired-sideband series it maps
    gain(high drive) - gain(low drive)
(dB). Around 0 dB the chain is linear at the higher drive; negative = compression at the higher drive; positive = gain
expansion (the ADL9006 behaviour) at the higher drive. Cells within 10 dB of the noise floor in either campaign are gray.
Writes linearity_<hi>_vs_<lo>.png next to the high-drive campaign. Local only."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import matplotlib
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from lo_map_data import LoMap, load_campaign  # noqa: E402
from plot_lo_map import draw_map  # noqa: E402
from plot_power_sweep import BLUE, INK, INK2, MUTED, ORANGE, SURFACE, fmt, style_axes  # noqa: E402
from results_layout import unit_dir  # noqa: E402

# diverging: orange (compression) - light neutral - blue (expansion), from the reference palette
DIV = LinearSegmentedColormap.from_list("div", [ORANGE, "#f4c3a8", "#f1f0ea", "#a9cdf5", BLUE])
DIV.set_bad("#d6d5cd")


def difference(hi: LoMap, lo: LoMap, key) -> np.ndarray:
    d = hi.gain[key] - lo.gain[key]
    d[hi.near_floor[key] | lo.near_floor[key]] = np.nan
    return d


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("hi", nargs="?", type=Path, default=unit_dir(5) / "lo_if_map_20260923")
    parser.add_argument("lo", nargs="?", type=Path, default=unit_dir(5) / "lo_if_map_20260923_drive-50dBm")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    hi, lo = load_campaign(args.hi), load_campaign(args.lo)
    assert np.array_equal(hi.lo_hz, lo.lo_hz) and np.array_equal(hi.if_hz, lo.if_hz), "campaigns have different grids"
    dh, dl = hi.settings["drive_dbm"], lo.settings["drive_dbm"]

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.9), sharex=True, sharey=True)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.07, right=0.90, top=0.76, bottom=0.13, wspace=0.08)
    im = None
    for ax, (iq, tone) in zip(axes, (("THRU", "upper"), ("SWAP", "lower"))):
        d = difference(hi, lo, (iq, tone))
        im = draw_map(ax, hi, d, -3.0, 3.0, f"IQ {iq}: desired = {tone} sideband")
        im.set_cmap(DIV)
        v = d[np.isfinite(d)]
        ax.text(0.02, 0.03, f"median {np.median(v):+.2f} dB;  {100 * np.mean(v < -1):.1f} % of cells below −1 dB, "
                f"{100 * np.mean(v > 1):.1f} % above +1 dB", transform=ax.transAxes, fontsize=10, color=INK,
                bbox={"facecolor": SURFACE, "edgecolor": "none", "alpha": 0.85, "pad": 3}, ha="left", va="bottom")
        ax.set_xlabel("IF frequency (GHz)", fontsize=11, labelpad=8)
    axes[0].set_ylabel("LO frequency (GHz)", fontsize=11, labelpad=8)
    cax = fig.add_axes([0.915, 0.13, 0.016, 0.63])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label(f"Gain at {fmt(dh, 0)} dBm drive minus gain at {fmt(dl, 0)} dBm drive (dB)", fontsize=10.5, color=INK2)
    cb.ax.tick_params(colors=MUTED, labelsize=10)
    cb.outline.set_visible(False)
    fig.text(0.07, 0.935, "FR3 1CH rev 1.4: is the LO x IF gain map linear?", fontsize=16, color=INK, fontweight="semibold",
             ha="left", va="center")
    fig.text(0.07, 0.885, f"Desired-sideband gain difference between two campaigns, {fmt(dh, 0)} vs {fmt(dl, 0)} dBm drive. "
             "Orange = compression at the higher drive, blue = gain expansion. Gray = a tone within 10 dB of the noise floor.",
             fontsize=10.5, color=INK2, ha="left", va="center")
    out = args.hi / f"linearity_{args.hi.name}_vs_{args.lo.name}.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    print(f"Saved {out}")

    # numbers for the report
    for iq, tone in (("THRU", "upper"), ("SWAP", "lower")):
        d = difference(hi, lo, (iq, tone))
        g = lo.gain[(iq, tone)]
        print(f"{iq} {tone}: median diff {np.nanmedian(d):+.2f} dB, 5th/95th pct {np.nanpercentile(d, 5):+.2f}/{np.nanpercentile(d, 95):+.2f}")
        for lo_edge, hi_edge in ((-np.inf, 30), (30, 40), (40, 45), (45, 50), (50, np.inf)):
            sel = (g >= lo_edge) & (g < hi_edge) & np.isfinite(d)
            if sel.sum():
                print(f"   gain(-50 dBm map) in [{lo_edge:g},{hi_edge:g}) dB: n={sel.sum():6d}  median diff {np.median(d[sel]):+.2f}  "
                      f"5th {np.percentile(d[sel], 5):+.2f}  95th {np.percentile(d[sel], 95):+.2f}")
    if args.open:
        os.startfile(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
