"""Spurious outputs of the Pi-Radio FR3-1ch unit (datasheet section "Spurious Outputs", user spec 2026-10-05).

    python spur_campaign.py --phase tx      [--limit N] [--filters optimal,bypass]   (A1 + A2)
    python spur_campaign.py --phase rx_lo                                              (B)
    python spur_campaign.py --phase rx_resp [--limit N] [--filters optimal,bypass]   (C2)
    python spur_campaign.py --phase <any> --dry-run      (test points + rough time; touches no instrument)

HOOKUPS (the script never asks: confirm the hookup with the user before running a phase)
  tx       FieldFox source (port 1) -> FR1 cable -> "TX-side FR1 IF In";  "TX-side FR3 RF Out" -> FR3 cable -> FieldFox input
  rx_lo    "RX-side FR3 RF In" -> FR3 cable -> FieldFox input.  Nothing else connected; the source stays OFF (read back).
  rx_resp  FieldFox source -> FR3 cable -> "RX-side FR3 RF In";  "RX-side FR1 IF Out" -> FR1 cable -> FieldFox input

A1  TX, no input (source off): survey of the whole analyzer range; every line above the floor, absolute dBm at the connector.
A2  TX, CW tone in at FR1, at an input level 5 dB below this configuration's own input P1dB (measured first by a power ramp:
    from -60 dBm, 2 dB steps, 0.5 dB steps once compression passes 0.3 dB, stop at 5 dB compression or at the 0 dBm TX
    input limit). Survey again; spurs in dBc relative to the wanted output. The wanted tone, the unwanted sideband and the
    LO are excluded from the "worst spur" (they have their own datasheet sections).
B   RX, LO leakage coming out of "RX-side FR3 RF In": LO, LO/2 and 2*LO (where <= 26.5 GHz) at every LO, 7-22.6 GHz in
    100 MHz steps; filter bypassed and "optimal" (for FR1 = 2 GHz, low- and high-side).
C2  RX spurious responses: at each configuration, the input level is 5 dB below that configuration's own input P1dB
    (ramp as above, never above -5 dBm at the RX input). A CW tone is then placed, one at a time, at every input frequency f
    that a low-order mixing product |m*LO + n*f| = FR1 (|m| <= 4, 1 <= n <= 5) maps onto the IF, and the IF output at FR1 is
    read. Rejection = wanted IF output - IF output at f. The wanted input and the image are excluded (own sections).

Readings: continuous sweep always (never INIT:CONT OFF); trace average restarted (TRAC1:REST) and read after enough sweeps;
peak-search marker before every reading; the board and analyzer clocks are independent, so a marker re-centres once.
Every line found is re-read with 10 dB more input attenuation: a line from the unit keeps its level, a line made inside the
analyzer does not -- only lines that pass are counted. Products with |n| >= 2 can include the FieldFox source's own
harmonics (no low-pass filter on the source), so they are flagged: their measured level is conservative.

Results: results/unit_<serial>/spurs_<YYYYMMDD>/ -- <phase>_configs.csv, <phase>_lines.csv, <phase>_ramps.csv (tracked in
git), survey traces in surveys/*.npz (local only). Resumable per configuration. Source read back OFF at the end.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from board import MeasurementSession
from cables import CableLoss
from compression import compression_point, small_signal_gain
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, SOURCE_POWER_RANGE_DBM, FieldFox
from results_layout import unit_dir
from rx_nf_campaign import optimal_rx_filter

FF_HOST = "192.168.137.61"
FF_MAX_HZ = 26.5e9
LO_MIN_HZ, LO_MAX_HZ = 7.0e9, 22.6e9
TX_INPUT_LIMIT_DBM, RX_INPUT_LIMIT_DBM = 0.0, -5.0       # absolute maximum ratings at the connector (Table 1.2)
BACKOFF_DB = 5.0                                          # drive = input P1dB - 5 dB (user, 2026-10-05)
RAMP_START_DBM, COARSE_DB, FINE_DB, FINE_FROM_DB, RAMP_STOP_DB = -60.0, 2.0, 0.5, 0.3, 5.0
ATT_DB, ATT_CHECK_DB, REF_DBM = 20.0, 30.0, 20.0         # strong outputs (TX RF out, RX IF out)
ATT_QUIET_DB, REF_QUIET_DBM = 0.0, -20.0                  # B: only weak leakage arrives, nothing strong
SURVEY_START_HZ, SEG_HZ, SURVEY_POINTS, SURVEY_RBW = 0.1e9, 1.0e9, 10001, 100e3
DETECT_DB = 10.0                                          # survey line must stand this far above the local floor
MARK_SPAN, MARK_RBW, MARK_AVG = 1e6, 10e3, 4
VERIFY_TOL_DB = 3.0
REF_TABLES = ("golden_lo_null_5MHz_20260927", "lo_null_hot_5MHz_20261004")   # cold, hot LO-null tables (Section 9)


# ------------------------------------------------------------------------------------------------ test points
def tx_points(filters) -> list[dict]:
    los = [7e9 + 1e9 * k for k in range(16)]                      # 7 ... 22 GHz
    pts = [(2.0e9, lo, sb) for lo in los for sb in ("upper", "lower")]
    pts += [(fr1, lo, sb) for fr1 in (1.0e9, 3.5e9) for lo in (8e9, 14e9, 20e9) for sb in ("upper", "lower")]
    out = []
    for fr1, lo, sb in pts:
        fr3 = lo + fr1 if sb == "upper" else lo - fr1
        if not 6e9 - 1 <= fr3 <= FF_MAX_HZ + 1:
            continue
        for filt in filters:
            bits = 0x00 if filt == "bypass" else optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})
            out.append({"fr1_hz": fr1, "lo_hz": lo, "fr3_hz": fr3, "config": sb, "filter": filt, "bits": bits})
    return out


def rx_resp_points(filters) -> list[dict]:
    out = []
    for lo in (8e9, 12e9, 16e9, 20e9):
        for side in ("low", "high"):
            fr1 = 2.0e9
            fr3 = lo + fr1 if side == "low" else lo - fr1
            for filt in filters:
                bits = 0x00 if filt == "bypass" else optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})
                out.append({"fr1_hz": fr1, "lo_hz": lo, "fr3_hz": fr3, "config": side, "filter": filt, "bits": bits})
    return out


def rx_lo_points() -> list[dict]:
    out = []
    for k in range(157):                                         # 7.0 ... 22.6 GHz in 100 MHz steps
        lo = 7e9 + 1e8 * k
        filts = [("bypass", 0x00)]
        for side in ("low", "high"):
            fr3 = lo + 2e9 if side == "low" else lo - 2e9
            if 6e9 <= fr3 <= FF_MAX_HZ:
                filts.append((f"optimal_{side}", optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})))
        out += [{"lo_hz": lo, "filter": f, "bits": b} for f, b in filts]
    return out


def key(p) -> str:
    return "|".join(f"{p[k]:.0f}" if isinstance(p[k], float) else str(p[k]) for k in sorted(p) if k != "bits")


# ------------------------------------------------------------------------------------------------ labelling
def label(f, lo, fr1) -> tuple[str, int]:
    """Lowest-order |m*LO + n*FR1| (|m| <= 4, |n| <= 6) or k*LO/2 matching f within 3 MHz -> (name, |n|)."""
    best = None
    for m in range(0, 5):
        for n in range(-6, 7):
            if m == 0 and n <= 0:
                continue
            if abs(abs(m * lo + n * fr1) - f) < 3e6 and (best is None or m + abs(n) < best[0]):
                best = (m + abs(n), m, n)
    if best:
        _, m, n = best
        lo_s = "" if m == 0 else ("LO" if m == 1 else f"{m}LO")
        fr_s = "" if n == 0 else (("+" if n > 0 and m else "") + ("" if abs(n) == 1 else str(abs(n))) + "FR1")
        if n < 0:
            fr_s = "-" + fr_s.lstrip("+")
        name = (lo_s + fr_s) if m * lo + n * fr1 >= 0 else f"{('' if abs(n) == 1 else abs(n))}FR1-{lo_s}"
        return name, abs(n)
    for k in (1, 3, 5):
        if abs(k * lo / 2 - f) < 3e6:
            return ("LO/2" if k == 1 else f"{k}LO/2"), 0
    return "unidentified", 0


def tx_predicted(lo, fr1, with_input: bool) -> list[float]:
    fs = {k * lo / 2 for k in (1, 3, 5)} | {m * lo for m in (2, 3)}
    if with_input:
        fs |= {abs(m * lo + n * fr1) for m in range(0, 5) for n in range(-5, 6) if not (m == 0 and n <= 0)}
    return sorted(f for f in fs if SURVEY_START_HZ <= f <= FF_MAX_HZ - MARK_SPAN)


# ------------------------------------------------------------------------------------------------ FieldFox
def ff_setup(ff: FieldFox, att_db: float, ref_dbm: float) -> int:
    """SA mode, continuous sweep ON (never OFF), power averaging, fixed attenuation, tracking OFF, source OFF."""
    ff.write("*CLS")
    ff.select_mode("SA")
    orig_points = int(float(ff.query("SENS:SWE:POIN?")))
    ff.source_enable(False)
    for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF"):
        ff.write(c)
    ff._saved_attenuation = (ff.query("SENS:POW:ATT:AUTO?") in ("1", "ON"), ff.attenuation_db)
    ff.set_attenuation(att_db)
    ff.write(f"DISP:WIND:TRAC:Y:RLEV {ref_dbm:.1f}")
    ff.write("SENS:BAND:VID:AUTO ON")
    ff.write("FORM:DATA ASCii,0")
    ff.write("TRAC1:TYPE AVG")
    ff.write("SENS:AVER:TYPE POW")
    ff.write("CALC:MARK1:STAT NORM")
    ff.write("INIT:CONT ON")
    errs = ff.errors()
    if errs:
        raise RuntimeError(f"FieldFox rejected the set-up: {errs}")
    return orig_points


def restore_ff(ff: FieldFox, orig_points) -> bool:
    ff.source_enable(False)
    for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF", "SENS:BAND:RES:AUTO ON", "TRAC1:TYPE CLRW"):
        ff.write(c)
    if orig_points:
        ff.write(f"SENS:SWE:POIN {orig_points}")
    ff.write("SENS:FREQ:SPAN 1000000")
    ff.restore_instrument_state()                                  # leaves INIT:CONT ON
    time.sleep(SETTLE_S)
    return not ff.source_state()


def _wait_average(ff: FieldFox, n: int) -> None:
    ff.write(f"SENS:AVER:COUN {n}")
    time.sleep(SETTLE_S)
    t = float(ff.query("SENS:SWE:MTIM?"))
    ff.write("TRAC1:REST")
    time.sleep(max(0.3, 1.5 * (n + 1) * t))


def _trace(ff: FieldFox, points: int) -> np.ndarray:
    for _ in range(10):
        tr = np.array([float(v) for v in ff.query("TRAC1:DATA?").split(",")])
        if tr.size == points:
            return tr
        _wait_average(ff, 1)
    raise RuntimeError(f"trace has {tr.size} points, expected {points}")


def marker(ff: FieldFox, f_hz: float, avg: int = MARK_AVG) -> tuple[float, float, float]:
    """(frequency, level, floor) of the strongest line within MARK_SPAN of f_hz -- raw analyzer dBm. Re-centres once."""
    for attempt in range(2):
        ff.write(f"SENS:FREQ:CENT {f_hz:.0f}")
        ff.write(f"SENS:FREQ:SPAN {MARK_SPAN:.0f}")
        ff.write(f"SENS:BAND:RES {MARK_RBW:.0f}")
        ff.write("SENS:SWE:POIN 401")
        time.sleep(SETTLE_S)
        _wait_average(ff, avg)
        ff.write("CALC:MARK1:FUNC:MAX")
        fx, p = float(ff.query("CALC:MARK1:X?")), float(ff.query("CALC:MARK1:Y?"))
        floor = float(np.median(_trace(ff, 401)))
        if attempt == 0 and abs(fx - f_hz) > 0.25 * MARK_SPAN and p > floor + 10:
            f_hz = fx
            continue
        return fx, p, floor
    return fx, p, floor


def survey(ff: FieldFox, start: float, stop: float) -> tuple[np.ndarray, np.ndarray]:
    fs, ps = [], []
    a = start
    while a < stop - 1:
        b = min(a + SEG_HZ, stop)
        ff.write(f"SENS:FREQ:STAR {a:.0f}")
        ff.write(f"SENS:FREQ:STOP {b:.0f}")
        ff.write(f"SENS:SWE:POIN {SURVEY_POINTS}")
        ff.write(f"SENS:BAND:RES {SURVEY_RBW:.0f}")
        time.sleep(SETTLE_S)
        _wait_average(ff, 1)
        fs.append(np.linspace(a, b, SURVEY_POINTS))
        ps.append(_trace(ff, SURVEY_POINTS))
        a = b
    return np.concatenate(fs), np.concatenate(ps)


def survey_lines(f, p) -> list[tuple[float, float, float]]:
    """Local maxima at least DETECT_DB above the 1 GHz segment's median floor; merged within 5 MHz. -> (f, raw dBm, floor)."""
    out = []
    for a in np.arange(f[0], f[-1], SEG_HZ):
        m = (f >= a) & (f < a + SEG_HZ)
        if not m.any():
            continue
        fl = float(np.median(p[m]))
        idx = np.where(m)[0]
        for i in idx[1:-1]:
            if p[i] >= p[i - 1] and p[i] >= p[i + 1] and p[i] > fl + DETECT_DB:
                if out and f[i] - out[-1][0] < 5e6:
                    if p[i] > out[-1][1]:
                        out[-1] = (f[i], p[i], fl)
                    continue
                out.append((f[i], p[i], fl))
    return out


