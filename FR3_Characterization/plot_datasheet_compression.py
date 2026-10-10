"""Datasheet figures for compression -- TX (Section 7: upper sideband, Section 8: lower sideband) from a
compression_campaign.py run, and with --chain rx, RX (Section 14: low-side LO, Section 15: high-side LO; images
sec9/sec10_fig1-9) from an rx_compression_campaign.py run: one panel per (FR1, FR3) point -- output power vs input power at the board connectors, the
small-signal-gain line, P1dB and P3dB marked and labelled, the filter byte and LO frequency.

    python plot_datasheet_compression.py [--campaign compression_tx_20261009]
    python plot_datasheet_compression.py --chain rx [--campaign compression_rx_20261009]

Writes FR3-1ch-Datasheet/images/sec4_fig{1..9}.pdf (upper) and sec5_fig{1..9}.pdf (lower), in the order of
compression_campaign.POINTS, and FR3-1ch-Datasheet/sections/sec_compression_numbers.tex (temperatures, drives).
"""
from __future__ import annotations

import argparse
import csv

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from compression_campaign import POINTS  # noqa: E402
from rx_compression_campaign import POINTS as RX_POINTS  # noqa: E402
from plot_datasheet_nf import DATASHEET, GRID_GREY, IMAGES, INK, use_plex  # noqa: E402
from results_layout import unit_dir  # noqa: E402

LINE, P1C, P3C, NOTE = "#3b78c4", "#e8742a", "#c62828", "#1f6fd1"
# per chain: title prefix, x (input) limits, y (output) limits
CHAIN = {"tx": ("TX", (-62, 2), (-45, 30)), "rx": ("RX", (-64, -2), (-40, 28))}
CH = CHAIN["tx"]
SIDE_NAME = {"upper": "Upper sideband", "lower": "Lower sideband", "low": "Low-side LO", "high": "High-side LO"}


def fmt(v: float, unit: str) -> str:
    return f"{v:+.1f} {unit}".replace("+", "").replace("-", "−") if v < 0 else f"{v:.1f} {unit}"


def panel(rows: list[dict], s: dict, side: str, path) -> None:
    used = [r for r in rows if r["valid"] == "1"]
    pin = [float(r["in_at_dut_dbm"]) for r in used]
    pout = [float(r["out_at_dut_dbm"]) for r in used]
    g0 = float(s["small_signal_gain_db"]) if s["small_signal_gain_db"] else None
    fig, ax = plt.subplots(figsize=(6.0, 4.3))
    ax.plot(pin, pout, lw=1.8, color=LINE)
    lab = []
    if g0 is not None:
        ax.plot(list(CH[1]), [CH[1][0] + g0, CH[1][1] + g0], ls="--", lw=1.0, color="#777777")
        lab.append((f"Small-signal gain: {g0:.1f} dB", "#333333"))
    for k, color, name in (("p1db", P1C, "P1dB"), ("p3db", P3C, "P3dB")):
        if s[f"{k}_in_dbm"]:
            x, y = float(s[f"{k}_in_dbm"]), float(s[f"{k}_out_dbm"])
            ax.plot([x], [y], "o" if k == "p1db" else "s", ms=7, color=color, zorder=5)
            ax.annotate(name, (x, y), textcoords="offset points", xytext=(0, -16 if k == "p1db" else 10), ha="center",
                        color=color, fontsize=8.5, fontweight="semibold")
            lab += [(f"Input {name}: {fmt(x, 'dBm')}", color), (f"Output {name}: {fmt(y, 'dBm')}", color)]
        else:
            lab.append((f"{name}: not reached (source max 0 dBm)", color))
    for i, (t, c) in enumerate(lab):
        ax.text(0.04, 0.95 - 0.06 * i, t, transform=ax.transAxes, fontsize=7.5, color=c, va="top")
    ax.text(0.97, 0.14, f"Filter: {s.get('filter_bits') or s.get('rx_filter_bits')}", transform=ax.transAxes, ha="right", fontsize=7.5, color=NOTE,
            fontweight="semibold")
    ax.text(0.97, 0.06, f"LO: {float(s['lo_ghz']):g} GHz, LMX drive {s['lmx_power']}", transform=ax.transAxes, ha="right",
            fontsize=7.5, color=NOTE, fontweight="semibold")
    ax.set_xlim(*CH[1])
    ax.set_ylim(*CH[2])
    ax.set_xlabel("Input Power (dBm)")
    ax.set_ylabel("Output Power (dBm)")
    ax.set_title(f"{CH[0]} Compression at FR1 = {float(s['fr1_ghz']):g} GHz, FR3 = {float(s['fr3_ghz']):g} GHz", loc="left",
                 color=INK, fontsize=10.5)
    ax.set_title(SIDE_NAME[side], loc="right", color=INK, fontsize=10.5)
    ax.grid(color=GRID_GREY, lw=0.8)
    ax.set_axisbelow(True)
    for sp in ax.spines.values():
        sp.set_visible(False)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", choices=("tx", "rx"), default="tx")
    ap.add_argument("--campaign", default=None)
    args = ap.parse_args()
    global CH
    CH = CHAIN[args.chain]
    args.campaign = args.campaign or f"compression_{args.chain}_20261009"
    use_plex()
    d = unit_dir(5) / args.campaign
    summ = {(r.get("sideband") or r["side"], r["fr1_ghz"], r["fr3_ghz"]): r
            for r in csv.DictReader(open(d / "summary.csv", newline=""))}
    temps = []
    pts, sides = (POINTS, (("upper", "sec4"), ("lower", "sec5"))) if args.chain == "tx" else \
        (RX_POINTS, (("low", "sec9"), ("high", "sec10")))
    for side, pre in sides:
        for n, (fr1, fr3) in enumerate(pts[side], 1):
            s = summ[(side, f"{fr1:g}", f"{fr3:g}")]
            rows = list(csv.DictReader(open(d / f"{side}_FR1_{fr1:g}_FR3_{fr3:g}.csv", newline="")))
            temps += [float(r["lmx_temperature_c"]) for r in rows]
            panel(rows, s, side, IMAGES / f"{pre}_fig{n}.pdf")
    if args.chain == "tx":                                          # RX temperatures: make_rx_conditions.py
      (DATASHEET / "sections" / "sec_compression_numbers.tex").write_text(
        f"% generated by FR3_Characterization/plot_datasheet_compression.py from {args.campaign} -- do not edit\n"
        f"\\newcommand{{\\compTxMinC}}{{{min(temps):.0f}}}\n\\newcommand{{\\compTxMaxC}}{{{max(temps):.0f}}}\n", encoding="utf-8")
    print(f"{args.campaign}: 18 panels, LMX {min(temps):.1f}-{max(temps):.1f} C")


if __name__ == "__main__":
    main()
