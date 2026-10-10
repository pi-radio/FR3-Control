"""Verify an LO-null table: tune to every LO of the table, apply its (I_V, Q_V), and measure the LO leakage once (no search).

    python lo_null_verify.py --table-campaign lo_null_hot_5MHz_20261004 --campaign lo_null_hot_verify_5MHz_20261004
                             [--max-lmx-temp-c 110 --min-lmx-temp-c 72 --temp-log FILE] [--note TEXT]

Used for "hot verify" (the hot table re-applied right after the hot scan, board still hot: how much have the nulls degraded?) and
"cold bias on the hot board" (the cold golden table applied to the hot board: what does using the wrong table cost?).

Each reading uses lo_null.Nuller's own analyzer set-up and reading (span 20 kHz, attenuation 20 dB, ref +10 dBm, RBW auto, trace
AVG x16 = the averaging of the scan's final reading, marker peak search, re-centring on the tone), so the levels are directly
comparable with the table's leakage_dbm_at_board. Conditions as in lo_null_scan.py: LMX power 7, TX filter bypass, FieldFox source
OFF. Resumable (LOs already in the output are skipped). Temperature limits as in lo_null_scan.py: wait (LMX on) below the minimum,
stop cleanly with exit code 3 at the maximum.

Output, in results/unit_<serial>/<campaign>/: verify.csv (freq_ghz, i_v, q_v, leakage_dbm_at_board, table_leakage_dbm_at_board,
degradation_db, lmx_temp_c, table_lmx_temp_c, tone_offset_hz, time), logs/lo_<GHz>GHz.csv (the reading), campaign.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime

import lo_null
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import configure_board, must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from lo_null import Nuller
from lo_null_scan import CONFIG_LO_HZ, EXIT_TOO_HOT, LMX_POWER, TEMP_POLL_S, awake, log_temp, now
from results_layout import unit_dir

FIELDS = ["freq_ghz", "i_v", "q_v", "leakage_dbm_at_board", "table_leakage_dbm_at_board", "degradation_db", "lmx_temp_c",
          "table_lmx_temp_c", "tone_offset_hz", "time"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--table-campaign", required=True, help="campaign folder whose lo_null_table.csv is applied")
    p.add_argument("--campaign", required=True, help="output campaign folder")
    p.add_argument("--max-lmx-temp-c", type=float, default=0.0)
    p.add_argument("--min-lmx-temp-c", type=float, default=0.0)
    p.add_argument("--temp-log", default="")
    p.add_argument("--note", default="")
    p.add_argument("--host", default="192.168.137.61")
    p.add_argument("--port", default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cable_rf = CableLoss("fr3_cable")
    session = MeasurementSession(port=args.port)
    with awake(), session as board, FieldFox(args.host, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        src = unit_dir(serial) / args.table_campaign / "lo_null_table.csv"
        table = [r for r in csv.DictReader(open(src, newline="")) if not r["outcome"].startswith("failed")]
        outdir = unit_dir(serial) / args.campaign
        (outdir / "logs").mkdir(parents=True, exist_ok=True)
        out = outdir / "verify.csv"
        done = {r["freq_ghz"] for r in csv.DictReader(open(out, newline=""))} if out.exists() else set()
        todo = [r for r in table if r["freq_ghz"] not in done]
        meta = outdir / "campaign.json"
        camp = json.loads(meta.read_text()) if meta.exists() else {"table": str(src), "unit_serial": serial, "runs": []}
        camp["runs"].append({"started": now(), "command": sys.argv[1:], "note": args.note, "to_do": len(todo),
                             "lmx_temp_c_at_start": board.get_lmx_temperature_c()})
        meta.write_text(json.dumps(camp, indent=2))
        print(f"{now()}  lo_null_verify.py {' '.join(sys.argv[1:])}")
        print(f"Unit #{serial}: applying {src.parent.name} ({len(table)} LOs), {len(todo)} to do -> {outdir}")
        too_hot = False
        try:
            ff.setup_spectrum_analyzer(ref_level_dbm=lo_null.REF_LEVEL_DBM)
            ff.source_enable(False)
            configure_board(board, CONFIG_LO_HZ, "upper")          # LO INT, PWR 7, IQ THRU, bypass
            must(board.get_lmx_power() == LMX_POWER, f"LMX power is {board.get_lmx_power()}, expected {LMX_POWER}")
            with open(out, "a", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS)
                if not done:
                    w.writeheader()
                for n, r in enumerate(todo, 1):
                    f_ghz = float(r["freq_ghz"])
                    t_lmx = board.get_lmx_temperature_c()
                    log_temp(args.temp_log, f"verify ({args.campaign}), before LO {f_ghz:.3f} GHz", True, t_lmx)
                    if args.max_lmx_temp_c and t_lmx >= args.max_lmx_temp_c:
                        print(f"LMX at {t_lmx:.1f} C >= the {args.max_lmx_temp_c:g} C limit; stopping cleanly before LO {f_ghz:g} GHz.")
                        too_hot = True
                        break
                    while args.min_lmx_temp_c and t_lmx < args.min_lmx_temp_c:
                        time.sleep(TEMP_POLL_S)
                        t_lmx = board.get_lmx_temperature_c()
                        log_temp(args.temp_log, f"verify, waiting for {args.min_lmx_temp_c:g} C before LO {f_ghz:.3f} GHz", True, t_lmx)
                    assert not ff.source_state(), "FieldFox source must be OFF"
                    tune_and_lock(board, f_ghz * 1e9)
                    time.sleep(SETTLE_S)
                    nuller = Nuller(ff, board, f_ghz * 1e9, cable_rf, outdir / "logs" / f"lo_{f_ghz:07.3f}GHz.csv")
                    try:
                        nuller.configure_analyzer()
                        ff.tune(nuller.center)
                        level = nuller.measure_point(0, 0.0, "table", float(r["i_v"]), float(r["q_v"]),
                                                     lo_null.SECOND_FIT_AVERAGES)
                    finally:
                        nuller.close()
                    dbm = nuller._dbm(level)
                    t_read = nuller.temp_c
                    if args.min_lmx_temp_c and t_read < args.min_lmx_temp_c:
                        print(f"  LO {f_ghz:g} GHz: LMX {t_read:.1f} C during the reading (< {args.min_lmx_temp_c:g} C); noted")
                    row = {"freq_ghz": r["freq_ghz"], "i_v": r["i_v"], "q_v": r["q_v"], "leakage_dbm_at_board": f"{dbm:.2f}",
                           "table_leakage_dbm_at_board": r["leakage_dbm_at_board"],
                           "degradation_db": f"{dbm - float(r['leakage_dbm_at_board']):.2f}", "lmx_temp_c": f"{t_read:.1f}",
                           "table_lmx_temp_c": r["lmx_temp_c"], "tone_offset_hz": f"{nuller._offset:.0f}", "time": now()}
                    w.writerow(row)
                    fh.flush()
                    print(f"  LO {f_ghz:7.3f} GHz [{len(done) + n}/{len(table)}]  I_V {float(r['i_v']):+.5f}  Q_V {float(r['q_v']):+.5f}  "
                          f"leakage {dbm:+6.1f} dBm (table {float(r['leakage_dbm_at_board']):+6.1f}, "
                          f"{dbm - float(r['leakage_dbm_at_board']):+5.1f} dB)  LMX {t_read:.1f} C (table {r['lmx_temp_c']} C)", flush=True)
        finally:
            ff.source_enable(False)
            try:
                ff.set_span(1e6)
                ff.set_rbw(None)
            finally:
                ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            print("FieldFox source confirmed OFF (read back)." if not ff.source_state() else "*** WARNING: FieldFox source STILL ON!")
            session.snapshot = board.snapshot()                        # leave the LMX running; the caller decides
    return EXIT_TOO_HOT if too_hot else 0


if __name__ == "__main__":
    sys.exit(main())
