"""Small experiment for the big LO x IF map: at ONE LO, both IQ states, the full IF band in one
tracking-generator sweep per tone, timed, and checked against discrete single-tone measurements.

    python tracking_map.py [--lo-ghz 12] [--if-start-ghz 0.7] [--if-stop-ghz 4.0] [--step-mhz 10]

For each IQ state (THRU = upper sideband desired, SWAP = lower sideband desired) two sweeps:
    upper tone  RF = LO + IF : analyzer sweeps LO+IF_lo .. LO+IF_hi, source forwards  (offset -LO, reverse OFF)
    lower tone  RF = LO - IF : analyzer sweeps LO-IF_hi .. LO-IF_lo, source backwards (offset +LO, reverse ON)
at a constant -40 dBm drive, TX filter in bypass, the FieldFox at RBW 100 kHz with the input
attenuation held fixed. Every step is timed (LMX tune + lock, I/Q bias, IQ switch, and for each sweep:
configuration, acquisition, trace read) so the full 156-LO experiment can be extrapolated.

Then, outside the timed part, the same tones are measured the slow way (stepped CW, 1 MHz span) at 12 IF
values outside the earlier stepped runs' 1.6-2.4 GHz range, and everything is compared with the sweeps and
with the earlier stepped runs at this LO. Results: results/unit_<serial>/<run>/. The FieldFox source is always
switched off at the end (read back) and the board's configuration restored."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime

import numpy as np

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import DEFAULT_FIXED_ATTENUATION_DB, REF_FIXED_DBM, must
from fieldfox import SETTLE_S, FieldFox
from fr3_gui.lo_suppression import suggest_iv_qv
from plot_flatness_compare import flatness_runs, meta_of
from results_layout import unit_dir

DRIVE_DBM = -40.0
RBW_HZ = 100e3
SPOT_IFS_GHZ = [0.7, 0.8, 1.0, 1.2, 1.4, 1.5, 2.6, 2.8, 3.0, 3.4, 3.7, 4.0]   # outside 1.6-2.4 GHz


class Stopwatch:
    def __init__(self):
        self.t: dict[str, list[float]] = {}

    @contextmanager
    def __call__(self, name: str):
        t0 = time.monotonic()
        try:
            yield
        finally:
            self.t.setdefault(name, []).append(time.monotonic() - t0)

    def total(self, name: str) -> float:
        return float(sum(self.t.get(name, [])))


def tone_rf(f_lo: float, f_if, tone: str):
    return f_lo + f_if if tone == "upper" else f_lo - f_if


def tracking_sweep(ff, sw, cable_if, cable_rf, f_lo, if_lo, if_hi, points, tone, drive_dbm=DRIVE_DBM):
    """One sweep of one tone across the IF band. Returns (rf_hz, if_hz, trace_dbm, gain_db).
    drive_dbm is the source level the gain is referenced to; it must match what the caller set with SOUR:POW."""
    if tone == "upper":
        start, stop, offset, rev = f_lo + if_lo, f_lo + if_hi, -f_lo, "OFF"      # source = receiver + offset
    else:
        start, stop, offset, rev = f_lo - if_hi, f_lo - if_lo, +f_lo, "ON"       # source = offset - receiver
    with sw("sweep_configure"):
        ff.write(f"SENS:FREQ:STAR {start:.0f}")
        ff.write(f"SENS:FREQ:STOP {stop:.0f}")
        ff.write(f"SENS:SWE:POIN {points}")
        ff.write(f"SOUR:TOFF:FREQ {offset:.0f}")
        ff.write(f"SOUR:TOFF:REV {rev}")
        time.sleep(SETTLE_S)                     # the 100 ms rule after every retune
    with sw("sweep_acquire"):
        ff.wait_fresh_sweeps()  # continuous sweep (never INIT:CONT OFF / INIT:IMM)
    with sw("sweep_read"):
        trace = np.array([float(v) for v in ff.query("TRAC1:DATA?").split(",")])
    if trace.size != points:
        raise RuntimeError(f"trace has {trace.size} points, expected {points}")
    rf = np.linspace(start, stop, points)
    f_if = (rf - f_lo) if tone == "upper" else (f_lo - rf)
    gain = trace - cable_rf.s21_db_array(rf) - (drive_dbm + cable_if.s21_db_array(f_if))
    return rf, f_if, trace, gain


def stepped_reference(unit: int, f_lo: float):
    """Earlier stepped runs at this LO (IF 1.6-2.4 GHz): {(iq, tone): (rf, gain)}, first pass only."""
    ref: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
    for run in flatness_runs(unit):
        m = meta_of(run)
        if m["f_lo_hz"] != f_lo:
            continue
        side = m["args"]["sideband"]
        iq = "THRU" if side == "upper" else "SWAP"
        with open(run / "flatness.csv", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r["pass"] == "1"]
        g = np.array([float(r["gain_corrected_db"]) for r in rows])
        s = np.array([float(r["suppression_corrected_db"]) for r in rows])
        wanted_tone, image_tone = ("upper", "lower") if side == "upper" else ("lower", "upper")
        ref[(iq, wanted_tone)] = (np.array([float(r["rf_hz"]) for r in rows]), g)
        ref[(iq, image_tone)] = (np.array([float(r["image_hz"]) for r in rows]), g - s)
    return ref  # newest run per (iq, tone) wins (runs are sorted oldest first)


def compare(rf_sweep, gain_sweep, rf_pts, gain_pts):
    o = np.argsort(rf_sweep)
    inside = (rf_pts >= rf_sweep.min()) & (rf_pts <= rf_sweep.max())
    d = np.interp(rf_pts[inside], rf_sweep[o], gain_sweep[o]) - gain_pts[inside]
    return {"points": int(inside.sum()), "mean_db": float(d.mean()), "std_db": float(d.std()),
            "worst_db": float(np.abs(d).max())} if inside.any() else {"points": 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lo-ghz", type=float, default=12.0)
    parser.add_argument("--if-start-ghz", type=float, default=0.7)
    parser.add_argument("--if-stop-ghz", type=float, default=4.0)
    parser.add_argument("--step-mhz", type=float, default=10.0)
    parser.add_argument("--host", default="192.168.137.61")
    parser.add_argument("--port", default=None)
    parser.add_argument("--attenuation-db", type=float, default=20.0,
                        help="analyzer input attenuation, held fixed (lower = lower noise floor; default 20)")
    parser.add_argument("--ref-level-dbm", type=float, default=10.0, help="analyzer reference level (default +10)")
    parser.add_argument("--extra-points", default="1321,3301",
                        help="also sweep the THRU tones at these finer point counts (comma separated, '' = none)")
    args = parser.parse_args()

    f_lo = args.lo_ghz * 1e9
    if_lo, if_hi = args.if_start_ghz * 1e9, args.if_stop_ghz * 1e9
    points = int(round((if_hi - if_lo) / (args.step_mhz * 1e6))) + 1
    cable_if, cable_rf = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    for tone in ("upper", "lower"):
        cable_rf.s21_db_array(tone_rf(f_lo, np.array([if_lo, if_hi]), tone))
    cable_if.s21_db_array(np.array([if_lo, if_hi]))
    print(f"LO {args.lo_ghz:g} GHz, IF {if_lo/1e9:g}-{if_hi/1e9:g} GHz, {points} points per sweep, "
          f"{DRIVE_DBM:g} dBm drive.")

    sw = Stopwatch()
    meta = {"args": vars(args), "kind": "tracking_map", "f_lo_hz": f_lo, "points": points, "drive_dbm": DRIVE_DBM,
            "rbw_hz": RBW_HZ, "started": datetime.now().astimezone().isoformat(timespec="seconds")}
    sweeps: list[dict] = []
    spots: list[dict] = []
    fine: list[dict] = []
    previous = sorted(p for p in unit_dir(0).parent.glob("unit_*/*_tracking_map_lo*")
                      if p.is_dir() and (p / "sweeps.csv").exists())      # runs from before this one
    session = MeasurementSession(port=args.port)
    with session as board, FieldFox(args.host, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if serial == 0:
            raise RuntimeError("board serial is 0")
        outdir = unit_dir(serial) / f"{datetime.now():%Y%m%d_%H%M%S}_tracking_map_lo{args.lo_ghz:g}"
        outdir.mkdir(parents=True)
        meta["unit_serial"] = serial
        print(f"Unit #{serial}. Results: {outdir}")
        orig_points = None
        try:
            meta["ff_idn"] = ff.identify()
            ff.setup_spectrum_analyzer(ref_level_dbm=args.ref_level_dbm)
            orig_points = ff.points
            ff.source_enable(False)
            ff.set_attenuation(args.attenuation_db)
            meta.update(attenuation_db=args.attenuation_db, ref_level_dbm=args.ref_level_dbm)
            ff.write(f"SENS:BAND:RES {RBW_HZ:.0f}")
            ff.write("FORM:DATA ASCii,0")
            ff.write(f"SOUR:POW {DRIVE_DBM:.2f}")
            ff.write("SOUR:TRAC TSWP")
            ff.write("SOUR:TOFF:ENAB ON")
            errs = ff.errors()
            if errs:
                raise RuntimeError(f"FieldFox rejected the tracking setup: {errs}")

            # ------------------------- the timed experiment -------------------------
            t_experiment = time.monotonic()
            with sw("static_setup"):
                must(board.set_clock_internal(True), "SET CLOCK INT")
                must(board.set_lo_internal(True), "SET LO INT")
                must(board.set_lmx_power(7), "LMX PWR 7")
                must(board.set_tx_filter(0x00), "SET TXFILTER 0x00")
            # First tune from wherever the LMX was, then two more warm retunes; the last lands on the LO.
            for f in (f_lo + 0.1e9, f_lo - 0.1e9, f_lo):
                with sw("lmx_tune_and_lock"):
                    must(board.lmx_tune(f), f"LMX TUNE {f:.0f}")
                    for _ in range(40):
                        if board.get_lmx_lock() == "LOCKED":
                            break
                        time.sleep(0.05)
                    else:
                        raise RuntimeError("LMX not locked")
            with sw("iq_bias"):
                iv = suggest_iv_qv(f_lo / 1e9)
                must(iv is not None, "no LO-null table entry")
                must(board.set_i_v(iv[0]), "SET I_V")
                must(board.set_q_v(iv[1]), "SET Q_V")
            meta["board_state_during"] = {"lmx_lock": board.get_lmx_lock(),
                                          "lmx_temperature_c": board.get_lmx_temperature_c()}

            ff.source_enable(True)
            time.sleep(SETTLE_S)
            for iq, swap in (("THRU", False), ("SWAP", True)):
                with sw("iq_switch"):
                    must(board.set_iq_swap(swap), f"SET IQ {iq}")
                    time.sleep(SETTLE_S)
                for tone in ("upper", "lower"):
                    rf, f_if, trace, gain = tracking_sweep(ff, sw, cable_if, cable_rf, f_lo, if_lo, if_hi, points, tone)
                    sweeps.append({"iq": iq, "tone": tone, "rf": rf, "if": f_if, "trace": trace, "gain": gain})
                    print(f"  IQ {iq}, {tone} tone: RF {rf.min()/1e9:.2f}-{rf.max()/1e9:.2f} GHz, gain "
                          f"{gain.min():+.1f} to {gain.max():+.1f} dB (median trace {np.median(trace):+.1f} dBm)")
            t_experiment = time.monotonic() - t_experiment

            # Finer point counts for the THRU tones (not part of the timed experiment): how does sweep
            # time scale with points, and does a finer grid show structure the 331-point sweep misses?
            with sw("iq_switch_untimed"):
                must(board.set_iq_swap(False), "SET IQ THRU")
                time.sleep(SETTLE_S)
            for n_str in [x for x in args.extra_points.split(",") if x.strip()]:
                n = int(n_str)
                for tone in ("upper", "lower"):
                    local = Stopwatch()
                    rf, f_if, trace, gain = tracking_sweep(ff, local, cable_if, cable_rf, f_lo, if_lo, if_hi, n, tone)
                    fine.append({"points": n, "tone": tone, "rf": rf, "if": f_if, "trace": trace, "gain": gain,
                                 "acquire_s": local.total("sweep_acquire"), "read_s": local.total("sweep_read")})
                    print(f"  fine sweep, THRU {tone} tone, {n} points ({(if_hi - if_lo) / (n - 1) / 1e6:.2f} MHz): "
                          f"acquire {local.total('sweep_acquire'):.2f} s, read {local.total('sweep_read'):.2f} s")
            ff.source_enable(False)

            # noise floor of the sweep (source off), for flagging weak points; not part of the timed experiment
            rf0, _, floor_trace, _ = tracking_sweep(ff, Stopwatch(), cable_if, cable_rf, f_lo, if_lo, if_hi, points, "upper")
            floor_dbm = float(np.percentile(floor_trace, 99))
            meta["noise_floor_dbm_p99"] = floor_dbm

            # ------------------------- discrete measurements (not timed) -------------------------
            print("\nDiscrete single-tone measurements (stepped CW) at IF values outside the earlier runs' range:")
            for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF", "SENS:BAND:RES:AUTO ON"):
                ff.write(c)
            ff.write(f"SENS:SWE:POIN {orig_points}")
            ff.write("SENS:FREQ:SPAN 1000000")
            ff.source_enable(True)
            for iq, swap in (("THRU", False), ("SWAP", True)):
                must(board.set_iq_swap(swap), f"SET IQ {iq}")
                time.sleep(SETTLE_S)
                off = {"upper": 0.0, "lower": 0.0}
                for g_if in SPOT_IFS_GHZ:
                    f_if_hz = g_if * 1e9
                    ff.source_configure(f_if_hz, DRIVE_DBM)
                    time.sleep(SETTLE_S)
                    for tone in ("upper", "lower"):
                        rf_hz = float(tone_rf(f_lo, f_if_hz, tone))
                        r = ff.measure_at(rf_hz + off[tone])
                        off[tone] = r.freq_hz - rf_hz
                        gain = (r.power_dbm - cable_rf.s21_db(rf_hz)) - (DRIVE_DBM + cable_if.s21_db(f_if_hz))
                        spots.append({"iq": iq, "tone": tone, "if_hz": f_if_hz, "rf_hz": rf_hz,
                                      "measured_dbm": r.power_dbm, "gain_db": gain})
                print(f"  IQ {iq}: {len(SPOT_IFS_GHZ) * 2} tones measured")
            meta["timing"] = {k: {"n": len(v), "total_s": round(sum(v), 3), "mean_s": round(float(np.mean(v)), 3)}
                              for k, v in sw.t.items()}
            meta["experiment_seconds"] = t_experiment
        finally:
            ff.source_enable(False)
            for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF", "SENS:BAND:RES:AUTO ON"):
                ff.write(c)
            if orig_points is not None:
                ff.write(f"SENS:SWE:POIN {orig_points}")
            ff.write("SENS:FREQ:SPAN 1000000")
            ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            meta["ff_source_verified_off"] = not ff.source_state()
            meta["errors_at_end"] = ff.errors()
            print("\nFieldFox source " + ("confirmed OFF (read back), tracking turned off."
                                          if meta["ff_source_verified_off"] else "*** STILL ON - switch it off! ***"))
            if sweeps:
                with open(outdir / "sweeps.csv", "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["iq", "tone", "if_hz", "rf_hz", "trace_dbm", "gain_db", "near_noise_floor"])
                    for s in sweeps:
                        fl = meta.get("noise_floor_dbm_p99", -1e9)
                        for x in zip(s["if"], s["rf"], s["trace"], s["gain"]):
                            w.writerow([s["iq"], s["tone"], f"{x[0]:.0f}", f"{x[1]:.0f}", f"{x[2]:.3f}", f"{x[3]:.3f}",
                                        int(x[2] < fl + 10)])
            if spots:
                with open(outdir / "spot_checks.csv", "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=list(spots[0]))
                    w.writeheader()
                    w.writerows(spots)

    # ------------------------- comparison and timing summary (board restored) -------------------------
    ref = stepped_reference(serial, f_lo)
    comp: dict[str, dict] = {}
    for s in sweeps:
        key = (s["iq"], s["tone"])
        entry = {}
        if key in ref:
            entry["earlier_stepped_runs_1.6_to_2.4GHz"] = compare(s["rf"], s["gain"], *ref[key])
        pts = [p for p in spots if (p["iq"], p["tone"]) == key]
        if pts:
            entry["new_spot_checks_outside_1.6_to_2.4GHz"] = compare(
                s["rf"], s["gain"], np.array([p["rf_hz"] for p in pts]), np.array([p["gain_db"] for p in pts]))
        comp[f"{key[0]}_{key[1]}"] = entry
    meta["comparison"] = comp

    # ---- checks for the new analyzer settings and the finer grids ----
    checks: dict = {"noise_floor_dbm_p99": meta.get("noise_floor_dbm_p99")}
    if previous:
        prev = previous[-1]
        pm = json.loads((prev / "metadata.json").read_text())
        checks.update(previous_run=prev.name, previous_noise_floor_dbm_p99=pm.get("noise_floor_dbm_p99"),
                      previous_attenuation_db=pm.get("attenuation_db", 35.0))
        prev_sw: dict[tuple[str, str], list] = {}
        with open(prev / "sweeps.csv", newline="") as f:
            for r in csv.DictReader(f):
                prev_sw.setdefault((r["iq"], r["tone"]), []).append((float(r["if_hz"]), float(r["gain_db"]), int(r["near_noise_floor"])))
        for s in sweeps:
            p = np.array(prev_sw.get((s["iq"], s["tone"]), []))
            if p.size and p.shape[0] == s["gain"].size and np.allclose(p[:, 0], s["if"]):
                strong = (p[:, 2] == 0) & (s["gain"] > 25.0)          # far above either run's noise floor
                d = (s["gain"] - p[:, 1])[strong]
                checks[f"vs_previous_{s['iq']}_{s['tone']}"] = {"points": int(strong.sum()), "mean_db": float(d.mean()),
                                                               "std_db": float(d.std()), "worst_db": float(np.abs(d).max())}
    coarse = {(s["iq"], s["tone"]): s for s in sweeps}
    fine_checks = []
    for tone in ("upper", "lower"):
        prev_grid = coarse[("THRU", tone)]
        for fs in sorted((x for x in fine if x["tone"] == tone), key=lambda x: x["points"]):
            o = np.argsort(prev_grid["rf"])
            resid = fs["gain"] - np.interp(fs["rf"], prev_grid["rf"][o], prev_grid["gain"][o])
            fine_checks.append({"tone": tone, "points": fs["points"], "acquire_s": round(fs["acquire_s"], 3),
                                "read_s": round(fs["read_s"], 3), "vs_previous_grid_rms_db": float(np.sqrt(np.mean(resid ** 2))),
                                "vs_previous_grid_worst_db": float(np.abs(resid).max())})
            prev_grid = fs
    checks["fine_grids"] = fine_checks
    meta["checks"] = checks
    if fine:
        with open(outdir / "sweeps_fine.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["points", "tone", "if_hz", "rf_hz", "trace_dbm", "gain_db"])
            for fs in fine:
                for x in zip(fs["if"], fs["rf"], fs["trace"], fs["gain"]):
                    w.writerow([fs["points"], fs["tone"], f"{x[0]:.0f}", f"{x[1]:.0f}", f"{x[2]:.3f}", f"{x[3]:.3f}"])
    (outdir / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))

    print(f"\nAnalyzer settings this run: input attenuation {args.attenuation_db:g} dB, reference level "
          f"{args.ref_level_dbm:+g} dBm, RBW {RBW_HZ / 1e3:g} kHz")
    if previous:
        print(f"  Noise floor (99th percentile of a source-off sweep): {checks['noise_floor_dbm_p99']:.1f} dBm now vs "
              f"{checks['previous_noise_floor_dbm_p99']:.1f} dBm before (attenuation {checks['previous_attenuation_db']:g} dB)")
        print("  Same strong points, this run minus the previous run (a change here would mean the analyzer is compressing):")
        for k, v in checks.items():
            if k.startswith("vs_previous_"):
                print(f"    {k[12:]:12s} n={v['points']:3d}  mean {v['mean_db']:+.2f}  std {v['std_db']:.2f}  worst {v['worst_db']:.2f} dB")
    if fine_checks:
        print("  Finer grids (THRU tones): acquisition time, and difference from the next-coarser sweep:")
        print(f"    coarse 331 points: acquire {T_ACQ_331:.2f} s" if (T_ACQ_331 := sw.total('sweep_acquire') / 4) else "")
        for c in fine_checks:
            print(f"    {c['tone']:5s} {c['points']:5d} points: acquire {c['acquire_s']:.2f} s + read {c['read_s']:.2f} s;  "
                  f"vs the coarser grid: rms {c['vs_previous_grid_rms_db']:.2f} dB, worst {c['vs_previous_grid_worst_db']:.2f} dB")

    print("\nSweep vs. discrete tones (tracking minus discrete, dB):")
    for name, e in comp.items():
        for label, c in e.items():
            if c.get("points"):
                print(f"  {name:11s} {label:42s} n={c['points']:3d}  mean {c['mean_db']:+.2f}  std {c['std_db']:.2f}  worst {c['worst_db']:.2f}")
    T = meta["timing"]
    print("\nTIMING")
    print(f"  Static setup (clock, LO source, LMX power, filter):   {T['static_setup']['total_s']:.2f} s")
    tunes = sw.t["lmx_tune_and_lock"]
    print(f"  LMX tune + lock:  first (from 13 GHz) {tunes[0]:.2f} s;  warm retunes {tunes[1]:.2f} s and {tunes[2]:.2f} s")
    print(f"  I/Q bias (2 SPI writes):                              {T['iq_bias']['total_s']:.2f} s")
    print(f"  IQ switch (each):                                     {T['iq_switch']['mean_s']:.2f} s")
    print(f"  Per sweep ({points} points): configure {T['sweep_configure']['mean_s']:.2f} s + acquire "
          f"{T['sweep_acquire']['mean_s']:.2f} s + read {T['sweep_read']['mean_s']:.2f} s = "
          f"{T['sweep_configure']['mean_s'] + T['sweep_acquire']['mean_s'] + T['sweep_read']['mean_s']:.2f} s")
    print(f"  WHOLE EXPERIMENT (LO tuning through the 4th sweep):   {meta['experiment_seconds']:.1f} s")
    warm = float(np.mean(tunes[1:]))
    per_sweep = T['sweep_configure']['mean_s'] + T['sweep_acquire']['mean_s'] + T['sweep_read']['mean_s']
    per_lo = warm + T['iq_bias']['total_s'] + 2 * T['iq_switch']['mean_s'] + 4 * per_sweep
    print(f"  Extrapolated per LO (warm tune + bias + 2 IQ switches + 4 sweeps): {per_lo:.2f} s")
    print(f"  Extrapolated 156 LOs: {156 * per_lo / 60:.1f} minutes")
    print(f"Saved {outdir}")
    print("Board configuration restored, flash persistence back ON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
