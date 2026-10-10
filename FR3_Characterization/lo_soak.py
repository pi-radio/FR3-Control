"""Soak: watch the LO leakage and the LMX temperature over time at the board's CURRENT configuration. Changes nothing.

    python lo_soak.py [--seconds 300] [--name lo_soak_<time>]

The board is only read (GET PERSIST first, then LMX/I/Q/temperature queries): no voltage, LO or PERSIST setting is written, and
no session snapshot/restore is used (a restore could re-tune the LMX). The FieldFox analyzer is used exactly as it was left by
the last nulling run (span, attenuation, reference level, RBW/VBW, averaging): nothing is configured, the marker is just read,
once per second, from the analyzer's running average. Only if the tone drifts to the edge of the span is the center re-tuned
(logged). Cable loss is subtracted to give the level at the board's RF connector.

Writes results/unit_<serial>/<name>/soak.csv (t_s, lo_leakage_dbm_at_board, lmx_temp_c, tone_offset_hz, lmx_lock), and two PNGs:
LO leakage vs. time, and LMX temperature vs. time."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from board import OPERATING_TIMEOUT_S, Board, find_board_ports
from cables import CableLoss
from fieldfox import SETTLE_S, FieldFox
from plot_power_sweep import BLUE, INK, INK2, MUTED, ORANGE, SURFACE, style_axes
from results_layout import unit_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=300.0)
    parser.add_argument("--name", default=None)
    parser.add_argument("--no-open", action="store_true", help="do not open the figures afterwards")
    parser.add_argument("--go-file", default=None, help="connect, print READY, and start recording only when this file appears")
    parser.add_argument("--start-label", default=None, help="label drawn at t = 0 on the plot, e.g. 'fan turned off'")
    parser.add_argument("--marker-file", default=None, help="when this file appears, the time is recorded and marked on the plots")
    parser.add_argument("--event-label", default="event", help="label for the marker on the plots, e.g. 'fan turned on'")
    parser.add_argument("--host", default="192.168.137.61")
    parser.add_argument("--port", default=None)
    args = parser.parse_args()

    ports = [args.port] if args.port else find_board_ports()
    if len(ports) != 1:
        raise RuntimeError(f"expected exactly one board, found {ports}")
    board = Board(ports[0], timeout=OPERATING_TIMEOUT_S)
    try:
        persist = board.get_persist()                                   # first command, per the standing rule
        serial = board.get_board_serial()
        f_lo = board.get_lmx_freq_hz()
        cable = CableLoss("fr3_cable")
        s21 = cable.s21_db(f_lo)
        outdir = unit_dir(serial) / (args.name or f"lo_soak_{datetime.now():%Y%m%d_%H%M%S}")
        outdir.mkdir(parents=True)
        state = {"persist": persist, "lo_internal": board.get_lo_internal(), "lmx_mute": board.get_lmx_mute(),
                 "lmx_lock": board.get_lmx_lock(), "lmx_freq_ghz": f_lo / 1e9, "lmx_power": board.get_lmx_power(),
                 "i_v": board.get_i_v(), "q_v": board.get_q_v(), "lmx_temp_c": board.get_lmx_temperature_c()}
        print(f"Unit #{serial}: PERSIST {'ON' if persist else 'OFF'}; LO internal {state['lo_internal']}, LMX {state['lmx_lock']} at "
              f"{f_lo / 1e9:g} GHz, power {state['lmx_power']}, I_V {state['i_v']:+.5f} V, Q_V {state['q_v']:+.5f} V, "
              f"LMX {state['lmx_temp_c']:.1f} C. Nothing will be changed.")
        with FieldFox(args.host) as ff:
            assert not ff.source_state(), "FieldFox source is ON - it must be off for a leakage soak"
            span = float(ff.query("SENS:FREQ:SPAN?"))
            center = float(ff.query("SENS:FREQ:CENT?"))
            ff.span_hz = span
            analyzer = {"span_hz": span, "center_hz": center, "attenuation_db": ff.attenuation_db, "rbw_hz": ff.rbw_hz,
                        "trace1_type": ff.query("TRAC1:TYPE?"), "ref_level_dbm": float(ff.query("DISP:WIND:TRAC:Y:RLEV?"))}
            print("FieldFox as found (not modified):", analyzer)
            if args.go_file:                                 # connect first, then wait for the operator's go (t = 0)
                if os.path.exists(args.go_file):
                    os.remove(args.go_file)
                print("READY - waiting for the go file", flush=True)
                while not os.path.exists(args.go_file):
                    time.sleep(0.05)
            rows = []
            event_t = None                                   # when the marker file appeared (e.g. "fan turned on now")
            t0 = time.monotonic()
            k = 0
            print(f"Soaking for {args.seconds:g} s, one reading per second ...")
            while True:
                t = time.monotonic() - t0
                if t > args.seconds:
                    break
                if args.marker_file and event_t is None and os.path.exists(args.marker_file):
                    event_t = t
                    print(f"  >>> marker file appeared at t = {t:.1f} s ({args.event_label})")
                ff.write("CALC:MARK1:FUNC:MAX")
                x = float(ff.query("CALC:MARK1:X?")); y = float(ff.query("CALC:MARK1:Y?")) - s21
                if abs(x - center) > 0.3 * span:                        # only if the tone nears the edge of the span
                    center = x
                    ff.tune(center)
                temp = board.get_lmx_temperature_c()
                lock = board.get_lmx_lock() if k % 10 == 0 else ""
                rows.append((t, y, temp, x - f_lo, lock))
                if k % 15 == 0:
                    print(f"  t {t:5.0f} s: LO leakage {y:+7.2f} dBm, LMX {temp:.1f} C {('(' + lock + ')') if lock else ''}")
                k += 1
                time.sleep(max(0.0, k * 1.0 - (time.monotonic() - t0)))
            end_state = {"lmx_lock": board.get_lmx_lock(), "i_v": board.get_i_v(), "q_v": board.get_q_v()}
    finally:
        board.close()

    with open(outdir / "soak.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "lo_leakage_dbm_at_board", "lmx_temp_c", "tone_offset_hz", "lmx_lock"])
        w.writerows([(f"{t:.2f}", f"{y:.2f}", f"{c:.1f}", f"{o:.0f}", lk) for t, y, c, o, lk in rows])
    t = np.array([r[0] for r in rows]); v = np.array([r[1] for r in rows]); c = np.array([r[2] for r in rows])
    (outdir / "result.json").write_text(json.dumps({"state_at_start": state, "analyzer_as_found": analyzer, "state_at_end": end_state,
                                                    "seconds": args.seconds, "n": len(rows), "event_label": args.event_label,
                                                    "event_t_s": event_t, "start_label": args.start_label}, indent=2, default=str))
    mean_db = 10 * np.log10(np.mean(10 ** (v / 10)))
    print(f"\nLO leakage: first {v[0]:+.2f}, last {v[-1]:+.2f}, min {v.min():+.2f}, max {v.max():+.2f} dBm, power-mean {mean_db:+.2f} dBm")
    print(f"LMX temperature: {c[0]:.1f} -> {c[-1]:.1f} C (min {c.min():.1f}, max {c.max():.1f}); end: LMX {end_state['lmx_lock']}, "
          f"I_V {end_state['i_v']:+.5f}, Q_V {end_state['q_v']:+.5f}")

    from plot_soak import plot_folder                      # one image: leakage on top, temperature below
    out = plot_folder(outdir)
    print("Saved", out)
    if not args.no_open:
        os.startfile(out)
        time.sleep(3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
