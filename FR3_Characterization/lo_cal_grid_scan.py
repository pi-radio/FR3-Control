"""One-null-per-LO TX LO calibration scan (user spec, 2026-10-07).

    python lo_cal_grid_scan.py --step-mhz 100 --out-dir results/unit_005/<date> [--note ...] [--setup "..."]

For every LO from --lo-start to --lo-stop in --step-mhz steps (LMX drive 0, IQ THRU, FieldFox source OFF):
  1. reference state = the filter state with the least model loss at the LO, among the states usable at that LO
     (every optimal filter of the FR1 0.7-4.0 GHz x 100 MHz grid, both sidebands, FR3 6-24 GHz: states_at);
  2. null the LO with the reference engaged (lo_null.Nuller, warm-started from the previous LO's null);
  3. apply that reference bias to every usable state and read the LO leakage at "TX-side FR3 RF Out"
     (1 MHz span, RBW 10 kHz, 30 dB att, no averaging, peak search; FR3 cable corrected).
Files (appended as measured; a restart with the same --resume file skips finished LOs):
  <base>_table.csv    one row per LO: LO, reference state, reference bias (the calibration table), null level, LMX temp,
                      range across all states, floor = median over the "blocking" states (model loss >= 40 dB at the LO)
  <base>_states.csv   one row per (LO, state) reading
With --zero-bias (the uncalibrated reference): no search, I_V = Q_V = 0 V at every LO, every usable state read;
files lo_uncal_grid_* (same columns; the "ref_*" columns are the 0 V setting, and lo_dbm_ref_bias is the 0 V reading).
Board restored on exit; source read back OFF.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

import lo_null
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from lo_null import Nuller
from lmx_drive import set_drive_for
from rx_nf_campaign import get_response
from spur_campaign import FF_HOST, restore_ff
from tx_2lo_vs_filter_state import reading_setup
from tx_lo_products import read
from tx_null_filter_state_test import BAND_NAME, states_at

BLOCKING_DB = 40.0


def model_s21(bits: int, f_hz: float) -> float:
    r = get_response(bits)
    return float(np.interp(f_hz, r.freq_hz, r.s21_db))


def append(path: Path, row: dict) -> None:
    new = not path.exists()
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-start", type=float, default=7.0)
    ap.add_argument("--lo-stop", type=float, default=22.5)
    ap.add_argument("--step-mhz", type=float, default=100.0)
    ap.add_argument("--lmx-power", default="auto", help="auto (default since 2026-10-09) = lmx_drive.drive_for(LO): 0 / 2 / 4; or a fixed level")
    ap.add_argument("--start", default="0.022,0.059", help="warm-start bias for the first LO")
    ap.add_argument("--max-temp-c", type=float, default=92.0)
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--setup", default="")
    ap.add_argument("--resume", default="", help="an existing <base>_table.csv to continue")
    ap.add_argument("--null-span-hz", type=float, default=None,
                    help="analyzer span for the null search (default lo_null.NULL_SPAN_HZ, 20 kHz); wider tolerates LO drift")
    ap.add_argument("--los", default="", help="explicit comma-separated LO list in GHz (overrides start/stop/step)")
    ap.add_argument("--read-2lo", action="store_true",
                    help="also read the 2xLO in every state (datasheet 10.1; only where 2xLO <= 26.5 GHz); column two_lo_dbm")
    ap.add_argument("--zero-bias", action="store_true",
                    help="uncalibrated reference: no null search; I_V = Q_V = 0 V for every state (files lo_uncal_grid_*)")
    ap.add_argument("--also-swap", action="store_true",
                    help="also read every state with the IQ switch in SWAP (same bias), right after its THRU reading; "
                         "column lo_dbm_swap. The null search itself is always done in THRU")
    args = ap.parse_args()
    n = int(round((args.lo_stop - args.lo_start) * 1000 / args.step_mhz)) + 1
    los = [round(args.lo_start + k * args.step_mhz / 1000, 6) for k in range(n)]
    if args.los:
        los = [round(float(x), 6) for x in args.los.split(",")]
        n = len(los)
    if args.null_span_hz:
        lo_null.NULL_SPAN_HZ = args.null_span_hz          # read by Nuller.configure_analyzer and by the set_span below
    fr3c = CableLoss("fr3_cable")
    start = tuple(float(v) for v in args.start.split(","))
    if args.resume:
        table = Path(args.resume)
        base = Path(str(table)[: -len("_table.csv")])
        done = {round(float(r["lo_ghz"]), 6): r for r in csv.DictReader(open(table, newline=""))}
        if done:
            last = done[max(done)]
            start = (float(last["ref_i_v"]), float(last["ref_q_v"]))
        los = [x for x in los if x not in done]
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        kind = "lo_uncal_grid" if args.zero_bias else "lo_cal_grid"
        base = Path(args.out_dir) / f"{kind}_{int(args.step_mhz)}MHz_{stamp}{('_' + args.note) if args.note else ''}"
        json.dump({"script": "lo_cal_grid_scan.py", "started": datetime.now().isoformat(timespec="seconds"),
                   "lo_start_ghz": args.lo_start, "lo_stop_ghz": args.lo_stop, "step_mhz": args.step_mhz, "n_los": n,
                   "lmx_power": args.lmx_power, "blocking_db": BLOCKING_DB, "zero_bias": args.zero_bias,
                   "null_span_hz": lo_null.NULL_SPAN_HZ, "also_swap": args.also_swap, "setup": args.setup}, open(f"{base}.json", "w"), indent=2)
    table, states_csv = Path(f"{base}_table.csv"), Path(f"{base}_states.csv")
    two_lo: dict[float, list[float]] = {}
    search_dir = Path(f"{base}_null_searches")
    print(f"{len(los)} LOs to do -> {table}", flush=True)
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        orig = None
        try:
            ff.write("*CLS")
            ff.select_mode("SA")
            orig = int(float(ff.query("SENS:SWE:POIN?")))
            ff.source_enable(False)
            for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF"):
                ff.write(c)
            ff._saved_attenuation = (ff.query("SENS:POW:ATT:AUTO?") in ("1", "ON"), ff.attenuation_db)
            ff.write("CALC:MARK1:STAT NORM")
            ff.write("INIT:CONT ON")
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            if args.lmx_power != "auto":
                must(board.set_lmx_power(int(args.lmx_power)), f"LMX PWR {args.lmx_power}")
            must(board.set_iq_swap(False), "SET IQ THRU")
            for lo_ghz in los:
                lo = lo_ghz * 1e9
                t0 = time.time()
                states = states_at(lo_ghz)
                loss = {b: model_s21(b, lo) for b in states}
                ref = max(states, key=lambda b: loss[b])
                drive = set_drive_for(board, lo) if args.lmx_power == "auto" else int(args.lmx_power)
                tune_and_lock(board, lo)
                if args.zero_bias:
                    res = type("Zero", (), {"i_v": 0.0, "q_v": 0.0, "level_dbm": float("nan")})()
                else:
                    must(board.set_tx_filter(ref), "SET TXFILTER")
                    time.sleep(SETTLE_S)
                    ff.set_span(lo_null.NULL_SPAN_HZ)
                    search_dir.mkdir(exist_ok=True)
                    nul = Nuller(ff, board, lo, fr3c, search_dir / f"lo_{lo_ghz:07.3f}GHz_0x{ref:02X}.csv")
                    try:
                        res = nul.run(start)
                    finally:
                        nul.close()
                reading_setup(ff)
                must(board.set_i_v(res.i_v), "SET I_V")
                must(board.set_q_v(res.q_v), "SET Q_V")
                levels = {}
                for b in states:
                    must(board.set_tx_filter(b), "SET TXFILTER")
                    time.sleep(SETTLE_S)
                    f, p = read(ff, lo)
                    levels[b] = p - fr3c.s21_db(f)
                    two = ""
                    if args.read_2lo and 2 * lo <= 26.5e9 + 1:
                        f2, p2 = read(ff, 2 * lo)
                        two = round(p2 - fr3c.s21_db(min(f2, 26.5e9)), 2)
                        two_lo.setdefault(lo_ghz, []).append(two)
                    row = {"lo_ghz": lo_ghz, "tx_filter": f"0x{b:02X}", "band": BAND_NAME[b >> 4],
                           "model_s21_at_lo_db": round(loss[b], 1), "is_reference": int(b == ref),
                           "lo_dbm_ref_bias": round(levels[b], 2), **({"two_lo_dbm": two} if args.read_2lo else {})}
                    if args.also_swap:
                        must(board.set_iq_swap(True), "SET IQ SWAP")
                        time.sleep(SETTLE_S)
                        f, p = read(ff, lo)
                        must(board.set_iq_swap(False), "SET IQ THRU")
                        row["lo_dbm_swap"] = round(p - fr3c.s21_db(f), 2)
                    append(states_csv, row)
                temp = board.get_lmx_temperature_c()
                blocking = [levels[b] for b in states if loss[b] <= -BLOCKING_DB]
                vals = list(levels.values())
                append(table, {"lo_ghz": lo_ghz, "lmx_power": drive, "ref_filter": f"0x{ref:02X}", "ref_model_s21_db": round(loss[ref], 1),
                               "ref_i_v": round(res.i_v, 5), "ref_q_v": round(res.q_v, 5),
                               "null_search_dbm": round(res.level_dbm, 2), "ref_dbm_in_sweep": round(levels[ref], 2),
                               "n_states": len(states), "min_dbm": round(min(vals), 2), "max_dbm": round(max(vals), 2),
                               "n_blocking": len(blocking), "floor_dbm": round(st.median(blocking), 2) if blocking else "",
                               "lmx_temp_c": round(temp, 1), "seconds": round(time.time() - t0, 1)})
                print(f"LO {lo_ghz:7.3f} ref 0x{ref:02X} | {len(states):2d} states {min(vals):+6.1f} .. {max(vals):+6.1f} dBm | floor "
                      f"{(f'{st.median(blocking):+6.1f}' if blocking else '   --')} | {temp:.1f} C | {time.time() - t0:4.1f} s", flush=True)
                if not args.zero_bias:
                    start = (res.i_v, res.q_v)
                if temp > args.max_temp_c:
                    raise RuntimeError(f"LMX at {temp:.1f} C > {args.max_temp_c} C: stopping")
        finally:
            ff.write("TRAC1:TYPE CLRW")
            off = restore_ff(ff, orig)
            print(f"Saved {table}\n" + ("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
