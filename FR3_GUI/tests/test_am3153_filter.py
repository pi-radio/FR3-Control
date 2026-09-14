"""Tests for the AM3153 filter-bits -> S-parameter-file mapping and parser,
against the real data files shipped in data/am3153_sparams/."""

from __future__ import annotations

from fr3_gui.am3153_filter import _filename_for_bits, get_response


def test_bypass_maps_for_any_low_nibble():
    for low in range(16):
        assert _filename_for_bits(low) == "AM3153_SN2_5V_6mA_Bypass.s2p"


def test_band_mapping_matches_datasheet_state_table():
    # VA=1,VB=1 (bits 5,4 set) -> Band1; VA=0,VB=1 -> Band2; VA=1,VB=0 -> Band3
    assert _filename_for_bits(0b110000) == "AM3153_SN2_5V_6mA_Band1_0000.s2p"
    assert _filename_for_bits(0b010000) == "AM3153_SN2_5V_6mA_Band2_0000.s2p"
    assert _filename_for_bits(0b100000) == "AM3153_SN2_5V_6mA_Band3_0000.s2p"


def test_low_nibble_is_binary_suffix():
    assert _filename_for_bits(0b110101) == "AM3153_SN2_5V_6mA_Band1_0101.s2p"
    assert _filename_for_bits(0b101111) == "AM3153_SN2_5V_6mA_Band3_1111.s2p"


def test_get_response_loads_real_data():
    response = get_response(0b110000)
    assert len(response.freq_hz) == len(response.s21_db)
    assert len(response.freq_hz) > 100
    assert response.freq_hz.min() < 1e9  # covers well below the passband
    assert response.freq_hz.max() > 20e9  # and well above it
    # Band1's passband is ~6-12GHz per the datasheet; peak S21 should be
    # much higher (less negative) than deep out-of-band attenuation.
    assert response.s21_db.max() > -15.0


def test_bypass_response_is_near_zero_db_broadband():
    response = get_response(0x00)
    # Bypass path should stay close to 0dB (low loss) across most of its range.
    assert response.s21_db.max() > -5.0
