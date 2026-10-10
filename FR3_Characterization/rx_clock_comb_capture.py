"""One reading of the RX FR1 IF Out clock-harmonic comb on the UXA.

Reads the board serial (read-only: no board setting is changed), restarts the
UXA's averaging, waits for the full average count, saves the trace to
results/unit_###/rx_clock_comb/, and appends a summary row to
results/rx_clock_comb_summary.csv so units and lid placements compare directly.
UXA span/RBW/points/average count are used exactly as set on the instrument.

Usage:  python rx_clock_comb_capture.py LABEL ["free-text note"]
e.g.    python rx_clock_comb_capture.py in_case_1 "screws torqued in order 1-6"
"""
from __future__ import annotations

import csv
import socket
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from board import OPERATING_TIMEOUT_S, Board, find_board_ports
from results_layout import RESULTS_DIR, unit_dir

UXA = ("192.168.137.71", 5025)
COMB_STEP_HZ = 10e6
CLUSTERS_GHZ = (0.69, 1.30, 1.54, 1.92, 2.32, 2.50, 2.60, 2.69, 2.88, 3.40)
CLUSTER_HALF_WIDTH_HZ = 60e6
FR1_POINTS_GHZ = (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
SUMMARY_CSV = RESULTS_DIR / "rx_clock_comb_summary.csv"


class Uxa:
    def __init__(self):
        self.s = socket.create_connection(UXA, timeout=30.0)

    def write(self, cmd):
        self.s.sendall((cmd + "\n").encode("ascii"))

    def query(self, cmd, timeout=60.0):
        self.write(cmd)
        self.s.settimeout(timeout)
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = self.s.recv(1 << 20)
            if not chunk:
                break
            buf += chunk
        return buf.decode("ascii", "replace").strip()

    def check(self, what):
        err = self.query(":SYST:ERR?")
        if not err.startswith(("+0", "0")):
            raise RuntimeError(f"UXA error after {what}: {err}")


def board_serial() -> int:
    ports = find_board_ports()
    if len(ports) != 1:
        raise RuntimeError(f"expected exactly one board, found {ports or 'none'}")
    b = Board(ports[0], timeout=OPERATING_TIMEOUT_S)
    try:
        return b.get_board_serial()
    finally:
        b.close()


def capture(uxa):
    start = float(uxa.query(":SENS:FREQ:STAR?"))
    stop = float(uxa.query(":SENS:FREQ:STOP?"))
    npts = int(float(uxa.query(":SENS:SWE:POIN?")))
    rbw = float(uxa.query(":SENS:BAND:RES?"))
    navg = int(float(uxa.query(":SENS:AVER:COUN?")))
    sweep_s = float(uxa.query(":SENS:SWE:TIME?"))
    wait_s = navg * sweep_s * 1.3 + 3.0
    uxa.write(":FORM:TRAC:DATA ASC")
    uxa.write(":INIT:REST")
    uxa.check("INIT:REST")
    print(f"UXA {start/1e9:.3f}-{stop/1e9:.3f} GHz, {npts} pts, RBW {rbw/1e3:g} kHz, "
          f"{navg} averages x {sweep_s:.2f} s sweep -> waiting {wait_s:.0f} s ...")
    time.sleep(wait_s)
    trace = [float(v) for v in uxa.query(":TRAC:DATA? TRACE1").split(",")]
    uxa.check("TRAC:DATA?")
    freqs = [start + i * (stop - start) / (npts - 1) for i in range(npts)]
    return freqs, trace, {"rbw_hz": rbw, "averages": navg}


def comb_lines(freqs, trace):
    """(freq, level dBm, height above local median floor dB) at each 10 MHz multiple."""
    df = freqs[1] - freqs[0]
    out = []
    k = int(freqs[0] // COMB_STEP_HZ) + 1
    while k * COMB_STEP_HZ <= freqs[-1]:
        f = k * COMB_STEP_HZ
        i = round((f - freqs[0]) / df)
        level = max(trace[max(0, i - 3):i + 4])
        floor = statistics.median(trace[max(0, i - 60):i + 61])
        out.append((f, level, level - floor))
        k += 1
    return out


def summarize(lines):
    row = {
        "lines_gt6db": sum(1 for _, _, a in lines if a > 6),
        "lines_gt15db": sum(1 for _, _, a in lines if a > 15),
    }
    f, lvl, a = max(lines, key=lambda r: r[1])
    row.update(strongest_ghz=round(f / 1e9, 3), strongest_dbm=round(lvl, 1),
               strongest_above_floor_db=round(a, 1))
    for c in CLUSTERS_GHZ:
        near = [r for r in lines if abs(r[0] - c * 1e9) <= CLUSTER_HALF_WIDTH_HZ]
        row[f"cluster_{c:.2f}GHz_db"] = round(max(a for _, _, a in near), 1) if near else ""
    by_f = {round(f): (lvl, a) for f, lvl, a in lines}
    for p in FR1_POINTS_GHZ:
        lvl, a = by_f.get(round(p * 1e9), ("", ""))
        row[f"fr1_{p:.1f}GHz_db"] = round(a, 1) if a != "" else ""
    return row


def main() -> int:
    label = sys.argv[1]
    note = sys.argv[2] if len(sys.argv) > 2 else ""
    serial = board_serial()
    print(f"Board serial: unit #{serial}")
    uxa = Uxa()
    freqs, trace, meta = capture(uxa)

    outdir = unit_dir(serial) / "rx_clock_comb"
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tpath = outdir / f"trace_{stamp}_{label}.csv"
    with open(tpath, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["freq_hz", "dbm"])
        w.writerows([f"{fq:.0f}", f"{p:.2f}"] for fq, p in zip(freqs, trace))

    row = {"timestamp": stamp, "unit": serial, "label": label, "note": note,
           "start_ghz": round(freqs[0] / 1e9, 3), "stop_ghz": round(freqs[-1] / 1e9, 3),
           "points": len(freqs), "rbw_khz": meta["rbw_hz"] / 1e3, "averages": meta["averages"],
           "median_floor_dbm": round(statistics.median(trace), 1),
           **summarize(comb_lines(freqs, trace)), "trace_file": str(tpath.relative_to(RESULTS_DIR))}
    new = not SUMMARY_CSV.exists()
    with open(SUMMARY_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)

    print(f"Saved {tpath}")
    print_table()
    return 0


def print_table():
    rows = list(csv.DictReader(open(SUMMARY_CSV)))
    cl = [f"cluster_{c:.2f}GHz_db" for c in CLUSTERS_GHZ]
    print(f"\n{'unit':>4} {'label':<26} {'>6dB':>5} {'>15dB':>5} {'strongest':>17} | "
          + " ".join(f"{c:>5.2f}" for c in CLUSTERS_GHZ) + "  (cluster peaks, dB above floor)")
    for r in rows:
        print(f"{r['unit']:>4} {r['label'][:26]:<26} {r['lines_gt6db']:>5} {r['lines_gt15db']:>5} "
              f"{r['strongest_dbm']:>6} @ {r['strongest_ghz']:>5} GHz | "
              + " ".join(f"{r[c]:>5}" for c in cl))


if __name__ == "__main__":
    sys.exit(main())
