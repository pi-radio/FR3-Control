"""Experiment Types 4 and 5 (user spec, 2026-10-07): the TX 2LO floor vs. frequency.

Type 5 (--source-dbm P): as Type 4, then the FieldFox source ON at FR1 (P dBm at the source port), read LO, FR3, 2LO and
2LO+FR1 (blank above 26.5 GHz), source OFF again before the next point's null. Output prefix tx_2lo_type5_.

    python tx_2lo_type4_sweep.py --fr1-ghz 1 --sideband upper --fr3-start 8 --fr3-stop 13 --fr3-step 0.25
                                 [--lmx-power 0] --out-dir results/unit_005/<date> [--note ...] [--setup "..."]
                                 [--append-to <existing type 4 csv>]   # extend a sweep; measured points are skipped

For every FR3: LO = FR3 - FR1 (upper, IQ THRU) or FR3 + FR1 (lower, IQ SWAP); optimal TX filter for (FR3, LO); tune the
LMX, null the LO with that filter engaged (lo_null.Nuller, warm-started from the previous point's null; one retry from
the result if the read-back LO is above RETRY_ABOVE_DBM), then read LO and 2LO at "TX-side FR3 RF Out" (1 MHz span,
RBW 10 kHz, 30 dB attenuation, no averaging, peak search, continuous sweep ON). FieldFox source OFF throughout (nothing
is fed into "TX-side FR1 IF In"). Rows are saved as they are measured: tx_2lo_type4_<stamp>[_note].csv + .json.
Board restored on exit; source read back OFF.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import lo_null
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from lo_null import Nuller
from results_layout import unit_dir
from rx_nf_campaign import optimal_rx_filter
from spur_campaign import FF_HOST, restore_ff
from tx_2lo_vs_filter_state import reading_setup
from tx_lo_products import read

RETRY_ABOVE_DBM = -45.0
FF_MAX_HZ = 26.5e9                      # FieldFox and FR3 cable calibration top end


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fr1-ghz", type=float, required=True)
    ap.add_argument("--sideband", choices=("upper", "lower"), default="upper")
    ap.add_argument("--fr3-start", type=float, required=True)
    ap.add_argument("--fr3-stop", type=float, required=True)
    ap.add_argument("--fr3-step", type=float, default=0.25)
    ap.add_argument("--lmx-power", type=int, default=0)
    ap.add_argument("--start", default="0.0,0.07", help="warm-start bias for the first point, I_V,Q_V (V)")
    ap.add_argument("--max-temp-c", type=float, default=92.0)
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--setup", default="")
    ap.add_argument("--source-dbm", type=float, default=None,
                    help="Experiment Type 5: after the null, FieldFox source ON at FR1 with this power (dBm at the "
                         "FieldFox source port), read LO, FR3, 2LO and 2LO+FR1; source OFF again before the next null")
    ap.add_argument("--append-to", default="", help="append rows to this existing Type 4 CSV (extending a sweep) "
                                                  "instead of starting a new file; points already in it are skipped")
    args = ap.parse_args()
    n = int(round((args.fr3_stop - args.fr3_start) / args.fr3_step)) + 1
    fr3s = [round(args.fr3_start + k * args.fr3_step, 6) for k in range(n)]
    fr1 = args.fr1_ghz
    fr3c, fr1c = CableLoss("fr3_cable"), CableLoss("fr1_cable")
    kind = "type5" if args.source_dbm is not None else "type4"
    if args.source_dbm is not None and args.source_dbm - fr1c.s21_db(fr1 * 1e9) > -5.0:
        raise SystemExit("source power too high for TX-side FR1 IF In (cap -5 dBm at the connector)")
    start = tuple(float(v) for v in args.start.split(","))
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(args.out_dir) if args.out_dir else unit_dir(serial)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"tx_2lo_{kind}_{stamp}{('_' + args.note) if args.note else ''}.csv"
        meta_path = out.with_suffix(".json")
        if args.append_to:
            out = Path(args.append_to)
            done = {round(float(r["fr3_ghz"]), 6) for r in csv.DictReader(open(out))}
            fr3s = [f for f in fr3s if round(f, 6) not in done]
            meta_path = out.with_name(out.stem + f"_extension_{stamp}.json")
            print(f"appending to {out}; skipping {len(done)} measured points; {len(fr3s)} to do: {fr3s}", flush=True)
        json.dump({"script": "tx_2lo_type4_sweep.py", "experiment": "Type 5" if kind == "type5" else "Type 4", "started": datetime.now().isoformat(timespec="seconds"),
                   "unit_serial": serial, "fr1_ghz": fr1, "sideband": args.sideband, "fr3_ghz": fr3s,
                   "lmx_power": args.lmx_power, "iq": "THRU" if args.sideband == "upper" else "SWAP", "tx_filter": "optimal per point",
                   "input": "off (FieldFox source OFF)" if kind == "type4" else
                            f"FieldFox source OFF while nulling; then ON at FR1, {args.source_dbm} dBm at the source port "
                            f"({args.source_dbm + fr1c.s21_db(fr1 * 1e9):.2f} dBm at TX-side FR1 IF In, FR1 cable)",
                   "setup": args.setup,
                   "readings": "LO and 2LO at TX-side FR3 RF Out, FR3 cable corrected; 1 MHz span, RBW 10 kHz, 30 dB att, "
                               "no averaging, peak search, continuous sweep ON"},
                  open(meta_path, "w"), indent=2)
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
            must(board.set_lmx_power(args.lmx_power), f"LMX PWR {args.lmx_power}")
            must(board.set_iq_swap(args.sideband == "lower"), "SET IQ")
            print(f"{'FR3':>6} {'LO':>6} {'2LO':>6} {'filter':>6} | {'null search':>11} | {'LO':>7} {'2LO':>7} dBm | LMX", flush=True)
            for fr3 in fr3s:
                lo = (fr3 - fr1 if args.sideband == "upper" else fr3 + fr1) * 1e9
                bits = optimal_rx_filter({"fr3_hz": fr3 * 1e9, "lo_hz": lo})
                tune_and_lock(board, lo)
                must(board.set_tx_filter(bits), f"SET TXFILTER 0x{bits:02X}")
                ff.source_enable(False)                                   # source OFF while nulling
                log = out.parent / f"lo_null_{kind}_{stamp}_{lo / 1e9:07.3f}GHz_0x{bits:02X}.csv"
                tries, res = 0, None
                for tries in (1, 2):
                    ff.set_span(lo_null.NULL_SPAN_HZ)
                    nul = Nuller(ff, board, lo, fr3c, log)
                    try:
                        res = nul.run(start if res is None else (res.i_v, res.q_v))
                    finally:
                        nul.close()
                    must(board.set_i_v(res.i_v), "SET I_V")
                    must(board.set_q_v(res.q_v), "SET Q_V")
                    reading_setup(ff)
                    time.sleep(SETTLE_S)
                    fl, pl = read(ff, lo)
                    lo_dbm = pl - fr3c.s21_db(fl)
                    if lo_dbm <= RETRY_ABOVE_DBM:
                        break
                if 2 * lo + 0.5e6 <= FF_MAX_HZ:
                    f2, p2 = read(ff, 2 * lo)
                    two = p2 - fr3c.s21_db(f2)
                else:
                    two = float("nan")                                   # 2LO above the analyzer / cable range
                extra = {}
                if kind == "type5":
                    ff.source_configure(fr1 * 1e9, args.source_dbm)
                    ff.source_enable(True)
                    time.sleep(SETTLE_S)
                    at = lambda f_hz: (lambda fp: fp[1] - fr3c.s21_db(fp[0]))(read(ff, f_hz))
                    f2p = 2 * lo + fr1 * 1e9
                    extra = {"source_dbm": args.source_dbm, "input_dbm": round(args.source_dbm + fr1c.s21_db(fr1 * 1e9), 2),
                             "lo_tone_dbm": round(at(lo), 2), "fr3_out_dbm": round(at(fr3 * 1e9), 2),
                             "two_lo_tone_dbm": round(at(2 * lo), 2), "two_lo_plus_fr1_ghz": f2p / 1e9,
                             "two_lo_plus_fr1_dbm": round(at(f2p), 2) if f2p + 0.5e6 <= FF_MAX_HZ else ""}
                    ff.source_enable(False)
                t = board.get_lmx_temperature_c()
                row = {"fr1_ghz": fr1, "fr3_ghz": fr3, "sideband": args.sideband, "lo_ghz": lo / 1e9, "two_lo_ghz": 2 * lo / 1e9,
                       "tx_filter": f"0x{bits:02X}", "lmx_power": args.lmx_power, "i_v": round(res.i_v, 5),
                       "q_v": round(res.q_v, 5), "null_search_dbm": round(res.level_dbm, 2), "null_tries": tries,
                       "lo_dbm": round(lo_dbm, 2), "two_lo_dbm": round(two, 2) if two == two else "", **extra, "lmx_temp_c": round(t, 1)}
                new = not out.exists()
                with open(out, "a", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(row))
                    if new:
                        w.writeheader()
                    w.writerow(row)
                print(f"{fr3:6.2f} {lo / 1e9:6.2f} {2 * lo / 1e9:6.2f} {f'0x{bits:02X}':>6} | {res.level_dbm:8.1f} x{tries} | "
                      f"{lo_dbm:+7.1f} {two:+7.1f}     | " + (f"tone: LO {extra['lo_tone_dbm']:+7.1f} FR3 {extra['fr3_out_dbm']:+6.1f} "
                      f"2LO {extra['two_lo_tone_dbm']:+7.1f} 2LO+FR1 {extra['two_lo_plus_fr1_dbm']} | " if extra else "") + f"{t:.1f} C", flush=True)
                start = (res.i_v, res.q_v)
                if t > args.max_temp_c:
                    raise RuntimeError(f"LMX at {t:.1f} C > {args.max_temp_c} C: stopping")
        finally:
            ff.source_enable(False)
            ff.write("TRAC1:TYPE CLRW")
            off = restore_ff(ff, orig)
            print(f"Saved {out}\n" + ("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