def verify(ff: FieldFox, f_hz: float, level: float) -> tuple[bool | None, float]:
    """Re-read with +10 dB attenuation: a line from the unit keeps its level. None = too close to the raised floor."""
    ff.set_attenuation(ATT_CHECK_DB)
    _, p2, floor2 = marker(ff, f_hz)
    ff.set_attenuation(ATT_DB)
    if p2 < floor2 + 6:
        return None, p2
    return abs(p2 - level) <= VERIFY_TOL_DB, p2


# ------------------------------------------------------------------------------------------------ board
class LoNull:
    """Runtime LO-null bias, as the datasheet's calibrated TX: interpolate the cold/hot tables at the LMX temperature."""
    def __init__(self, serial: int):
        self.tables = []
        for name in REF_TABLES:
            with open(unit_dir(serial) / name / "lo_null_table.csv", newline="") as fh:
                rows = [r for r in csv.DictReader(fh) if not r["outcome"].startswith("failed")]
            self.tables.append({round(float(r["freq_ghz"]) * 1000): r for r in rows})

    def bias(self, lo_hz: float, temp_c: float) -> tuple[float, float]:
        k = round(lo_hz / 1e6)
        c, h = self.tables[0].get(k), self.tables[1].get(k)
        if c is None or h is None:
            raise RuntimeError(f"no cold/hot LO-null entry at {lo_hz / 1e9:g} GHz")
        tc, th = float(c["lmx_temp_c"]), float(h["lmx_temp_c"])
        x = (temp_c - tc) / (th - tc)
        return (float(c["i_v"]) + x * (float(h["i_v"]) - float(c["i_v"])),
                float(c["q_v"]) + x * (float(h["q_v"]) - float(c["q_v"])))


