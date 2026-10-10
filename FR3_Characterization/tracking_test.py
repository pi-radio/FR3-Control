"""Can the FieldFox's tracking generator (source follows the analyzer's sweep, with a
frequency offset) replace stepping a tone one frequency at a time?

Test, on the real board (LO 12 GHz, upper sideband, filters in bypass, -40 dBm):
  A. Desired sideband: analyzer sweeps RF 13.75-14.25 GHz; the source should follow at
     RF - 12 GHz = IF 1.75-2.25 GHz (offset 12 GHz).
  B. Undesired (image) sideband: analyzer sweeps RF 9.75-10.25 GHz; the source should run
     BACKWARDS, at 12 GHz - RF = IF 2.25-1.75 GHz (offset 12 GHz, reversed).
Each sweep is read as one full trace (a measurement that genuinely needs the whole span),
converted to conversion gain with the same cable corrections as the stepped measurements, and
compared point by point with the newest stepped-tone flatness run at LO 12 GHz. The offset
commands' sign convention is not documented, so the comparison itself tells us whether the
setup did what we intended (a wrong mapping shows up as a trace at the noise floor).

Result (FieldFox N9918B, firmware A.13.25, unit 5, LO 12 GHz): both sweeps match the stepped tones
to a few hundredths of a dB (mean difference <= 0.01 dB, worst point 0.14 dB) in ~0.15 s per 201-point
sweep. Offset conventions found on the instrument (undocumented):
    reverse OFF: source = receiver + offset   -> upper sideband needs a NEGATIVE offset (-LO)
    reverse ON : source = offset - receiver   -> lower/image sideband: offset +LO, reverse ON
(the documented range of SOURce:TOFFset:FREQuency is 1 Hz and up, but a negative value is accepted).

    python tracking_test.py [--points 201] [--rbw-khz 100]

Commands used (Keysight FieldFox SCPI help): SOURce:TRACking <OFF|TCF|TPG|TSWP>,
SOURce:TOFFset:ENABle / :FREQuency / :REVerse, SOURce:POWer, SOURce:ENABle, TRACe1:DATA?.
The source is always switched off and tracking turned off again at the end (read back)."""

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
from conversion_gain_small_case import DEFAULT_FIXED_ATTENUATION_DB, REF_FIXED_DBM, configure_board
from fieldfox import SETTLE_S, FieldFox
from plot_flatness_compare import flatness_runs, meta_of
from results_layout import unit_dir

LO_HZ = 12e9
DRIVE_DBM = -40.0
IF_BAND = (1.75e9, 2.25e9)          # IF 2 GHz center, 500 MHz bandwidth


