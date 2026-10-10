"""Plot LO phase noise runs from phase_noise_capture.py (results/unit_<n>/phase_noise/*.csv).

    python plot_phase_noise.py RUN.csv [--out FILE.png]

One run: the smoothed trace (trace 2) bold and the unsmoothed one (trace 1) thin; decade offsets are labelled with
the smoothed value. No carrier
level and no UXA floor are shown (user, 2026-10-04): the UXA's own phase noise is well below the board's.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from plot_datasheet_nf import INK, INK2, GRID_GREY, use_plex  # noqa: E402

COLOURS = ["#2b7bd6", "#c0392b", "#2e7d32", "#ef6c00"]


def load(path: Path):
    rows = list(csv.DictReader(open(path)))
    f = np.array([float(r["offset_hz"]) for r in rows])
    t1 = np.array([float(r["trace1_dbc_hz"]) for r in rows])
    t2 = np.array([float(r["trace2_dbc_hz"]) for r in rows])
    meta_path = path.with_suffix(".json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return f, t1, t2, meta


def decade_values(run: Path) -> dict[float, float]:
    """Phase noise (trace 2) at 100 Hz, 1 kHz, 10 kHz, 100 kHz and 1 MHz offset."""
    f, _, t2, _ = load(run)
    return {dec: float(np.interp(np.log10(dec), np.log10(f), t2)) for dec in (100, 1e3, 1e4, 1e5, 1e6)}


def plot_run(run: Path, out: Path) -> None:
    use_plex()
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    # one run: trace 1 = raw (unsmoothed) average, thin; trace 2 = the UXA's smoothed trace, bold (both are the
    # average of the run's 10 measurements; trace assignment per the Phase Noise app's preset: RAW|SMO|BLANK)
    f, t1, t2, meta = load(run)
    c = COLOURS[0]
    lo = meta.get("lo_hz", 0) / 1e9
    ax.semilogx(f, t1, color=c, lw=0.6, alpha=0.55, label="Unsmoothed")
    ax.semilogx(f, t2, color=c, lw=2.0, label="Smoothed")
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    for dec in (100, 1e3, 1e4, 1e5, 1e6):
        v = float(np.interp(np.log10(dec), np.log10(f), t2))
        ax.plot(dec, v, "o", color=c, ms=4)
        ax.annotate(f"{v:.1f}".replace("-", "−"), (dec, v), textcoords="offset points", xytext=(4, 6), fontsize=8, color=INK)
    ax.set_xlim(100, 1e6)
    ax.set_ylim(-140, -40)
    ax.set_xlabel("Offset from Carrier (Hz)")
    ax.set_ylabel("Phase Noise (dBc/Hz)")
    ax.set_title(f"Phase Noise of the Internal LO at {lo:g} GHz (10 MHz TCXO + LMX2820)", loc="left", color=INK)
    ax.grid(True, which="both", color=GRID_GREY, lw=0.6)
    for s in ax.spines.values():
        s.set_color(GRID_GREY)
    fig.savefig(out, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


def plot_compare(runs: list[tuple[Path, str]], title: str, out: Path) -> None:
    """Several runs on one axes: each smoothed bold + unsmoothed thin, labelled with its RMS phase error."""
    use_plex()
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    for k, (run, name) in enumerate(runs):
        f, t1, t2, meta = load(run)
        c = COLOURS[k % len(COLOURS)]
        ax.semilogx(f, t1, color=c, lw=0.6, alpha=0.5)
        ax.semilogx(f, t2, color=c, lw=2.0, label=f"{name}: RMS phase error {meta['rms_pn_deg']:.2f}°")
        for dec in (100, 1e3, 1e4, 1e5, 1e6):
            v = float(np.interp(np.log10(dec), np.log10(f), t2))
            ax.plot(dec, v, "o", color=c, ms=4)
            ax.annotate(f"{v:.1f}".replace("-", "−"), (dec, v), textcoords="offset points", xytext=(4, 6), fontsize=8, color=c)
    ax.set_xlim(100, 1e6)
    ax.set_ylim(-140, -40)
    ax.set_xlabel("Offset from Carrier (Hz)")
    ax.set_ylabel("Phase Noise (dBc/Hz)")
    ax.set_title(title, loc="left", color=INK)
    ax.grid(True, which="both", color=GRID_GREY, lw=0.6)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right",
              title="thick: smoothed   thin: unsmoothed (10 averages)", title_fontsize=7.5)
    for s in ax.spines.values():
        s.set_color(GRID_GREY)
    fig.savefig(out, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path, help="one phase_noise_capture.py run (.csv)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    plot_run(args.run, args.out or args.run.with_suffix(".png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