def board_common(board) -> None:
    must(board.set_clock_internal(True), "SET CLOCK INT")
    must(board.set_lo_internal(True), "SET LO INT")
    must(board.set_lmx_power(7), "LMX PWR 7")


def tx_configure(board, null: LoNull, pt) -> dict:
    tune_and_lock(board, pt["lo_hz"])
    temp = board.get_lmx_temperature_c()
    iv, qv = null.bias(pt["lo_hz"], temp)
    must(board.set_i_v(iv), "SET I_V")
    must(board.set_q_v(qv), "SET Q_V")
    must(board.set_iq_swap(pt["config"] == "lower"), "SET IQ")
    must(board.set_tx_filter(pt["bits"]), f"SET TXFILTER 0x{pt['bits']:02X}")
    time.sleep(SETTLE_S)
    return {"lmx_temp_c": round(temp, 1), "i_v": round(iv, 4), "q_v": round(qv, 4)}


def rx_configure(board, pt) -> dict:
    tune_and_lock(board, pt["lo_hz"])
    must(board.set_rx_filter(pt["bits"]), f"SET RXFILTER 0x{pt['bits']:02X}")
    time.sleep(SETTLE_S)
    return {"lmx_temp_c": round(board.get_lmx_temperature_c(), 1)}


# ------------------------------------------------------------------------------------------------ ramp
def set_input(ff: FieldFox, f_hz: float, at_connector_dbm: float, cable_in: CableLoss, limit_dbm: float) -> float:
    if at_connector_dbm > limit_dbm + 1e-9:
        raise RuntimeError(f"refusing {at_connector_dbm:.1f} dBm at the input (limit {limit_dbm:+.0f} dBm)")
    src = at_connector_dbm - cable_in.s21_db(f_hz)                  # S21 is negative: the source makes up the loss
    lo, hi = SOURCE_POWER_RANGE_DBM
    if not lo <= src <= hi:
        raise ValueError(f"source would need {src:.1f} dBm (range {lo}..{hi})")
    ff.source_configure(f_hz, src)
    time.sleep(SETTLE_S)
    return src


