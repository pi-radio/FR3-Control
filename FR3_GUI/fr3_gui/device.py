"""Blocking protocol layer for one board's USB CDC serial port. No Qt/GUI
code - independently testable against a mock serial port. Every method
sends one command and parses one response line; all failures raise
DeviceError."""

from __future__ import annotations

import logging
import threading

import serial

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 1.0

# Firmware echoes the command line, then the real response, then a blank
# line (see app_usbx_device.c) - skip up to 2 lines to reach the response.
_MAX_LINES_PER_QUERY = 3

# Matches LMX2820_REG_COUNT in the firmware - registers 0-122 inclusive.
LMX_REGISTER_COUNT = 123


class DeviceError(Exception):
    """Raised for any failure talking to a device: timeout, I/O error, or a
    response that doesn't parse as expected."""


class Device:
    """Thread-safe wrapper around one open serial connection. Safe to call
    from any thread - an internal lock serializes command traffic so two
    threads can never interleave bytes on the same port."""

    def __init__(self, port_name: str, timeout: float = DEFAULT_TIMEOUT_S):
        self.port_name = port_name
        self._lock = threading.Lock()
        # CDC ACM ignores the requested baud rate entirely, but pyserial
        # requires a value to be given.
        self._serial = serial.Serial(
            port=port_name,
            baudrate=115200,
            timeout=timeout,
            write_timeout=timeout,
        )

    def close(self) -> None:
        with self._lock:
            try:
                self._serial.close()
            except Exception:
                pass

    def set_timeout(self, timeout_s: float) -> None:
        """Changes the read/write timeout on the open connection. Discovery
        probes with a short timeout; switch to a longer one before handing
        off for normal use, since a full LMX2820 retune can take seconds."""
        with self._lock:
            self._serial.timeout = timeout_s
            self._serial.write_timeout = timeout_s

    def _query(self, command: str) -> str:
        with self._lock:
            logger.debug("%s -> %r", self.port_name, command)
            try:
                self._serial.reset_input_buffer()
                self._serial.write((command + "\r\n").encode("ascii"))
                self._serial.flush()

                for _ in range(_MAX_LINES_PER_QUERY):
                    raw = self._serial.readline()
                    if not raw:
                        raise DeviceError(
                            f"Timeout waiting for response to {command!r} on {self.port_name}"
                        )
                    text = raw.decode("ascii", errors="replace").strip()
                    logger.debug("%s <- %r", self.port_name, text)
                    if text == "" or text == command:
                        continue  # the command's own echo, or the trailing blank-line echo
                    return text

                raise DeviceError(
                    f"No response to {command!r} on {self.port_name} (only echo/blank lines)"
                )
            except (serial.SerialException, OSError) as exc:
                raise DeviceError(f"I/O error on {self.port_name} ({command!r}): {exc}") from exc

    def _query_ok(self, command: str) -> bool:
        return self._query(command) == "OK"

    # ---- Identity ----

    def get_idn(self) -> str:
        return self._query("*IDN?")

    def get_board_serial(self) -> int:
        return int(self._query("GET BOARD SERIAL"))

    # ---- LMX2820 ----

    def lmx_tune(self, freq_hz: float) -> bool:
        return self._query_ok(f"LMX TUNE {freq_hz:.0f}")

    def get_lmx_freq_hz(self) -> int:
        return int(self._query("LMX FREQ?"))

    def set_lmx_power(self, level: int) -> bool:
        return self._query_ok(f"LMX PWR {level}")

    def get_lmx_power(self) -> int:
        return int(self._query("LMX PWR?"))

    def set_lmx_mute(self, mute: bool) -> bool:
        return self._query_ok(f"LMX MUTE {'ON' if mute else 'OFF'}")

    def get_lmx_mute(self) -> bool:
        return self._query("LMX MUTE?") == "ON"

    def get_lmx_lock(self) -> str:
        """Returns 'LOCKED', 'UNLOCKED', or 'INVALID'."""
        return self._query("LMX LOCK?")

    def read_lmx_register(self, addr: int) -> int:
        """Raw single-register readback (debug/bring-up command), addr 0-122."""
        return int(self._query(f"LMX REG{addr}?"), 16)

    # ---- LTC2668 I/Q DAC ----

    def set_i_v(self, volts: float) -> bool:
        return self._query_ok(f"SET I_V {volts:.6f}")

    def get_i_v(self) -> float:
        return float(self._query("GET I_V"))

    def set_q_v(self, volts: float) -> bool:
        return self._query_ok(f"SET Q_V {volts:.6f}")

    def get_q_v(self) -> float:
        return float(self._query("GET Q_V"))

    # ---- Clock / LO / IQ swap ----

    def set_clock_internal(self, internal: bool) -> bool:
        return self._query_ok(f"SET CLOCK {'INT' if internal else 'EXT'}")

    def get_clock_internal(self) -> bool:
        return self._query("GET CLOCK") == "INT"

    def set_lo_internal(self, internal: bool) -> bool:
        return self._query_ok(f"SET LO {'INT' if internal else 'EXT'}")

    def get_lo_internal(self) -> bool:
        return self._query("GET LO") == "INT"

    def set_iq_swap(self, swap: bool) -> bool:
        return self._query_ok(f"SET IQ {'SWAP' if swap else 'THRU'}")

    def get_iq_swap(self) -> bool:
        return self._query("GET IQ") == "SWAP"

    # ---- RF filters (rev 1.4 only - caller checks capabilities first) ----

    def set_tx_filter(self, bits: int) -> bool:
        return self._query_ok(f"SET TXFILTER 0x{bits:02X}")

    def get_tx_filter(self) -> int:
        return int(self._query("GET TXFILTER"), 16)

    def set_rx_filter(self, bits: int) -> bool:
        return self._query_ok(f"SET RXFILTER 0x{bits:02X}")

    def get_rx_filter(self) -> int:
        return int(self._query("GET RXFILTER"), 16)
