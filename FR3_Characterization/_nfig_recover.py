import socket

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


def query(sock, cmd, timeout=6.0):
    write(sock, cmd)
    try:
        return read_line(sock, timeout=timeout)
    except socket.timeout:
        return "<TIMEOUT>"


with socket.create_connection((HOST, PORT), timeout=8.0) as s:
    s.settimeout(8.0)
    print("IDN:", query(s, "*IDN?"))
    print("STATus:OPER:COND? (1=calibrating bit):", query(s, "STATus:OPERation:CONDition?"))
    print("Sending *CLS (clear status)...")
    write(s, "*CLS")
    print("Sending ABORt...")
    write(s, "ABORt")
    print("SYST:ERR? after CLS+ABORt:", query(s, "SYST:ERR?"))
    print("STATus:OPER:COND? again:", query(s, "STATus:OPERation:CONDition?"))
    print("NFloor cal time (fresh check):", query(s, "CALibration:TIME:NFLoor?", timeout=8.0))
    print("SYST:ERR?:", query(s, "SYST:ERR?"))
