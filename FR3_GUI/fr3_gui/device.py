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

    # ---- 1.4.1 drive rule (rev 1.4: BoardCapabilities.has_lo_control) ----

    def set_lmx_power_auto(self) -> bool:
        """AUTO drive: the firmware sets OUTA_PWR from the LO frequency on every tune (0 for LO <= 13
        GHz, 2 for 13-20 GHz, 4 for >= 20 GHz). set_lmx_power() switches back to MANUAL."""
        return self._query_ok("LMX PWR AUTO")

    def get_lmx_power_auto(self) -> bool:
        return self._query("LMX PWR MODE?") == "AUTO"

    def set_lmx_mute(self, mute: bool) -> bool:
        return self._query_ok(f"LMX MUTE {'ON' if mute else 'OFF'}")

    def get_lmx_mute(self) -> bool:
        return self._query("LMX MUTE?") == "ON"

    def get_lmx_lock(self) -> str:
        """Returns 'LOCKED' or 'UNLOCKED' - the firmware collapses the
        LMX2820's own rb_LD==0b11 "invalid" readback (e.g. seen with
        External clock selected and nothing actually connected) into
        UNLOCKED before it ever reaches this command."""
        return self._query("LMX LOCK?")

    def get_lmx_temperature_c(self) -> float:
        """Die temperature from the LMX2820's own sensor - approximate
        (+-5C per datasheet), see Section 6 of README.md."""
        return float(self._query("LMX TEMP?"))

    def read_lmx_register(self, addr: int) -> int:
        """Raw single-register readback (debug/bring-up command), addr 0-122."""
        return int(self._query(f"LMX REG{addr}?"), 16)

    def write_lmx_register(self, addr: int, value: int) -> bool:
        """Raw single-register write (debug sessions only), addr 0-122. Not
        persisted; LMX FREQ? goes stale and the next LMX TUNE rewrites all
        registers from the firmware template."""
        # Bare hex digits: the firmware's newlib scanf rejects a zero value
        # written with a 0X prefix ("0X0000").
        return self._query_ok(f"LMX REG{addr} {value:04X}")

    # ---- LTC2668 I/Q DAC ----

    def set_i_v(self, volts: float) -> bool:
        return self._query_ok(f"SET I_V {volts:.6f}")

    def get_i_v(self) -> float:
        return float(self._query("GET I_V"))

    def set_q_v(self, volts: float) -> bool:
        return self._query_ok(f"SET Q_V {volts:.6f}")

    def get_q_v(self) -> float:
        return float(self._query("GET Q_V"))

    # ---- 1.4.1 per-unit LO-null calibration (rev 1.4: BoardCapabilities.has_lo_control) ----

    def set_iq_bias_auto(self, auto: bool) -> bool:
        """AUTO: the firmware applies the unit's stored cold/hot calibration, interpolated to the LMX
        temperature, on every tune and every 2 s. Fails (False) with no calibration stored. A manual
        set_i_v()/set_q_v() also switches to MANUAL."""
        return self._query_ok("IQBIAS AUTO" if auto else "IQBIAS MANUAL")

    def get_iq_bias(self) -> dict:
        """{'auto': bool, 'state': 'ON'|'NOCAL'|'EXTLO'|'MUTED'|'' (manual), 'i_v': float, 'q_v': float,
        'temp_c': float|None} from "AUTO ON I=0.019950 Q=0.061300 T=63.6" / "MANUAL I=... Q=...". """
        text = self._query("IQBIAS?")
        words = text.split()
        if not words or words[0] not in ("AUTO", "MANUAL"):
            raise DeviceError(f"Unexpected IQBIAS? response on {self.port_name}: {text!r}")
        fields = dict(w.split("=", 1) for w in words if "=" in w)
        try:
            return {"auto": words[0] == "AUTO", "state": words[1] if words[0] == "AUTO" else "",
                    "i_v": float(fields["I"]), "q_v": float(fields["Q"]),
                    "temp_c": float(fields["T"]) if "T" in fields else None}
        except (KeyError, ValueError, IndexError) as exc:
            raise DeviceError(f"Unexpected IQBIAS? response on {self.port_name}: {text!r}") from exc

    def get_cal_info(self) -> dict | None:
        """None if no calibration is stored, else {'n': int, 'format': int, 'crc_ok': bool, 'serial': int,
        'date': int} from "N=312 FMT=1 CRC=OK SN=6 DATE=20261010". """
        text = self._query("CAL INFO?")
        if text == "NONE":
            return None
        try:
            f = dict(w.split("=", 1) for w in text.split())
            return {"n": int(f["N"]), "format": int(f["FMT"]), "crc_ok": f["CRC"] == "OK",
                    "serial": int(f["SN"]), "date": int(f["DATE"])}
        except (KeyError, ValueError) as exc:
            raise DeviceError(f"Unexpected CAL INFO? response on {self.port_name}: {text!r}") from exc

    def get_cal_temps(self) -> dict | None:
        """{'cold': (min, max), 'hot': (min, max)} in C from "C=61.0..67.8 H=73.8..85.3", or None."""
        text = self._query("CAL TEMPS?")
        if text.startswith("ERR"):
            return None
        try:
            f = dict(w.split("=", 1) for w in text.split())
            pair = lambda v: tuple(float(x) for x in v.split(".."))
            return {"cold": pair(f["C"]), "hot": pair(f["H"])}
        except (KeyError, ValueError) as exc:
            raise DeviceError(f"Unexpected CAL TEMPS? response on {self.port_name}: {text!r}") from exc

    # Upload (production; not used by the GUI itself). One entry per command - the firmware's
    # 63-character line limit. Nothing is active until cal_commit().

    def cal_clear(self) -> bool:
        return self._query_ok("CAL CLEAR")

    def cal_set_entry(self, idx: int, hot: bool, i_v: float, q_v: float, temp_c: float) -> bool:
        return self._query_ok(f"CAL LO {idx} {'H' if hot else 'C'} {i_v:.6f} {q_v:.6f} {temp_c:.1f}")

    def cal_set_date(self, yyyymmdd: int) -> bool:
        return self._query_ok(f"CAL DATE {yyyymmdd}")

    def cal_staged_count(self) -> int:
        return int(self._query("CAL STAGED?"))

    def cal_commit(self) -> str:
        """'OK', or the firmware's 'ERR <reason>' (INCOMPLETE / FLASH / VERIFY)."""
        return self._query("CAL COMMIT")

    def cal_get_entry(self, idx: int, hot: bool) -> tuple[float, float, float] | None:
        """(I_V, Q_V, temperature C) of the stored (flash) table, or None."""
        text = self._query(f"CAL LO? {idx} {'H' if hot else 'C'}")
        if text.startswith("ERR"):
            return None
        try:
            i_v, q_v, t = (float(x) for x in text.split())
            return i_v, q_v, t
        except ValueError as exc:
            raise DeviceError(f"Unexpected CAL LO? response on {self.port_name}: {text!r}") from exc

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
