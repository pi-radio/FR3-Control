"""Tests for the LO suppression calibration table lookup, against the real
data file shipped in data/lo_suppression.csv."""

from __future__ import annotations

import pytest

from fr3_gui.lo_suppression import MAX_TABLE_FREQ_GHZ, MIN_TABLE_FREQ_GHZ, suggest_iv_qv


def test_below_min_returns_none():
    assert suggest_iv_qv(MIN_TABLE_FREQ_GHZ - 0.1) is None
    assert suggest_iv_qv(1.0) is None


def test_exact_table_point_matches_measured_value():
    # From the raw data: 7.0 GHz -> i_v=-0.18, q_v=0.372
    i_v, q_v = suggest_iv_qv(MIN_TABLE_FREQ_GHZ)
    assert i_v == pytest.approx(-0.18)
    assert q_v == pytest.approx(0.372)


def test_interpolates_between_two_points():
    # 7.0 -> (-0.18, 0.372), 7.1 -> (-0.15, 0.289); halfway should be the
    # arithmetic mean of the two, for a linear interpolation.
    i_v, q_v = suggest_iv_qv(MIN_TABLE_FREQ_GHZ + 0.05)
    assert i_v == pytest.approx((-0.18 + -0.15) / 2, abs=1e-6)
    assert q_v == pytest.approx((0.372 + 0.289) / 2, abs=1e-6)


def test_above_max_clamps_to_last_point():
    i_v_at_max, q_v_at_max = suggest_iv_qv(MAX_TABLE_FREQ_GHZ)
    i_v_above, q_v_above = suggest_iv_qv(MAX_TABLE_FREQ_GHZ + 5.0)
    assert i_v_above == pytest.approx(i_v_at_max)
    assert q_v_above == pytest.approx(q_v_at_max)
