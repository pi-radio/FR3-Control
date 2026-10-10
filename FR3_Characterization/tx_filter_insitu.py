"""In-board (in-situ) TX AM3153 response at one frequency vs. its published S-parameters (diagnostic, 2026-10-06).

    python tx_filter_insitu.py --fr3-ghz 18 --fr1-ghz 2 --null-bias -0.1110,-0.0094 [--lmx-power 0] [--input-dbm -40]

Upper sideband: LO = FR3 - FR1, IQ THRU, the given LO-null bias. A CW tone at FR1 (FR1 cable corrected) makes the WANTED
output exactly at FR3 (a fundamental mixing product -- no source-harmonic contamination). The wanted output at "TX-side
FR3 RF Out" is read (1 MHz span, peak search, continuous sweep, 30 dB attenuation; 4 averages) with the TX filter in
bypass and in each of the 48 band/sub-state settings. In-board rejection = output(state) - output(bypass), compared with
the S-parameter prediction S21(state, FR3) - S21(bypass, FR3). Results: results/unit_<n>/tx_filter_insitu_<FR3>GHz_<stamp>.csv.
Board's pre-run configuration restored on exit; FieldFox source read back OFF.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime

import numpy as np

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, SOURCE_POWER_RANGE_DBM, FieldFox
from results_layout import unit_dir
from spur_campaign import FF_HOST, restore_ff
from tx_lo_products import SPAN, setup_ff

SPARAM_DIR = r"C:\Users\Aditya Dhananjay\Documents\GitHub\FR3-Control\FR3_GUI\data\am3153_sparams"
BAND_OF_NIBBLE = {0x3: 1, 0x1: 2, 0x2: 3}


def s21_file(bits: int) -> str:
    if bits >> 4 == 0:
        return "AM3153_SN2_5V_6mA_Bypass.s2p"
    return f"AM3153_SN2_5V_6mA_Band{BAND_OF_NIBBLE[bits >> 4]}_{bits & 0xF:04b}.s2p"


def s21_at(bits: int, f_hz: float) -> float:
    d = np.array([l.split() for l in open(f"{SPARAM_DIR}\\{s21_file(bits)}") if l.strip() and l[0] not in "!#"], float)
    return float(np.interp(f_hz / 1e9, d[:, 0] / 1e9, d[:, 3]))


def read_avg(ff: FieldFox, f_hz: float, n: int = 4) -> tuple[float, float]:
    ff.write(f"SENS:FREQ:CENT {f_hz:.0f}")
    time.sleep(SETTLE_S)
    ff.write("TRAC1:TYPE AVG")
    ff.write(f"SENS:AVER:COUN {n}")
    t = float(ff.query("SENS:SWE:MTIM?"))
    ff.write("TRAC1:REST")
    time.sleep(max(0.3, 1.5 * (n + 1) * t))
    ff.write("CALC:MARK1:FUNC:MAX")
    return float(ff.query("CALC:MARK1:X?")), float(ff.query("CALC:MARK1:Y?"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fr3-ghz", type=float, required=True)
    ap.add_argument("--fr1-ghz", type=float, default=2.0)
    ap.add_argument("--null-bias", required=True)
    ap.add_argument("--lmx-power", type=int, default=0)
    ap.add_argument("--input-dbm", type=float, default=-40.0)
    ap.add_argument("--expect-unit", type=int, default=5)
    args = ap.parse_args()
    fr1, fr3 = args.fr1_ghz * 1e9, args.fr3_ghz * 1e9
    lo = fr3 - fr1
    iv, qv = (float(v) for v in args.null_bias.split(","))
    fr1c, fr3c = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    states = [0x00] + [(b << 4) | s for b in (0x3, 0x1, 0x2) for s in range(16)]
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=SPAN) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        out = unit_dir(serial) / f"tx_filter_insitu_{args.fr3_ghz:g}GHz_{datetime.now():%Y%m%d_%H%M%S}.csv"
        orig, rows = None, []
        try:
            orig = setup_ff(ff)
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            must(board.set_lmx_power(args.lmx_power), f"LMX PWR {args.lmx_power}")
            tune_and_lock(board, lo)
            must(board.set_iq_swap(False), "SET IQ THRU")
            must(board.set_i_v(iv), "SET I_V")
            must(board.set_q_v(qv), "SET Q_V")
            src = args.input_dbm - fr1c.s21_db(fr1)
            lo_lim, hi_lim = SOURCE_POWER_RANGE_DBM
            if not lo_lim <= src <= hi_lim:
                raise RuntimeError(f"source would need {src:.1f} dBm")
            ff.source_configure(fr1, src)
            ff.source_enable(True)
            print(f"Unit #{serial}: FR1 {args.fr1_ghz:g} GHz at {args.input_dbm:+g} dBm, LO {lo / 1e9:g} GHz (PWR {args.lmx_power}, "
                  f"{board.get_lmx_lock()}), wanted FR3 {args.fr3_ghz:g} GHz; bias {iv:+.4f}/{qv:+.4f} V", flush=True)
            ref = None
            for bits in states:
                must(board.set_tx_filter(bits), f"SET TXFILTER 0x{bits:02X}")
                time.sleep(SETTLE_S)
                fx, p = read_avg(ff, fr3)
                level = p - fr3c.s21_db(fx)
                if bits == 0x00:
                    ref = level
                pred = s21_at(bits, fr3) - s21_at(0x00, fr3)
                meas = level - ref
                rows.append({"tx_filter": f"0x{bits:02X}", "file": s21_file(bits), "out_dbm": round(level, 2),
                             "meas_rel_bypass_db": round(meas, 2), "sparam_rel_bypass_db": round(pred, 2),
                             "meas_minus_sparam_db": round(meas - pred, 2), "freq_hz": round(fx)})
                print(f"  0x{bits:02X}: out {level:+7.2f} dBm   in-board {meas:+7.2f} dB   S-param {pred:+7.2f} dB   "
                      f"difference {meas - pred:+6.2f} dB", flush=True)
            ff.source_enable(False)
        finally:
            ff.source_enable(False)
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
