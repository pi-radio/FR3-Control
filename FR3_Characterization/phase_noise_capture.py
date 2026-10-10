"""LO phase noise of the Pi-Radio FR3-1ch, measured on the LO leakage at the "TX-side FR3 RF Out" port with
the UXA's Phase Noise application (N9068EM0E), Log Plot measurement.

    python phase_noise_capture.py --lo-ghz 10 --leak zero_dbm  [--navg 10]
    python phase_noise_capture.py --lo-ghz 10 --leak max        (I_V = Q_V = 0 V: ~+17 dBm, PA in compression)

Setup (by the user, before running): "TX-side FR3 RF Out" port -> UXA RF input; "TX-side FR1 IF In" port
terminated in 50 ohm. The script sets the TX filter to bypass, tunes the LMX2820 (internal clock and LO),
sets the I/Q bias, and restores the board's previous settings on exit (MeasurementSession).

Leakage level:
  zero_dbm  start from the stored LO-null bias, then raise I_V (bisection on the UXA's measured carrier, Swept
            SA mode, fresh peak search per reading) until the carrier is 0 dBm +/- 0.3 dB.
  max       I_V = Q_V = 0 V.

Phase noise (SCPI from the N9068A Phase Noise Measurement Application User's & Programmer's Reference,
9018-01741): INST:SEL PNOISE; CONF:LPL; carrier frequency + signal tracking ON; offsets 100 Hz - 1 MHz;
averaging ON, count --navg, REPeat; single measurement; FETC:LPL1? (scalars) and FETC:LPL3?/4? (traces 1/2 as
offset, dBc/Hz pairs). Every setting is read back and the UXA error queue checked.

Results: results/unit_<serial>/phase_noise/lo<GHz>_<leak>_<stamp>.csv (+ .json with scalars/settings).
"""
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
from fr3_gui.am3153_filter import FILTER_BANKS, get_response
from fr3_gui.lo_suppression import suggest_iv_qv
from results_layout import unit_dir
from rx_clock_comb_capture import Uxa

START_OFFSET_HZ = 100.0
STOP_OFFSET_HZ = 1e6
TARGET_DBM, TOL_DB = 0.0, 0.3
LMX_SETTLE_S = 5.0               # wait after lock before measuring
LMX_CROSSOVER_HZ = 11.3e9        # firmware lmx2820.c: VCO direct up to here (inclusive), output doubler above
FILTER_SCORE_HALF_BW_HZ = 25e6   # S21 averaged over +/-25 MHz around each tone
FILTER_DESIRED_WITHIN_DB = 3.0
MAX_CARRIER_FREQ_ERROR_HZ = 1e6  # phase-noise app must be on the LO, not on a harmonic/subharmonic
DISPLAY_TOP_DBC_HZ, DISPLAY_DB_PER_DIV = -40.0, 10.0
MIXER_TARGET_DBM = -6.0          # carrier level at the UXA's first mixer (the 0 dBm run's operating point)
MAX_CARRIER_MISMATCH_DB = 1.5    # phase-noise app carrier vs Swept SA reading; larger means analyzer overload


def unwanted_tone_hz(lo_hz: float) -> float:
    """The LMX2820 tone to block: at/below the 11.3 GHz crossover the VCO drives the output directly, so its 2nd
    harmonic leaks; above it the output doubler is used, so the VCO fundamental (LO/2) leaks."""
    return 2 * lo_hz if lo_hz <= LMX_CROSSOVER_HZ else lo_hz / 2


def choose_tx_filter(lo_hz: float) -> tuple[int, float, float]:
    """AM3153 setting that passes the LO and blocks the unwanted tone (same two-step rule as the datasheet's
    'optimal' filter): best desired power first, then the least unwanted power among settings within
    FILTER_DESIRED_WITHIN_DB of it. Returns (bits, desired S21 dB, unwanted S21 dB) from the S-parameter data."""
    def s21_db(resp, f):
        m = (resp.freq_hz >= f - FILTER_SCORE_HALF_BW_HZ) & (resp.freq_hz <= f + FILTER_SCORE_HALF_BW_HZ)
        return 10 * np.log10(np.mean(10 ** (resp.s21_db[m] / 10))) if np.any(m) else -999.0

    bad = unwanted_tone_hz(lo_hz)
    cands = []
    for _, bank in FILTER_BANKS:
        if bank == 0x0:                       # bypass is not a filter
            continue
        for cfg in range(16):
            bits = (bank << 4) | cfg
            resp = get_response(bits)
            cands.append((bits, s21_db(resp, lo_hz), s21_db(resp, bad)))
    best = max(c[1] for c in cands)
    return min((c for c in cands if c[1] >= best - FILTER_DESIRED_WITHIN_DB), key=lambda c: c[2])


