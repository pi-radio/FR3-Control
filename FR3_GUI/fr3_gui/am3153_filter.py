"""Loads AM3153 filter S-parameters and maps a filter control byte (as used
by RFFilter_SetTx/SetRx in firmware - VA=0x20, VB=0x10, V3=0x08, V2=0x04,
V1=0x02, V0=0x01) to its measured response.

Mapping confirmed against the AM3153 datasheet's state table:
  VA=0,VB=0            -> Bypass (V3-V0 don't care - matches "0x0X")
  VA=1,VB=1            -> Band1 (~6-12GHz)
  VA=0,VB=1            -> Band2 (~12-18GHz)
  VA=1,VB=0            -> Band3 (~18-26GHz)
V3V2V1V0 is the 4-bit binary sub-state index, matching each file's
"_0000".."_1111" suffix directly.

All 49 underlying files are parsed once at import time (49 files, not the
full 64 lookup table - the 16 "bypass" byte values all share one file).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "am3153_sparams"

_BAND_BY_VA_VB = {(1, 1): 1, (0, 1): 2, (1, 0): 3}

# (name, upper-nibble value), in UI display order (not numeric nibble
# order) - see the mapping table above.
FILTER_BANKS = (("Bypass", 0x0), ("Bank 1", 0x3), ("Bank 2", 0x1), ("Bank 3", 0x2))


@dataclass(frozen=True)
class FilterResponse:
    freq_hz: np.ndarray
    s21_db: np.ndarray


def _filename_for_bits(bits: int) -> str:
    va = (bits >> 5) & 1
    vb = (bits >> 4) & 1
    if va == 0 and vb == 0:
        return "AM3153_SN2_5V_6mA_Bypass.s2p"
    band = _BAND_BY_VA_VB[(va, vb)]
    suffix = format(bits & 0x0F, "04b")
    return f"AM3153_SN2_5V_6mA_Band{band}_{suffix}.s2p"


def _parse_s2p(path: Path) -> FilterResponse:
    """Standard Touchstone 2-port file, confirmed format from the data
    itself: "# Hz S dB R 50" - freq in Hz, dB+angle pairs for S11/S21/S12/S22
    in that order. Only S21 (columns 3) is needed here."""
    freqs = []
    s21 = []
    with open(path, encoding="ascii") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("!") or line.startswith("#"):
                continue
            parts = line.split()
            freqs.append(float(parts[0]))
            s21.append(float(parts[3]))
    return FilterResponse(freq_hz=np.array(freqs), s21_db=np.array(s21))


def _load_all() -> dict[int, FilterResponse]:
    file_cache: dict[str, FilterResponse] = {}
    by_bits: dict[int, FilterResponse] = {}
    for bits in range(64):
        filename = _filename_for_bits(bits)
        if filename not in file_cache:
            file_cache[filename] = _parse_s2p(DATA_DIR / filename)
        by_bits[bits] = file_cache[filename]
    return by_bits


_RESPONSES = _load_all()


def get_response(bits: int) -> FilterResponse:
    """bits: the low 6 bits of a TX/RX filter control byte (0-63)."""
    return _RESPONSES[bits & 0x3F]
