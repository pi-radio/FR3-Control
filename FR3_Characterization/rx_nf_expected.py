"""Expected RX noise figure from component datasheets, for the same 42
(FR1, FR3, sideband) points as rx_nf_campaign.py, compared against the
measured NF in results/unit_005/rx_nf_campaign/nf_results.csv.

Chain: SMA (1 dB) -> HMC963 LNA -> AM3153 (bypass) -> MAMX-011075 (I output
only, Q terminated) -> LFCG-4400+ LPF -> ADL5545 -> ADL5545.

Noise is tracked as available noise density in units of kT0 with the input
at T0 (the cold-termination condition of Phase 2), so predicted
NF = N_out / G_signal, the same quantity the measurement computes. With the
filter bypassed and only the mixer's I output kept, the LNA's output noise at
the image frequency folds into the IF alongside the wanted band (DSB noise).

All curves are +25 C typical values read off the datasheet plots; component
temperatures, board losses between parts and LO drive are not modeled
(nominal +14 dBm LO assumed)."""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import numpy as np

# HMC963LC4: gain (+25 C, "Gain vs Temperature" / broadband S21 outside 6-26.5 GHz)
LNA_GAIN = [(2, -30), (3, -20), (4, -10), (4.5, 0), (5, 12), (5.5, 19), (6, 21.0), (6.5, 22.0),
            (7, 22.2), (8, 21.8), (10, 21.9), (12, 21.8), (14, 21.8), (15, 21.6), (16, 21.5),
            (18, 21.9), (20, 22.5), (21, 22.0), (22, 21.3), (23, 21.5), (24, 21.0), (25, 20.6),
            (26, 20.0), (27, 17.5), (28, 12), (30, 6)]
# HMC963LC4 NF (+25 C); not specified below 6 GHz -> 3.5 dB assumed (only matters near 5-6 GHz)
LNA_NF = [(2, 3.5), (5.9, 3.5), (6, 3.1), (6.5, 2.5), (7, 2.55), (8, 2.75), (9, 2.55), (10, 2.35),
          (11, 2.25), (12, 2.2), (13, 2.35), (14, 2.35), (15, 2.3), (16, 2.2), (17, 2.15), (18, 2.1),
          (19, 2.2), (20, 2.45), (21, 2.4), (22, 2.3), (23, 2.6), (24, 2.7), (25, 2.7), (26, 2.6),
          (27, 2.55), (28, 3.0), (30, 3.0)]
# AM3153 bypass-path insertion loss
FILT_BYP_IL = [(0, 0.2), (5, 0.4), (10, 0.7), (15, 1.0), (18, 1.2), (20, 1.5), (22, 2.0),
               (24, 3.0), (26, 5.0), (30, 5.0)]
# MAMX-011075 down-conversion gain vs RF, 2 GHz IF, LO +14 dBm, I+Q combined in a 90deg hybrid.
# USB = RF above LO (low-side LO); LSB = RF below LO (high-side LO). Spec'd 8-26 GHz only.
MIX_USB = [(2, -35), (4, -25), (5, -14), (5.5, -10), (6, -8.5), (7, -7.2), (8, -7.3), (9, -7.8),
           (10, -8.2), (12, -8.8), (14, -9.5), (15, -10.0), (16, -10.0), (18, -9.7), (20, -9.0),
           (22, -8.3), (23, -8.2), (24, -8.8), (25, -9.8), (26, -10.8), (28, -13.5), (30, -16.5)]
MIX_LSB = [(1, -35), (2, -25), (3, -20), (4, -13.5), (5, -9.5), (6, -8.0), (7, -7.6), (8, -8.2),
           (10, -8.5), (12, -9.0), (14, -9.3), (16, -9.8), (18, -9.6), (20, -9.2), (22, -8.6),
           (23, -8.6), (24, -9.0), (26, -10.5), (28, -12.3), (30, -14)]
# "IF Bandwidth" curve, re-referenced to 2 GHz IF (the IF the curves above were taken at)
MIX_IF_CORR = [(0.5, 0.6), (1.0, 0.2), (1.5, 0.1), (2.0, 0.0), (2.5, -0.6), (3.0, -1.3),
               (3.5, -1.0), (4.0, 0.3)]
I_ONLY_PENALTY_DB = 3.0
# LFCG-4400+ insertion loss (MHz table -> GHz)
LPF_IL = [(0.01, 0.07), (0.1, 0.11), (1.0, 0.23), (2.0, 0.41), (3.0, 0.60), (4.0, 0.90),
          (4.4, 1.31)]
# ADL5545 typical gain / NF
IFA_GAIN = [(0.7, 24.4), (0.9, 24.1), (1.9, 22.2), (2.14, 21.8), (2.6, 20.9), (3.5, 19.7),
            (4.0, 18.6)]
