"""Does the FieldFox's reading of a fixed tone depend on its input attenuation and reference level?

Board in a fixed state (LO 12 GHz, IQ THRU, filter bypass, -40 dBm at IF 2 GHz): the wanted tone at RF 14 GHz
and the image at 10 GHz are read (stepped CW, 1 MHz span, marker) at several (attenuation, reference level)
combinations, each several times. The tones' true levels do not change, so any difference between combinations
is the analyzer's own amplitude error. The first combination is repeated at the end to expose drift.

    python analyzer_setting_check.py

The FieldFox source is always switched off at the end (read back) and the board's configuration restored."""

from __future__ import annotations

import sys
import time

import numpy as np

from board import MeasurementSession
from conversion_gain_small_case import configure_board
from fieldfox import SETTLE_S, FieldFox

LO_HZ, IF_HZ, DRIVE = 12e9, 2e9, -40.0
COMBOS = [(35, 20), (35, 10), (20, 20), (20, 10), (25, 10), (15, 10), (10, 10), (35, 20)]   # (attenuation dB, ref dBm)
READS = 4


def main() -> int:
    with MeasurementSession() as board, FieldFox("192.168.137.61", span_hz=1e6) as ff:
        try:
            ff.setup_spectrum_analyzer(ref_level_dbm=20.0)
            ff.source_enable(False)
            configure_board(board, LO_HZ, "upper")
            ff.source_configure(IF_HZ, DRIVE)
            ff.source_enable(True)
            time.sleep(SETTLE_S)
            tones = {"wanted 14 GHz": LO_HZ + IF_HZ, "image 10 GHz": LO_HZ - IF_HZ}
            results: list[dict[str, float]] = []
            print(f"{'attenuation':>11} {'ref':>6}   " + "   ".join(f"{t:>14}" for t in tones))
            for att, ref in COMBOS:
                ff.set_ref_level(float(ref))
                ff.set_attenuation(float(att))
                row = {}
                for name, f in tones.items():
                    row[name] = float(np.mean([ff.measure_at(f).power_dbm for _ in range(READS)]))
                results.append(row)
                print(f"{att:9d} dB {ref:+5d}   " + "   ".join(f"{row[t]:12.2f} dBm" for t in tones))
            base = results[0]
            print("\nChange relative to the first combination (35 dB, +20 dBm):")
            for (att, ref), row in zip(COMBOS, results):
                print(f"{att:9d} dB {ref:+5d}   " + "   ".join(f"{row[t] - base[t]:+12.2f} dB " for t in tones))
        finally:
            ff.source_enable(False)
            ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            print("\nFieldFox source " + ("confirmed OFF (read back)." if not ff.source_state() else "*** STILL ON ***"))
    print("Board configuration restored, flash persistence back ON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
