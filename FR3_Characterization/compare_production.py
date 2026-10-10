"""Compare a unit's production-test data with the golden unit (#5) at the same points (no pass/fail yet, user 2026-10-09).

    python compare_production.py [--unit 6] [--folder production_20261009] [--chain tx|rx]

TX: T1 LO leakage after the unit's own null (every usable filter setting at each test LO) vs golden COLD and HOT calibration
scans at the same LO (the production test runs in the cold window); T2 2xLO vs the golden Section 10.1 run; T3 gain, T4 RMS
flatness, T5 sideband suppression vs the golden datasheet campaigns, point by point and filter by filter; T6 compression vs the
golden panels. Golden TX data is hot (LMX ~80-85 C), so temperature differences are part of every delta -- listed per test.
RX: R1 gain, R2 flatness, R4 image rejection (point by point), R3 compression panels, R5/R6 noise figure (optimal filter),
R7 LO / 2xLO leaking out of "RX-side FR3 RF In" -- each against the golden hot RX re-run of 2026-10-09.
Writes <folder>/comparison_<chain>.md and prints it.
"""
from __future__ import annotations

import argparse
import csv
import glob
import statistics as st
from pathlib import Path

from results_layout import unit_dir

G = unit_dir(5)
G_COLD = r"2026-10-09\lo_cal_grid_100MHz_*_full_cal_cold_drive_rule"
G_HOT = r"2026-10-09\lo_cal_grid_100MHz_*_full_cal_hot_drive_rule"
G_2LO = r"2026-10-09\lo_cal_grid_100MHz_20261009_044140_sec10_1_2lo_hot"
G_RXLEAK = r"2026-10-09\rx_port_leakage_20261009_163240_rx_hot_drive_rule.csv"


def rows(path) -> list[dict]:
    return list(csv.DictReader(open(path, newline="")))


def states(pattern: str) -> list[dict]:
    return [r for f in sorted(glob.glob(str(pattern) + "_states.csv")) for r in rows(f)]


def table(pattern: str) -> dict[float, dict]:
    return {round(float(r["lo_ghz"]), 1): r for f in sorted(glob.glob(str(pattern) + "_table.csv")) for r in rows(f)}


def f(v, d=1) -> str:
    return "" if v is None else f"{v:+.{d}f}".replace("+", "") if v >= 0 else f"{v:.{d}f}".replace("-", "−")


def by_lo(st_rows, col) -> dict[float, list[float]]:
    out: dict[float, list[float]] = {}
    for r in st_rows:
        if r.get(col) not in ("", None):
            out.setdefault(round(float(r["lo_ghz"]), 1), []).append(float(r[col]))
    return out


def _key(k: str) -> str:
    return k.split("|", 1)[-1] if k.startswith(("tx|", "rx|")) else k


def _pointwise(unit, title, sub, gold, col, unit_txt, side_word) -> list[str]:
    u = {_key(r["key"]): r for r in rows(unit / sub / "points.csv")}
    gd = {_key(r["key"]): r for r in rows(G / gold / "points.csv")}
    out = [f"## {title}", "", f"| {side_word} | FR1 / FR3 (GHz) | LO (GHz) | Filter | Unit {unit_txt} | Golden | Unit - golden | Unit temp (C) |",
           "|---|---|---|---|---|---|---|---|"]
    deltas = {"bypass": [], "optimal": []}
    for k in sorted(u, key=lambda k: (u[k]["config"], float(u[k]["lo_hz"]), float(u[k]["fr1_hz"]), u[k]["filter"])):
        r, g = u[k], gd.get(k)
        if g is None:
            continue
        a, b = float(r[col]), float(g[col])
        deltas[r["filter"]].append(a - b)
        out.append(f"| {r['config']} | {float(r['fr1_hz']) / 1e9:g} / {float(r['fr3_hz']) / 1e9:g} | {float(r['lo_hz']) / 1e9:g} | "
                   f"{r['filter']} {r['filter_bits']} | {f(a)} | {f(b)} | {f(a - b)} | {r['lmx_temp_c']} |")
    out += ["", "Unit - golden, median (min to max): " + "; ".join(
        f"{k} {f(st.median(v))} dB ({f(min(v))} to {f(max(v))})" for k, v in deltas.items() if v), ""]
    return out


def _exists(path: Path) -> bool:
    return path.exists()


