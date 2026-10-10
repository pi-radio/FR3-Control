"""Four-graph figure of a lo_null_scan.py campaign, redrawn as the campaign runs (LMX temperature vs. LO frequency; I_V, Q_V vs. LO
frequency; magnitude and angle vs. LO frequency; the null vector in the complex plane).

    python plot_null_sweep.py <campaign folder> [--total 157] [--out live_null_vs_freq.png]

Used by lo_null_scan.py --live-plot after every frequency. The image is written to a temporary file and moved into place, so a browser
that reloads it never sees a half-written picture. Only frequencies with a usable fit are plotted; failed ones are listed in the subtitle.
The frequency and voltage axes are fixed for the whole campaign, so the view does not jump while the data arrives. The complex-plane
graph is a half-circle (angles 0 to 180 degrees) as long as every null has Q_V >= 0, and becomes a full circle if one does not."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from plot_power_sweep import BLUE, INK, INK2, MUTED, ORANGE, SURFACE, style_axes  # noqa: E402

AQUA = "#1baf7a"
TEMP_COLOR = "#c0392b"
R_MAX_V = 0.75                                                         # |I + jQ| cannot exceed sqrt(2) * 0.5 V (firmware limit)
HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>LO null sweep (live)</title>
<style>body{margin:0;background:#fcfcfa;font-family:'Segoe UI',sans-serif} img{width:100%;max-width:1150px;display:block;margin:0 auto}
.s{padding:10px 18px;color:#555;font-size:14px}</style></head><body>
<div class="s">Live view of the LO-null sweep. The picture is redrawn after every frequency; press F5 to refresh at any time (this page also reloads
the picture every 15 s). <span id="t"></span></div>
<img id="im" src="live_null_vs_freq.png">
<script>function r(){document.getElementById('im').src='live_null_vs_freq.png?'+Date.now();
document.getElementById('t').textContent='(picture reloaded '+new Date().toLocaleTimeString()+')';} setInterval(r,15000);</script>
</body></html>
"""


def write_live_page(folder: Path) -> Path:
    page = folder / "live.html"
    page.write_text(HTML, encoding="utf-8")
    return page


