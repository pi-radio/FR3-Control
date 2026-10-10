"""Warm the board up with the LMX at 15 GHz (doubler engaged) for 10 minutes, then run the full "interpolated" measurement
(user request, 2026-10-05). Every warm-up reading (every 10 s) goes to <campaign>/lmx_temperature_log.csv.

    python interp_warmup_then_run.py        (normally started detached)
"""
import subprocess
import sys
import time
from datetime import datetime

from board import OPERATING_TIMEOUT_S, Board, find_board_ports
from conversion_gain_small_case import tune_and_lock
from lo_null_scan import log_temp
from results_layout import unit_dir

WARM_LO_HZ = 15e9
WARM_S = 600.0
POLL_S = 10.0
CAMPAIGN = "lo_null_interpolated_5MHz_20261005"
OUTDIR = unit_dir(5) / CAMPAIGN


def say(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    temp_log = str(OUTDIR / "lmx_temperature_log.csv")
    b = Board(find_board_ports()[0], timeout=OPERATING_TIMEOUT_S)
    try:
        if not b.get_lo_internal():
            b.set_lo_internal(True)
        tune_and_lock(b, WARM_LO_HZ)
        say(f"LMX at {b.get_lmx_freq_hz() / 1e9:g} GHz, {b.get_lmx_lock()}, mute {b.get_lmx_mute()}; warming for {WARM_S / 60:g} min")
        t_end = time.monotonic() + WARM_S
        while True:
            t = b.get_lmx_temperature_c()
            log_temp(temp_log, "warm-up at 15 GHz", True, t)
            say(f"warm-up: LMX {t:.1f} C ({(t_end - time.monotonic()) / 60:4.1f} min left)")
            if time.monotonic() >= t_end:
                break
            time.sleep(POLL_S)
    finally:
        b.close()
    say("warm-up done -> starting lo_null_interpolated.py")
    rc = subprocess.call([sys.executable, "-u", "lo_null_interpolated.py", "--campaign", CAMPAIGN,
                          "--note", "full run after 10 min warm-up with the LMX at 15 GHz (doubler on)"])
    say(f"lo_null_interpolated.py exited with code {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
