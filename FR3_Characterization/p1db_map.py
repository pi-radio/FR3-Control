"""TX output compression (P1dB / P3dB / max output power) versus frequency, desired sideband only.

    python p1db_map.py --campaign p1db_map_20260923 [--lo-start-ghz 7] [--lo-stop-ghz 22.5] [--lo-step-ghz 0.5]
                       [--if-ghz 2] [--max-minutes 8]

For every LO and for both IQ states (THRU = upper sideband desired, SWAP = lower), one CW power sweep of the IF tone
(the same power_sweep as conversion_gain_small_case.py: coarse 2 dB steps from -58 dBm, 0.5 dB steps once compression
sets in, stop at 3.5 dB compression / the +23 dBm analyzer guard / 0 dBm source). TX filter in bypass, I/Q bias from the
LO-null table, analyzer attenuation held fixed at 35 dB, span 1 MHz. Data are cable-corrected to the board connectors.

Resumable: an LO whose file already exists is skipped; --max-minutes stops cleanly between LOs (one tool call is
limited to 10 minutes). Results: results/unit_<serial>/<campaign>/p1db_<GHz>.csv (one row per drive step, both IQ
states), summary.csv (one row per LO and IQ state) and campaign.json. The FieldFox source is always switched off and
read back; the board configuration is restored with persistence back ON."""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import sys
import time
from datetime import datetime

import numpy as np

from board import MeasurementSession
from cables import CableLoss
from compression import compression_point
from conversion_gain_small_case import (DEFAULT_FIXED_ATTENUATION_DB, DEFAULT_START_DBM, REF_FIXED_DBM,
                                        configure_board, must, power_sweep)
from fieldfox import SETTLE_S, FieldFox
from results_layout import unit_dir

SUMMARY_FIELDS = ["lo_hz", "iq", "rf_hz", "small_signal_gain_db", "p1db_in_dbm", "p1db_out_dbm", "p3db_in_dbm",
                  "p3db_out_dbm", "max_out_dbm", "max_gain_expansion_db", "stop_reason"]