def plot_campaign(folder: Path, total: int, out: Path | None = None, dpi: int = 300) -> Path:
    out = out or folder / "live_null_vs_freq.png"
    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    campaign = json.loads((folder / "campaign.json").read_text(encoding="utf-8-sig"))
    x0, x1 = campaign["lo_start_ghz"], campaign["lo_stop_ghz"]
    unit = campaign.get("unit_serial", "?")
    rows = {}
    path = folder / "lo_null_table.csv"
    if path.exists():
        for r in csv.DictReader(open(path, newline="")):
            rows[round(float(r["freq_ghz"]), 4)] = r                      # a later row for the same frequency replaces an earlier one
    ok = sorted((r for r in rows.values() if not r["outcome"].startswith("failed")), key=lambda r: float(r["freq_ghz"]))
    failed = sorted(float(r["freq_ghz"]) for r in rows.values() if r["outcome"].startswith("failed"))
    f = np.array([float(r["freq_ghz"]) for r in ok])
    i_v = np.array([float(r["i_v"]) for r in ok])
    q_v = np.array([float(r["q_v"]) for r in ok])
    temps = [float(r["lmx_temp_c"]) for r in ok]
    leak = [float(r["leakage_dbm_at_board"]) for r in ok]
    mag = np.hypot(i_v, q_v)
    ang = np.degrees(np.unwrap(np.arctan2(q_v, i_v))) if len(f) else np.array([])
    half = len(f) == 0 or (ang.min() >= 0 and ang.max() <= 180)

    fig_w = 12.5
    # Growing the figure to add the temperature panel: everything below the header shrinks by `scale` (so the new panel's room comes
    # from proportionally shrinking the rest, not from changing the original panels' design), and the header text moves with it.
    if half:
        fig_h_old, fig_h = 15.8, 18.0
    else:
        fig_h_old, fig_h = 18.2, 20.6
    scale = fig_h_old / fig_h
    header_y1, header_y2 = 0.972 * scale, 0.953 * scale
    fig = plt.figure(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(SURFACE)
    if half:
        # the half-circle sits in the middle band of a square polar axes (its diameter a quarter of the side below the centre); the box is
        # placed so that the diameter is at figure height DIAMETER_Y, and the empty lower part of the box hangs off the page
        gs = fig.add_gridspec(3, 1, height_ratios=[0.5, 1.0, 0.85], hspace=0.34, left=0.075, right=0.925, top=0.915 * scale, bottom=0.445 * scale)
        side_in, diameter_y = 8.6, 0.075 * scale
        axc = fig.add_axes([(1 - side_in / fig_w) / 2, diameter_y - side_in / (4 * fig_h), side_in / fig_w, side_in / fig_h],
                           projection="polar")
        caption_y = 0.405 * scale
    else:
        gs = fig.add_gridspec(4, 1, height_ratios=[0.5, 1.0, 0.85, 1.9], hspace=0.55, left=0.075, right=0.925, top=0.925 * scale, bottom=0.06 * scale)
        axc = fig.add_subplot(gs[3], projection="polar")
        caption_y = axc.get_position().y1 + 0.05
    axt = fig.add_subplot(gs[0])
    ax = fig.add_subplot(gs[1], sharex=axt)
    axp = fig.add_subplot(gs[2], sharex=axt)
    style_axes(axt)
    style_axes(ax)
    style_axes(axp)
    span = x1 - x0

    axt.set_ylabel("LMX temperature (°C)", fontsize=11, labelpad=8)
    axt.set_title("LMX temperature at each measured LO frequency", loc="left", fontsize=12.5, color=INK, fontweight="semibold", pad=8)
    plt.setp(axt.get_xticklabels(), visible=False)

    ax.axhline(0, color=MUTED, linewidth=1)
    ax.plot(f, i_v, color=BLUE, linewidth=1.8, marker="o", markersize=3.6, solid_joinstyle="round", label="I_V")
    ax.plot(f, q_v, color=ORANGE, linewidth=1.8, marker="o", markersize=3.6, solid_joinstyle="round", label="Q_V")
    ax.set_xlim(x0 - 0.02 * span, x1 + 0.02 * span)
    ax.set_ylim(-0.5, 0.5)
    ax.set_ylabel("Bias voltage that nulls the LO (V)", fontsize=11, labelpad=8)
    ax.set_title("Cartesian form: I_V and Q_V", loc="left", fontsize=12.5, color=INK, fontweight="semibold", pad=8)
    ax.legend(loc="upper left", ncol=2, frameon=True, facecolor=SURFACE, edgecolor="none", framealpha=0.95, fontsize=11, labelcolor=INK2)

    axp.set_ylabel("Magnitude M = √(I² + Q²)  (V)", fontsize=11, labelpad=8, color=AQUA)
    axp.tick_params(axis="y", colors=AQUA)
    axp.set_ylim(0, R_MAX_V)
    axp2 = axp.twinx()
    axp2.set_ylabel("Angle φ = atan2(Q, I), unwrapped  (degrees)", fontsize=11, labelpad=10, color=INK)
    axp2.tick_params(axis="y", colors=INK, labelsize=10)
    axp2.spines["top"].set_visible(False)
    axp2.spines["right"].set_color("#c9c8c0")
    axp.set_xlabel("LO frequency (GHz)", fontsize=11, labelpad=8)
    axp.set_title("Polar form of the same points: magnitude (green, left axis) and angle (black, right axis)", loc="left", fontsize=12.5,
                  color=INK, fontweight="semibold", pad=8)

    axc.set_facecolor(SURFACE)
    axc.set_rlim(0, R_MAX_V)
    axc.set_rticks([0.2, 0.4, 0.6])
    if half:
        axc.set_thetamin(0)
        axc.set_thetamax(180)
        axc.set_rlabel_position(90)
        axc.set_thetagrids(range(0, 181, 30))
    else:
        axc.set_rlabel_position(45)
    axc.grid(color="#d6d5cd", linewidth=1)
    axc.tick_params(colors=MUTED, labelsize=10)
    axc.spines["polar"].set_color("#c9c8c0")
    if len(f):
        axt.plot(f, temps, color=TEMP_COLOR, linewidth=1.8, marker="o", markersize=3.6, solid_joinstyle="round")
        axp.plot(f, mag, color=AQUA, linewidth=1.8, marker="o", markersize=3.6, solid_joinstyle="round")
        axp2.plot(f, ang, color=INK, linewidth=1.8, marker="s", markersize=3.4, solid_joinstyle="round")
        pad = max(10.0, 0.08 * (ang.max() - ang.min()))
        axp2.set_ylim(min(0.0, ang.min() - pad) if half else ang.min() - pad, max(180.0, ang.max() + pad) if half else ang.max() + pad)
        th = np.radians(ang)
        axc.plot(th, mag, color=BLUE, linewidth=0.5, zorder=2)             # thin solid line joining the points in order of frequency
        axc.scatter(th, mag, s=2, color=BLUE, linewidths=0, zorder=3)      # one tiny filled circle per LO frequency, all the same colour
        if abs(f[0] - x0) < 0.06:                                          # the only marker: the low-frequency end
            axc.annotate(f"{x0:g}", (th[0], mag[0]), textcoords="offset points", xytext=(7, 6), fontsize=10, color=INK, fontweight="semibold")
    else:
        axp2.set_ylim(0, 180)
        ax.text(0.5, 0.5, "waiting for the first frequency to finish ...", transform=ax.transAxes, ha="center", va="center", fontsize=14,
                color=MUTED)
    fig.text(0.075, caption_y, "Complex-plane view (like a Smith chart): the null vector I + jQ at radius M (V) and angle φ,", fontsize=12.5,
             color=INK, fontweight="semibold", ha="left", va="center")
    fig.text(0.075, caption_y - 0.017, "one point per LO frequency, joined in order of frequency; the label marks the low-frequency end (GHz).", fontsize=11, color=INK2, ha="left", va="center")

    fig.text(0.075, header_y1, f"LO-null bias voltages vs. LO frequency, {x0:g} to {x1:g} GHz, unit #{unit}", fontsize=16, color=INK,
             fontweight="semibold", ha="left", va="center")
    if failed:
        fail = f", {len(failed)} failed" if len(failed) > 3 else f", failed: {', '.join(f'{x:.3f}' for x in failed)} GHz"
    else:
        fail = ""
    if len(f):
        head = (f"{len(f)} of {total} done{fail}, last {f[-1]:.3f} GHz.  Leakage at the null {min(leak):.0f} to {max(leak):.0f} dBm, "
                f"LMX {min(temps):.0f} to {max(temps):.0f} °C.  Updated {datetime.now():%H:%M:%S}.")
    else:
        head = f"0 of {total} done so far.  Updated {datetime.now():%H:%M:%S}."
    fig.text(0.075, header_y2, head, fontsize=10.5, color=INK2, ha="left", va="center")

    tmp = out.with_name(out.stem + ".tmp.png")
    fig.savefig(tmp, dpi=dpi, facecolor=SURFACE)
    plt.close(fig)
    os.replace(tmp, out)                                               # atomic: a reloading browser never sees a partial file
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--total", type=int, default=157)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    print("Saved", plot_campaign(args.folder, args.total, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
