"""Baseline: the FieldFox's own noise floor, with its RF input directly
50-ohm terminated (DUT, cable, everything else out of the picture). Same
settings as the RX-side cold-noise measurement: SA mode, 1 MHz span, 0 dB
attenuation, 10-sweep linear-power average of the noise marker at 2 GHz."""
from __future__ import annotations

import math
import sys

from fieldfox import FieldFox

FF_HOST = "192.168.137.61"
FR1_HZ = 2.0e9


def main() -> int:
    with FieldFox(FF_HOST, span_hz=1e6) as ff:
        print("FieldFox:", ff.identify())
        ff.setup_spectrum_analyzer(ref_level_dbm=-30.0)
        ff.source_enable(False)
        ff.set_attenuation(0.0)
        print(f"SA mode, span {ff.span_hz/1e6:g} MHz, RBW {ff.rbw_hz/1e3:g} kHz, "
              f"attenuation {ff.attenuation_db:.0f} dB")

        print("\n--- FieldFox RF input must be capped directly with a 50-ohm "
              "termination (no cable, no DUT). ---")
        ff.tune(FR1_HZ)
        ff.write("CALC:MARK1:NOIS:STAT ON")
        ff.check("enable noise marker")

        n_reads = 10
        readings = []
        for i in range(n_reads):
            ff.wait_fresh_sweeps()  # continuous sweep (never INIT:CONT OFF / INIT:IMM)
            y = float(ff.query("CALC:MARK1:Y?"))
            readings.append(y)
            print(f"  sweep {i+1:2d}/{n_reads}: {y:8.2f} dBm/Hz")
        ff.check("read noise marker")
        ff.write("CALC:MARK1:NOIS:STAT OFF")
        ff.check("disable noise marker")

        lin = [10 ** (y / 10.0) for y in readings]
        mean_lin = sum(lin) / len(lin)
        mean_dbm_hz = 10.0 * math.log10(mean_lin)
        spread = max(readings) - min(readings)
        print(f"\n{n_reads} sweeps: min {min(readings):.2f}, max {max(readings):.2f} dBm/Hz "
              f"(spread {spread:.2f} dB)")
        print(f"FieldFox's own noise floor at {FR1_HZ/1e9:g} GHz "
              f"(averaged in linear power): {mean_dbm_hz:.2f} dBm/Hz")

        ff.restore_instrument_state()
    return 0


if __name__ == "__main__":
    sys.exit(main())
