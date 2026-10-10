"""RX image rejection over the datasheet grid with discrete CW tones (2026-10-09 hot RX re-run; the same 426-point grid as the
gain and sideband-suppression sections, user).

    python rx_image_campaign.py [--limit N] [--campaign image_rx_<date>] [--dry-run] [--lo-min-ghz X]

GRID: flatness_campaign.grid("rx"): FR1 1.0-4.0 GHz and FR3 6.0-26.0 GHz in 0.5 GHz steps, low-side and high-side LO,
7 <= LO <= 22.6 GHz; each point with the RX filter BYPASSED and with the per-point optimal filter. Points whose image lies
above 26.5 GHz (FieldFox source / cable limit) are skipped.

AT EVERY POINT: LO tuned at the LMX drive rule; the TX side in normal use (rx_tx_side.py; TX ports terminated). FieldFox
source CW at --input-dbm at "RX-side FR3 RF In" (FR3 cable removed; default -50 dBm, the RX gain sections' level, far below
the -5 dBm cap): first at the desired FR3, then at the image (low-side: LO - FR1, high-side: LO + FR1). Each time the IF tone
at FR1 is read at "RX-side FR1 IF Out" (FR1 cable removed): 1 MHz span, RBW 10 kHz, 30 dB attenuation, no averaging, fresh
peak search, continuous sweep ON. Image rejection = output(desired) - output(image), both inputs at the same level (dB).
The raw image reading is kept and flagged when it is below NOISE_FLAG_DBM at the analyzer.

Output: results/unit_005/<campaign>/points.csv (resumable), campaign.json. Source OFF at the end (read back); the board's
configuration is restored (MeasurementSession).
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
from rx_tx_side import tx_normal_state
from spur_campaign import restore_ff
from tx_lo_products import read, setup_ff

NOISE_FLAG_DBM = -85.0
MAX_INPUT_DBM = -5.0                                       # never more than this into "RX-side FR3 RF In" (user)


def key(pt, filt) -> str:
    return f"{pt['config']}|{pt['fr1_hz']:.0f}|{pt['fr3_hz']:.0f}|{filt}"


def image_hz(pt) -> float:
    return pt["lo_hz"] - pt["fr1_hz"] if pt["config"] == "low" else pt["lo_hz"] + pt["fr1_hz"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dbm", type=float, default=-50.0, help="CW level at the RX-side FR3 RF In connector")
    ap.add_argument("--lo-min-ghz", type=float, default=0.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--campaign", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--expect-unit", type=int, default=5)
    ap.add_argument("--only", default="", help="only these points, e.g. low:1:9,high:2:14 (LO side:FR1:FR3 in GHz)")
    args = ap.parse_args()
    if args.input_dbm > MAX_INPUT_DBM:
        raise SystemExit(f"--input-dbm {args.input_dbm} is above the {MAX_INPUT_DBM} dBm RX input cap")
    pts = [p for p in grid("rx") if image_hz(p) <= FF_MAX_HZ + 1]
    if args.only:
        want = set(args.only.split(","))
        pts = [p for p in pts if f"{p['config']}:{p['fr1_hz'] / 1e9:g}:{p['fr3_hz'] / 1e9:g}" in want]
    if args.dry_run:
        print(f"{len(pts)} points x 2 filters = {2 * len(pts)} cases (of {len(grid('rx'))} grid points); ~4 s each -> "
              f"~{2 * len(pts) * 4 / 60:.0f} min")
        return 0
    if args.lo_min_ghz:
        pts = [p for p in pts if p["lo_hz"] > args.lo_min_ghz * 1e9 + 1]
    if args.limit:
        pts = pts[:args.limit]
    campaign = args.campaign or f"image_rx_{datetime.now():%Y%m%d}"
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
            "script": "rx_image_campaign.py", "lmx_power": "drive rule", "input_dbm_at_connector": args.input_dbm,
            "tx_side": "normal use (rx_tx_side.py)", "bias": f"cal tables: {tables.cold_path} / {tables.hot_path}",
            "reading": "IF tone at FR1: 1 MHz span, RBW 10 kHz, 30 dB att, no averaging, peak search; cables removed", "runs": []}
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
            for k, pt in enumerate(pts, 1):
                if all(key(pt, f) in done for f in ("bypass", "optimal")):
                    continue
                try:
                    drive = set_drive_for(board, pt["lo_hz"])
                    tune_and_lock(board, pt["lo_hz"])
                    temp = board.get_lmx_temperature_c()
                    tx = tx_normal_state(board, tables, pt["fr3_hz"], pt["lo_hz"], temp)
                    f_img = image_hz(pt)
                    for filt, bits in (("bypass", 0x00), ("optimal", pt["opt_filter"])):
                        if key(pt, filt) in done:
                            continue
                        must(board.set_rx_filter(bits), f"SET RXFILTER 0x{bits:02X}")
                        res = {}
                        for name, f_in in (("desired", pt["fr3_hz"]), ("image", f_img)):
                            src = args.input_dbm - fr3c.s21_db(f_in)        # lands input_dbm at the connector
                            ff.source_configure(f_in, src)
                            ff.source_enable(True)
                            time.sleep(SETTLE_S)
                            fx, p = read(ff, pt["fr1_hz"])
                            ff.source_enable(False)
                            res[name] = (fx, p, p - fr1c.s21_db(fx))
                        des, img = res["desired"][2], res["image"][2]
                        row = {"key": key(pt, filt), "config": pt["config"], "filter": filt, "filter_bits": f"0x{bits:02X}",
                               "fr1_hz": f"{pt['fr1_hz']:.0f}", "fr3_hz": f"{pt['fr3_hz']:.0f}", "lo_hz": f"{pt['lo_hz']:.0f}",
                               "image_hz": f"{f_img:.0f}", "input_dbm": args.input_dbm,
                               "desired_out_dbm": f"{des:.2f}", "image_out_dbm": f"{img:.2f}", "rejection_db": f"{des - img:.2f}",
                               "desired_raw_dbm": f"{res['desired'][1]:.2f}", "image_raw_dbm": f"{res['image'][1]:.2f}",
                               "image_near_floor": int(res["image"][1] < NOISE_FLAG_DBM), "gain_db": f"{des - args.input_dbm:.2f}",
                               "lmx_power": drive, **tx, "lmx_temp_c": f"{temp:.1f}", "lmx_lock": board.get_lmx_lock(),
                               "time": datetime.now().astimezone().isoformat(timespec="seconds")}
                        new = not path.exists()
                        with open(path, "a", newline="") as fh:
                            w = csv.DictWriter(fh, fieldnames=list(row))
                            if new:
                                w.writeheader()
                            w.writerow(row)
                        print(f"  [{k}/{len(pts)}] {pt['config']:4s} FR1 {pt['fr1_hz'] / 1e9:.1f} FR3 {pt['fr3_hz'] / 1e9:5.1f} "
                              f"LO {pt['lo_hz'] / 1e9:5.1f} {filt:7s} 0x{bits:02X}: desired {des:+6.1f}  image {img:+6.1f} "
                              f"-> {des - img:5.1f} dB{'  (image near floor)' if row['image_near_floor'] else ''}  {temp:.1f} C",
                              flush=True)
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
