"""Phase noise of an external LO source connected straight to the UXA (e.g. the Pi-Radio OctoLO), with exactly the
same UXA Phase Noise settings as phase_noise_capture.py (Log Plot 100 Hz - 1 MHz, signal tracking on, 10 averages,
mode preset + Auto Tune, overload and carrier-frequency checks). Talks ONLY to the UXA: no board, and nothing is
sent to the source.

    python measure_external_lo.py --lo-ghz 10 --source octolo

Saves results/external_lo/<source>_lo<GHz>GHz_<stamp>.csv/.json (same columns as phase_noise_capture.py).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime

from phase_noise_capture import MAX_CARRIER_FREQ_ERROR_HZ, disable_alignment, measure_log_plot
from results_layout import RESULTS_DIR
from rx_clock_comb_capture import Uxa


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-ghz", type=float, required=True)
    ap.add_argument("--source", default="octolo")
    ap.add_argument("--navg", type=int, default=10)
    args = ap.parse_args()
    lo_hz = args.lo_ghz * 1e9
    uxa = Uxa()
    print("UXA:", uxa.query("*IDN?"))
    disable_alignment(uxa)
    meta, rows = measure_log_plot(uxa, lo_hz, args.navg, carrier_dbm_at_uxa=0.0)
    if abs(meta["carrier_hz"] - lo_hz) > MAX_CARRIER_FREQ_ERROR_HZ:
        raise RuntimeError(f"measured a carrier at {meta['carrier_hz']/1e9:.6f} GHz, not {args.lo_ghz:g} GHz - not saving")
    meta.update({"lo_hz": lo_hz, "source": args.source, "time": datetime.now().isoformat(timespec="seconds")})
    outdir = RESULTS_DIR / "external_lo"
    outdir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.source}_lo{args.lo_ghz:g}GHz_{datetime.now():%Y%m%d_%H%M%S}"
    with open(outdir / f"{stem}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["offset_hz", "trace1_dbc_hz", "trace2_dbc_hz"])
        w.writerows(rows)
    (outdir / f"{stem}.json").write_text(json.dumps(meta, indent=2))
    print(f"carrier {meta['carrier_dbm']:+.2f} dBm (at the UXA input) at {meta['carrier_hz']/1e9:.6f} GHz; "
          f"RMS PN {meta['rms_pn_deg']:.3f} deg")
    for target in (100, 1e3, 1e4, 1e5, 1e6):
        near = min(rows, key=lambda r: abs(r[0] - target))
        print(f"  {target:>9.0f} Hz: smoothed {near[2]:7.1f}  unsmoothed {near[1]:7.1f} dBc/Hz")
    print("saved", outdir / f"{stem}.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
