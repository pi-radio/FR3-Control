"""Warm-up and cool-down of the LO null: turn the LMX on with the fan off and watch, then turn the fan on and keep watching.

    python lo_warm_cool.py --go-file <f> --fan-on-file <f> [--warm-seconds 300] [--cool-seconds 300]

Sequence (the prompts to the user are sent by the operator, this script coordinates through two files):
  1. Connects to the board and the FieldFox, checks the state (bias = the converged 7.9 GHz null, LMX power 7, FieldFox source
     off), prints READY and waits for --go-file.
  2. When --go-file appears: SET LO INT + LMX TUNE (the LMX comes on, fan already being switched OFF), restarts the FieldFox
     averaging (INIT:REST, not a setting) and reads the LO leakage and the LMX temperature once per second.
  3. When --fan-on-file appears (the operator has just told the user to switch the fan ON) that moment is recorded, and the
     observation continues for --cool-seconds after it. Overall limit --max-seconds.
Nothing else is changed: the FieldFox analyzer settings stay as they were left; the bias is only written if it differs from the
converged values. The board runs inside a MeasurementSession (GET PERSIST first, PERSIST OFF while measuring, ON again at the
end); the LMX is left running at the end. Output: results/unit_<serial>/<name>/soak.csv, result.json (read by plot_soak.py)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime

import numpy as np

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must
from fieldfox import FieldFox
from results_layout import unit_dir

LO_HZ = 7.9e9
I_V, Q_V = 0.00149, 0.14271               # the converged 7.9 GHz null (100 uV search), unit 5
LMX_POWER = 7


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--go-file", required=True)
    parser.add_argument("--fan-on-file", required=True)
    parser.add_argument("--warm-seconds", type=float, default=300.0, help="expected warm-up length (only used for the prompt)")
    parser.add_argument("--cool-seconds", type=float, default=300.0)
    parser.add_argument("--max-seconds", type=float, default=1200.0)
    parser.add_argument("--name", default=None)
    parser.add_argument("--host", default="192.168.137.61")
    args = parser.parse_args()

    for f in (args.go_file, args.fan_on_file):
        if os.path.exists(f):
            os.remove(f)
    cable = CableLoss("fr3_cable")
    s21 = cable.s21_db(LO_HZ)
    session = MeasurementSession()
    with session as board, FieldFox(args.host) as ff:
        serial = board.get_board_serial()
        outdir = unit_dir(serial) / (args.name or f"lo_warm_cool_{datetime.now():%Y%m%d_%H%M%S}")
        outdir.mkdir(parents=True)
        assert not ff.source_state(), "FieldFox source is ON - it must be off"
        span = float(ff.query("SENS:FREQ:SPAN?")); center = float(ff.query("SENS:FREQ:CENT?"))
        ff.span_hz = span
        analyzer = {"span_hz": span, "center_hz": center, "attenuation_db": ff.attenuation_db, "rbw_hz": ff.rbw_hz,
                    "trace1_type": ff.query("TRAC1:TYPE?"), "ref_level_dbm": float(ff.query("DISP:WIND:TRAC:Y:RLEV?"))}
        pre = {"lo_internal": board.get_lo_internal(), "lmx_mute": board.get_lmx_mute(), "lmx_temp_c": board.get_lmx_temperature_c(),
               "i_v": board.get_i_v(), "q_v": board.get_q_v(), "lmx_power": board.get_lmx_power()}
        print(f"Unit #{serial}: before the start LO internal {pre['lo_internal']}, LMX mute {pre['lmx_mute']}, LMX {pre['lmx_temp_c']:.1f} C, "
              f"I_V {pre['i_v']:+.5f}, Q_V {pre['q_v']:+.5f}, LMX power {pre['lmx_power']}")
        print("FieldFox as found (not modified):", analyzer)
        # make sure the null bias and the LMX power are the intended ones (writes only if different; the LMX is still off)
        if abs(pre["i_v"] - I_V) > 2e-4 or abs(pre["q_v"] - Q_V) > 2e-4:
            must(board.set_i_v(I_V) and board.set_q_v(Q_V), "SET I_V / Q_V")
            print(f"  bias set to I_V {I_V:+.5f}, Q_V {Q_V:+.5f}")
        if pre["lmx_power"] != LMX_POWER:
            must(board.set_lmx_power(LMX_POWER), "LMX PWR")
        print("READY - waiting for the go file", flush=True)
        while not os.path.exists(args.go_file):
            time.sleep(0.05)

        # ---- t = 0: LMX on ----
        t0 = time.monotonic()
        must(board.set_lo_internal(True), "SET LO INT")
        must(board.lmx_tune(LO_HZ), "LMX TUNE")
        for _ in range(60):
            if board.get_lmx_lock() == "LOCKED":
                break
            time.sleep(0.05)
        t_locked = time.monotonic() - t0
        ff.write("INIT:REST")                                          # restart the averaging (it held noise from before)
        print(f"LMX ON at t = 0, locked after {t_locked:.2f} s. Observing ...", flush=True)
        rows, event_t = [], None
        k = 0
        time.sleep(max(0.0, 1.5 - (time.monotonic() - t0)))
        while True:
            t = time.monotonic() - t0
            if event_t is None and os.path.exists(args.fan_on_file):
                event_t = t
                print(f"  >>> fan-on file appeared at t = {t:.1f} s: cool-down starts", flush=True)
            if t > args.max_seconds or (event_t is not None and t > event_t + args.cool_seconds):
                break
            ff.write("CALC:MARK1:FUNC:MAX")
            x = float(ff.query("CALC:MARK1:X?")); y = float(ff.query("CALC:MARK1:Y?")) - s21
            if abs(x - center) > 0.3 * span:
                center = x
                ff.tune(center)
            temp = board.get_lmx_temperature_c()
            lock = board.get_lmx_lock() if k % 10 == 0 else ""
            rows.append((t, y, temp, x - LO_HZ, lock))
            if k % 15 == 0:
                print(f"  t {t:5.0f} s: LO leakage {y:+7.2f} dBm, LMX {temp:.1f} C {('(' + lock + ')') if lock else ''}", flush=True)
            k += 1
            time.sleep(max(0.0, 1.5 + k * 1.0 - (time.monotonic() - t0)))
        end = {"lmx_lock": board.get_lmx_lock(), "i_v": board.get_i_v(), "q_v": board.get_q_v(), "lmx_temp_c": board.get_lmx_temperature_c()}
        session.snapshot = board.snapshot()                            # leave the LMX running when the session closes

    with open(outdir / "soak.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "lo_leakage_dbm_at_board", "lmx_temp_c", "tone_offset_hz", "lmx_lock"])
        w.writerows([(f"{t:.2f}", f"{y:.2f}", f"{c:.1f}", f"{o:.0f}", lk) for t, y, c, o, lk in rows])
    (outdir / "result.json").write_text(json.dumps({
        "state_at_start": {"lmx_freq_ghz": LO_HZ / 1e9, "i_v": I_V, "q_v": Q_V, "lmx_power": LMX_POWER, **{"before_" + k: v for k, v in pre.items()}},
        "analyzer_as_found": analyzer, "state_at_end": end, "seconds": rows[-1][0], "n": len(rows), "start_label": "LMX on, fan off",
        "event_label": "fan turned on", "event_t_s": event_t}, indent=2, default=str))
    v = np.array([r[1] for r in rows]); c = np.array([r[2] for r in rows]); t = np.array([r[0] for r in rows])
    print(f"\nDone: {len(rows)} readings over {t[-1]:.0f} s. LO leakage first {v[0]:+.1f}, last {v[-1]:+.1f}, min {v.min():+.1f}, max {v.max():+.1f} dBm; "
          f"LMX {c[0]:.1f} -> {c[-1]:.1f} C (max {c.max():.1f}).")
    if event_t is not None:
        i = int(np.searchsorted(t, event_t))
        print(f"At the fan-on marker (t = {event_t:.0f} s): LO leakage {v[i]:+.1f} dBm, LMX {c[i]:.1f} C.")
    print("Board left with the LMX running at the found bias; flash persistence back ON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
