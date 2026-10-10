"""Datasheet figure for the TX-side LO suppression section (100 MHz-grid calibration, 2026-10-08 rewrite), unit 5:

  images/sec6_cal_fig1.pdf  LO leakage vs LO frequency after calibration: median over the non-reference filter settings
                            (line) and their minimum-to-maximum range (shaded), with the -20 dBm pass level. Cold only until
                            the hot calibration exists.
  images/sec6_cal_fig1_hot.pdf  the same for the hot calibration (made only once the hot scan has data).

    python plot_datasheet_lo_cal.py [--cold <..._states.csv>]

Also works mid-run (plots the LOs measured so far).
"""
from __future__ import annotations

import argparse
import csv
import glob
import statistics as st

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from plot_datasheet_lo import I_COLD, I_HOT, Q_COLD, Q_HOT, house, signed_int  # noqa: E402
from plot_datasheet_nf import IMAGES, INK, use_plex  # noqa: E402

THRESHOLD_DBM = -20.0
BLUE = "#1565c0"
# the full-band calibration scans at the LMX drive rule (2026-10-09); the cold one needs the fan on
COLD_DEFAULT = r"results\unit_005\2026-10-09\lo_cal_grid_100MHz_*_full_cal_cold_drive_rule_states.csv"
HOT_DEFAULT = r"results\unit_005\2026-10-09\lo_cal_grid_100MHz_*_full_cal_hot_drive_rule_states.csv"
ORANGE = "#e65100"


def per_lo(path: str) -> tuple[list[float], list[float], list[float], list[float], float, int]:
    rows = list(csv.DictReader(open(path, newline="")))
    h: dict[float, list[float]] = {}
    for r in rows:
        if r["is_reference"] != "1":
            h.setdefault(round(float(r["lo_ghz"]), 3), []).append(float(r["lo_dbm_ref_bias"]))
    los = sorted(h)
    pct = 100 * sum(float(r["lo_dbm_ref_bias"]) <= THRESHOLD_DBM for r in rows) / len(rows)
    return los, [st.median(h[k]) for k in los], [min(h[k]) for k in los], [max(h[k]) for k in los], pct, len(rows)


def plot(path: str, which: str, color: str, out_name: str) -> None:
    los, med, lo_, hi, pct, n = per_lo(path)
    fig, ax = plt.subplots(figsize=(11, 3.6))
    ax.fill_between(los, lo_, hi, color=color, alpha=0.2, lw=0, label="Range across the other filter settings (min to max)")
    ax.plot(los, med, lw=1.4, color=color, label="Median across the other filter settings")
    ax.axhline(THRESHOLD_DBM, color="black", ls="--", lw=1.2,
               label=f"Pass level: {signed_int(THRESHOLD_DBM)} dBm ({pct:.1f}% of all {n} readings at or below it)")
    x_arrow, length = 6.45, 11.0                                   # in the empty 6-7 GHz strip, left of the data
    for direction, word in ((+1, "Fail"), (-1, "Pass")):
        ax.annotate("", xy=(x_arrow, THRESHOLD_DBM + direction * length), xytext=(x_arrow, THRESHOLD_DBM),
                    arrowprops=dict(arrowstyle="-|>", color="black", lw=1.5))
        ax.text(x_arrow, THRESHOLD_DBM + direction * (length + 1.0), word, color="black", fontsize=10, ha="center",
                va="bottom" if direction > 0 else "top")
    ax.set_xlim(6, 24)
    ax.set_ylim(-60, 0)
    ax.set_xlabel("LO Frequency (GHz)")
    ax.set_ylabel("LO Leakage (dBm)")
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    house(ax, f'LO Leakage at the "TX-side FR3 RF Out" Connector after Calibration ({which})')
    out = IMAGES / out_name
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(out, f"{len(los)} LOs, {n} readings, {pct:.1f}%")


def tables(cold: str, hot: str) -> None:
    """The calibration tables: stored I_V and Q_V vs LO frequency, cold and hot (hot may be partial)."""
    fig, ax = plt.subplots(figsize=(11, 3.4))
    for path, which, ci, cq in ((cold, "cold", I_COLD, Q_COLD), (hot, "hot", I_HOT, Q_HOT)):
        if not path:
            continue
        t = list(csv.DictReader(open(path.replace("_states.csv", "_table.csv"), newline="")))
        f = [float(r["lo_ghz"]) for r in t]
        ax.plot(f, [1e3 * float(r["ref_i_v"]) for r in t], lw=1.3, color=ci, label=f"I_V, {which}")
        ax.plot(f, [1e3 * float(r["ref_q_v"]) for r in t], lw=1.3, color=cq, label=f"Q_V, {which}")
    ax.set_xlim(6, 24)
    ax.set_xlabel("LO Frequency (GHz)")
    ax.set_ylabel("Bias Voltage (mV)")
    ax.legend(frameon=False, fontsize=9, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.2))
    house(ax, "Calibration Tables: Stored I_V and Q_V Bias Voltages")
    out = IMAGES / "sec6_cal_fig3.pdf"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(out)


