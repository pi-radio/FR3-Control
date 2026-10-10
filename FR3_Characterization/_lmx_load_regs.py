"""Debug: load a TICS Pro hex register export into the LMX2820 via the raw
`LMX REG<n> 0x<hhhh>` command (R122 down to R0, R0 last). Opens the board
directly - not MeasurementSession, whose exit restore would re-tune the LMX and
overwrite these registers."""
import re
import sys
import time
from pathlib import Path

from board import OPERATING_TIMEOUT_S, Board, find_board_ports

READBACK_ONLY = {74, 75, 76}  # status/readback registers, not configuration

path = Path(sys.argv[1])
regs = {}
for line in path.read_text().splitlines():
    m = re.match(r"R(\d+)\s+0x([0-9A-Fa-f]{6})", line.strip())
    if m:
        word = int(m.group(2), 16)
        addr, data = int(m.group(1)), word & 0xFFFF
        assert (word >> 16) == addr, f"address byte mismatch on {line!r}"
        regs[addr] = data
assert sorted(regs) == list(range(123)), "expected R0..R122"

ports = find_board_ports()
assert len(ports) == 1, ports
b = Board(ports[0], timeout=OPERATING_TIMEOUT_S)
try:
    print("IDN:", b.get_idn())
    print(f"Before: LMX FREQ? {b.get_lmx_freq_hz()/1e9:g} GHz, mute {b.get_lmx_mute()}, "
          f"lock {b.get_lmx_lock()}")

    r11 = b.read_lmx_register(11)
    ok = b.write_lmx_register(11, r11)
    print(f"Write-command check: R11 = 0x{r11:04X}, wrote it back -> {'OK' if ok else 'FAILED'}, "
          f"readback 0x{b.read_lmx_register(11):04X}")
    if not ok:
        sys.exit(1)

    current = {a: b.read_lmx_register(a) for a in range(123)}
    diffs = [a for a in range(123) if a not in READBACK_ONLY and current[a] != regs[a]]
    print(f"\nRegisters that differ from the chip's current values ({len(diffs)}):")
    for a in diffs:
        print(f"  R{a:<3d} chip 0x{current[a]:04X} -> file 0x{regs[a]:04X}")

    print("\nWriting R122..R0 ...")
    for a in range(122, -1, -1):
        if not b.write_lmx_register(a, regs[a]):
            print(f"  write R{a} FAILED")
            sys.exit(1)
    for _ in range(20):
        time.sleep(0.05)
        if b.get_lmx_lock() == "LOCKED":
            break
    print(f"After: lock {b.get_lmx_lock()}")
    for a in diffs:
        rb = b.read_lmx_register(a)
        print(f"  R{a:<3d} readback 0x{rb:04X} {'(matches file)' if rb == regs[a] else '(DIFFERS from file)'}")
finally:
    b.close()
