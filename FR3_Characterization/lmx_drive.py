"""The LMX2820 output drive level to use at each LO frequency (user decision, 2026-10-09):

    LO <= 13 GHz       drive 0
    13 < LO < 20 GHz   drive 2
    LO >= 20 GHz       drive 4      (never 7)

At drive 0 the mixer is starved of LO at the top of the range (the LVA273 LO drivers roll off with frequency): drive 4 beat
drive 0 by ~1.4 / 2.5 / 5 dB of conversion gain at LO 21 / 21.5 / 22 GHz, and drive 7 added <= 0.1 dB over drive 4
(results/unit_005/2026-10-09/tx_gain_vs_lmx_drive_20261009_001436.csv). Threshold moved from 15 to 13 GHz on 2026-10-09 (user):
at LO 14 GHz drive 4 gave ~2.8 dB higher input P1dB than drive 0 (compression_point_drives_20261009_013529 / _013019).
Below 13 GHz drive 0 avoids the LO-chain overdrive
and the 2xLO seen at higher drives. Every measurement script uses this one function, and the firmware/GUI should apply the
same rule.
"""
from __future__ import annotations


def drive_for(lo_hz: float) -> int:
    lo_ghz = lo_hz / 1e9
    if lo_ghz <= 13.0 + 1e-9:
        return 0
    if lo_ghz < 20.0 - 1e-9:
        return 2
    return 4


def set_drive_for(board, lo_hz: float) -> int:
    """Set the LMX drive for this LO (only when it changes); returns the drive."""
    d = drive_for(lo_hz)
    if getattr(board, "_fr3_lmx_drive", None) != d:
        if not board.set_lmx_power(d):
            raise RuntimeError(f"board rejected: LMX PWR {d}")
        board._fr3_lmx_drive = d
    return d
