"""Gain-flatness figures of merit over a frequency band. Pure functions (no
instruments) so they can be tested against curves with known answers.

For a band [lo, hi] (Hz) and a gain curve (dB):
  peak_to_peak_db   max - min inside the band
  plus_minus_db     half of peak-to-peak (the usual "+/- x dB" datasheet form)
  slope_db_per_100mhz   straight-line trend across the band
  ripple_pp_db      peak-to-peak of what is left after removing that trend
                    (fast variation that a slope alone doesn't explain)
  mean_db, std_db"""

from __future__ import annotations

import numpy as np


def flatness_metrics(freq_hz, gain_db, band_hz: tuple[float, float]) -> dict:
    f = np.asarray(freq_hz, dtype=float)
    g = np.asarray(gain_db, dtype=float)
    lo, hi = band_hz
    mask = (f >= lo) & (f <= hi)
    if mask.sum() < 3:
        raise ValueError(f"fewer than 3 points inside the band {lo/1e6:g}-{hi/1e6:g} MHz")
    fb, gb = f[mask], g[mask]
    slope_per_100mhz, intercept = np.polyfit(fb / 1e8, gb, 1)
    residual = gb - (slope_per_100mhz * (fb / 1e8) + intercept)
    return {
        "points": int(mask.sum()),
        "mean_db": float(gb.mean()),
        "std_db": float(gb.std()),
        "min_db": float(gb.min()),
        "max_db": float(gb.max()),
        "peak_to_peak_db": float(gb.max() - gb.min()),
        "plus_minus_db": float((gb.max() - gb.min()) / 2),
        "slope_db_per_100mhz": float(slope_per_100mhz),
        "ripple_pp_db": float(residual.max() - residual.min()),
    }
