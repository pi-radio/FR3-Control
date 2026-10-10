"""TX conversion gain at a few (FR1, FR3, sideband, filter) points with the per-LO LMX drive rule, each after a fresh LO null
at that LO, drive and filter (user, 2026-10-09: verify that the higher drive recovers the gain lost at LO 22-22.5 GHz).

    python tx_gain_points_drive_rule.py --out-dir results/unit_005/<date>

For each point: SET LO INT, LMX drive = lmx_drive.drive_for(LO), tune + lock, IQ (SWAP for lower), the point's filter, LO null
(lo_null.Nuller, 1 MHz span, FieldFox source OFF), then the conversion gain measured exactly as the gain sections
(flatness_campaign.sweep_point: tracking-generator sweep of the 500 MHz window around FR1 at -40 dBm, 2026-10-05 loopback cal,
mean gain = mean linear power). Output: <out-dir>/tx_gain_points_drive_rule_<stamp>.csv. Source OFF at the end (read back);
the unit's configuration is restored (MeasurementSession).
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

import flatness_campaign as fc
import lo_null
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from lmx_drive import set_drive_for
from lo_null import Nuller
from results_layout import unit_dir
from rx_nf_campaign import optimal_rx_filter

# (sideband, FR1 GHz, FR3 GHz, filter) -- the four Section 4 points that lost the most gain at drive 0
POINTS = [("lower", 2.0, 20.5, "bypass"), ("lower", 2.0, 20.5, "optimal"), ("lower", 1.5, 21.0, "bypass"),
          ("lower", 2.0, 20.0, "bypass")]
CAL = unit_dir(5) / "flatness_tx_20261005" / "cal.csv"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    lo_null.NULL_SPAN_HZ = 1e6
    fr1c, fr3c = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    cal_rows = list(csv.DictReader(open(CAL, newline="")))
    cal = (np.array([float(r["freq_hz"]) for r in cal_rows]), np.array([float(r["loopback_dbm"]) for r in cal_rows]))
    out = Path(args.out_dir) / f"tx_gain_points_drive_rule_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with MeasurementSession() as board, FieldFox(fc.FF_HOST, span_hz=1e6) as ff:
        orig = None
        try:
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            start = (0.0, 0.0)
            for side, fr1_g, fr3_g, filt in POINTS:
                fr1, fr3 = fr1_g * 1e9, fr3_g * 1e9
                lo = fr3 - fr1 if side == "upper" else fr3 + fr1
                bits = 0x00 if filt == "bypass" else optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})
                # --- LO null at this LO, drive and filter (plain SA set-up, source OFF)
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
                drive = set_drive_for(board, lo)
                tune_and_lock(board, lo)
                must(board.set_iq_swap(side == "lower"), "SET IQ")
                must(board.set_tx_filter(bits), "SET TXFILTER")
                time.sleep(SETTLE_S)
                ff.set_span(lo_null.NULL_SPAN_HZ)
                nul = Nuller(ff, board, lo, fr3c, out.with_name(out.stem + f"_null_{side}_FR1_{fr1_g:g}_FR3_{fr3_g:g}_{filt}.csv"))
                try:
                    res = nul.run(start)
                finally:
                    nul.close()
                must(board.set_i_v(res.i_v), "SET I_V")
                must(board.set_q_v(res.q_v), "SET Q_V")
                start = (res.i_v, res.q_v)
                # --- conversion gain, exactly as the gain sections
                fc.setup_ff(ff, fc.DRIVE_DBM["tx"])
                ff.source_enable(True)
                time.sleep(SETTLE_S)
                pt = {"fr1_hz": fr1, "fr3_hz": fr3, "config": side, "lo_hz": lo}
                f_if, f_rf, tr, gain = fc.sweep_point(ff, "tx", pt, fr1c, fr3c, cal, fc.DRIVE_DBM["tx"])
                ff.source_enable(False)
                mean = 10 * np.log10(np.mean(10 ** (gain / 10)))
                temp = board.get_lmx_temperature_c()
                row = {"sideband": side, "fr1_ghz": fr1_g, "fr3_ghz": fr3_g, "lo_ghz": lo / 1e9, "filter": filt,
                       "filter_bits": f"0x{bits:02X}", "lmx_power": drive, "i_v": round(res.i_v, 5), "q_v": round(res.q_v, 5),
                       "null_dbm": round(res.level_dbm, 1), "mean_gain_db": round(float(mean), 2),
                       "rms_flatness_db": round(fc.rms_db(gain), 3), "max_out_dbm": round(float(tr.max()), 2),
                       "lmx_temp_c": round(temp, 1), "lmx_lock": board.get_lmx_lock(),
                       "time": datetime.now().isoformat(timespec="seconds")}
                new = not out.exists()
                with open(out, "a", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(row))
                    if new:
                        w.writeheader()
                    w.writerow(row)
                print(f"{side} FR1 {fr1_g:g} FR3 {fr3_g:g} LO {lo / 1e9:g} {filt} 0x{bits:02X} drive {drive}: null {res.level_dbm:+.1f} dBm, "
                      f"mean gain {mean:+.2f} dB, LMX {temp:.1f} C", flush=True)
        finally:
            off = fc.restore_ff(ff, orig)
            print(f"Saved {out}\n" + ("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
