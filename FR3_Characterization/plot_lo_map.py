"""Figures from a lo_map.py campaign (see lo_map_data.py).

    python plot_lo_map.py [campaign folder] [--open]

Writes three PNGs into the campaign folder:
  A  gain maps: conversion gain of the desired and undesired sideband vs. (IF, LO), one row per IQ state
  B  sideband-suppression maps (desired minus undesired gain), one panel per IQ state
  C  desired-sideband gain vs. RF frequency at three fixed IF frequencies, one row per IQ state
Cells within 10 dB of the analyzer's noise floor are drawn in flat gray (the gain there is not trustworthy).
Local only; --open shows them in the default image viewer."""

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

from lo_map_data import KEYS, LoMap, load_campaign, newest_campaign  # noqa: E402
from plot_power_sweep import BLUE, INK, INK2, MUTED, ORANGE, SURFACE, fmt, style_axes  # noqa: E402

# one-hue sequential ramp (reference palette, blue steps 100 -> 700), light = low
SEQ = LinearSegmentedColormap.from_list("blue_seq", ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"])
SEQ.set_bad("#d6d5cd")   # masked cells: flat neutral gray
AQUA = "#1baf7a"
ACTIVE = {"cmap": SEQ, "tag": ""}   # colormap used by draw_map; main() switches it with --cmap


GAIN_RANGE = (10.0, 55.0)           # dB shown by the gain-map color scale


def use_colormap(name: str) -> None:
    """'blue' = the original one-hue ramp; anything else is a matplotlib colormap name (e.g. viridis, turbo, magma)."""
    if name == "blue":
        ACTIVE.update(cmap=SEQ, tag="")
        return
    cm = matplotlib.colormaps[name].copy()
    cm.set_bad("#d6d5cd")
    ACTIVE.update(cmap=cm, tag=f"_{name}")


def draw_map(ax, m: LoMap, z: np.ndarray, vmin: float, vmax: float, title: str):
    step_if = float(m.if_hz[1] - m.if_hz[0])
    step_lo = float(m.lo_hz[1] - m.lo_hz[0])
    extent = ((m.if_hz[0] - step_if / 2) / 1e9, (m.if_hz[-1] + step_if / 2) / 1e9,
              (m.lo_hz[0] - step_lo / 2) / 1e9, (m.lo_hz[-1] + step_lo / 2) / 1e9)
    im = ax.imshow(np.ma.masked_invalid(z), origin="lower", aspect="auto", extent=extent, cmap=ACTIVE["cmap"], vmin=vmin, vmax=vmax,
                   interpolation="nearest")
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=10, length=3)
    ax.set_title(title, loc="left", fontsize=11.5, color=INK, fontweight="semibold", pad=8)
    return im


def fig_gain_maps(m: LoMap, folder: Path) -> Path:
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 10.4), sharex=True, sharey=True)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.07, right=0.90, top=0.86, bottom=0.075, wspace=0.08, hspace=0.24)
    layout = [("THRU", "upper", "lower"), ("SWAP", "lower", "upper")]
    im = None
    for r, (iq, want, other) in enumerate(layout):
        for c, (tone, role) in enumerate(((want, "Desired"), (other, "Undesired (image)"))):
            k = (iq, tone)
            z = np.where(m.near_floor[k], np.nan, m.gain[k])
            im = draw_map(axes[r][c], m, z, GAIN_RANGE[0], GAIN_RANGE[1], f"IQ {iq}: {role}, {tone} sideband (RF = LO {'+' if tone == 'upper' else '−'} IF)")
    for ax in axes[:, 0]:
        ax.set_ylabel("LO frequency (GHz)", fontsize=11, labelpad=8)
    for ax in axes[1, :]:
        ax.set_xlabel("IF frequency (GHz)", fontsize=11, labelpad=8)
    cax = fig.add_axes([0.915, 0.075, 0.016, 0.785])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label(f"Conversion gain (dB); values outside {GAIN_RANGE[0]:g} to {GAIN_RANGE[1]:g} dB are clipped to the end colors",
                 fontsize=10.5, color=INK2)
    cb.ax.tick_params(colors=MUTED, labelsize=10)
    cb.outline.set_visible(False)
    fig.text(0.07, 0.955, f"FR3 1CH rev 1.4, unit #{m.folder.parent.name[-3:].lstrip('0')}: conversion gain across the LO x IF plane",
             fontsize=16, color=INK, fontweight="semibold", ha="left", va="center")
    fig.text(0.07, 0.915, f"LO {m.lo_hz[0] / 1e9:g}–{m.lo_hz[-1] / 1e9:g} GHz in {(m.lo_hz[1] - m.lo_hz[0]) / 1e6:g} MHz steps, IF "
             f"{m.if_hz[0] / 1e9:g}–{m.if_hz[-1] / 1e9:g} GHz in {(m.if_hz[1] - m.if_hz[0]) / 1e6:g} MHz steps; constant "
             f"{fmt(m.settings['drive_dbm'], 0)} dBm drive, TX filter in bypass. Gray cells are within 10 dB of the analyzer's noise floor.",
             fontsize=10.5, color=INK2, ha="left", va="center")
    fig.text(0.07, 0.022, "Corrected to the board's connectors for cable loss (uncalibrated FieldFox S21). I/Q bias at each LO from the shipped "
             "LO-null table. Each cell is one point of one tracking-generator sweep.", fontsize=8.8, color=MUTED, ha="left", va="center")
    out = folder / f"map_A_gain_{folder.name}{ACTIVE['tag']}.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return out