def summarize(rows: list[dict], results: dict) -> dict:
    used = [r for r in rows if r["valid"]]
    out = {"small_signal_gain_db": results.get("small_signal_gain_db"), "stop_reason": results["stop_reason"]}
    for drop in (1, 3):
        cp = results.get(f"p{drop}db")
        out[f"p{drop}db_in_dbm"] = "" if not cp else cp["input_dbm"]
        out[f"p{drop}db_out_dbm"] = "" if not cp else cp["output_dbm"]
    out["max_out_dbm"] = round(max(r["out_at_dut_dbm"] for r in used), 2) if used else ""
    g0 = results.get("small_signal_gain_db")
    out["max_gain_expansion_db"] = round(max(r["corrected_gain_db"] for r in used) - g0, 2) if used and g0 is not None else ""
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--lo-start-ghz", type=float, default=7.0)
    parser.add_argument("--lo-stop-ghz", type=float, default=22.5)
    parser.add_argument("--lo-step-ghz", type=float, default=0.5)
    parser.add_argument("--if-ghz", type=float, default=2.0)
    parser.add_argument("--attenuation-db", type=float, default=DEFAULT_FIXED_ATTENUATION_DB)
    parser.add_argument("--start-dbm", type=float, default=DEFAULT_START_DBM,
                        help="first drive level; raise it where the output at -58 dBm would be near the analyzer floor")
    parser.add_argument("--max-minutes", type=float, default=8.0)
    parser.add_argument("--host", default="192.168.137.61")
    parser.add_argument("--port", default=None)
    args = parser.parse_args()

    f_if = args.if_ghz * 1e9
    n = int(round((args.lo_stop_ghz - args.lo_start_ghz) / args.lo_step_ghz)) + 1
    los = [int(round((args.lo_start_ghz + i * args.lo_step_ghz) * 1e9)) for i in range(n)]
    cable_if, cable_rf = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    cable_if.s21_db(f_if)
    for lo in los:
        cable_rf.s21_db(lo + f_if)
        cable_rf.s21_db(lo - f_if)          # raise now, not mid-campaign, if outside the cable data

    session = MeasurementSession(port=args.port)
    with session as board, FieldFox(args.host) as ff:
        serial = board.get_board_serial()
        outdir = unit_dir(serial) / args.campaign
        outdir.mkdir(parents=True, exist_ok=True)
        settings = {"if_hz": f_if, "attenuation_db": args.attenuation_db, "lo_step_hz": int(round(args.lo_step_ghz * 1e9))}
        cj = outdir / "campaign.json"
        if cj.exists():
            old = json.loads(cj.read_text())["settings"]
            if old != settings:
                raise RuntimeError(f"campaign {args.campaign} exists with different settings {old}; use a new name")
        else:
            cj.write_text(json.dumps({"settings": settings, "unit_serial": serial, "tx_filter": "bypass",
                                      "fr1_cable_file": cable_if.path.name, "fr3_cable_file": cable_rf.path.name,
                                      "started": datetime.now().astimezone().isoformat(timespec="seconds")}, indent=2))
        todo = [lo for lo in los if not (outdir / f"p1db_{lo / 1e9:06.2f}GHz.csv").exists()]
        print(f"Unit #{serial}, campaign {args.campaign}: {len(los)} LOs in range, {len(todo)} to do. {outdir}")
        t0 = time.monotonic()
        try:
            ff.setup_spectrum_analyzer(ref_level_dbm=REF_FIXED_DBM)
            ff.source_enable(False)
            ff.set_attenuation(args.attenuation_db)
            for lo in todo:
                if (time.monotonic() - t0) / 60 > args.max_minutes:
                    print(f"Time budget of {args.max_minutes:g} min used; stopping cleanly before LO {lo / 1e9:g} GHz.")
                    break
                configure_board(board, float(lo), "upper")
                all_rows, summ = [], []
                for iq, swap, rf in (("THRU", False, lo + f_if), ("SWAP", True, lo - f_if)):
                    must(board.set_iq_swap(swap), f"SET IQ {iq}")
                    ff.source_configure(f_if, args.start_dbm)
                    ff.source_enable(True)
                    time.sleep(SETTLE_S)
                    with contextlib.redirect_stdout(io.StringIO()):
                        rows, results = power_sweep(ff, board, cable_if, cable_rf, f_if, float(rf),
                                                    start_dbm=args.start_dbm)
                    ff.source_enable(False)
                    for r in rows:
                        all_rows.append({"iq": iq, "rf_hz": rf, **r})
                    s = {"lo_hz": lo, "iq": iq, "rf_hz": rf, **summarize(rows, results)}
                    summ.append(s)
                    p1 = s["p1db_out_dbm"]
                    print(f"  LO {lo / 1e9:6.2f} GHz {iq}: RF {rf / 1e9:6.2f}  G0 "
                          + (f"{s['small_signal_gain_db']:+6.2f} dB" if s["small_signal_gain_db"] is not None else "   n/a   ")
                          + f"  P1dB out {p1 if p1 != '' else '  -  '}  max out {s['max_out_dbm']}  ({s['stop_reason']})")
                with open(outdir / f"p1db_{lo / 1e9:06.2f}GHz.csv", "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=list(all_rows[0]))
                    w.writeheader()
                    w.writerows(all_rows)
                new = not (outdir / "summary.csv").exists()
                with open(outdir / "summary.csv", "a", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
                    if new:
                        w.writeheader()
                    w.writerows(summ)
                if ff.errors():
                    print("  FieldFox reported errors:", ff.errors())
        finally:
            ff.source_enable(False)
            ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            off = not ff.source_state()
            print("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON!",
                  file=sys.stdout if off else sys.stderr)
    print(f"Done in {(time.monotonic() - t0) / 60:.1f} min. Board configuration restored, flash persistence back ON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
