"""LO and 2xLO leaking out of the "RX-side FR3 RF In" connector, unit in normal use (datasheet Section 10.2).

2026-10-09 hot RX re-run (default, no --bias): LOs on the 100 MHz grid (--lo-start/--lo-stop/--step-mhz, default 7.0-22.5 GHz,
the TX calibration's grid), LMX drive by the drive rule (lmx_drive.py), and the TX side in normal use from the unit's stored
cold/hot calibration (rx_tx_side.tx_normal_state for FR3 = LO + 1 GHz: I/Q bias interpolated to the LMX temperature, IQ THRU,
optimal TX filter); RX filter optimal for the same FR3. The offset check moves I_V off that stored bias.

    python rx_port_leakage.py --out-dir results/unit_005/<date> [--note ...] [--setup "..."]
The original 2026-10-07 mode (fixed drive, bias and TX filter from Type 4 rows) is kept:
    python rx_port_leakage.py --bias <type 4 csv> [<type 4 csv> ...] --lmx-power 0 --out-dir results/unit_005/<date>

The TX-side state at each LO comes from Type 4 runs made at LMX drive 0 with the TX output on the analyzer (the LO
grid, TX filter and LO-null bias of every row of the given CSVs, e.g. Sweep A plus "Pass 1"). For every LO: tune the
LMX (drive 0), IQ THRU, TX filter and I_V/Q_V from that row, RX filter = the optimal filter for FR3 = LO + 1 GHz (RX
low-side LO, as TX upper sideband forces), then read LO and 2xLO at "RX-side FR3 RF In" (FR3 cable corrected): 1 MHz
span, RBW 10 kHz, 0 dB attenuation, ref -20 dBm, 4 power averages, marker peak, floor = trace median (spur_campaign).
2xLO is read only up to 26.5 GHz.
At a few LOs (--offset-check-los) the reading is repeated with I_V moved --offset-mv off the TX null, to show whether the
TX-side null matters for the RX-port leakage (it raises the TX LO leakage by tens of dB). Hookup: "RX-side FR3 RF In" -> FR3 cable -> FieldFox; "TX-side FR3 RF Out" 50-ohm
terminated; FieldFox source OFF. Rows saved as measured: rx_port_leakage_<stamp>[_note].csv + .json. Board restored.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from lmx_drive import set_drive_for
from lo_cal_tables import CalTables
from rx_nf_campaign import optimal_rx_filter
from rx_tx_side import tx_normal_state
from spur_campaign import ATT_QUIET_DB, FF_HOST, FF_MAX_HZ, MARK_SPAN, REF_QUIET_DBM, ff_setup, marker, restore_ff


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bias", nargs="+", default=None, help="(2026-10-07 mode) Type 4 CSVs giving lo_ghz, tx_filter, i_v, q_v per LO")
    ap.add_argument("--lmx-power", default="auto", help="auto = drive rule (default); or a fixed level")
    ap.add_argument("--lo-start", type=float, default=7.0)
    ap.add_argument("--lo-stop", type=float, default=22.5)
    ap.add_argument("--step-mhz", type=float, default=100.0)
    ap.add_argument("--los", default="", help="explicit comma-separated LO list in GHz (overrides start/stop/step)")
    ap.add_argument("--rx-offset-ghz", type=float, default=1.0, help="RX filter chosen for FR3 = LO + this")
    ap.add_argument("--max-temp-c", type=float, default=92.0)
    ap.add_argument("--offset-check-los", default="8,12,16,20",
                    help="LOs (GHz, nearest grid point) where the reading is repeated with the TX bias deliberately off the null")
    ap.add_argument("--offset-mv", type=float, default=5.0, help="I_V offset for that check (mV)")
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--setup", default="")
    args = ap.parse_args()
    pts = {}
    tables = None
    if args.bias:
        for f in args.bias:
            for r in csv.DictReader(open(f, newline="")):
                pts[round(float(r["lo_ghz"]), 6)] = r
    else:
        tables = CalTables()
        if args.los:
            pts = {round(float(x), 6): None for x in args.los.split(",") if x}
        else:
            n = int(round((args.lo_stop - args.lo_start) * 1000 / args.step_mhz)) + 1
            pts = {round(args.lo_start + k * args.step_mhz / 1000, 6): None for k in range(n)}
    los = sorted(pts)
    check = {min(los, key=lambda x: abs(x - float(c))) for c in args.offset_check_los.split(",") if c}
    fr3c = CableLoss("fr3_cable")
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=MARK_SPAN) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(args.out_dir)
        out = out_dir / f"rx_port_leakage_{stamp}{('_' + args.note) if args.note else ''}.csv"
        json.dump({"script": "rx_port_leakage.py", "started": datetime.now().isoformat(timespec="seconds"), "unit_serial": serial,
                   "lmx_power": args.lmx_power,
                   "bias_from": [Path(f).name for f in args.bias] if args.bias else f"stored cal tables: {tables.cold_path} / {tables.hot_path}",
                   "lo_ghz": los, "rx_filter": f"optimal for FR3 = LO + {args.rx_offset_ghz:g} GHz", "iq": "THRU",
                   "readings": "LO and 2LO at RX-side FR3 RF In, FR3 cable corrected; 1 MHz span, RBW 10 kHz, 0 dB att, "
                               "ref -20 dBm, 4 power averages, marker peak; floor = trace median", "setup": args.setup},
                  open(out.with_suffix(".json"), "w"), indent=2)
        orig = None
        try:
            orig = ff_setup(ff, ATT_QUIET_DB, REF_QUIET_DBM)
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            if args.lmx_power != "auto":
                must(board.set_lmx_power(int(args.lmx_power)), f"LMX PWR {args.lmx_power}")
            must(board.set_iq_swap(False), "SET IQ THRU")
            print(f"{'LO':>7} {'TXf':>5} {'RXf':>5} | {'LO dBm':>8} {'floor':>7} | {'2LO dBm':>8} {'floor':>7} | LMX", flush=True)
            for lo_ghz in los:
                lo = lo_ghz * 1e9
                fr3 = lo + args.rx_offset_ghz * 1e9
                drive = set_drive_for(board, lo) if args.lmx_power == "auto" else int(args.lmx_power)
                rx_bits = optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})
                tune_and_lock(board, lo)
                if tables is not None:                                  # stored calibration, as the unit runs
                    st = tx_normal_state(board, tables, fr3, lo)
                    r = {"i_v": st["tx_i_v"], "q_v": st["tx_q_v"]}
                    tx_bits = int(st["tx_filter_bits"], 16)
                else:
                    r = pts[lo_ghz]
                    tx_bits = int(r["tx_filter"], 16)
                    must(board.set_tx_filter(tx_bits), "SET TXFILTER")
                    must(board.set_i_v(float(r["i_v"])), "SET I_V")
                    must(board.set_q_v(float(r["q_v"])), "SET Q_V")
                must(board.set_rx_filter(rx_bits), "SET RXFILTER")
                time.sleep(SETTLE_S)
                row = {"lo_ghz": lo_ghz, "two_lo_ghz": 2 * lo_ghz, "tx_filter": f"0x{tx_bits:02X}", "rx_filter": f"0x{rx_bits:02X}",
                       "i_v": r["i_v"], "q_v": r["q_v"], "lmx_power": drive}
                for name, f in (("lo", lo), ("two_lo", 2 * lo)):
                    if f + MARK_SPAN / 2 > FF_MAX_HZ:
                        row[f"{name}_dbm"] = row[f"{name}_floor_dbm"] = ""
                        continue
                    fx, p, floor = marker(ff, f)
                    corr = -fr3c.s21_db(fx)
                    row[f"{name}_dbm"] = round(p + corr, 2)
                    row[f"{name}_floor_dbm"] = round(floor + corr, 2)
                row["lo_dbm_tx_offset"] = row["two_lo_dbm_tx_offset"] = ""
                if lo_ghz in check:                                    # sensitivity to the TX null: I_V off by offset_mv
                    must(board.set_i_v(float(r["i_v"]) + args.offset_mv / 1000), "SET I_V (offset)")
                    time.sleep(SETTLE_S)
                    for name, f in (("lo", lo), ("two_lo", 2 * lo)):
                        if f + MARK_SPAN / 2 <= FF_MAX_HZ:
                            fx, p, _ = marker(ff, f)
                            row[f"{name}_dbm_tx_offset"] = round(p - fr3c.s21_db(fx), 2)
                    must(board.set_i_v(float(r["i_v"])), "SET I_V")
                    print(f"        TX bias off the null by {args.offset_mv:g} mV: LO {row['lo_dbm_tx_offset']} dBm, "
                          f"2LO {row['two_lo_dbm_tx_offset']} dBm", flush=True)
                t = board.get_lmx_temperature_c()
                row["lmx_temp_c"] = round(t, 1)
                new = not out.exists()
                with open(out, "a", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(row))
                    if new:
                        w.writeheader()
                    w.writerow(row)
                print(f"{lo_ghz:7.3f} {row['tx_filter']:>5} {row['rx_filter']:>5} | {row['lo_dbm']:>8} {row['lo_floor_dbm']:>7} | "
                      f"{row['two_lo_dbm']:>8} {row['two_lo_floor_dbm']:>7} | {t:.1f} C", flush=True)
                if t > args.max_temp_c:
                    raise RuntimeError(f"LMX at {t:.1f} C > {args.max_temp_c} C: stopping")
        finally:
            ff.source_enable(False)
            off = restore_ff(ff, orig)
            print(f"Saved {out}\n" + ("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
