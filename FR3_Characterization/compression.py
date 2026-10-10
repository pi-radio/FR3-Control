"""Small-signal gain and compression-point extraction from a power sweep.
Pure functions (no instruments) so they can be tested against known curves.

Definitions used throughout:
  gain        = Pout - Pin at each drive level (dB)
  G0          = small-signal gain: mean gain over the first few valid,
                mutually consistent (low-drive) points
  compression = G0 - gain
  P1dB / P3dB = the drive level at which compression reaches 1 dB / 3 dB,
                linearly interpolated between the two bracketing points;
                reported input-referred (Pin) and output-referred (Pout)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompressionPoint:
    drop_db: float
    pin_dbm: float
    pout_dbm: float


def small_signal_gain(gains_db: list[float], n: int = 3, max_spread_db: float = 0.5) -> float | None:
    """Mean of the first n gains, or None if fewer than n are available yet.
    Raises if those n disagree by more than max_spread_db - a sign that the
    'small-signal' region isn't clean (noise-limited or already compressing)."""
    if len(gains_db) < n:
        return None
    first = gains_db[:n]
    spread = max(first) - min(first)
    if spread > max_spread_db:
        raise ValueError(f"first {n} gains spread {spread:.2f} dB (> {max_spread_db} dB): "
                         f"{[round(g, 2) for g in first]}")
    return sum(first) / n


def compression_point(pin_dbm: list[float], pout_dbm: list[float], g0_db: float,
                      drop_db: float) -> CompressionPoint | None:
    """First drive level at which gain has fallen drop_db below g0_db, or None
    if the sweep never got there."""
    gains = [po - pi for pi, po in zip(pin_dbm, pout_dbm)]
    target = g0_db - drop_db
    for i in range(1, len(gains)):
        if gains[i] <= target < gains[i - 1]:
            frac = (gains[i - 1] - target) / (gains[i - 1] - gains[i])
            return CompressionPoint(
                drop_db=drop_db,
                pin_dbm=pin_dbm[i - 1] + frac * (pin_dbm[i] - pin_dbm[i - 1]),
                pout_dbm=pout_dbm[i - 1] + frac * (pout_dbm[i] - pout_dbm[i - 1]),
            )
    return None