def ramp(ff, f_in, f_out, cable_in, cable_out, limit_dbm) -> tuple[list[dict], dict]:
    """Input P1dB at this configuration: -60 dBm up, 2 dB then 0.5 dB steps, stop at 5 dB compression or the limit."""
    rows, pin, gains, g0 = [], RAMP_START_DBM, [], None
    ff.source_enable(True)
    reason = "reached input limit"
    while pin <= limit_dbm + 1e-9:
        try:
            set_input(ff, f_in, pin, cable_in, limit_dbm)
        except ValueError:
            reason = "source power range"
            break
        fx, p, floor = marker(ff, f_out)
        pout = p - cable_out.s21_db(f_out)
        rows.append({"pin_dbm": round(pin, 2), "pout_dbm": round(pout, 3), "floor_dbm": round(floor - cable_out.s21_db(f_out), 2)})
        gains.append(pout - pin)
        if g0 is None:
            try:
                g0 = small_signal_gain(gains[-3:]) if len(gains) >= 3 and p > floor + 20 else None
            except ValueError:
                g0 = None
        comp = (g0 - gains[-1]) if g0 is not None else 0.0
        if comp >= RAMP_STOP_DB:
            reason = "reached 5 dB compression"
            break
        pin += FINE_DB if comp >= FINE_FROM_DB else COARSE_DB
    ff.source_enable(False)
    res = {"g0_db": g0, "p1db_in_dbm": None, "p1db_out_dbm": None, "ramp_stop": reason}
    if g0 is not None:
        cp = compression_point([r["pin_dbm"] for r in rows], [r["pout_dbm"] for r in rows], g0, 1.0)
        if cp:
            res.update(p1db_in_dbm=round(cp.pin_dbm, 2), p1db_out_dbm=round(cp.pout_dbm, 2))
    return rows, res


