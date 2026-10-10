"""TX conversion gain and compression, one (LO, IF, sideband) case, filters
in Bypass. FieldFox Port 1 -> FR1 cable -> board TX IF input; board TX FR3
output -> FR3 cable -> FieldFox Port 2. Nothing else in the path.

    python conversion_gain_small_case.py --stage A     # LO leakage only, nothing transmitted
    python conversion_gain_small_case.py --stage B     # A + IF tone at -45 dBm: wanted / image / LO
    python conversion_gain_small_case.py --stage C     # B + power sweep to 3 dB compression

Each stage includes the earlier ones. Defaults: LO 12 GHz, IF 2 GHz, upper
sideband (RF = LO + IF, IQ THRU); --sideband lower gives RF = LO - IF, IQ SWAP.

Every value is saved twice: as measured at the FieldFox, and corrected for
the two cables (FR1 at the IF, FR3 at each output tone) to the board's
connectors. Cable data are the S21 files in calibration/ (no user calibration,
see their .json). Errors of a few tenths of a dB are acceptable.

Analyzer: 1 MHz span, and the input attenuation is HELD FIXED for the whole run
(default 35 dB; --auto-attenuation restores the level-tracking behavior), so
attenuator steps cannot masquerade as gain changes. The FieldFox and the board
run on independent clocks, so tones are found by peak search and tracked.

Safety: the FieldFox source is always switched off at the end (and on any
error); the board's flash persistence is off during the run and its original
configuration is restored afterwards (board.MeasurementSession). The sweep
stops at 3.5 dB compression, or if the analyzer would see more than
+23 dBm, or if the FF source reaches 0 dBm."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from board import MeasurementSession  # also puts FR3_GUI on sys.path
from cables import CableLoss
from compression import compression_point, small_signal_gain
from fieldfox import SETTLE_S, FieldFox
from fr3_gui.lo_suppression import suggest_iv_qv
from results_layout import unit_dir


FF_SOURCE_MIN_DBM = -60.0          # the FF source goes down to -60 dBm (guide says -45)
DEFAULT_START_DBM = -58.0          # -60 itself read ~0.6 dB low on the board once; see --start-dbm
FF_SOURCE_MAX_DBM = 0.0
FF_INPUT_GUARD_DBM = 23.0          # never let the analyzer see more than this (FF rating: +27 dBm)
MAX_INPUT_AT_DUT_DBM: float | None = None   # RX sweeps set -5.0: never more than this INTO the board (LNA safety)
COARSE_STEP_DB = 2.0
FINE_STEP_DB = 0.5
FINE_STARTS_AT_COMPRESSION_DB = 0.3
STOP_AT_COMPRESSION_DB = 3.5
NOISE_LIMIT_DBM = -65.0            # FF readings below this are too near its floor to trust
TX_FILTER_BYPASS = 0x00
REF_FIXED_DBM = 20.0               # analyzer reference level used with a fixed attenuator
DEFAULT_FIXED_ATTENUATION_DB = 35  # holds the mixer at about -12 dBm at the +23 dBm guard level


def must(ok: bool, what: str) -> None:
    if not ok:
        raise RuntimeError(f"board rejected: {what}")


def configure_board(board, f_lo_hz: float, sideband: str) -> dict:
    """Known TX state: internal clock and LO, LMX at power 7 locked on f_lo,
    I/Q bias from the shipped LO-null table (what the GUI does by default),
    IQ for the requested sideband, TX filter in Bypass."""
    must(board.set_clock_internal(True), "SET CLOCK INT")
    must(board.set_lo_internal(True), "SET LO INT")
    must(board.set_lmx_power(7), "LMX PWR 7")
    must(board.lmx_tune(f_lo_hz), f"LMX TUNE {f_lo_hz:.0f} (did not lock)")
    for _ in range(20):
        if board.get_lmx_lock() == "LOCKED":
            break
        time.sleep(0.25)
    else:
        raise RuntimeError("LMX not LOCKED after tune")
    iv = suggest_iv_qv(f_lo_hz / 1e9)
    if iv is None:
        raise RuntimeError("no LO-null table entry at this LO frequency")
    must(board.set_i_v(iv[0]), "SET I_V")
    must(board.set_q_v(iv[1]), "SET Q_V")
    must(board.set_iq_swap(sideband == "lower"), "SET IQ")
    must(board.set_tx_filter(TX_FILTER_BYPASS), "SET TXFILTER bypass")
    return {**board.snapshot(), "lmx_lock": board.get_lmx_lock(),
            "lmx_temperature_c": board.get_lmx_temperature_c(), "board_serial": board.get_board_serial()}


def tune_and_lock(board, f_lo_hz: float) -> None:
    """Retune the LMX to f_lo_hz and wait (up to about 3 s, one retry) until it reports LOCKED."""
    for _ in range(2):
        if board.lmx_tune(f_lo_hz):
            for _ in range(60):
                if board.get_lmx_lock() == "LOCKED":
                    return
                time.sleep(0.05)
        time.sleep(0.3)
    raise RuntimeError(f"LMX would not lock at {f_lo_hz / 1e9:g} GHz")


def read_tone(ff, cable_rf, name: str, freq_hz: float, p_set_dbm: float | None,
              fixed_att: bool = True, ref_hint: float = 20.0) -> dict:
    if fixed_att:
        r, ref = ff.measure_at(freq_hz), REF_FIXED_DBM
    else:
        r, ref = ff.measure_tone_adaptive(freq_hz, ref_hint)
    s21 = cable_rf.s21_db(freq_hz)
    return {"tone": name, "freq_hz": freq_hz, "marker_freq_hz": r.freq_hz,
            "offset_from_nominal_hz": round(r.freq_hz - freq_hz, 1),
            "ff_source_dbm": "" if p_set_dbm is None else p_set_dbm,
            "measured_at_ff_dbm": round(r.power_dbm, 3), "cable_s21_db": round(s21, 3),
            "corrected_at_dut_dbm": round(r.power_dbm - s21, 3),
            "ref_level_dbm": ref, "attenuation_db": ff.attenuation_db}


def show_tone(t: dict) -> None:
    print(f"  {t['tone']:<7} {t['freq_hz']/1e9:7.3f} GHz  measured {t['measured_at_ff_dbm']:+8.2f} dBm   "
          f"corrected {t['corrected_at_dut_dbm']:+8.2f} dBm   (tone {t['offset_from_nominal_hz']/1e3:+.1f} kHz "
          f"from nominal, ref {t['ref_level_dbm']:+.0f} dBm, atten {t['attenuation_db']:.0f} dB)")


def power_sweep(ff, board, cable_if, cable_rf, f_if: float, f_rf: float,
                fixed_att: bool = True, start_dbm: float = DEFAULT_START_DBM) -> tuple[list[dict], dict]:
    s21_if = cable_if.s21_db(f_if)
    s21_rf = cable_rf.s21_db(f_rf)
    rows: list[dict] = []
    valid_gains: list[float] = []
    g0: float | None = None
    p_set = start_dbm
    step = COARSE_STEP_DB
    last_read: float | None = None
    center = f_rf  # follows the tone: the FF and the board have independent clocks
    stop_reason = ""

    print(f"\nC) Power sweep: FF source {start_dbm:.0f} dBm upward, IF {f_if/1e9:g} GHz, "
          f"reading RF {f_rf/1e9:g} GHz, span {ff.span_hz/1e6:g} MHz, input attenuation "
          + (f"held fixed at {ff.attenuation_db:.0f} dB" if fixed_att else "tracking the signal (auto)"))
    print("   set   in@DUT   read@FF  out@DUT | gain(meas) gain(corr) compress |  ref  att   temp lock")
    while True:
        if last_read is None:
            ref_hint = 20.0  # unknown gain: start with the analyzer fully protected
        else:
            predicted = last_read + (p_set - rows[-1]["ff_source_dbm"])  # gain can only fall
            if predicted > FF_INPUT_GUARD_DBM:
                stop_reason = f"next step would put the analyzer above +{FF_INPUT_GUARD_DBM:.0f} dBm"
                break
            ref_hint = min(20.0, predicted + 7.0)
        if MAX_INPUT_AT_DUT_DBM is not None and p_set + s21_if > MAX_INPUT_AT_DUT_DBM + 1e-6:
            stop_reason = f"next step would put more than {MAX_INPUT_AT_DUT_DBM:+.0f} dBm into the board"
            break
        if not fixed_att:
            ff.set_ref_level(ref_hint)      # protect the analyzer BEFORE raising the drive
        ff.source_configure(f_if, p_set)
        time.sleep(SETTLE_S)
        if fixed_att:
            r, ref = ff.measure_at(center), REF_FIXED_DBM
        else:
            r, ref = ff.measure_tone_adaptive(center, ref_hint, apply_ref=False)

        p_in = p_set + s21_if
        p_out = r.power_dbm - s21_rf
        gain_meas = r.power_dbm - p_set
        gain_corr = p_out - p_in
        valid = r.power_dbm >= NOISE_LIMIT_DBM
        if valid:
            center = r.freq_hz
            valid_gains.append(gain_corr)
            if g0 is None:
                try:
                    g0 = small_signal_gain(valid_gains)
                except ValueError as err:
                    stop_reason = f"small-signal gain not stable: {err}"
        compression = None if (g0 is None or not valid) else g0 - gain_corr
        lock = board.get_lmx_lock()
        temp = board.get_lmx_temperature_c()
        rows.append({
            "ff_source_dbm": p_set, "marker_freq_hz": r.freq_hz,
            "tone_offset_from_nominal_hz": round(r.freq_hz - f_rf, 1),
            "measured_at_ff_dbm": round(r.power_dbm, 3),
            "measured_gain_db": round(gain_meas, 3),
            "in_at_dut_dbm": round(p_in, 3), "out_at_dut_dbm": round(p_out, 3),
            "corrected_gain_db": round(gain_corr, 3),
            "compression_db": "" if compression is None else round(compression, 3),
            "valid": int(valid), "ref_level_dbm": ref, "attenuation_db": ff.attenuation_db,
            "lmx_temperature_c": temp, "lmx_lock": lock,
        })
        comp_txt = "     -" if compression is None else f"{compression:6.2f}"
        print(f"  {p_set:+5.1f} {p_in:+7.2f} {r.power_dbm:+9.2f} {p_out:+8.2f} | {gain_meas:+9.2f} "
              f"{gain_corr:+10.2f} {comp_txt}  | {ref:+4.0f} {rows[-1]['attenuation_db']:4.0f} "
              f"{temp:6.1f} {lock}{'' if valid else '  (near FF noise floor - not used)'}")

        if stop_reason:
            break
        if lock != "LOCKED":
            stop_reason = f"LMX reported {lock}"
            break
        if compression is not None and compression >= STOP_AT_COMPRESSION_DB:
            stop_reason = f"reached {STOP_AT_COMPRESSION_DB} dB compression"
            break
        step = FINE_STEP_DB if (compression is not None and compression >= FINE_STARTS_AT_COMPRESSION_DB) \
            else COARSE_STEP_DB
        last_read = r.power_dbm
        p_set = round(p_set + step, 3)
        if p_set > FF_SOURCE_MAX_DBM:
            stop_reason = "FieldFox source reached 0 dBm before the target compression"
            break

    results: dict = {"stop_reason": stop_reason, "small_signal_gain_db": g0}
    if g0 is not None:
        used = [x for x in rows if x["valid"]]
        for drop in (1.0, 3.0):
            cp = compression_point([x["in_at_dut_dbm"] for x in used],
                                   [x["out_at_dut_dbm"] for x in used], g0, drop)
            results[f"p{drop:g}db"] = None if cp is None else {
                "input_dbm": round(cp.pin_dbm, 2), "output_dbm": round(cp.pout_dbm, 2)}
    print(f"\n   Stopped: {stop_reason}")
    if g0 is not None:
        print(f"   Small-signal conversion gain (corrected): {g0:+.2f} dB")
        for drop in (1, 3):
            cp = results.get(f"p{drop}db")
            print(f"   P{drop}dB: " + ("not reached" if cp is None else
                  f"input {cp['input_dbm']:+.2f} dBm, output {cp['output_dbm']:+.2f} dBm (at the board connectors)"))
    return rows, results


def write_csv(path: Path, rows: list[dict]) -> None:
    if rows:
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices="ABC", required=True)
    parser.add_argument("--lo-ghz", type=float, default=12.0)
    parser.add_argument("--if-ghz", type=float, default=2.0)
    parser.add_argument("--sideband", choices=("upper", "lower"), default="upper")
    parser.add_argument("--host", default="192.168.137.61", help="FieldFox address")
    parser.add_argument("--port", default=None, help="board COM port (default: auto-detect)")
    parser.add_argument("--start-dbm", type=float, default=DEFAULT_START_DBM,
                        help="FF source power for stage B and where the sweep starts "
                             f"(default {DEFAULT_START_DBM:g}; the source's own minimum is -60)")
    parser.add_argument("--allow-unserialized", action="store_true",
                        help="permit a board whose serial number is 0 (saved under unit_000)")
    parser.add_argument("--span-mhz", type=float, default=1.0, help="analyzer span (default 1 MHz)")
    parser.add_argument("--attenuation-db", type=float, default=DEFAULT_FIXED_ATTENUATION_DB,
                        help="analyzer input attenuation, held FIXED for the whole run "
                             f"(default {DEFAULT_FIXED_ATTENUATION_DB} dB)")
    parser.add_argument("--auto-attenuation", action="store_true",
                        help="instead let the attenuation follow the signal level (the first run's behavior)")
    args = parser.parse_args()

    rank = "ABC".index(args.stage) + 1
    f_lo, f_if = args.lo_ghz * 1e9, args.if_ghz * 1e9
    upper = args.sideband == "upper"
    f_rf = f_lo + f_if if upper else f_lo - f_if
    f_img = f_lo - f_if if upper else f_lo + f_if

    cable_if, cable_rf = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    cable_if.s21_db(f_if)
    for f in (f_lo, f_rf, f_img):
        cable_rf.s21_db(f)  # raises now, not mid-run, if a frequency is outside the cable data

    fixed_att = not args.auto_attenuation
    att_tag = f"att{args.attenuation_db:g}" if fixed_att else "autoatt"
    run_name = (f"{datetime.now():%Y%m%d_%H%M%S}_lo{args.lo_ghz:g}_if{args.if_ghz:g}_"
                f"{args.sideband}_bypass_span{args.span_mhz:g}MHz_{att_tag}")
    print(f"LO {f_lo/1e9:g} GHz, IF {f_if/1e9:g} GHz, {args.sideband} sideband: wanted RF {f_rf/1e9:g} GHz, "
          f"image {f_img/1e9:g} GHz. Stage {args.stage}.")

    meta = {"args": vars(args), "f_lo_hz": f_lo, "f_if_hz": f_if, "f_rf_hz": f_rf, "f_image_hz": f_img,
            "fr1_cable_file": cable_if.path.name, "fr3_cable_file": cable_rf.path.name,
            "tx_filter": "bypass (0x00)", "started": datetime.now().astimezone().isoformat(timespec="seconds")}
    tones: list[dict] = []
    session = MeasurementSession(port=args.port)
    with session as board, FieldFox(args.host, span_hz=args.span_mhz * 1e6) as ff:
        meta["persist_before"] = session.persist_before
        meta["board_state_found"] = session.snapshot
        # Results go in this unit's own folder, named after the board's serial number.
        serial = board.get_board_serial()
        if serial == 0 and not args.allow_unserialized:
            raise RuntimeError("this board's serial number is 0 (never programmed with SET BOARD SERIAL), so its "
                               "data could not be told apart from other units'. Program a serial, or pass "
                               "--allow-unserialized to save under unit_000.")
        outdir = unit_dir(serial) / run_name
        outdir.mkdir(parents=True)
        meta["unit_serial"] = serial
        print(f"Unit #{serial}. Results: {outdir}")
        try:
            meta["ff_idn"] = ff.identify()
            ff.setup_spectrum_analyzer(ref_level_dbm=REF_FIXED_DBM)
            ff.source_enable(False)
            if fixed_att:
                ff.set_attenuation(args.attenuation_db)   # read back; aborts if it did not take
            meta["ff_span_hz"] = ff.span_hz
            meta["ff_rbw_hz"] = ff.rbw_hz
            meta["ff_attenuation"] = ("fixed" if fixed_att else "auto")
            meta["ff_attenuation_db_at_start"] = ff.attenuation_db
            print(f"FieldFox: span {ff.span_hz/1e6:g} MHz, RBW {ff.rbw_hz/1e3:g} kHz, input attenuation "
                  + (f"HELD FIXED at {ff.attenuation_db:.0f} dB" if fixed_att else "auto"))
            meta["board_state_during"] = configure_board(board, f_lo, args.sideband)
            print(f"Board: LMX {board.get_lmx_freq_hz()/1e9:g} GHz {board.get_lmx_lock()}, "
                  f"I_V {board.get_i_v():+.4f} V, Q_V {board.get_q_v():+.4f} V, "
                  f"IQ {'SWAP' if board.get_iq_swap() else 'THRU'}, TX filter bypass")

            print("\nA) LO leakage, FieldFox source OFF (nothing transmitted)")
            t = read_tone(ff, cable_rf, "LO", f_lo, None, fixed_att)
            t["stage"] = "A"; tones.append(t); show_tone(t)

            if rank >= 2:
                print(f"\nB) IF tone {args.start_dbm:.0f} dBm at {f_if/1e9:g} GHz: wanted / image / LO")
                ff.source_configure(f_if, args.start_dbm)
                ff.source_enable(True)
                time.sleep(SETTLE_S)
                b = [read_tone(ff, cable_rf, "wanted", f_rf, args.start_dbm, fixed_att),
                     read_tone(ff, cable_rf, "image", f_img, args.start_dbm, fixed_att),
                     read_tone(ff, cable_rf, "LO", f_lo, args.start_dbm, fixed_att)]
                for t in b:
                    t["stage"] = "B"; tones.append(t); show_tone(t)
                wanted, image = b[0]["measured_at_ff_dbm"], b[1]["measured_at_ff_dbm"]
                print(f"  Sideband suppression (wanted - image): {wanted - image:+.1f} dB")
                if wanted - image < 3.0:
                    print("  *** WARNING: image is not clearly weaker than the wanted tone. Either the "
                          "sideband/IQ mapping is reversed, or the wanted tone is near the FF noise floor. "
                          "Not continuing to the power sweep until this is understood.")
                    rank = min(rank, 2)

            if rank >= 3:
                rows, results = power_sweep(ff, board, cable_if, cable_rf, f_if, f_rf, fixed_att,
                                            args.start_dbm)
                write_csv(outdir / "power_sweep.csv", rows)
                meta["power_sweep"] = results
        finally:
            ff.source_enable(False)
            ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            source_off = not ff.source_state()  # read it back - never assume
            write_csv(outdir / "tones.csv", tones)
            meta["finished"] = datetime.now().astimezone().isoformat(timespec="seconds")
            meta["ff_source_verified_off"] = source_off
            (outdir / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
            if source_off:
                print(f"\nFieldFox source confirmed OFF (read back). Saved {outdir}")
            else:
                print(f"\n*** WARNING: FieldFox source is STILL ON after the run - switch it off "
                      f"before touching the board! Saved {outdir}", file=sys.stderr)
    print("Board configuration restored, flash persistence back ON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
