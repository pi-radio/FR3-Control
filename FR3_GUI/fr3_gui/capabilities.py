"""Client-side capability lookup table, keyed on (board name, revision)
from *IDN?. Mirrors board_config.h's BOARD_HAS_* flags - a hardware
revision's capabilities never change after shipping, so this stays a
static table rather than a firmware-reported list. Add an entry per new
revision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BoardCapabilities:
    has_lmx2820: bool = False
    has_ltc2668: bool = False
    has_clock_switch: bool = False
    has_lo_switch: bool = False
    has_iq_swap: bool = False
    has_rf_filters: bool = False


_TABLE: dict[tuple[str, str], BoardCapabilities] = {
    ("FR3 1CH", "1.1"): BoardCapabilities(
        has_lmx2820=True,
        has_ltc2668=True,
        has_clock_switch=True,
        has_lo_switch=True,
        has_iq_swap=True,
        has_rf_filters=False,
    ),
    ("FR3 1CH", "1.4"): BoardCapabilities(
        has_lmx2820=True,
        has_ltc2668=True,
        has_clock_switch=True,
        has_lo_switch=True,
        has_iq_swap=True,
        has_rf_filters=True,
    ),
    ("OctoLO", "1.4"): BoardCapabilities(
        has_lmx2820=True,
        has_ltc2668=False,
        has_clock_switch=False,
        has_lo_switch=False,
        has_iq_swap=False,
        has_rf_filters=False,
    ),
}


def get_capabilities(board_name: str, revision: str) -> Optional[BoardCapabilities]:
    """None for an unrecognized (board, revision) - not one of our devices."""
    return _TABLE.get((board_name, revision))