def stepped_reference(unit: int):
    """Newest stepped LO-12-GHz upper-sideband flatness run: (rf, wanted gain) and (image rf, image gain)."""
    runs = [r for r in flatness_runs(unit)
            if meta_of(r)["f_lo_hz"] == LO_HZ and meta_of(r)["args"]["sideband"] == "upper"]
    if not runs:
        sys.exit("no stepped LO-12-GHz upper-sideband flatness run to compare against - run gain_flatness.py first")
    run = runs[-1]
    with open(run / "flatness.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["pass"] == "1"]
    rf_w = np.array([float(r["rf_hz"]) for r in rows])
    g_w = np.array([float(r["gain_corrected_db"]) for r in rows])
    rf_i = np.array([float(r["image_hz"]) for r in rows])
    g_i = g_w - np.array([float(r["suppression_corrected_db"]) for r in rows])
    o, oi = np.argsort(rf_w), np.argsort(rf_i)
    return run, (rf_w[o], g_w[o]), (rf_i[oi], g_i[oi])


def try_commands(ff, label: str, commands: list[str]) -> list[str]:
    for c in commands:
        ff.write(c)
    errs = ff.errors()
    print(f"  {label}: " + ("ok" if not errs else f"REJECTED -> {errs}"))
    return errs


def sweep(ff, cable_if, cable_rf, start_hz: float, stop_hz: float, points: int, offset_hz: float,
          rev_on: bool, source_backwards: bool):
    """One tracking sweep with the given offset / reverse setting. `source_backwards` says where the
    source SHOULD be for the cable correction (IF = LO - RF, else RF - LO); the comparison with the
    stepped data then tells whether the setting really produced that. Returns
    (rf_hz, measured_dbm, gain_db, seconds)."""
    ff.write(f"SENS:FREQ:STAR {start_hz:.0f}")
    ff.write(f"SENS:FREQ:STOP {stop_hz:.0f}")
    ff.write(f"SENS:SWE:POIN {points}")
    ff.write(f"SOUR:TOFF:FREQ {offset_hz:.0f}")
    ff.write(f"SOUR:TOFF:REV {'ON' if rev_on else 'OFF'}")
    time.sleep(SETTLE_S)
    t0 = time.monotonic()
    ff.wait_fresh_sweeps()  # continuous sweep (never INIT:CONT OFF / INIT:IMM)
    seconds = time.monotonic() - t0
    trace = np.array([float(v) for v in ff.query("TRAC1:DATA?").split(",")])
    if trace.size != points:
        raise RuntimeError(f"trace has {trace.size} points, expected {points}")
    rf = np.linspace(start_hz, stop_hz, points)
    f_if = (LO_HZ - rf) if source_backwards else (rf - LO_HZ)   # where the source should be
    p_in = DRIVE_DBM + np.array([cable_if.s21_db(x) for x in f_if])
    p_out = trace - np.array([cable_rf.s21_db(x) for x in rf])
    return rf, trace, p_out - p_in, seconds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--points", type=int, default=201, help="sweep points (201 over 500 MHz = 2.5 MHz spacing)")
    parser.add_argument("--rbw-khz", type=float, default=100.0)
    parser.add_argument("--host", default="192.168.137.61")
    parser.add_argument("--port", default=None)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1, help="sweeps taken and discarded before the counted ones")
    args = parser.parse_args()

    cable_if, cable_rf = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    meta = {"args": vars(args), "kind": "tracking_generator_test", "f_lo_hz": LO_HZ, "drive_dbm": DRIVE_DBM,
            "started": datetime.now().astimezone().isoformat(timespec="seconds")}
    results: dict[str, dict] = {}
    session = MeasurementSession(port=args.port)
    with session as board, FieldFox(args.host, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if serial == 0:
            raise RuntimeError("board serial is 0")
        ref_run, (rf_w, g_w), (rf_i, g_i) = stepped_reference(serial)
        outdir = unit_dir(serial) / f"{datetime.now():%Y%m%d_%H%M%S}_tracking_test_lo12_upper"
        outdir.mkdir(parents=True)
        meta.update(unit_serial=serial, stepped_reference_run=ref_run.name)
        print(f"Unit #{serial}. Comparing with the stepped run {ref_run.name[:15]}. Results: {outdir}")
        orig_points = None
        try:
            meta["ff_idn"] = ff.identify()
            ff.setup_spectrum_analyzer(ref_level_dbm=REF_FIXED_DBM)
            orig_points = ff.points   # restored afterwards: later CW measurements expect the normal sweep
            ff.source_enable(False)
            ff.set_attenuation(DEFAULT_FIXED_ATTENUATION_DB)
            configure_board(board, LO_HZ, "upper")
            print("Board: LO 12 GHz locked, upper sideband (IQ THRU), TX filter bypass.\n")

            print("Tracking-generator state before any change (read-only):")
            for q in ("SOUR:TRAC?", "SOUR:TOFF:ENAB?", "SOUR:TOFF:FREQ?", "SOUR:TOFF:REV?"):
                try:
                    print(f"  {q:16s} -> {ff.query(q)}")
                except Exception as e:  # noqa: BLE001
                    print(f"  {q:16s} -> no answer ({e})")
            print("  errors:", ff.errors())

            print("\nConfiguring tracking with a 12 GHz offset:")
            ff.write(f"SENS:BAND:RES {args.rbw_khz * 1e3:.0f}")
            ff.write("FORM:DATA ASCii,0")
            ff.write(f"SOUR:POW {DRIVE_DBM:.2f}")
            errs = try_commands(ff, "tracking = TSWP (source follows the analyzer's sweep)", ["SOUR:TRAC TSWP"])
            if errs:
                errs = try_commands(ff, "fallback: SOUR:MODE SRTS", ["SOUR:MODE SRTS"])
            errs = errs or try_commands(ff, "offset frequency 12 GHz", [f"SOUR:TOFF:FREQ {LO_HZ:.0f}"])
            errs = errs or try_commands(ff, "offset enabled", ["SOUR:TOFF:ENAB ON"])
            meta["configuration_errors"] = errs
            if errs:
                print("\nThe FieldFox rejected the tracking-offset setup, so this method is NOT available in SA mode "
                      "on this instrument/firmware. Nothing else was tried.")
            else:
                meta["readback"] = {q: ff.query(q) for q in ("SOUR:TRAC?", "SOUR:TOFF:ENAB?", "SOUR:TOFF:FREQ?")}
                print("  read back:", meta["readback"])
                ff.source_enable(True)
                time.sleep(SETTLE_S)
                # (offset, reverse-switch) settings to try, in order, for a source that must run
                # FORWARDS (desired: IF = RF - LO) or BACKWARDS (image: IF = LO - RF). The FieldFox's
                # offset sign convention is not documented: the first setting whose result matches the
                # stepped data (mean gain within 3 dB) is the one used.
                for name, (a, b), backwards, tries, (rr, gg) in (
                        ("desired", (LO_HZ + IF_BAND[0], LO_HZ + IF_BAND[1]), False,
                         [(+LO_HZ, False), (-LO_HZ, False)], (rf_w, g_w)),
                        ("image", (LO_HZ - IF_BAND[1], LO_HZ - IF_BAND[0]), True,
                         [(+LO_HZ, True)], (rf_i, g_i))):
                    print(f"\n{name} sideband: analyzer sweeps {a/1e9:.2f}-{b/1e9:.2f} GHz, "
                          f"source should run {'backwards' if backwards else 'forwards'}")
                    attempts, sweeps, worked = [], [], None
                    for offset, rev_on in tries:
                        label = f"offset {offset/1e9:+g} GHz, reverse {'ON' if rev_on else 'OFF'}"
                        print(f"  trying {label}")
                        sweeps, ok = [], True
                        for k in range(args.warmup + args.repeats):
                            rf, trace, gain, secs = sweep(ff, cable_if, cable_rf, a, b, args.points, offset,
                                                          rev_on, backwards)
                            ref_k = np.interp(rf, rr, gg)
                            tag = "warm-up (discarded)" if k < args.warmup else f"repeat {k - args.warmup + 1}"
                            print(f"    {tag}: {secs:.2f} s, median level {np.median(trace):+.1f} dBm, "
                                  f"mean gain {gain.mean():+.2f} dB (stepped {ref_k.mean():+.2f} dB)")
                            if abs(gain.mean() - ref_k.mean()) > 3.0:
                                ok = False
                                print("    -> does not match the stepped data; this setting did not put the source "
                                      "where intended")
                                break
                            if k >= args.warmup:
                                sweeps.append((trace, gain, secs))
                        attempts.append({"offset_hz": offset, "reverse": rev_on, "matched": ok})
                        if ok:
                            worked = (offset, rev_on)
                            break
                    meta[f"{name}_attempts"] = attempts
                    if worked is None:
                        print(f"  NO setting produced a valid {name} sweep.")
                        continue
                    print(f"  using {label}")
                    ref = np.interp(rf, rr, gg)
                    gain = np.mean([s[1] for s in sweeps], axis=0)
                    diff = gain - ref
                    rep = float(np.max(np.ptp([s[1] for s in sweeps], axis=0)))
                    floor_hint = float(np.median(sweeps[0][0]))
                    results[name] = {"rf": rf, "gain": gain, "ref": ref, "trace": sweeps[0][0], "diff": diff}
                    meta[name] = {"sweep_seconds": [round(s[2], 2) for s in sweeps],
                                  "repeatability_max_db": rep, "median_trace_dbm": floor_hint,
                                  "diff_mean_db": float(diff.mean()), "diff_std_db": float(diff.std()),
                                  "diff_max_abs_db": float(np.abs(diff).max()),
                                  "tracking_mean_gain_db": float(gain.mean()), "stepped_mean_gain_db": float(ref.mean())}
                    m = meta[name]
                    print(f"  sweep time {np.mean(m['sweep_seconds']):.2f} s for {args.points} points; "
                          f"repeat-to-repeat {rep:.2f} dB")
                    print(f"  mean gain: tracking {m['tracking_mean_gain_db']:+.2f} dB vs stepped "
                          f"{m['stepped_mean_gain_db']:+.2f} dB;  difference mean {m['diff_mean_db']:+.2f}, "
                          f"std {m['diff_std_db']:.2f}, worst {m['diff_max_abs_db']:.2f} dB")
        finally:
            ff.source_enable(False)
            for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF", "SENS:BAND:RES:AUTO ON"):
                ff.write(c)
            if orig_points is not None:
                ff.write(f"SENS:SWE:POIN {orig_points}")
            ff.write(f"SENS:FREQ:SPAN {ff.span_hz:.0f}")   # back to the 1 MHz span the CW measurements use
            ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            meta["ff_source_verified_off"] = not ff.source_state()
            meta["errors_at_end"] = ff.errors()
            for name, d in results.items():
                with open(outdir / f"tracking_{name}.csv", "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["rf_hz", "trace_dbm", "tracking_gain_db", "stepped_gain_db", "difference_db"])
                    for row in zip(d["rf"], d["trace"], d["gain"], d["ref"], d["diff"]):
                        w.writerow([f"{row[0]:.0f}"] + [f"{x:.3f}" for x in row[1:]])
            meta["finished"] = datetime.now().astimezone().isoformat(timespec="seconds")
            (outdir / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
            print("\nFieldFox source " + ("confirmed OFF (read back), tracking turned off."
                                          if meta["ff_source_verified_off"] else "*** STILL ON - switch it off! ***"))
            print(f"Saved {outdir}")
    print("Board configuration restored, flash persistence back ON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
