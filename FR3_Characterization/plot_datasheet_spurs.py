"""Datasheet figure and numbers for the Spurious Outputs section (sections/section_spurious_outputs.tex), unit 5.

  images/sec_spur_fig2.pdf        RX-side LO leakage out of "RX-side FR3 RF In" vs LO (rx_port_leakage.py)
  images/sec_spur_fig3.pdf        RX-side 2xLO leakage out of "RX-side FR3 RF In" vs LO (split from fig2, user 2026-10-09);
                                  both are "Awaiting data" placeholders until that run exists
  (the old TX-side figure sec_spur_fig1.pdf is no longer made: Section 10.1 uses plot_datasheet_2lo.py since 2026-10-09;
   its numbers are still written to sec_spur_numbers.tex)
  sections/sec_spur_numbers.tex   every number the section text, caption and the Key Specifications row quote

Data (all LMX drive 0, case closed, results/unit_005/2026-10-07/):
  Sweep A   tx_2lo_type4_*_sweepA_*.csv   Type 4: LO nulled with the TX filter engaged, no input, 2xLO read
  Type 5    tx_2lo_type5_*_run26_*.csv    the same with a 1 GHz input tone switched on after the null (2xLO tone on/off)
  Type 3    tx_2lo_vs_lo_level_*run1[3-7]*case_on*.csv (drive 0): 2xLO vs deliberately raised LO leakage
  run25     tx_2lo_type4_*_run25_*.csv    the Sweep A LOs measured before the case was opened and closed again

    python plot_datasheet_spurs.py
"""
from __future__ import annotations

import csv
import glob
import json
import statistics as st
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from plot_datasheet_nf import DATASHEET, GRID_GREY, IMAGES, INK, use_plex  # noqa: E402
from results_layout import unit_dir  # noqa: E402

DAY = unit_dir(5) / "2026-10-07"
EXPECTED_BOUND_DBM = -20.0          # user, 2026-10-07: unit-to-unit variation not expected to exceed this
TWO_LO_MAX_GHZ = 26.5
RX_TX_OFFSET_MV = 5.0               # rx_port_leakage.py --offset-mv used for the TX-null sensitivity check
BLUE, RED, GREEN = "#1565c0", "#c62828", "#2e7d32"


def m(v: float, d: int = 1) -> str:
    """Typographic minus (U+2212), as the other generated number files."""
    return f"{v:.{d}f}".replace("-", "−")


def g(v: float) -> str:
    return f"{v:g}".replace("-", "−")


def rows(pattern: str) -> list[dict]:
    files = sorted(glob.glob(str(DAY / pattern)))
    if not files:
        raise FileNotFoundError(pattern)
    return [r for f in files for r in csv.DictReader(open(f, newline=""))]


