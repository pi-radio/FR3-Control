"""Datasheet figure for the TX 2xLO spur (Section 10.1), from the all-filter-settings sweep (lo_cal_grid_scan.py --read-2lo):
at each LO frequency the median 2xLO over every usable filter setting (line) and the minimum-to-maximum range (shaded), with the
-20 dBm line; top axis = the spur frequency (2 x LO).

    python plot_datasheet_2lo.py [--table <..._sec10_1_2lo_hot_table.csv>]

Writes FR3-1ch-Datasheet/images/sec_spur_2lo_all_filters.pdf.
"""
from __future__ import annotations

import argparse
import csv
import glob
import statistics as st

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from make_sec10_1_numbers import DEFAULT  # noqa: E402
from plot_datasheet_lo import house  # noqa: E402
from plot_datasheet_nf import IMAGES, use_plex  # noqa: E402

BLUE = "#1565c0"
LINE_DBM = -20.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="")
    args = ap.parse_args()
    use_plex()
    tpath = args.table or sorted(glob.glob(DEFAULT))[-1]
    h: dict[float, list[float]] = {}
    for r in csv.DictReader(open(tpath.replace("_table.csv", "_states.csv"), newline="")):
        h.setdefault(round(float(r["lo_ghz"]), 3), []).append(float(r["two_lo_dbm"]))
    los = sorted(h)
    fig, ax = plt.subplots(figsize=(11, 3.8))
    ax.fill_between(los, [min(h[k]) for k in los], [max(h[k]) for k in los], color=BLUE, alpha=0.2, lw=0,
                    label="Range across all usable filter settings (min to max)")
    ax.plot(los, [st.median(h[k]) for k in los], lw=1.5, color=BLUE, label="Median across all usable filter settings")
    allv = [x for k in los for x in h[k]]
    pct = 100 * sum(x <= LINE_DBM for x in allv) / len(allv)
    ax.axhline(LINE_DBM, color="black", ls="--", lw=1.2,
               label=f"−20 dBm threshold: {pct:.1f}% of configurations are better (lower)")
    x_arrow, length = 6.65, 12.0                                   # in the empty strip left of the data
    for direction, word in ((+1, "Fail"), (-1, "Pass")):
        ax.annotate("", xy=(x_arrow, LINE_DBM + direction * length), xytext=(x_arrow, LINE_DBM),
                    arrowprops=dict(arrowstyle="-|>", color="black", lw=1.5))
        ax.text(x_arrow, LINE_DBM + direction * (length + 1.0), word, color="black", fontsize=10, ha="center",
                va="bottom" if direction > 0 else "top")
    ax.set_xlim(6.4, 13.3)
    ax.set_ylim(-75, 0)
    ax.set_xlabel("LO Frequency (GHz)")
    ax.set_ylabel("2×LO Spur (dBm)")
    top = ax.secondary_xaxis("top", functions=(lambda x: 2 * x, lambda x: x / 2))
    top.set_xlabel("Spur Frequency, 2×LO (GHz)")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    house(ax, "")
    out = IMAGES / "sec_spur_2lo_all_filters.pdf"
    fig.savefig(out, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    main()
