"""Capture the S21 currently displayed by the FieldFox in NA (VNA) mode and
save it as a cable-loss file for correcting later sweeps.

    python capture_cable_s21.py --name fr3_cable [--host 192.168.137.61]

Reads whatever sweep is currently set up on the FieldFox - it changes NO sweep
setting, so it cannot invalidate a calibration. Takes three fresh sweeps to
check repeatability, saves the last one. Writes, without overwriting anything
(timestamped names):

    calibration/<name>_s21_<timestamp>.csv   freq_hz,s21_db,s21_phase_deg,s21_re,s21_im
    calibration/<name>_s21_<timestamp>.json  instrument, sweep settings, calibration state

Whether a user calibration was active is recorded in the metadata. The full
trace is read here because this measurement genuinely needs the whole span."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from fieldfox import FieldFox, FieldFoxError

CALIBRATION_DIR = Path(__file__).resolve().parent / "calibration"
N_SWEEPS = 3


def read_s21(ff: FieldFox) -> tuple[np.ndarray, np.ndarray]:
    """One fresh sweep -> (freq_hz, complex S21). Correction, if any, is
    already applied by the instrument."""
    # continuous sweep (never INIT:CONT OFF / INIT:IMM). NA-mode sweep-time query: CHECK it against the
    # FieldFox programming guide before the next run (this script was written for single sweeps).
    ff.wait_fresh_sweeps(sweep_time_query="SENS:SWE:TIME?")
    freq = np.array([float(v) for v in ff.query("SENS:FREQ:DATA?").split(",")])
    ri = np.array([float(v) for v in ff.query("CALC:DATA:SDAT?").split(",")])
    if ri.size != 2 * freq.size:
        raise FieldFoxError(f"got {ri.size} S-data values for {freq.size} frequency points")
    return freq, ri[0::2] + 1j * ri[1::2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="e.g. fr3_cable or fr1_cable")
    parser.add_argument("--host", default="192.168.137.61")
    args = parser.parse_args()

    with FieldFox(args.host) as ff:
        idn = ff.identify()
        if ff.query("INST:SEL?") != '"NA"':
            print("FieldFox is not in NA mode - aborting.")
            return 1
        if ff.query("CALC:PAR1:DEF?") != "S21":
            print("Trace 1 is not S21 - aborting.")
            return 1

        meta = {
            "instrument": idn,
            "cable": args.name,
            "captured": datetime.now().astimezone().isoformat(timespec="seconds"),
            "measurement": ff.query("CALC:PAR1:DEF?"),
            "start_hz": float(ff.query("SENS:FREQ:STAR?")),
            "stop_hz": float(ff.query("SENS:FREQ:STOP?")),
            "points": int(ff.query("SENS:SWE:POIN?")),
            "if_bandwidth_hz": float(ff.query("SENS:BWID?")),
            "source_power_dbm": float(ff.query("SOUR:POW?")),
            "averaging_count": int(ff.query("AVER:COUN?")),
            "correction_state": ff.query("CORR?"),
            "user_calibration_active": ff.query("CORR:USER:STAT?") in ("1", "ON"),
        }

        # (was INIT:CONT OFF: removed 2026-10-10, never sent to this FieldFox)
        try:
            sweeps = [read_s21(ff) for _ in range(N_SWEEPS)]
            ff.check("S21 capture")
        finally:
            ff.write("INIT:CONT ON")

    freq = sweeps[0][0]
    if any(not np.array_equal(f, freq) for f, _ in sweeps):
        raise FieldFoxError("frequency axis changed between sweeps")
    db = np.array([20 * np.log10(np.abs(z)) for _, z in sweeps])
    meta["repeatability_max_db"] = float(np.max(np.ptp(db, axis=0)))
    meta["sweeps_averaged_for_repeatability_check"] = N_SWEEPS

    z = sweeps[-1][1]
    s21_db = 20 * np.log10(np.abs(z))
    phase_deg = np.degrees(np.angle(z))

    CALIBRATION_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = CALIBRATION_DIR / f"{args.name}_s21_{stamp}"
    with open(base.with_suffix(".csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["freq_hz", "s21_db", "s21_phase_deg", "s21_re", "s21_im"])
        for row in zip(freq, s21_db, phase_deg, z.real, z.imag):
            w.writerow([f"{row[0]:.0f}", f"{row[1]:.5f}", f"{row[2]:.4f}",
                        f"{row[3]:.8f}", f"{row[4]:.8f}"])
    with open(base.with_suffix(".json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"Saved {base.with_suffix('.csv')}")
    print(f"      {base.with_suffix('.json')}")
    print(f"{meta['points']} points, {meta['start_hz']/1e9:g}-{meta['stop_hz']/1e9:g} GHz, "
          f"user calibration active: {meta['user_calibration_active']}")
    print(f"Repeatability across {N_SWEEPS} sweeps: max spread {meta['repeatability_max_db']:.4f} dB")
    print(f"S21: min {s21_db.min():.2f} dB, max {s21_db.max():.2f} dB")
    for g in (0.7e9, 1e9, 2e9, 3e9, 4e9, 6e9, 10e9, 15e9, 20e9, 26e9):
        if freq[0] <= g <= freq[-1]:  # never print an out-of-range (clamped) value
            print(f"  {g/1e9:5.1f} GHz: {np.interp(g, freq, s21_db):+.3f} dB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