# ------------------------------------------------------------------------------------------------ io
def append(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    new = not path.exists()
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        if new:
            w.writeheader()
        w.writerows(rows)


def done_keys(path: Path) -> set[str]:
    return {r["key"] for r in csv.DictReader(open(path, newline=""))} if path.exists() else set()


# ------------------------------------------------------------------------------------------------ phases
def run_tx(board, ff, out: Path, pts, serial) -> None:
    fr1c, fr3c = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    start = max(SURVEY_START_HZ, fr3c.range_hz[0])
    null = LoNull(serial)
    (out / "surveys").mkdir(exist_ok=True)
    done = done_keys(out / "tx_configs.csv")
    todo = [p for p in pts if key(p) not in done]
    print(f"TX: {len(pts)} configurations, {len(todo)} to do; survey {start / 1e9:.2f}-{FF_MAX_HZ / 1e9:.1f} GHz")
    for i, pt in enumerate(todo, 1):
        t0, k = time.monotonic(), key(pt)
        cfg = {"key": k, **{x: (f"{pt[x]:.0f}" if isinstance(pt[x], float) else pt[x]) for x in pt if x != "bits"},
               "filter_bits": f"0x{pt['bits']:02X}"}
        lines = []
        try:
            cfg.update(tx_configure(board, null, pt))
            lo, fr1, fr3 = pt["lo_hz"], pt["fr1_hz"], pt["fr3_hz"]
            excluded = {"LO", "LO+FR1", "LO-FR1", "FR1-LO"}
            # ---- A1: no input ----
            ff.source_enable(False)
            f, p = survey(ff, start, FF_MAX_HZ)
            np.savez_compressed(out / "surveys" / f"tx_A1_{i:03d}_{int(lo / 1e6)}_{pt['config']}_{pt['filter']}.npz", f=f, p=p)
            cands = [(x, "survey") for x, _, _ in survey_lines(f, p)] + [(x, "predicted") for x in tx_predicted(lo, fr1, False)]
            a1 = measure_lines(ff, cands, fr3c, lo, fr1, "A1", k, excluded, None)
            # ---- input P1dB at this configuration, then A2 at P1dB - 5 dB ----
            rrows, res = ramp(ff, fr1, fr3, fr1c, fr3c, TX_INPUT_LIMIT_DBM)
            append(out / "tx_ramps.csv", [{"key": k, **r} for r in rrows])
            cfg.update(res)
            if res["p1db_in_dbm"] is None:
                raise RuntimeError(f"no P1dB found ({res['ramp_stop']})")
            drive = min(res["p1db_in_dbm"] - BACKOFF_DB, TX_INPUT_LIMIT_DBM)
            set_input(ff, fr1, drive, fr1c, TX_INPUT_LIMIT_DBM)
            ff.source_enable(True)
            _, pw, _ = marker(ff, fr3)
            wanted = pw - fr3c.s21_db(fr3)
            cfg.update(drive_dbm=round(drive, 2), wanted_out_dbm=round(wanted, 2))
            f, p = survey(ff, start, FF_MAX_HZ)
            np.savez_compressed(out / "surveys" / f"tx_A2_{i:03d}_{int(lo / 1e6)}_{pt['config']}_{pt['filter']}.npz", f=f, p=p)
            cands = [(x, "survey") for x, _, _ in survey_lines(f, p)] + [(x, "predicted") for x in tx_predicted(lo, fr1, True)]
            a2 = measure_lines(ff, cands, fr3c, lo, fr1, "A2", k, excluded, wanted)
            ff.source_enable(False)
            lines = a1 + a2
            w1 = max((l for l in a1 if l["counted"]), key=lambda l: l["level_dbm"], default=None)
            w2 = max((l for l in a2 if l["counted"]), key=lambda l: l["level_dbm"], default=None)
            cfg.update(a1_worst_dbm=w1 and w1["level_dbm"], a1_worst_label=w1 and w1["label"],
                       a1_worst_hz=w1 and w1["freq_hz"],
                       a2_worst_dbc=w2 and w2["dbc"], a2_worst_label=w2 and w2["label"], a2_worst_hz=w2 and w2["freq_hz"],
                       a2_worst_source_harmonic_possible=w2 and w2["source_harmonic_possible"], status="ok")
        except Exception as err:                                     # noqa: BLE001 - record and carry on
            ff.source_enable(False)
            cfg["status"] = f"FAILED: {err}"
            ff.errors()
        cfg["seconds"] = round(time.monotonic() - t0, 1)
        cfg["time"] = datetime.now().astimezone().isoformat(timespec="seconds")
        append(out / "tx_lines.csv", lines)
        append(out / "tx_configs.csv", [cfg])
        print(f"  [{i}/{len(todo)}] LO {pt['lo_hz'] / 1e9:4.1f} FR1 {pt['fr1_hz'] / 1e9:.1f} {pt['config']:5s} {pt['filter']:7s} "
              f"P1dB(in) {cfg.get('p1db_in_dbm')} dBm, drive {cfg.get('drive_dbm')} dBm | A1 worst {cfg.get('a1_worst_dbm')} dBm "
              f"({cfg.get('a1_worst_label')}) | A2 worst {cfg.get('a2_worst_dbc')} dBc ({cfg.get('a2_worst_label')}) "
              f"| {cfg['seconds']} s  {cfg['status']}", flush=True)


def measure_lines(ff, cands, cable_out, lo, fr1, phase, k, excluded, wanted) -> list[dict]:
    """Marker-read each candidate, verify with +10 dB attenuation, label. Levels in dBm at the connector."""
    seen, rows = [], []
    for f0, src in sorted(cands):
        if any(abs(f0 - s) < MARK_SPAN for s in seen):
            continue
        seen.append(f0)
        fx, p, floor = marker(ff, f0)
        if p < floor + 6:
            continue                                                   # nothing there
        ok, p2 = verify(ff, fx, p)
        corr = -cable_out.s21_db(fx)
        name, n_order = label(fx, lo, fr1) if phase == "A2" else label(fx, lo, 0.0)
        level = p + corr
        counted = ok is not False and name not in excluded
        rows.append({"key": k, "phase": phase, "freq_hz": round(fx), "level_dbm": round(level, 2),
                     "dbc": round(level - wanted, 2) if wanted is not None else "", "floor_dbm": round(floor + corr, 2),
                     "label": name, "found_by": src, "att_check_dbm": round(p2 + corr, 2),
                     "from_unit": {True: "yes", False: "no (analyzer)", None: "near floor"}[ok],
                     "source_harmonic_possible": int(phase != "A1" and n_order >= 2), "counted": int(counted)})
    return rows


def tx_side_for(pt) -> tuple[str, int]:
    """The TX configuration that runs alongside an RX row (user rule, 2026-10-05: the TX side ALWAYS has its optimal
    filter and its LO nulled, whatever the RX filter). FR1 = 2 GHz; RX low-side <-> TX upper sideband (same LO),
    RX high-side <-> TX lower; for the RX-bypassed row, upper if FR3 = LO + 2 GHz is in range, else lower."""
    lo = pt["lo_hz"]
    upper_ok = lo + 2e9 <= FF_MAX_HZ
    sb = {"optimal_low": "upper", "optimal_high": "lower"}.get(pt["filter"], "upper" if upper_ok else "lower")
    fr3 = lo + 2e9 if sb == "upper" else lo - 2e9
    return sb, optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})


