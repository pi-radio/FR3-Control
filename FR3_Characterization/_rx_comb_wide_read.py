"""Read the UXA's current (already averaged) trace without restarting it, and
summarize the 10 MHz-multiple comb across the span."""
import csv
import statistics
import sys

from _rx_comb_doubler_ab import OUTDIR, Uxa, comb_lines

label = sys.argv[1]
uxa = Uxa()
start = float(uxa.query(":SENS:FREQ:STAR?"))
stop = float(uxa.query(":SENS:FREQ:STOP?"))
npts = int(float(uxa.query(":SENS:SWE:POIN?")))
print(f"UXA: {start/1e9:.3f}-{stop/1e9:.3f} GHz, {npts} pts, "
      f"RBW {float(uxa.query(':SENS:BAND:RES?'))/1e3:g} kHz, detector "
      f"{uxa.query(':SENS:DET:TRAC1?')}, trace type {uxa.query(':TRAC1:TYPE?')}")
uxa.write(":FORM:TRAC:DATA ASC")
trace = [float(v) for v in uxa.query(":TRAC:DATA? TRACE1", timeout=60).split(",")]
uxa.check("TRAC:DATA?")
freqs = [start + i * (stop - start) / (npts - 1) for i in range(npts)]

tag = f"{label}_{start/1e9:.2f}-{stop/1e9:.2f}GHz"
with open(OUTDIR / f"trace_{tag}.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["freq_hz", "dbm"])
    w.writerows([f"{fq:.0f}", f"{p:.2f}"] for fq, p in zip(freqs, trace))

lines = comb_lines(freqs, trace)
df = freqs[1] - freqs[0]


def local_floor(fq):
    i = round((fq - freqs[0]) / df)
    win = trace[max(0, i - 60):i + 61]
    return statistics.median(win)


rows = [(fq, p, p - local_floor(fq)) for fq, p in lines]
with open(OUTDIR / f"comb_lines_{tag}.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["freq_hz", "multiple_of", "dbm", "above_local_floor_db"])
    for fq, p, a in rows:
        w.writerow([f"{fq:.0f}", "20MHz" if round(fq / 10e6) % 2 == 0 else "10MHz",
                    f"{p:.2f}", f"{a:.2f}"])

print(f"Median trace level: {statistics.median(trace):.1f} dBm")
print(f"\nPer 250 MHz band: strongest 20 MHz-multiple and odd-10 MHz line, "
      f"and how many lines are >6 dB above the local floor")
print(f"{'band (GHz)':>12} | {'max even':>17} | {'max odd':>17} | {'>6 dB':>5}")
b0 = start
while b0 < stop - 1:
    b1 = b0 + 250e6
    sel = [r for r in rows if b0 <= r[0] < b1]
    ev = [r for r in sel if round(r[0] / 10e6) % 2 == 0]
    od = [r for r in sel if round(r[0] / 10e6) % 2 == 1]
    fe = max(ev, key=lambda r: r[1]) if ev else None
    fo = max(od, key=lambda r: r[1]) if od else None
    n6 = sum(1 for r in sel if r[2] > 6)
    print(f"{b0/1e9:5.2f}-{b1/1e9:5.2f} | "
          + (f"{fe[1]:6.1f} @ {fe[0]/1e9:5.3f}" if fe else " " * 17) + " | "
          + (f"{fo[1]:6.1f} @ {fo[0]/1e9:5.3f}" if fo else " " * 17) + f" | {n6:5d}")
    b0 = b1

print("\nTop 15 lines by height above local floor:")
for fq, p, a in sorted(rows, key=lambda r: -r[2])[:15]:
    print(f"  {fq/1e9:6.3f} GHz ({'20MHz' if round(fq/10e6) % 2 == 0 else '10MHz'}): "
          f"{p:6.1f} dBm, {a:+5.1f} dB above floor")
print(f"\nSaved {OUTDIR / f'trace_{tag}.csv'}")
