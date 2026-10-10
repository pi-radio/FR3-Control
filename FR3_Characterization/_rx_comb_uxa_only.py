"""UXA-only capture of the RX IF comb (no board commands), compared line by line
against a previous comb_lines CSV taken over the same span."""
import csv
import sys
import time
from pathlib import Path

from _rx_comb_doubler_ab import AVG_WAIT_S, OUTDIR, Uxa, comb_lines

label = sys.argv[1]
ref_csv = Path(sys.argv[2]) if len(sys.argv) > 2 else None
ref_col = sys.argv[3] if len(sys.argv) > 3 else "doubler_on_dbm"

uxa = Uxa()
start = float(uxa.query(":SENS:FREQ:STAR?"))
stop = float(uxa.query(":SENS:FREQ:STOP?"))
npts = int(float(uxa.query(":SENS:SWE:POIN?")))
print(f"UXA: {start/1e9:.4f}-{stop/1e9:.4f} GHz, {npts} pts, "
      f"RBW {float(uxa.query(':SENS:BAND:RES?'))/1e3:g} kHz")
uxa.write(":FORM:TRAC:DATA ASC")
freqs = [start + i * (stop - start) / (npts - 1) for i in range(npts)]
uxa.write(":INIT:REST")
uxa.check("INIT:REST")
time.sleep(AVG_WAIT_S)
trace = [float(v) for v in uxa.query(":TRAC:DATA? TRACE1").split(",")]
uxa.check("TRAC:DATA?")

tag = f"{label}_{start/1e9:.2f}-{stop/1e9:.2f}GHz"
with open(OUTDIR / f"trace_{tag}.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["freq_hz", "dbm"])
    w.writerows([f"{fq:.0f}", f"{p:.2f}"] for fq, p in zip(freqs, trace))

ref = {}
if ref_csv:
    for r in csv.DictReader(open(ref_csv)):
        ref[round(float(r["freq_hz"]))] = float(r[ref_col])
lines = comb_lines(freqs, trace)
print(f"Median trace level: {sorted(trace)[npts // 2]:.1f} dBm")
print(f"{'freq (GHz)':>11} {'mult':>5} | {'now':>7} {'before':>7} {'delta':>6}")
deltas = {"20MHz": [], "10MHz": []}
for fq, p in lines:
    mult = "20MHz" if round(fq / 10e6) % 2 == 0 else "10MHz"
    b = ref.get(round(fq))
    if b is not None:
        deltas[mult].append(p - b)
    print(f"{fq/1e9:11.3f} {mult:>5} | {p:7.1f} "
          + (f"{b:7.1f} {p - b:+6.1f}" if b is not None else ""))
for k, v in deltas.items():
    if v:
        print(f"Mean change, {k} lines: {sum(v)/len(v):+.1f} dB (range {min(v):+.1f} to {max(v):+.1f})")
print(f"Saved {OUTDIR / f'trace_{tag}.csv'}")
