"""LO / 2*LO / LO/2 out of "RX-side FR3 RF In" with an EXTERNAL LO (diagnostic, 2026-10-05).

    python rx_lo_leak_ext_lo.py [--lo-ghz 10] [--null-unit 5]

The user supplies the LO from the Pi-Radio OctoLO into the "LO In" connector (this script never touches the OctoLO).
Board: internal 10 MHz reference, SET LO EXT (the on-board LMX2820 is powered down), TX side in normal use (optimal TX
filter for FR1 = 2 GHz upper sideband, IQ thru, LO-null bias from the cold/hot tables at this LO), RX filter bypassed /
optimal low-side / optimal high-side. Readings as in spur_campaign B. On exit, MeasurementSession restores the board's configuration from before the run (including the LO source).
Hookup: "RX-side FR3 RF In" -> FR3 cable -> FieldFox input; OctoLO -> "LO In"; other ports terminated.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must
from fieldfox import SETTLE_S, FieldFox
from results_layout import unit_dir
from rx_nf_campaign import optimal_rx_filter
from spur_campaign import (ATT_QUIET_DB, FF_HOST, FF_MAX_HZ, MARK_SPAN, REF_QUIET_DBM, LoNull, append, ff_setup, marker,
                           restore_ff)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-ghz", type=float, default=10.0)
    ap.add_argument("--null-unit", type=int, default=0)
    ap.add_argument("--campaign", default="spurs_20261005")
    ap.add_argument("--expect-unit", type=int, default=0, help="refuse to run unless this unit is connected")
    args = ap.parse_args()
    lo = args.lo_ghz * 1e9
    fr3c = CableLoss("fr3_cable")
    rx_states = [("bypass", 0x00)]
    for side, fr3 in (("optimal_low", lo + 2e9), ("optimal_high", lo - 2e9)):
        if 6e9 <= fr3 <= FF_MAX_HZ:
            rx_states.append((side, optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})))
    tx_bits = optimal_rx_filter({"fr3_hz": lo + 2e9, "lo_hz": lo})
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=MARK_SPAN) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        out = unit_dir(serial) / args.campaign
        out.mkdir(parents=True, exist_ok=True)
        orig = None
        try:
            orig = ff_setup(ff, ATT_QUIET_DB, REF_QUIET_DBM)
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(False), "SET LO EXT")
            time.sleep(0.5)
            temp = board.get_lmx_temperature_c()
            iv, qv = LoNull(args.null_unit or serial).bias(lo, temp)
            must(board.set_i_v(iv), "SET I_V")
            must(board.set_q_v(qv), "SET Q_V")
            must(board.set_iq_swap(False), "SET IQ THRU")
            must(board.set_tx_filter(tx_bits), f"SET TXFILTER 0x{tx_bits:02X}")
            print(f"Unit #{serial}: LO EXTERNAL at {lo / 1e9:g} GHz (OctoLO), LMX temp {temp:.1f} C, "
                  f"TX filter 0x{tx_bits:02X}, I_V {iv:+.4f} Q_V {qv:+.4f}")
            for name_f, bits in rx_states:
                must(board.set_rx_filter(bits), f"SET RXFILTER 0x{bits:02X}")
                time.sleep(SETTLE_S)
                row = {"time": datetime.now().astimezone().isoformat(timespec="seconds"), "lo_source": "external (OctoLO)",
                       "lo_hz": f"{lo:.0f}", "rx_filter": name_f, "rx_filter_bits": f"0x{bits:02X}",
                       "tx_filter_bits": f"0x{tx_bits:02X}", "i_v": round(iv, 4), "q_v": round(qv, 4),
                       "lmx_temp_c": round(temp, 1)}
                for prod, f in (("lo", lo), ("2lo", 2 * lo), ("lo_half", lo / 2)):
                    if f > FF_MAX_HZ - MARK_SPAN:
                        continue
                    fx, p, floor = marker(ff, f)
                    corr = -fr3c.s21_db(fx)
                    row.update({f"{prod}_hz": round(fx), f"{prod}_dbm": round(p + corr, 2), f"{prod}_floor_dbm": round(floor + corr, 2)})
                append(out / "rx_lo_ext_lo.csv", [row])
                print(f"  RX {name_f:12s} 0x{bits:02X}:  LO {row.get('lo_dbm')} dBm   2LO {row.get('2lo_dbm')} dBm   "
                      f"LO/2 {row.get('lo_half_dbm')} dBm   (floors {row.get('lo_floor_dbm')} / {row.get('2lo_floor_dbm')} / "
                      f"{row.get('lo_half_floor_dbm')})", flush=True)
        finally:
            off = restore_ff(ff, orig)
            print("(Board configuration is restored to its pre-run state on exit.) " + ("FieldFox source confirmed OFF (read back)." if off
                                                       else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
