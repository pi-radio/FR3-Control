"""Configure (FR1, FR3, sideband), null the TX LO, then switch the FieldFox source on at FR1 and LEAVE everything running
(for near-field probing; user, 2026-10-08).

    python setup_null_and_tone.py --fr1-ghz 1 --fr3-ghz 10 --sideband upper --input-dbm -50 [--null-span-hz 1e6]

LMX drive 0, optimal TX filter for the configuration, IQ THRU/SWAP. The null is found with "TX-side FR3 RF Out" on the
FieldFox (FR3 cable), the source OFF (lo_null.Nuller, PERSIST off during the search). Then the bias is applied, PERSIST is
switched back on (the nulled state is saved), and the source is switched ON at FR1 with --input-dbm at "TX-side FR1 IF In"
(FR1 cable corrected). The analyzer is left at the LO, 1 MHz span, continuous sweep ON. Nothing is restored on exit:
the source STAYS ON until switched off (python setup_null_and_tone.py --source-off).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import lo_null
from board import Board, OPERATING_TIMEOUT_S, find_board_ports
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, SOURCE_POWER_RANGE_DBM, FieldFox
from lo_null import Nuller
from rx_nf_campaign import optimal_rx_filter
from spur_campaign import FF_HOST
from tx_2lo_vs_filter_state import reading_setup
from tx_lo_products import read


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fr1-ghz", type=float, default=1.0)
    ap.add_argument("--fr3-ghz", type=float, default=10.0)
    ap.add_argument("--sideband", choices=("upper", "lower"), default="upper")
    ap.add_argument("--input-dbm", type=float, default=-50.0)
    ap.add_argument("--null-span-hz", type=float, default=1e6)
    ap.add_argument("--start", default="-0.0011,0.0685")
    ap.add_argument("--source-off", action="store_true", help="only switch the FieldFox source off and exit")
    ap.add_argument("--no-tone", action="store_true", help="null and leave the bias applied, but keep the source OFF")
    args = ap.parse_args()
    with FieldFox(FF_HOST, span_hz=1e6) as ff:
        if args.source_off:
            ff.source_enable(False)
            print("FieldFox source OFF:", not ff.source_state())
            return 0
        if args.input_dbm > -5:
            raise SystemExit("input above the -5 dBm cap")
        fr1, fr3 = args.fr1_ghz * 1e9, args.fr3_ghz * 1e9
        lo = fr3 - fr1 if args.sideband == "upper" else fr3 + fr1
        bits = optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})
        fr3c, fr1c = CableLoss("fr3_cable"), CableLoss("fr1_cable")
        lo_null.NULL_SPAN_HZ = args.null_span_hz
        b = Board(find_board_ports()[0], timeout=OPERATING_TIMEOUT_S)
        try:
            ff.write("*CLS")
            ff.select_mode("SA")
            ff.source_enable(False)
            for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF"):
                ff.write(c)
            ff.write("CALC:MARK1:STAT NORM")
            ff.write("INIT:CONT ON")
            must(b.set_persist(False), "PERSIST OFF")
            must(b.set_clock_internal(True), "CLK INT")
            must(b.set_lo_internal(True), "LO INT")
            must(b.set_lmx_power(0), "PWR 0")
            tune_and_lock(b, lo)
            must(b.set_iq_swap(args.sideband == "lower"), "IQ")
            must(b.set_tx_filter(bits), "TXFILTER")
            time.sleep(SETTLE_S)
            ff.set_span(lo_null.NULL_SPAN_HZ)
            n = Nuller(ff, b, lo, fr3c, Path(r"results\unit_005\2026-10-08") / f"null_for_probing_LO{lo / 1e9:g}GHz_0x{bits:02X}.csv")
            try:
                res = n.run(tuple(float(v) for v in args.start.split(",")))
            finally:
                n.close()
            must(b.set_i_v(res.i_v), "I_V")
            must(b.set_q_v(res.q_v), "Q_V")
            reading_setup(ff)
            time.sleep(SETTLE_S)
            fl, pl = read(ff, lo)
            lo_dbm = pl - fr3c.s21_db(fl)
            if args.no_tone:
                ff.write(f"SENS:FREQ:CENT {lo:.0f}")
                print(f"config: FR1 {args.fr1_ghz:g} GHz, FR3 {args.fr3_ghz:g} GHz, {args.sideband}, LO {lo / 1e9:g} GHz, TX filter 0x{bits:02X}")
                print(f"null: I_V {res.i_v:+.5f} V, Q_V {res.q_v:+.5f} V (search {res.level_dbm:.1f} dBm); LO read {lo_dbm:+.1f} dBm; source OFF")
                print(f"LMX {b.get_lmx_temperature_c():.1f} C; FieldFox left at {lo / 1e9:g} GHz, 1 MHz span")
                return 0
            src = args.input_dbm - fr1c.s21_db(fr1)
            lim = SOURCE_POWER_RANGE_DBM
            if not lim[0] <= src <= lim[1]:
                raise RuntimeError(f"source would need {src:.1f} dBm")
            ff.source_configure(fr1, src)
            ff.source_enable(True)
            time.sleep(SETTLE_S)
            ff_, p3 = read(ff, fr3)
            fl2, pl2 = read(ff, lo)
            ff.write(f"SENS:FREQ:CENT {lo:.0f}")
            print(f"config: FR1 {args.fr1_ghz:g} GHz, FR3 {args.fr3_ghz:g} GHz, {args.sideband}, LO {lo / 1e9:g} GHz, TX filter 0x{bits:02X}")
            print(f"null: I_V {res.i_v:+.5f} V, Q_V {res.q_v:+.5f} V (search {res.level_dbm:.1f} dBm); LO read {lo_dbm:+.1f} dBm (source off)")
            print(f"source ON: {fr1 / 1e9:g} GHz, {src:+.2f} dBm at the source = {args.input_dbm:+.1f} dBm at TX-side FR1 IF In")
            print(f"with the tone: FR3 {p3 - fr3c.s21_db(ff_):+.1f} dBm, LO {pl2 - fr3c.s21_db(fl2):+.1f} dBm at TX-side FR3 RF Out")
            print(f"LMX {b.get_lmx_temperature_c():.1f} C; FieldFox left at {lo / 1e9:g} GHz, 1 MHz span, continuous sweep")
        finally:
            b.set_persist(True)
            print("PERSIST", b.get_persist(), "| source on:", ff.source_state())
            b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
