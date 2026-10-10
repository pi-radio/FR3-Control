"""TX-side LO / sideband / 2*LO products vs. IF input level, four bias/filter cases (user spec, 2026-10-06).

    python tx_lo_products.py [--expect-unit 5]

Static: FR1 = 2 GHz, FR3 = 11 GHz, LO = 9 GHz (upper sideband, IQ THRU), internal LO, LMX PWR 7.
Cases: 1A LO-null bias + TX filter bypass; 1B LO-null bias + optimal TX filter; 2A I_V = Q_V = 0 + bypass; 2B 0 V + optimal.
In each case: input OFF (baseline), then a 2 GHz CW tone at -60 ... -30 dBm (5 dB steps) at the "TX-side FR1 IF In"
connector (FR1 cable corrected). At every step: LO, LO-IF, LO+IF, 2LO, 2LO-IF, 2LO+IF at "TX-side FR3 RF Out" (FR3 cable
corrected). FieldFox: 1 MHz span, NO averaging (clear/write), RBW 10 kHz, 30 dB fixed attenuation, peak search on every
reading, continuous sweep always ON (wait two sweeps after each retune; never INIT:CONT OFF).
Hookup: FieldFox source -> FR1 cable -> "TX-side FR1 IF In"; "TX-side FR3 RF Out" -> FR3 cable -> FieldFox input;
"RX-side" ports terminated. Results: results/unit_<n>/tx_lo_products_<YYYYMMDD_HHMMSS>/readings.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, SOURCE_POWER_RANGE_DBM, FieldFox
from results_layout import unit_dir
from rx_nf_campaign import optimal_rx_filter
from spur_campaign import FF_HOST, LoNull, restore_ff

FR1, FR3 = 2.0e9, 11.0e9
LO = FR3 - FR1
SPAN, RBW, ATT, REF = 1e6, 10e3, 30.0, 20.0
LEVELS = [-60.0 + 5 * k for k in range(7)]                  # -60 ... -30 dBm at the connector (user, 2026-10-06)
TX_INPUT_LIMIT_DBM = 0.0
PRODUCTS = (("LO", LO), ("LO-IF", LO - FR1), ("LO+IF", LO + FR1), ("2LO", 2 * LO), ("2LO-IF", 2 * LO - FR1),
            ("2LO+IF", 2 * LO + FR1))


def setup_ff(ff: FieldFox) -> int:
    ff.write("*CLS")
    ff.select_mode("SA")
    orig = int(float(ff.query("SENS:SWE:POIN?")))
    ff.source_enable(False)
    for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF"):
        ff.write(c)
    ff._saved_attenuation = (ff.query("SENS:POW:ATT:AUTO?") in ("1", "ON"), ff.attenuation_db)
    ff.set_attenuation(ATT)
    ff.write(f"DISP:WIND:TRAC:Y:RLEV {REF:.1f}")
    ff.write(f"SENS:FREQ:SPAN {SPAN:.0f}")
    ff.write(f"SENS:BAND:RES {RBW:.0f}")
    ff.write("SENS:BAND:VID:AUTO ON")
    ff.write("SENS:SWE:POIN 401")
    ff.write("TRAC1:TYPE CLRW")                              # no averaging
    ff.write("CALC:MARK1:STAT NORM")
    ff.write("INIT:CONT ON")
    errs = ff.errors()
    if errs:
        raise RuntimeError(f"FieldFox rejected the set-up: {errs}")
    return orig


def read(ff: FieldFox, f_hz: float) -> tuple[float, float]:
    """Retune, wait two complete sweeps (continuous sweep), peak search -> (frequency, raw dBm)."""
    ff.write(f"SENS:FREQ:CENT {f_hz:.0f}")
    time.sleep(SETTLE_S)
    t = float(ff.query("SENS:SWE:MTIM?"))
    time.sleep(max(0.15, 2.2 * t))
    ff.write("CALC:MARK1:FUNC:MAX")
    return float(ff.query("CALC:MARK1:X?")), float(ff.query("CALC:MARK1:Y?"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--null-unit", type=int, default=0, help="LO-null tables from this unit (default: connected unit)")
    ap.add_argument("--null-bias", default="", help="use this I_V,Q_V (V) for the nulled cases instead of the tables")
    ap.add_argument("--lmx-power", type=int, default=7, help="LMX2820 OUTx_PWR for the whole run")
    ap.add_argument("--max-input-dbm", type=float, default=-30.0, help="top of the 5 dB input sweep (from -60 dBm)")
    ap.add_argument("--null-bias-1b", default="", help="separate I_V,Q_V (V) for case 1B (null found with the filter engaged)")
    args = ap.parse_args()
    fr1c, fr3c = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    levels = [-60.0 + 5 * k for k in range(int(round((args.max_input_dbm + 60) / 5)) + 1)]
    fixed_bias = tuple(float(v) for v in args.null_bias.split(",")) if args.null_bias else None
    fixed_bias_1b = tuple(float(v) for v in args.null_bias_1b.split(",")) if args.null_bias_1b else None
    opt = optimal_rx_filter({"fr3_hz": FR3, "lo_hz": LO})
    cases = (("1A", True, 0x00), ("1B", True, opt), ("2A", False, 0x00), ("2B", False, opt))
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=SPAN) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        out = unit_dir(serial) / f"tx_lo_products_{datetime.now():%Y%m%d_%H%M%S}"
        out.mkdir(parents=True)
        (out / "campaign.json").write_text(json.dumps({
            "unit_serial": serial, "fr1_hz": FR1, "fr3_hz": FR3, "lo_hz": LO, "sideband": "upper (IQ THRU)",
            "lmx_power": args.lmx_power, "optimal_tx_filter": f"0x{opt:02X}", "levels_dbm": levels, "span_hz": SPAN, "rbw_hz": RBW,
            "attenuation_db": ATT, "averaging": "none (clear/write)", "ff_idn": ff.identify(),
            "lo_null_tables_from_unit": args.null_unit or serial,
            "null_bias_override_v": args.null_bias or None,
            "null_bias_1b_override_v": args.null_bias_1b or None,
            "started": datetime.now().astimezone().isoformat(timespec="seconds")}, indent=2))
        null = LoNull(args.null_unit or serial)
        rows, orig = [], None
        try:
            orig = setup_ff(ff)
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            must(board.set_lmx_power(args.lmx_power), f"LMX PWR {args.lmx_power}")
            tune_and_lock(board, LO)
            must(board.set_iq_swap(False), "SET IQ THRU")
            for case, nulled, bits in cases:
                temp = board.get_lmx_temperature_c()
                if nulled and case == "1B" and fixed_bias_1b:
                    iv, qv = fixed_bias_1b
                elif nulled and fixed_bias:
                    iv, qv = fixed_bias
                else:
                    iv, qv = null.bias(LO, temp) if nulled else (0.0, 0.0)
                must(board.set_i_v(iv), "SET I_V")
                must(board.set_q_v(qv), "SET Q_V")
                must(board.set_tx_filter(bits), f"SET TXFILTER 0x{bits:02X}")
                time.sleep(SETTLE_S)
                print(f"\nCase {case}: bias {'nulled' if nulled else '0 V'} (I_V {iv:+.4f}, Q_V {qv:+.4f}), "
                      f"TX filter 0x{bits:02X}, LMX {board.get_lmx_lock()} {temp:.1f} C", flush=True)
                for level in [None] + levels:
                    if level is None:
                        ff.source_enable(False)
                        src = None
                    else:
                        if level > TX_INPUT_LIMIT_DBM:
                            raise RuntimeError("input limit")
                        src = level - fr1c.s21_db(FR1)
                        lo_lim, hi_lim = SOURCE_POWER_RANGE_DBM
                        if not lo_lim <= src <= hi_lim:
                            raise RuntimeError(f"source would need {src:.1f} dBm")
                        ff.source_configure(FR1, src)
                        ff.source_enable(True)
                    time.sleep(SETTLE_S)
                    row = {"case": case, "bias": "nulled" if nulled else "0V", "tx_filter": f"0x{bits:02X}",
                           "i_v": round(iv, 4), "q_v": round(qv, 4), "lmx_temp_c": round(temp, 1),
                           "input_dbm": "off" if level is None else level,
                           "source_dbm": "" if src is None else round(src, 2)}
                    for name, f in PRODUCTS:
                        fx, p = read(ff, f)
                        row[f"{name}_dbm"] = round(p - fr3c.s21_db(fx), 2)
                        row[f"{name}_offset_hz"] = round(fx - f)
                    errs = ff.errors()
                    row["ff_errors"] = ";".join(errs)
                    rows.append(row)
                    new = not (out / "readings.csv").exists()
                    with open(out / "readings.csv", "a", newline="") as fh:   # saved as we go
                        w = csv.DictWriter(fh, fieldnames=list(row))
                        if new:
                            w.writeheader()
                        w.writerow(row)
                    print(f"  in {('off' if level is None else f'{level:+.0f}'):>4} dBm | " +
                          "  ".join(f"{n} {row[n + '_dbm']:+7.1f}" for n, _ in PRODUCTS), flush=True)
                ff.source_enable(False)
        finally:
            ff.source_enable(False)
            off = restore_ff(ff, orig)
            print(f"\nSaved {out}\n" + ("FieldFox source confirmed OFF (read back)." if off
                                         else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
