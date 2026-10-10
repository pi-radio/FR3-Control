"""FieldFox source-only loopback: is the FieldFox's CW source (plus its own
analyzer) linear over the drive levels used in the TX power sweep?

Wiring for this test (the board is NOT used and is not touched):
    FieldFox Port 1 --- FR1 cable ---> FieldFox Port 2

    python source_loopback_check.py [--ghz 2.0] [--from-dbm -45] [--to-dbm -10] [--step-db 1]

Sets the source to the same commanded powers the TX sweep used, with the same
settings as that sweep (1 MHz span, input attenuation held fixed at 35 dB), and
reads the tone. In a perfectly linear setup 'loss' is one constant number (the
cable) at every drive level. A bump like the ~1.3 dB gain expansion seen in the
TX sweep would show up here as a variation of 'loss' with drive level - i.e.
it would come from the FieldFox, not from the board.

The source is always switched off at the end (and on any error), read back."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from fieldfox import SETTLE_S, FieldFox
from results_layout import INSTRUMENT_CHECKS_DIR

REF_DBM = 20.0
ATTENUATION_DB = 35
MIN_SNR_DB = 25.0              # only points this far above the measured noise floor are judged
WINDOW_DBM = (-31.0, -19.0)    # where the TX sweep showed its gain expansion
LINEAR_WITHIN_DB = 0.25


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.137.61")
    parser.add_argument("--ghz", type=float, default=2.0)
    parser.add_argument("--from-dbm", type=float, default=-45.0)
    parser.add_argument("--to-dbm", type=float, default=-10.0)
    parser.add_argument("--step-db", type=float, default=1.0)
    args = parser.parse_args()
    if args.to_dbm > -5.0:
        sys.exit("refusing --to-dbm above -5 dBm: this is a loopback into the analyzer")

    freq = args.ghz * 1e9
    n = int(round((args.to_dbm - args.from_dbm) / args.step_db)) + 1
    levels = [round(args.from_dbm + i * args.step_db, 3) for i in range(n)]
    # No board is involved, so this belongs to no unit.
    outdir = INSTRUMENT_CHECKS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_source_loopback_{args.ghz:g}GHz_att{ATTENUATION_DB}"
    outdir.mkdir(parents=True)

    rows: list[dict] = []
    with FieldFox(args.host) as ff:
        meta = {"args": vars(args), "started": datetime.now().astimezone().isoformat(timespec="seconds")}
        try:
            meta["ff_idn"] = ff.identify()
            ff.setup_spectrum_analyzer(ref_level_dbm=REF_DBM)
            ff.source_enable(False)
            ff.set_attenuation(ATTENUATION_DB)
            meta.update(ff_span_hz=ff.span_hz, ff_rbw_hz=ff.rbw_hz, ff_attenuation_db=ff.attenuation_db)
            print(f"Source-only loopback at {args.ghz:g} GHz: span {ff.span_hz/1e6:g} MHz, RBW "
                  f"{ff.rbw_hz/1e3:g} kHz, input attenuation fixed at {ff.attenuation_db:.0f} dB")
            meta["noise_floor_dbm"] = floor = ff.measure_at(freq).power_dbm  # source still OFF
            print(f"Noise floor at this frequency and attenuation (source off, marker peak): {floor:.1f} dBm; "
                  f"points closer than {MIN_SNR_DB:.0f} dB to it are not judged")
            ff.source_configure(freq, levels[0])
            ff.source_enable(True)
            time.sleep(SETTLE_S)
            for p in levels:
                ff.source_configure(freq, p)
                time.sleep(SETTLE_S)
                r = ff.measure_at(freq)
                rows.append({"ff_source_dbm": p, "measured_dbm": round(r.power_dbm, 3),
                             "loss_db": round(p - r.power_dbm, 3),
                             "tone_offset_hz": round(r.freq_hz - freq, 1)})
            ff.check("loopback sweep")
        finally:
            ff.source_enable(False)
            ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            meta["ff_source_verified_off"] = not ff.source_state()
            print("FieldFox source " + ("confirmed OFF (read back)." if meta["ff_source_verified_off"]
                                        else "*** STILL ON - switch it off! ***"))

    # Judge only points well above the noise floor: near it, the marker-peak reading is
    # biased and scattered by noise, which is not a property of the source or analyzer.
    usable = [r for r in rows if r["measured_dbm"] >= floor + MIN_SNR_DB]
    if len(usable) < 5:
        sys.exit("fewer than 5 points are well above the noise floor - cannot judge linearity")
    losses = sorted(r["loss_db"] for r in usable)
    base = losses[len(losses) // 2]  # median: robust reference loss
    print("\n   set    read    loss  deviation")
    for r in rows:
        r["usable"] = int(r in usable)
        r["deviation_db"] = round(r["loss_db"] - base, 3)
        note = "" if r["usable"] else "   (noise-limited, not judged)"
        print(f"  {r['ff_source_dbm']:+6.1f} {r['measured_dbm']:+7.2f} {r['loss_db']:+7.3f} {r['deviation_db']:+8.3f}{note}")

    worst = max(usable, key=lambda r: abs(r["deviation_db"]))
    window = [r for r in usable if WINDOW_DBM[0] <= r["ff_source_dbm"] <= WINDOW_DBM[1]]
    worst_window = max(window, key=lambda r: abs(r["deviation_db"])) if window else None
    print(f"\nReference loss (median of {len(usable)} judged points): {base:.3f} dB")
    print(f"Largest deviation over the judged points: {worst['deviation_db']:+.3f} dB at {worst['ff_source_dbm']:+.1f} dBm")
    if worst_window:
        print(f"Largest deviation in the TX sweep's expansion window {WINDOW_DBM[0]:.0f}..{WINDOW_DBM[1]:.0f} dBm: "
              f"{worst_window['deviation_db']:+.3f} dB at {worst_window['ff_source_dbm']:+.1f} dBm")
    verdict = ("The FieldFox source + analyzer are linear to within "
               f"{abs(worst['deviation_db']):.2f} dB over the judged range, so they cannot explain a ~1.3 dB expansion."
               if abs(worst["deviation_db"]) <= LINEAR_WITHIN_DB else
               f"The FieldFox itself deviates by up to {worst['deviation_db']:+.2f} dB - "
               "it contributes to (or explains) the apparent expansion.")
    print(verdict)

    with open(outdir / "loopback.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    meta.update(reference_loss_db=round(base, 3), verdict=verdict,
                finished=datetime.now().astimezone().isoformat(timespec="seconds"))
    (outdir / "metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"Saved {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
