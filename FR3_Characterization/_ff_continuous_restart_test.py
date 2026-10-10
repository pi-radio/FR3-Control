"""Test: INIT:CONT ON + TRAC1:REST + wait + single read, compared against the
known-good INIT:CONT OFF + 100x INIT:IMM;*OPC? loop, for both correctness
(does the mean/stdev match) and speed."""

import sys as _sys
_sys.exit("DISABLED 2026-10-10: this diagnostic sends INIT:CONT OFF to the FieldFox, which is never allowed "
          "(standing rule; the FieldFox crashed after a CONT OFF set-up). Kept only as a record of the 2026-10-02 test.")

import socket
import time

HOST = "192.168.137.61"
PORT = 5025
FREQ_HZ = 2.0e9
N_AVERAGES = 100


def write(sock, cmd):
    sock.sendall((cmd + "\n").encode("ascii"))


def query(sock, cmd, timeout=15.0):
    write(sock, cmd)
    buf = b""
    sock.settimeout(timeout)
    while b"\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    return buf.decode("ascii", "replace").strip()


def check(sock, label):
    e = query(sock, "SYST:ERR?")
    if not e.startswith("0,"):
        print(f"    *** ERROR [{label}]: {e}")
    return e


def stats(vals):
    m = sum(vals) / len(vals)
    var = sum((v - m) ** 2 for v in vals) / len(vals)
    return m, var ** 0.5


with socket.create_connection((HOST, PORT), timeout=20.0) as s:
    s.settimeout(20.0)
    write(s, "*CLS")
    write(s, 'INST:SEL "SA"')
    query(s, "*OPC?")
    write(s, "SENS:FREQ:SPAN 1000000")
    write(s, "SENS:POW:ATT 0")
    write(s, "DISP:WIND:TRAC:Y:RLEV -40")
    write(s, "CALC:MARK1:STAT NORM")
    write(s, "SENS:FREQ:CENT %d" % int(FREQ_HZ))
    time.sleep(0.2)
    write(s, "TRAC1:TYPE AVG")
    check(s, "trace type AVG")
    write(s, "SENS:AVER:TYPE POW")
    check(s, "aver type POW")
    write(s, f"SENS:AVER:COUN {N_AVERAGES}")
    check(s, "aver count")
    write(s, "CALC:MARK1:NOIS:STAT ON")
    check(s, "noise marker on")

    # First, time a single sweep under INIT:CONT OFF to estimate sweep duration.
    write(s, "INIT:CONT OFF")
    check(s, "cont off")
    t0 = time.monotonic()
    query(s, "INIT:IMM;*OPC?")
    one_sweep_s = time.monotonic() - t0
    print(f"Single sweep duration (measured): {one_sweep_s:.4f} s")
    wait_s = one_sweep_s * N_AVERAGES * 1.5  # 50% safety margin
    print(f"Planned wait for {N_AVERAGES} sweeps (with 50% margin): {wait_s:.2f} s\n")

    print("--- Known-good: CONT OFF, 100x INIT:IMM;*OPC? loop ---")
    vals_loop = []
    times_loop = []
    for i in range(10):
        t0 = time.monotonic()
        for _ in range(N_AVERAGES):
            query(s, "INIT:IMM;*OPC?")
        write(s, f"CALC:MARK1:X {FREQ_HZ:.0f}")
        check(s, "marker X")
        v = float(query(s, "CALC:MARK1:Y?"))
        elapsed = time.monotonic() - t0
        vals_loop.append(v)
        times_loop.append(elapsed)
        print(f"  [{i+1:2d}] {v:8.3f} dBm/Hz  ({elapsed:.2f} s)")
    m_loop, sd_loop = stats(vals_loop)
    print(f"  mean {m_loop:8.3f}  stdev {sd_loop:6.3f} dB  "
          f"avg time {sum(times_loop)/len(times_loop):.2f} s\n")

    print("--- New: CONT ON, TRAC1:REST, wait, single read ---")
    write(s, "INIT:CONT ON")
    check(s, "cont on")
    vals_cont = []
    times_cont = []
    for i in range(10):
        t0 = time.monotonic()
        write(s, "TRAC1:REST")
        check(s, "trace restart")
        time.sleep(wait_s)
        write(s, f"CALC:MARK1:X {FREQ_HZ:.0f}")
        check(s, "marker X")
        v = float(query(s, "CALC:MARK1:Y?"))
        elapsed = time.monotonic() - t0
        vals_cont.append(v)
        times_cont.append(elapsed)
        print(f"  [{i+1:2d}] {v:8.3f} dBm/Hz  ({elapsed:.2f} s)")
    m_cont, sd_cont = stats(vals_cont)
    print(f"  mean {m_cont:8.3f}  stdev {sd_cont:6.3f} dB  "
          f"avg time {sum(times_cont)/len(times_cont):.2f} s\n")

    write(s, "CALC:MARK1:NOIS:STAT OFF")
    write(s, "INIT:CONT OFF")
    write(s, "TRAC1:TYPE CLRW")

    print("Summary:")
    print(f"  100x-loop (CONT OFF):     mean {m_loop:8.3f}  stdev {sd_loop:.3f} dB  "
          f"time/reading {sum(times_loop)/len(times_loop):.2f} s")
    print(f"  CONT ON + TRAC1:REST:     mean {m_cont:8.3f}  stdev {sd_cont:.3f} dB  "
          f"time/reading {sum(times_cont)/len(times_cont):.2f} s")
