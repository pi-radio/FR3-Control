"""LMX temperature vs time for the hot LO-null run (unit 5), from <campaign>/lmx_temperature_log.csv (the reading taken before
every LO, plus any waiting/cool-down readings during the run; the pre-start waiting readings are left out). The LO frequency is shown on a second axis; the 72 C minimum and 110 C cutoff
as lines. Output: <campaign>/temperature_vs_time.png

    python plot_hot_run_temperature.py
"""
import csv
import re
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from results_layout import unit_dir

CAMPAIGN = "lo_null_hot_5MHz_20261004"
MIN_C, CUTOFF_C = 72.0, 110.0


def main() -> None:
    d = unit_dir(5) / CAMPAIGN
    t, temp, lo, t_lo = [], [], [], []
    with open(d / "lmx_temperature_log.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            if not r["phase"].startswith(("scan", "cooling", "just before")):
                continue                              # readings taken while waiting for the start are not part of the run
            ts = datetime.fromisoformat(r["time"]).replace(tzinfo=None)
            t.append(ts)
            temp.append(float(r["lmx_temp_c"]))
            m = re.search(r"before LO ([\d.]+) GHz", r["phase"])
            if m and r["phase"].startswith("scan, before"):
                t_lo.append(ts)
                lo.append(float(m.group(1)))
    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.plot(t, temp, ".", ms=3, color="tab:red", label="LMX die temperature (reading before each LO)")
    ax.axhline(MIN_C, color="tab:blue", ls="--", lw=1, label=f"{MIN_C:g} C minimum")
    ax.set_ylabel("LMX die temperature (C)")
    ax.set_ylim(min(MIN_C - 2, min(temp) - 1), max(temp) + 3)
    ax.grid(alpha=0.3)
    ax2 = ax.twinx()
    ax2.plot(t_lo, lo, "-", lw=1, color="0.5", label="LO frequency")
    ax2.axhline(11.3, color="0.5", ls=":", lw=1)
    ax2.text(t_lo[0] if t_lo else t[0], 11.4, " doubler above 11.3 GHz", color="0.4", fontsize=8, va="bottom")
    ax2.set_ylabel("LO frequency (GHz)")
    ax2.set_ylim(6, 23)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_xlabel(f"time ({t[0]:%Y-%m-%d})")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8)
    ax.set_title(f"Hot LO-null run, unit 5: LMX temperature vs time  ({len(t_lo)} LOs, "
                 f"{min(temp):.1f}-{max(temp):.1f} C; cutoff {CUTOFF_C:g} C off-scale)")
    fig.tight_layout()
    out = d / "temperature_vs_time.png"
    fig.savefig(out, dpi=150)
    print(out)


if __name__ == "__main__":
    main()
