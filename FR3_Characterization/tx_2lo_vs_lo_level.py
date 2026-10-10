"""TX 2LO vs. LO leakage level, set by moving the I/Q bias away from the null (user spec, 2026-10-06; type 3 2026-10-07).

    python tx_2lo_vs_lo_level.py [--lo-ghz 9 | --fr1-ghz 2 --fr3-ghz 11 --sideband upper] [--tx-filter 0x3F|optimal]
                                 [--axes I|Q|IQ] [--zero-point] [--tone-fr3-dbm 0] [--targets -40,-30,...] [--out-dir ...]

LMX PWR 0, IQ THRU (upper) or SWAP (lower), TX filter fixed. Null the LO (lo_null.Nuller, filter engaged), read LO and
2LO there. Experiment type 3 (--tone-fr3-dbm): then switch on a CW tone at FR1 into "TX-side FR1 IF In" (FieldFox
source, FR1 cable corrected, input capped at --max-input-dbm), levelled so the wanted FR3 output is the given power
+-0.25 dB; read LO, 2LO and FR3 there; the tone stays on. Then for each bias direction (--axes; IQ = from the null toward
the farthest corner of the +-0.5 V bias box), move the bias until the LO at "TX-side FR3 RF Out" is within +-0.5 dB of
each target and read LO and 2LO (and FR3 with the tone). The offset is found by a bracketing search in log(offset)
(regula falsi), within the firmware bias limit; unreachable targets report the closest level found.
Readings: 1 MHz span, RBW 10 kHz, 30 dB attenuation, no averaging, peak search, continuous sweep ON.
Results: <out-dir or results/unit_<n>>/tx_2lo_vs_lo_level_<stamp>[_note].csv + .json. Board restored on exit;
FieldFox source read back OFF.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import lo_null
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, SOURCE_POWER_RANGE_DBM, FieldFox
from lo_null import Nuller
from results_layout import unit_dir
from rx_nf_campaign import optimal_rx_filter
from spur_campaign import FF_HOST, restore_ff
from tx_2lo_vs_filter_state import reading_setup
from tx_lo_products import read

TARGETS = (-50.0, -40.0, -30.0, -20.0, -10.0, 0.0, 10.0)
TOL_DB, MAX_OFFSET_V, MAX_ITER = 0.5, 0.5, 14
TONE_TOL_DB = 0.25                       # wanted FR3 output level tolerance (experiment type 3)
TX_INPUT_LIMIT_DBM = 0.0                 # absolute maximum at TX-side FR1 IF In


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-ghz", type=float, default=9.0)
    ap.add_argument("--fr1-ghz", type=float, default=0.0, help="with --fr3-ghz: the LO is computed (upper: FR3-FR1, lower: FR3+FR1)")
    ap.add_argument("--fr3-ghz", type=float, default=0.0)
    ap.add_argument("--sideband", choices=("upper", "lower"), default="upper", help="upper = IQ THRU, lower = IQ SWAP")
    ap.add_argument("--tx-filter", default="0x39", help="filter byte, or 'optimal' (needs --fr1-ghz/--fr3-ghz)")
    ap.add_argument("--tone-fr3-dbm", type=float, default=None,
                    help="Experiment type 3: after the null, feed a CW tone at FR1 into TX-side FR1 IF In, levelled so the "
                         "wanted FR3 output is this power (dBm at the connector); it stays on for all later steps")
    ap.add_argument("--max-input-dbm", type=float, default=-5.0, help="never drive TX-side FR1 IF In above this (abs. max 0 dBm)")
    ap.add_argument("--targets", default=",".join(f"{t:g}" for t in TARGETS), help="LO leakage targets, dBm")
    ap.add_argument("--lmx-power", type=int, default=0)
    ap.add_argument("--start", default="-0.0014,0.0708")
    ap.add_argument("--max-temp-c", type=float, default=92.0)
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--note", default="")
    ap.add_argument("--axes", default="I,Q", help="bias directions to step, one case each: I, Q, or IQ (both, toward the farthest bias-box corner)")
    ap.add_argument("--zero-point", action="store_true", help="finish with I_V = Q_V = 0 V (LO and 2LO read there)")
    ap.add_argument("--out-dir", default="", help="results folder (default: results/unit_<n>/)")
    ap.add_argument("--setup", default="", help="free-text hardware setup, stored in a .json next to the .csv")
    args = ap.parse_args()
    if args.fr1_ghz and args.fr3_ghz:
        fr1, fr3 = args.fr1_ghz * 1e9, args.fr3_ghz * 1e9
        lo = fr3 - fr1 if args.sideband == "upper" else fr3 + fr1
    else:
        fr1 = fr3 = None
        lo = args.lo_ghz * 1e9
    args.lo_ghz = lo / 1e9
    if args.tx_filter == "optimal":
        if fr3 is None:
            raise SystemExit("--tx-filter optimal needs --fr1-ghz and --fr3-ghz")
        bits = optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})
    else:
        bits = int(args.tx_filter, 16)
    if args.tone_fr3_dbm is not None and fr1 is None:
        raise SystemExit("--tone-fr3-dbm needs --fr1-ghz and --fr3-ghz")
    if args.max_input_dbm > TX_INPUT_LIMIT_DBM:
        raise SystemExit(f"--max-input-dbm above the {TX_INPUT_LIMIT_DBM} dBm absolute maximum")
    targets = tuple(float(t) for t in args.targets.split(","))
    fr3c, fr1c = CableLoss("fr3_cable"), CableLoss("fr1_cable")
    tone = {"input_dbm": None, "source_dbm": None}
    start = tuple(float(v) for v in args.start.split(","))
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(args.out_dir) if args.out_dir else unit_dir(serial)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"tx_2lo_vs_lo_level_{stamp}{('_' + args.note) if args.note else ''}.csv"
        meta = {"script": "tx_2lo_vs_lo_level.py", "started": datetime.now().isoformat(timespec="seconds"),
                "unit_serial": serial, "fr1_ghz": args.fr1_ghz or None, "fr3_ghz": args.fr3_ghz or None,
                "sideband": args.sideband, "lo_ghz": args.lo_ghz, "tone_fr3_dbm": args.tone_fr3_dbm,
                "max_input_dbm": args.max_input_dbm, "lmx_power": args.lmx_power, "tx_filter": f"0x{bits:02X}",
                "iq": "THRU" if args.sideband == "upper" else "SWAP",
                "input": "off" if args.tone_fr3_dbm is None else f"CW at FR1, levelled for {args.tone_fr3_dbm} dBm at FR3", "axes": args.axes, "zero_point": args.zero_point, "start_bias_v": start,
                "targets_dbm": targets, "tolerance_db": TOL_DB, "setup": args.setup,
                "readings": "LO and 2LO at TX-side FR3 RF Out, FR3 cable corrected; 1 MHz span, RBW 10 kHz, 30 dB att, "
                            "no averaging, peak search, continuous sweep ON"}
        with open(out.with_suffix(".json"), "w") as fh:
            json.dump(meta, fh, indent=2)
        orig, rows = None, []

        def level(i_v, q_v):
            must(board.set_i_v(i_v), "SET I_V")
            must(board.set_q_v(q_v), "SET Q_V")
            time.sleep(SETTLE_S)
            f, p = read(ff, lo)
            return p - fr3c.s21_db(f)

        def at(f_hz):
            f, p = read(ff, f_hz)
            return p - fr3c.s21_db(f)

        def tone_on(target_dbm):
            """CW at FR1, levelled so the wanted FR3 output is target_dbm +-TONE_TOL_DB (input capped)."""
            inp = -40.0
            for _ in range(10):
                src = inp - fr1c.s21_db(fr1)
                lo_lim, hi_lim = SOURCE_POWER_RANGE_DBM
                if not lo_lim <= src <= hi_lim:
                    raise RuntimeError(f"FieldFox source would need {src:.1f} dBm")
                ff.source_configure(fr1, src)
                ff.source_enable(True)
                time.sleep(SETTLE_S)
                out = at(fr3)
                tone.update(input_dbm=round(inp, 2), source_dbm=round(src, 2))
                print(f"  tone: input {inp:+6.2f} dBm -> FR3 {out:+6.2f} dBm (gain {out - inp:+5.1f} dB)", flush=True)
                if abs(out - target_dbm) <= TONE_TOL_DB:
                    return out
                nxt = min(inp + min(target_dbm - out, 10.0), args.max_input_dbm)
                if nxt == inp:
                    print(f"  tone: input at its {args.max_input_dbm} dBm cap, FR3 {out:+.2f} dBm", flush=True)
                    return out
                inp = nxt
            return out

        def two_lo():
            f, p = read(ff, 2 * lo)
            return p - fr3c.s21_db(f)

        def null(st):
            ff.set_span(lo_null.NULL_SPAN_HZ)
            nuller = Nuller(ff, board, lo, fr3c, (out_dir if args.out_dir else unit_dir(serial) / "lo_null_single") / f"lo_{args.lo_ghz:07.3f}GHz_0x{bits:02X}_{stamp}.csv")
            try:
                res = nuller.run(st)
            finally:
                nuller.close()
            reading_setup(ff)
            return res

        def step_vec(axis):
            """Unit direction in the (I_V, Q_V) plane: I, Q, or IQ = from the null toward the farthest corner of the
            +-BIAS_LIMIT_V box (largest reachable LO leakage); and the largest allowed step along it (V)."""
            lim = lo_null.BIAS_LIMIT_V
            if axis == "I":
                return (1.0, 0.0), min(MAX_OFFSET_V, lim - i0)
            if axis == "Q":
                return (0.0, 1.0), min(MAX_OFFSET_V, lim - q0)
            ci, cq = (-lim if i0 > 0 else lim), (-lim if q0 > 0 else lim)
            n = math.hypot(ci - i0, cq - q0)
            return ((ci - i0) / n, (cq - q0) / n), n

        def record(case, axis, target, i_v, q_v, lo_dbm, iters):
            t = board.get_lmx_temperature_c()
            row = {"case": case, "axis": axis, "target_dbm": target, "i_v": round(i_v, 5), "q_v": round(q_v, 5),
                   "offset_mv": round(1000 * math.hypot(i_v - i0, q_v - q0), 2) if axis in ("I", "Q", "IQ") else 0.0,
                   "lo_dbm": round(lo_dbm, 2), "within_tol": int(target is None or abs(lo_dbm - target) <= TOL_DB),
                   "two_lo_dbm": round(two_lo(), 2), "iterations": iters, "lmx_temp_c": round(t, 1),
                   "input_dbm": tone["input_dbm"], "fr3_out_dbm": round(at(fr3), 2) if tone["input_dbm"] is not None else None}
            rows.append(row)
            tgt = "null" if target is None else f"{target:+.0f}"
            print(f"  {case:6s} {axis:4s} target {tgt:>5s} | offset {row['offset_mv']:+8.2f} mV | LO {row['lo_dbm']:+7.2f} dBm"
                  f"{'' if row['within_tol'] else ' (outside +-0.5 dB)'} | 2LO {row['two_lo_dbm']:+7.2f} dBm"
                  + (f" | FR3 {row['fr3_out_dbm']:+6.2f} dBm (in {row['input_dbm']:+.1f})" if row["fr3_out_dbm"] is not None else "")
                  + f" | {iters:2d} it | {t:.1f} C",
                  flush=True)
            if t > args.max_temp_c:
                raise RuntimeError(f"LMX at {t:.1f} C > {args.max_temp_c} C")

        def find(axis, target):
            """Offset (V, positive) on one axis giving LO within TOL of target; regula falsi in log10(offset).
            The bias itself stays within the firmware limit (|I_V|, |Q_V| <= lo_null.BIAS_LIMIT_V)."""
            (ui, uq), cap = step_vec(axis)

            def meas(d):
                return level(i0 + d * ui, q0 + d * uq)
            lo_d, lo_p = None, None                                   # bracket: below target
            hi_d, hi_p = None, None                                   # above target
            d = 1e-3
            it = 0
            best = None
            while it < MAX_ITER:
                p = meas(d)
                it += 1
                if best is None or abs(p - target) < abs(best[1] - target):
                    best = (d, p)
                if abs(p - target) <= TOL_DB:
                    return d, p, it
                if p < target:
                    lo_d, lo_p = d, p
                else:
                    hi_d, hi_p = d, p
                if lo_d is not None and hi_d is not None:
                    a, b = math.log10(lo_d), math.log10(hi_d)
                    frac = (target - lo_p) / (hi_p - lo_p) if hi_p != lo_p else 0.5
                    frac = min(max(frac, 0.1), 0.9)
                    d = 10 ** (a + frac * (b - a))
                elif hi_d is None:
                    if d >= cap:
                        break
                    d = min(d * (10 ** max(0.15, min(1.0, (target - p) / 20))), cap)
                else:
                    d = d / (10 ** max(0.15, min(1.0, (p - target) / 20)))
            return best[0], best[1], it

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
            tune_and_lock(board, lo)
            must(board.set_iq_swap(args.sideband == "lower"), f"SET IQ {'SWAP' if args.sideband == 'lower' else 'THRU'}")
            must(board.set_tx_filter(bits), f"SET TXFILTER 0x{bits:02X}")
            must(board.set_i_v(start[0]), "SET I_V")
            must(board.set_q_v(start[1]), "SET Q_V")
            for n, axis in enumerate(a.strip() for a in args.axes.split(",")):
                case = f"Case {n + 1}"
                res = null(start)
                i0, q0 = res.i_v, res.q_v
                print(f"\n{case} ({axis} axis only): null {res.level_dbm:.1f} dBm at I_V {i0:+.4f} V, Q_V {q0:+.4f} V", flush=True)
                record(case, "null", None, i0, q0, level(i0, q0), 0)
                if args.tone_fr3_dbm is not None and tone["input_dbm"] is None:
                    tone_on(args.tone_fr3_dbm)
                    record(case, "tone", None, i0, q0, level(i0, q0), 0)
                for target in targets:
                    d, p, it = find(axis, target)
                    (ui, uq), _ = step_vec(axis)
                    i_v, q_v = i0 + d * ui, q0 + d * uq
                    level(i_v, q_v)                                       # leave the bias at the found point
                    record(case, axis, target, i_v, q_v, p, it)
                start = (i0, q0)
            if args.zero_point:
                record("Zero", "zero", None, 0.0, 0.0, level(0.0, 0.0), 0)
            print()
        finally:
            ff.source_enable(False)
            ff.write("TRAC1:TYPE CLRW")
            if rows:
                with open(out, "w", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                    w.writeheader()
                    w.writerows(rows)
                print(f"Saved {out}")
            off = restore_ff(ff, orig)
            print("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***")
    return 0


if __name__ == "__main__":
    sys.exit(main())



