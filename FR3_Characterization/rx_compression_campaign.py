"""RX compression at the datasheet's 9 representative (FR1, FR3) points per LO side (2026-10-09 hot RX re-run; the same
points as the earlier RX panels, user).

    python rx_compression_campaign.py [--side low|high|both] [--campaign compression_rx_<date>] [--limit N] [--only low:1:9,...]

POINTS (Sections 14 and 15): low-side LO (FR3 = LO + FR1) and high-side LO (FR3 = LO - FR1), FR1 1.0 / 2.0 / 3.5 GHz.

AT EVERY POINT: LO tuned at the LMX drive rule (lmx_drive.py); the TX side in normal use (rx_tx_side.py: stored LO-null bias,
IQ state, optimal TX filter; TX ports terminated); RX filter = the per-point optimal filter (rx_nf_campaign.optimal_rx_filter);
wait until the LMX temperature holds for 30 s (as compression_campaign.py). Power sweep = conversion_gain_small_case.power_sweep
with the source at FR3 (FR3 cable) and the reading at FR1 (FR1 cable): from -60 dBm at the FieldFox source, 2 dB steps (0.5 dB
past 0.3 dB compression), analyzer attenuation fixed at 35 dB, 1 MHz span, fresh peak search; stops at 5 dB compression, or
when the next step would put more than -5 dBm INTO "RX-side FR3 RF In" (HMC963 safety cap, user), or at 0 dBm source.
Small-signal gain and the P1dB / P3dB search use the -50 dBm-and-up steps (compression_campaign.py's rule, imported).

Output: results/unit_005/<campaign>/<side>_FR1_<x>_FR3_<y>.csv and summary.csv; campaign.json. Source OFF at the end (read
back); the board's configuration is restored (MeasurementSession).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime

import compression_campaign  # noqa: F401  (applies the small-signal / P1dB rules and the 5 dB stop to conversion_gain_small_case)
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
from rx_tx_side import tx_normal_state

POINTS = {"low": [(1.0, 9.0), (2.0, 9.0), (3.5, 11.5), (1.0, 13.0), (2.0, 15.0), (3.5, 17.5), (1.0, 19.0), (2.0, 22.0),
                  (3.5, 25.5)],
          "high": [(1.0, 8.0), (2.0, 8.0), (3.5, 9.0), (1.0, 13.0), (2.0, 14.0), (3.5, 15.0), (1.0, 19.0), (2.0, 19.0),
                   (3.5, 18.5)]}
START_DBM = compression_campaign.START_DBM            # -60 dBm at the FieldFox source (user rule)
cg.MAX_INPUT_AT_DUT_DBM = -5.0                         # never more than -5 dBm into "RX-side FR3 RF In" (user)


def settle(board, timeout_s: float = 240, hold_s: float = 30) -> float:
    """Wait until the LMX temperature holds within 0.5 C for hold_s (at most timeout_s); returns the temperature."""
    t_end, last, since = time.monotonic() + timeout_s, board.get_lmx_temperature_c(), time.monotonic()
    while time.monotonic() < t_end and time.monotonic() - since < hold_s:
        time.sleep(5)
        now_t = board.get_lmx_temperature_c()
        if abs(now_t - last) > 0.5:
            last, since = now_t, time.monotonic()
    return board.get_lmx_temperature_c()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=("low", "high", "both"), default="both")
    ap.add_argument("--campaign", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="only these points, e.g. low:1:9,high:3.5:18.5")
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--settle-s", type=float, default=30.0,
                    help="LMX temperature must hold within 0.5 C this long before each sweep (datasheet 30; production 15)")
    args = ap.parse_args()
    sides = ("low", "high") if args.side == "both" else (args.side,)
    campaign = args.campaign or f"compression_rx_{datetime.now():%Y%m%d}"
    fr1c, fr3c = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    tables = CalTables()
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        out = unit_dir(serial) / campaign
        out.mkdir(parents=True, exist_ok=True)
        (out / "campaign.json").write_text(json.dumps({
            "script": "rx_compression_campaign.py", "lmx_power": "drive rule", "start_dbm_at_source": START_DBM,
            "max_input_at_board_dbm": cg.MAX_INPUT_AT_DUT_DBM, "stop_at_compression_db": cg.STOP_AT_COMPRESSION_DB,
            "attenuation_db": cg.DEFAULT_FIXED_ATTENUATION_DB, "tx_side": "normal use (rx_tx_side.py)",
            "bias": f"cal tables interpolated: {tables.cold_path} / {tables.hot_path}", "points": POINTS,
            "started": datetime.now().astimezone().isoformat(timespec="seconds"), "ff_idn": ff.identify()}, indent=2))
        summary = out / "summary.csv"
        done = {(r["side"], r["fr1_ghz"], r["fr3_ghz"]) for r in csv.DictReader(open(summary, newline=""))} \
            if summary.exists() else set()
        t0 = time.monotonic()
        try:
            ff.setup_spectrum_analyzer(ref_level_dbm=cg.REF_FIXED_DBM)
            ff.source_enable(False)
            ff.set_attenuation(cg.DEFAULT_FIXED_ATTENUATION_DB)
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            for side in sides:
                pts = POINTS[side][:args.limit] if args.limit else POINTS[side]
                for fr1_g, fr3_g in pts:
                    if args.only and f"{side}:{fr1_g:g}:{fr3_g:g}" not in args.only.split(","):
                        continue
                    if (side, f"{fr1_g:g}", f"{fr3_g:g}") in done:
                        continue
                    fr1, fr3 = fr1_g * 1e9, fr3_g * 1e9
                    lo = fr3 - fr1 if side == "low" else fr3 + fr1
                    print(f"\n=== {side}-side LO, FR1 {fr1_g:g} GHz, FR3 {fr3_g:g} GHz, LO {lo / 1e9:g} GHz", flush=True)
                    try:
                        drive = set_drive_for(board, lo)
                        tune_and_lock(board, lo)
                        bits = optimal_rx_filter({"fr3_hz": fr3, "lo_hz": lo})
                        must(board.set_rx_filter(bits), f"SET RXFILTER 0x{bits:02X}")
                        tx_normal_state(board, tables, fr3, lo)
                        temp = settle(board, hold_s=args.settle_s)
                        tx = tx_normal_state(board, tables, fr3, lo, temp)   # re-apply for the settled temperature
                        print(f"  LMX settled at {temp:.1f} C", flush=True)
                        ff.source_configure(fr3, START_DBM)
                        ff.source_enable(True)
                        rows, res = power_sweep(ff, board, fr3c, fr1c, fr3, fr1, True, START_DBM)
                        ff.source_enable(False)
                        write_csv(out / f"{side}_FR1_{fr1_g:g}_FR3_{fr3_g:g}.csv", rows)
                        p1, p3 = res.get("p1db"), res.get("p3db")
                        row = {"side": side, "fr1_ghz": f"{fr1_g:g}", "fr3_ghz": f"{fr3_g:g}", "lo_ghz": f"{lo / 1e9:g}",
                               "rx_filter_bits": f"0x{bits:02X}", "lmx_power": drive, **tx,
                               "small_signal_gain_db": "" if res.get("small_signal_gain_db") is None
                               else f"{res['small_signal_gain_db']:.2f}",
                               "p1db_in_dbm": "" if not p1 else p1["input_dbm"], "p1db_out_dbm": "" if not p1 else p1["output_dbm"],
                               "p3db_in_dbm": "" if not p3 else p3["input_dbm"], "p3db_out_dbm": "" if not p3 else p3["output_dbm"],
                               "max_input_dbm": max(r["in_at_dut_dbm"] for r in rows) if rows else "",
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
