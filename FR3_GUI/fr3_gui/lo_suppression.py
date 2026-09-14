"""LO leakage suppression calibration: measured I_V/Q_V values (on one
device) at discrete LMX2820 frequencies that null its own LO leakage. Only
meaningful with the internal LMX2820 - callers shouldn't offer this with
an external LO.

Table covers 7.0-22.6GHz only; below that, use a high-side LO with the
lower sideband instead - callers must not interpolate below
MIN_TABLE_FREQ_GHZ.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

import numpy as np

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "lo_suppression.csv"


def _load_table() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    freqs, i_vs, q_vs = [], [], []
    with open(DATA_FILE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            freqs.append(float(row["freq_ghz"]))
            i_vs.append(float(row["i_v"]))
            q_vs.append(float(row["q_v"]))
    return np.array(freqs), np.array(i_vs), np.array(q_vs)


_FREQ_GHZ, _I_V, _Q_V = _load_table()

MIN_TABLE_FREQ_GHZ = float(_FREQ_GHZ.min())
MAX_TABLE_FREQ_GHZ = float(_FREQ_GHZ.max())


def suggest_iv_qv(freq_ghz: float) -> Optional[tuple[float, float]]:
    """Linear interpolation between the two nearest table points; None
    below MIN_TABLE_FREQ_GHZ (no data there). Clamps above
    MAX_TABLE_FREQ_GHZ rather than extrapolating."""
    if freq_ghz < MIN_TABLE_FREQ_GHZ:
        return None
    i_v = float(np.interp(freq_ghz, _FREQ_GHZ, _I_V))
    q_v = float(np.interp(freq_ghz, _FREQ_GHZ, _Q_V))
    return i_v, q_v
