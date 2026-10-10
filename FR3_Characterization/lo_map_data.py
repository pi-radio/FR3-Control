"""Load a lo_map.py campaign into arrays, and verify it.

    from lo_map_data import load_campaign
    m = load_campaign(unit_dir(5) / "lo_if_map_20260923")
    m.gain[("THRU", "upper")]      # shape (n_lo, n_if), dB, cable-corrected to the board's connectors
    m.trace[...] / m.rf[...]       # analyzer level (dBm) and RF frequency (Hz), same shape
    m.lo_hz, m.if_hz               # the axes
    m.near_floor[...]              # True where the analyzer level is within 10 dB of that chunk's noise floor

Also runnable:  python lo_map_data.py [campaign folder]   (verifies and writes map.npz beside the data)."""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from results_layout import unit_dirs

KEYS = [("THRU", "upper"), ("THRU", "lower"), ("SWAP", "upper"), ("SWAP", "lower")]


@dataclass
class LoMap:
    folder: Path
    settings: dict
    lo_hz: np.ndarray
    if_hz: np.ndarray
    gain: dict
    trace: dict
    rf: dict
    near_floor: dict
    index: list
    monitor: list

    @property
    def desired(self):
        return {"THRU": ("THRU", "upper"), "SWAP": ("SWAP", "lower")}

    def suppression(self, iq: str) -> np.ndarray:
        """Desired minus undesired gain at the same (LO, IF), dB (nan where either is near the noise floor)."""
        want, other = (("THRU", "upper"), ("THRU", "lower")) if iq == "THRU" else (("SWAP", "lower"), ("SWAP", "upper"))
        s = self.gain[want] - self.gain[other]
        s[self.near_floor[want] | self.near_floor[other]] = np.nan
        return s


def load_campaign(folder: Path) -> LoMap:
    settings = json.loads((folder / "campaign.json").read_text())["settings"]
    index = list(csv.DictReader(open(folder / "lo_index.csv", newline="")))
    floors = {int(r["lo_hz"]): float(r["noise_floor_dbm_chunk"]) for r in index if r["status"].startswith("ok")}
    files = sorted(folder.glob("lo_*GHz.csv"))
    los, per = [], {k: {"if": [], "rf": [], "trace": [], "gain": []} for k in KEYS}
    for f in files:
        lo = int(round(float(f.stem[3:-3]) * 1e9))
        rows = list(csv.DictReader(open(f, newline="")))
        los.append(lo)
        for k in KEYS:
            r = [x for x in rows if (x["iq"], x["tone"]) == k]
            r.sort(key=lambda x: float(x["if_hz"]))
            for name, col in (("if", "if_hz"), ("rf", "rf_hz"), ("trace", "trace_dbm"), ("gain", "gain_db")):
                per[k][name].append([float(x[col]) for x in r])
    lo_hz = np.array(los, dtype=float)
    o = np.argsort(lo_hz)
    lo_hz = lo_hz[o]
    gain = {k: np.array(per[k]["gain"])[o] for k in KEYS}
    trace = {k: np.array(per[k]["trace"])[o] for k in KEYS}
    rf = {k: np.array(per[k]["rf"])[o] for k in KEYS}
    if_hz = np.array(per[KEYS[0]]["if"][0])
    fl = np.array([floors.get(int(lo), np.nan) for lo in lo_hz])
    near = {k: trace[k] < (fl[:, None] + 10.0) for k in KEYS}
    monitor = list(csv.DictReader(open(folder / "monitor.csv", newline=""))) if (folder / "monitor.csv").exists() else []
    return LoMap(folder, settings, lo_hz, if_hz, gain, trace, rf, near, index, monitor)


def newest_campaign() -> Path:
    c = sorted((p for d in unit_dirs() for p in d.iterdir() if p.is_dir() and (p / "campaign.json").exists()
                and "test" not in p.name), key=lambda p: p.stat().st_mtime)
    if not c:
        sys.exit("no campaign found")
    return c[-1]


def main() -> int:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else newest_campaign()
    m = load_campaign(folder)
    n_lo, n_if = m.gain[KEYS[0]].shape
    print(f"Campaign {folder.name}: {n_lo} LOs ({m.lo_hz[0]/1e9:g} to {m.lo_hz[-1]/1e9:g} GHz) x {n_if} IF points "
          f"({m.if_hz[0]/1e9:g} to {m.if_hz[-1]/1e9:g} GHz), 4 sweeps each = {4 * n_lo} sweeps")
    expected = int(round((m.lo_hz[-1] - m.lo_hz[0]) / m.settings["lo_step_hz"])) + 1
    gaps = sorted(set(int(x) for x in np.arange(m.lo_hz[0], m.lo_hz[-1] + 1, m.settings["lo_step_hz"])) - set(int(x) for x in m.lo_hz))
    print(f"  LO coverage: {n_lo} of {expected} expected" + ("" if not gaps else f"; MISSING {[g / 1e9 for g in gaps]}"))
    bad = [r for r in m.index if not r["status"].startswith("ok")]
    print(f"  index rows: {len(m.index)}; not ok: {len(bad)}" + ("" if not bad else f" -> {[(int(r['lo_hz'])/1e9, r['status']) for r in bad][:8]}"))
    tune = np.array([float(r["tune_s"]) for r in m.index if r["status"].startswith("ok")])
    tot = np.array([float(r["total_s"]) for r in m.index if r["status"].startswith("ok")])
    print(f"  per-LO time: tune {tune.mean():.2f} s (max {tune.max():.2f}), total {tot.mean():.2f} s (max {tot.max():.2f})")
    temps = np.array([float(r["lmx_temp_c_before"]) for r in m.index if r["status"].startswith("ok")])
    print(f"  LMX temperature during the run: {temps.min():.1f} to {temps.max():.1f} C")
    if m.monitor:
        g = np.array([float(r["gain_db_at_if_2ghz"]) for r in m.monitor])
        print(f"  drift monitor (LO 12 GHz, THRU upper, IF 2 GHz gain), {len(g)} checks: "
              f"{g.min():.2f} to {g.max():.2f} dB (spread {g.max() - g.min():.2f} dB)  " + " ".join(f"{x:.2f}" for x in g))
    print("  points within 10 dB of the noise floor, per series:")
    for k in KEYS:
        print(f"    {k[0]}_{k[1]:5s}: {int(m.near_floor[k].sum()):5d} of {m.near_floor[k].size} ({100 * m.near_floor[k].mean():.1f} %)   "
              f"gain {np.nanmin(m.gain[k]):+.1f} to {np.nanmax(m.gain[k]):+.1f} dB")
    for iq in ("THRU", "SWAP"):
        s = m.suppression(iq)
        print(f"  {iq}: sideband suppression (desired - undesired), valid points {np.isfinite(s).mean() * 100:.1f} %: "
              f"median {np.nanmedian(s):.1f} dB, 10th pct {np.nanpercentile(s, 10):.1f}, 90th pct {np.nanpercentile(s, 90):.1f}")
    np.savez_compressed(folder / "map.npz", lo_hz=m.lo_hz, if_hz=m.if_hz,
                        **{f"gain_{k[0]}_{k[1]}": m.gain[k] for k in KEYS}, **{f"trace_{k[0]}_{k[1]}": m.trace[k] for k in KEYS},
                        **{f"rf_{k[0]}_{k[1]}": m.rf[k] for k in KEYS})
    print(f"  wrote {folder / 'map.npz'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
