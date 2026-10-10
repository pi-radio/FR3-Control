"""How far does the TX LO null move between TX filter states at one LO? (calibration-grid decision, 2026-10-07)

    python tx_null_filter_state_test.py --los 10,15,20 --out-dir results/unit_005/<date> [--note ...] [--setup "..."]

For each LO, the filter states the calibration would have to cover there: every optimal filter of the 100 MHz grid
(FR1 0.7-4.0 GHz in 100 MHz steps, both sidebands, FR3 6-24 GHz). LMX drive 0, IQ THRU, FieldFox source OFF.
  1. each state engaged in turn: null the LO (lo_null.Nuller, warm-started from the previous state's null), read LO.
  2. cross-check: for each state, apply the null bias of each band's reference state (the middle state of that band)
     and read the LO leakage -> the penalty of calibrating once per band, or once per LO, instead of once per state.
Readings at "TX-side FR3 RF Out": 1 MHz span, RBW 10 kHz, 30 dB att, no averaging, peak search (reading_setup/read).
Output: tx_null_filter_state_<stamp>[_note]_nulls.csv and _cross.csv + .json. Board restored on exit.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import lo_null
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from lo_null import Nuller
from rx_nf_campaign import optimal_rx_filter
from spur_campaign import FF_HOST, restore_ff
from tx_2lo_vs_filter_state import reading_setup
from tx_lo_products import read

BAND_NAME = {0x3: "band 1", 0x1: "band 2", 0x2: "band 3"}       # filter byte upper nibble -> AM3153 band


def states_at(lo_ghz: float) -> list[int]:
    s = set()
    for fr1_10 in range(7, 41):
        fr1 = fr1_10 / 10
        for fr3 in (lo_ghz + fr1, lo_ghz - fr1):
            if 6.0 - 1e-9 <= fr3 <= 24.0 + 1e-9:
                s.add(optimal_rx_filter({"fr3_hz": fr3 * 1e9, "lo_hz": lo_ghz * 1e9}))
    return sorted(s)


def append(path: Path, row: dict) -> None:
    new = not path.exists()
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--los", default="10,15,20")
    ap.add_argument("--lmx-power", type=int, default=0)
    ap.add_argument("--start", default="0.0,0.07")
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--max-temp-c", type=float, default=92.0)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--setup", default="")
    args = ap.parse_args()
    los = [float(x) for x in args.los.split(",")]
    fr3c = CableLoss("fr3_cable")
    start = tuple(float(v) for v in args.start.split(","))
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(args.out_dir) / f"tx_null_filter_state_{stamp}{('_' + args.note) if args.note else ''}"
        json.dump({"script": "tx_null_filter_state_test.py", "started": datetime.now().isoformat(timespec="seconds"),
                   "unit_serial": serial, "lmx_power": args.lmx_power, "los_ghz": los,
                   "states": {str(lo): [f"0x{b:02X}" for b in states_at(lo)] for lo in los}, "setup": args.setup},
                  open(f"{base}.json", "w"), indent=2)
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
            must(board.set_iq_swap(False), "SET IQ THRU")

            def level(i_v: float, q_v: float, lo: float) -> float:
                must(board.set_i_v(i_v), "SET I_V")
                must(board.set_q_v(q_v), "SET Q_V")
                time.sleep(SETTLE_S)
                f, p = read(ff, lo)
                return p - fr3c.s21_db(f)

            for lo_ghz in los:
                lo = lo_ghz * 1e9
                tune_and_lock(board, lo)
                nulls = {}
                states = states_at(lo_ghz)
                print(f"\nLO {lo_ghz:g} GHz: {len(states)} states", flush=True)
                for bits in states:                                   # 1. a null per state
                    must(board.set_tx_filter(bits), "SET TXFILTER")
                    time.sleep(SETTLE_S)
                    ff.set_span(lo_null.NULL_SPAN_HZ)
                    nul = Nuller(ff, board, lo, fr3c, Path(f"{base}_search_{lo_ghz:g}GHz_0x{bits:02X}.csv"))
                    try:
                        res = nul.run(start)
                    finally:
                        nul.close()
                    reading_setup(ff)
                    lv = level(res.i_v, res.q_v, lo)
                    nulls[bits] = (res.i_v, res.q_v, lv)
                    start = (res.i_v, res.q_v)
                    t = board.get_lmx_temperature_c()
                    append(Path(f"{base}_nulls.csv"), {"lo_ghz": lo_ghz, "tx_filter": f"0x{bits:02X}", "band": BAND_NAME[bits >> 4],
                                                       "i_v": round(res.i_v, 5), "q_v": round(res.q_v, 5),
                                                       "null_search_dbm": round(res.level_dbm, 2), "lo_dbm": round(lv, 2),
                                                       "lmx_temp_c": round(t, 1)})
                    print(f"  0x{bits:02X} {BAND_NAME[bits >> 4]}: null I {res.i_v:+.5f} Q {res.q_v:+.5f} -> LO {lv:+6.1f} dBm | {t:.1f} C",
                          flush=True)
                    if t > args.max_temp_c:
                        raise RuntimeError(f"LMX at {t:.1f} C > {args.max_temp_c} C")
                by_band = defaultdict(list)
                for b in states:
                    by_band[b >> 4].append(b)
                refs = {band: bl[len(bl) // 2] for band, bl in by_band.items()}
                for bits in states:                                   # 2. cross-check against each band's reference null
                    must(board.set_tx_filter(bits), "SET TXFILTER")
                    for band, ref in refs.items():
                        i_v, q_v, _ = nulls[ref]
                        lv = level(i_v, q_v, lo)
                        own = nulls[bits]
                        append(Path(f"{base}_cross.csv"), {
                            "lo_ghz": lo_ghz, "tx_filter": f"0x{bits:02X}", "band": BAND_NAME[bits >> 4],
                            "ref_filter": f"0x{ref:02X}", "ref_band": BAND_NAME[band], "same_band": int(band == bits >> 4),
                            "bias_distance_mv": round(1000 * ((i_v - own[0]) ** 2 + (q_v - own[1]) ** 2) ** 0.5, 2),
                            "lo_dbm_own_null": round(own[2], 2), "lo_dbm_ref_null": round(lv, 2),
                            "penalty_db": round(lv - own[2], 2)})
                    print(f"  cross 0x{bits:02X}: " + ", ".join(f"ref 0x{r:02X}" for r in refs.values()) + " done", flush=True)
        finally:
            ff.write("TRAC1:TYPE CLRW")
            off = restore_ff(ff, orig)
            print(f"Saved {base}_nulls.csv / _cross.csv\n" + ("FieldFox source confirmed OFF (read back)." if off
                                                              else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
