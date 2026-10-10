"""Upload a unit's LO-null calibration (cold + hot, 100 MHz grid) into its flash (firmware 1.4.1 CAL commands), then read
every entry back and check it.

    python upload_lo_cal.py --unit 6 --cold <..._full_cal_cold_drive_rule_table.csv> --hot <..._full_cal_hot_drive_rule_table.csv>
                            [--date 20261010] [--dry-run]

Default tables: the newest results/unit_<n>/2026-10-*/lo_cal_grid_100MHz_*_full_cal_{cold,hot}_drive_rule_table.csv.

Steps: check the connected unit's serial == --unit (the commit stamps the board serial into the table) and its firmware
has the CAL commands; check each table has all 156 LOs (7.0-22.5 GHz) measured at the drive rule; CAL CLEAR; 312 x
CAL LO <k> <C|H> <I_V> <Q_V> <T>; CAL DATE; CAL STAGED? == 312; CAL COMMIT; then CAL LO? for every entry, compared within
the storage resolution (1/65536 V, 0.1 C); CAL INFO? / CAL TEMPS? / IQBIAS? printed. Nothing else on the unit is changed:
the CAL commands do not touch the RF settings or the persisted settings. --dry-run checks the tables only (no unit needed).
"""
from __future__ import annotations

import argparse
import csv
import glob
import sys
from datetime import date

from board import Board, OPERATING_TIMEOUT_S, find_board_ports
from lmx_drive import drive_for
from results_layout import unit_dir

N_POINTS = 156
F_START_GHZ, STEP_GHZ = 7.0, 0.1
V_TOL = 0.5 / 65536 + 2e-6          # storage rounding + the 6-decimal print
T_TOL = 0.06


def load_table(path: str) -> dict[int, tuple[float, float, float]]:
    out = {}
    for r in csv.DictReader(open(path, newline="")):
        lo = float(r["lo_ghz"])
        k = round((lo - F_START_GHZ) / STEP_GHZ)
        if abs(F_START_GHZ + k * STEP_GHZ - lo) > 1e-6 or not 0 <= k < N_POINTS:
            raise SystemExit(f"{path}: LO {lo} GHz is not on the 7.0-22.5 GHz / 100 MHz grid")
        if int(r.get("lmx_power") or -1) != drive_for(lo * 1e9):
            raise SystemExit(f"{path}: LO {lo} GHz was measured at drive {r.get('lmx_power')}, not the drive rule's {drive_for(lo * 1e9)}")
        out[k] = (float(r["ref_i_v"]), float(r["ref_q_v"]), float(r["lmx_temp_c"]))
    missing = sorted(set(range(N_POINTS)) - set(out))
    if missing:
        raise SystemExit(f"{path}: {len(missing)} LO frequencies missing, e.g. index {missing[:5]}")
    return out


def newest(unit: int, which: str) -> str:
    files = sorted(glob.glob(str(unit_dir(unit) / "2026-10-*" / f"lo_cal_grid_100MHz_*_full_cal_{which}_drive_rule_table.csv")))
    if not files:
        raise SystemExit(f"no {which} calibration table found for unit {unit}: pass --{which}")
    return files[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, required=True)
    ap.add_argument("--cold", default="")
    ap.add_argument("--hot", default="")
    ap.add_argument("--date", type=int, default=int(date.today().strftime("%Y%m%d")))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cold_path = args.cold or newest(args.unit, "cold")
    hot_path = args.hot or newest(args.unit, "hot")
    tables = {"C": load_table(cold_path), "H": load_table(hot_path)}
    print(f"cold: {cold_path}\nhot:  {hot_path}")
    for w, t in tables.items():
        temps = [v[2] for v in t.values()]
        print(f"  {w}: {len(t)} entries, LMX {min(temps):.1f}-{max(temps):.1f} C")
    if args.dry_run:
        print("dry run: tables OK, nothing sent")
        return 0

    ports = find_board_ports()
    if len(ports) != 1:
        raise SystemExit(f"expected exactly one unit, found {ports or 'none'}")
    b = Board(ports[0], timeout=OPERATING_TIMEOUT_S)
    try:
        idn = b.get_idn()
        serial = b.get_board_serial()
        print(f"unit: {idn}, serial {serial}")
        if serial != args.unit:
            raise SystemExit(f"connected unit has serial {serial}, expected {args.unit} -- nothing sent")
        if b._query("CAL STAGED?").startswith("ERR"):
            raise SystemExit("this firmware has no CAL commands (needs 1.4.1) -- nothing sent")

        if not b.cal_clear():
            raise SystemExit("CAL CLEAR failed")
        for w, t in tables.items():
            for k in range(N_POINTS):
                i_v, q_v, temp = t[k]
                if not b.cal_set_entry(k, w == "H", i_v, q_v, temp):
                    raise SystemExit(f"CAL LO {k} {w} rejected ({i_v}, {q_v}, {temp}) -- not committed")
        if not b.cal_set_date(args.date):
            raise SystemExit("CAL DATE failed -- not committed")
        staged = b.cal_staged_count()
        print(f"staged: {staged}")
        if staged != 2 * N_POINTS:
            raise SystemExit("not all entries staged -- not committed")
        result = b.cal_commit()
        print(f"CAL COMMIT -> {result}")
        if result != "OK":
            return 1

        bad = []
        for w, t in tables.items():
            for k in range(N_POINTS):
                got = b.cal_get_entry(k, w == "H")
                i_v, q_v, temp = t[k]
                if got is None or abs(got[0] - i_v) > V_TOL or abs(got[1] - q_v) > V_TOL or abs(got[2] - temp) > T_TOL:
                    bad.append((k, w, (i_v, q_v, temp), got))
        print(f"read-back: {2 * N_POINTS - len(bad)} of {2 * N_POINTS} entries match")
        for k, w, want, got in bad[:10]:
            print(f"  MISMATCH LO {F_START_GHZ + k * STEP_GHZ:.1f} GHz {w}: wrote {want}, read {got}")
        print(f"CAL INFO?  -> {b._query('CAL INFO?')}")
        print(f"CAL TEMPS? -> {b._query('CAL TEMPS?')}")
        print(f"IQBIAS?    -> {b._query('IQBIAS?')}")
        return 1 if bad else 0
    finally:
        b.close()


if __name__ == "__main__":
    sys.exit(main())