def rx_lo_configure(board, null: LoNull, pt) -> dict:
    """B: the TX side in normal use -- optimal TX filter, matching IQ state, TX LO-null bias applied -- and the RX filter
    per the row; then the leakage out of "RX-side FR3 RF In" is read. Unused ports terminated (user)."""
    tune_and_lock(board, pt["lo_hz"])
    temp = board.get_lmx_temperature_c()
    iv, qv = null.bias(pt["lo_hz"], temp)
    sb, tx_bits = tx_side_for(pt)
    must(board.set_i_v(iv), "SET I_V")
    must(board.set_q_v(qv), "SET Q_V")
    must(board.set_iq_swap(sb == "lower"), "SET IQ")
    must(board.set_tx_filter(tx_bits), f"SET TXFILTER 0x{tx_bits:02X}")
    must(board.set_rx_filter(pt["bits"]), f"SET RXFILTER 0x{pt['bits']:02X}")
    time.sleep(SETTLE_S)
    return {"lmx_temp_c": round(temp, 1), "i_v": round(iv, 4), "q_v": round(qv, 4), "tx_sideband": sb,
            "tx_filter_bits": f"0x{tx_bits:02X}"}


def run_rx_lo(board, ff, out: Path, pts, serial) -> None:
    fr3c = CableLoss("fr3_cable")
    null = LoNull(serial)
    done = done_keys(out / "rx_lo.csv")
    todo = [p for p in pts if key(p) not in done]
    print(f"B (RX LO leakage at the RX input): {len(pts)} readings sets, {len(todo)} to do")
    for i, pt in enumerate(todo, 1):
        rows = []
        try:
            cfg = rx_lo_configure(board, null, pt)
            lo = pt["lo_hz"]
            for name, f in (("LO", lo), ("LO/2", lo / 2), ("2LO", 2 * lo)):
                if f > FF_MAX_HZ - MARK_SPAN:
                    continue
                fx, p, floor = marker(ff, f)
                corr = -fr3c.s21_db(fx)
                rows.append({"key": key(pt), "lo_hz": f"{lo:.0f}", "filter": pt["filter"], "filter_bits": f"0x{pt['bits']:02X}",
                             "product": name, "freq_hz": round(fx), "level_dbm": round(p + corr, 2),
                             "floor_dbm": round(floor + corr, 2), "above_floor_db": round(p - floor, 1), **cfg, "status": "ok"})
        except Exception as err:                                     # noqa: BLE001
            rows = [{"key": key(pt), "lo_hz": f"{pt['lo_hz']:.0f}", "filter": pt["filter"], "status": f"FAILED: {err}"}]
            ff.errors()
        append(out / "rx_lo.csv", rows)
        if i % 10 == 1 or i == len(todo):
            r = next((x for x in rows if x.get("product") == "LO"), rows[0])
            print(f"  [{i}/{len(todo)}] LO {pt['lo_hz'] / 1e9:5.1f} {pt['filter']:13s} LO leakage {r.get('level_dbm')} dBm "
                  f"(floor {r.get('floor_dbm')})  {r['status']}", flush=True)


