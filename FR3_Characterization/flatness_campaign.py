"""In-channel gain flatness of the Pi-Radio FR3-1ch: the gain across a 500 MHz channel, for TX and RX (user spec 2026-10-05).

    python flatness_campaign.py --chain tx|rx --phase cal       (loopback normalization of the source and input cable)
    python flatness_campaign.py --chain tx|rx --phase measure   (the grid; resumable)
    python flatness_campaign.py --chain tx|rx --dry-run         (grid size, filters and time estimate; no instruments)

GRID (user spec): FR1 (IF) centre 1.0-4.0 GHz and FR3 centre 6.0-26.5 GHz, both in 0.5 GHz steps, both configurations
(TX: upper / lower sideband; RX: low-side / high-side LO), kept where 7 <= LO <= 22.6 GHz. A 500 MHz window centred on
FR1 is swept, so a window must stay inside the FieldFox's range: FR3 = 26.5 GHz (window to 26.75 GHz) is skipped.

AT EVERY POINT the LO is tuned once and the window is swept twice: AM3153 filter BYPASSED, then the per-point
"optimal" filter (the same rule as the rest of the datasheet: rx_nf_campaign.optimal_rx_filter -- best desired-band
power, then the most image rejection within 3 dB of it). One sweep always uses ONE filter setting.

THE SWEEP is the FieldFox's tracking generator (SOUR:TRAC TSWP with a frequency offset). The receiver is the FieldFox
SA input, the source its RF out:
  TX  source = FR1 (into "TX-side FR1 IF In"), receiver = FR3 (from "TX-side FR3 RF Out")
      upper sideband FR3 = LO + FR1: offset -LO, reverse OFF;  lower sideband FR3 = LO - FR1: offset +LO, reverse ON
  RX  source = FR3 (into "RX-side FR3 RF In"), receiver = FR1 (from "RX-side FR1 IF Out")
      low-side LO  FR3 = LO + FR1: offset +LO, reverse OFF;    high-side LO FR3 = LO - FR1: offset +LO, reverse ON
(FieldFox rule, confirmed on its own display: reverse OFF -> source = receiver + offset; ON -> source = offset - receiver.)
INIT:CONT OFF is never sent: the analyzer sweeps continuously; for each reading the trace average is restarted
(TRAC1:REST) and read after enough complete sweeps (measured sweep time x (count + 1) x margin).

GAIN = output trace - output cable loss - input level, where the input level at each frequency is the CAL phase's
loopback reading (FieldFox source -> the input cable -> FieldFox input, no board), so the source's own unflatness and the
input cable cancel. Without a cal file the nominal drive + cable S21 is used (and the run says so). FLATNESS = RMS deviation (dB) of the gain
from the window's RMS power level (rms_flatness_db; the datasheet metric); max - min is kept as flatness_db.

Drive: TX -40 dBm (as the gain sections); RX -50 dBm (the RX gain sections' -40 dBm compresses the highest-gain points
~0.5 dB, which would flatten the ripple). Analyzer: RBW 100 kHz, attenuation 20 dB, reference +10 dBm, 101 points per
500 MHz (5 MHz steps), trace average x2. RX runs put the TX side in normal use at every LO (rx_tx_side.py: stored LO-null bias, IQ
state, optimal TX filter). TX bias: --bias cal-tables (default since 2026-10-08) = the new 100 MHz-grid
cold/hot calibration interpolated to the LMX temperature at each point (lo_cal_tables.py), as a user's unit runs; --bias gui =
the old GUI LO-null table. LMX drive --lmx-power (default 0 since 2026-10-08; the 2026-10-05 run used 7).
--cal-from copies an existing cal.csv (same cables) into a new campaign folder instead of a new loopback.

Output: results/unit_<n>/flatness_<chain>_<date>/ -- cal.csv, points.csv (one row per point and filter: flatness, mean,
min, max gain, filter byte, LMX temperature, status), traces.csv (every trace), campaign.json. The FieldFox source is
always switched off at the end (read back).
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from datetime import datetime

import numpy as np

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from fr3_gui.lo_suppression import suggest_iv_qv
from lo_cal_tables import CalTables
from lmx_drive import set_drive_for
from results_layout import unit_dir
from rx_nf_campaign import optimal_rx_filter
from rx_tx_side import tx_normal_state

FF_HOST = "192.168.137.61"
FR1_LIST_HZ = [1.0e9 + 0.5e9 * k for k in range(7)]          # 1.0 ... 4.0 GHz
FR3_LIST_HZ = [6.0e9 + 0.5e9 * k for k in range(42)]         # 6.0 ... 26.5 GHz
LO_MIN_HZ, LO_MAX_HZ = 7.0e9, 22.6e9
WINDOW_HZ = 500e6
POINTS = 101                                                   # 5 MHz steps across 500 MHz
FF_MAX_HZ = 26.5e9                                             # FieldFox N9918B upper limit (and the FR3 cable data's)
RBW_HZ = 100e3
ATTEN_DB, REF_DBM = 20.0, 10.0
AVG_COUNT = 2
DRIVE_DBM = {"tx": -40.0, "rx": -50.0}
CONFIGS = {"tx": ("upper", "lower"), "rx": ("low", "high")}
CAL_STEP_HZ = 5e6


def lo_for(chain: str, config: str, fr1: float, fr3: float) -> float:
    """TX upper / RX low-side: FR3 = LO + FR1.  TX lower / RX high-side: FR3 = LO - FR1."""
    return fr3 - fr1 if config in ("upper", "low") else fr3 + fr1


def grid(chain: str) -> list[dict]:
    pts = []
    for fr1 in FR1_LIST_HZ:
        for config in CONFIGS[chain]:
            for fr3 in FR3_LIST_HZ:
                lo = lo_for(chain, config, fr1, fr3)
                if not LO_MIN_HZ - 1 <= lo <= LO_MAX_HZ + 1:
                    continue
                if fr3 + WINDOW_HZ / 2 > FF_MAX_HZ + 1:                  # the window would leave the FieldFox's range
                    continue
                pt = {"fr1_hz": fr1, "fr3_hz": fr3, "config": config, "lo_hz": lo}
                # the shared "optimal" rule (desired band at FR3, image on the other side of the LO)
                pt["opt_filter"] = optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})
                pts.append(pt)
    return pts


def key(chain, pt, filt) -> str:
    return f"{chain}|{pt['config']}|{pt['fr1_hz']:.0f}|{pt['fr3_hz']:.0f}|{filt}"


# ---------------------------------------------------------------------------------------------------- FieldFox
def setup_ff(ff: FieldFox, drive_dbm: float) -> int:
    """Tracking-generator SA set-up with continuous sweep ON (never CONT OFF). Returns the original point count."""
    ff.write("*CLS")
    ff.select_mode("SA")
    orig_points = int(float(ff.query("SENS:SWE:POIN?")))
    ff.source_enable(False)
    # remember the attenuator so restore_instrument_state() puts it back (as setup_spectrum_analyzer() would)
    ff._saved_attenuation = (ff.query("SENS:POW:ATT:AUTO?") in ("1", "ON"), ff.attenuation_db)
    ff.set_attenuation(ATTEN_DB)
    ff.write(f"DISP:WIND:TRAC:Y:RLEV {REF_DBM:.1f}")
    ff.write(f"SENS:BAND:RES {RBW_HZ:.0f}")
    ff.write("SENS:BAND:VID:AUTO ON")
    ff.write("FORM:DATA ASCii,0")
    ff.write("TRAC1:TYPE AVG")
    ff.write(f"SENS:AVER:COUN {AVG_COUNT}")
    ff.write(f"SENS:SWE:POIN {POINTS}")
    ff.write(f"SOUR:POW {drive_dbm:.2f}")
    ff.write("SOUR:TRAC TSWP")
    ff.write("SOUR:TOFF:ENAB ON")
    ff.write("INIT:CONT ON")
    errs = ff.errors()
    if errs:
        raise RuntimeError(f"FieldFox rejected the tracking set-up: {errs}")
    return orig_points


def restore_ff(ff: FieldFox, orig_points: int | None) -> bool:
    ff.source_enable(False)
    for c in ("SOUR:TOFF:ENAB OFF", "SOUR:TRAC OFF", "SOUR:TOFF:REV OFF", "SENS:BAND:RES:AUTO ON", "TRAC1:TYPE CLRW"):
        ff.write(c)
    if orig_points:
        ff.write(f"SENS:SWE:POIN {orig_points}")
    ff.write("SENS:FREQ:SPAN 1000000")
    ff.restore_instrument_state()                                  # leaves INIT:CONT ON
    time.sleep(SETTLE_S)
    return not ff.source_state()


def read_trace(ff: FieldFox, start: float, stop: float, points: int, offset: float, reverse: bool) -> np.ndarray:
    """One averaged trace of the receiver sweep start..stop with the source tracking at the given offset/direction.
    Continuous sweep stays ON: restart the average, wait for (count + 1) complete sweeps, read."""
    ff.write(f"SENS:FREQ:STAR {start:.0f}")
    ff.write(f"SENS:FREQ:STOP {stop:.0f}")
    ff.write(f"SENS:SWE:POIN {points}")
    ff.write(f"SOUR:TOFF:FREQ {offset:.0f}")
    ff.write(f"SOUR:TOFF:REV {'ON' if reverse else 'OFF'}")
    time.sleep(SETTLE_S)
    t_sweep = float(ff.query("SENS:SWE:MTIM?"))
    for attempt in range(4):
        ff.write("TRAC1:REST")
        time.sleep(max(0.3, 1.5 * (AVG_COUNT + 1) * t_sweep))
        errs = ff.errors()
        # The FieldFox source sometimes reports "SRC VCO Unlocked" on the first sweep after a set-up (2026-10-08: the first
        # point of a run, and once mid-run, where the sweep then read no signal). It clears by itself: wait, re-sweep.
        if errs and all("VCO Unlocked" in e for e in errs) and attempt < 3:
            time.sleep(2.0)
            continue
        break
    if errs:
        raise RuntimeError(f"FieldFox rejected the sweep settings: {errs}")
    for _ in range(10):                    # the first trace after a point-count change can still be the old one
        trace = np.array([float(v) for v in ff.query("TRAC1:DATA?").split(",")])
        if trace.size == points:
            return trace
        ff.write("TRAC1:REST")
        time.sleep(max(0.5, 1.5 * (AVG_COUNT + 1) * float(ff.query("SENS:SWE:MTIM?"))))
    raise RuntimeError(f"trace has {trace.size} points, expected {points} "
                       f"(SENS:SWE:POIN? = {ff.query('SENS:SWE:POIN?')})")


# ---------------------------------------------------------------------------------------------------- phases
def run_cal(ff, outdir, chain) -> None:
    """Loopback (no board): FieldFox source -> the INPUT cable -> FieldFox input, tracking at offset 0. Covers every
    input frequency any window uses: TX the FR1 band, RX the FR3 band."""
    if chain == "tx":
        lo, hi = FR1_LIST_HZ[0] - WINDOW_HZ / 2, FR1_LIST_HZ[-1] + WINDOW_HZ / 2
    else:
        lo, hi = FR3_LIST_HZ[0] - WINDOW_HZ / 2, FF_MAX_HZ
    segs = []
    f0 = lo
    while f0 < hi:                                                 # 500 MHz segments, the same span as the windows
        f1 = min(f0 + WINDOW_HZ, hi)
        segs.append((f0, f1, int(round((f1 - f0) / CAL_STEP_HZ)) + 1))
        f0 = f1
    # The first reading after set-up came back unsettled once (RX, 2026-10-05: -99 dBm in the first segment), so
    # take one throw-away reading first, and re-read any segment whose median is > 5 dB off the others' median.
    read_trace(ff, *segs[0], 0.0, False)
    traces = [read_trace(ff, a, b, n, 0.0, False) for a, b, n in segs]
    for attempt in range(3):
        overall = np.median([np.median(t) for t in traces])
        bad = [i for i, t in enumerate(traces) if abs(np.median(t) - overall) > 5 or t.min() < overall - 10]
        if not bad:
            break
        print(f"  re-reading {len(bad)} unsettled segment(s): {[f'{segs[i][0] / 1e9:.2f} GHz' for i in bad]}")
        for i in bad:
            traces[i] = read_trace(ff, *segs[i], 0.0, False)
    else:
        raise RuntimeError("loopback segments still inconsistent after 3 re-reads: check the loopback connection")
    rows = [(f, v) for (a, b, n), t in zip(segs, traces) for f, v in zip(np.linspace(a, b, n), t)]
    with open(outdir / "cal.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_hz", "loopback_dbm"])
        for f, v in rows:
            w.writerow([f"{f:.0f}", f"{v:.3f}"])
    v = np.array([r[1] for r in rows])
    print(f"cal: {len(rows)} points {lo / 1e9:.2f}-{hi / 1e9:.2f} GHz, loopback {v.min():.2f} to {v.max():.2f} dBm")


def load_cal(outdir):
    p = outdir / "cal.csv"
    if not p.exists():
        return None
    r = list(csv.DictReader(open(p, newline="")))
    f = np.array([float(x["freq_hz"]) for x in r])
    v = np.array([float(x["loopback_dbm"]) for x in r])
    o = np.argsort(f)
    return f[o], v[o]


def sweep_point(ff, chain, pt, cable_in, cable_out, cal, drive):
    """Returns (f_if, f_rf, trace, gain) across the window around FR1 (the board is already set up)."""
    lo, fr1, config = pt["lo_hz"], pt["fr1_hz"], pt["config"]
    if_lo, if_hi = fr1 - WINDOW_HZ / 2, fr1 + WINDOW_HZ / 2
    f_if = np.linspace(if_lo, if_hi, POINTS)
    plus = config in ("upper", "low")                               # FR3 = LO + FR1
    f_rf = lo + f_if if plus else lo - f_if
    if chain == "tx":                                                # receiver = RF, source = IF
        if plus:
            tr = read_trace(ff, lo + if_lo, lo + if_hi, POINTS, -lo, False)
            rx_f = np.linspace(lo + if_lo, lo + if_hi, POINTS)
        else:
            tr = read_trace(ff, lo - if_hi, lo - if_lo, POINTS, +lo, True)
            rx_f = np.linspace(lo - if_hi, lo - if_lo, POINTS)
        src_f = rx_f - lo if plus else lo - rx_f
        out_loss = cable_out.s21_db_array(rx_f)
    else:                                                            # receiver = IF, source = RF
        tr = read_trace(ff, if_lo, if_hi, POINTS, +lo, not plus)
        rx_f = f_if
        src_f = lo + rx_f if plus else lo - rx_f
        out_loss = cable_out.s21_db_array(rx_f)
    if cal is not None:
        level_in = np.interp(src_f, cal[0], cal[1])                   # source + input cable, measured
    else:
        level_in = drive + cable_in.s21_db_array(src_f)
    gain = tr - out_loss - level_in
    # index everything by IF (ascending) for storage
    if_of_rx = rx_f - lo if (chain == "tx" and plus) else (lo - rx_f if chain == "tx" else rx_f)
    o = np.argsort(if_of_rx)
    return if_of_rx[o], (lo + if_of_rx[o] if plus else lo - if_of_rx[o]), tr[o], gain[o]


def rms_db(gain: np.ndarray) -> float:
    """RMS flatness (the datasheet metric): RMS deviation in dB from the window's RMS power level."""
    ref = 10 * np.log10(np.mean(10 ** (gain / 10)))
    return float(np.sqrt(np.mean((gain - ref) ** 2)))


