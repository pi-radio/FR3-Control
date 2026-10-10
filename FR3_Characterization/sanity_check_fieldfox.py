"""FieldFox sanity check: Port 1 (CW source) cabled straight to Port 2 (SA
input). Confirms the instrument, the CW source, the SA frequency axis and
the SA level axis all behave before any board measurement is trusted.

    python sanity_check_fieldfox.py [--host 192.168.137.61]

Always uses the small default span (1 MHz), retunes the center frequency per
point, waits 100 ms after each retune, and reads power from marker 1 after a peak search
(see fieldfox.py) - the full trace is never downloaded."""

from __future__ import annotations

import argparse
import sys
import time

from fieldfox import DEFAULT_SPAN_HZ as SPAN_HZ, SETTLE_S, FieldFox

TEST_FREQS_HZ = [1e9, 3e9, 6e9, 10e9, 15e9, 20e9, 26e9]
TONE_POWER_DBM = -30.0
POWER_STEPS_DBM = [-45.0, -40.0, -35.0, -30.0, -25.0, -20.0]
OFFSET_HZ = 300e3                   # must stay well inside the 1 MHz span

MAX_FREQ_ERROR_HZ = 10e3            # ~10 marker bins of 1 kHz; source and analyzer share one clock here
MAX_POWER_STEP_ERROR_DB = 1.0
MIN_ON_OFF_RATIO_DB = 30.0          # source-off marker vs. tone at the same frequency

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.137.61")
    args = parser.parse_args()

    with FieldFox(args.host) as ff:
        print(f"Instrument: {ff.identify()}")
        ff.setup_spectrum_analyzer(ref_level_dbm=-10.0)
        print(f"SA: span {SPAN_HZ/1e6:.0f} MHz, RBW {ff.rbw_hz/1e3:.1f} kHz, "
              f"trace type CLRW, single-sweep triggering, marker-peak readings")
        print(f"Source: CW, {TONE_POWER_DBM:.0f} dBm, Port 1 -> Port 2 cable\n")

        try:
            ff.source_enable(False)
            ff.source_configure(TEST_FREQS_HZ[0], TONE_POWER_DBM)
            ff.check("source configure")

            print("1) Source ON: tone appears at the commanded frequency")
            ff.source_enable(True)
            tone_dbm: dict[float, float] = {}
            for f in TEST_FREQS_HZ:
                ff.source_configure(f, TONE_POWER_DBM)
                time.sleep(SETTLE_S)
                r = ff.measure_at(f)
                tone_dbm[f] = r.power_dbm
                err = r.freq_hz - f
                record(f"tone @ {f/1e9:g} GHz", abs(err) <= MAX_FREQ_ERROR_HZ,
                       f"{r.power_dbm:.2f} dBm (path loss "
                       f"{TONE_POWER_DBM - r.power_dbm:+.2f} dB), "
                       f"freq error {err/1e3:+.1f} kHz")

            print(f"\n2) Frequency axis: analyzer centered {OFFSET_HZ/1e6:g} MHz "
                  f"away, tone must appear {OFFSET_HZ/1e6:g} MHz off-center")
            for f in (TEST_FREQS_HZ[1], TEST_FREQS_HZ[3], TEST_FREQS_HZ[5]):
                ff.source_configure(f, TONE_POWER_DBM)
                time.sleep(SETTLE_S)
                for sign in (+1, -1):
                    r = ff.measure_at(f + sign * OFFSET_HZ)
                    err = r.freq_hz - f
                    record(f"offset {sign*OFFSET_HZ/1e6:+g} MHz @ {f/1e9:g} GHz",
                           abs(err) <= MAX_FREQ_ERROR_HZ,
                           f"marker at {(r.freq_hz - r.center_hz)/1e6:+.3f} MHz "
                           f"from center, freq error {err/1e3:+.1f} kHz")

            print("\n3) Level axis: 5 dB source steps -> 5 dB on the analyzer")
            f = TEST_FREQS_HZ[3]
            levels = []
            for p in POWER_STEPS_DBM:
                ff.source_configure(f, p)
                time.sleep(SETTLE_S)
                levels.append(ff.measure_at(f).power_dbm)
            for i in range(1, len(POWER_STEPS_DBM)):
                step = levels[i] - levels[i - 1]
                want = POWER_STEPS_DBM[i] - POWER_STEPS_DBM[i - 1]
                record(f"step {POWER_STEPS_DBM[i-1]:.0f} -> {POWER_STEPS_DBM[i]:.0f} dBm "
                       f"@ {f/1e9:g} GHz",
                       abs(step - want) <= MAX_POWER_STEP_ERROR_DB,
                       f"analyzer moved {step:+.2f} dB, expected {want:+.1f} dB "
                       f"(reads {levels[i]:.2f} dBm)")

            print(f"\n4) Source OFF: marker at every test frequency must sit at "
                  f"least {MIN_ON_OFF_RATIO_DB:.0f} dB below the tone level")
            ff.source_enable(False)
            time.sleep(SETTLE_S)
            for f in TEST_FREQS_HZ:
                r = ff.measure_at(f)
                ratio = tone_dbm[f] - r.power_dbm
                record(f"off @ {f/1e9:g} GHz", ratio >= MIN_ON_OFF_RATIO_DB,
                       f"marker {r.power_dbm:.1f} dBm, {ratio:.1f} dB below the "
                       f"{tone_dbm[f]:.1f} dBm tone")

            ff.check("end of run")
        finally:
            ff.source_enable(False)
            ff.restore_instrument_state()
            print(f"\nSource output left OFF: {not ff.source_state()}; "
                  f"trace type and continuous sweep restored.")

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    for name in failed:
        print(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
