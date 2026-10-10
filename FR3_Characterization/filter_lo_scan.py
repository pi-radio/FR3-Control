"""TX filter scan: which of the AM3153 filter states passes the wanted sideband best and rejects the LO leakage and the unwanted sideband?

    python filter_lo_scan.py [--los 8 12 16 20] [--ifs 1 2 3] [--drive-dbm -40] [--name filter_lo_scan_<date>]

FieldFox Port 1 -> FR1 cable -> board TX IF input; board TX FR3 output -> FR3 cable -> FieldFox Port 2 (analyzer, 1 MHz span, marker
readings, 100 ms settling after every retune, attenuation 20 dB, reference +10 dBm, all fixed for the whole scan).
For every LO, every one of the 49 TX filter states (bypass 0x00, and 0x30/0x10/0x20 + 0..15 = the three banks), and both IQ states
(THRU = upper sideband wanted, SWAP = lower sideband wanted) the board uses the GUI-shipped LO-null bias for that LO, and the scan reads
  - the LO leakage at RF = LO (FieldFox source OFF),
  - with the IF source ON at each IF (CW, --drive-dbm): the tone at LO + IF and the tone at LO - IF (one of them is the wanted tone, the other the
    unwanted sideband, depending on the IQ state).
All levels are cable-corrected to the board's connectors. The datasheet S21 of each filter state at the three frequencies (from
FR3_GUI/data/am3153_sparams) is written alongside for comparison. LMX power 7, LO internal.
Safety: the FieldFox source is switched off after every measurement block and confirmed OFF (read back) at the end; the board's
configuration (including the TX filter) is restored afterwards, with flash persistence back ON.
Output: results/unit_<serial>/<name>/filter_scan.csv (written after every LO), metadata.json."""

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
from conversion_gain_small_case import configure_board, must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from fr3_gui.am3153_filter import get_response
from fr3_gui.lo_suppression import suggest_iv_qv
from results_layout import unit_dir

STATES = [0x00] + [bank | sub for bank in (0x30, 0x10, 0x20) for sub in range(16)]     # 49 states
BANK_NAME = {0x00: "bypass", 0x30: "band1", 0x10: "band2", 0x20: "band3"}
ATTENUATION_DB = 20
REF_LEVEL_DBM = 10.0
FF_GUARD_DBM = 23.0
FIELDS = ["lo_ghz", "iq", "if_ghz", "state_hex", "band", "sub", "rf_wanted_ghz", "rf_unwanted_ghz", "wanted_dbm", "unwanted_dbm",
          "lo_leak_dbm", "floor_dbm", "drive_at_board_dbm", "gain_db", "lmx_temp_c", "pred_s21_wanted_db", "pred_s21_unwanted_db",
          "pred_s21_lo_db"]