def recompute(outdir, chain) -> None:
    """Re-derive gain and flatness from the stored traces with the (now available) cal.csv -- so the measurement can be
    taken first and the loopback normalization afterwards, without re-measuring. Rewrites points.csv/traces.csv."""
    cal = load_cal(outdir)
    if cal is None:
        raise RuntimeError("no cal.csv yet: run --phase cal first")
    cable_out = CableLoss("fr3_cable" if chain == "tx" else "fr1_cable")
    pts = list(csv.DictReader(open(outdir / "points.csv", newline="")))
    traces = {}
    for r in csv.DictReader(open(outdir / "traces.csv", newline="")):
        traces.setdefault(r["key"], []).append(r)
    out_tr = []
    for p in pts:
        t = traces[p["key"]]
        f_if = np.array([float(x["if_hz"]) for x in t])
        f_rf = np.array([float(x["rf_hz"]) for x in t])
        tr = np.array([float(x["trace_dbm"]) for x in t])
        f_out, f_src = (f_rf, f_if) if chain == "tx" else (f_if, f_rf)
        gain = tr - cable_out.s21_db_array(f_out) - np.interp(f_src, cal[0], cal[1])
        p.update(flatness_db=f"{gain.max() - gain.min():.3f}", rms_flatness_db=f"{rms_db(gain):.3f}",
                 mean_gain_db=f"{10 * np.log10(np.mean(10 ** (gain / 10))):.3f}",
                 min_gain_db=f"{gain.min():.3f}", max_gain_db=f"{gain.max():.3f}", cal=1)
        out_tr += [[p["key"], f"{a:.0f}", f"{b:.0f}", f"{c:.3f}", f"{d:.3f}"] for a, b, c, d in zip(f_if, f_rf, tr, gain)]
    with open(outdir / "points.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(pts[0]))
        w.writeheader()
        w.writerows(pts)
    with open(outdir / "traces.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "if_hz", "rf_hz", "trace_dbm", "gain_db"])
        w.writerows(out_tr)
    f = np.array([float(p["flatness_db"]) for p in pts])
    print(f"recomputed {len(pts)} sweeps with cal.csv: flatness median {np.median(f):.2f} dB, max {f.max():.2f} dB")


def run_measure(board, ff, outdir, chain, pts, cal, lmx_power="auto", tables: CalTables | None = None) -> None:
    cable_if, cable_rf = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    cable_in, cable_out = (cable_if, cable_rf) if chain == "tx" else (cable_rf, cable_if)
    drive = DRIVE_DBM[chain]
    pts_path, tr_path = outdir / "points.csv", outdir / "traces.csv"
    done = {r["key"] for r in csv.DictReader(open(pts_path, newline=""))} if pts_path.exists() else set()
    todo = [p for p in pts if not all(key(chain, p, f) in done for f in ("bypass", "optimal"))]
    print(f"{len(pts)} points x 2 filters, {len(todo)} points still to do" +
          ("" if cal is not None else "   *** no cal.csv: using nominal drive + cable S21 ***"))
    must(board.set_clock_internal(True), "SET CLOCK INT")
    must(board.set_lo_internal(True), "SET LO INT")
    if lmx_power != "auto":
        must(board.set_lmx_power(int(lmx_power)), f"LMX PWR {lmx_power}")
    ff.source_enable(True)
    time.sleep(SETTLE_S)
    t0 = time.monotonic()
    for k, pt in enumerate(todo, 1):
        status = "ok"
        try:
            drive = set_drive_for(board, pt["lo_hz"]) if lmx_power == "auto" else int(lmx_power)
            tune_and_lock(board, pt["lo_hz"])
            temp = board.get_lmx_temperature_c()
            iv = (0.0, 0.0)
            if chain == "tx":
                iv = tables.bias(pt["lo_hz"], temp) if tables is not None else suggest_iv_qv(pt["lo_hz"] / 1e9)
                must(iv is not None, "no LO-null table entry")
                must(board.set_i_v(iv[0]), "SET I_V")
                must(board.set_q_v(iv[1]), "SET Q_V")
                must(board.set_iq_swap(pt["config"] == "lower"), "SET IQ")
            else:                                    # RX: the TX side in normal use (rx_tx_side.py; TX ports terminated)
                st_tx = tx_normal_state(board, tables, pt["fr3_hz"], pt["lo_hz"], temp)
                iv = (float(st_tx["tx_i_v"]), float(st_tx["tx_q_v"]))
            for filt, bits in (("bypass", 0x00), ("optimal", pt["opt_filter"])):
                if key(chain, pt, filt) in done:
                    continue
                must((board.set_tx_filter if chain == "tx" else board.set_rx_filter)(bits), f"SET FILTER 0x{bits:02X}")
                time.sleep(SETTLE_S)
                f_if, f_rf, tr, gain = sweep_point(ff, chain, pt, cable_in, cable_out, cal, drive)
                lock = board.get_lmx_lock()
                st = status if lock == "LOCKED" else f"lock {lock}"
                row = {"key": key(chain, pt, filt), "chain": chain, "config": pt["config"], "filter": filt,
                       "filter_bits": f"0x{bits:02X}", "fr1_hz": f"{pt['fr1_hz']:.0f}", "fr3_hz": f"{pt['fr3_hz']:.0f}",
                       "lo_hz": f"{pt['lo_hz']:.0f}", "flatness_db": f"{gain.max() - gain.min():.3f}", "rms_flatness_db": f"{rms_db(gain):.3f}",
                       "mean_gain_db": f"{10 * np.log10(np.mean(10 ** (gain / 10))):.3f}", "min_gain_db": f"{gain.min():.3f}",
                       "max_gain_db": f"{gain.max():.3f}", "max_out_dbm": f"{tr.max():.2f}", "lmx_temp_c": f"{temp:.1f}",
                       "lmx_power": drive, "i_v": f"{iv[0]:.5f}", "q_v": f"{iv[1]:.5f}",
                       "cal": int(cal is not None), "status": st,
                       "time": datetime.now().astimezone().isoformat(timespec="seconds")}
                new = not pts_path.exists()
                with open(pts_path, "a", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(row))
                    if new:
                        w.writeheader()
                    w.writerow(row)
                new = not tr_path.exists()
                with open(tr_path, "a", newline="") as fh:
                    w = csv.writer(fh)
                    if new:
                        w.writerow(["key", "if_hz", "rf_hz", "trace_dbm", "gain_db"])
                    for a, b, c, d in zip(f_if, f_rf, tr, gain):
                        w.writerow([row["key"], f"{a:.0f}", f"{b:.0f}", f"{c:.3f}", f"{d:.3f}"])
                print(f"  [{k}/{len(todo)}] {pt['config']:5s} FR1 {pt['fr1_hz'] / 1e9:.1f} FR3 {pt['fr3_hz'] / 1e9:5.1f} "
                      f"LO {pt['lo_hz'] / 1e9:5.2f} {filt:7s} 0x{bits:02X}: flatness {gain.max() - gain.min():5.2f} dB, "
                      f"mean gain {float(row['mean_gain_db']):+6.1f} dB, out max {tr.max():+6.1f} dBm  {st}", flush=True)
        except Exception as err:                                     # noqa: BLE001 - log the point and carry on
            print(f"  [{k}/{len(todo)}] FAILED {pt}: {err}", flush=True)
            ff.errors()
    print(f"done in {(time.monotonic() - t0) / 60:.1f} min")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chain", choices=("tx", "rx"), required=True)
    ap.add_argument("--phase", choices=("cal", "measure", "recompute"))
    ap.add_argument("--limit", type=int, default=0, help="measure only the first N grid points (a quick sanity run)")
    ap.add_argument("--campaign", default=None, help="results sub-folder (default flatness_<chain>_<YYYYMMDD>)")
    ap.add_argument("--dry-run", action="store_true", help="print the grid and a time estimate; touches no instrument")
    ap.add_argument("--host", default=FF_HOST)
    ap.add_argument("--port", default=None)
    ap.add_argument("--lmx-power", default="auto", help="auto (default since 2026-10-09) = lmx_drive.drive_for(LO): 0 / 2 / 4; or a fixed level")
    ap.add_argument("--lo-min-ghz", type=float, default=0.0, help="measure only points with LO strictly above this")
    ap.add_argument("--bias", choices=("cal-tables", "gui"), default="cal-tables")
    ap.add_argument("--cal-from", default="", help="copy this cal.csv into the campaign folder (if it has none)")
    ap.add_argument("--only", default="", help="only these points, e.g. upper:1:9,lower:2:14 (config:FR1:FR3 in GHz)")
    args = ap.parse_args()
    pts = grid(args.chain)
    if args.only:
        want = set(args.only.split(","))
        pts = [p for p in pts if f"{p['config']}:{p['fr1_hz'] / 1e9:g}:{p['fr3_hz'] / 1e9:g}" in want]
    if args.dry_run or args.phase is None:
        n = {c: sum(p["config"] == c for p in pts) for c in CONFIGS[args.chain]}
        print(f"{args.chain.upper()}: {len(pts)} points ({n}) x 2 filters = {2 * len(pts)} sweeps of {POINTS} points; "
              f"FR3 = 26.5 GHz skipped (window beyond {FF_MAX_HZ / 1e9:g} GHz)")
        print(f"optimal filter bytes used: {sorted({f'0x{p['opt_filter']:02X}' for p in pts})}")
        print(f"rough time at ~1.2 s per sweep + 0.3 s per tune: {(len(pts) * (2 * 1.2 + 0.3)) / 60:.0f} min")
        return 0
    campaign = args.campaign or f"flatness_{args.chain}_{datetime.now():%Y%m%d}"
    if args.phase == "recompute":                                    # no instruments needed
        recompute(unit_dir(5) / campaign, args.chain)
        return 0
    if args.lo_min_ghz:
        pts = [p for p in pts if p["lo_hz"] > args.lo_min_ghz * 1e9 + 1]
    if args.limit:
        pts = pts[:args.limit]
    for f in (FR1_LIST_HZ[0] - WINDOW_HZ / 2, FR1_LIST_HZ[-1] + WINDOW_HZ / 2):
        CableLoss("fr1_cable").s21_db(f)                              # raise now if a window is outside the cable data
    with MeasurementSession(port=args.port) as board, FieldFox(args.host, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        outdir = unit_dir(serial) / campaign
        outdir.mkdir(parents=True, exist_ok=True)
        meta = outdir / "campaign.json"
        m = json.loads(meta.read_text()) if meta.exists() else {
            "chain": args.chain, "unit_serial": serial, "points_per_window": POINTS, "window_hz": WINDOW_HZ,
            "drive_dbm": DRIVE_DBM[args.chain], "rbw_hz": RBW_HZ, "attenuation_db": ATTEN_DB, "ref_dbm": REF_DBM,
            "avg_count": AVG_COUNT, "lo_range_hz": [LO_MIN_HZ, LO_MAX_HZ], "lmx_power": args.lmx_power,
            "bias": args.bias, "cal_from": args.cal_from, "runs": []}
        if args.cal_from and not (outdir / "cal.csv").exists():
            shutil.copyfile(args.cal_from, outdir / "cal.csv")
        m["runs"].append({"phase": args.phase, "started": datetime.now().astimezone().isoformat(timespec="seconds"),
                          "ff_idn": ff.identify()})
        meta.write_text(json.dumps(m, indent=2))
        print(f"Unit #{serial}, {args.chain.upper()} {args.phase}: {outdir}")
        orig = None
        try:
            orig = setup_ff(ff, DRIVE_DBM[args.chain])
            if args.phase == "cal":
                ff.source_enable(True)
                time.sleep(SETTLE_S)
                run_cal(ff, outdir, args.chain)
            else:
                tables = CalTables() if (args.chain == "rx" or args.bias == "cal-tables") else None
                if tables is not None:
                    print(f"bias: interpolated between {tables.cold_path} and {tables.hot_path}")
                run_measure(board, ff, outdir, args.chain, pts, load_cal(outdir), args.lmx_power, tables)
        finally:
            off = restore_ff(ff, orig)
            print("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***")
    return 0


if __name__ == "__main__":
    sys.exit(main())
