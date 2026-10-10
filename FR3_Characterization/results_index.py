"""Lists every measurement run of every unit in one table - the starting point
for post-processing across units (unit-to-unit variation).

    python results_index.py [--unit N] [--csv index.csv]

Walks results/unit_*/<run>/ (see results_layout.py). One row per run: what was
measured (LO, IF, sideband), under which analyzer settings (older runs used a
10 MHz span and level-tracking attenuation; newer ones 1 MHz and fixed 35 dB, so
filter on those columns before comparing units), and the headline numbers:
small-signal gain, P1dB / P3dB output, and sideband suppression (wanted - image,
cable-corrected, from the low-drive tone reading). Blank = not measured in that run."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from results_layout import unit_dirs, unit_of

COLUMNS = ["unit", "run", "stages", "lo_ghz", "if_ghz", "sideband", "span_mhz", "attenuation",
           "gain_db", "p1db_out_dbm", "p3db_out_dbm", "sideband_suppression_db", "sweep_stopped_early_because"]


def run_row(run) -> dict | None:
    mp = run / "metadata.json"
    if not mp.exists():
        return None
    meta = json.loads(mp.read_text())
    args = meta.get("args", {})
    sweep = meta.get("power_sweep") or {}
    row = {"unit": unit_of(run), "run": run.name,
           "stages": args.get("stage", "?") if (run / "tones.csv").exists() else "?",
           "lo_ghz": meta.get("f_lo_hz", 0) / 1e9, "if_ghz": meta.get("f_if_hz", 0) / 1e9,
           "sideband": args.get("sideband", ""),
           "span_mhz": meta["ff_span_hz"] / 1e6 if "ff_span_hz" in meta else "",
           "attenuation": (f"{meta['ff_attenuation_db_at_start']:g} dB fixed" if meta.get("ff_attenuation") == "fixed"
                           else meta.get("ff_attenuation", "")),
           "gain_db": sweep.get("small_signal_gain_db", ""),
           "p1db_out_dbm": (sweep.get("p1db") or {}).get("output_dbm", ""),
           "p3db_out_dbm": (sweep.get("p3db") or {}).get("output_dbm", ""),
           "sideband_suppression_db": "", "sweep_stopped_early_because": ""}
    if isinstance(row["gain_db"], float):
        row["gain_db"] = round(row["gain_db"], 2)
    elif row["gain_db"] is None:
        row["gain_db"] = ""
    stop = sweep.get("stop_reason", "")
    if stop and not stop.startswith("reached"):  # e.g. hit the analyzer guard, or aborted
        row["sweep_stopped_early_because"] = stop if len(stop) <= 60 else stop[:57] + "..."
    tp = run / "tones.csv"
    if tp.exists():
        with open(tp, newline="") as f:
            b = {t["tone"]: float(t["corrected_at_dut_dbm"]) for t in csv.DictReader(f) if t["stage"] == "B"}
        if "wanted" in b and "image" in b:
            row["sideband_suppression_db"] = round(b["wanted"] - b["image"], 1)
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", type=int)
    parser.add_argument("--csv", help="also write the table to this CSV file")
    args = parser.parse_args()

    rows = []
    for ud in unit_dirs():
        if args.unit is not None and unit_of(ud) != args.unit:
            continue
        for run in sorted(p for p in ud.iterdir() if p.is_dir()):
            row = run_row(run)
            if row:
                rows.append(row)
    if not rows:
        sys.exit("no runs found under results/unit_*/")

    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in COLUMNS}
    print("  ".join(c.ljust(widths[c]) for c in COLUMNS))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in COLUMNS))
    print(f"\n{len(rows)} run(s), unit(s): {sorted({r['unit'] for r in rows})}")
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