def check(uxa: Uxa, what: str) -> None:
    """UXA error-queue check that tolerates only "Align Now required" (+64, expected with auto-align OFF and no
    Align Now, per the user's decision); any other error still stops the run."""
    while True:
        err = uxa.query(":SYST:ERR?")
        if err.startswith(("+0", "0")):
            return
        if "Align Now" in err and "required" in err:
            print(f"  (UXA: {err} - ignored, alignments are off by design)")
            continue
        raise RuntimeError(f"UXA error after {what}: {err}")


def disable_alignment(uxa: Uxa) -> None:
    """UXA background auto-align OFF and no Align Now: these are not metrology-grade measurements, and the
    alignments (53 in one Align Now) were only getting in the way (user decision 2026-10-04). Left OFF."""
    uxa.write(":CAL:AUTO OFF")
    check(uxa, "auto align off")


def lmx_locked(board, lo_hz: float) -> None:
    ok = board.set_clock_internal(True) and board.set_lo_internal(True) and board.set_lmx_mute(False) \
        and board.set_lmx_power(7) and board.lmx_tune(lo_hz)
    if not ok:
        raise RuntimeError("board rejected clock/LO/LMX setup")
    for _ in range(40):
        if board.get_lmx_lock() == "LOCKED":
            # lock detect asserts before the loop has fully settled: wait before any measurement (user, 2026-10-04)
            print(f"  LMX locked at {lo_hz/1e9:g} GHz; settling {LMX_SETTLE_S:g} s")
            time.sleep(LMX_SETTLE_S)
            return
        time.sleep(0.25)
    raise RuntimeError(f"LMX not locked at {lo_hz/1e9:g} GHz")


def sa_setup(uxa: Uxa, lo_hz: float) -> None:
    uxa.write(":INST:SEL SA")
    uxa.query("*OPC?", timeout=60)
    uxa.write(":CONF:SAN")
    uxa.write(f":SENS:FREQ:CENT {lo_hz:.0f};:SENS:FREQ:SPAN 1e6;:SENS:BAND:RES 10e3")
    uxa.write(":SENS:POW:RF:ATT:AUTO ON;:DISP:WIND:TRAC:Y:RLEV 25")
    uxa.write(":INIT:CONT OFF")
    check(uxa, "SA setup")


def sa_carrier_dbm(uxa: Uxa, lo_hz: float, cable_db: float) -> float:
    """LO leakage at the board's "TX-side FR3 RF Out" port: single sweep, fresh peak search, marker read,
    corrected for the cable's S21 (cable_db is negative, so subtracting it adds the loss back)."""
    uxa.write(":INIT:IMM;*WAI")
    uxa.query("*OPC?", timeout=30)
    uxa.write(":CALC:MARK1:MAX")
    return float(uxa.query(":CALC:MARK1:Y?")) - cable_db


