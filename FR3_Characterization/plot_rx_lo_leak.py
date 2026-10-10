"""Hardware-investigation plot (not a datasheet figure): LO and 2*LO coming out of "RX-side FR3 RF In" vs LO frequency,
for each RX filter state, from spur_campaign.py --phase rx_lo (TX side optimal + nulled, LMX PWR 7, unused ports
terminated).

    python plot_rx_lo_leak.py [--campaign spurs_20261005] [--out <png>]
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from plot_datasheet_nf import use_plex  # noqa: E402
from results_layout import unit_dir  # noqa: E402

STYLE = {"bypass": ("#424242", "RX filter bypassed"), "optimal_low": ("#1565c0", "RX filter optimal, low-side LO"),
         "optimal_high": ("#c62828", "RX filter optimal, high-side LO")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=5)
    ap.add_argument("--campaign", default="spurs_20261005")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    use_plex()
    rows = [r for r in csv.DictReader(open(unit_dir(args.unit) / args.campaign / "rx_lo.csv", newline=""))
            if r.get("status") == "ok"]
    data = defaultdict(list)
    for r in rows:
        data[(r["product"], r["filter"])].append((float(r["lo_hz"]) / 1e9, float(r["level_dbm"]), float(r["floor_dbm"])))
    fig, axes = plt.subplots(2, 1, figsize=(10, 7.5), sharex=True)
    for ax, prod, title in ((axes[0], "LO", "LO (fundamental) out of \"RX-side FR3 RF In\""),
                            (axes[1], "2LO", "2·LO out of \"RX-side FR3 RF In\" (visible up to LO = 13.25 GHz)")):
        for filt, (col, lab) in STYLE.items():
            pts = sorted(data.get((prod, filt), []))
            if not pts:
                continue
            x, y, fl = zip(*pts)
            ax.plot(x, y, "o-", color=col, ms=4, lw=1.3, label=lab)
            if filt == "bypass":
                ax.plot(x, fl, color="#9e9e9e", lw=0.9, ls=":", label="Noise floor")
        ax.set_title(title, loc="left", fontsize=11)
        ax.set_ylabel("Level at connector (dBm)")
        ax.grid(color="#e0e0e0", lw=0.8)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.legend(frameon=False, fontsize=8, loc="best")
    axes[1].set_xlabel("LO Frequency (GHz)")
    fig.suptitle("RX-side LO leakage at the RF input (LMX PWR 7, TX optimal + nulled, unused ports terminated)",
                 x=0.01, ha="left", fontsize=12)
    fig.tight_layout()
    out = args.out or str(unit_dir(args.unit) / args.campaign / "rx_lo_leak.png")
    fig.savefig(out, dpi=130)
    print(out)
    for prod in ("LO", "2LO"):
        for filt in STYLE:
            pts = sorted(data.get((prod, filt), []))
            if pts:
                lv = [p[1] for p in pts]
                worst = max(pts, key=lambda p: p[1])
                print(f"{prod:3s} {filt:12s} n={len(pts):2d}  median {sorted(lv)[len(lv) // 2]:7.1f} dBm   worst {worst[1]:7.1f} dBm at LO {worst[0]:g} GHz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
