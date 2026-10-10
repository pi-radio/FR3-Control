"""Near-field probe logger (H5 loop on the UXA input) for the 10 MHz clock comb.

One sweep per call, with the UXA exactly as the user set it (no settings
changed; averaging is expected to be off). Reports per spot: strongest comb
line per band, even/odd line ratio near 2.88 GHz and near 0.75 GHz (robust to
probe coupling, since nearby lines are swept within milliseconds), and the
0.75-vs-2.88 GHz ratio. Appends to probe_log.csv and prints a ranked table.

The user is at the bench, away from this computer, so prompts go to the UXA's
own screen title: "NEXT: <spot> - place probe (Ns)" counting down, then
"MEASURING <spot> - HOLD STILL" during the sweep, then the next spot. The
original title is restored at the end (also on Ctrl-C).

Usage: python rx_clock_probe_log.py [--place-s 20] SPOT [SPOT ...]
"""
from __future__ import annotations

import csv
import math
import statistics
import sys
import time
from datetime import datetime

from rx_clock_comb_capture import COMB_STEP_HZ, Uxa
from results_layout import unit_dir

UNIT = 5
OUTDIR = unit_dir(UNIT) / "rx_clock_comb" / "probe_h5"
LOG = OUTDIR / "probe_log.csv"
BANDS_GHZ = ((0.5, 1.0), (1.0, 2.0), (2.0, 2.65), (2.65, 2.95), (2.95, 3.5))
EVEN_ODD_WINDOWS_GHZ = ((2.80, 2.96), (0.70, 0.80))


def line_levels(freqs, trace):
    """Level (dBm) at every 10 MHz multiple: max within +-3 points."""
    df = freqs[1] - freqs[0]
    out = {}
    k = int(freqs[0] // COMB_STEP_HZ) + 1
    while k * COMB_STEP_HZ <= freqs[-1]:
        i = round((k * COMB_STEP_HZ - freqs[0]) / df)
        out[k] = max(trace[max(0, i - 3):i + 4])
        k += 1
    return out


def power_mean_db(vals):
    return 10 * math.log10(sum(10 ** (v / 10) for v in vals) / len(vals))


def title(uxa, text):
    # This UXA's firmware doesn't show the annotation title; the screen tab name is
    # visible but only fits about 17 characters.
    uxa.write(f':INST:SCR:REN "{text[:16]}"')


def measure(uxa, spot, note=""):
    start = float(uxa.query(":SENS:FREQ:STAR?"))
    stop = float(uxa.query(":SENS:FREQ:STOP?"))
    npts = int(float(uxa.query(":SENS:SWE:POIN?")))
    sweep_s = float(uxa.query(":SENS:SWE:TIME?"))
    ttype = uxa.query(":TRAC1:TYPE?")
    uxa.write(":FORM:TRAC:DATA ASC")
    uxa.write(":INIT:REST")
    uxa.check("INIT:REST")
    wait = sweep_s * 1.2 + 0.5
    if ttype.upper().startswith("AVER"):
        navg = int(float(uxa.query(":SENS:AVER:COUN?")))
        wait = navg * sweep_s * 1.3 + 1.0
        print(f"(trace type {ttype}: averaging {navg} sweeps)")
    title(uxa, f"HOLD {spot}")
    print(f"[{spot}] measuring, {wait:.1f} s ...")
    time.sleep(wait)
    trace = [float(v) for v in uxa.query(":TRAC:DATA? TRACE1").split(",")]
    uxa.check("TRAC:DATA?")
    freqs = [start + i * (stop - start) / (npts - 1) for i in range(npts)]
    lines = line_levels(freqs, trace)
    floor = statistics.median(trace)

    row = {"timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"), "spot": spot, "note": note,
           "trace_type": ttype, "median_floor_dbm": round(floor, 1)}
    for a, b in BANDS_GHZ:
        sel = {k: v for k, v in lines.items() if a * 1e9 <= k * COMB_STEP_HZ < b * 1e9}
        k = max(sel, key=sel.get)
        row[f"max_{a:.2f}-{b:.2f}_dbm"] = round(sel[k], 1)
        row[f"max_{a:.2f}-{b:.2f}_at_ghz"] = round(k * COMB_STEP_HZ / 1e9, 2)
    for a, b in EVEN_ODD_WINDOWS_GHZ:
        sel = {k: v for k, v in lines.items() if a * 1e9 <= k * COMB_STEP_HZ <= b * 1e9}
        even = [v for k, v in sel.items() if k % 2 == 0]
        odd = [v for k, v in sel.items() if k % 2 == 1]
        row[f"even_minus_odd_{a:.2f}-{b:.2f}_db"] = round(power_mean_db(even) - power_mean_db(odd), 1)
    row["low_minus_high_db"] = round(row["max_0.50-1.00_dbm"] - row["max_2.65-2.95_dbm"], 1)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    with open(OUTDIR / f"trace_{row['timestamp']}_{spot}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["freq_hz", "dbm"])
        w.writerows([f"{fq:.0f}", f"{p:.2f}"] for fq, p in zip(freqs, trace))
    new = not LOG.exists()
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    return row


def print_table(mark_ts=()):
    rows = sorted(csv.DictReader(open(LOG)), key=lambda r: -float(r["max_2.65-2.95_dbm"]))
    print(f"\n{'spot':<28}{'0.5-1':>8}{'1-2':>8}{'2-2.65':>8}{'2.65-2.95':>10}{'2.95-3.5':>9}"
          f"{'E-O@2.88':>10}{'E-O@0.75':>10}{'low-high':>10}   (dBm; ratios in dB)")
    for r in rows:
        mark = " <" if r["timestamp"] in mark_ts else ""
        print(f"{r['spot'][:28]:<28}{r['max_0.50-1.00_dbm']:>8}{r['max_1.00-2.00_dbm']:>8}"
              f"{r['max_2.00-2.65_dbm']:>8}{r['max_2.65-2.95_dbm']:>10}{r['max_2.95-3.50_dbm']:>9}"
              f"{r['even_minus_odd_2.80-2.96_db']:>10}{r['even_minus_odd_0.70-0.80_db']:>10}"
              f"{r['low_minus_high_db']:>10}{mark}")


def main() -> int:
    args = sys.argv[1:]
    place_s = 20
    if args[:1] == ["--place-s"]:
        place_s = int(args[1])
        args = args[2:]
    spots = args
    get_ready_s = 45
    if args[:1] == ["--get-ready-s"]:
        get_ready_s = int(args[1])
        args = args[2:]
    spots = args
    uxa = Uxa()
    old_name = uxa.query(":INST:SCR:CAT?").strip('"').split('","')[0]
    if old_name.startswith(("HELLO", "NEXT", "HOLD", "DONE", "ALL DONE", "GET READY")):
        old_name = "Spectrum Analyzer 1"
    uxa.write(':DISP:ANN:TITL:DATA "Swept SA"')
    done = []
    try:
        for s in range(get_ready_s, 0, -5):
            title(uxa, f"READY {s}s")
            time.sleep(min(5, s))
        for n, spot in enumerate(spots, start=1):
            for s in range(place_s, 0, -1):
                title(uxa, f"{n} {spot} {s}s")
                time.sleep(1)
            done.append(measure(uxa, spot)["timestamp"])
            title(uxa, f"DONE {n}")
            time.sleep(1)
        title(uxa, "ALL DONE")
        time.sleep(5)
    finally:
        title(uxa, old_name)
    print_table(set(done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
