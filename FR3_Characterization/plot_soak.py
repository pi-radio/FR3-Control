"""One figure for a lo_soak.py run: LO leakage vs. time (top) and LMX temperature vs. time (bottom), sharing the time axis.

    python plot_soak.py <soak folder> [--open]

Reads soak.csv and result.json from the folder; if the run recorded an event (e.g. "fan turned on") it is marked on both graphs.
Writes soak_combined_<hhmmss>.png into the folder (a new name each time, so an image viewer never confuses two files)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from plot_power_sweep import BLUE, INK, INK2, MUTED, ORANGE, SURFACE, style_axes  # noqa: E402


def plot_folder(folder: Path) -> Path:
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    meta = json.loads((folder / "result.json").read_text())
    rows = list(csv.DictReader(open(folder / "soak.csv", newline="")))
    t = np.array([float(r["t_s"]) for r in rows])
    v = np.array([float(r["lo_leakage_dbm_at_board"]) for r in rows])
    c = np.array([float(r["lmx_temp_c"]) for r in rows])
    st = meta["state_at_start"]
    event_t, label = meta.get("event_t_s"), meta.get("event_label", "event")

    fig, (a0, a1) = plt.subplots(2, 1, figsize=(11.5, 8.6), sharex=True)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.085, right=0.975, top=0.87, bottom=0.08, hspace=0.14)
    for ax in (a0, a1):
        style_axes(ax)
    a0.plot(t, v, color=BLUE, linewidth=2, marker="o", markersize=3, solid_joinstyle="round")
    a0.axhline(-55, color=MUTED, linewidth=1.1, linestyle=(0, (4, 3)))
    a0.set_ylabel("LO leakage at the RF connector (dBm)", fontsize=11, labelpad=8)
    a1.plot(t, c, color=ORANGE, linewidth=2, solid_joinstyle="round")
    a1.set_ylabel("LMX temperature (°C)", fontsize=11, labelpad=8)
    a1.set_xlabel("Time (s)", fontsize=11, labelpad=8)
    if event_t is not None:
        for ax in (a0, a1):
            ax.axvline(event_t, color=INK2, linewidth=1.4, linestyle=(0, (2, 2)))
        lo, hi = a1.get_ylim()
        a1.text(event_t + 4, lo + 0.05 * (hi - lo), label, color=INK2, fontsize=10.5, ha="left", va="bottom")
    if meta.get("start_label"):                      # e.g. "LMX on, fan off" at t = 0
        for ax in (a0, a1):
            ax.axvline(0.0, color=INK2, linewidth=1.4, linestyle=(0, (2, 2)))
        lo, hi = a1.get_ylim()
        a1.text(t[-1] * 0.008 + 3, lo + 0.05 * (hi - lo), meta["start_label"], color=INK2, fontsize=10.5, ha="left", va="bottom")
    lo_ghz = st["lmx_freq_ghz"]
    fig.text(0.085, 0.955, f"LO leakage and LMX temperature vs. time: LO {lo_ghz:g} GHz, unit #5", fontsize=16, color=INK,
             fontweight="semibold", ha="left", va="center")
    fig.text(0.085, 0.915, f"Held at I_V = {st['i_v']:+.5f} V, Q_V = {st['q_v']:+.5f} V, LMX power {st['lmx_power']}; "
             f"{meta['seconds']:g} s soak, one reading per second, FieldFox source off.", fontsize=10.5, color=INK2, ha="left", va="center")
    out = folder / f"soak_combined_{datetime.now():%H%M%S}.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    out = plot_folder(args.folder)
    print("Saved", out)
    if args.open:
        os.startfile(out)
        time.sleep(3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
