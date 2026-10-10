"""Figure from a p1db_map.py campaign: small-signal gain, output P1dB / max output power and input P1dB versus RF frequency.

    python plot_p1db_map.py [campaign folder] [--open]

Blue = IQ THRU (desired = upper sideband, RF = LO + IF), orange = IQ SWAP (desired = lower, RF = LO - IF). Local only."""

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


def load(folder: Path) -> dict:
    out: dict = {}
    for r in csv.DictReader(open(folder / "summary.csv", newline="")):
        d = {k: (float(v) if v not in ("", None) and k not in ("iq", "stop_reason") else (np.nan if v == "" else v)) for k, v in r.items()}
        out.setdefault(r["iq"], []).append(d)
    return {iq: {k: np.array([d[k] for d in rows]) for k in rows[0]} for iq, rows in out.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", nargs="?", type=Path, default=unit_dir(5) / "p1db_map_20260923")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    folder = args.folder
    data = load(folder)
    meta = json.loads((folder / "campaign.json").read_text())
    if_ghz = meta["settings"]["if_hz"] / 1e9

    fig, axes = plt.subplots(3, 1, figsize=(13.5, 11.6), sharex=True)
    fig.patch.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.88, bottom=0.07, hspace=0.20)
    panels = [("small_signal_gain_db", "Small-signal gain (dB)", "Small-signal conversion gain"),
              ("p1db_out_dbm", "Output P1dB (dBm)", "Output-referred 1 dB compression point"),
              ("p1db_in_dbm", "Input P1dB at the IF port (dBm)", "Input-referred 1 dB compression point")]
    for ax, (key, ylab, title) in zip(axes, panels):
        style_axes(ax)
        for iq, color, lab in (("THRU", BLUE, "desired = upper sideband (IQ THRU)"), ("SWAP", ORANGE, "desired = lower sideband (IQ SWAP)")):
            d = data[iq]
            o = np.argsort(d["rf_hz"])
            ax.plot(d["rf_hz"][o] / 1e9, d[key][o], color=color, linewidth=2, marker="o", markersize=4, solid_joinstyle="round", label=lab)
        if key == "p1db_out_dbm":
            for iq, color in (("THRU", BLUE), ("SWAP", ORANGE)):
                d = data[iq]
                o = np.argsort(d["rf_hz"])
                ax.plot(d["rf_hz"][o] / 1e9, d["max_out_dbm"][o], color=color, linewidth=1.2, linestyle=(0, (4, 3)), alpha=0.8)
            ax.text(0.99, 0.04, "dashed: highest output level reached (about 3.5 dB compression)", transform=ax.transAxes, ha="right",
                    fontsize=9.5, color=MUTED)
        ax.set_ylabel(ylab, fontsize=11, labelpad=8)
        ax.set_title(title, loc="left", fontsize=12.5, color=INK, fontweight="semibold", pad=8)
    axes[0].legend(loc="lower left", ncol=2, frameon=True, facecolor=SURFACE, edgecolor="none", framealpha=0.95, fontsize=10.5, labelcolor=INK2)
    axes[2].set_xlabel("RF frequency at the board's RF output (GHz)", fontsize=11, labelpad=8)
    fig.text(0.075, 0.96, f"FR3 1CH rev 1.4, unit #{meta['unit_serial']}: TX compression vs. RF frequency", fontsize=16, color=INK,
             fontweight="semibold", ha="left", va="center")
    fig.text(0.075, 0.925, f"One CW power sweep per point: IF {if_ghz:g} GHz, LO stepped in {meta['settings']['lo_step_hz'] / 1e9:g} GHz steps, "
             "TX filter bypass, LMX power 7. Compression is relative to the small-signal gain; cable-corrected to the board's connectors.",
             fontsize=10.5, color=INK2, ha="left", va="center")
    out = folder / f"p1db_vs_rf_{folder.name}.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    print(f"Saved {out}")
    for iq in ("THRU", "SWAP"):
        d = data[iq]
        print(f"{iq}: G0 {np.nanmin(d['small_signal_gain_db']):.1f}..{np.nanmax(d['small_signal_gain_db']):.1f} dB; "
              f"P1dB out {np.nanmin(d['p1db_out_dbm']):.1f}..{np.nanmax(d['p1db_out_dbm']):.1f} dBm (median {np.nanmedian(d['p1db_out_dbm']):.1f}); "
              f"max out {np.nanmax(d['max_out_dbm']):.1f} dBm; expansion max {np.nanmax(d['max_gain_expansion_db']):.2f} dB (median {np.nanmedian(d['max_gain_expansion_db']):.2f})")
        i = np.nanargmin(d["p1db_out_dbm"]); j = np.nanargmax(d["p1db_out_dbm"])
        print(f"   lowest P1dB out {d['p1db_out_dbm'][i]:.1f} at RF {d['rf_hz'][i]/1e9:.2f} GHz; highest {d['p1db_out_dbm'][j]:.1f} at RF {d['rf_hz'][j]/1e9:.2f} GHz")
    if args.open:
        os.startfile(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
