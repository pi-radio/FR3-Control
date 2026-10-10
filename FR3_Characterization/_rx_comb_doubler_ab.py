"""A/B: RX FR1 IF Out spur comb on the UXA with the LMX2820 at 10 GHz,
(A) via LMX TUNE (firmware template, OSC_2X doubler on, fPD 20 MHz) and
(B) via the TICS Pro no-doubler register file (fPD 10 MHz).
UXA settings are left exactly as the user set them; only averaging is restarted."""
import csv
import re
import socket
import sys
import time
from pathlib import Path

from board import OPERATING_TIMEOUT_S, Board, find_board_ports

UXA = ("192.168.137.71", 5025)
REG_FILE = Path(r"C:\Users\Aditya Dhananjay\Downloads\HexRegisterValues_10GHz_No_Doubler.txt")
OUTDIR = Path("results/unit_005/rx_clock_comb")
AVG_WAIT_S = 15.0


class Uxa:
    def __init__(self):
        self.s = socket.create_connection(UXA, timeout=30.0)

    def write(self, cmd):
        self.s.sendall((cmd + "\n").encode("ascii"))

    def query(self, cmd, timeout=30.0):
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
            print(f"  UXA error after {what}: {err}")


def load_regs(path):
    regs = {}
    for line in path.read_text().splitlines():
        m = re.match(r"R(\d+)\s+0x([0-9A-Fa-f]{6})", line.strip())
        if m:
            regs[int(m.group(1))] = int(m.group(2), 16) & 0xFFFF
    assert sorted(regs) == list(range(123))
    return regs


def wait_lock(b):
    for _ in range(40):
        if b.get_lmx_lock() == "LOCKED":
            return "LOCKED"
        time.sleep(0.05)
    return b.get_lmx_lock()


def capture(uxa, label, freqs):
    uxa.write(":INIT:REST")
    uxa.check("INIT:REST")
    print(f"  [{label}] averaging restarted, waiting {AVG_WAIT_S:.0f} s ...")
    time.sleep(AVG_WAIT_S)
    data = [float(v) for v in uxa.query(":TRAC:DATA? TRACE1").split(",")]
    uxa.check("TRAC:DATA?")
    assert len(data) == len(freqs), (len(data), len(freqs))
    return data


def comb_lines(freqs, trace, step_hz=10e6):
    """Peak within +-3 bins of every 10 MHz multiple in the span."""
    df = freqs[1] - freqs[0]
    out = []
    k = int(freqs[0] // step_hz) + 1
    while k * step_hz <= freqs[-1]:
        f = k * step_hz
        i = round((f - freqs[0]) / df)
        lo, hi = max(0, i - 3), min(len(trace), i + 4)
        out.append((f, max(trace[lo:hi])))
        k += 1
    return out


def main():
    regs = load_regs(REG_FILE)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    uxa = Uxa()
    print("UXA:", uxa.query("*IDN?"))
    start = float(uxa.query(":SENS:FREQ:STAR?"))
    stop = float(uxa.query(":SENS:FREQ:STOP?"))
    npts = int(float(uxa.query(":SENS:SWE:POIN?")))
    rbw = float(uxa.query(":SENS:BAND:RES?"))
    print(f"UXA as set by user: {start/1e9:.4f}-{stop/1e9:.4f} GHz, {npts} pts, RBW {rbw/1e3:g} kHz, "
          f"avg {uxa.query(':SENS:AVER:STAT?')} count {uxa.query(':SENS:AVER:COUN?')}, "
          f"cont {uxa.query(':INIT:CONT?')}")
    uxa.write(":FORM:TRAC:DATA ASC")
    uxa.check("FORM ASC")
    freqs = [start + i * (stop - start) / (npts - 1) for i in range(npts)]

    ports = find_board_ports()
    assert len(ports) == 1, ports
    b = Board(ports[0], timeout=OPERATING_TIMEOUT_S)
    persist_before = b.get_persist()
    b.set_persist(False)
    traces = {}
    try:
        print("\n(A) LMX TUNE 10 GHz (firmware template, doubler ON)")
        assert b.lmx_tune(10e9)
        print(f"  lock {wait_lock(b)}, R11 0x{b.read_lmx_register(11):04X}, "
              f"R36 (PLL_N) {b.read_lmx_register(36)}")
        traces["doubler_on"] = capture(uxa, "A", freqs)

        print("\n(B) TICS no-doubler register file, 10 GHz")
        for a in range(122, -1, -1):
            assert b.write_lmx_register(a, regs[a]), f"write R{a} failed"
        print(f"  lock {wait_lock(b)}, R11 0x{b.read_lmx_register(11):04X}, "
              f"R36 (PLL_N) {b.read_lmx_register(36)}")
        traces["doubler_off"] = capture(uxa, "B", freqs)
    finally:
        b.set_persist(persist_before)
        b.close()

    with open(OUTDIR / "trace_doubler_on_vs_off.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["freq_hz", "doubler_on_dbm", "doubler_off_dbm"])
        for row in zip(freqs, traces["doubler_on"], traces["doubler_off"]):
            w.writerow([f"{row[0]:.0f}", f"{row[1]:.2f}", f"{row[2]:.2f}"])

    on = comb_lines(freqs, traces["doubler_on"])
    off = comb_lines(freqs, traces["doubler_off"])
    floor_on = sorted(traces["doubler_on"])[len(freqs) // 2]
    floor_off = sorted(traces["doubler_off"])[len(freqs) // 2]
    print(f"\nMedian trace level (floor): doubler ON {floor_on:.1f} dBm, OFF {floor_off:.1f} dBm")
    print(f"{'freq (GHz)':>11} {'mult':>5} | {'ON (dBm)':>9} {'OFF (dBm)':>9} {'OFF-ON':>7}")
    with open(OUTDIR / "comb_lines_doubler_on_vs_off.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["freq_hz", "multiple_of", "doubler_on_dbm", "doubler_off_dbm"])
        for (fq, p_on), (_, p_off) in zip(on, off):
            mult = "20MHz" if round(fq / 10e6) % 2 == 0 else "10MHz"
            print(f"{fq/1e9:11.3f} {mult:>5} | {p_on:9.1f} {p_off:9.1f} {p_off - p_on:+7.1f}")
            w.writerow([f"{fq:.0f}", mult, f"{p_on:.2f}", f"{p_off:.2f}"])
    print(f"\nSaved {OUTDIR}")


if __name__ == "__main__":
    sys.exit(main())
