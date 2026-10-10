"""Does the TX output 2LO follow the filter's in-board rejection at 2LO? (diagnostic, 2026-10-06)

    python tx_2lo_vs_filter_state.py --insitu results/unit_005/tx_filter_insitu_18GHz_<stamp>.csv [--lo-ghz 9]

For every band-1 TX filter state (0x30..0x3F) at LO 9 GHz, LMX PWR 0, IQ THRU, input OFF: engage the state, null the LO
with that state engaged (lo_null.Nuller, warm-started from the previous state's null), then read LO and 2LO at
"TX-side FR3 RF Out" (1 MHz span, RBW 10 kHz, 30 dB attenuation, no averaging, peak search, continuous sweep ON).
If the output 2LO comes from the mixer THROUGH the filter, it should track each state's in-board rejection at 2LO
(from tx_filter_insitu.py, 21 dB spread across band 1); if it enters AFTER the filter, it should stay roughly constant.
Results: results/unit_<n>/tx_2lo_vs_filter_state_<stamp>.csv; null logs in lo_null_single/. Board restored on exit.
"""
from __future__ import annotations

import argparse
import csv
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
from spur_campaign import FF_HOST, restore_ff
from tx_lo_products import ATT, RBW, SPAN, read


def reading_setup(ff: FieldFox) -> None:
    ff.set_attenuation(ATT)
    ff.write(f"SENS:FREQ:SPAN {SPAN:.0f}")
    ff.span_hz = SPAN
    ff.write(f"SENS:BAND:RES {RBW:.0f}")
    ff.write("SENS:SWE:POIN 401")
    ff.write("TRAC1:TYPE CLRW")
    ff.write("INIT:CONT ON")
    time.sleep(SETTLE_S)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--insitu", required=True, help="tx_filter_insitu CSV measured at 2LO")
    ap.add_argument("--lo-ghz", type=float, default=9.0)
    ap.add_argument("--lmx-power", type=int, default=0)
    ap.add_argument("--start", default="0.0029,0.0742", help="warm start for the first state (I_V,Q_V)")
    ap.add_argument("--expect-unit", type=int, default=5)
    args = ap.parse_args()
    lo = args.lo_ghz * 1e9
    insitu = {r["tx_filter"]: float(r["meas_rel_bypass_db"]) for r in csv.DictReader(open(args.insitu, newline=""))}
    fr3c = CableLoss("fr3_cable")
    states = [0x30 | s for s in range(16)]
    start = tuple(float(v) for v in args.start.split(","))
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = unit_dir(serial) / f"tx_2lo_vs_filter_state_{stamp}.csv"
        logdir = unit_dir(serial) / "lo_null_single"
        logdir.mkdir(parents=True, exist_ok=True)
        orig, rows = None, []
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
            must(board.set_iq_swap(False), "SET IQ THRU")
            for bits in states:
                must(board.set_tx_filter(bits), f"SET TXFILTER 0x{bits:02X}")
                must(board.set_i_v(start[0]), "SET I_V")
                must(board.set_q_v(start[1]), "SET Q_V")
                time.sleep(SETTLE_S)
                ff.set_span(lo_null.NULL_SPAN_HZ)
                nuller = Nuller(ff, board, lo, fr3c, logdir / f"lo_{args.lo_ghz:07.3f}GHz_0x{bits:02X}_{stamp}.csv")
                try:
                    res = nuller.run(start)
                finally:
                    nuller.close()
                must(board.set_i_v(res.i_v), "SET I_V")
                must(board.set_q_v(res.q_v), "SET Q_V")
                reading_setup(ff)
                fl, pl = read(ff, lo)
                f2, p2 = read(ff, 2 * lo)
                row = {"tx_filter": f"0x{bits:02X}", "null_outcome": res.outcome, "i_v": round(res.i_v, 5),
                       "q_v": round(res.q_v, 5), "null_level_dbm": round(res.level_dbm, 2),
                       "lo_dbm": round(pl - fr3c.s21_db(fl), 2), "two_lo_dbm": round(p2 - fr3c.s21_db(f2), 2),
                       "insitu_rejection_at_2lo_db": insitu.get(f"0x{bits:02X}"), "lmx_lock": board.get_lmx_lock(),
                       "lmx_temp_c": round(board.get_lmx_temperature_c(), 1)}
                rows.append(row)
                with open(out, "a", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(row))
                    if len(rows) == 1:
                        w.writeheader()
                    w.writerow(row)
                print(f"  0x{bits:02X}: null {res.level_dbm:7.1f} dBm ({res.outcome}) at {res.i_v:+.4f}/{res.q_v:+.4f} V | "
                      f"LO {row['lo_dbm']:+7.1f} dBm | 2LO {row['two_lo_dbm']:+7.1f} dBm | in-board rejection at 2LO "
                      f"{row['insitu_rejection_at_2lo_db']:+.1f} dB", flush=True)
                if res.ok:
                    start = (res.i_v, res.q_v)
            print(f"Saved {out}")
        finally:
            ff.write("TRAC1:TYPE CLRW")
            off = restore_ff(ff, orig)
            print("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***")
    return 0


if __name__ == "__main__":
    sys.exit(main())
