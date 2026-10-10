"""Read-only LMX temperature monitor: one reading every 10 s (GET only, nothing is set), printed and appended to a CSV.

    python lmx_temp_monitor.py OUT.csv      (normally started detached; stop it by ending the process)
"""
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

from board import OPERATING_TIMEOUT_S, Board, find_board_ports

POLL_S = 10.0


def main() -> int:
    out = Path(sys.argv[1])
    new = not out.exists()
    with open(out, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["time", "lmx_freq_ghz", "lmx_lock", "lmx_temp_c"])
        while True:
            try:
                b = Board(find_board_ports()[0], timeout=OPERATING_TIMEOUT_S)
                try:
                    t, f, lock = b.get_lmx_temperature_c(), b.get_lmx_freq_hz() / 1e9, b.get_lmx_lock()
                finally:
                    b.close()
                w.writerow([datetime.now().isoformat(timespec="seconds"), f"{f:g}", lock, f"{t:.1f}"])
                fh.flush()
                print(f"{datetime.now():%H:%M:%S} LMX {t:.1f} C  ({f:g} GHz, {lock})", flush=True)
            except Exception as e:                   # noqa: BLE001
                print(f"{datetime.now():%H:%M:%S} read failed: {e}", flush=True)
            time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
