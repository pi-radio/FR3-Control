"""LMX die temperature watcher (read-only): reads the temperature every --interval-s seconds, prints it with the rise
since start and the rate over the last few minutes, and appends it to a CSV.

    python watch_lmx_temperature.py --out results/unit_005/<date>/lmx_temperature_<stamp>.csv [--interval-s 15]

The serial port is opened only for each reading and closed again straight after, so another script can use the unit
in between; stop this watcher before starting a measurement anyway.
"""
from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime
from pathlib import Path

from board import Board, OPERATING_TIMEOUT_S, find_board_ports


def read_temp() -> float:
    b = Board(find_board_ports()[0], timeout=OPERATING_TIMEOUT_S)
    try:
        return b.get_lmx_temperature_c()
    finally:
        b.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--interval-s", type=float, default=15.0)
    args = ap.parse_args()
    out = Path(args.out)
    hist: list[tuple[float, float]] = []
    t0 = time.time()
    print(f"LMX die temperature, every {args.interval_s:g} s -> {out}\nHot window 75-85 C. Ctrl+C or close the window to stop.\n")
    print(f"{'time':>8}  {'elapsed':>7}  {'LMX C':>6}  {'since start':>11}  {'last 5 min':>10}")
    while True:
        try:
            t = read_temp()
        except Exception as e:                                      # port busy (another script) or a glitch: skip
            print(f"{datetime.now():%H:%M:%S}  read failed: {e}")
            time.sleep(args.interval_s)
            continue
        now = time.time()
        hist.append((now, t))
        old = [p for p in hist if now - p[0] >= 300]
        rate = f"{t - old[-1][1]:+5.1f} C" if old else "    --"
        new = not out.exists()
        with open(out, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["time", "elapsed_s", "lmx_temp_c"])
            w.writerow([datetime.now().isoformat(timespec="seconds"), round(now - t0), round(t, 1)])
        flag = "  <-- in the hot window" if 75 <= t <= 85 else ("  <-- ABOVE 85 C" if t > 85 else "")
        print(f"{datetime.now():%H:%M:%S}  {(now - t0) / 60:6.1f}m  {t:6.1f}  {t - hist[0][1]:+10.1f}  {rate:>10}{flag}", flush=True)
        time.sleep(args.interval_s)


if __name__ == "__main__":
    main()