def fig_suppression(m: LoMap, folder: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.9), sharex=True, sharey=True)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.07, right=0.90, top=0.76, bottom=0.13, wspace=0.08)
    im = None
    for ax, iq, want in zip(axes, ("THRU", "SWAP"), ("upper", "lower")):
        s = m.suppression(iq)
        im = draw_map(ax, m, s, 0.0, 40.0, f"IQ {iq}: desired = {want} sideband")
        ax.text(0.02, 0.03, f"median {np.nanmedian(s):.1f} dB;  10% of cells below {np.nanpercentile(s, 10):.1f} dB, "
                f"90% below {np.nanpercentile(s, 90):.1f} dB", transform=ax.transAxes, fontsize=10, color=INK,
                bbox={"facecolor": SURFACE, "edgecolor": "none", "alpha": 0.85, "pad": 3}, ha="left", va="bottom")
        ax.set_xlabel("IF frequency (GHz)", fontsize=11, labelpad=8)
    axes[0].set_ylabel("LO frequency (GHz)", fontsize=11, labelpad=8)
    cax = fig.add_axes([0.915, 0.13, 0.016, 0.63])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("Sideband suppression (dB), desired minus undesired", fontsize=10.5, color=INK2)
    cb.ax.tick_params(colors=MUTED, labelsize=10)
    cb.outline.set_visible(False)
    fig.text(0.07, 0.935, "FR3 1CH rev 1.4: sideband suppression across the LO x IF plane", fontsize=16, color=INK,
             fontweight="semibold", ha="left", va="center")
    fig.text(0.07, 0.885, "Suppression = desired-sideband gain minus undesired-sideband gain at the same LO and IF (both measured, "
             "cable-corrected). Gray = either tone within 10 dB of the noise floor.", fontsize=10.5, color=INK2, ha="left", va="center")
    out = folder / f"map_B_suppression_{folder.name}{ACTIVE['tag']}.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return out


def fig_vs_rf(m: LoMap, folder: Path) -> Path:
    fig, axes = plt.subplots(2, 1, figsize=(13.5, 9.4))
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.83, bottom=0.085, hspace=0.30)
    colors = {1.0: BLUE, 2.0: ORANGE, 3.0: AQUA}
    for ax, (iq, tone, sign) in zip(axes, (("THRU", "upper", 1), ("SWAP", "lower", -1))):
        style_axes(ax)
        k = (iq, tone)
        for g_if, color in colors.items():
            j = int(np.argmin(abs(m.if_hz - g_if * 1e9)))
            rf = m.rf[k][:, j] / 1e9
            o = np.argsort(rf)
            ax.plot(rf[o], m.gain[k][o, j], color=color, linewidth=2, solid_joinstyle="round", label=f"IF {g_if:g} GHz")
        ax.set_ylabel("Conversion gain (dB)", fontsize=11, labelpad=8)
        ax.set_title(f"IQ {iq}: desired = {tone} sideband (RF = LO {'+' if sign > 0 else chr(0x2212)} IF)", loc="left",
                     fontsize=12.5, color=INK, fontweight="semibold", pad=10)
        ax.set_xlabel("RF frequency at the board's RF output (GHz)", fontsize=11, labelpad=8)
        ax.legend(loc="lower left", ncol=3, frameon=True, facecolor=SURFACE, edgecolor="none", framealpha=0.95, fontsize=10.5,
                  labelcolor=INK2)
    fig.text(0.075, 0.955, "FR3 1CH rev 1.4: desired-sideband gain vs. RF frequency at fixed IF", fontsize=16, color=INK,
             fontweight="semibold", ha="left", va="center")
    fig.text(0.075, 0.915, "Each curve is one IF frequency, taken from the LO sweep (one point per 100 MHz of LO). Constant "
             f"{fmt(m.settings['drive_dbm'], 0)} dBm drive, TX filter in bypass, cable-corrected.", fontsize=10.5, color=INK2,
             ha="left", va="center")
    out = folder / f"map_C_gain_vs_rf_{folder.name}.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", nargs="?", type=Path)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--cmap", default="blue", help="'blue' (default one-hue ramp) or a matplotlib colormap name, e.g. viridis")
    parser.add_argument("--only", default="ABC", help="which figures to draw, e.g. AB")
    args = parser.parse_args()
    use_colormap(args.cmap)
    folder = args.folder or newest_campaign()
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    m = load_campaign(folder)
    makers = {"A": fig_gain_maps, "B": fig_suppression, "C": fig_vs_rf}
    outs = [makers[k](m, folder) for k in args.only.upper()]
    for o in outs:
        print(f"Saved {o}")
        if args.open:
            os.startfile(o)
    return 0


if __name__ == "__main__":
    sys.exit(main())