def histograms(cold: str, hot: str) -> None:
    """Figure 9.4: every (LO, filter setting) reading of each calibration (reference setting included), 1 dB bins."""
    import numpy as np
    runs = [(n, p) for n, p in (("Cold", cold), ("Hot", hot)) if p]
    fig, axes = plt.subplots(1, len(runs), figsize=(11, 3.4), sharey=True, squeeze=False)
    for ax, (name, path) in zip(axes[0], runs):
        v = [float(r["lo_dbm_ref_bias"]) for r in csv.DictReader(open(path, newline=""))]
        pct = 100 * sum(x <= THRESHOLD_DBM for x in v) / len(v)
        ax.hist(v, bins=np.arange(-90, 1, 1.0), color=BLUE, alpha=0.85, edgecolor="white", linewidth=0.3)
        ax.axvline(THRESHOLD_DBM, color="black", ls="--", lw=1.2,
                   label=f"{signed_int(THRESHOLD_DBM)} dBm: {pct:.1f}% of {len(v)} readings at or below")
        ax.set_xlim(-90, 0)
        ax.set_xlabel("LO Leakage (dBm)")
        ax.legend(frameon=False, fontsize=8.5, loc="upper left")
        house(ax, f"{name} Calibration")
    axes[0][0].set_ylabel("Number of (LO, Filter) Readings")
    out = IMAGES / "sec6_cal_fig2.pdf"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(out)


def temperature_difference(cold: str, hot: str) -> None:
    """Figure 9.6: hot minus cold stored bias (I_V and Q_V, mV) vs LO, plus sec6_tempdiff_numbers.tex: the size of that
    difference, and how much the leakage rises at a given distance from the null (from the hot run's null searches:
    every search reading vs its distance from that search's final null, in the reference setting)."""
    import math
    import numpy as np
    if not (cold and hot):
        return
    t = {k: {round(float(r["lo_ghz"]), 1): r for r in csv.DictReader(open(p.replace("_states.csv", "_table.csv"), newline=""))}
         for k, p in (("c", cold), ("h", hot))}
    los = sorted(set(t["c"]) & set(t["h"]))
    di = [1e3 * (float(t["h"][k]["ref_i_v"]) - float(t["c"][k]["ref_i_v"])) for k in los]
    dq = [1e3 * (float(t["h"][k]["ref_q_v"]) - float(t["c"][k]["ref_q_v"])) for k in los]
    fig, ax = plt.subplots(figsize=(11, 3.4))
    ax.plot(los, di, lw=1.3, color=I_HOT, label="I_V: hot − cold")
    ax.plot(los, dq, lw=1.3, color=Q_HOT, label="Q_V: hot − cold")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlim(6, 24)
    ax.set_xlabel("LO Frequency (GHz)")
    ax.set_ylabel("Bias Difference (mV)")
    ax.legend(frameon=False, fontsize=9, ncol=2, loc="upper left")
    house(ax, "Stored Bias Voltages: Hot Minus Cold")
    out = IMAGES / "sec6_cal_fig4.pdf"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    dist = [math.hypot(a, b) for a, b in zip(di, dq)]
    rise = {1: [], 3: []}
    for f in glob.glob(hot.replace("_states.csv", "_null_searches") + "/*.csv"):
        rows = list(csv.DictReader(open(f, newline="")))
        fin = [r for r in rows if r["point"].startswith("fit")]
        if not fin:
            continue
        i0, q0, l0 = float(fin[-1]["i_v"]), float(fin[-1]["q_v"]), float(fin[-1]["level_dbm_at_board"])
        for r in rows:
            d = 1e3 * math.hypot(float(r["i_v"]) - i0, float(r["q_v"]) - q0)
            for b in rise:
                if abs(d - b) <= 0.25 * b:
                    rise[b].append(float(r["level_dbm_at_board"]) - l0)
    lines = ["% generated by FR3_Characterization/plot_datasheet_lo_cal.py -- do not edit",
             f"\\newcommand{{\\tdiffMedianMv}}{{{np.median(dist):.0f}}}",
             f"\\newcommand{{\\tdiffNinetyMv}}{{{np.percentile(dist, 90):.0f}}}",
             f"\\newcommand{{\\tdiffMaxMv}}{{{max(dist):.0f}}}",
             f"\\newcommand{{\\nullRiseOneMv}}{{{np.median(rise[1]):.0f}}}",
             f"\\newcommand{{\\nullRiseThreeMv}}{{{np.median(rise[3]):.0f}}}"]
    (IMAGES.parent / "sections" / "sec6_tempdiff_numbers.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out, lines[1:])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cold", default="")
    ap.add_argument("--hot", default="")
    args = ap.parse_args()
    use_plex()
    cold = args.cold or (sorted(glob.glob(COLD_DEFAULT)) or [""])[-1]
    if cold:
        plot(cold, "Cold", BLUE, "sec6_cal_fig1.pdf")
    else:                                                    # not measured yet: the datasheet shows its placeholder
        (IMAGES / "sec6_cal_fig1.pdf").unlink(missing_ok=True)
        print("no cold scan at the drive rule yet: sec6_cal_fig1.pdf removed (placeholder in the datasheet)")
    hot = args.hot or (sorted(glob.glob(HOT_DEFAULT)) or [""])[-1]
    if hot:
        plot(hot, "Hot", BLUE, "sec6_cal_fig1_hot.pdf")
    else:
        print("no hot scan data yet: sec6_cal_fig1_hot.pdf not made")
    tables(cold, hot)
    histograms(cold, hot)
    temperature_difference(cold, hot)


if __name__ == "__main__":
    main()
