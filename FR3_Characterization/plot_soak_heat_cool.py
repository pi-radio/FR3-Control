"""One image with the heating (fan off) and cooling (fan on) soaks of the same 7.9 GHz null, on a shared time axis.

    python plot_soak_heat_cool.py [heating folder] [cooling folder] [--open]

Top: LO leakage vs. time. Bottom: LMX temperature vs. time. The two soaks were run some minutes apart at the same bias; the time
between them (not recorded; the fan stayed off and the box kept warming) is shown as a shaded gap. Absolute times come from
the files' modification times (soak.csv is written when a soak ends)."""

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
from results_layout import unit_dir  # noqa: E402


def load(folder: Path):
    rows = list(csv.DictReader(open(folder / "soak.csv", newline="")))
    t = np.array([float(r["t_s"]) for r in rows])
    v = np.array([float(r["lo_leakage_dbm_at_board"]) for r in rows])
    c = np.array([float(r["lmx_temp_c"]) for r in rows])
    end_wall = (folder / "soak.csv").stat().st_mtime
    meta = json.loads((folder / "result.json").read_text())
    return t, v, c, end_wall - t[-1], meta       # (start wall-clock, s since epoch)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("heat", nargs="?", type=Path, default=unit_dir(5) / "lo_soak_fan_off_20260924")
    parser.add_argument("cool", nargs="?", type=Path, default=unit_dir(5) / "lo_soak_fan_on_cooldown_20260924")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]

    th, vh, ch, h0, mh = load(args.heat)
    tc, vc, cc, c0, mc = load(args.cool)
    xh = th / 60.0                                   # minutes since the start of the heating soak
    xc = (c0 - h0 + tc) / 60.0
    gap0, gap1 = xh[-1], xc[0]
    fan_on = xc[0] + (mc["event_t_s"] or 0) / 60.0 if mc.get("event_t_s") is not None else None
    st = mh["state_at_start"]

    fig, (a0, a1) = plt.subplots(2, 1, figsize=(12.5, 8.8), sharex=True)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.08, right=0.975, top=0.86, bottom=0.08, hspace=0.14)
    for ax in (a0, a1):
        style_axes(ax)
        ax.axvspan(gap0, gap1, color="#d6d5cd", alpha=0.55, linewidth=0)
    a0.plot(xh, vh, color=BLUE, linewidth=2, solid_joinstyle="round")
    a0.plot(xc, vc, color=BLUE, linewidth=2, solid_joinstyle="round")
    a0.axhline(-55, color=MUTED, linewidth=1.1, linestyle=(0, (4, 3)))
    a0.set_ylabel("LO leakage at the RF connector (dBm)", fontsize=11, labelpad=8)
    a1.plot(xh, ch, color=ORANGE, linewidth=2, solid_joinstyle="round")
    a1.plot(xc, cc, color=ORANGE, linewidth=2, solid_joinstyle="round")
    a1.set_ylabel("LMX temperature (°C)", fontsize=11, labelpad=8)
    a1.set_xlabel("Time since the start of the heating soak (minutes)", fontsize=11, labelpad=8)
    if fan_on is not None:
        for ax in (a0, a1):
            ax.axvline(fan_on, color=INK2, linewidth=1.4, linestyle=(0, (2, 2)))
    y0, y1 = a0.get_ylim()
    a0.text((xh[0] + gap0) / 2, y1 - 0.06 * (y1 - y0), "fan OFF (heating)", ha="center", va="top", fontsize=11, color=INK2)
    a0.text((gap0 + gap1) / 2, y1 - 0.06 * (y1 - y0), "not\nrecorded", ha="center", va="top", fontsize=9.5, color=MUTED)
    if fan_on is not None:
        a0.text((fan_on + xc[-1]) / 2, y1 - 0.06 * (y1 - y0), "fan ON (cooling)", ha="center", va="top", fontsize=11, color=INK2)
        a0.text(xc[0] + (fan_on - xc[0]) / 2, y1 - 0.06 * (y1 - y0), "fan\nstill off", ha="center", va="top", fontsize=9.5, color=MUTED)
    fig.text(0.08, 0.955, f"LO leakage and LMX temperature: heating (fan off) and cooling (fan on), LO {st['lmx_freq_ghz']:g} GHz, unit #5",
             fontsize=15.5, color=INK, fontweight="semibold", ha="left", va="center")
    fig.text(0.08, 0.905, f"Held at I_V = {st['i_v']:+.5f} V, Q_V = {st['q_v']:+.5f} V, LMX power {st['lmx_power']}; one reading per second, "
             "FieldFox source off.\nThe shaded gap is the time between the two soaks (fan off, not recorded). Dashed line: −55 dBm.",
             fontsize=10.5, color=INK2, ha="left", va="center")
    out = args.cool / f"heating_and_cooling_{datetime.now():%H%M%S}.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    print("Saved", out)
    print(f"heating: {th[-1]:.0f} s, LMX {ch[0]:.1f}->{ch[-1]:.1f} C, leakage {vh[0]:+.1f}->{vh[-1]:+.1f} dBm; gap {(gap1 - gap0):.1f} min; "
          f"cooling: {tc[-1]:.0f} s, LMX {cc[0]:.1f}->{cc[-1]:.1f} C, leakage {vc[0]:+.1f}->{vc[-1]:+.1f} dBm")
    if args.open:
        os.startfile(out)
        time.sleep(3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
