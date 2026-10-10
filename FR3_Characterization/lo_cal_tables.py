"""The unit's TX LO-null calibration (100 MHz grid, cold + hot), applied the way the GUI applies it: at the current LMX die
temperature, the bias is interpolated between the cold and hot values for the LO frequency (linearly in temperature, using
each table's own recorded LMX temperature at that LO), or extrapolated beyond them.

    from lo_cal_tables import CalTables
    t = CalTables()
    i_v, q_v = t.bias(lo_hz, lmx_temp_c)

Each temperature's table is assembled from several lo_cal_grid_scan.py runs: later runs override earlier ones at the same
LO, and an entry is used only if it was made at the LMX drive that lmx_drive.drive_for() prescribes for that LO (runs before
2026-10-09 have no lmx_power column: they were all at drive 0). So the 2026-10-08 drive-0 tables serve LO <= 15 GHz, and the
drive-rule re-runs serve LO > 15 GHz. Where only one temperature has a valid entry, that one is used (and `partial` says so).

LO frequencies must be on the 100 MHz grid (FR1 and FR3 are chosen as multiples of 100 MHz); anything else raises.
"""
from __future__ import annotations

import csv
import glob

from lmx_drive import drive_for

D = r"results\unit_005\2026-10-08"
D9 = r"results\unit_005\2026-10-09"
# Since 2026-10-09 the tables are the FULL-band re-runs at the drive rule only (user: re-run everything, reuse nothing).
# The 2026-10-08 drive-0 tables are no longer used. Until the cold re-run exists, every LO has only its hot value.
COLD = [rf"{D9}\lo_cal_grid_100MHz_*_full_cal_cold_drive_rule_table.csv"]
HOT = [rf"{D9}\lo_cal_grid_100MHz_*_full_cal_hot_drive_rule_table.csv"]
# Another unit (production tests): set FR3_CAL_COLD / FR3_CAL_HOT to that unit's table glob(s), ";"-separated; an empty
# value means "no table at that temperature". Unit #5's tables are then never used.
import os  # noqa: E402
if "FR3_CAL_COLD" in os.environ or "FR3_CAL_HOT" in os.environ:
    COLD = [x for x in os.environ.get("FR3_CAL_COLD", "").split(";") if x]
    HOT = [x for x in os.environ.get("FR3_CAL_HOT", "").split(";") if x]


def _load(patterns: list[str]) -> tuple[dict[int, tuple[float, float, float]], list[str]]:
    table, used = {}, []
    for pat in patterns:
        for path in sorted(glob.glob(pat)):                          # time-stamped names: oldest first
            used.append(path)
            for r in csv.DictReader(open(path, newline="")):
                lo_hz = float(r["lo_ghz"]) * 1e9
                if int(r.get("lmx_power") or 0) != drive_for(lo_hz):
                    continue                                          # made at another drive: not valid for this LO
                table[int(round(lo_hz / 1e8))] = (float(r["ref_i_v"]), float(r["ref_q_v"]), float(r["lmx_temp_c"]))
    return table, used


class CalTables:
    def __init__(self, cold: list[str] = COLD, hot: list[str] = HOT):
        self.cold, cold_used = _load(cold)
        self.hot, hot_used = _load(hot)
        self.cold_path, self.hot_path = " + ".join(cold_used), " + ".join(hot_used)
        self.partial = sorted(k / 10 for k in set(self.cold) ^ set(self.hot))   # LOs (GHz) with only one temperature

    def bias(self, lo_hz: float, temp_c: float) -> tuple[float, float]:
        k = round(lo_hz / 1e8)
        if abs(lo_hz - k * 1e8) > 1e3:
            raise ValueError(f"LO {lo_hz / 1e9:g} GHz is not on the 100 MHz calibration grid")
        c, h = self.cold.get(k), self.hot.get(k)
        if c is None and h is None:
            raise ValueError(f"no calibration at LO {lo_hz / 1e9:g} GHz for drive {drive_for(lo_hz)}")
        if c is None or h is None:
            return (c or h)[:2]
        (ic, qc, tc), (ih, qh, th) = c, h
        frac = 0.5 if abs(th - tc) < 0.5 else (temp_c - tc) / (th - tc)
        return ic + frac * (ih - ic), qc + frac * (qh - qc)
