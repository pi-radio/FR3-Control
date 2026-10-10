"""Analysis of a tx_lo_products.py run: every product vs. IF input level, per case; slopes; case comparisons.

    python analyze_tx_lo_products.py [<run folder>]     (default: newest results/unit_005/tx_lo_products_*)
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from plot_datasheet_nf import use_plex  # noqa: E402
from results_layout import unit_dir  # noqa: E402

PRODUCTS = ("LO", "LO-IF", "LO+IF", "2LO", "2LO-IF", "2LO+IF")
COLORS = {"LO": "#ef6c00", "LO-IF": "#c62828", "LO+IF": "#2e7d32", "2LO": "#6a1b9a", "2LO-IF": "#1565c0",
          "2LO+IF": "#00838f"}
CASES = {"1A": "LO nulled, filter bypassed", "1B": "LO nulled, filter optimal",
         "2A": "I/Q bias 0 V, filter bypassed", "2B": "I/Q bias 0 V, filter optimal"}


def main() -> int:
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(unit_dir(5).glob("tx_lo_products_*"))[-1]
    rows = list(csv.DictReader(open(run / "readings.csv", newline="")))
    import json
    pwr = json.loads((run / "campaign.json").read_text()).get("lmx_power", 7)
    use_plex()
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharex=True, sharey=True)
    summary = {}
    for ax, case in zip(axes.flat, CASES):
        rc = [r for r in rows if r["case"] == case]
        if not rc:
            continue
        off = next((r for r in rc if r["input_dbm"] == "off"), None)
        on = [r for r in rc if r["input_dbm"] != "off"]
        x = np.array([float(r["input_dbm"]) for r in on])
        summary[case] = {"off": off, "on": on}
        for p in PRODUCTS:
            y = np.array([float(r[f"{p}_dbm"]) for r in on])
            ax.plot(x, y, "o-", color=COLORS[p], ms=4, lw=1.4, label=p)
            if off:
                ax.axhline(float(off[f"{p}_dbm"]), color=COLORS[p], lw=0.8, ls=":")
        ax.set_title(f"Case {case}: {CASES[case]}", loc="left", fontsize=11)
        ax.grid(color="#e0e0e0", lw=0.8)
        for s in ax.spines.values():
            s.set_visible(False)
    for ax in axes[1]:
        ax.set_xlabel("IF input at \"TX-side FR1 IF In\" (dBm), 2 GHz")
    for ax in axes[:, 0]:
        ax.set_ylabel("Level at \"TX-side FR3 RF Out\" (dBm)")
    axes[0, 0].legend(frameon=False, fontsize=9, ncol=2, loc="upper left", title="dotted = input off", title_fontsize=8)
    fig.suptitle(f"TX products vs IF input: FR1 = 2 GHz, LO = 9 GHz, upper sideband (unit 5, LMX PWR {pwr})", x=0.01,
                 ha="left", fontsize=12)
    fig.tight_layout()
    out = run / "tx_lo_products.png"
    fig.savefig(out, dpi=130)
    print(out)

    print("\nINPUT OFF (dBm at TX-side FR3 RF Out):")
    print("case  " + "  ".join(f"{p:>8s}" for p in PRODUCTS))
    for case, s in summary.items():
        if s["off"]:
            print(f"{case:4s}  " + "  ".join(f"{float(s['off'][p + '_dbm']):8.1f}" for p in PRODUCTS))
    print("\nSLOPES (dB per dB of input), least squares over -60...-30 dBm, and over the lowest 4 levels:")
    print("case  " + "  ".join(f"{p:>13s}" for p in PRODUCTS))
    for case, s in summary.items():
        x = np.array([float(r["input_dbm"]) for r in s["on"]])
        cells = []
        for p in PRODUCTS:
            y = np.array([float(r[f"{p}_dbm"]) for r in s["on"]])
            k_all = np.polyfit(x, y, 1)[0]
            k_low = np.polyfit(x[:4], y[:4], 1)[0]
            cells.append(f"{k_all:5.2f} ({k_low:4.2f})")
        print(f"{case:4s}  " + "  ".join(f"{c:>13s}" for c in cells))
    print("\nFULL TABLE (dBm):")
    for case, s in summary.items():
        print(f"\nCase {case}: {CASES[case]}")
        print("  input  " + "  ".join(f"{p:>8s}" for p in PRODUCTS) + "   SB supp. (LO+IF minus LO-IF)")
        for r in ([s["off"]] if s["off"] else []) + s["on"]:
            v = [float(r[p + "_dbm"]) for p in PRODUCTS]
            sb = "" if r["input_dbm"] == "off" else f"{v[2] - v[1]:6.1f} dB"
            print(f"  {r['input_dbm']:>5s}  " + "  ".join(f"{a:8.1f}" for a in v) + f"   {sb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
