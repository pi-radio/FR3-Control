"""Take over the end of the hot LO-null run (unit 5) from hot_lo_null_watch.py without interrupting the scan (user request, 2026-10-04).

    python hot_lo_null_finish.py SCAN_PID       (started detached after the old watcher process is ended; the scan keeps running)

1. Wait for the running lo_null_scan.py (SCAN_PID) to exit. Exit code 3 (over-temperature cutoff): SET LO EXT, wait until the LMX
   reads <= RESUME_C (LMX off), resume the scan with the same arguments, repeat.
2. Scan finished (exit 0), board still hot and the LMX still on:
   a. "hot verify"  -> lo_null_verify.py applies the HOT table at every LO and reads the leakage once (campaign lo_null_hot_verify_...)
   With the same temperature limits (min 72 C, cutoff 110 C with cool-down and resume).
3. End (whatever happened): SET LO EXT (the LMX2820 powers fully down) and record the outcome in lo_null_temperature_sets.json.
Every temperature reading goes to <hot campaign>/lmx_temperature_log.csv.
"""
import ctypes
import json
import subprocess
import sys
import time
from datetime import datetime

from hot_lo_null_watch import (CAMPAIGN, CUTOFF_C, MIN_C, NOTE_RESUME, OUTDIR, POLL_S, RESUME_C, SCAN_ARGS, SERIAL, TEMP_LOG,
                               lo_ext, read_temp, record, say)
from lo_null_scan import EXIT_TOO_HOT
from results_layout import unit_dir

VERIFY_RUNS = [  # (label, table campaign, output campaign)
    ("hot verify", CAMPAIGN, "lo_null_hot_verify_5MHz_20261004"),
    # ("cold bias on the hot board", ...) was removed: the user stopped it on 2026-10-05 (applying the cold table to the hot board
    # is not a meaningful test) and its partial results were deleted.
]


def wait_adopted(pid: int) -> int:
    """Wait for a process that is not our child and return its exit code (the handle is opened now, so the code survives the exit)."""
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000 | 0x00100000, False, pid)        # QUERY_LIMITED_INFORMATION | SYNCHRONIZE
    if not h:
        raise RuntimeError(f"cannot open process {pid}")
    k.WaitForSingleObject(h, 0xFFFFFFFF)
    code = ctypes.c_ulong()
    k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return code.value


def cool_down(n: int) -> None:
    lo_ext(f"over-temperature cutoff #{n}")
    while read_temp(f"cooling after cutoff #{n}", False) > RESUME_C:
        time.sleep(POLL_S)


def run_with_cooling(cmd: list[str], label: str, first_rc: int | None, counter: list[int]) -> int:
    """Run cmd (or, with first_rc, continue from an adopted run that exited with that code) until it ends other than too hot."""
    rc = first_rc
    while True:
        if rc is None:
            say(f"starting {label}")
            rc = subprocess.call(cmd)
            say(f"{label} exited with code {rc}")
        if rc != EXIT_TOO_HOT:
            return rc
        counter[0] += 1
        cool_down(counter[0])
        rc = None


def main() -> int:
    scan_pid = int(sys.argv[1])
    counter, outcome = [0], "scan stopped"
    say(f"finisher: adopted scan PID {scan_pid}; cutoff {CUTOFF_C:g} C, resume at {RESUME_C:g} C (LMX off), min {MIN_C:g} C; "
        f"then {' + '.join(v[0] for v in VERIFY_RUNS)}, then SET LO EXT")
    try:
        rc = wait_adopted(scan_pid)
        say(f"adopted scan exited with code {rc}")
        scan_cmd = [sys.executable, "-u", "lo_null_scan.py", *SCAN_ARGS, "--note", NOTE_RESUME]
        rc = run_with_cooling(scan_cmd, "lo_null_scan.py (resume)", rc, counter)
        if rc != 0:
            outcome = f"scan stopped (exit code {rc}); verify runs skipped"
            return rc
        outcome = "scan finished"
        for label, table, camp in VERIFY_RUNS:
            cmd = [sys.executable, "-u", "lo_null_verify.py", "--table-campaign", table, "--campaign", camp,
                   "--max-lmx-temp-c", f"{CUTOFF_C:g}", "--min-lmx-temp-c", f"{MIN_C:g}", "--temp-log", TEMP_LOG,
                   "--note", f"{label}: {table} applied to the hot board right after the hot scan"]
            vrc = run_with_cooling(cmd, label, None, counter)
            outcome += f"; {label} " + ("done" if vrc == 0 else f"stopped (exit code {vrc})")
        return 0
    finally:
        try:
            lo_ext("end of the hot run")
        finally:
            record(outcome, counter[0])


if __name__ == "__main__":
    sys.exit(main())