def s21_at(bits: int, f_hz: float) -> float:
    r = get_response(bits)
    return float(np.interp(f_hz, r.freq_hz, r.s21_db))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--los", nargs="+", type=float, default=[8.0, 12.0, 16.0, 20.0])
    parser.add_argument("--ifs", nargs="+", type=float, default=[1.0, 2.0, 3.0])
    parser.add_argument("--drive-dbm", type=float, default=-40.0)
    parser.add_argument("--name", default=f"filter_lo_scan_{datetime.now():%Y%m%d}")
    parser.add_argument("--host", default="192.168.137.61")
    args = parser.parse_args()

    cable_if, cable_rf = CableLoss("fr1_cable"), CableLoss("fr3_cable")
    for f in args.ifs:
        cable_if.s21_db(f * 1e9)
    for lo in args.los:
        for f in [lo] + [lo + i for i in args.ifs] + [lo - i for i in args.ifs] + [lo + 0.5]:
            cable_rf.s21_db(f * 1e9)

    session = MeasurementSession()
    with session as board, FieldFox(args.host) as ff:
        serial = board.get_board_serial()
        outdir = unit_dir(serial) / args.name
        outdir.mkdir(parents=True, exist_ok=True)
        meta = {"unit_serial": serial, "los_ghz": args.los, "ifs_ghz": args.ifs, "drive_dbm": args.drive_dbm, "attenuation_db": ATTENUATION_DB,
                "ref_level_dbm": REF_LEVEL_DBM, "bias": "GUI-shipped table (fr3_gui/data/lo_suppression.csv)", "lmx_power": 7,
                "states": [f"0x{s:02X}" for s in STATES], "started": datetime.now().astimezone().isoformat(timespec="seconds"),
                "fr1_cable_file": cable_if.path.name, "fr3_cable_file": cable_rf.path.name, "persist_before": session.persist_before,
                "board_state_found": session.snapshot}
        print(f"Unit #{serial}: {len(args.los)} LOs x {len(STATES)} filter states x 2 IQ states x {len(args.ifs)} IFs. {outdir}", flush=True)
        rows = []
        try:
            ff.setup_spectrum_analyzer(ref_level_dbm=REF_LEVEL_DBM)      # 1 MHz span, CLRW, single sweeps
            ff.source_enable(False)
            ff.set_attenuation(ATTENUATION_DB)
            meta["ff_idn"] = ff.identify()
            configure_board(board, args.los[0] * 1e9, "upper")
            t_start = time.monotonic()
            for lo in args.los:
                iv = suggest_iv_qv(lo)
                assert iv is not None
                tune_and_lock(board, lo * 1e9)
                must(board.set_i_v(iv[0]) and board.set_q_v(iv[1]), "SET I_V/Q_V")
                time.sleep(SETTLE_S)
                ff.source_enable(False)
                floor = ff.measure_at((lo + 0.5) * 1e9, recenter=False).power_dbm - cable_rf.s21_db((lo + 0.5) * 1e9)
                print(f"LO {lo:g} GHz: shipped bias I_V {iv[0]:+.4f} Q_V {iv[1]:+.4f}, LMX {board.get_lmx_temperature_c():.1f} C, "
                      f"analyzer floor about {floor:+.1f} dBm  (elapsed {time.monotonic() - t_start:.0f} s)", flush=True)
                for n_state, state in enumerate(STATES):
                    must(board.set_tx_filter(state), f"SET TXFILTER 0x{state:02X}")
                    time.sleep(SETTLE_S)
                    temp = board.get_lmx_temperature_c()
                    for iq in ("THRU", "SWAP"):
                        must(board.set_iq_swap(iq == "SWAP"), f"SET IQ {iq}")
                        time.sleep(SETTLE_S)
                        ff.source_enable(False)
                        time.sleep(SETTLE_S)
                        lo_leak = ff.measure_at(lo * 1e9, recenter=False).power_dbm - cable_rf.s21_db(lo * 1e9)
                        for f_if in args.ifs:
                            ff.source_configure(f_if * 1e9, args.drive_dbm)
                            ff.source_enable(True)
                            time.sleep(SETTLE_S)
                            f_up, f_dn = lo + f_if, lo - f_if
                            up = ff.measure_at(f_up * 1e9, recenter=False).power_dbm
                            dn = ff.measure_at(f_dn * 1e9, recenter=False).power_dbm
                            if max(up, dn) > FF_GUARD_DBM:
                                raise RuntimeError(f"analyzer input would exceed the +{FF_GUARD_DBM:g} dBm guard")
                            up_b, dn_b = up - cable_rf.s21_db(f_up * 1e9), dn - cable_rf.s21_db(f_dn * 1e9)
                            wanted, unwanted = ((up_b, dn_b) if iq == "THRU" else (dn_b, up_b))
                            f_w, f_u = ((f_up, f_dn) if iq == "THRU" else (f_dn, f_up))
                            drive_b = args.drive_dbm + cable_if.s21_db(f_if * 1e9)
                            rows.append({"lo_ghz": lo, "iq": iq, "if_ghz": f_if, "state_hex": f"0x{state:02X}",
                                         "band": BANK_NAME[state & 0x30], "sub": state & 0x0F, "rf_wanted_ghz": f_w,
                                         "rf_unwanted_ghz": f_u, "wanted_dbm": f"{wanted:.2f}", "unwanted_dbm": f"{unwanted:.2f}",
                                         "lo_leak_dbm": f"{lo_leak:.2f}", "floor_dbm": f"{floor:.1f}",
                                         "drive_at_board_dbm": f"{drive_b:.2f}", "gain_db": f"{wanted - drive_b:.2f}",
                                         "lmx_temp_c": f"{temp:.1f}",
                                         "pred_s21_wanted_db": f"{s21_at(state, f_w * 1e9):.2f}",
                                         "pred_s21_unwanted_db": f"{s21_at(state, f_u * 1e9):.2f}",
                                         "pred_s21_lo_db": f"{s21_at(state, lo * 1e9):.2f}"})
                        ff.source_enable(False)
                    if n_state % 8 == 0:
                        r = [x for x in rows if x["state_hex"] == f"0x{state:02X}" and x["iq"] == "THRU" and x["if_ghz"] == args.ifs[0]][-1]
                        print(f"  LO {lo:g} GHz, state 0x{state:02X} ({BANK_NAME[state & 0x30]}): wanted {r['wanted_dbm']}, unwanted {r['unwanted_dbm']}, "
                              f"LO {r['lo_leak_dbm']} dBm  [{n_state + 1}/{len(STATES)}, elapsed {time.monotonic() - t_start:.0f} s]", flush=True)
                errs = ff.errors()
                if errs:
                    print("  FieldFox errors:", errs, flush=True)
                with open(outdir / "filter_scan.csv", "w", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=FIELDS)
                    w.writeheader()
                    w.writerows(rows)
                print(f"LO {lo:g} GHz done: {len(rows)} rows so far.", flush=True)
            print("Scan complete.", flush=True)
        finally:
            ff.source_enable(False)
            ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            off = not ff.source_state()
            meta["finished"] = datetime.now().astimezone().isoformat(timespec="seconds")
            meta["ff_source_verified_off"] = off
            (outdir / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
            print("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON!", flush=True)
    print("Board configuration restored, flash persistence back ON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
