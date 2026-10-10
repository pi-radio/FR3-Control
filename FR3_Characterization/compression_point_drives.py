"""TX compression at ONE (FR1, FR3) point at several LMX drives (user, 2026-10-09: re-run datasheet panel 7.7 -- upper sideband,
FR1 1.0 GHz, FR3 19.0 GHz, LO 18 GHz -- at drives 0, 2, 4, 7).

    python compression_point_drives.py --out-dir results/unit_005/<date> [--fr1 1 --fr3 19 --sideband upper] [--drives 0,2,4,7]

For each drive: LMX PWR d, tune + lock, IQ, the optimal filter, a fresh LO null at that drive with the filter engaged
(lo_null.Nuller, 1 MHz span, source OFF), then the same power sweep as compression_campaign.py (conversion_gain_small_case.
power_sweep: -60 dBm upward, analyzer attenuation fixed at 35 dB, stop at 5 dB compression; small-signal gain from the -50..-46
dBm steps). Output: <out-dir>/compression_point_drives_<stamp>_PWR<d>.csv per sweep and ..._summary.csv. Source OFF at the end;
the unit's configuration is restored (MeasurementSession).
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import compression_campaign  # noqa: F401  (applies the 5 dB stop and the -50..-46 dBm small-signal window)
import conversion_gain_small_case as cg
import lo_null
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, power_sweep, tune_and_lock, write_csv
from fieldfox import SETTLE_S, FieldFox
from flatness_campaign import FF_HOST
from lo_null import Nuller
from lo_cal_grid_scan import model_s21
from rx_nf_campaign import optimal_rx_filter
from tx_null_filter_state_test import states_at

START_DBM = -60.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--fr1", type=float, default=1.0)
    ap.add_argument("--fr3", type=float, default=19.0)
    ap.add_argument("--sideband", choices=("upper", "lower"), default="upper")
    ap.add_argument("--drives", default="0,2,4,7")
    ap.add_argument("--fixed-bias", default="", help="skip the null and use given biases: '0=I,Q;4=I,Q' (volts), keyed by drive")
    ap.add_argument("--null-filter", choices=("optimal", "reference"), default="reference",
                    help="filter engaged during the LO null (default since 2026-10-09: reference, the user's rule): the point's optimal filter, or the LO's reference filter (least model loss at\n the LO, as the calibration uses) -- needed when the optimal filter blocks the LO")
    args = ap.parse_args()
    fr1, fr3 = args.fr1 * 1e9, args.fr3 * 1e9
    lo = fr3 - fr1 if args.sideband == "upper" else fr3 + fr1
    bits = optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})
    null_bits = bits if args.null_filter == "optimal" else max(states_at(lo / 1e9), key=lambda b: model_s21(b, lo))
    lo_null.NULL_SPAN_HZ = 1e6
    fr1c, fr3c = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    stem = Path(args.out_dir) / f"compression_point_drives_{datetime.now():%Y%m%d_%H%M%S}"
    summary = Path(f"{stem}_summary.csv")
    print(f"{args.sideband} FR1 {args.fr1:g} FR3 {args.fr3:g} GHz, LO {lo / 1e9:g} GHz, optimal filter 0x{bits:02X}, null with 0x{null_bits:02X}", flush=True)
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        try:
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            must(board.set_iq_swap(args.sideband == "lower"), "SET IQ")
            start = (0.0, 0.0)
            for d in (int(x) for x in args.drives.split(",")):
                print(f"\n=== drive {d}", flush=True)
                # LO null at this drive (plain SA, source OFF)
                ff.setup_spectrum_analyzer(ref_level_dbm=cg.REF_FIXED_DBM)
                ff.source_enable(False)
                for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF"):
                    ff.write(c)
                must(board.set_lmx_power(d), f"LMX PWR {d}")
                tune_and_lock(board, lo)
                must(board.set_tx_filter(null_bits), "SET TXFILTER (null)")
                time.sleep(SETTLE_S)
                fixed = dict((int(k), tuple(float(x) for x in v.split(","))) for k, v in (e.split("=") for e in args.fixed_bias.split(";") if e))
                if d in fixed:
                    res = type("Fixed", (), {"i_v": fixed[d][0], "q_v": fixed[d][1], "level_dbm": float("nan")})()
                    print(f"  re-used bias for drive {d}: I_V {res.i_v:+.5f} Q_V {res.q_v:+.5f} (no null search)", flush=True)
                else:
                    ff.set_span(lo_null.NULL_SPAN_HZ)
                    nul = Nuller(ff, board, lo, fr3c, Path(f"{stem}_null_PWR{d}.csv"))
                    try:
                        res = nul.run(start)
                    finally:
                        nul.close()
                must(board.set_i_v(res.i_v), "SET I_V")
                must(board.set_q_v(res.q_v), "SET Q_V")
                start = (res.i_v, res.q_v)
                must(board.set_tx_filter(bits), "SET TXFILTER")
                time.sleep(SETTLE_S)
                # power sweep, exactly as compression_campaign.py
                ff.setup_spectrum_analyzer(ref_level_dbm=cg.REF_FIXED_DBM)
                ff.set_span(1e6)
                ff.set_attenuation(cg.DEFAULT_FIXED_ATTENUATION_DB)
                ff.source_configure(fr1, START_DBM)
                ff.source_enable(True)
                rows, r = power_sweep(ff, board, fr1c, fr3c, fr1, fr3, True, START_DBM)
                ff.source_enable(False)
                write_csv(Path(f"{stem}_PWR{d}.csv"), rows)
                p1, p3 = r.get("p1db"), r.get("p3db")
                row = {"lmx_power": d, "lo_ghz": lo / 1e9, "fr1_ghz": args.fr1, "fr3_ghz": args.fr3, "filter_bits": f"0x{bits:02X}",
                       "null_filter_bits": f"0x{null_bits:02X}", "null_dbm": round(res.level_dbm, 1), "small_signal_gain_db": r.get("small_signal_gain_db"),
                       "p1db_in_dbm": p1["input_dbm"] if p1 else "", "p1db_out_dbm": p1["output_dbm"] if p1 else "",
                       "p3db_in_dbm": p3["input_dbm"] if p3 else "", "p3db_out_dbm": p3["output_dbm"] if p3 else "",
                       "max_out_dbm": max(x["out_at_dut_dbm"] for x in rows), "stop_reason": r.get("stop_reason", ""),
                       "lmx_temp_c": round(board.get_lmx_temperature_c(), 1)}
                new = not summary.exists()
                with open(summary, "a", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(row))
                    if new:
                        w.writeheader()
                    w.writerow(row)
        finally:
            ff.source_enable(False)
            ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            off = not ff.source_state()
            print(f"Saved {summary}\n" + ("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
