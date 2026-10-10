"""RX sensitivity/NF campaign for the Pi-Radio FR3-1ch board.

Phase 0: FieldFox source level at the end of the FR3 cable (source -> FR3 cable ->
         FieldFox RF input, board not involved), at every FR3 on the grid. Combine
         uses these readings as the input power, in place of -50 dBm + cable S21.
Phase 1: FieldFox's own noise floor (its RF input directly 50-ohm
         terminated, board not involved), at the 7 FR1 (IF) frequencies.
         This is the validation baseline: Phase 2's readings must sit well
         above this, or they're measuring the analyzer, not the board.
Phase 2: Cold RX-chain output noise (RX-side FR3 RF In terminated,
         RX-side FR1 IF Out -> FieldFox), across the dense (FR1, FR3,
         sideband) grid (see grid_points(): 427 points) -- the same LO every
         one of Phase 3's gain points uses, so every NF pairing is gain and
         noise measured at the identical LO.
Phase 3: Conversion gain (FieldFox source -> RX-side FR3 RF In at
         -50 dBm, RX-side FR1 IF Out -> FieldFox), same grid.

All noise/gain readings use the FieldFox's own hardware averaging in the
POWER domain (SENS:AVER:TYPE POW, count 100) -- not log averaging (biased
~2.5 dB low for noise) and not voltage averaging (biased ~1 dB low), and
not manual Python-side averaging.

Phase 1/2 use 0 dB attenuation and a -40 dBm reference level (maximum
sensitivity for very weak noise). Phase 3 uses 20 dB attenuation and a
+10 dBm reference level (the tone measured at this project's representative
point came back around +10 dBm; 0 dB/-30 dBm here overloaded the ADC).

Run the phases in order; each one prompts for the physical change it needs
before starting. Then combine the results:

    python rx_nf_campaign.py --phase 0
    python rx_nf_campaign.py --phase 1
    python rx_nf_campaign.py --phase 2
    python rx_nf_campaign.py --phase 3
    python rx_nf_campaign.py --phase combine
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np
from board import MeasurementSession
from fr3_gui.am3153_filter import FILTER_BANKS, get_response
from cables import CableLoss
from fieldfox import FieldFox
from results_layout import unit_dir

FF_HOST = "192.168.137.61"

FR1_LIST_HZ = [1.0e9, 1.5e9, 2.0e9, 2.5e9, 3.0e9, 3.5e9, 4.0e9]
FR3_GRID_HZ = [6.0e9 + 0.5e9 * k for k in range(42)]   # 6.0-26.5 GHz
LO_MIN_HZ, LO_MAX_HZ = 7.0e9, 22.5e9   # LO >= 7 GHz: user decision 2026-10-04 (was 8)
SIDEBANDS = ("low", "high")
# Phase 3 warns above this IF output level: -50 dBm in was linear to +/-0.15 dB up to
# ~+5 dBm out at the old grid's highest-gain point; -40 dBm in (+14.6 dBm out) compressed ~0.5 dB.
OVERLOAD_WARN_DBM = 5.0

# -40 dBm compressed the highest-gain point (FR1 1 GHz, FR3 7 GHz, ~55.9 dB gain, +14.6 dBm out)
# by ~0.5 dB (linearity check 2026-10-04); gain was flat to +/-0.15 dB from -45 to -60 dBm.
SOURCE_DBM = -50.0
RX_FILTER_BYPASS = 0x00
# The datasheet NF uses the RX filter in BYPASS (user decision 2026-10-04). The per-point
# "optimal" AM3153 filter (same rule as the GUI's Configuration Helper) is kept as an option
# (--filter optimal): its 3-11.5 dB loss sits after the LNA, so it raised NF 1.4-9.4 dB at
# 40 of 42 points (results/unit_005/rx_nf_campaign/optimal_filter_2026-10-04/).
FILTER_MODE = "bypass"              # set from --filter in main()
TX_TABLES = None                    # lo_cal_tables.CalTables when --tx-normal (2026-10-09 re-run)
LIMIT = 0                           # --limit: first N grid points only (quick test)
ONLY: set[str] = set()              # --only: "side:FR1:FR3" (GHz) points only (production tests)
FILTER_SCORE_BW_HZ = 0.5e9          # Configuration Helper's default bandwidth
MAX_DESIRED_DEGRADATION_DB = 3.0
N_AVERAGES = 100
SPAN_HZ = 1e6
# Directly validated against the physical on-screen averaging count (not extrapolated):
# at a 3.5s gap (actual ~3.71s), 10/10 restarts reliably reached the full count of 100.
# 4.0s adds a bit more margin beyond that confirmed-sufficient point.
AVERAGE_WAIT_S = 4.0
# Noise is read this far above FR1, clear of the board's on-frequency spur; the noise
# floor was flat to ~0.3 dB from 100 to 400 kHz off center.
NOISE_OFFSET_HZ = 200e3

# Fixed rather than auto, so every phase uses the same RBW; 10 kHz also keeps the comb line
# at FR1 well outside the noise marker at FR1 + 200 kHz.
RBW_HZ = 10e3

NOISE_REF_DBM = -40.0
NOISE_ATTEN_DB = 0.0
GAIN_REF_DBM = 10.0
GAIN_ATTEN_DB = 20.0


def must(ok: bool, what: str) -> None:
    if not ok:
        raise RuntimeError(f"board rejected: {what}")


def lo_for(fr3_hz: float, fr1_hz: float, sideband: str) -> float:
    return fr3_hz - fr1_hz if sideband == "low" else fr3_hz + fr1_hz


def grid_points() -> list[dict]:
    """The dense (FR1, FR3, sideband) grid shared by Phases 2 and 3 (user spec 2026-10-04):
    FR1 1-4 GHz and FR3 6-26.5 GHz in 0.5 GHz steps, both sidebands, kept only where
    LO_MIN_HZ <= LO <= LO_MAX_HZ -> 427 points (224 low side, 203 high side)."""
    points = []
    for fr1 in FR1_LIST_HZ:
        for sideband in SIDEBANDS:
            for fr3 in FR3_GRID_HZ:
                lo = lo_for(fr3, fr1, sideband)
                if not LO_MIN_HZ - 1.0 <= lo <= LO_MAX_HZ + 1.0:
                    continue
                pt = {"fr1_hz": fr1, "fr3_hz": fr3, "sideband": sideband, "lo_hz": lo}
                bits = optimal_rx_filter(pt) if FILTER_MODE == "optimal" else RX_FILTER_BYPASS
                pt["rx_filter"] = f"0x{bits:02X}"
                if ONLY and f"{sideband}:{fr1 / 1e9:g}:{fr3 / 1e9:g}" not in ONLY:
                    continue
                points.append(pt)
    return points


def _band_mean_power(response, lo_hz: float, hi_hz: float) -> float:
    """Mean linear power over [lo_hz, hi_hz] (as in configuration_helper)."""
    mask = (response.freq_hz >= lo_hz) & (response.freq_hz <= hi_hz)
    return float(np.mean(10.0 ** (response.s21_db[mask] / 10.0))) if np.any(mask) else 0.0


def optimal_rx_filter(pt: dict) -> int:
    """The datasheet's "optimal" AM3153 filter for this grid point: desired band at FR3,
    image at the other side of the LO."""
    desired = pt["fr3_hz"]
    image = 2.0 * pt["lo_hz"] - pt["fr3_hz"]
    half = FILTER_SCORE_BW_HZ / 2.0
    candidates = []
    for _, bank_nibble in FILTER_BANKS:
        if bank_nibble == 0x0:  # Bypass excluded
            continue
        for config_nibble in range(16):
            bits = (bank_nibble << 4) | config_nibble
            resp = get_response(bits)
            candidates.append((bits, _band_mean_power(resp, desired - half, desired + half),
                               _band_mean_power(resp, image - half, image + half)))
    floor = max(c[1] for c in candidates) / 10.0 ** (MAX_DESIRED_DEGRADATION_DB / 10.0)
    return min((c for c in candidates if c[1] >= floor), key=lambda c: c[2])[0]


def configure_board_rx(board, lo_hz: float, rx_filter: int = RX_FILTER_BYPASS, fr3_hz: float | None = None) -> None:
    must(board.set_clock_internal(True), "SET CLOCK INT")
    must(board.set_lo_internal(True), "SET LO INT")
    # 2026-10-09 hot RX re-run: the LMX drive rule (lmx_drive.py) instead of the old fixed drive 7
    from lmx_drive import set_drive_for
    set_drive_for(board, lo_hz)
    must(board.lmx_tune(lo_hz), f"LMX TUNE {lo_hz:.0f}")
    for _ in range(40):
        if board.get_lmx_lock() == "LOCKED":
            break
        time.sleep(0.25)
    else:
        raise RuntimeError(f"LMX not LOCKED after tune to {lo_hz/1e9:g} GHz")
    must(board.set_rx_filter(rx_filter), f"SET RXFILTER 0x{rx_filter:02X}")
    if TX_TABLES is not None and fr3_hz is not None:     # the TX side in normal use (rx_tx_side.py), 2026-10-09
        from rx_tx_side import tx_normal_state
        tx_normal_state(board, TX_TABLES, fr3_hz, lo_hz)


def setup_ff_common(ff: FieldFox, ref_level_dbm: float, atten_db: float) -> None:
    """Sets up the FieldFox for a phase. Deliberately does NOT call
    fieldfox.setup_spectrum_analyzer() - that shared helper sends
    INIT:CONT OFF, which is never to be sent to this instrument, full stop
    (explicit, repeated standing instruction: "NEVER EVER SET CONT TO OFF.
    EVER."). Continuous sweep stays ON for the entire run; averaging is
    restarted per-point with TRAC1:REST and read after a fixed, directly
    validated wait (AVERAGE_WAIT_S), not by looping single-sweep triggers in
    INIT:CONT OFF mode the way other scripts in this project do."""
    ff.write("*CLS")
    ff.select_mode("SA")
    ff.write(f"SENS:FREQ:SPAN {ff.span_hz:.0f}")
    ff.set_rbw(RBW_HZ)
    ff.write(f"DISP:WIND:TRAC:Y:RLEV {ref_level_dbm:.1f}")
    ff.write("CALC:MARK1:STAT NORM")
    ff.write("INIT:CONT ON")
    ff.check("basic SA setup (continuous sweep ON, never OFF)")
    ff.source_enable(False)
    ff.set_attenuation(atten_db)
    # Front panel "Trace -> State -> Average" = TRAC1:TYPE AVG (confirmed: the
    # SCPI abbreviation is AVG, not AVER/AVERAGE - both of those are rejected).
    ff.write("TRAC1:TYPE AVG")
    ff.check("set trace type to AVG (true hardware trace averaging)")
    ff.write("SENS:AVER:TYPE POW")
    ff.check("set averaging type to POW (true power-domain, not log/voltage)")
    ff.write(f"SENS:AVER:COUN {N_AVERAGES}")
    ff.check("set averaging count")
    print(f"FieldFox: ref {ref_level_dbm:+.0f} dBm, attenuation {ff.attenuation_db:.0f} dB, "
          f"RBW {ff.rbw_hz / 1e3:g} kHz, "
          f"continuous sweep ON, trace type AVG, averaging TYPE POW COUNT {N_AVERAGES}, "
          f"wait {AVERAGE_WAIT_S:.1f}s per point")


def averaged_noise_dbm_hz(ff: FieldFox, center_hz: float) -> tuple[float, float]:
    """Noise-marker reading, averaged N_AVERAGES times in the power domain
    by the FieldFox itself, via continuous sweep + TRAC1:REST + a fixed wait
    (never INIT:CONT OFF). Deliberately NOT peak-searched: noise is a flat
    random process across the span, so FUNC:MAX would just pick out
    whichever bin happened to fluctuate highest, biasing the reading high
    rather than reporting the true average noise density. Read at the exact
    requested frequency instead, with the marker position set explicitly.

    Critical ordering: the marker's X position MUST be set AFTER the wait,
    not before. Setting it right after a retune (before any sweep has run
    at that center) silently clamps the marker to the edge of the still-stale
    trace instead of the requested frequency - confirmed empirically
    (readback showed the window's start frequency instead of the requested
    center) - which then makes CALC:MARK1:Y? return a meaningless 0.0 with
    no SCPI error raised anywhere.

    Returns (noise at center + NOISE_OFFSET_HZ, reading exactly at center).
    The board emits a narrow spur exactly at round output frequencies (seen
    ~16-20 dB above the floor at 3.000 GHz), so the offset reading is the noise
    value; the on-center one is kept only to flag where a spur sits."""
    ff.tune(center_hz)
    ff.write("CALC:MARK1:NOIS:STAT ON")
    ff.check("enable noise marker")
    ff.write("TRAC1:REST")
    ff.check("restart averaging")
    time.sleep(AVERAGE_WAIT_S)
    readings = []
    for f in (center_hz + NOISE_OFFSET_HZ, center_hz):
        ff.write(f"CALC:MARK1:X {f:.0f}")
        ff.check("set marker frequency (after the wait, not before)")
        readings.append(float(ff.query("CALC:MARK1:Y?")))
        ff.check("read averaged noise marker")
    ff.write("CALC:MARK1:NOIS:STAT OFF")
    ff.check("disable noise marker")
    return readings[0], readings[1]


def averaged_tone_reading(ff: FieldFox, center_hz: float) -> tuple[float, float]:
    """Tone (frequency, power), averaged N_AVERAGES times in the power
    domain via continuous sweep + TRAC1:REST + a fixed wait, with a peak
    search on the averaged trace. Re-centers and re-averages once if the
    peak lands far from center (the FieldFox and the board run on
    independent clocks, so the tone drifts within the span) -- same
    drift-tolerant behavior as fieldfox.measure_at(), just with hardware
    averaging instead of a single sweep, and never INIT:CONT OFF."""
    def one_pass(c: float) -> tuple[float, float]:
        ff.tune(c)
        ff.write("TRAC1:REST")
        ff.check("restart averaging")
        time.sleep(AVERAGE_WAIT_S)
        ff.write("CALC:MARK1:FUNC:MAX")
        f = float(ff.query("CALC:MARK1:X?"))
        p = float(ff.query("CALC:MARK1:Y?"))
        ff.check("read averaged tone marker")
        return f, p

    freq, power = one_pass(center_hz)
    if abs(freq - center_hz) > 0.25 * ff.span_hz:
        freq, power = one_pass(freq)
    return freq, power


def write_csv(path: Path, rows: list[dict]) -> None:
    if rows:
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


PHASE0_FR3_HZ = FR3_GRID_HZ


def run_phase0(outdir: Path, fr3_cable: CableLoss) -> None:
    """Source loopback: FieldFox source -> FR3 cable -> FieldFox RF input (board not involved).
    The reading is the power that actually arrives at the end of the FR3 cable, i.e. at
    RX-side FR3 RF In in Phase 3, read with Phase 3's exact analyzer settings. The cable file
    is only used to report how far the source itself is from its commanded level."""
    print("\n=== PHASE 0: FieldFox source level at the end of the FR3 cable ===")
    print("Assuming FieldFox source -> FR3 cable -> FieldFox RF input, board not connected, "
          "confirmed by the user before this script was run.")
    rows = []
    with FieldFox(FF_HOST, span_hz=SPAN_HZ) as ff:
        setup_ff_common(ff, GAIN_REF_DBM, GAIN_ATTEN_DB)
        try:
            for fr3 in PHASE0_FR3_HZ:
                ff.source_configure(fr3, SOURCE_DBM)
                ff.source_enable(True)
                time.sleep(0.3)
                freq, power = averaged_tone_reading(ff, fr3)
                ff.source_enable(False)
                s21 = fr3_cable.s21_db(fr3)
                src_err = power - s21 - SOURCE_DBM
                print(f"  FR3 {fr3/1e9:5.2f} GHz: at cable end {power:7.2f} dBm "
                      f"(nominal {SOURCE_DBM + s21:7.2f}), cable {s21:6.2f} dB, "
                      f"source error {src_err:+5.2f} dB")
                rows.append({"fr3_hz": fr3, "source_dbm": SOURCE_DBM,
                             "measured_at_cable_end_dbm": round(power, 3),
                             "marker_freq_hz": round(freq, 1), "s21_fr3_db": round(s21, 3),
                             "nominal_at_cable_end_dbm": round(SOURCE_DBM + s21, 3),
                             "source_error_db": round(src_err, 3)})
        finally:
            ff.source_enable(False)
            print(f"FieldFox source OFF confirmed: {not ff.source_state()}")
    write_csv(outdir / "phase0_source_loopback.csv", rows)
    print(f"Saved {outdir / 'phase0_source_loopback.csv'}")


def run_phase1(outdir: Path) -> None:
    print("\n=== PHASE 1: FieldFox's own noise floor ===")
    print("Assuming FieldFox RF input is directly 50-ohm terminated (no cable, no DUT), "
          "confirmed by the user before this script was run.")
    rows = []
    with FieldFox(FF_HOST, span_hz=SPAN_HZ) as ff:
        print("FieldFox:", ff.identify())
        setup_ff_common(ff, NOISE_REF_DBM, NOISE_ATTEN_DB)
        for fr1 in FR1_LIST_HZ:
            val, on_center = averaged_noise_dbm_hz(ff, fr1)
            print(f"  FR1 {fr1/1e9:4.1f} GHz: {val:8.2f} dBm/Hz  (on center {on_center:8.2f})")
            rows.append({"fr1_hz": fr1, "ff_own_noise_dbm_hz": round(val, 3),
                         "on_center_dbm_hz": round(on_center, 3)})
    write_csv(outdir / "phase1_ff_noise_floor.csv", rows)
    print(f"Saved {outdir / 'phase1_ff_noise_floor.csv'}")


def run_phase2(board, outdir: Path) -> None:
    print(f"\n=== PHASE 2: Cold RX-chain output noise (full {len(grid_points())}-point grid) ===")
    print("Assuming RX-side FR3 RF In is 50-ohm terminated and RX-side FR1 IF Out is "
          "connected to the FieldFox's RF input, confirmed by the user before this "
          "script was run.")
    rows = []
    points = grid_points()[:LIMIT] if LIMIT else grid_points()
    with FieldFox(FF_HOST, span_hz=SPAN_HZ) as ff:
        setup_ff_common(ff, NOISE_REF_DBM, NOISE_ATTEN_DB)
        for i, pt in enumerate(points):
            configure_board_rx(board, pt["lo_hz"], int(pt["rx_filter"], 16), pt["fr3_hz"])
            val, on_center = averaged_noise_dbm_hz(ff, pt["fr1_hz"])
            print(f"  [{i+1:2d}/{len(points)}] FR1 {pt['fr1_hz']/1e9:4.2f} GHz  "
                  f"FR3 {pt['fr3_hz']/1e9:5.2f} GHz  {pt['sideband']:4s}  "
                  f"LO {pt['lo_hz']/1e9:5.2f} GHz  lock {board.get_lmx_lock()}: "
                  f"{val:8.2f} dBm/Hz  (on center {on_center:8.2f}, "
                  f"{on_center - val:+5.2f} dB)")
            rows.append({**pt, "cold_noise_dbm_hz": round(val, 3),
                         "on_center_dbm_hz": round(on_center, 3),
                         "lmx_lock": board.get_lmx_lock(),
                         "lmx_temperature_c": round(board.get_lmx_temperature_c(), 1)})
            write_csv(outdir / "phase2_cold_noise.csv", rows)
    write_csv(outdir / "phase2_cold_noise.csv", rows)
    print(f"Saved {outdir / 'phase2_cold_noise.csv'}")


def run_phase3(board, outdir: Path, fr1_cable: CableLoss, fr3_cable: CableLoss) -> None:
    print(f"\n=== PHASE 3: Conversion gain (full {len(grid_points())}-point grid) ===")
    print("Assuming the termination is removed from RX-side FR3 RF In and the FieldFox's "
          "source output is connected there instead, with RX-side FR1 IF Out still "
          "connected to the FieldFox's RF input, confirmed by the user before this "
          "script was run.")
    rows = []
    points = grid_points()[:LIMIT] if LIMIT else grid_points()
    with FieldFox(FF_HOST, span_hz=SPAN_HZ) as ff:
        setup_ff_common(ff, GAIN_REF_DBM, GAIN_ATTEN_DB)
        try:
            for i, pt in enumerate(points):
                configure_board_rx(board, pt["lo_hz"], int(pt["rx_filter"], 16), pt["fr3_hz"])
                ff.source_configure(pt["fr3_hz"], SOURCE_DBM)
                ff.source_enable(True)
                time.sleep(0.3)
                freq, power = averaged_tone_reading(ff, pt["fr1_hz"])
                ff.source_enable(False)

                s21_fr3 = fr3_cable.s21_db(pt["fr3_hz"])
                s21_fr1 = fr1_cable.s21_db(pt["fr1_hz"])
                p_in = SOURCE_DBM + s21_fr3
                p_out = power - s21_fr1
                gain_db = p_out - p_in
                overload = p_out > OVERLOAD_WARN_DBM
                print(f"  [{i+1:3d}/{len(points)}] FR1 {pt['fr1_hz']/1e9:4.2f} GHz  "
                      f"FR3 {pt['fr3_hz']/1e9:5.2f} GHz  {pt['sideband']:4s}  "
                      f"LO {pt['lo_hz']/1e9:5.2f} GHz  lock {board.get_lmx_lock()}: "
                      f"gain {gain_db:+7.2f} dB, out {p_out:+6.2f} dBm"
                      + (f"  *** ABOVE {OVERLOAD_WARN_DBM:+.0f} dBm - may be compressing ***"
                         if overload else ""))
                rows.append({**pt, "source_dbm": SOURCE_DBM,
                             "measured_ff_dbm": round(power, 3),
                             "marker_freq_hz": round(freq, 1),
                             "s21_fr3_db": round(s21_fr3, 3), "s21_fr1_db": round(s21_fr1, 3),
                             "p_in_at_dut_dbm": round(p_in, 3), "p_out_at_dut_dbm": round(p_out, 3),
                             "gain_db": round(gain_db, 3), "overload_warning": overload,
                             "lmx_lock": board.get_lmx_lock(),
                             "lmx_temperature_c": round(board.get_lmx_temperature_c(), 1)})
                write_csv(outdir / "phase3_gain.csv", rows)
        finally:
            # Deliberately not calling restore_instrument_state(): each phase/iteration
            # sets up exactly the FieldFox state it needs rather than reverting to
            # whatever was found at the start of the connection. Source off is a safety
            # action (don't leave RF transmitting unattended), not a state restore.
            ff.source_enable(False)
            print(f"FieldFox source OFF confirmed: {not ff.source_state()}")
    write_csv(outdir / "phase3_gain.csv", rows)
    print(f"Saved {outdir / 'phase3_gain.csv'}")


def combine_and_compute_nf(outdir: Path) -> None:
    """Pairs Phase 2 (noise) and Phase 3 (gain) rows at matching grid
    points, computes NF, and reports each point's margin above Phase 1's
    FF-only noise floor as a trust check."""
    def load(path: Path) -> list[dict]:
        with open(path, newline="") as f:
            return list(csv.DictReader(f))

    phase1 = {float(r["fr1_hz"]): float(r["ff_own_noise_dbm_hz"])
              for r in load(outdir / "phase1_ff_noise_floor.csv")}
    phase2 = load(outdir / "phase2_cold_noise.csv")
    phase3 = load(outdir / "phase3_gain.csv")
    # Input power at RX-side FR3 RF In = Phase 0's reading at the end of the FR3 cable;
    # where the dips were re-measured (phase0_repeat_dips.csv), the repeats' mean is used.
    p_in_meas = {float(r["fr3_hz"]): float(r["measured_at_cable_end_dbm"])
                 for r in load(outdir / "phase0_source_loopback.csv")}
    repeats_path = outdir / "phase0_repeat_dips.csv"
    if repeats_path.exists():
        by_f: dict[float, list[float]] = {}
        for r in load(repeats_path):
            by_f.setdefault(float(r["fr3_hz"]), []).append(float(r["measured_at_cable_end_dbm"]))
        p_in_meas.update({f: sum(v) / len(v) for f, v in by_f.items()})

    def key(r: dict) -> tuple[str, str, str]:
        return (r["fr1_hz"], r["fr3_hz"], r["sideband"])

    gain_by_key = {key(r): r for r in phase3}
    rows = []
    for n in phase2:
        g = gain_by_key.get(key(n))
        if g is None:
            continue
        fr1, fr3 = float(n["fr1_hz"]), float(n["fr3_hz"])
        noise_dbm_hz = float(n["cold_noise_dbm_hz"])
        match = [f for f in p_in_meas if abs(f - fr3) < 1e3]
        if not match:
            raise RuntimeError(f"Phase 0 has no reading at FR3 {fr3/1e9:g} GHz - rerun Phase 0")
        p_in = p_in_meas[match[0]]
        p_in_correction = p_in - float(g["p_in_at_dut_dbm"])   # vs -50 dBm + cable S21
        gain_db = float(g["p_out_at_dut_dbm"]) - p_in
        ff_floor = phase1.get(fr1)
        margin_db = None if ff_floor is None else noise_dbm_hz - ff_floor
        # Corrections (user, 2026-10-09; before this the NF came out 0.5-1.1 dB too low):
        # 1) the FieldFox's own noise floor (Phase 1) adds to every reading: subtract it in linear power;
        # 2) the noise is read at the far end of the FR1 cable, but the gain is referred to the unit's connectors
        #    (p_out_at_dut_dbm is cable-corrected): refer the noise to the "RX-side FR1 IF Out" connector too.
        if ff_floor is not None:
            if margin_db <= 0.5:
                raise RuntimeError(f"noise at FR1 {fr1/1e9:g} / FR3 {fr3/1e9:g} GHz is within 0.5 dB of the FieldFox floor")
            noise_unit_ff = 10 * np.log10(10 ** (noise_dbm_hz / 10) - 10 ** (ff_floor / 10))
        else:
            noise_unit_ff = noise_dbm_hz
        s21_fr1 = float(g["s21_fr1_db"])
        noise_at_dut = noise_unit_ff - s21_fr1                       # s21 is negative: adds the cable loss back
        nf_db = noise_at_dut - gain_db + 174.0
        rows.append({
            "fr1_hz": n["fr1_hz"], "fr3_hz": n["fr3_hz"], "sideband": n["sideband"],
            "lo_hz": n["lo_hz"], "rx_filter": n.get("rx_filter", ""),
            "cold_noise_dbm_hz": n["cold_noise_dbm_hz"],
            "noise_minus_ff_floor_dbm_hz": round(noise_unit_ff, 3), "s21_fr1_db": round(s21_fr1, 3),
            "noise_at_dut_dbm_hz": round(noise_at_dut, 3),
            "p_in_measured_dbm": round(p_in, 3), "p_in_correction_db": round(p_in_correction, 3),
            "gain_nominal_db": g["gain_db"], "gain_db": round(gain_db, 3),
            "overload_warning": g.get("overload_warning", ""), "nf_db": round(nf_db, 2),
            "ff_own_noise_floor_dbm_hz": ff_floor,
            "margin_above_ff_floor_db": None if margin_db is None else round(margin_db, 2),
        })
    write_csv(outdir / "nf_results.csv", rows)
    print(f"\nSaved {outdir / 'nf_results.csv'} ({len(rows)} points)\n")
    for r in rows:
        flag = ""
        if r["margin_above_ff_floor_db"] is not None and r["margin_above_ff_floor_db"] < 10.0:
            flag = "  *** LOW MARGIN above FF's own noise floor - NF may be inflated ***"
        print(f"  FR1 {float(r['fr1_hz'])/1e9:4.2f} GHz  FR3 {float(r['fr3_hz'])/1e9:5.2f} GHz  "
              f"{r['sideband']:4s}: NF {r['nf_db']:>6} dB{flag}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("0", "1", "2", "3", "combine"), required=True)
    parser.add_argument("--allow-unserialized", action="store_true")
    parser.add_argument("--filter", choices=("bypass", "optimal"), default="bypass",
                        help="RX filter for Phases 2-3 (datasheet uses bypass)")
    parser.add_argument("--campaign", default="rx_nf_campaign",
                        help="results sub-folder of results/unit_<n>/ (keep separate runs apart; the default is the "
                             "datasheet's filter-bypassed campaign)")
    parser.add_argument("--tx-normal", action="store_true",
                        help="put the TX side in normal use at every point (stored LO-null bias, IQ, optimal TX filter)")
    parser.add_argument("--limit", type=int, default=0, help="first N grid points only (quick test)")
    parser.add_argument("--only", default="", help="only these points, e.g. low:1:9,high:2:14 (side:FR1:FR3 in GHz)")
    args = parser.parse_args()
    global FILTER_MODE, TX_TABLES, LIMIT, ONLY
    ONLY = set(x for x in args.only.split(",") if x)
    FILTER_MODE = args.filter
    LIMIT = args.limit
    if args.tx_normal:
        from lo_cal_tables import CalTables
        TX_TABLES = CalTables()

    if args.phase == "combine":
        candidates = sorted(Path("results").glob(f"unit_*/{args.campaign}"))
        if len(candidates) != 1:
            raise RuntimeError(f"expected exactly one results/unit_*/{args.campaign} folder, found {len(candidates)}")
        combine_and_compute_nf(candidates[0])
        return 0

    fr1_cable = CableLoss("fr1_cable")
    fr3_cable = CableLoss("fr3_cable")

    with MeasurementSession() as board:
        serial = board.get_board_serial()
        if serial == 0 and not args.allow_unserialized:
            raise RuntimeError("board serial is 0 - pass --allow-unserialized")
        outdir = unit_dir(serial) / args.campaign
        outdir.mkdir(parents=True, exist_ok=True)
        print(f"Unit #{serial}. Results: {outdir}")

        if args.phase == "0":
            run_phase0(outdir, fr3_cable)
        elif args.phase == "1":
            run_phase1(outdir)
        elif args.phase == "2":
            run_phase2(board, outdir)
        else:
            run_phase3(board, outdir, fr1_cable, fr3_cable)
    return 0


if __name__ == "__main__":
    sys.exit(main())