def rx(unit: Path) -> list[str]:
    md = []
    pw = lambda title, sub, gold, col, txt: _pointwise(unit, title, sub, gold, col, txt, "LO side") \
        if _exists(unit / sub / "points.csv") else [f"## {title}", "", "(not measured yet)", ""]
    md += pw("R1: conversion gain (500 MHz window average, dB)", "gain_rx", "gain_rx_20261009", "mean_gain_db", "gain")
    md += pw("R2: RMS gain flatness (dB)", "flatness_rx", "flatness_rx_20261009", "rms_flatness_db", "flatness")
    # ---- R3: compression panels
    md += ["## R3: compression", ""]
    if _exists(unit / "compression_rx" / "summary.csv"):
        u = {(r["side"], r["fr1_ghz"], r["fr3_ghz"]): r for r in rows(unit / "compression_rx" / "summary.csv")}
        gd = {(r["side"], r["fr1_ghz"], r["fr3_ghz"]): r for r in rows(G / "compression_rx_20261009" / "summary.csv")}
        md += ["| Panel | Unit gain / in P1dB / out P1dB / out P3dB | Golden gain / in P1dB / out P1dB / out P3dB | "
               "Delta gain / out P1dB / out P3dB | Unit / golden temp (C) |", "|---|---|---|---|---|"]
        num = lambda x: float(x) if x not in ("", None) else None
        cols = ("small_signal_gain_db", "p1db_in_dbm", "p1db_out_dbm", "p3db_out_dbm")
        for k, r in u.items():
            g = gd.get(k)
            if g is None:
                continue
            a, b = [num(r[c]) for c in cols], [num(g[c]) for c in cols]
            dl = [None if x is None or y is None else x - y for x, y in ((a[0], b[0]), (a[2], b[2]), (a[3], b[3]))]
            md.append(f"| {k[0]}-side {k[1]} / {k[2]} GHz | {' / '.join(f(x) for x in a)} | {' / '.join(f(x) for x in b)} | "
                      f"{' / '.join(f(x) for x in dl)} | {r['lmx_temp_c']} / {g['lmx_temp_c']} |")
        md.append("")
    else:
        md += ["(not measured yet)", ""]
    md += pw("R4: image rejection (dB)", "image_rx", "image_rx_20261009", "rejection_db", "rejection")
    # ---- R5/R6: noise figure
    md += ["## R5/R6: noise figure, optimal filter (dB)", ""]
    nf_u = unit / "rx_nf" / "nf_results.csv"
    if nf_u.exists():
        k = lambda r: (r["sideband"], round(float(r["fr1_hz"]) / 1e9, 2), round(float(r["fr3_hz"]) / 1e9, 2))
        gd = {k(r): r for r in rows(G / "rx_nf_optimal_20261009" / "nf_results.csv")}
        md += ["| LO side | FR1 / FR3 (GHz) | Unit NF | Golden NF | Unit - golden | Unit gain / golden gain (dB) | Margin above FieldFox floor (dB) |",
               "|---|---|---|---|---|---|---|"]
        dl = []
        for r in sorted(rows(nf_u), key=lambda r: (r["sideband"], float(r["fr1_hz"]), float(r["fr3_hz"]))):
            g = gd.get(k(r))
            if g is None:
                continue
            a, b = float(r["nf_db"]), float(g["nf_db"])
            dl.append(a - b)
            md.append(f"| {r['sideband']} | {k(r)[1]:g} / {k(r)[2]:g} | {f(a)} | {f(b)} | {f(a - b)} | "
                      f"{f(float(r['gain_db']))} / {f(float(g['gain_db']))} | {r['margin_above_ff_floor_db']} |")
        if dl:
            md += ["", f"Unit - golden, median (min to max): {f(st.median(dl))} dB ({f(min(dl))} to {f(max(dl))})"]
        md.append("")
    else:
        md += ["(not measured yet: needs R5 in set-up A and R6 in set-up B)", ""]
    # ---- R7: RX-side leakage
    md += ['## R7: LO / 2xLO leaking out of "RX-side FR3 RF In" (dBm)', ""]
    fl = sorted(glob.glob(str(unit / "rx_port_leakage_*_prod_rx_leak.csv")))
    if fl:
        gd = {round(float(r["lo_ghz"]), 1): r for r in rows(G / G_RXLEAK)}
        md += ["| LO (GHz) | Unit LO / golden LO | Unit 2xLO / golden 2xLO | Unit: change with TX bias 5 mV off (LO / 2xLO) | Unit temp (C) |",
               "|---|---|---|---|---|"]
        num = lambda x: float(x) if x not in ("", None) else None
        for r in rows(fl[-1]):
            lo = round(float(r["lo_ghz"]), 1)
            g = gd.get(lo, {})
            ch = [None if num(r.get(f"{c}_dbm_tx_offset")) is None else num(r[f"{c}_dbm_tx_offset"]) - num(r[f"{c}_dbm"])
                  for c in ("lo", "two_lo")]
            md.append(f"| {lo:g} | {f(num(r['lo_dbm']))} / {f(num(g.get('lo_dbm')))} | {f(num(r['two_lo_dbm']))} / "
                      f"{f(num(g.get('two_lo_dbm')))} | {f(ch[0])} / {f(ch[1])} | {r['lmx_temp_c']} |")
        md.append("")
    else:
        md += ["(not measured yet: needs set-up C)", ""]
    return md


