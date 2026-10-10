"""TX sideband suppression over the datasheet grid, with discrete CW tones (user spec 2026-10-08: re-run at LMX drive 0,
with the unit's stored LO-null calibration -- "Option A", how a user's unit actually runs).

    python sideband_campaign.py [--limit N] [--campaign sideband_tx_<date>] [--dry-run]

GRID: the same as the gain and flatness sections (flatness_campaign.grid("tx")): FR1 1.0-4.0 GHz and FR3 6.0-26.5 GHz in
0.5 GHz steps, upper and lower sideband, 7 <= LO <= 22.6 GHz; each point measured with the TX filter BYPASSED and with the
per-point "optimal" filter. Points whose undesired sideband lies above 26.5 GHz (FieldFox / cable limit) are skipped.

AT EVERY POINT: LO tuned (LMX drive --lmx-power, default 0); I_V/Q_V from the stored cold/hot calibration interpolated to the
LMX temperature read at that point (lo_cal_tables.py); IQ THRU for upper, SWAP for lower. FieldFox source: CW at FR1,
--input-dbm at the "TX-side FR1 IF In" connector (FR1 cable removed; default -40 dBm, the gain sections' level). Read the
desired tone at FR3 and the undesired (image) tone at the other side of the LO (upper: LO - FR1, lower: LO + FR1) at
"TX-side FR3 RF Out" (FR3 cable removed): 1 MHz span, RBW 10 kHz, 30 dB attenuation, no averaging, fresh peak search,
continuous sweep ON. Suppression = desired - undesired (dB). The analyzer floor is not measured at every point (time);
the raw undesired reading is kept and flagged when it is below NOISE_FLAG_DBM at the analyzer.

Output: results/unit_005/<campaign>/points.csv (one row per point and filter; resumable), campaign.json. Source OFF at the end
(read back); the board's configuration is restored (MeasurementSession).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime

from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from flatness_campaign import FF_HOST, FF_MAX_HZ, grid
from lo_cal_tables import CalTables
from lmx_drive import set_drive_for
from results_layout import unit_dir
from tx_lo_products import read, setup_ff
from spur_campaign import restore_ff

CABLE_MAX_HZ = 26.5e9            # top of the FR3 cable S21 data
NOISE_FLAG_DBM = -85.0          # raw analyzer reading below this: the undesired tone may be at the noise floor


def key(pt, filt) -> str:
    return f"{pt['config']}|{pt['fr1_hz']:.0f}|{pt['fr3_hz']:.0f}|{filt}"


def image_hz(pt) -> float:
    return pt["lo_hz"] - pt["fr1_hz"] if pt["config"] == "upper" else pt["lo_hz"] + pt["fr1_hz"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lmx-power", default="auto", help="auto (default since 2026-10-09) = lmx_drive.drive_for(LO): 0 / 2 / 4; or a fixed level")
    ap.add_argument("--lo-min-ghz", type=float, default=0.0, help="measure only points with LO strictly above this")
    ap.add_argument("--input-dbm", type=float, default=-40.0, help="CW level at the TX-side FR1 IF In connector")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--campaign", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--only", default="", help="only these points, e.g. upper:1:9,lower:2:14 (sideband:FR1:FR3 in GHz)")
    args = ap.parse_args()
    pts = [p for p in grid("tx") if image_hz(p) <= FF_MAX_HZ + 1]
    if args.only:
        want = set(args.only.split(","))
        pts = [p for p in pts if f"{p['config']}:{p['fr1_hz'] / 1e9:g}:{p['fr3_hz'] / 1e9:g}" in want]
    if args.dry_run:
        print(f"{len(pts)} points x 2 filters = {2 * len(pts)} cases; ~3 s each -> ~{2 * len(pts) * 3 / 60:.0f} min")
        return 0
    if args.lo_min_ghz:
        pts = [p for p in pts if p["lo_hz"] > args.lo_min_ghz * 1e9 + 1]
    if args.limit:
        pts = pts[:args.limit]
    campaign = args.campaign or f"sideband_tx_{datetime.now():%Y%m%d}"
    fr1c, fr3c = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    tables = CalTables()
    with MeasurementSession() as board, FieldFox(FF_HOST, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        if args.expect_unit and serial != args.expect_unit:
            raise SystemExit(f"connected unit is #{serial}, expected #{args.expect_unit} -- nothing changed")
        out = unit_dir(serial) / campaign
        out.mkdir(parents=True, exist_ok=True)
        meta = out / "campaign.json"
        m = json.loads(meta.read_text()) if meta.exists() else {
            "script": "sideband_campaign.py", "lmx_power": args.lmx_power, "input_dbm_at_connector": args.input_dbm,
            "bias": f"cal tables interpolated: {tables.cold_path} / {tables.hot_path}",
            "reading": "1 MHz span, RBW 10 kHz, 30 dB att, no averaging, peak search; cables removed", "runs": []}
        m["runs"].append({"started": datetime.now().astimezone().isoformat(timespec="seconds"), "ff_idn": ff.identify()})
        meta.write_text(json.dumps(m, indent=2))
        path = out / "points.csv"
        done = {r["key"] for r in csv.DictReader(open(path, newline=""))} if path.exists() else set()
        print(f"Unit #{serial}: {len(pts)} points x 2 filters, {len(done)} cases already done -> {path}", flush=True)
        orig = None
        t0 = time.monotonic()
        try:
            orig = setup_ff(ff)
            must(board.set_clock_internal(True), "SET CLOCK INT")
            must(board.set_lo_internal(True), "SET LO INT")
            if args.lmx_power != "auto":
                must(board.set_lmx_power(int(args.lmx_power)), f"LMX PWR {args.lmx_power}")
            for k, pt in enumerate(pts, 1):
                if all(key(pt, f) in done for f in ("bypass", "optimal")):
                    continue
                try:
                    drive = set_drive_for(board, pt["lo_hz"]) if args.lmx_power == "auto" else int(args.lmx_power)
                    tune_and_lock(board, pt["lo_hz"])
                    temp = board.get_lmx_temperature_c()
                    iv, qv = tables.bias(pt["lo_hz"], temp)
                    must(board.set_i_v(iv), "SET I_V")
                    must(board.set_q_v(qv), "SET Q_V")
                    must(board.set_iq_swap(pt["config"] == "lower"), "SET IQ")
                    src = args.input_dbm - fr1c.s21_db(pt["fr1_hz"])            # p_in = p_source + S21, so this lands input_dbm at the connector
                    ff.source_configure(pt["fr1_hz"], src)
                    ff.source_enable(True)
                    f_img = image_hz(pt)
                    for filt, bits in (("bypass", 0x00), ("optimal", pt["opt_filter"])):
                        if key(pt, filt) in done:
                            continue
                        must(board.set_tx_filter(bits), f"SET TXFILTER 0x{bits:02X}")
                        time.sleep(SETTLE_S)
                        fd, pd = read(ff, pt["fr3_hz"])
                        fu, pu = read(ff, f_img)
                        # the FR3 cable data end at 26.5 GHz; a tone found a few kHz above that (an image exactly at 26.5 GHz) uses the
                        # 26.5 GHz value instead of being skipped (user, 2026-10-09)
                        des, und = pd - fr3c.s21_db(min(fd, CABLE_MAX_HZ)), pu - fr3c.s21_db(min(fu, CABLE_MAX_HZ))
                        row = {"key": key(pt, filt), "config": pt["config"], "filter": filt, "filter_bits": f"0x{bits:02X}",
                               "fr1_hz": f"{pt['fr1_hz']:.0f}", "fr3_hz": f"{pt['fr3_hz']:.0f}", "lo_hz": f"{pt['lo_hz']:.0f}",
                               "image_hz": f"{f_img:.0f}", "input_dbm": args.input_dbm,
                               "desired_dbm": f"{des:.2f}", "undesired_dbm": f"{und:.2f}", "suppression_db": f"{des - und:.2f}",
                               "desired_raw_dbm": f"{pd:.2f}", "undesired_raw_dbm": f"{pu:.2f}",
                               "undesired_near_floor": int(pu < NOISE_FLAG_DBM), "gain_db": f"{des - args.input_dbm:.2f}",
                               "lmx_power": drive, "i_v": f"{iv:.5f}", "q_v": f"{qv:.5f}", "lmx_temp_c": f"{temp:.1f}",
                               "lmx_lock": board.get_lmx_lock(), "time": datetime.now().astimezone().isoformat(timespec="seconds")}
                        new = not path.exists()
                        with open(path, "a", newline="") as fh:
                            w = csv.DictWriter(fh, fieldnames=list(row))
                            if new:
                                w.writeheader()
                            w.writerow(row)
                        print(f"  [{k}/{len(pts)}] {pt['config']:5s} FR1 {pt['fr1_hz'] / 1e9:.1f} FR3 {pt['fr3_hz'] / 1e9:5.1f} "
                              f"LO {pt['lo_hz'] / 1e9:5.1f} {filt:7s} 0x{bits:02X}: desired {des:+6.1f}  undesired {und:+6.1f} "
                              f"-> {des - und:5.1f} dB{'  (undesired near floor)' if pu < NOISE_FLAG_DBM else ''}  {temp:.1f} C",
                              flush=True)
                    ff.source_enable(False)
                except Exception as err:                                       # noqa: BLE001 - log and carry on
                    ff.source_enable(False)
                    print(f"  [{k}/{len(pts)}] FAILED {pt}: {err}", flush=True)
                    ff.errors()
        finally:
            off = restore_ff(ff, orig)
            print(f"done in {(time.monotonic() - t0) / 60:.1f} min\n" +
                  ("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON! ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