def rx_predicted(lo, fr1) -> list[tuple[float, str, int]]:
    """Input frequencies f with |m*LO + n*f| = FR1 (|m| <= 4, 1 <= n <= 5), minus the wanted input and the image."""
    out = {}
    for m in range(-4, 5):
        for n in range(1, 6):
            for s in (1, -1):
                f = (s * fr1 - m * lo) / n
                if 0.1e9 <= f <= FF_MAX_HZ and (m != 0 or n != 1 or True):
                    nm = f"{'' if n == 1 else n}f{'+' if m >= 0 else '-'}{'' if abs(m) == 1 else abs(m)}LO" if m else f"{'' if n == 1 else n}f"
                    out.setdefault(round(f / 1e6), (f, nm, n))
    wanted_or_image = {round((lo + fr1) / 1e6), round((lo - fr1) / 1e6)}
    return [v for kk, v in sorted(out.items()) if kk not in wanted_or_image]


def run_rx_resp(board, ff, out: Path, pts) -> None:
    fr1c, fr3c = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    done = done_keys(out / "rx_resp_configs.csv")
    todo = [p for p in pts if key(p) not in done]
    print(f"C2 (RX spurious responses): {len(pts)} configurations, {len(todo)} to do")
    for i, pt in enumerate(todo, 1):
        t0, k = time.monotonic(), key(pt)
        cfg = {"key": k, **{x: (f"{pt[x]:.0f}" if isinstance(pt[x], float) else pt[x]) for x in pt if x != "bits"},
               "filter_bits": f"0x{pt['bits']:02X}"}
        rows = []
        try:
            cfg.update(rx_configure(board, pt))
            lo, fr1, fr3 = pt["lo_hz"], pt["fr1_hz"], pt["fr3_hz"]
            rrows, res = ramp(ff, fr3, fr1, fr3c, fr1c, RX_INPUT_LIMIT_DBM)
            append(out / "rx_resp_ramps.csv", [{"key": k, **r} for r in rrows])
            cfg.update(res)
            if res["p1db_in_dbm"] is None:
                raise RuntimeError(f"no P1dB found ({res['ramp_stop']})")
            drive = min(res["p1db_in_dbm"] - BACKOFF_DB, RX_INPUT_LIMIT_DBM)
            set_input(ff, fr3, drive, fr3c, RX_INPUT_LIMIT_DBM)
            ff.source_enable(True)
            _, pw, _ = marker(ff, fr1)
            wanted = pw - fr1c.s21_db(fr1)
            cfg.update(drive_dbm=round(drive, 2), wanted_out_dbm=round(wanted, 2))
            for f, nm, n in rx_predicted(lo, fr1):
                try:
                    set_input(ff, f, drive, fr3c, RX_INPUT_LIMIT_DBM)
                except ValueError as err:
                    rows.append({"key": k, "input_hz": round(f), "product": nm, "status": f"skipped: {err}"})
                    continue
                if ff.errors():
                    rows.append({"key": k, "input_hz": round(f), "product": nm, "status": "skipped: source rejected"})
                    continue
                fx, p, floor = marker(ff, fr1)
                out_dbm = p - fr1c.s21_db(fr1)
                floor_dbm = floor - fr1c.s21_db(fr1)
                above = p > floor + 6
                rows.append({"key": k, "input_hz": round(f), "product": nm, "out_dbm": round(out_dbm, 2),
                             "floor_dbm": round(floor_dbm, 2),
                             "rejection_db": round(wanted - (out_dbm if above else floor_dbm), 2),
                             "floor_limited": int(not above), "source_harmonic_possible": int(n >= 2), "status": "ok"})
            ff.source_enable(False)
            ok = [r for r in rows if r.get("status") == "ok"]
            w = min(ok, key=lambda r: r["rejection_db"], default=None)
            cfg.update(worst_rejection_db=w and w["rejection_db"], worst_product=w and w["product"],
                       worst_input_hz=w and w["input_hz"], worst_floor_limited=w and w["floor_limited"],
                       worst_source_harmonic_possible=w and w["source_harmonic_possible"], status="ok")
        except Exception as err:                                     # noqa: BLE001
            ff.source_enable(False)
            cfg["status"] = f"FAILED: {err}"
            ff.errors()
        cfg["seconds"] = round(time.monotonic() - t0, 1)
        cfg["time"] = datetime.now().astimezone().isoformat(timespec="seconds")
        append(out / "rx_resp_lines.csv", rows)
        append(out / "rx_resp_configs.csv", [cfg])
        print(f"  [{i}/{len(todo)}] LO {pt['lo_hz'] / 1e9:4.1f} {pt['config']:4s} {pt['filter']:7s} P1dB(in) "
              f"{cfg.get('p1db_in_dbm')} dBm, drive {cfg.get('drive_dbm')} dBm | worst rejection {cfg.get('worst_rejection_db')} dB "
              f"({cfg.get('worst_product')}) | {cfg['seconds']} s  {cfg['status']}", flush=True)


