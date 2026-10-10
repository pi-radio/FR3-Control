"""Wait for the board to warm up, then run the high-temperature LO-null scan, with an over-temperature cutoff (user requests, 2026-10-04).

1. Wait: read the LMX2820 die temperature every 10 s (GET only) until it reaches TRIGGER_C.
2. Scan: run lo_null_scan.py with exactly the golden (cold) run's arguments (7-22.6 GHz, 5 MHz step, warm start) under the hot
   campaign name, plus --max-lmx-temp-c CUTOFF_C: before every LO the scan reads the LMX temperature and stops cleanly if it is
   at or above the cutoff (115 C = the data sheet's 125 C recommended maximum junction temperature, less the sensor's +-5 C
   accuracy and 5 C margin), and --min-lmx-temp-c MIN_C: every reading of every LO is taken with the LMX at or above MIN_C (the scan waits for it,
   and redoes an LO if any reading of its search dipped below).
3. Cool: after a cutoff, SET LO EXT (the firmware powers the LMX2820 fully down), read the temperature every 10 s until it is at
   or below RESUME_C, then resume the scan with the same command (resumable; the scan switches the LO back to internal itself).
   Note: with the LMX powered down the die reads ~15 C lower within seconds (its own heating is gone), so RESUME_C is an
   LMX-off reading.
4. End (scan finished, or stopped for any other reason): SET LO EXT so the board doesn't sit hot, and record the outcome in
   results/unit_005/lo_null_temperature_sets.json.

Every temperature reading -- waiting, before every LO of the scan, cooling -- goes to <campaign>/lmx_temperature_log.csv
(time, phase, lmx_on, lmx_temp_c); the scan's logs/lo_*.csv also hold the temperature at every single bias reading.

    python hot_lo_null_watch.py            (normally started detached; output -> results/unit_005/<campaign>_watch.log)
"""
import csv
import json
import subprocess
import sys
import time
from datetime import datetime

from board import OPERATING_TIMEOUT_S, Board, find_board_ports
from lo_null_scan import EXIT_TOO_HOT, log_temp
from results_layout import unit_dir

TRIGGER_C = 72.0                # start as soon as the LMX reads the minimum (user: "start now")
MIN_C = 72.0                    # every reading of every LO's search must be at or above this
CUTOFF_C = 110.0                # user-set (data sheet: 125 C recommended max junction)
RESUME_C = 75.0                 # LMX-off reading (~90 C once the LMX is back on)
POLL_S = 10.0
SERIAL = 5
CAMPAIGN = "lo_null_hot_5MHz_20261004"
OUTDIR = unit_dir(SERIAL) / CAMPAIGN
TEMP_LOG = str(OUTDIR / "lmx_temperature_log.csv")
SCAN_ARGS = ["--campaign", CAMPAIGN, "--lo-start-ghz", "7.0", "--lo-stop-ghz", "22.6", "--lo-step-ghz", "0.005",
             "--warm-start", "--live-plot", "--plot-every", "20",
             "--max-lmx-temp-c", f"{CUTOFF_C:g}", "--min-lmx-temp-c", f"{MIN_C:g}", "--temp-log", TEMP_LOG]
NOTE_FIRST = ("HOT companion to golden_lo_null_5MHz_20260927 (cold): same settings, fan OFF, started once the LMX die reached "
              f"{TRIGGER_C:g} C; cutoff {CUTOFF_C:g} C, resume at {RESUME_C:g} C (LMX off)")
NOTE_RESUME = f"HOT run resumed after an over-temperature cool-down (cutoff {CUTOFF_C:g} C, resumed at {RESUME_C:g} C, LMX off)"


def say(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def with_board(fn, retries: int = 6):
    """Open the board, run fn(board), close; retry while the port is busy (e.g. a scan just released it)."""
    for attempt in range(retries):
        try:
            b = Board(find_board_ports()[0], timeout=OPERATING_TIMEOUT_S)
            try:
                return fn(b)
            finally:
                b.close()
        except Exception as e:                       # noqa: BLE001
            say(f"board access failed ({e}); retrying")
            time.sleep(POLL_S)
    raise RuntimeError("board not reachable")


def read_temp(phase: str, lmx_on: bool) -> float:
    t = with_board(lambda b: b.get_lmx_temperature_c())
    log_temp(TEMP_LOG, phase, lmx_on, t)
    say(f"LMX {t:.1f} C  ({phase})")
    return t


def lo_ext(why: str) -> None:
    def go(b):
        t = b.get_lmx_temperature_c()
        log_temp(TEMP_LOG, f"just before SET LO EXT ({why})", True, t)
        ok = b.set_lo_internal(False)
        say(f"LMX {t:.1f} C; SET LO EXT ({why}) -> {'OK' if ok else 'ERR'}; LO internal {b.get_lo_internal()}, "
            f"LMX mute {b.get_lmx_mute()}")
    with_board(go)


def record(outcome: str, cutoffs: int) -> None:
    table = OUTDIR / "lo_null_table.csv"
    rows = list(csv.DictReader(open(table))) if table.exists() else []
    temps = [float(r["lmx_temp_c"]) for r in rows]
    idx = unit_dir(SERIAL) / "lo_null_temperature_sets.json"
    sets = json.loads(idx.read_text(encoding="utf-8-sig"))
    sets["hot"].update({"status": f"{outcome} {datetime.now():%Y-%m-%d %H:%M}; {len(rows)}/3121 points; "
                                  f"{cutoffs} over-temperature cool-down(s); LO set to EXT (LMX powered down) after",
                        "cutoff_c": CUTOFF_C, "resume_c_lmx_off": RESUME_C, "temperature_log": "lmx_temperature_log.csv",
                        "lmx_temp_c": ({"min": min(temps), "max": max(temps),
                                        "mean": round(sum(temps) / len(temps), 1)} if temps else None)})
    idx.write_text(json.dumps(sets, indent=2), encoding="utf-8")
    say(f"index updated: {len(rows)} points" + (f", LMX {min(temps):.1f}-{max(temps):.1f} C during the scan" if temps else ""))


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    say(f"waiting for LMX >= {TRIGGER_C:g} C (reading every {POLL_S:g} s); cutoff {CUTOFF_C:g} C, resume at {RESUME_C:g} C")
    while read_temp("waiting for trigger", True) < TRIGGER_C:
        time.sleep(POLL_S)
    cutoffs, note, outcome = 0, NOTE_FIRST, "scan stopped"
    try:
        while True:
            say(f"starting lo_null_scan.py ({'first run' if cutoffs == 0 else f'resume #{cutoffs}'})")
            rc = subprocess.call([sys.executable, "-u", "lo_null_scan.py", *SCAN_ARGS, "--note", note])
            say(f"lo_null_scan.py exited with code {rc}")
            if rc != EXIT_TOO_HOT:
                outcome = "scan finished" if rc == 0 else f"scan stopped (exit code {rc})"
                break
            cutoffs += 1
            lo_ext(f"over-temperature cutoff #{cutoffs}")
            while read_temp(f"cooling after cutoff #{cutoffs}", False) > RESUME_C:
                time.sleep(POLL_S)
            note = NOTE_RESUME
    finally:
        try:
            lo_ext("end of the hot run")
        finally:
            record(outcome, cutoffs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
