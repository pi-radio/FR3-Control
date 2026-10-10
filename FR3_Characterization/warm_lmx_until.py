"""Warm the LMX up for a "hot" run: internal LO on, tuned to --lo-ghz at the rule's drive, then wait until the LMX die reads
at least --target-c (read every 15 s; gives up after --timeout-min). Leaves the LO running. Persistence is turned off for
the change and restored afterwards, so nothing is saved to flash.

    python warm_lmx_until.py --lo-ghz 15.1 --target-c 75
"""
from __future__ import annotations

import argparse
import sys
import time

from board import Board, OPERATING_TIMEOUT_S, find_board_ports
from conversion_gain_small_case import must, tune_and_lock
from lmx_drive import set_drive_for


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-ghz", type=float, default=15.1)
    ap.add_argument("--target-c", type=float, default=75.0)
    ap.add_argument("--timeout-min", type=float, default=60.0)
    args = ap.parse_args()
    b = Board(find_board_ports()[0], timeout=OPERATING_TIMEOUT_S)
    try:
        persist = b.get_persist()
        must(b.set_persist(False), "PERSIST OFF")
        must(b.set_lo_internal(True), "SET LO INT")
        d = set_drive_for(b, args.lo_ghz * 1e9)
        tune_and_lock(b, args.lo_ghz * 1e9)
        b.set_persist(persist)
        t0 = time.monotonic()
        while True:
            t = b.get_lmx_temperature_c()
            print(f"{(time.monotonic() - t0) / 60:5.1f} min  LMX {t:.1f} C  (LO {args.lo_ghz:g} GHz, drive {d})", flush=True)
            if t >= args.target_c:
                return 0
            if time.monotonic() - t0 > args.timeout_min * 60:
                print(f"timeout: LMX did not reach {args.target_c} C", flush=True)
                return 1
            time.sleep(15)
    finally:
        b.close()


if __name__ == "__main__":
    sys.exit(main())