def main() -> None:
    use_plex()
    a = sorted(rows("tx_2lo_type4_*_sweepA_*.csv"), key=lambda r: float(r["lo_ghz"]))
    meta = json.loads(Path(glob.glob(str(DAY / "tx_2lo_type4_*_sweepA_*.json"))[0]).read_text(encoding="utf-8-sig"))
    lo = np.array([float(r["lo_ghz"]) for r in a])
    two = np.array([float(r["two_lo_dbm"]) for r in a])
    t = np.array([float(r["lmx_temp_c"]) for r in a])
    i_max, i_min = int(np.argmax(two)), int(np.argmin(two))

    # Type 5: 2xLO with the input tone on vs off (same null)
    t5 = rows("tx_2lo_type5_*run26*.csv")
    d5 = [abs(float(r["two_lo_tone_dbm"]) - float(r["two_lo_dbm"])) for r in t5]
    # Type 3, case on, drive 0: flat 2xLO up to -10 dBm LO leakage; 2xLO at +10 dBm leakage and at 0 V bias
    t3 = [r for p in ("run13", "run14", "run15", "run16", "run17") for r in rows(f"tx_2lo_vs_lo_level_*{p}*case_on.csv")]
    plus10 = [float(r["two_lo_dbm"]) for r in t3 if r["axis"] == "IQ" and r["target_dbm"] and float(r["target_dbm"]) == 10.0]
    zero = [float(r["two_lo_dbm"]) for r in t3 if r["axis"] == "zero"]
    zero_lo = [float(r["lo_dbm"]) for r in t3 if r["axis"] == "zero"]
    # the same sweep before the case was opened and closed again (run25): how much re-seating the lid moves the spur
    before = {round(float(r["lo_ghz"]), 3): float(r["two_lo_dbm"]) for r in rows("tx_2lo_type4_*_run25_*.csv")}
    shifts = [two[k] - before[round(lo[k], 3)] for k in range(len(lo)) if round(lo[k], 3) in before]

    # ---- Figure: 2xLO vs LO, full page width ----
    fig, ax = plt.subplots(figsize=(11, 3.6))
    ax.plot(lo, two, "-o", color=BLUE, lw=1.2, ms=3.5, label="2×LO spur at the “TX-side FR3 RF Out” connector")
    ax.axhline(EXPECTED_BOUND_DBM, color="black", ls="--", lw=1.2,
               label=f"{g(EXPECTED_BOUND_DBM)} dBm: expected upper bound, allowing for unit-to-unit variation")
    ax.plot(lo[i_max], two[i_max], "o", ms=8, mfc="none", mec=RED, mew=1.6)
    ax.annotate(f"Worst: {m(two[i_max])} dBm (LO {lo[i_max]:g} GHz)", (lo[i_max], two[i_max]), xytext=(10, 13),
                textcoords="offset points", color=RED, fontsize=9, va="bottom",
                bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none"))
    ax.plot(lo[i_min], two[i_min], "o", ms=8, mfc="none", mec=GREEN, mew=1.6)
    ax.annotate(f"Best: {m(two[i_min])} dBm (LO {lo[i_min]:g} GHz)", (lo[i_min], two[i_min]), xytext=(12, 2),
                textcoords="offset points", color=GREEN, fontsize=9, va="center")
    ax.set_xlabel("LO frequency (GHz)", color=INK)
    ax.set_ylabel("2×LO spur (dBm at connector)", color=INK)
    ax.set_xlim(lo[0] - 0.15, lo[-1] + 0.15)
    ax.set_ylim(-55, -15)
    sec = ax.secondary_xaxis("top", functions=(lambda v: 2 * v, lambda v: v / 2))
    sec.set_xlabel("2×LO frequency (GHz)", color=INK)
    for s in list(ax.spines.values()) + list(sec.spines.values()):
        s.set_visible(False)
    ax.grid(color=GRID_GREY, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(loc="lower left", fontsize=9, frameon=False)
    plt.close(fig)                                                  # not saved: no longer in the datasheet

    nums = {
        "spurCount": str(len(a)),
        "spurLoMin": g(lo[0]), "spurLoMax": g(lo[-1]), "spurLoStepMHz": g(round((lo[1] - lo[0]) * 1000)),
        "spurTwoLoMin": g(2 * lo[0]), "spurTwoLoMax": g(2 * lo[-1]), "spurTwoLoLimit": g(TWO_LO_MAX_GHZ),
        "spurLoLimit": g(TWO_LO_MAX_GHZ / 2),
        "spurMax": m(two[i_max]), "spurMaxLo": g(lo[i_max]), "spurMaxTwoLo": g(2 * lo[i_max]),
        "spurMedian": m(float(np.median(two))),
        "spurMin": m(two[i_min]), "spurMinLo": g(lo[i_min]), "spurMinTwoLo": g(2 * lo[i_min]),
        "spurExpected": g(EXPECTED_BOUND_DBM),
        "spurLmxMinC": f"{t.min():.0f}", "spurLmxMaxC": f"{t.max():.0f}",
        "spurToneCount": str(len(d5)), "spurToneWithinOne": str(sum(x <= 1.0 for x in d5)),
        "spurToneMedianDiff": f"{st.median(d5):.1f}",
        "spurAmpLow": m(min(plus10)), "spurAmpHigh": m(max(plus10)),
        "spurZeroBiasWorst": m(max(zero)), "spurZeroBiasLoMax": g(round(max(zero_lo))),
    }
    nums.update(rx_port())
    tex = "% generated by FR3_Characterization/plot_datasheet_spurs.py -- do not edit\n" + "".join(
        f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in nums.items())
    out = DATASHEET / "sections" / "sec_spur_numbers.tex"
    out.write_text(tex, encoding="utf-8")
    print(out)
    print(tex)


def _axes(ylabel: str):
    fig, ax = plt.subplots(figsize=(11, 3.6))
    ax.set_xlabel("LO frequency (GHz)", color=INK)
    ax.set_ylabel(ylabel, color=INK)
    ax.grid(color=GRID_GREY, lw=0.8)
    ax.set_axisbelow(True)
    for sp in ax.spines.values():
        sp.set_visible(False)
    return fig, ax


def rx_port() -> dict[str, str]:
    """Figures 2 (LO) and 3 (2xLO) and their numbers: leakage at the "RX-side FR3 RF In" connector. Placeholders if not
    measured yet."""
    # the hot RX re-run at the drive rule, 100 MHz grid (2026-10-09, run 7); the 10-07 drive-0 run is superseded
    files = sorted(glob.glob(str(unit_dir(5) / "2026-10-09" / "rx_port_leakage_*_rx_hot_drive_rule.csv")))
    fig, ax = _axes("LO leakage (dBm at connector)")
    fig3, ax3 = _axes("2\u00d7LO leakage (dBm at connector)")
    keys = ("rxLeakLoCount", "rxLeakLoMin", "rxLeakLoMax", "rxLeakLoMedian", "rxLeakLoMaxAt", "rxLeakLoBest",
            "rxLeakTwoLoCount", "rxLeakTwoLoMax", "rxLeakTwoLoMedian", "rxLeakTwoLoMaxAt", "rxLeakLoFineMax",
            "rxLeakLmxMinC", "rxLeakLmxMaxC", "rxLeakLoTop", "rxLeakLoBestAt", "rxLeakOffsetMv", "rxLeakOffsetCount",
            "rxLeakOffsetMaxChange", "rxLeakOffsetLos")
    if not files:
        for a in (ax, ax3):
            a.set_xlim(6.8, 22.7)
            a.set_ylim(-100, -20)
            a.text(0.5, 0.5, "Awaiting data", transform=a.transAxes, ha="center", va="center", fontsize=20, color="#9e9e9e")
        nums = {k: "--" for k in keys}
    else:
        r = sorted((x for f in files for x in csv.DictReader(open(f, newline=""))), key=lambda x: float(x["lo_ghz"]))
        lo = np.array([float(x["lo_ghz"]) for x in r])
        lv = np.array([float(x["lo_dbm"]) for x in r])
        sel = np.array([x["two_lo_dbm"] != "" for x in r])
        tl = np.array([float(x["two_lo_dbm"]) for x in r if x["two_lo_dbm"] != ""])
        tlo = lo[sel]
        t = np.array([float(x["lmx_temp_c"]) for x in r])
        ax.plot(lo, lv, "-o", color=BLUE, lw=1.2, ms=3, label="LO leakage (at the LO frequency)")
        ax3.plot(tlo, tl, "-o", color="#ef6c00", lw=1.2, ms=3, label="2\u00d7LO leakage (at twice the LO frequency)")
        ax.set_xlim(lo[0] - 0.2, lo[-1] + 0.2)
        ax.legend(loc="upper left", fontsize=9, frameon=False)
        ax3.set_xlim(tlo[0] - 0.1, tlo[-1] + 0.1)                    # 2xLO was measured only up to 2xLO = 26.5 GHz
        ax3.legend(loc="lower left", fontsize=9, frameon=False)
        sec = ax3.secondary_xaxis("top", functions=(lambda v: 2 * v, lambda v: v / 2))
        sec.set_xlabel("2\u00d7LO frequency (GHz)", color=INK)
        for sp in sec.spines.values():
            sp.set_visible(False)
        nums = {"rxLeakLoCount": str(len(lo)), "rxLeakLoMin": g(lo[0]), "rxLeakLoMax": m(lv.max()),
                "rxLeakLoMedian": m(float(np.median(lv))), "rxLeakLoMaxAt": g(lo[int(np.argmax(lv))]), "rxLeakLoBest": m(lv.min()),
                "rxLeakTwoLoCount": str(len(tl)), "rxLeakTwoLoMax": m(tl.max()), "rxLeakTwoLoMedian": m(float(np.median(tl))),
                "rxLeakTwoLoMaxAt": g(tlo[int(np.argmax(tl))]), "rxLeakLoFineMax": g(tlo[-1]),
                "rxLeakLmxMinC": f"{t.min():.0f}", "rxLeakLmxMaxC": f"{t.max():.0f}", "rxLeakLoTop": g(lo[-1]),
                "rxLeakLoBestAt": g(lo[int(np.argmin(lv))])}
        chk = [x for x in r if x.get("lo_dbm_tx_offset")]
        ch = [abs(float(x[f"{k}_dbm_tx_offset"]) - float(x[f"{k}_dbm"])) for x in chk for k in ("lo", "two_lo")
              if x.get(f"{k}_dbm_tx_offset")]
        nums.update({"rxLeakOffsetMv": g(RX_TX_OFFSET_MV), "rxLeakOffsetCount": str(len(chk)),
                     "rxLeakOffsetMaxChange": f"{max(ch):.1f}",
                     "rxLeakOffsetLos": ", ".join(g(float(x["lo_ghz"])) for x in chk)})
    for f_, name in ((fig, "sec_spur_fig2.pdf"), (fig3, "sec_spur_fig3.pdf")):
        f_.tight_layout()
        f_.savefig(IMAGES / name)
        plt.close(f_)
        print(IMAGES / name)
    return nums


if __name__ == "__main__":
    main()
