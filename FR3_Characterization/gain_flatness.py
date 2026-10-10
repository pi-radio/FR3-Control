"""TX conversion-gain flatness across a wideband signal's bandwidth.

    python gain_flatness.py [--lo-ghz 12] [--sideband upper] [--drive-dbm -40]
                            [--if-start-ghz 1.6] [--if-stop-ghz 2.4] [--step-mhz 5]
                            [--signal-center-ghz 2.0] [--signal-bw-mhz 500] [--passes 1]

The FieldFox source can only make a CW tone, so a wideband signal is reconstructed
by stepping a tone across the IF band and reading the RF output (and the image
sideband) at each step. For a linear system that is the response a flat
wideband input would see. Default: LO 12 GHz, upper sideband, IF scan 1.6-2.4 GHz
in 5 MHz steps (RF 13.6-14.4 GHz), highlighting a 500 MHz signal (IF 1.75-2.25 GHz
-> RF 13.75-14.25 GHz), one constant drive of -40 dBm (linear region), TX filter in
bypass, ONE pass upward in frequency (--passes 2 adds a downward pass, which earlier runs showed
agrees with the first to 0.09 dB or better - so it is not needed by default).

At every step it records the wanted tone, the image tone, and the LMX state, each as
measured and cable-corrected (FR1 cable at the IF, FR3 cable at the RF). Scalar only:
phase and group delay are not measured. Analyzer: 1 MHz span, attenuation held fixed,
tones tracked by peak search (the FieldFox and the board run on independent clocks).
Results: results/unit_<serial>/<run>/flatness.csv + metadata.json. The FieldFox source is
always switched off at the end (read back) and the board's configuration restored."""

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
from conversion_gain_small_case import (DEFAULT_FIXED_ATTENUATION_DB, FF_INPUT_GUARD_DBM,
                                        REF_FIXED_DBM, configure_board)
