import socket
import time

HOST = "192.168.137.71"
PORT = 5025


def write(sock, cmd):
    sock.sendall((cmd + "\n").encode("ascii"))


def read_line(sock, bufsize=65536, timeout=None):
    if timeout is not None:
        sock.settimeout(timeout)
    data = b""
    while b"\n" not in data:
        chunk = sock.recv(bufsize)
        if not chunk:
            break
        data += chunk
    return data.decode("ascii", "replace").strip()


def query(sock, cmd, timeout=None):
    write(sock, cmd)
    return read_line(sock, timeout=timeout)


def check(sock, label):
    e = query(sock, "SYST:ERR?", timeout=10.0)
    print(f"  [{label}] SYST:ERR? -> {e}", flush=True)
    return e


with socket.create_connection((HOST, PORT), timeout=20.0) as s:
    s.settimeout(20.0)

    write(s, 'INST:SEL "NFIG"')
    time.sleep(2)
    check(s, "mode select")

    print("Starting CALibration:NFLoor -- giving it up to 30 minutes this time...", flush=True)
    t0 = time.monotonic()
    write(s, "CALibration:NFLoor")
    print("OPC result:", query(s, "*OPC?", timeout=1800.0), flush=True)
    print(f"elapsed: {time.monotonic() - t0:.1f}s", flush=True)
    check(s, "after NFLoor cal")

    print("NFloor cal time now:", query(s, "CALibration:TIME:NFLoor?", timeout=15.0))
    print("NFloor cal temp now:", query(s, "CALibration:TEMPerature:NFLoor?", timeout=15.0))
