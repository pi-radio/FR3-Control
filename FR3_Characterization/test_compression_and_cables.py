"""Offline tests: compression math against curves with known answers, and
cable-loss lookup."""

from __future__ import annotations

import pytest

from cables import CableLoss
from compression import compression_point, small_signal_gain


def synthetic_sweep(g0=20.0, knee_dbm=-20.0, slope=0.5):
    """Gain flat at g0 until knee_dbm, then compressing slope dB per dB.
    Compression = slope*(pin-knee): 1 dB at knee+2 (-18), 3 dB at knee+6 (-14)."""
    pin = [-45.0 + 2 * i for i in range(17)]          # -45 ... -13
    comp = [max(0.0, slope * (p - knee_dbm)) for p in pin]
    pout = [p + g0 - c for p, c in zip(pin, comp)]
    return pin, pout


def test_p1db_and_p3db_match_the_known_curve():
    pin, pout = synthetic_sweep()
    g0 = small_signal_gain([po - pi for pi, po in zip(pin, pout)])
    assert g0 == pytest.approx(20.0)
    p1 = compression_point(pin, pout, g0, 1.0)
    p3 = compression_point(pin, pout, g0, 3.0)
    assert (p1.pin_dbm, p1.pout_dbm) == pytest.approx((-18.0, 1.0))
    assert (p3.pin_dbm, p3.pout_dbm) == pytest.approx((-14.0, 3.0))


def test_none_when_the_sweep_never_compresses_that_far():
    pin, pout = synthetic_sweep()
    assert compression_point(pin[:8], pout[:8], 20.0, 1.0) is None


def test_small_signal_gain_waits_for_enough_points_and_rejects_a_messy_start():
    assert small_signal_gain([20.0, 20.1]) is None
    with pytest.raises(ValueError, match="spread"):
        small_signal_gain([20.0, 21.0, 20.1])


def write_cable(directory, name, stamp, s21):
    (directory / f"{name}_s21_{stamp}.csv").write_text(
        "freq_hz,s21_db,s21_phase_deg,s21_re,s21_im\n"
        + "".join(f"{f},{db},0,0,0\n" for f, db in s21))


def test_cable_interpolates_uses_newest_file_and_refuses_out_of_range(tmp_path):
    write_cable(tmp_path, "cab", "20260101_000000", [(1e9, -9.0), (3e9, -9.0)])
    write_cable(tmp_path, "cab", "20260202_000000", [(1e9, -1.0), (3e9, -3.0)])
    cable = CableLoss("cab", tmp_path)
    assert cable.s21_db(2e9) == pytest.approx(-2.0)
    with pytest.raises(ValueError, match="outside"):
        cable.s21_db(4e9)
    with pytest.raises(FileNotFoundError):
        CableLoss("missing", tmp_path)
