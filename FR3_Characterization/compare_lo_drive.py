"""Side-by-side table of Experiment Type 3 runs at different LMX drives for one FR3 (markdown, for the chat log).

    python compare_lo_drive.py <run csv> [<run csv> ...]

Each CSV is a tx_2lo_vs_lo_level.py result; its .json gives the LMX drive. Rows are grouped by step, one row per drive.
"""
import csv
import json
import sys
from pathlib import Path

STEPS = [("null", None, "Null, no tone"), ("tone", None, "Tone on"), ("IQ", -40.0, "LO target −40"),
         ("IQ", -30.0, "LO target −30"), ("IQ", -20.0, "LO target −20"), ("IQ", -10.0, "LO target −10"),
         ("IQ", 0.0, "LO target 0"), ("IQ", 10.0, "LO target +10"), ("zero", None, "I_V = Q_V = 0 V")]

runs = []
for p in map(Path, sys.argv[1:]):
    meta = json.loads(p.with_suffix(".json").read_text())
    runs.append((meta["lmx_power"], list(csv.DictReader(open(p)))))
print("| Step | LO Drive | Bias (I, Q) / distance from null | LO (dBm) | 2LO (dBm) | FR3 out (dBm) |")
print("|---|---|---|---|---|---|")
for axis, target, label in STEPS:
    for drive, rows in runs:
        r = next((r for r in rows if r["axis"] == axis and (target is None or float(r["target_dbm"] or "nan") == target)), None)
        if r is None:
            continue
        if axis == "null":
            bias = f"{float(r['i_v']):+.4f}, {float(r['q_v']):+.4f} V"
        elif axis == "IQ":
            bias = f"{float(r['offset_mv']):.2f} mV"
        else:
            bias = "–" if axis == "tone" else "0, 0"
        lo = f"{float(r['lo_dbm']):+.1f}" + ("" if r["within_tol"] == "1" else " (not reached)")
        fr3 = f"{float(r['fr3_out_dbm']):+.2f}" if r.get("fr3_out_dbm") else "–"
        print(f"| {label} | {drive} | {bias} | {lo} | {float(r['two_lo_dbm']):+.1f} | {fr3} |")
