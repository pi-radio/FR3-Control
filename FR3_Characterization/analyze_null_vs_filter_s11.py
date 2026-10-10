"""Does the TX LO-null bias follow the AM3153 filter's input reflection at the LO? (analysis only, 2026-10-07)

    python analyze_null_vs_filter_s11.py <tx_null_filter_state_*_nulls.csv>

Hypothesis: the filter state changes the reflection seen by the mixer's RF port, which shifts the mixer's LO leakage
and so the null bias. If the shift is caused by the reflection, the null bias (I_V, Q_V) should be an affine function
of the complex reflection coefficient Gamma at the LO: [I, Q] = A [Re G, Im G] + c (A a real 2x2 matrix absorbing the
unknown line delay / mixer gain, c the bias for no reflection). Fitted per LO by least squares on the states with a
good null; the fit quality is compared with the same fit using S22 (the filter's other port) and |S21| (a control that
carries no phase). Touchstone files: FR3_GUI/data/am3153_sparams (# Hz S dB R 50; S11 S21 S12 S22 as dB/angle pairs).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

SP = Path(__file__).resolve().parent.parent / "FR3_GUI" / "data" / "am3153_sparams"
BAND_BY_NIBBLE = {0x3: 1, 0x1: 2, 0x2: 3}
GOOD_NULL_DBM = -45.0                       # a state counts only if its own null reached this


def sparams(bits: int):
    f = SP / f"AM3153_SN2_5V_6mA_Band{BAND_BY_NIBBLE[bits >> 4]}_{bits & 0xF:04b}.s2p"
    rows = [list(map(float, ln.split())) for ln in open(f, encoding="ascii")
            if ln.strip() and not ln.lstrip().startswith(("!", "#"))]
    a = np.array(rows)
    def cplx(db_col, ang_col):
        return 10 ** (a[:, db_col] / 20) * np.exp(1j * np.radians(a[:, ang_col]))
    return a[:, 0], {"S11": cplx(1, 2), "S21": cplx(3, 4), "S22": cplx(7, 8)}


def at(freq, s, f0):
    return np.interp(f0, freq, s.real) + 1j * np.interp(f0, freq, s.imag)


def fit(x: np.ndarray, iq: np.ndarray):
    """Affine least squares iq ~ x @ A.T + c. Returns (rms residual mV, R^2 of the bias spread explained)."""
    X = np.column_stack([x, np.ones(len(x))])
    coef, *_ = np.linalg.lstsq(X, iq, rcond=None)
    res = iq - X @ coef
    rms = 1000 * np.sqrt(np.mean(np.sum(res ** 2, axis=1)))
    tot = np.sum((iq - iq.mean(axis=0)) ** 2)
    return rms, 1 - np.sum(res ** 2) / tot


def main() -> None:
    rows = list(csv.DictReader(open(sys.argv[1], newline="")))
    for lo in sorted({float(r["lo_ghz"]) for r in rows}):
        sel = [r for r in rows if float(r["lo_ghz"]) == lo]
        good = [r for r in sel if float(r["lo_dbm"]) <= GOOD_NULL_DBM and abs(float(r["i_v"])) < 0.49 and abs(float(r["q_v"])) < 0.49]
        iq = np.array([[float(r["i_v"]), float(r["q_v"])] for r in good])
        g = {k: [] for k in ("S11", "S21", "S22")}
        print(f"\nLO {lo:g} GHz: {len(good)} of {len(sel)} states with a good null (<= {GOOD_NULL_DBM:g} dBm, inside +-0.49 V)")
        print(f"  {'state':6s} {'I_V':>8s} {'Q_V':>8s} | {'|S11| dB':>8s} {'ang':>6s} | {'|S22| dB':>8s} | {'|S21| dB':>8s}")
        for r in good:
            b = int(r["tx_filter"], 16)
            f, s = sparams(b)
            for k in g:
                g[k].append(at(f, s[k], lo * 1e9))
            s11, s22, s21 = g["S11"][-1], g["S22"][-1], g["S21"][-1]
            print(f"  {r['tx_filter']:6s} {float(r['i_v']):+8.4f} {float(r['q_v']):+8.4f} | {20*np.log10(abs(s11)):8.2f} "
                  f"{np.degrees(np.angle(s11)):6.0f} | {20*np.log10(abs(s22)):8.2f} | {20*np.log10(abs(s21)):8.1f}")
        spread = 1000 * np.sqrt(np.mean(np.sum((iq - iq.mean(axis=0)) ** 2, axis=1)))
        print(f"  null-bias spread (rms about the mean): {spread:.1f} mV")
        if len(good) < 5:
            print("  too few states for a 6-parameter fit")
            continue
        for name, x in (("S11 (complex)", np.column_stack([np.real(g["S11"]), np.imag(g["S11"])])),
                        ("S22 (complex)", np.column_stack([np.real(g["S22"]), np.imag(g["S22"])])),
                        ("|S21| only", np.column_stack([np.abs(g["S21"]), np.abs(g["S21"]) ** 2]))):
            rms, r2 = fit(x, iq)
            print(f"  affine fit on {name:14s}: residual {rms:6.1f} mV rms, explains {100 * r2:5.1f}% of the spread")


if __name__ == "__main__":
    main()
