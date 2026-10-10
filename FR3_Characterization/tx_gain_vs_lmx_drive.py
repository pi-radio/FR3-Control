"""TX conversion gain vs LMX drive at the top of the LO range (user, 2026-10-09: drive 0 vs 4 vs 7 at LO 21, 21.5, 22 GHz),
to separate the drive from the temperature in the drop seen at high LO in the drive-0 gain re-run.

    python tx_gain_vs_lmx_drive.py --out-dir results/unit_005/<date> [--los 21,21.5,22] [--drives 0,4,7] [--fr1 1,2]

The unit is switched to the INTERNAL LO first (SET LO INT; it was left on EXT so the LMX could cool). For each LO, the drives
are run back to back (so they see the same temperature): LMX PWR d, tune + lock, IQ THRU, the optimal TX filter for FR3 =
LO + 1 GHz, a fresh LO null at that drive (lo_null.Nuller, 1 MHz span, source OFF) -- the stored tables are for drive 0 only.
Then for each FR1: CW at FR1, -40 dBm at "TX-side FR1 IF In" (FR1 cable removed), desired tone read at FR3 = LO + FR1 at
"TX-side FR3 RF Out" (FR3 cable removed; 1 MHz span, RBW 10 kHz, 30 dB att, peak search), with the optimal filter for that
FR3 and with the filter bypassed. Gain = desired - input. LMX temperature logged at every reading.
Output: <out-dir>/tx_gain_vs_lmx_drive_<stamp>.csv. Source OFF at the end (read back); board configuration restored.
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
from tx_2lo_vs_filter_state import reading_setup
from tx_lo_products import read

INPUT_DBM = -40.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--los", default="21,21.5,22")
    ap.add_argument("--drives", default="0,4,7")
    ap.add_argument("--fr1", default="1,2")
    ap.add_argument("--expect-unit", type=int, default=5)
    args = ap.parse_args()
    los = [float(x) for x in args.los.split(",")]
    drives = [int(x) for x in args.drives.split(",")]
    fr1s = [float(x) for x in args.fr1.split(",")]
    lo_null.NULL_SPAN_HZ = 1e6
    fr1c, fr3c = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    out = Path(args.out_dir) / f"tx_gain_vs_lmx_drive_{datetime.now():%Y%m%d_%H%M%S}.csv"
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
            print(f"SET LO INT done; LMX {board.get_lmx_temperature_c():.1f} C", flush=True)
            must(board.set_iq_swap(False), "SET IQ THRU")
            start = (0.0, 0.0)
            for lo_g in los:
                lo = lo_g * 1e9
                for d in drives:
                    must(board.set_lmx_power(d), f"LMX PWR {d}")
                    tune_and_lock(board, lo)
                    ref = optimal_rx_filter({"fr3_hz": lo + 1e9, "lo_hz": lo})
                    must(board.set_tx_filter(ref), "SET TXFILTER")
                    time.sleep(SETTLE_S)
                    ff.source_enable(False)
                    ff.set_span(lo_null.NULL_SPAN_HZ)
                    nul = Nuller(ff, board, lo, fr3c, out.with_name(out.stem + f"_null_LO{lo_g:g}_PWR{d}.csv"))
                    try:
                        res = nul.run(start)
                    finally:
                        nul.close()
                    must(board.set_i_v(res.i_v), "SET I_V")
                    must(board.set_q_v(res.q_v), "SET Q_V")
                    reading_setup(ff)
                    for fr1_g in fr1s:
                        fr1, fr3 = fr1_g * 1e9, lo + fr1_g * 1e9
                        ff.source_configure(fr1, INPUT_DBM - fr1c.s21_db(fr1))
                        ff.source_enable(True)
                        for filt, bits in (("optimal", optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})), ("bypass", 0x00)):
                            must(board.set_tx_filter(bits), "SET TXFILTER")
                            time.sleep(SETTLE_S)
                            f, p = read(ff, fr3)
                            g = p - fr3c.s21_db(f) - INPUT_DBM
                            temp = board.get_lmx_temperature_c()
                            row = {"lo_ghz": lo_g, "lmx_power": d, "fr1_ghz": fr1_g, "fr3_ghz": fr3 / 1e9, "filter": filt,
                                   "filter_bits": f"0x{bits:02X}", "gain_db": round(g, 2), "desired_dbm": round(g + INPUT_DBM, 2),
                                   "i_v": round(res.i_v, 5), "q_v": round(res.q_v, 5), "null_dbm": round(res.level_dbm, 1),
                                   "lmx_temp_c": round(temp, 1), "lmx_lock": board.get_lmx_lock(),
                                   "time": datetime.now().isoformat(timespec="seconds")}
                            new = not out.exists()
                            with open(out, "a", newline="") as fh:
                                w = csv.DictWriter(fh, fieldnames=list(row))
                                if new:
                                    w.writeheader()
                                w.writerow(row)
                            print(f"LO {lo_g:5.2f} PWR {d}  FR1 {fr1_g:g} FR3 {fr3 / 1e9:5.2f} {filt:7s} 0x{bits:02X}: gain {g:+6.2f} dB  "
                                  f"(null {res.level_dbm:+.1f} dBm, LMX {temp:.1f} C)", flush=True)
                        ff.source_enable(False)
                    start = (res.i_v, res.q_v) if d == drives[0] else start
        finally:
            off = restore_ff(ff, orig)
            print(f"Saved {out}\n" + ("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
