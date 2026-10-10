"""Cable loss from the S21 files saved by capture_cable_s21.py.

    fr1 = CableLoss("fr1_cable")      # IF-in cable, 0.5-4.5 GHz
    fr3 = CableLoss("fr3_cable")      # RF-out cable, 2-26.5 GHz
    fr1.s21_db(2e9)                   # -0.755 (negative = loss)

Always uses the newest file for the name. Asking for a frequency outside the
captured range raises instead of silently clamping to the end value."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

CALIBRATION_DIR = Path(__file__).resolve().parent / "calibration"


class CableLoss:
    def __init__(self, name: str, directory: Path = CALIBRATION_DIR):
        files = sorted(directory.glob(f"{name}_s21_*.csv"))
        if not files:
            raise FileNotFoundError(f"no {name}_s21_*.csv in {directory} - capture it first "
                                    f"with capture_cable_s21.py --name {name}")
        self.path = files[-1]  # timestamped names sort chronologically
        with open(self.path, newline="") as f:
            rows = list(csv.DictReader(f))
        self._freq_hz = np.array([float(r["freq_hz"]) for r in rows])
        self._s21_db = np.array([float(r["s21_db"]) for r in rows])

    @property
    def range_hz(self) -> tuple[float, float]:
        return float(self._freq_hz[0]), float(self._freq_hz[-1])

    def s21_db_array(self, freq_hz) -> np.ndarray:
        """Vectorized s21_db(): same range check (raises if any frequency is outside the data)."""
        f = np.asarray(freq_hz, dtype=float)
        lo, hi = self.range_hz
        if f.min() < lo or f.max() > hi:
            raise ValueError(f"{f.min()/1e9:.3f}-{f.max()/1e9:.3f} GHz is outside {self.path.name} "
                             f"({lo/1e9:g}-{hi/1e9:g} GHz)")
        return np.interp(f, self._freq_hz, self._s21_db)

    def s21_db(self, freq_hz: float) -> float:
        lo, hi = self.range_hz
        if not lo <= freq_hz <= hi:
            raise ValueError(f"{freq_hz/1e9:.3f} GHz is outside {self.path.name} "
                             f"({lo/1e9:g}-{hi/1e9:g} GHz)")
        return float(np.interp(freq_hz, self._freq_hz, self._s21_db))
