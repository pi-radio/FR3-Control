"""LO and 2*LO leakage out of "RX-side FR3 RF In" vs. LMX2820 output power, at one LO (diagnostic, 2026-10-05).

    python rx_lo_leak_lmx_power.py [--lo-ghz 9] [--rx-filters 0x00,0x3F]

TX side: filter BYPASSED (user, for this experiment), LO-null bias applied, output terminated. For each RX filter and
LMX power 7..0: read LO and 2*LO (marker, peak search, power averaging, 0 dB attenuation). A line that passes straight
through falls ~1 dB per dB of LO drive; a second harmonic generated on the way falls ~2 dB per dB. LMX power is set back
to 7 at the end. Hookup: "RX-side FR3 RF In" -> FR3 cable -> FieldFox input; unused ports terminated; source never on.
"""
from __future__ import annotations

import argparse
import sys
import time

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from results_layout import unit_dir
from spur_campaign import (ATT_QUIET_DB, FF_HOST, MARK_SPAN, REF_QUIET_DBM, LoNull, append, board_common, ff_setup,
                           marker, restore_ff)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-ghz", type=float, default=9.0)
    ap.add_argument("--rx-filters", default="0x00,0x3F")
    ap.add_argument("--campaign", default="spurs_20261005")
    args = ap.parse_args()
    lo = args.lo_ghz * 1e9
    rx_filters = [int(x, 16) for x in args.rx_filters.split(",")]
    fr3c = CableLoss("fr3_cable")
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=MARK_SPAN) as ff:
        serial = board.get_board_serial()
        out = unit_dir(serial) / args.campaign
        out.mkdir(parents=True, exist_ok=True)
        orig = None
        try:
            orig = ff_setup(ff, ATT_QUIET_DB, REF_QUIET_DBM)
            board_common(board)
            null = LoNull(serial)
            tune_and_lock(board, lo)
            iv, qv = null.bias(lo, board.get_lmx_temperature_c())
            must(board.set_i_v(iv), "SET I_V")
            must(board.set_q_v(qv), "SET Q_V")
            must(board.set_iq_swap(False), "SET IQ THRU")
            must(board.set_tx_filter(0x00), "SET TXFILTER bypass")
            for rxf in rx_filters:
                must(board.set_rx_filter(rxf), f"SET RXFILTER 0x{rxf:02X}")
                for pwr in range(7, -1, -1):
                    must(board.set_lmx_power(pwr), f"LMX PWR {pwr}")
                    time.sleep(SETTLE_S)
                    lock = board.get_lmx_lock()
                    row = {"lo_hz": f"{lo:.0f}", "rx_filter": f"0x{rxf:02X}", "tx_filter": "0x00", "lmx_power": pwr,
                           "lmx_lock": lock, "lmx_temp_c": round(board.get_lmx_temperature_c(), 1),
                           "i_v": round(iv, 4), "q_v": round(qv, 4)}
                    for name, f in (("lo", lo), ("2lo", 2 * lo)):
                        fx, p, floor = marker(ff, f)
                        corr = -fr3c.s21_db(fx)
                        row.update({f"{name}_hz": round(fx), f"{name}_dbm": round(p + corr, 2),
                                    f"{name}_floor_dbm": round(floor + corr, 2)})
                    append(out / f"lmx_power_lo{args.lo_ghz:g}.csv", [row])
                    print(f"  RX 0x{rxf:02X}  LMX PWR {pwr}  {lock:9s}  LO {row['lo_dbm']:7.2f} dBm   2LO {row['2lo_dbm']:7.2f} dBm "
                          f"(floors {row['lo_floor_dbm']:.1f} / {row['2lo_floor_dbm']:.1f})", flush=True)
        finally:
            board.set_lmx_power(7)
            off = restore_ff(ff, orig)
            print("LMX power restored to 7. " + ("FieldFox source confirmed OFF (read back)." if off
                                                 else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
