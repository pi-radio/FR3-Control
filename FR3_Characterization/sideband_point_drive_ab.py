"""Repeatability of the sideband suppression at ONE (FR1, FR3) point at two LMX drives (user, 2026-10-09: the optimal-filter
suppression improved by ~10-20 dB going from the old drive-7 data to the new drive-0 run -- is that repeatable?).

    python sideband_point_drive_ab.py --out-dir results/unit_005/<date> [--fr1 2.5 --fr3 15 --sideband upper] [--drives 0,7,0,7]

For each drive in the given order (alternating, so slow drift shows up): LMX PWR d, tune + lock, IQ for the sideband, the
optimal filter, a fresh LO null at that drive with that filter engaged (lo_null.Nuller, 1 MHz span, source OFF). Then the
same CW reading as sideband_campaign.py: tone at FR1, -40 dBm at "TX-side FR1 IF In"; desired at FR3, undesired at the image,
and the LO, each read 3 times (1 MHz span, RBW 10 kHz, 30 dB att, peak search; cables removed); with the optimal filter and
then with the filter bypassed. Output: <out-dir>/sideband_point_drive_ab_<stamp>.csv. Source OFF at the end; the unit's
configuration is restored (MeasurementSession).
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
from rx_nf_campaign import optimal_rx_filter
from spur_campaign import FF_HOST, restore_ff
from tx_lo_products import read, setup_ff

INPUT_DBM = -40.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--fr1", type=float, default=2.5)
    ap.add_argument("--fr3", type=float, default=15.0)
    ap.add_argument("--sideband", choices=("upper", "lower"), default="upper")
    ap.add_argument("--drives", default="0,7,0,7")
    args = ap.parse_args()
    fr1, fr3 = args.fr1 * 1e9, args.fr3 * 1e9
    lo = fr3 - fr1 if args.sideband == "upper" else fr3 + fr1
    img = lo - fr1 if args.sideband == "upper" else lo + fr1
    opt = optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})
    lo_null.NULL_SPAN_HZ = 1e6
    fr1c, fr3c = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    out = Path(args.out_dir) / f"sideband_point_drive_ab_{datetime.now():%Y%m%d_%H%M%S}.csv"
    print(f"{args.sideband} FR1 {args.fr1:g} FR3 {args.fr3:g} GHz: LO {lo / 1e9:g}, image {img / 1e9:g} GHz, optimal filter 0x{opt:02X}", flush=True)
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        orig = None
        try:
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            must(board.set_iq_swap(args.sideband == "lower"), "SET IQ")
            start = (0.0, 0.0)
            for run, d in enumerate(int(x) for x in args.drives.split(",")):
                ff.write("*CLS")
                ff.select_mode("SA")
                if orig is None:
                    orig = int(float(ff.query("SENS:SWE:POIN?")))
                    ff._saved_attenuation = (ff.query("SENS:POW:ATT:AUTO?") in ("1", "ON"), ff.attenuation_db)
                ff.source_enable(False)
                for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF", "TRAC1:TYPE CLRW", "SENS:BAND:RES:AUTO ON"):
                    ff.write(c)
                ff.write("CALC:MARK1:STAT NORM")
                ff.write("INIT:CONT ON")
                must(board.set_lmx_power(d), f"LMX PWR {d}")
                tune_and_lock(board, lo)
                must(board.set_tx_filter(opt), "SET TXFILTER")
                time.sleep(SETTLE_S)
                ff.set_span(lo_null.NULL_SPAN_HZ)
                nul = Nuller(ff, board, lo, fr3c, out.with_name(out.stem + f"_null_run{run}_PWR{d}.csv"))
                try:
                    res = nul.run(start)
                finally:
                    nul.close()
                must(board.set_i_v(res.i_v), "SET I_V")
                must(board.set_q_v(res.q_v), "SET Q_V")
                start = (res.i_v, res.q_v)
                setup_ff(ff)
                ff.source_configure(fr1, INPUT_DBM - fr1c.s21_db(fr1))
                ff.source_enable(True)
                for filt, bits in (("optimal", opt), ("bypass", 0x00)):
                    must(board.set_tx_filter(bits), "SET TXFILTER")
                    time.sleep(SETTLE_S)
                    for rep in range(3):
                        vals = {}
                        for name, f0 in (("desired", fr3), ("undesired", img), ("lo", lo)):
                            f, p = read(ff, f0)
                            vals[name] = p - fr3c.s21_db(f)
                            vals[name + "_raw"] = p
                        temp = board.get_lmx_temperature_c()
                        row = {"run": run, "lmx_power": d, "filter": filt, "filter_bits": f"0x{bits:02X}", "rep": rep,
                               "desired_dbm": round(vals["desired"], 2), "undesired_dbm": round(vals["undesired"], 2),
                               "suppression_db": round(vals["desired"] - vals["undesired"], 2), "lo_dbm": round(vals["lo"], 2),
                               "undesired_raw_dbm": round(vals["undesired_raw"], 2), "null_dbm": round(res.level_dbm, 1),
                               "i_v": round(res.i_v, 5), "q_v": round(res.q_v, 5), "lmx_temp_c": round(temp, 1),
                               "time": datetime.now().isoformat(timespec="seconds")}
                        new = not out.exists()
                        with open(out, "a", newline="") as fh:
                            w = csv.DictWriter(fh, fieldnames=list(row))
                            if new:
                                w.writeheader()
                            w.writerow(row)
                        print(f"run {run} PWR {d} {filt:7s} rep {rep}: desired {vals['desired']:+6.1f}  undesired {vals['undesired']:+6.1f}  "
                              f"-> {vals['desired'] - vals['undesired']:5.1f} dB   LO (tone on) {vals['lo']:+6.1f} dBm   {temp:.1f} C", flush=True)
                ff.source_enable(False)
        finally:
            off = restore_ff(ff, orig)
            print(f"Saved {out}\n" + ("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
