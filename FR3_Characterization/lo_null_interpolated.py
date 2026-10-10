"""Temperature-interpolated LO-null bias: for every LO, read the LMX temperature, interpolate (or extrapolate) the bias between the
cold and the hot LO-null tables to that temperature, apply it and measure the LO leakage once (user request, 2026-10-05).

    python lo_null_interpolated.py [--campaign lo_null_interpolated_5MHz_20261005] [--lo-start-ghz 7 --lo-stop-ghz 22.6]
                                   [--max-lmx-temp-c 110] [--note TEXT]

Per LO: tune and lock the LMX (SETTLE_S), read the LMX temperature T, then for I and Q separately
    bias(T) = cold + (T - T_cold) / (T_hot - T_cold) x (hot - cold)
with cold/hot = that LO's null in the two tables and T_cold/T_hot = the LMX temperature each table recorded for that LO (straight-line
interpolation; extrapolation outside [T_cold, T_hot]). The bias is applied and the leakage read exactly as in lo_null_verify.py
(lo_null.Nuller's analyzer set-up and reading, trace AVG x16, marker peak search, re-centring), so the levels compare directly with
the tables' leakage_dbm_at_board and with the hot verify. Conditions: LO internal (this switches the LMX back on), LMX power 7, TX
filter bypass, IQ THRU, FieldFox source OFF. Resumable. Stops cleanly (exit code 3) if the LMX reads --max-lmx-temp-c.

Output, in results/unit_<serial>/<campaign>/: interpolated.csv, logs/lo_<GHz>GHz.csv (the reading), campaign.json, lmx_temperature_log.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time

import lo_null
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import configure_board, must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from lo_null import Nuller
from lo_null_scan import CONFIG_LO_HZ, EXIT_TOO_HOT, LMX_POWER, awake, log_temp, now
from results_layout import unit_dir

COLD = "golden_lo_null_5MHz_20260927"
HOT = "lo_null_hot_5MHz_20261004"
FIELDS = ["freq_ghz", "lmx_temp_c", "i_v", "q_v", "leakage_dbm_at_board", "frac", "extrapolated",
          "cold_i_v", "cold_q_v", "cold_temp_c", "cold_leakage_dbm", "hot_i_v", "hot_q_v", "hot_temp_c", "hot_leakage_dbm",
          "lmx_temp_c_at_reading", "tone_offset_hz", "time"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--campaign", default="lo_null_interpolated_5MHz_20261005")
    p.add_argument("--lo-start-ghz", type=float, default=7.0)
    p.add_argument("--lo-stop-ghz", type=float, default=22.6)
    p.add_argument("--max-lmx-temp-c", type=float, default=110.0)
    p.add_argument("--note", default="")
    p.add_argument("--host", default="192.168.137.61")
    p.add_argument("--port", default=None)
    return p.parse_args()


def load(serial: int, campaign: str) -> dict[str, dict]:
    with open(unit_dir(serial) / campaign / "lo_null_table.csv", newline="") as fh:
        return {r["freq_ghz"]: r for r in csv.DictReader(fh) if not r["outcome"].startswith("failed")}


def interpolate(c: dict, h: dict, t: float) -> tuple[float, float, float]:
    """(I_V, Q_V, fraction) at temperature t on the straight line through the cold and hot nulls (fraction 0 = cold, 1 = hot)."""
    tc, th = float(c["lmx_temp_c"]), float(h["lmx_temp_c"])
    frac = (t - tc) / (th - tc)
    return (float(c["i_v"]) + frac * (float(h["i_v"]) - float(c["i_v"])),
            float(c["q_v"]) + frac * (float(h["q_v"]) - float(c["q_v"])), frac)


def main() -> int:
    args = parse_args()
    cable_rf = CableLoss("fr3_cable")
    session = MeasurementSession(port=args.port)
    with awake(), session as board, FieldFox(args.host, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        cold, hot = load(serial, COLD), load(serial, HOT)
        grid = sorted((k for k in hot if k in cold and args.lo_start_ghz - 1e-9 <= float(k) <= args.lo_stop_ghz + 1e-9), key=float)
        bad = [k for k in grid if float(hot[k]["lmx_temp_c"]) - float(cold[k]["lmx_temp_c"]) < 5.0]
        must(not bad, f"hot and cold temperatures less than 5 C apart at {bad[:5]}")
        outdir = unit_dir(serial) / args.campaign
        (outdir / "logs").mkdir(parents=True, exist_ok=True)
        temp_log = str(outdir / "lmx_temperature_log.csv")
        out = outdir / "interpolated.csv"
        done = {r["freq_ghz"] for r in csv.DictReader(open(out, newline=""))} if out.exists() else set()
        todo = [k for k in grid if k not in done]
        meta = outdir / "campaign.json"
        camp = json.loads(meta.read_text()) if meta.exists() else {
            "cold_table": COLD, "hot_table": HOT, "unit_serial": serial, "averages": lo_null.SECOND_FIT_AVERAGES,
            "method": "per LO: bias = cold + (T - T_cold)/(T_hot - T_cold) x (hot - cold), T read after tuning", "runs": []}
        camp["runs"].append({"started": now(), "command": sys.argv[1:], "note": args.note, "to_do": len(todo)})
        meta.write_text(json.dumps(camp, indent=2))
        print(f"{now()}  lo_null_interpolated.py {' '.join(sys.argv[1:])}")
        print(f"Unit #{serial}: {len(grid)} LOs, {len(todo)} to do -> {outdir}")
        too_hot = False
        try:
            ff.setup_spectrum_analyzer(ref_level_dbm=lo_null.REF_LEVEL_DBM)
            ff.source_enable(False)
            configure_board(board, CONFIG_LO_HZ, "upper")          # LO INT (the LMX powers up), PWR 7, IQ THRU, bypass
            must(board.get_lo_internal() and not board.get_lmx_mute(), "LMX is not on")
            must(board.get_lmx_power() == LMX_POWER, f"LMX power is {board.get_lmx_power()}, expected {LMX_POWER}")
            print(f"LMX on (LO internal, unmuted); LMX {board.get_lmx_temperature_c():.1f} C")
            with open(out, "a", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS)
                if not done:
                    w.writeheader()
                for n, k in enumerate(todo, 1):
                    f_ghz = float(k)
                    assert not ff.source_state(), "FieldFox source must be OFF"
                    tune_and_lock(board, f_ghz * 1e9)
                    time.sleep(SETTLE_S)
                    t = board.get_lmx_temperature_c()
                    log_temp(temp_log, f"interpolated, LO {f_ghz:.3f} GHz tuned", True, t)
                    if t >= args.max_lmx_temp_c:
                        print(f"LMX at {t:.1f} C >= the {args.max_lmx_temp_c:g} C limit; stopping cleanly at LO {f_ghz:g} GHz.")
                        too_hot = True
                        break
                    c, h = cold[k], hot[k]
                    i_v, q_v, frac = interpolate(c, h, t)
                    nuller = Nuller(ff, board, f_ghz * 1e9, cable_rf, outdir / "logs" / f"lo_{f_ghz:07.3f}GHz.csv")
                    try:
                        nuller.configure_analyzer()
                        ff.tune(nuller.center)
                        level = nuller.measure_point(0, 0.0, "interpolated", i_v, q_v, lo_null.SECOND_FIT_AVERAGES)
                    finally:
                        nuller.close()
                    dbm = nuller._dbm(level)
                    row = {"freq_ghz": k, "lmx_temp_c": f"{t:.1f}", "i_v": f"{i_v:.5f}", "q_v": f"{q_v:.5f}",
                           "leakage_dbm_at_board": f"{dbm:.2f}", "frac": f"{frac:.3f}", "extrapolated": int(not 0.0 <= frac <= 1.0),
                           "cold_i_v": c["i_v"], "cold_q_v": c["q_v"], "cold_temp_c": c["lmx_temp_c"],
                           "cold_leakage_dbm": c["leakage_dbm_at_board"], "hot_i_v": h["i_v"], "hot_q_v": h["q_v"],
                           "hot_temp_c": h["lmx_temp_c"], "hot_leakage_dbm": h["leakage_dbm_at_board"],
                           "lmx_temp_c_at_reading": f"{nuller.temp_c:.1f}", "tone_offset_hz": f"{nuller._offset:.0f}", "time": now()}
                    w.writerow(row)
                    fh.flush()
                    print(f"  LO {f_ghz:7.3f} GHz [{len(done) + n}/{len(grid)}]  LMX {t:.1f} C (cold {c['lmx_temp_c']}, hot "
                          f"{h['lmx_temp_c']}; frac {frac:+.2f})  I_V {i_v:+.5f}  Q_V {q_v:+.5f}  leakage {dbm:+6.1f} dBm", flush=True)
        finally:
            ff.source_enable(False)
            try:
                ff.set_span(1e6)
                ff.set_rbw(None)
            finally:
                ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            print("FieldFox source confirmed OFF (read back)." if not ff.source_state() else "*** WARNING: FieldFox source STILL ON!")
            session.snapshot = board.snapshot()                        # leave the LMX on
    print("Run done; the LMX is left on.")
    return EXIT_TOO_HOT if too_hot else 0


if __name__ == "__main__":
    sys.exit(main())