# ------------------------------------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--phase", choices=("tx", "rx_lo", "rx_resp"), required=True)
    ap.add_argument("--filters", default="optimal,bypass")
    ap.add_argument("--limit", type=int, default=0, help="only the first N configurations (a quick test run)")
    ap.add_argument("--lo-ghz", default="", help="only these LOs, comma separated (e.g. 9 or 9,14)")
    ap.add_argument("--null-unit", type=int, default=0,
                    help="take the TX LO-null tables from this unit (default: the connected unit)")
    ap.add_argument("--campaign", default=None, help="results sub-folder (default spurs_<YYYYMMDD>)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--host", default=FF_HOST)
    ap.add_argument("--port", default=None)
    args = ap.parse_args()
    filters = [x.strip() for x in args.filters.split(",") if x.strip()]
    pts = {"tx": lambda: tx_points(filters), "rx_lo": rx_lo_points, "rx_resp": lambda: rx_resp_points(filters)}[args.phase]()
    if args.lo_ghz:
        keep = {round(float(x) * 1000) for x in args.lo_ghz.split(",") if x.strip()}
        pts = [p for p in pts if round(p["lo_hz"] / 1e6) in keep]
    if args.limit:
        pts = pts[:args.limit]
    if args.dry_run:
        per = {"tx": 240, "rx_lo": 8, "rx_resp": 90}[args.phase]     # rough seconds per configuration, until timed
        print(f"{args.phase}: {len(pts)} configurations, roughly {len(pts) * per / 60:.0f} min (estimate {per} s each)")
        for p in pts[:12]:
            print("  ", {k: (f"{v / 1e9:g} GHz" if isinstance(v, float) and v > 1e6 else (f"0x{v:02X}" if k == "bits" else v))
                         for k, v in p.items()})
        if len(pts) > 12:
            print(f"   ... {len(pts) - 12} more")
        if args.phase == "rx_resp":
            p = pts[0]
            print(f"   e.g. LO {p['lo_hz'] / 1e9:g} GHz: {len(rx_predicted(p['lo_hz'], p['fr1_hz']))} spurious input frequencies")
        return 0
    fr3c = CableLoss("fr3_cable")
    if args.phase in ("tx", "rx_resp") and fr3c.range_hz[0] > SURVEY_START_HZ + 1:
        print(f"note: the FR3 cable data start at {fr3c.range_hz[0] / 1e9:g} GHz -- recapture it from 0.1 GHz first")
        return 2
    campaign = args.campaign or f"spurs_{datetime.now():%Y%m%d}"
    with MeasurementSession(port=args.port) as board, FieldFox(args.host, span_hz=MARK_SPAN) as ff:
        serial = board.get_board_serial()
        out = unit_dir(serial) / campaign
        out.mkdir(parents=True, exist_ok=True)
        meta_p = out / "campaign.json"
        meta = json.loads(meta_p.read_text()) if meta_p.exists() else {"unit_serial": serial, "runs": []}
        meta["runs"].append({"phase": args.phase, "filters": filters, "started": datetime.now().astimezone().isoformat(timespec="seconds"),
                             "ff_idn": ff.identify(), "backoff_db": BACKOFF_DB, "att_db": ATT_DB, "survey_rbw_hz": SURVEY_RBW,
                             "marker_rbw_hz": MARK_RBW, "fr3_cable": str(fr3c.path.name),
                             "lo_null_tables_from_unit": args.null_unit or serial})
        meta_p.write_text(json.dumps(meta, indent=2))
        print(f"Unit #{serial}, phase {args.phase}: {out}")
        orig = None
        try:
            if args.phase == "rx_lo":
                orig = ff_setup(ff, ATT_QUIET_DB, REF_QUIET_DBM)
            else:
                orig = ff_setup(ff, ATT_DB, REF_DBM)
            board_common(board)
            {"tx": lambda: run_tx(board, ff, out, pts, serial), "rx_lo": lambda: run_rx_lo(board, ff, out, pts, args.null_unit or serial),
             "rx_resp": lambda: run_rx_resp(board, ff, out, pts)}[args.phase]()
        finally:
            off = restore_ff(ff, orig)
            print("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***")
    return 0


if __name__ == "__main__":
    sys.exit(main())