def tx(unit: Path) -> list[str]:
    md = []
    # ---- T1 / T2: LO and 2xLO after the unit's own null
    u_st = states(unit / "lo_cal_grid_*")
    u_tab = table(unit / "lo_cal_grid_*")
    gc, gh, g2 = by_lo(states(G / G_COLD), "lo_dbm_ref_bias"), by_lo(states(G / G_HOT), "lo_dbm_ref_bias"), \
        by_lo(states(G / G_2LO), "two_lo_dbm")
    gct, ght = table(G / G_COLD), table(G / G_HOT)
    u_lo, u_2lo = by_lo(u_st, "lo_dbm_ref_bias"), by_lo(u_st, "two_lo_dbm")
    md += ["## T1: LO leakage after the unit's own null (every usable filter setting)", "",
           "| LO (GHz) | Unit temp (C) | Unit median / worst (dBm) | Unit: readings <= -20 dBm | Golden cold median / worst | "
           "Golden hot median / worst | Unit null I, Q (mV) | Golden cold null I, Q (mV) |", "|---|---|---|---|---|---|---|---|"]
    for lo in sorted(u_lo):
        v = u_lo[lo]
        t = u_tab.get(lo, {})
        c, h = gc.get(lo, []), gh.get(lo, [])
        md.append(f"| {lo:g} | {t.get('lmx_temp_c', '')} | {f(st.median(v))} / {f(max(v))} | {sum(x <= -20 for x in v)} of {len(v)} | "
                  f"{f(st.median(c)) if c else ''} / {f(max(c)) if c else ''} | {f(st.median(h)) if h else ''} / {f(max(h)) if h else ''} | "
                  f"{1e3 * float(t['ref_i_v']):.1f}, {1e3 * float(t['ref_q_v']):.1f} | "
                  + (f"{1e3 * float(gct[lo]['ref_i_v']):.1f}, {1e3 * float(gct[lo]['ref_q_v']):.1f}" if lo in gct else "") + " |")
    md += ["", "## T2: 2xLO after the unit's own null (every usable filter setting)", "",
           "| LO (GHz) | Unit median / worst (dBm) | Golden (hot, 10.1) median / worst (dBm) |", "|---|---|---|"]
    for lo in sorted(u_2lo):
        v, g = u_2lo[lo], g2.get(lo, [])
        md.append(f"| {lo:g} | {f(st.median(v))} / {f(max(v))} | {f(st.median(g)) if g else ''} / {f(max(g)) if g else ''} |")

    # ---- T3-T5: point by point
    pointwise = lambda title, sub, gold, col, unit_txt: _pointwise(unit, title, sub, gold, col, unit_txt, "Sideband")
    md += [""] + pointwise("T3: conversion gain (500 MHz window average, dB)", "gain_tx", "gain_tx_20261009", "mean_gain_db", "gain")
    md += pointwise("T4: RMS gain flatness (dB)", "flatness_tx", "flatness_tx_20261009", "rms_flatness_db", "flatness")
    md += pointwise("T5: sideband suppression (dB)", "sideband_tx", "sideband_tx_20261009", "suppression_db", "suppression")

    # ---- T6: compression panels
    u = {(r["sideband"], r["fr1_ghz"], r["fr3_ghz"]): r for r in rows(unit / "compression_tx" / "summary.csv")}
    gd = {(r["sideband"], r["fr1_ghz"], r["fr3_ghz"]): r for r in rows(G / "compression_tx_20261009" / "summary.csv")}
    md += ["## T6: compression", "", "| Panel | Unit gain / out P1dB / out P3dB | Golden gain / out P1dB / out P3dB | Delta gain / P1dB / P3dB | "
           "Unit / golden temp (C) |", "|---|---|---|---|---|"]
    num = lambda x: float(x) if x not in ("", None) else None
    for k, r in u.items():
        g = gd.get(k)
        if g is None:
            continue
        a = [num(r[c]) for c in ("small_signal_gain_db", "p1db_out_dbm", "p3db_out_dbm")]
        b = [num(g[c]) for c in ("small_signal_gain_db", "p1db_out_dbm", "p3db_out_dbm")]
        dl = [None if x is None or y is None else x - y for x, y in zip(a, b)]
        md.append(f"| {k[0]} {k[1]} / {k[2]} GHz | {' / '.join(f(x) for x in a)} | {' / '.join(f(x) for x in b)} | "
                  f"{' / '.join(f(x) for x in dl)} | {r['lmx_temp_c']} / {g['lmx_temp_c']} |")
    return md


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", type=int, default=6)
    ap.add_argument("--folder", default="production_20261009")
    ap.add_argument("--chain", choices=("tx", "rx"), default="tx")
    args = ap.parse_args()
    unit = unit_dir(args.unit) / args.folder
    if args.chain == "tx":
        md = [f"# Unit #{args.unit} vs golden #5, TX production test ({args.folder})", "",
              "Golden: Unit #5 datasheet data (TX tests hot, LMX ~80-85 C; T1 also against its cold calibration, 57-63 C).", ""] + tx(unit)
    else:
        md = [f"# Unit #{args.unit} vs golden #5, RX production test ({args.folder})", "",
              "Golden: Unit #5 hot RX re-run of 2026-10-09 (LMX ~69-84 C). TX side in normal use with each unit's own nulls.", ""] + rx(unit)
    (unit / f"comparison_{args.chain}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
