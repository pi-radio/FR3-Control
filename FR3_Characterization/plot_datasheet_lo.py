"""SUPERSEDED (2026-10-09) by plot_datasheet_lo_cal.py + make_sec6_cal_numbers.py: its outputs (images/sec6_fig1-3.pdf,
sections/sec6_numbers.tex) were deleted from the datasheet. Kept only because plot_datasheet_lo_cal.py imports its
style helpers (house, signed_int, colours); do not run it to make datasheet figures.

Original description: Datasheet figures and numbers for the TX-side LO suppression section (sections/section6_lo_suppression.tex, printed as
Section 7), unit 5. User spec 2026-10-05:

  images/sec6_fig1.pdf  LO leakage vs LO frequency: uncalibrated (I_V = Q_V = 0 V) and calibrated (bias interpolated /
                        extrapolated at run time between the cold and hot tables), with the -20 dBm threshold, Worse/Better
                        arrows and the share of LOs below the threshold (full page width)
  images/sec6_fig2.pdf  the same two data sets as histograms
  images/sec6_fig3.pdf  the calibration tables: I_V and Q_V vs LO frequency, cold and hot (one line width, four colours)
  sections/sec6_numbers.tex  every number the section text and captions quote

    python plot_datasheet_lo.py
"""
from __future__ import annotations

import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from plot_datasheet_nf import DATASHEET, GRID_GREY, IMAGES, INK, use_plex  # noqa: E402
from results_layout import unit_dir  # noqa: E402

COLD = "golden_lo_null_5MHz_20260927"
HOT = "lo_null_hot_5MHz_20261004"
INTERP = "lo_null_interpolated_5MHz_20261005"
UNCAL = "unsuppressed_lo_leakage_5MHz_20260930"
THRESHOLD_DBM = -20.0
RED, GREEN = "#c62828", "#2e7d32"
I_COLD, I_HOT, Q_COLD, Q_HOT = "#1565c0", "#6a1b9a", "#ef6c00", "#00897b"   # blue, purple, orange, teal


def signed(v: float) -> str:
    """+13.7 / −41.4: explicit sign, typographic minus (U+2212) so it reads clearly."""
    return f"{v:+.1f}".replace("-", "\u2212")


def signed_int(v: float) -> str:
    return f"{v:g}".replace("-", "−")


def table(campaign: str) -> dict[str, dict]:
    return {r["freq_ghz"]: r for r in csv.DictReader(open(unit_dir(5) / campaign / "lo_null_table.csv", newline=""))}


def house(ax, title: str) -> None:
    ax.set_title(title, loc="left", color=INK)
    ax.grid(color=GRID_GREY, lw=0.8)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)


