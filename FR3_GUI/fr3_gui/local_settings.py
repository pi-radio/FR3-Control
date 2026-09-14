"""Local, per-machine GUI settings - unrelated to a board's own firmware
persistence (EDATA). Currently just the Configuration Helper's FR1/FR3/
bandwidth inputs, remembered per physical unit (keyed by tab_key, e.g.
"FR3 1CH:2") so they survive a GUI restart on this machine. Never touches
hardware."""

from __future__ import annotations

import json
import logging
from typing import Optional

from .paths import app_data_dir

logger = logging.getLogger(__name__)

SETTINGS_DIR = app_data_dir() / "local_settings"
TX_HELPER_FILE = SETTINGS_DIR / "tx_helper_inputs.json"


def _load_all() -> dict:
    if not TX_HELPER_FILE.exists():
        return {}
    try:
        with open(TX_HELPER_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        logger.warning("Could not read %s - starting fresh", TX_HELPER_FILE, exc_info=True)
        return {}


def load_tx_helper_inputs(tab_key: str) -> Optional[tuple[float, float, float]]:
    """Returns (f_in_ghz, fr3_ghz, bw_ghz) last saved for this tab_key, or None."""
    entry = _load_all().get(tab_key)
    if not entry:
        return None
    try:
        return float(entry["f_in_ghz"]), float(entry["fr3_ghz"]), float(entry["bw_ghz"])
    except (KeyError, TypeError, ValueError):
        return None


def save_tx_helper_inputs(tab_key: str, f_in_ghz: float, fr3_ghz: float, bw_ghz: float) -> None:
    data = _load_all()
    data[tab_key] = {"f_in_ghz": f_in_ghz, "fr3_ghz": fr3_ghz, "bw_ghz": bw_ghz}
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(TX_HELPER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        logger.warning("Could not write %s", TX_HELPER_FILE, exc_info=True)
