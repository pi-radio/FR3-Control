"""The LO x IF map: for every LO in a range, both IQ states, and both tones, one tracking-generator sweep
across the whole IF band. Saved incrementally (one CSV per LO) so a run can be split into chunks and resumed.

    python lo_map.py --campaign NAME [--lo-start-ghz 7.0] [--lo-stop-ghz 22.5] [--lo-step-ghz 0.1]
                     [--if-start-ghz 0.7] [--if-stop-ghz 4.0] [--step-mhz 10]

Per LO: tune the LMX and wait for lock, set the I/Q bias from the shipped LO-null table, then for
IQ THRU and IQ SWAP the two sweeps
    upper tone  RF = LO + IF  (source forwards:  offset -LO, reverse OFF)
    lower tone  RF = LO - IF  (source backwards: offset +LO, reverse ON)
at a constant drive (-40 dBm), TX filter in bypass, FieldFox RBW 100 kHz, attenuation 20 dB, reference level
+10 dBm (all held fixed). Desired = upper for THRU / lower for SWAP; the other tone is the undesired image.

Data: results/unit_<serial>/<campaign>/lo_<GHz>.csv (columns iq, tone, if_hz, rf_hz, trace_dbm, gain_db),
lo_index.csv (per-LO timing, LMX temperature, I/Q bias, errors), monitor.csv (a reference tone at LO 12 GHz
re-measured every N LOs to expose drift), campaign.json. Existing LO files are skipped, so re-running the same
command resumes. The FieldFox source is always switched off at the end (read back) and the board's
configuration restored."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime

import numpy as np

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must
from fieldfox import SETTLE_S, FieldFox
from fr3_gui.lo_suppression import suggest_iv_qv
from results_layout import unit_dir
from tracking_map import RBW_HZ, Stopwatch, tracking_sweep

MONITOR_LO_HZ = 12_000_000_000


def tune_and_lock(board, f_lo: int) -> float:
    """Tune the LMX (one retry) and confirm lock; returns seconds spent."""
    t0 = time.monotonic()
    for attempt in range(2):
        if board.lmx_tune(float(f_lo)):
            for _ in range(60):
                if board.get_lmx_lock() == "LOCKED":
                    return time.monotonic() - t0
                time.sleep(0.05)
        time.sleep(0.3)
    raise RuntimeError(f"LMX would not lock at {f_lo / 1e9:g} GHz")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True, help="folder name under the unit's results folder")
    parser.add_argument("--lo-start-ghz", type=float, default=7.0)
    parser.add_argument("--lo-stop-ghz", type=float, default=22.5)
    parser.add_argument("--lo-step-ghz", type=float, default=0.1)
    parser.add_argument("--if-start-ghz", type=float, default=0.7)
    parser.add_argument("--if-stop-ghz", type=float, default=4.0)
    parser.add_argument("--step-mhz", type=float, default=10.0)
    parser.add_argument("--drive-dbm", type=float, default=-40.0)
    parser.add_argument("--attenuation-db", type=float, default=20.0)
    parser.add_argument("--ref-level-dbm", type=float, default=10.0)
    parser.add_argument("--monitor-every", type=int, default=20, help="re-measure a reference tone every N LOs")
    parser.add_argument("--host", default="192.168.137.61")
    parser.add_argument("--port", default=None)
    args = parser.parse_args()

    step_lo = int(round(args.lo_step_ghz * 1e9))
    lo_list = list(range(int(round(args.lo_start_ghz * 1e9)), int(round(args.lo_stop_ghz * 1e9)) + 1, step_lo))
    if_lo, if_hi = args.if_start_ghz * 1e9, args.if_stop_ghz * 1e9
    points = int(round((if_hi - if_lo) / (args.step_mhz * 1e6))) + 1
    cable_if, cable_rf = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    cable_if.s21_db_array(np.array([if_lo, if_hi]))
    cable_rf.s21_db_array(np.array([lo_list[0] - if_hi, lo_list[-1] + if_hi]))     # raise now if out of range
    settings = {"if_start_hz": if_lo, "if_stop_hz": if_hi, "points": points, "drive_dbm": args.drive_dbm,
                "attenuation_db": args.attenuation_db, "ref_level_dbm": args.ref_level_dbm, "rbw_hz": RBW_HZ,
                "lo_step_hz": step_lo, "tx_filter": "bypass (0x00)"}

    session = MeasurementSession(port=args.port)
    with session as board, FieldFox(args.host, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if serial == 0:
            raise RuntimeError("board serial is 0")
        outdir = unit_dir(serial) / args.campaign
        outdir.mkdir(parents=True, exist_ok=True)
        cj = outdir / "campaign.json"
        if cj.exists():
            old = json.loads(cj.read_text())["settings"]
            if old != settings:
                raise RuntimeError(f"campaign {args.campaign} exists with different settings: {old} vs {settings}")
        else:
            cj.write_text(json.dumps({"settings": settings, "unit_serial": serial,
                                      "created": datetime.now().astimezone().isoformat(timespec="seconds")}, indent=2))
        todo = [lo for lo in lo_list if not (outdir / f"lo_{lo / 1e9:06.2f}GHz.csv").exists()]
        print(f"Unit #{serial}, campaign {args.campaign}: {len(lo_list)} LOs in range, {len(todo)} still to do "
              f"({points} points per sweep). {outdir}")
        idx_path, mon_path = outdir / "lo_index.csv", outdir / "monitor.csv"
        failures = 0
        t_start = time.monotonic()
        orig_points = None
        try:
            ff.setup_spectrum_analyzer(ref_level_dbm=args.ref_level_dbm)
            orig_points = ff.points
            ff.source_enable(False)
            ff.set_attenuation(args.attenuation_db)
            ff.write(f"SENS:BAND:RES {RBW_HZ:.0f}")
            ff.write("FORM:DATA ASCii,0")
            ff.write(f"SOUR:POW {args.drive_dbm:.2f}")
            ff.write("SOUR:TRAC TSWP")
            ff.write("SOUR:TOFF:ENAB ON")
            errs = ff.errors()
            if errs:
                raise RuntimeError(f"FieldFox rejected the tracking setup: {errs}")
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            must(board.set_lmx_power(7), "LMX PWR 7")
            must(board.set_tx_filter(0x00), "SET TXFILTER bypass")

            # noise floor of this chunk (source off), at the first LO
            if todo:
                tune_and_lock(board, todo[0])
                must(board.set_iq_swap(False), "SET IQ THRU")
                _, _, ftrace, _ = tracking_sweep(ff, Stopwatch(), cable_if, cable_rf, todo[0], if_lo, if_hi, points, "upper")
                floor = float(np.percentile(ftrace, 99))
                print(f"Noise floor of this chunk (source off, 99th percentile): {floor:.1f} dBm")
            else:
                floor = float("nan")
            ff.source_enable(True)
            time.sleep(SETTLE_S)

            for k, f_lo in enumerate(todo):
                if k % args.monitor_every == 0 and k > 0 or k == 0:      # drift monitor: fixed reference LO/tone
                    tune_and_lock(board, MONITOR_LO_HZ)
                    iv = suggest_iv_qv(MONITOR_LO_HZ / 1e9)
                    board.set_i_v(iv[0]); board.set_q_v(iv[1]); board.set_iq_swap(False); time.sleep(SETTLE_S)
                    rf, f_if, trace, gain = tracking_sweep(ff, Stopwatch(), cable_if, cable_rf, MONITOR_LO_HZ, if_lo, if_hi,
                                                           points, "upper", args.drive_dbm)
                    i2 = int(np.argmin(abs(f_if - 2e9)))
                    new = not mon_path.exists()
                    with open(mon_path, "a", newline="") as f:
                        w = csv.writer(f)
                        if new:
                            w.writerow(["time", "before_lo_hz", "trace_dbm_at_if_2ghz", "gain_db_at_if_2ghz", "lmx_temp_c"])
                        w.writerow([datetime.now().astimezone().isoformat(timespec="seconds"), f_lo, f"{trace[i2]:.3f}",
                                    f"{gain[i2]:.3f}", f"{board.get_lmx_temperature_c():.1f}"])
                sw = Stopwatch()
                t_lo = time.monotonic()
                status = "ok"
                try:
                    with sw("tune"):
                        t_tune = tune_and_lock(board, f_lo)
                    iv = suggest_iv_qv(f_lo / 1e9)
                    if iv is None:
                        raise RuntimeError("no LO-null table entry")
                    must(board.set_i_v(iv[0]), "SET I_V")
                    must(board.set_q_v(iv[1]), "SET Q_V")
                    temp0 = board.get_lmx_temperature_c()
                    rows = []
                    for iq, swap in (("THRU", False), ("SWAP", True)):
                        must(board.set_iq_swap(swap), f"SET IQ {iq}")
                        time.sleep(SETTLE_S)
                        for tone in ("upper", "lower"):
                            rf, f_if, trace, gain = tracking_sweep(ff, sw, cable_if, cable_rf, float(f_lo), if_lo, if_hi,
                                                                   points, tone, args.drive_dbm)
                            rows += [(iq, tone, a, b, c, d) for a, b, c, d in zip(f_if, rf, trace, gain)]
                    lock_after = board.get_lmx_lock()
                    ff_errs = ff.errors()
                    if lock_after != "LOCKED":
                        status = f"lock lost ({lock_after})"
                    if ff_errs:
                        status += f"; FieldFox errors {ff_errs}"
                    with open(outdir / f"lo_{f_lo / 1e9:06.2f}GHz.csv", "w", newline="") as f:
                        w = csv.writer(f)
                        w.writerow(["iq", "tone", "if_hz", "rf_hz", "trace_dbm", "gain_db"])
                        for r in rows:
                            w.writerow([r[0], r[1], f"{r[2]:.0f}", f"{r[3]:.0f}", f"{r[4]:.3f}", f"{r[5]:.3f}"])
                    failures = 0
                except Exception as err:  # noqa: BLE001 - log, keep going, stop only if it keeps happening
                    failures += 1
                    status = f"FAILED: {err}"
                    t_tune, temp0, iv = float("nan"), float("nan"), (float("nan"), float("nan"))
                    lock_after = "?"
                    print(f"  LO {f_lo / 1e9:.2f} GHz {status}")
                    ff.errors()
                new = not idx_path.exists()
                with open(idx_path, "a", newline="") as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(["lo_hz", "status", "tune_s", "total_s", "lmx_temp_c_before", "lmx_lock_after",
                                    "i_v", "q_v", "noise_floor_dbm_chunk", "time"])
                    w.writerow([f_lo, status, f"{t_tune:.3f}", f"{time.monotonic() - t_lo:.3f}", f"{temp0:.1f}",
                                lock_after, f"{iv[0]:.4f}", f"{iv[1]:.4f}", f"{floor:.1f}",
                                datetime.now().astimezone().isoformat(timespec="seconds")])
                if k % 10 == 0 or k == len(todo) - 1 or status != "ok":
                    print(f"  LO {f_lo / 1e9:6.2f} GHz  [{k + 1}/{len(todo)}]  {status}  LMX {temp0:.1f} C  "
                          f"{time.monotonic() - t_lo:.2f} s  (elapsed {time.monotonic() - t_start:.0f} s)")
                if failures >= 3:
                    print("Three consecutive failures - stopping this chunk safely.")
                    break
        finally:
            ff.source_enable(False)
            for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF", "SENS:BAND:RES:AUTO ON"):
                ff.write(c)
            if orig_points is not None:
                ff.write(f"SENS:SWE:POIN {orig_points}")
            ff.write("SENS:FREQ:SPAN 1000000")
            ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            print("FieldFox source " + ("confirmed OFF (read back), tracking turned off."
                                        if not ff.source_state() else "*** STILL ON - switch it off! ***"))
    print(f"Chunk finished in {time.monotonic() - t_start:.0f} s. Board configuration restored, flash persistence back ON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
