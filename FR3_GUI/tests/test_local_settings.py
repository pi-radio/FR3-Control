"""Tests for local_settings.py against a temp file, not the real one."""

from __future__ import annotations

from fr3_gui import local_settings


def test_load_returns_none_when_nothing_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(local_settings, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(local_settings, "TX_HELPER_FILE", tmp_path / "tx_helper_inputs.json")
    assert local_settings.load_tx_helper_inputs("FR3 1CH:2") is None


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(local_settings, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(local_settings, "TX_HELPER_FILE", tmp_path / "tx_helper_inputs.json")

    local_settings.save_tx_helper_inputs("FR3 1CH:2", 2.5, 12.0, 0.4)
    assert local_settings.load_tx_helper_inputs("FR3 1CH:2") == (2.5, 12.0, 0.4)


def test_different_tab_keys_dont_clobber_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(local_settings, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(local_settings, "TX_HELPER_FILE", tmp_path / "tx_helper_inputs.json")

    local_settings.save_tx_helper_inputs("FR3 1CH:2", 2.5, 12.0, 0.4)
    local_settings.save_tx_helper_inputs("FR3 1CH:3", 3.0, 15.0, 0.8)

    assert local_settings.load_tx_helper_inputs("FR3 1CH:2") == (2.5, 12.0, 0.4)
    assert local_settings.load_tx_helper_inputs("FR3 1CH:3") == (3.0, 15.0, 0.8)


def test_corrupt_file_is_treated_as_empty(tmp_path, monkeypatch):
    settings_file = tmp_path / "tx_helper_inputs.json"
    settings_file.write_text("not valid json{{{", encoding="utf-8")
    monkeypatch.setattr(local_settings, "SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(local_settings, "TX_HELPER_FILE", settings_file)

    assert local_settings.load_tx_helper_inputs("FR3 1CH:2") is None
