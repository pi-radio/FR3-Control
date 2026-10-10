"""Mute or unmute the LMX2820 without saving to flash (persistence restored as found).
Usage: python _lmx_mute.py on|off"""
import sys

from board import OPERATING_TIMEOUT_S, Board, find_board_ports

want_mute = sys.argv[1].lower() == "on"
ports = find_board_ports()
assert len(ports) == 1, ports
b = Board(ports[0], timeout=OPERATING_TIMEOUT_S)
persist = b.get_persist()
try:
    b.set_persist(False)
    print(f"before: mute {b.get_lmx_mute()}, lock {b.get_lmx_lock()}, LMX {b.get_lmx_freq_hz()/1e9:g} GHz")
    ok = b.set_lmx_mute(want_mute)
    print(f"LMX MUTE {'ON' if want_mute else 'OFF'} -> {'OK' if ok else 'ERR'}")
    print(f"after:  mute {b.get_lmx_mute()}, lock {b.get_lmx_lock()}")
finally:
    b.set_persist(persist)
    b.close()
