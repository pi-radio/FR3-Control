"""Plot a tracking_map run (tracking_map.py): for each IQ state one row, showing the desired and the
undesired sideband's conversion gain across the whole IF band as one tracking sweep each (lines),
with the discrete single-tone measurements overlaid (points).

    python plot_tracking_map.py [results/unit_005/<tracking_map folder>] [--no-open]

Part 1 (top): IQ THRU, desired = upper sideband.  Part 2 (bottom): IQ SWAP, desired = lower sideband.
Local only: writes a PNG beside the data and opens it in the default image viewer."""

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

from plot_power_sweep import BLUE, INK, INK2, MUTED, ORANGE, SURFACE, fmt, style_axes  # noqa: E402
from results_layout import unit_dirs  # noqa: E402
from tracking_map import compare, stepped_reference  # noqa: E402


def newest_run() -> Path:
    runs = sorted((r for d in unit_dirs() for r in d.iterdir() if r.is_dir() and (r / "sweeps.csv").exists()),
                  key=lambda r: r.name)
    if not runs:
        sys.exit("no tracking_map run found")
    return runs[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", nargs="?", type=Path)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    run = args.run or newest_run()
    meta = json.loads((run / "metadata.json").read_text())
    f_lo, unit = meta["f_lo_hz"], meta["unit_serial"]

    sweeps: dict[tuple[str, str], dict[str, np.ndarray]] = {}
    with open(run / "sweeps.csv", newline="") as f:
        for r in csv.DictReader(f):
            d = sweeps.setdefault((r["iq"], r["tone"]), {k: [] for k in ("if", "rf", "gain", "weak")})
            d["if"].append(float(r["if_hz"])); d["rf"].append(float(r["rf_hz"]))
            d["gain"].append(float(r["gain_db"])); d["weak"].append(int(r["near_noise_floor"]))
    sweeps = {k: {a: np.array(b) for a, b in v.items()} for k, v in sweeps.items()}
    with open(run / "spot_checks.csv", newline="") as f:
        spots = list(csv.DictReader(f))
    ref = stepped_reference(unit, f_lo)

    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    fig, axes = plt.subplots(2, 1, figsize=(13.5, 10.6), sharex=True)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.80, bottom=0.085, hspace=0.36)
    ymax = max(float(s["gain"].max()) for s in sweeps.values())
    ymin = min(float(s["gain"].min()) for s in sweeps.values())

    parts = [("Part 1: IQ THRU, desired = upper sideband", "THRU", "upper", "lower"),
             ("Part 2: IQ SWAP, desired = lower sideband", "SWAP", "lower", "upper")]
    for ax, (title, iq, want, other) in zip(axes, parts):
        style_axes(ax)
        stats = []
        for tone, color, role in ((want, BLUE, "desired"), (other, ORANGE, "undesired")):
            s = sweeps[(iq, tone)]
            ax.plot(s["if"] / 1e9, s["gain"], color=color, linewidth=2, solid_joinstyle="round", zorder=3)
            weak = s["weak"] > 0
            if weak.any():
                ax.plot(s["if"][weak] / 1e9, s["gain"][weak], linestyle="none", marker="o", markersize=5,
                        markerfacecolor=SURFACE, markeredgecolor=MUTED, markeredgewidth=1.1, zorder=5)
            # discrete measurements: the earlier stepped run (IF 1.6-2.4 GHz) plus the new spot checks
            rf_p, g_p = ref[(iq, tone)]
            f_p = (rf_p - f_lo) if tone == "upper" else (f_lo - rf_p)
            pts = [p for p in spots if (p["iq"], p["tone"]) == (iq, tone)]
            f_all = np.concatenate([f_p, [float(p["if_hz"]) for p in pts]])
            g_all = np.concatenate([g_p, [float(p["gain_db"]) for p in pts]])
            ax.plot(f_all / 1e9, g_all, linestyle="none", marker="o", markersize=5.5, markerfacecolor=color,
                    markeredgecolor=SURFACE, markeredgewidth=1.0, zorder=4)
            rf_all = (f_lo + f_all) if tone == "upper" else (f_lo - f_all)
            c = compare(s["rf"], s["gain"], rf_all, g_all)
            stats.append(f"{role}: mean {fmt(c['mean_db'], 2)} dB, std {c['std_db']:.2f} dB, worst {c['worst_db']:.2f} dB "
                         f"({c['points']} points)")
        ax.set_xlim(0.7, 4.0)
        ax.set_ylim(ymin - 3, ymax + 9)
        ax.set_ylabel("Conversion gain (dB)", fontsize=11, labelpad=8)
        ax.set_title(title, loc="left", fontsize=13.5, color=INK, fontweight="semibold", pad=26)
        ax.text(0.0, 1.03, "Tracking sweep minus discrete tones — " + ";   ".join(stats), transform=ax.transAxes,
                color=INK2, fontsize=10.5, ha="left", va="bottom")
    axes[1].set_xlabel("IF frequency at the board's IF input (GHz)", fontsize=11, labelpad=8)

    handles = [plt.Line2D([], [], color=BLUE, linewidth=2, label="Desired sideband, tracking sweep"),
               plt.Line2D([], [], color=ORANGE, linewidth=2, label="Undesired (image) sideband, tracking sweep"),
               plt.Line2D([], [], color=INK2, linestyle="none", marker="o", markersize=6, label="Discrete single tones (same colors)"),
               plt.Line2D([], [], color=MUTED, linestyle="none", marker="o", markersize=6, markerfacecolor=SURFACE,
                          label="Sweep point within 10 dB of its noise floor")]
    fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(0.985, 0.972), frameon=False, fontsize=10.5,
               labelcolor=INK2)
    T = meta["timing"]
    per_sweep = T["sweep_configure"]["mean_s"] + T["sweep_acquire"]["mean_s"] + T["sweep_read"]["mean_s"]
    fig.text(0.075, 0.955, f"FR3 1CH rev 1.4, unit #{unit}: tracking-generator sweeps vs. discrete tones, LO {f_lo / 1e9:g} GHz",
             fontsize=16, color=INK, fontweight="semibold", ha="left", va="center")
    fig.text(0.075, 0.915, f"IF {meta['args']['if_start_ghz']:g}–{meta['args']['if_stop_ghz']:g} GHz, "
             f"{meta['points']} points per sweep, constant {fmt(meta['drive_dbm'], 0)} dBm drive, TX filter in bypass.",
             fontsize=11, color=INK2, ha="left", va="center")
    fig.text(0.075, 0.03,
             f"Timing of the whole experiment, from LO tuning through the 4th sweep: {meta['experiment_seconds']:.1f} s "
             f"(LMX retune + lock about {T['lmx_tune_and_lock']['mean_s']:.2f} s; each sweep {per_sweep:.2f} s). "
             "Corrected to the board's connectors for cable loss (uncalibrated FieldFox S21).\nThe sweeps used RBW "
             f"{meta['rbw_hz'] / 1e3:g} kHz, input attenuation {meta.get('attenuation_db', 35):g} dB, reference level "
             f"{meta.get('ref_level_dbm', 20):+g} dBm (noise floor about {meta['noise_floor_dbm_p99']:.0f} dBm); "
             "the discrete tones used RBW 7.5 kHz.",
             fontsize=8.8, color=MUTED, ha="left", va="center", linespacing=1.5)

    out = run / f"tracking_map_unit{unit:03d}_LO{f_lo / 1e9:g}GHz_{run.name[:15]}.png"
    try:
        fig.savefig(out, dpi=150, facecolor=SURFACE)
    except OSError:
        out = out.with_name(out.stem + "_new" + out.suffix)
        fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(f"Saved {out}")
    if not args.no_open:
        os.startfile(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
