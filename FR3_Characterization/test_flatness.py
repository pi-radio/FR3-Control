"""Offline tests for the flatness figures of merit, against curves whose
answers are known exactly."""

from __future__ import annotations

import numpy as np
import pytest

from flatness_metrics import flatness_metrics

FREQ = np.arange(1.6e9, 2.4e9 + 1, 5e6)          # the scan grid: 161 points
BAND = (1.75e9, 2.25e9)                          # the 500 MHz signal band


def test_a_perfectly_flat_response():
    m = flatness_metrics(FREQ, np.full(FREQ.size, 33.0), BAND)
    assert m["peak_to_peak_db"] == pytest.approx(0.0)
    assert m["slope_db_per_100mhz"] == pytest.approx(0.0, abs=1e-9)
    assert m["mean_db"] == pytest.approx(33.0)
    assert m["points"] == 101                    # 1.75 ... 2.25 GHz inclusive at 5 MHz


def test_a_pure_slope_has_no_ripple():
    gain = 33.0 + 0.4 * (FREQ - 2.0e9) / 1e8     # +0.4 dB per 100 MHz
    m = flatness_metrics(FREQ, gain, BAND)
    assert m["slope_db_per_100mhz"] == pytest.approx(0.4)
    assert m["peak_to_peak_db"] == pytest.approx(2.0)       # 0.4 x 5 (500 MHz)
    assert m["plus_minus_db"] == pytest.approx(1.0)
    assert m["ripple_pp_db"] == pytest.approx(0.0, abs=1e-9)
    assert m["mean_db"] == pytest.approx(33.0)


def test_ripple_is_separated_from_slope():
    gain = 33.0 + 0.4 * (FREQ - 2.0e9) / 1e8 + 0.15 * np.sin(2 * np.pi * (FREQ - 1.75e9) / 100e6)
    m = flatness_metrics(FREQ, gain, BAND)
    assert m["slope_db_per_100mhz"] == pytest.approx(0.4, abs=0.02)
    # +/-0.15 dB of ripple = 0.30 dB peak-to-peak. A sine over whole periods still leaks a little
    # into the straight-line fit (about 0.01 dB/100 MHz here), which tilts the residual by ~0.06 dB
    # across the band, so the measured ripple is 0.30 to 0.36, not exactly 0.30.
    assert 0.30 <= m["ripple_pp_db"] <= 0.36


def test_only_points_inside_the_band_count():
    gain = np.where((FREQ >= BAND[0]) & (FREQ <= BAND[1]), 33.0, 20.0)   # huge roll-off outside
    m = flatness_metrics(FREQ, gain, BAND)
    assert m["peak_to_peak_db"] == pytest.approx(0.0)


def test_too_few_points_in_band_is_an_error():
    with pytest.raises(ValueError, match="fewer than 3"):
        flatness_metrics(FREQ, np.zeros(FREQ.size), (5e9, 6e9))
