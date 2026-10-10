"""TX compression at the datasheet's 9 representative (FR1, FR3) points per sideband (user spec 2026-10-08: re-run at LMX
drive 0 with the unit's stored LO-null calibration).

    python compression_campaign.py [--sideband upper|lower|both] [--campaign compression_tx_<date>] [--limit N]

POINTS (Sections 7 and 8 of the datasheet): upper (FR3 = LO + FR1) and lower (FR3 = LO - FR1), bands 1-3, FR1 1.0 / 2.0 / 3.5 GHz.

AT EVERY POINT: LO tuned (LMX drive --lmx-power, default 0); I_V/Q_V from the stored cold/hot calibration interpolated to the
LMX temperature (lo_cal_tables.py); IQ THRU (upper) / SWAP (lower); the per-point "optimal" TX filter
(rx_nf_campaign.optimal_rx_filter, the datasheet's rule). Power sweep = conversion_gain_small_case.power_sweep: CW at FR1 from
-60 dBm at the FieldFox source upward (2 dB steps, 0.5 dB once compression passes 0.3 dB), reading the desired tone at FR3
(peak search, analyzer attenuation held fixed at 35 dB, 1 MHz span); stops at 5 dB compression (user rule), at 0 dBm source,
or if the analyzer would see more than +23 dBm. Small-signal gain, P1dB and P3dB as in compression.py.

Output: results/unit_005/<campaign>/<sideband>_FR1_<x>_FR3_<y>.csv (every step) and summary.csv; campaign.json. Source OFF at
the end (read back); the board's configuration is restored (MeasurementSession).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime

import conversion_gain_small_case as cg
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, power_sweep, tune_and_lock, write_csv
from fieldfox import SETTLE_S, FieldFox
from flatness_campaign import FF_HOST
from lo_cal_tables import CalTables
from lmx_drive import set_drive_for
from results_layout import unit_dir
from rx_nf_campaign import optimal_rx_filter

# Panels 7.6 and 7.9 changed on 2026-10-09 (user): 7.6 (3.5, 17.5) -> (3.0, 17.0), because LO = 4 x FR1 exactly at the old
# point (products of the input and the LO land on the desired tone and distort the reading); 7.9 (3.5, 25.5, above the rated
# 24 GHz) -> (3.5, 23.5).
POINTS = {"upper": [(1.0, 9.0), (2.0, 9.0), (3.5, 11.5), (1.0, 13.0), (2.0, 15.0), (3.0, 17.0), (1.0, 19.0), (2.0, 22.0),
                    (3.5, 23.5)],
          "lower": [(1.0, 8.0), (2.0, 8.0), (3.5, 9.0), (1.0, 13.0), (2.0, 14.0), (3.5, 15.0), (1.0, 19.0), (2.0, 19.0),
                    (3.5, 18.5)]}
START_DBM = -60.0
cg.STOP_AT_COMPRESSION_DB = 5.0                     # user rule: compression sweeps stop at 5 dB compression


# Small-signal gain from the 6th-8th steps (FieldFox source -50, -48, -46 dBm), not the first three. The sweep still starts at
# -60 dBm (user safety rule), but the FieldFox source is not accurate in its bottom few dB: the 2026-10-08 test read the gain
# 0.6 dB higher at -56 than at -60 dBm at a steady LMX temperature (conversion_gain_small_case notes the same for -60 dBm).
# Those low steps are still recorded; they are just not used to define G0. power_sweep calls cg.small_signal_gain.
_orig_small_signal_gain = cg.small_signal_gain
SS_STEPS = (5, 8)        # steps 6-8 (-50, -48, -46 dBm at the source), with the 0.5 dB consistency check
SS_PLAIN_MEAN = False    # --ss-window: plain mean over a wider window, no consistency check (one-off, user 2026-10-09)


def _ss_gain(g):
    a, b = SS_STEPS
    if len(g) < b:
        return None
    return sum(g[a:b]) / (b - a) if SS_PLAIN_MEAN else _orig_small_signal_gain(g[a:b])


cg.small_signal_gain = _ss_gain
# ...and look for the P1dB / P3dB crossings only from the same -50 dBm step upward: the inaccurate bottom steps could otherwise
# produce a false crossing (2026-10-09: a drive-2 sweep reported P1dB at -59 dBm input).
_orig_compression_point = cg.compression_point
cg.compression_point = lambda pin, pout, g0, drop: _orig_compression_point(pin[5:], pout[5:], g0, drop)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sideband", choices=("upper", "lower", "both"), default="both")
    ap.add_argument("--lmx-power", default="auto", help="auto (default since 2026-10-09) = lmx_drive.drive_for(LO): 0 / 2 / 4; or a fixed level")
    ap.add_argument("--lo-min-ghz", type=float, default=0.0, help="measure only points with LO strictly above this")
    ap.add_argument("--campaign", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ss-window", default="", help="e.g. -50,-40: small-signal gain = plain mean of the gains with the source in that range (2 dB steps from -60), no consistency check")
    ap.add_argument("--only", default="", help="only these points, e.g. upper:3.5:23.5,lower:3.5:18.5")
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--settle-s", type=float, default=30.0,
                    help="LMX temperature must hold within 0.5 C this long before each sweep (datasheet 30; production 15)")
    args = ap.parse_args()
    if args.ss_window:
        global SS_STEPS, SS_PLAIN_MEAN
        lo_dbm, hi_dbm = (float(x) for x in args.ss_window.split(","))
        SS_STEPS = (int(round((lo_dbm - START_DBM) / 2)), int(round((hi_dbm - START_DBM) / 2)) + 1)
        SS_PLAIN_MEAN = True
        print(f"small-signal gain: plain mean of steps {SS_STEPS[0] + 1}-{SS_STEPS[1]} (source {lo_dbm:g} to {hi_dbm:g} dBm)", flush=True)
    sides = ("upper", "lower") if args.sideband == "both" else (args.sideband,)
    campaign = args.campaign or f"compression_tx_{datetime.now():%Y%m%d}"
    fr1c, fr3c = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    tables = CalTables()
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        out = unit_dir(serial) / campaign
        out.mkdir(parents=True, exist_ok=True)
        (out / "campaign.json").write_text(json.dumps({
            "script": "compression_campaign.py", "lmx_power": args.lmx_power, "start_dbm": START_DBM,
            "stop_at_compression_db": cg.STOP_AT_COMPRESSION_DB, "attenuation_db": cg.DEFAULT_FIXED_ATTENUATION_DB,
            "bias": f"cal tables interpolated: {tables.cold_path} / {tables.hot_path}", "points": POINTS,
            "started": datetime.now().astimezone().isoformat(timespec="seconds"), "ff_idn": ff.identify()}, indent=2))
        summary = out / "summary.csv"
        done = {(r["sideband"], r["fr1_ghz"], r["fr3_ghz"]) for r in csv.DictReader(open(summary, newline=""))} \
            if summary.exists() else set()
        t0 = time.monotonic()
        try:
            ff.setup_spectrum_analyzer(ref_level_dbm=cg.REF_FIXED_DBM)
            ff.source_enable(False)
            ff.set_attenuation(cg.DEFAULT_FIXED_ATTENUATION_DB)
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            if args.lmx_power != "auto":
                must(board.set_lmx_power(int(args.lmx_power)), f"LMX PWR {args.lmx_power}")
            for side in sides:
                pts = POINTS[side][:args.limit] if args.limit else POINTS[side]
                for fr1_g, fr3_g in pts:
                    if args.only and f"{side}:{fr1_g:g}:{fr3_g:g}" not in args.only.split(","):
                        continue
                    if (side, f"{fr1_g:g}", f"{fr3_g:g}") in done:
                        continue
                    fr1, fr3 = fr1_g * 1e9, fr3_g * 1e9
                    lo = fr3 - fr1 if side == "upper" else fr3 + fr1
                    if lo <= args.lo_min_ghz * 1e9 + 1:
                        continue
                    print(f"\n=== {side} FR1 {fr1_g:g} GHz, FR3 {fr3_g:g} GHz, LO {lo / 1e9:g} GHz", flush=True)
                    try:
                        drive = set_drive_for(board, lo) if args.lmx_power == "auto" else int(args.lmx_power)
                        tune_and_lock(board, lo)
                        temp = board.get_lmx_temperature_c()
                        iv, qv = tables.bias(lo, temp)
                        must(board.set_i_v(iv), "SET I_V")
                        must(board.set_q_v(qv), "SET Q_V")
                        must(board.set_iq_swap(side == "lower"), "SET IQ")
                        bits = optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})
                        must(board.set_tx_filter(bits), f"SET TXFILTER 0x{bits:02X}")
                        # Retuning moves the LMX temperature (it depends on the LO), and the gain follows it: the first test
                        # (2026-10-08) saw the gain climb 0.65 dB over the first three steps while the LMX cooled 1.8 C, which
                        # fails the small-signal check. Wait until the temperature holds for --settle-s (default 30 s; at
                        # most 4 min).
                        t_end, last, since = time.monotonic() + 240, board.get_lmx_temperature_c(), time.monotonic()
                        while time.monotonic() < t_end and time.monotonic() - since < args.settle_s:
                            time.sleep(5)
                            now_t = board.get_lmx_temperature_c()
                            if abs(now_t - last) > 0.5:
                                last, since = now_t, time.monotonic()
                        temp = board.get_lmx_temperature_c()
                        iv, qv = tables.bias(lo, temp)                  # re-apply for the settled temperature
                        must(board.set_i_v(iv), "SET I_V")
                        must(board.set_q_v(qv), "SET Q_V")
                        print(f"  LMX settled at {temp:.1f} C", flush=True)
                        ff.source_configure(fr1, START_DBM)
                        ff.source_enable(True)
                        rows, res = power_sweep(ff, board, fr1c, fr3c, fr1, fr3, True, START_DBM)
                        ff.source_enable(False)
                        write_csv(out / f"{side}_FR1_{fr1_g:g}_FR3_{fr3_g:g}.csv", rows)
                        p1, p3 = res.get("p1db"), res.get("p3db")
                        row = {"sideband": side, "fr1_ghz": f"{fr1_g:g}", "fr3_ghz": f"{fr3_g:g}", "lo_ghz": f"{lo / 1e9:g}",
                               "filter_bits": f"0x{bits:02X}", "lmx_power": drive, "i_v": f"{iv:.5f}", "q_v": f"{qv:.5f}",
                               "small_signal_gain_db": "" if res.get("small_signal_gain_db") is None
                               else f"{res['small_signal_gain_db']:.2f}",
                               "p1db_in_dbm": "" if not p1 else p1["input_dbm"], "p1db_out_dbm": "" if not p1 else p1["output_dbm"],
                               "p3db_in_dbm": "" if not p3 else p3["input_dbm"], "p3db_out_dbm": "" if not p3 else p3["output_dbm"],
                               "stop_reason": res.get("stop_reason", ""), "lmx_temp_c": f"{temp:.1f}",
                               "time": datetime.now().astimezone().isoformat(timespec="seconds")}
                        new = not summary.exists()
                        with open(summary, "a", newline="") as fh:
                            w = csv.DictWriter(fh, fieldnames=list(row))
                            if new:
                                w.writeheader()
                            w.writerow(row)
                    except Exception as err:                                   # noqa: BLE001 - log and carry on
                        ff.source_enable(False)
                        print(f"  FAILED: {err}", flush=True)
                        ff.errors()
        finally:
            ff.source_enable(False)
            ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            off = not ff.source_state()
            print(f"done in {(time.monotonic() - t0) / 60:.1f} min\n" +
                  ("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