from fieldfox import SETTLE_S, FieldFox
from flatness_metrics import flatness_metrics
from results_layout import unit_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lo-ghz", type=float, default=12.0)
    parser.add_argument("--sideband", choices=("upper", "lower"), default="upper")
    parser.add_argument("--drive-dbm", type=float, default=-40.0, help="FF source level at every step")
    parser.add_argument("--if-start-ghz", type=float, default=1.6)
    parser.add_argument("--if-stop-ghz", type=float, default=2.4)
    parser.add_argument("--step-mhz", type=float, default=5.0)
    parser.add_argument("--signal-center-ghz", type=float, default=2.0, help="IF center of the wideband signal")
    parser.add_argument("--signal-bw-mhz", type=float, default=500.0)
    parser.add_argument("--passes", type=int, default=1,
                        help="alternating up/down passes (default 1: a single upward pass is enough - "
                             "pass-to-pass differences have been 0.09 dB or less)")
    parser.add_argument("--host", default="192.168.137.61", help="FieldFox address")
    parser.add_argument("--port", default=None, help="board COM port (default: auto-detect)")
    parser.add_argument("--span-mhz", type=float, default=1.0)
    parser.add_argument("--attenuation-db", type=float, default=DEFAULT_FIXED_ATTENUATION_DB)
    parser.add_argument("--allow-unserialized", action="store_true")
    args = parser.parse_args()

    f_lo = args.lo_ghz * 1e9
    upper = args.sideband == "upper"
    step = args.step_mhz * 1e6
    if_grid = np.arange(args.if_start_ghz * 1e9, args.if_stop_ghz * 1e9 + step / 2, step)
    sig_lo = args.signal_center_ghz * 1e9 - args.signal_bw_mhz * 1e6 / 2
    sig_hi = args.signal_center_ghz * 1e9 + args.signal_bw_mhz * 1e6 / 2

    def rf_of(f_if: float) -> float:
        return f_lo + f_if if upper else f_lo - f_if

    def img_of(f_if: float) -> float:
        return f_lo - f_if if upper else f_lo + f_if

    cable_if, cable_rf = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    for f_if in (if_grid[0], if_grid[-1]):
        cable_if.s21_db(f_if)
        cable_rf.s21_db(rf_of(f_if))       # raise now, not mid-run, if a frequency is outside the cable data
        cable_rf.s21_db(img_of(f_if))
    cable_rf.s21_db(f_lo)

    print(f"LO {f_lo/1e9:g} GHz, {args.sideband} sideband. IF {if_grid[0]/1e9:g}-{if_grid[-1]/1e9:g} GHz in "
          f"{args.step_mhz:g} MHz steps ({len(if_grid)} points) -> wanted RF "
          f"{rf_of(if_grid[0])/1e9:g}-{rf_of(if_grid[-1])/1e9:g} GHz. Drive {args.drive_dbm:g} dBm, "
          f"{args.passes} pass(es). Signal band IF {sig_lo/1e9:g}-{sig_hi/1e9:g} GHz.")

    run_name = (f"{datetime.now():%Y%m%d_%H%M%S}_flatness_lo{args.lo_ghz:g}_{args.sideband}_bypass_"
                f"drive{args.drive_dbm:g}dBm_{args.step_mhz:g}MHzsteps")
    meta = {"args": vars(args), "kind": "gain_flatness", "f_lo_hz": f_lo,
            "if_scan_hz": [float(if_grid[0]), float(if_grid[-1])], "signal_band_if_hz": [sig_lo, sig_hi],
            "fr1_cable_file": cable_if.path.name, "fr3_cable_file": cable_rf.path.name,
            "tx_filter": "bypass (0x00)", "started": datetime.now().astimezone().isoformat(timespec="seconds")}
    rows: list[dict] = []

    session = MeasurementSession(port=args.port)
    with session as board, FieldFox(args.host, span_hz=args.span_mhz * 1e6) as ff:
        meta["persist_before"] = session.persist_before
        meta["board_state_found"] = session.snapshot
        serial = board.get_board_serial()
        if serial == 0 and not args.allow_unserialized:
            raise RuntimeError("this board's serial number is 0 (never programmed): its data could not be told "
                               "apart from other units'. Program a serial or pass --allow-unserialized.")
        outdir = unit_dir(serial) / run_name
        outdir.mkdir(parents=True)
        meta["unit_serial"] = serial
        print(f"Unit #{serial}. Results: {outdir}")
        try:
            meta["ff_idn"] = ff.identify()
            ff.setup_spectrum_analyzer(ref_level_dbm=REF_FIXED_DBM)
            ff.source_enable(False)
            ff.set_attenuation(args.attenuation_db)
            meta.update(ff_span_hz=ff.span_hz, ff_rbw_hz=ff.rbw_hz, ff_attenuation_db=ff.attenuation_db)
            meta["board_state_during"] = configure_board(board, f_lo, args.sideband)
            print(f"FieldFox: span {ff.span_hz/1e6:g} MHz, RBW {ff.rbw_hz/1e3:g} kHz, attenuation fixed at "
                  f"{ff.attenuation_db:.0f} dB. Board: LMX {board.get_lmx_freq_hz()/1e9:g} GHz "
                  f"{board.get_lmx_lock()}, IQ {'SWAP' if board.get_iq_swap() else 'THRU'}, TX filter bypass.")

            # LO leakage once, with the drive on at the middle of the scan.
            mid = float(if_grid[len(if_grid) // 2])
            ff.source_configure(mid, args.drive_dbm)
            ff.source_enable(True)
            time.sleep(SETTLE_S)
            lo_r = ff.measure_at(f_lo)
            meta["lo_leakage"] = {"measured_at_ff_dbm": lo_r.power_dbm,
                                  "corrected_at_dut_dbm": lo_r.power_dbm - cable_rf.s21_db(f_lo)}
            print(f"LO leakage at {f_lo/1e9:g} GHz: {meta['lo_leakage']['corrected_at_dut_dbm']:+.2f} dBm "
                  f"(corrected)\n")

            off_w = off_i = 0.0   # tone offsets from nominal (independent clocks); followed step to step
            stop_reason = ""
            for p in range(args.passes):
                order = if_grid if p % 2 == 0 else if_grid[::-1]
                print(f"Pass {p + 1} of {args.passes} ({'upward' if p % 2 == 0 else 'downward'} in frequency)")
                for k, f_if in enumerate(order):
                    f_rf, f_img = rf_of(f_if), img_of(f_if)
                    ff.source_configure(f_if, args.drive_dbm)
                    time.sleep(SETTLE_S)
                    w = ff.measure_at(f_rf + off_w)
                    off_w = w.freq_hz - f_rf
                    i = ff.measure_at(f_img + off_i)
                    off_i = i.freq_hz - f_img
                    s21_if, s21_w, s21_i = cable_if.s21_db(f_if), cable_rf.s21_db(f_rf), cable_rf.s21_db(f_img)
                    p_in = args.drive_dbm + s21_if
                    w_corr, i_corr = w.power_dbm - s21_w, i.power_dbm - s21_i
                    lock = board.get_lmx_lock()
                    rows.append({
                        "pass": p + 1, "if_hz": float(f_if), "rf_hz": float(f_rf), "image_hz": float(f_img),
                        "drive_dbm": args.drive_dbm, "wanted_measured_dbm": round(w.power_dbm, 3),
                        "wanted_corrected_dbm": round(w_corr, 3), "image_measured_dbm": round(i.power_dbm, 3),
                        "image_corrected_dbm": round(i_corr, 3),
                        "gain_measured_db": round(w.power_dbm - args.drive_dbm, 3),
                        "gain_corrected_db": round(w_corr - p_in, 3),
                        "suppression_measured_db": round(w.power_dbm - i.power_dbm, 3),
                        "suppression_corrected_db": round(w_corr - i_corr, 3),
                        "wanted_offset_hz": round(off_w, 1), "image_offset_hz": round(off_i, 1),
                        "lmx_temperature_c": board.get_lmx_temperature_c(), "lmx_lock": lock})
                    if k % 20 == 0 or k == len(order) - 1:
                        r = rows[-1]
                        print(f"  IF {f_if/1e9:.3f} GHz -> RF {f_rf/1e9:.3f} GHz: gain {r['gain_corrected_db']:+.2f} dB "
                              f"(measured {r['gain_measured_db']:+.2f}), suppression {r['suppression_corrected_db']:.1f} dB, "
                              f"LMX {r['lmx_temperature_c']:.1f} C {lock}")
                    if max(w.power_dbm, i.power_dbm) > FF_INPUT_GUARD_DBM:
                        stop_reason = f"analyzer saw {max(w.power_dbm, i.power_dbm):+.1f} dBm (guard {FF_INPUT_GUARD_DBM:g})"
                    elif lock != "LOCKED":
                        stop_reason = f"LMX reported {lock}"
                    if stop_reason:
                        break
                if stop_reason:
                    break
            meta["stop_reason"] = stop_reason
            if stop_reason:
                print(f"\nSTOPPED EARLY: {stop_reason}")
            ff.check("flatness sweep")
        finally:
            ff.source_enable(False)
            ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            source_off = not ff.source_state()
            if rows:
                with open(outdir / "flatness.csv", "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=list(rows[0]))
                    w.writeheader()
                    w.writerows(rows)
            meta["finished"] = datetime.now().astimezone().isoformat(timespec="seconds")
            meta["ff_source_verified_off"] = source_off
            (outdir / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
            print("\nFieldFox source " + ("confirmed OFF (read back)." if source_off else "*** STILL ON - switch it off! ***"))

    # ---- summary (after the board is restored) ----
    if not rows:
        print("No data collected.")
        return 1
    passes = sorted({r["pass"] for r in rows})
    by_f: dict[float, dict[str, list[float]]] = {}
    for r in rows:
        d = by_f.setdefault(r["if_hz"], {"gain": [], "supp": []})
        d["gain"].append(r["gain_corrected_db"])
        d["supp"].append(r["suppression_corrected_db"])
    fgrid = np.array(sorted(by_f))
    gain = np.array([np.mean(by_f[f]["gain"]) for f in fgrid])
    supp = np.array([np.mean(by_f[f]["supp"]) for f in fgrid])
    band = (sig_lo, sig_hi)
    summary = {"passes": len(passes),
               "signal_band_gain": flatness_metrics(fgrid, gain, band),
               "whole_scan_gain": flatness_metrics(fgrid, gain, (fgrid[0], fgrid[-1])),
               "signal_band_suppression_db": flatness_metrics(fgrid, supp, band)}
    if len(passes) >= 2:
        both = [f for f in fgrid if len(by_f[f]["gain"]) >= 2]
        summary["pass_to_pass_max_gain_diff_db"] = float(max(abs(by_f[f]["gain"][0] - by_f[f]["gain"][1]) for f in both))
    meta["summary"] = summary
    (outdir / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))

    g, s = summary["signal_band_gain"], summary["signal_band_suppression_db"]
    print(f"\nSignal band IF {sig_lo/1e9:g}-{sig_hi/1e9:g} GHz (RF {rf_of(sig_lo)/1e9:g}-{rf_of(sig_hi)/1e9:g} GHz), "
          f"mean of {len(passes)} pass(es), corrected to the board's connectors:")
    print(f"  conversion gain: mean {g['mean_db']:+.2f} dB, peak-to-peak {g['peak_to_peak_db']:.2f} dB "
          f"(+/-{g['plus_minus_db']:.2f}), slope {g['slope_db_per_100mhz']:+.2f} dB/100 MHz, ripple about the trend "
          f"{g['ripple_pp_db']:.2f} dB p-p")
    print(f"  sideband suppression: mean {s['mean_db']:.1f} dB, min {s['min_db']:.1f}, max {s['max_db']:.1f}")
    ws = summary["whole_scan_gain"]
    print(f"  whole scan (IF {fgrid[0]/1e9:g}-{fgrid[-1]/1e9:g} GHz): gain {ws['min_db']:+.2f} to {ws['max_db']:+.2f} dB")
    if "pass_to_pass_max_gain_diff_db" in summary:
        print(f"  pass-to-pass repeatability: max gain difference {summary['pass_to_pass_max_gain_diff_db']:.2f} dB")
    print(f"Saved {outdir}")
    print("Board configuration restored, flash persistence back ON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
