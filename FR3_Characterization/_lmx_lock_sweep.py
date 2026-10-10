"""Quick LMX2820 lock check across the tuning range (normal LMX TUNE path,
firmware template with OSC_2X doubler). Restores the original frequency and the
persistence setting afterwards; changes nothing else."""
import time

from board import OPERATING_TIMEOUT_S, Board, find_board_ports

FREQS_GHZ = (6.0, 7.5, 9.0, 10.0, 11.3, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 22.6)

ports = find_board_ports()
assert len(ports) == 1, ports
b = Board(ports[0], timeout=OPERATING_TIMEOUT_S)
persist = b.get_persist()
f0 = b.get_lmx_freq_hz()
try:
    b.set_persist(False)
    print(f"Start: LMX {f0/1e9:g} GHz, lock {b.get_lmx_lock()}, mute {b.get_lmx_mute()}")
    fails = 0
    for f in FREQS_GHZ:
        ok = b.lmx_tune(f * 1e9)
        lock = b.get_lmx_lock()
        for _ in range(20):
            if lock == "LOCKED":
                break
            time.sleep(0.05)
            lock = b.get_lmx_lock()
        fails += lock != "LOCKED"
        print(f"  {f:5.1f} GHz: tune {'OK' if ok else 'ERR'}, lock {lock}")
    print(f"{len(FREQS_GHZ) - fails}/{len(FREQS_GHZ)} frequencies locked")
finally:
    b.lmx_tune(f0)
    print(f"Restored LMX {b.get_lmx_freq_hz()/1e9:g} GHz, lock {b.get_lmx_lock()}")
    b.set_persist(persist)
    b.close()