IFA_NF = [(0.7, 3.0), (0.9, 2.9), (1.9, 3.4), (2.14, 3.5), (2.6, 3.6), (3.5, 4.0), (4.0, 4.6)]
SMA_IL_DB = 1.0


def interp(table, f_ghz):
    xs, ys = zip(*table)
    return float(np.interp(f_ghz, xs, ys))


def lin(db):
    return 10 ** (db / 10)


def mixer_gain_db(rf_ghz, rf_above_lo, if_ghz):
    curve = MIX_USB if rf_above_lo else MIX_LSB
    return interp(curve, rf_ghz) + interp(MIX_IF_CORR, if_ghz) - I_ONLY_PENALTY_DB


def lna_out_noise(f_ghz):
    """Noise density (kT0 units) at the AM3153 output, input termination at T0."""
    n = lin(interp(LNA_GAIN, f_ghz)) * lin(interp(LNA_NF, f_ghz))
    l_f = lin(interp(FILT_BYP_IL, f_ghz))
    return n / l_f + (1 - 1 / l_f)


def predict(fr1_hz, fr3_hz, lo_hz):
    fr1, fr3, lo = fr1_hz / 1e9, fr3_hz / 1e9, lo_hz / 1e9
    signal_above_lo = fr3 > lo
    f_img = 2 * lo - fr3

    gm_sig = lin(mixer_gain_db(fr3, signal_above_lo, fr1))
    gm_img = lin(mixer_gain_db(f_img, not signal_above_lo, fr1))
    # passive mixer at T0: with every port at kT0 its IF output must be kT0
    n_mix = gm_sig * lna_out_noise(fr3) + gm_img * lna_out_noise(f_img) + (1 - gm_sig - gm_img)

    l_lpf = lin(interp(LPF_IL, fr1))
    n_lpf = n_mix / l_lpf + (1 - 1 / l_lpf)
    g_ifa, f_ifa = lin(interp(IFA_GAIN, fr1)), lin(interp(IFA_NF, fr1))
    n_out = g_ifa * (g_ifa * (n_lpf + f_ifa - 1) + f_ifa - 1)

    g_sig = (1 / lin(SMA_IL_DB)) * lin(interp(LNA_GAIN, fr3)) / lin(interp(FILT_BYP_IL, fr3)) \
        * gm_sig / l_lpf * g_ifa ** 2
    nf_db = 10 * math.log10(n_out / g_sig)
    # same chain with the image contribution removed (SSB), for reference
    n_mix_ssb = gm_sig * lna_out_noise(fr3) + (1 - gm_sig)
    n_out_ssb = g_ifa * (g_ifa * (n_mix_ssb / l_lpf + (1 - 1 / l_lpf) + f_ifa - 1) + f_ifa - 1)
    return {
        "f_image_ghz": round(f_img, 2),
        "pred_gain_db": round(10 * math.log10(g_sig), 2),
        "pred_nf_dsb_db": round(nf_db, 2),
        "pred_nf_ssb_db": round(10 * math.log10(n_out_ssb / g_sig), 2),
    }


def main() -> int:
    src = Path("results/unit_005/rx_nf_campaign/nf_results.csv")
    rows = list(csv.DictReader(open(src)))
    out = []
    for r in rows:
        p = predict(float(r["fr1_hz"]), float(r["fr3_hz"]), float(r["lo_hz"]))
        out.append({
            "fr1_ghz": float(r["fr1_hz"]) / 1e9, "fr3_ghz": float(r["fr3_hz"]) / 1e9,
            "sideband": r["sideband"], "lo_ghz": float(r["lo_hz"]) / 1e9, **p,
            "meas_gain_db": round(float(r["gain_db"]), 2), "meas_nf_db": float(r["nf_db"]),
        })
    dst = src.with_name("nf_expected_vs_measured.csv")
    with open(dst, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"{'FR1':>4} {'FR3':>6} {'SB':4} {'LO':>6} {'img':>6} | {'Gpred':>6} {'Gmeas':>6} "
          f"{'dG':>6} | {'NFdsb':>6} {'NFssb':>6} {'NFmeas':>6} {'dNF':>6}")
    for o in out:
        print(f"{o['fr1_ghz']:4.1f} {o['fr3_ghz']:6.2f} {o['sideband']:4} {o['lo_ghz']:6.2f} "
              f"{o['f_image_ghz']:6.2f} | {o['pred_gain_db']:6.2f} {o['meas_gain_db']:6.2f} "
              f"{o['meas_gain_db'] - o['pred_gain_db']:+6.2f} | {o['pred_nf_dsb_db']:6.2f} "
              f"{o['pred_nf_ssb_db']:6.2f} {o['meas_nf_db']:6.2f} "
              f"{o['meas_nf_db'] - o['pred_nf_dsb_db']:+6.2f}")
    print(f"\nSaved {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
