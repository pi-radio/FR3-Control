"""Summary and figures for run_lmx_drive_sweep.ps1: LO-null bias voltages and null stability versus LMX output power.

    python plot_lmx_drive.py [name prefix, default lmx_drive_20260924] [--open]

Reads results/unit_<serial>/<prefix>_pwr<n>[_repeat]/{result.json, observation.csv, search_log.csv}. Writes lmx_drive_summary.csv
and two PNGs (bias voltages and stability vs LMX power; the 60 s leakage traces) into results/unit_<serial>/<prefix>_summary/."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from plot_power_sweep import BLUE, INK, INK2, MUTED, ORANGE, SURFACE, style_axes  # noqa: E402
from results_layout import unit_dir  # noqa: E402


def load_run(folder: Path) -> dict | None:
    res = folder / "result.json"
    obs = folder / "observation.csv"
    if not (res.exists() and obs.exists()):
        return None
    meta = json.loads(res.read_text())
    rows = list(csv.DictReader(open(obs, newline="")))
    t = np.array([float(r["t_s"]) for r in rows]); v = np.array([float(r["lo_leakage_dbm_at_board"]) for r in rows])
    temps = [float(r["lmx_temp_c"]) for r in rows if r["lmx_temp_c"]]
    slope = float(np.polyfit(t, v, 1)[0] * 60)                       # dB per minute, straight-line fit
    detr = v - np.polyval(np.polyfit(t, v, 1), t)
    s = meta["search"]
    return {"folder": folder.name, "power": int(meta["lmx_power"]), "repeat": folder.name.endswith("repeat"),
            "i_v": s["i_v"], "q_v": s["q_v"], "search_end_dbm": s["final_level_at_board_dbm"], "search_s": s["seconds"],
            "iterations": s["iterations"], "t": t, "v": v, "mean": float(v.mean()), "min": float(v.min()), "max": float(v.max()),
            "p2p": float(v.max() - v.min()), "slope_db_min": slope, "detrended_std": float(detr.std(ddof=1)),
            "first10": float(v[:10].mean()), "last10": float(v[-10:].mean()), "temp0": temps[0], "temp1": temps[-1]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prefix", nargs="?", default="lmx_drive_20260924")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    base = unit_dir(5)
    runs = [r for p in sorted(base.glob(f"{args.prefix}_pwr*")) if (r := load_run(p))]
    if not runs:
        sys.exit("no finished runs found")
    main_runs = sorted((r for r in runs if not r["repeat"]), key=lambda r: r["power"])
    rep = [r for r in runs if r["repeat"]]
    out = base / f"{args.prefix}_summary"
    out.mkdir(exist_ok=True)

    cols = ["power", "repeat", "i_v", "q_v", "search_end_dbm", "first10", "mean", "min", "max", "p2p", "slope_db_min", "detrended_std",
            "last10", "temp0", "temp1", "iterations", "search_s"]
    with open(out / "lmx_drive_summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in main_runs + rep:
            w.writerow([f"{r[c]:.5f}" if isinstance(r[c], float) else r[c] for c in cols])
    print("LMX  I_V(V)     Q_V(V)     end-of-search  first10s  mean   min    max   p2p  slope(dB/min)  LMX C")
    for r in main_runs + rep:
        print(f" {r['power']}{'r' if r['repeat'] else ' '}  {r['i_v']:+.5f}  {r['q_v']:+.5f}   {r['search_end_dbm']:+7.1f}   {r['first10']:+7.1f} "
              f"{r['mean']:+7.1f} {r['min']:+6.1f} {r['max']:+6.1f} {r['p2p']:5.1f}  {r['slope_db_min']:+6.1f}      {r['temp0']:.0f}->{r['temp1']:.0f}")

    # Figure 1: voltages and stability vs LMX power
    fig, axes = plt.subplots(3, 1, figsize=(11.5, 11.2), sharex=True)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.085, right=0.975, top=0.90, bottom=0.07, hspace=0.24)
    for ax in axes:
        style_axes(ax)
    p = [r["power"] for r in main_runs]
    axes[0].plot(p, [r["i_v"] for r in main_runs], color=BLUE, linewidth=2, marker="o", label="I_V")
    axes[0].plot(p, [r["q_v"] for r in main_runs], color=ORANGE, linewidth=2, marker="o", label="Q_V")
    for r in rep:
        axes[0].plot([r["power"]], [r["i_v"]], marker="x", color=BLUE, markersize=9, linestyle="none")
        axes[0].plot([r["power"]], [r["q_v"]], marker="x", color=ORANGE, markersize=9, linestyle="none")
    axes[0].set_ylabel("Found bias voltage (V)", fontsize=11, labelpad=8)
    axes[0].set_title("Bias voltages that null the LO (pattern search from 0, 0)", loc="left", fontsize=12.5, color=INK, fontweight="semibold", pad=8)
    axes[0].legend(loc="best", frameon=True, facecolor=SURFACE, edgecolor="none", fontsize=10.5, labelcolor=INK2)
    axes[1].plot(p, [r["search_end_dbm"] for r in main_runs], color=MUTED, linewidth=1.6, marker="s", label="end of search")
    axes[1].plot(p, [r["mean"] for r in main_runs], color=BLUE, linewidth=2.2, marker="o", label="mean over 60 s")
    axes[1].fill_between(p, [r["min"] for r in main_runs], [r["max"] for r in main_runs], color=BLUE, alpha=0.18, linewidth=0,
                         label="min to max over 60 s")
    for r in rep:
        axes[1].plot([r["power"]], [r["mean"]], marker="x", color=BLUE, markersize=9, linestyle="none", label="repeat of power 7")
    axes[1].axhline(-55, color=MUTED, linewidth=1.1, linestyle=(0, (4, 3)))
    axes[1].set_ylabel("LO leakage at the RF connector (dBm)", fontsize=11, labelpad=8)
    axes[1].set_title("Leakage after nulling, and how it moves over the next 60 s", loc="left", fontsize=12.5, color=INK, fontweight="semibold", pad=8)
    axes[1].legend(loc="best", frameon=True, facecolor=SURFACE, edgecolor="none", fontsize=10, labelcolor=INK2)
    axes[2].bar(np.array(p) - 0.18, [r["p2p"] for r in main_runs], width=0.36, color=BLUE, label="peak-to-peak over 60 s (dB)")
    axes[2].bar(np.array(p) + 0.18, [abs(r["slope_db_min"]) for r in main_runs], width=0.36, color=ORANGE, label="|straight-line drift| (dB/min)")
    for r in rep:
        axes[2].plot([r["power"] - 0.18], [r["p2p"]], marker="x", color=INK, markersize=9, linestyle="none", label="repeat of power 7 (peak-to-peak)")
    axes[2].set_ylabel("Instability (dB)", fontsize=11, labelpad=8)
    axes[2].set_xlabel("LMX output power setting", fontsize=11, labelpad=8)
    axes[2].set_xticks(range(8))
    axes[2].set_title("Stability of the null", loc="left", fontsize=12.5, color=INK, fontweight="semibold", pad=8)
    axes[2].legend(loc="best", frameon=True, facecolor=SURFACE, edgecolor="none", fontsize=10, labelcolor=INK2)
    fig.text(0.085, 0.965, "FR3 1CH rev 1.4, unit #5: LO null vs. LMX drive, LO 14.4 GHz", fontsize=16, color=INK, fontweight="semibold", ha="left", va="center")
    fig.text(0.085, 0.93, "One nulling run per LMX power setting (FieldFox source off, IF input terminated), then 60 s at constant bias. "
             "Dashed line: −55 dBm target.", fontsize=10.5, color=INK2, ha="left", va="center")
    f1 = out / f"lmx_drive_summary_{args.prefix}.png"
    fig.savefig(f1, dpi=150, facecolor=SURFACE)
    plt.close(fig)

    # Figure 2: the 60 s traces, small multiples on a common axis
    fig, axes = plt.subplots(3, 3, figsize=(13.5, 10.6), sharex=True, sharey=True)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.07, right=0.985, top=0.89, bottom=0.07, wspace=0.06, hspace=0.30)
    ordered = main_runs + rep
    lo = min(r["min"] for r in ordered) - 2; hi = max(r["max"] for r in ordered) + 2
    for ax, r in zip(axes.flat, ordered):
        style_axes(ax)
        ax.plot(r["t"], r["v"], color=BLUE, linewidth=1.8, solid_joinstyle="round")
        ax.axhline(-55, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
        ax.set_ylim(lo, hi)
        ax.set_title(f"LMX power {r['power']}{' (repeat)' if r['repeat'] else ''}", loc="left", fontsize=11.5, color=INK, fontweight="semibold", pad=6)
        ax.text(0.03, 0.05, f"I {r['i_v']:+.4f}  Q {r['q_v']:+.4f} V\nmean {r['mean']:+.1f}, p-p {r['p2p']:.1f} dB, {r['temp1']:.0f} °C",
                transform=ax.transAxes, fontsize=8.8, color=INK2, va="bottom", ha="left",
                bbox={"facecolor": SURFACE, "edgecolor": "none", "alpha": 0.85, "pad": 2})
    for ax in axes[:, 0]:
        ax.set_ylabel("LO leakage (dBm)", fontsize=10)
    for ax in axes[-1, :]:
        ax.set_xlabel("time at constant bias (s)", fontsize=10)
    fig.text(0.07, 0.965, "LO leakage vs. time at constant bias, for each LMX power", fontsize=16, color=INK, fontweight="semibold", ha="left", va="center")
    fig.text(0.07, 0.93, "Common axes. One reading per second (FieldFox averaging restarted at each bias change during the search, running average during the hold).",
             fontsize=10.5, color=INK2, ha="left", va="center")
    f2 = out / f"lmx_drive_traces_{args.prefix}.png"
    fig.savefig(f2, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    print("Saved", f1, "\nSaved", f2)
    if args.open:
        for f in (f1, f2):
            os.startfile(f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