def main() -> None:
    use_plex()
    u = unit_dir(5)
    rows = list(csv.DictReader(open(u / INTERP / "interpolated.csv", newline="")))
    uncal = {f"{int(r['lo_hz']) / 1e9:.3f}": float(r["level_dbm_at_board"])
             for r in csv.DictReader(open(u / UNCAL / "unsuppressed_lo_leakage.csv", newline=""))}
    keys = [r["freq_ghz"] for r in rows]
    f = np.array([float(k) for k in keys])
    cal = np.array([float(r["leakage_dbm_at_board"]) for r in rows])
    unc = np.array([uncal[k] for k in keys])
    t_run = np.array([float(r["lmx_temp_c"]) for r in rows])
    pct_cal, pct_unc = 100 * np.mean(cal < THRESHOLD_DBM), 100 * np.mean(unc < THRESHOLD_DBM)

    # ---- Figure 1: leakage vs frequency, full page width ----
    fig, ax = plt.subplots(figsize=(11, 3.5))
    ax.plot(f, unc, lw=1.0, color=RED,
            label=f"Uncalibrated: Only {pct_unc:.1f}% of LOs are better (lower) than {signed_int(THRESHOLD_DBM)}dBm")
    ax.plot(f, cal, lw=1.0, color=GREEN,
            label=f"Calibrated: {pct_cal:.1f}% of LOs are better (lower) than {signed_int(THRESHOLD_DBM)}dBm")
    ax.axhline(THRESHOLD_DBM, color="black", ls="--", lw=1.2, label=f"Threshold: {signed_int(THRESHOLD_DBM)}dBm")
    x_arrow, length = 6.85, 20.0                                   # in the empty 6-7 GHz strip, left of the data
    for direction, word in ((+1, "Worse"), (-1, "Better")):
        ax.annotate("", xy=(x_arrow, THRESHOLD_DBM + direction * length), xytext=(x_arrow, THRESHOLD_DBM),
                    arrowprops=dict(arrowstyle="-|>", color="black", lw=1.5))
        ax.text(x_arrow, THRESHOLD_DBM + direction * (length + 1.5), word, color="black", fontsize=10, ha="center",
                va="bottom" if direction > 0 else "top")
    ax.set_xlim(6, 24)
    ax.set_ylim(-95, 25)                                           # room for the legend below the data
    ax.set_xlabel("LO Frequency (GHz)")
    ax.set_ylabel("LO Leakage (dBm at connector)")
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    house(ax, 'LO Leakage at the "TX-side FR3 RF Out" Connector: Uncalibrated vs Calibrated')
    fig.savefig(IMAGES / "sec6_fig1.pdf", bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 2: the same as histograms ----
    fig, ax = plt.subplots(figsize=(11, 2.8))
    bins = np.arange(np.floor(min(cal.min(), unc.min())), np.ceil(max(cal.max(), unc.max())) + 1, 1.0)
    ax.hist(unc, bins=bins, histtype="step", lw=1.6, color=RED)
    ax.hist(cal, bins=bins, histtype="step", lw=1.6, color=GREEN)
    ax.set_xlabel("LO Leakage (dBm at connector)")
    ax.set_ylabel("Number of LO frequencies (1 dB bins)")
    house(ax, f"LO Leakage Distribution over {len(f)} LO Frequencies (7 to 22.6 GHz in 5 MHz steps)")
    # Hand-placed legend (user layout): the two entries equidistant above/below the 500 gridline, top-left, with the
    # "(Median: ...)" parts left-aligned with each other.
    ax.set_ylim(0, 600)
    ax.set_xlim(bins[0] - 1, bins[-1] + 1)
    x0, gap, box_w, box_h = bins[0] - 0.5, 35.0, 2.6, 24.0
    entries = ((500 + gap, RED, "Uncalibrated", f"(Median: {signed(np.median(unc))}dBm)"),
               (500 - gap, GREEN, "Calibrated", f"(Median: {signed(np.median(cal))}dBm)"))
    names = []
    for y, col, name, _ in entries:
        ax.add_patch(Rectangle((x0, y - box_h / 2), box_w, box_h, facecolor="none", edgecolor=col, lw=1.6))
        names.append(ax.text(x0 + box_w + 1.0, y, name, fontsize=9, va="center", ha="left", color=INK))
    fig.canvas.draw()
    inv = ax.transData.inverted()
    right = max(inv.transform((t.get_window_extent().x1, 0))[0] for t in names)
    for y, _, _, median in entries:
        ax.text(right + 0.25, y, median, fontsize=9, va="center", ha="left", color=INK)
    fig.savefig(IMAGES / "sec6_fig2.pdf", bbox_inches="tight")
    plt.close(fig)

    # ---- Figure 3: the calibration tables ----
    cold, hot = table(COLD), table(HOT)
    fk = sorted((k for k in hot if k in cold), key=float)
    ff = np.array([float(k) for k in fk])
    fig, ax = plt.subplots(figsize=(11, 3.1))
    for t, var, col, lab in ((cold, "i_v", I_COLD, "I_V (cold)"), (hot, "i_v", I_HOT, "I_V (hot)"),
                             (cold, "q_v", Q_COLD, "Q_V (cold)"), (hot, "q_v", Q_HOT, "Q_V (hot)")):
        ax.plot(ff, [float(t[k][var]) for k in fk], lw=1.0, color=col, label=lab)
    ax.set_xlabel("LO Frequency (GHz)")
    ax.set_ylabel("Bias Voltage (V)")
    ax.legend(frameon=False, fontsize=9, ncol=2, loc="upper right")
    house(ax, "Calibration Tables: I/Q Bias that Nulls the LO, Cold and Hot")
    fig.savefig(IMAGES / "sec6_fig3.pdf", bbox_inches="tight")
    plt.close(fig)

    # ---- numbers ----
    tc = np.array([float(cold[k]["lmx_temp_c"]) for k in fk])
    th = np.array([float(hot[k]["lmx_temp_c"]) for k in fk])
    macros = {
        "loColdMeanC": f"{tc.mean():.0f}", "loColdMinC": f"{tc.min():.0f}", "loColdMaxC": f"{tc.max():.0f}",
        "loHotMeanC": f"{th.mean():.0f}", "loHotMinC": f"{th.min():.0f}", "loHotMaxC": f"{th.max():.0f}",
        "loCount": f"{len(f)}", "loThreshold": f"{THRESHOLD_DBM:g}".replace("-", "−"),
        "loPctCal": f"{pct_cal:.1f}", "loPctUncal": f"{pct_unc:.1f}",
        "loMedCal": f"{np.median(cal):.0f}".replace("-", "−"), "loMedUncal": f"{np.median(unc):.0f}",
        "loMedSuppression": f"{np.median(unc - cal):.0f}",
        "loRunMinC": f"{t_run.min():.0f}", "loRunMaxC": f"{t_run.max():.0f}",
    }
    out = DATASHEET / "sections" / "sec6_numbers.tex"
    out.write_text("% generated by FR3_Characterization/plot_datasheet_lo.py -- do not edit\n"
                   + "".join(f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in macros.items()), encoding="utf-8")
    for k, v in macros.items():
        print(f"{k:18s} {v}")


if __name__ == "__main__":
    main()