def drive_sweep(board, uxa: Uxa, lo_hz: float, cable_db: float, outdir, stem: str) -> None:
    """LO leakage vs I_V offset from the null (Q_V at its null): 6 dB per doubling while linear, flattening in
    compression. Ends at I_V = Q_V = 0 V (the 'max' case) for reference."""
    i0, q0 = suggest_iv_qv(lo_hz / 1e9)
    sa_setup(uxa, lo_hz)
    board.set_q_v(q0)
    rows = []
    for dv in (0.002, 0.004, 0.008, 0.016, 0.032, 0.064, 0.128, 0.256, 0.4):
        if abs(i0 + dv) > 0.5:
            break
        board.set_i_v(round(i0 + dv, 4))
        time.sleep(0.2)
        p = sa_carrier_dbm(uxa, lo_hz, cable_db)
        rows.append((round(i0 + dv, 4), q0, dv, p))
        print(f"  I_V null{dv*1e3:+7.1f} mV: {p:+7.2f} dBm at the port")
    board.set_i_v(0.0)
    board.set_q_v(0.0)
    time.sleep(0.2)
    p = sa_carrier_dbm(uxa, lo_hz, cable_db)
    rows.append((0.0, 0.0, float("nan"), p))
    print(f"  I_V = Q_V = 0 V: {p:+7.2f} dBm at the port")
    with open(outdir / f"{stem}_drive_sweep.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["i_v", "q_v", "i_v_minus_null", "leak_dbm_at_port"])
        w.writerows(rows)


def level_to_zero_dbm(board, uxa: Uxa, lo_hz: float, cable_db: float) -> tuple[float, float, float]:
    """Raise I_V above the stored null until the leakage is TARGET_DBM. Returns (i_v, q_v, level)."""
    null = suggest_iv_qv(lo_hz / 1e9)
    if null is None:
        raise RuntimeError("no stored LO-null bias for this LO")
    i0, q0 = null
    sa_setup(uxa, lo_hz)
    if not (board.set_q_v(q0) and board.set_i_v(i0)):
        raise RuntimeError("board rejected null bias")
    # 0 = at the null (low leakage); the top is the DAC's +0.5 V limit, since the TX filter's 7-14 dB loss ahead of
    # the amplifiers can push 0 dBm well beyond the +0.2 V that sufficed with the filter bypassed
    lo_dv, hi_dv = 0.0, 0.5 - i0
    for _ in range(25):
        dv = (lo_dv + hi_dv) / 2
        board.set_i_v(round(i0 + dv, 4))
        time.sleep(0.2)
        p = sa_carrier_dbm(uxa, lo_hz, cable_db)
        print(f"  I_V {i0 + dv:+.4f} V (null {i0:+.4f}, +{dv*1e3:.1f} mV): carrier {p:+.2f} dBm")
        if abs(p - TARGET_DBM) <= TOL_DB:
            return round(i0 + dv, 4), q0, p
        if p < TARGET_DBM:
            lo_dv = dv
        else:
            hi_dv = dv
    raise RuntimeError("could not level the carrier to 0 dBm")


def attenuation_for(carrier_dbm_at_uxa: float) -> float:
    """Input attenuation putting the carrier at ~MIXER_TARGET_DBM on the UXA's first mixer (2 dB steps), so every
    run sees the same analyzer operating point and only the board's own state differs."""
    att = 2 * round((carrier_dbm_at_uxa - MIXER_TARGET_DBM) / 2)
    return float(min(max(att, 6), 40))


def measure_log_plot(uxa: Uxa, lo_hz: float, navg: int,
                     carrier_dbm_at_uxa: float) -> tuple[dict, list[tuple[float, float, float]]]:
    uxa.write(":INST:SEL PNOISE")
    uxa.query("*OPC?", timeout=120)
    # Mode Preset (*RST, per the manual) of the phase-noise mode only, so no setting left over from an earlier
    # run can carry over (2026-10-04: a leftover disabled electronic attenuator locked Pre-Adjust for Min Clip OFF).
    uxa.write("*RST")
    uxa.query("*OPC?", timeout=120)
    uxa.write(":CONF:LPL")
    uxa.query("*OPC?", timeout=60)
    uxa.write(f":SENS:FREQ:CARR {lo_hz:.0f}")
    uxa.write(":SENS:FREQ:CARR:TRAC ON")
    uxa.write(f":SENS:LPL:FREQ:OFFS:STAR {START_OFFSET_HZ:.0f};:SENS:LPL:FREQ:OFFS:STOP {STOP_OFFSET_HZ:.0f}")
    uxa.write(f":SENS:LPL:AVER ON;:SENS:LPL:AVER:COUN {navg};:SENS:LPL:AVER:TCON REP")
    uxa.write(":SENS:LPL:METH PN")
    # display scale only (the fetched data is unaffected), so the whole curve is visible on screen:
    # top -40 dBc/Hz, 10 dB/div -> -40 ... -140 dBc/Hz
    uxa.write(f":DISP:LPL:VIEW:WIND:TRAC:Y:RLEV {DISPLAY_TOP_DBC_HZ:g};"
              f":DISP:LPL:VIEW:WIND:TRAC:Y:PDIV {DISPLAY_DB_PER_DIV:g}")
    uxa.write(":INIT:CONT OFF")
    check(uxa, "phase noise setup")
    # Auto Tune (front-panel AUTO TUNE): finds the carrier and sets the input level/range itself. Hand-set
    # attenuation/ranging gave "Input overload, ADC over range"; Auto Tune clears it (user, 2026-10-04).
    uxa.write(":SENS:FREQ:CARR:SEAR")
    uxa.query("*OPC?", timeout=120)
    check(uxa, "auto tune")
    settings = {
        "carrier_hz": float(uxa.query(":SENS:FREQ:CARR?")),
        "tracking": uxa.query(":SENS:FREQ:CARR:TRAC?"),
        "start_offset_hz": float(uxa.query(":SENS:LPL:FREQ:OFFS:STAR?")),
        "stop_offset_hz": float(uxa.query(":SENS:LPL:FREQ:OFFS:STOP?")),
        "averaging": uxa.query(":SENS:LPL:AVER?"),
        "avg_count": int(float(uxa.query(":SENS:LPL:AVER:COUN?"))),
        "avg_mode": uxa.query(":SENS:LPL:AVER:TCON?"),
        "method": uxa.query(":SENS:LPL:METH?"),
        "smoothing": uxa.query(":SENS:LPL:SMO?"),
        "am_rejection": uxa.query(":SENS:LPL:AMR?"),
        "display_top_dbc_hz": float(uxa.query(":DISP:LPL:VIEW:WIND:TRAC:Y:RLEV?")),
        "display_db_per_div": float(uxa.query(":DISP:LPL:VIEW:WIND:TRAC:Y:PDIV?")),
        "atten_db": float(uxa.query(":SENS:POW:RF:ATT?")),
        "atten_auto": uxa.query(":SENS:POW:RF:ATT:AUTO?"),
        "range_auto_min_clip": uxa.query(":SENS:POW:RF:RANG:AUTO?"),
    }
    print("  UXA settings read back:", settings)
    if (settings["start_offset_hz"], settings["stop_offset_hz"]) != (START_OFFSET_HZ, STOP_OFFSET_HZ):
        raise RuntimeError(f"offsets not as requested: {settings}")
    t0 = time.time()
    uxa.write(":INIT:LPL")
    uxa.query("*OPC?", timeout=1800)                 # single measurement incl. all averages
    print(f"  measurement done in {time.time() - t0:.0f} s")
    check(uxa, "log plot measurement")
    # Questionable Integrity condition: 16 while the UXA showed "Input overload, ADC over range"; 0 when clean
    integrity = int(float(uxa.query(":STAT:QUES:INT:COND?")))
    if integrity != 0:
        raise RuntimeError(f"UXA Questionable Integrity condition = {integrity} (16 = the ADC over-range seen on "
                           f"2026-10-04): measurement not valid - not saving")
    s = [float(v) for v in uxa.query(":FETC:LPL1?", timeout=60).split(",")]
    scalars = dict(zip(["carrier_dbm", "carrier_hz", "rms_pn_deg", "rms_pn_rad", "residual_fm_hz",
                        "spot_start_dbc_hz", "spot_stop_dbc_hz"], s))
    t1 = [float(v) for v in uxa.query(":FETC:LPL3?", timeout=60).split(",")]
    t2 = [float(v) for v in uxa.query(":FETC:LPL4?", timeout=60).split(",")]
    check(uxa, "fetch")
    p1, p2 = list(zip(t1[0::2], t1[1::2])), list(zip(t2[0::2], t2[1::2]))
    rows = [(f, a, b) for (f, a), (_, b) in zip(p1, p2)] if len(p1) == len(p2) else [(f, a, float("nan")) for f, a in p1]
    return {**settings, **scalars, "n_trace1": len(p1), "n_trace2": len(p2)}, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-ghz", type=float, required=True)
    ap.add_argument("--leak", choices=("zero_dbm", "max", "sweep"), required=True,
                    help="sweep = LO-leakage drive sweep only (no phase noise measurement)")
    ap.add_argument("--navg", type=int, default=10)
    ap.add_argument("--cable", default="fr3_cable", help="S21 file of the cable from the board to the UXA")
    args = ap.parse_args()
    lo_hz = args.lo_ghz * 1e9
    cable_db = CableLoss(args.cable).s21_db(lo_hz)
    print(f"cable {args.cable}: {cable_db:.2f} dB at {args.lo_ghz:g} GHz (added back to every UXA reading)")
    uxa = Uxa()
    print("UXA:", uxa.query("*IDN?"))
    disable_alignment(uxa)
    return run(args, uxa, lo_hz, cable_db)


def run(args, uxa: Uxa, lo_hz: float, cable_db: float) -> int:
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    stem = f"lo{args.lo_ghz:g}GHz_{args.leak}_{stamp}"
    with MeasurementSession() as board:
        serial = board.get_board_serial()
        outdir = unit_dir(serial) / "phase_noise"
        outdir.mkdir(parents=True, exist_ok=True)
        lmx_locked(board, lo_hz)
        # TX filter: pass the LO, block the LMX's unwanted tone (2nd harmonic below the doubler crossover, VCO
        # fundamental above it) so neither the levelling nor Auto Tune can lock onto the wrong tone (user, 2026-10-04)
        bad_hz = unwanted_tone_hz(lo_hz)
        tx_filter, s21_lo, s21_bad = choose_tx_filter(lo_hz)
        if not board.set_tx_filter(tx_filter):
            raise RuntimeError(f"board rejected TX filter 0x{tx_filter:02X}")
        print(f"  TX filter 0x{tx_filter:02X}: S21 {s21_lo:+.1f} dB at the LO, {s21_bad:+.1f} dB at the unwanted "
              f"{bad_hz/1e9:g} GHz ({'2nd harmonic' if bad_hz > lo_hz else 'VCO fundamental'})")
        if args.leak == "sweep":
            drive_sweep(board, uxa, lo_hz, cable_db, outdir, stem)
            print("saved", outdir / f"{stem}_drive_sweep.csv")
            return 0
        if args.leak == "zero_dbm":
            i_v, q_v, level = level_to_zero_dbm(board, uxa, lo_hz, cable_db)
        else:
            i_v, q_v = 0.0, 0.0
            if not (board.set_i_v(0.0) and board.set_q_v(0.0)):
                raise RuntimeError("board rejected zero bias")
            sa_setup(uxa, lo_hz)
            level = sa_carrier_dbm(uxa, lo_hz, cable_db)
        print(f"Bias I_V {i_v:+.4f} V, Q_V {q_v:+.4f} V; LO leakage {level:+.2f} dBm at the "
              f"\"TX-side FR3 RF Out\" port (after the filter); lock {board.get_lmx_lock()}")
        # the unwanted tone at the port, with the same filter and bias, for the record
        bad_cable_db = CableLoss(args.cable).s21_db(bad_hz)
        sa_setup(uxa, bad_hz)
        bad_level = sa_carrier_dbm(uxa, bad_hz, bad_cable_db)
        print(f"  unwanted tone at {bad_hz/1e9:g} GHz: {bad_level:+.2f} dBm at the port "
              f"({level - bad_level:.1f} dB below the LO)")
        meta, rows = measure_log_plot(uxa, lo_hz, args.navg, level + cable_db)
        if abs(meta["carrier_hz"] - lo_hz) > MAX_CARRIER_FREQ_ERROR_HZ:
            raise RuntimeError(f"phase-noise app measured a carrier at {meta['carrier_hz']/1e9:.6f} GHz, not the "
                               f"{lo_hz/1e9:g} GHz LO - not saving this run")
        app_at_port = meta["carrier_dbm"] - cable_db
        if abs(app_at_port - level) > MAX_CARRIER_MISMATCH_DB:
            raise RuntimeError(f"phase-noise app carrier {app_at_port:+.2f} dBm vs Swept SA {level:+.2f} dBm at the "
                               f"port: analyzer overloaded or mis-ranged (attenuation {meta['atten_db']:g} dB) - "
                               f"not saving this run")
        meta.update({"lo_hz": lo_hz, "leak": args.leak, "i_v": i_v, "q_v": q_v,
                     "tx_filter": f"0x{tx_filter:02X}", "filter_s21_lo_db": s21_lo, "filter_s21_unwanted_db": s21_bad,
                     "unwanted_tone_hz": bad_hz, "unwanted_tone_dbm_at_port": bad_level,
                     "leak_dbm_at_port_sa": level, "cable": args.cable, "cable_s21_db": cable_db,
                     "pn_app_carrier_dbm_at_port": meta["carrier_dbm"] - cable_db,
                     "lmx_lock_after": board.get_lmx_lock(), "lmx_temperature_c": board.get_lmx_temperature_c(),
                     "unit_serial": serial, "time": datetime.now().isoformat(timespec="seconds")})
    with open(outdir / f"{stem}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["offset_hz", "trace1_dbc_hz", "trace2_dbc_hz"])
        w.writerows(rows)
    (outdir / f"{stem}.json").write_text(json.dumps(meta, indent=2))
    print(f"carrier at the port: SA {meta['leak_dbm_at_port_sa']:+.2f} dBm, phase-noise app "
          f"{meta['pn_app_carrier_dbm_at_port']:+.2f} dBm, at {meta['carrier_hz']/1e9:.6f} GHz; "
          f"{len(rows)} points; RMS PN {meta['rms_pn_deg']:.3f} deg")
    for target in (100, 1e3, 1e4, 1e5, 1e6):
        near = min(rows, key=lambda r: abs(r[0] - target))
        print(f"  {target:>9.0f} Hz: trace1 {near[1]:7.1f}  trace2 {near[2]:7.1f} dBc/Hz")
    print("saved", outdir / f"{stem}.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
