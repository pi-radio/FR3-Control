"""Unit tests for the Device protocol layer against a fake serial port -
no real hardware needed. Covers command formatting, response parsing, and
the timeout/I/O-error -> DeviceError contract."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fr3_gui.device import Device, DeviceError


class FakeSerial:
    """Stand-in for serial.Serial mirroring firmware's line-echo behavior:
    each write() queues an echo of the command, the response, then a
    trailing blank line."""

    def __init__(self, *args, **kwargs):
        self.written: list[bytes] = []
        self.next_response: bytes = b""
        self._read_queue: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)
        command_text = data.decode("ascii").rstrip("\r\n")
        self._read_queue = [f"{command_text}\r\n".encode("ascii")]
        if self.next_response:
            self._read_queue.append(self.next_response)
        self._read_queue.append(b"\r\n")

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        pass

    def readline(self) -> bytes:
        if self._read_queue:
            return self._read_queue.pop(0)
        return b""

    def close(self) -> None:
        pass


@pytest.fixture
def device():
    with patch("fr3_gui.device.serial.Serial") as serial_ctor:
        fake = FakeSerial()
        serial_ctor.return_value = fake
        dev = Device("COM_FAKE")
        dev._fake = fake  # stash for tests to configure/inspect
        yield dev


def test_get_idn(device):
    device._fake.next_response = b"FR3 1CH REV1.4,STM32H573VIT6,FW1.0\r\n"
    assert device.get_idn() == "FR3 1CH REV1.4,STM32H573VIT6,FW1.0"
    assert device._fake.written[-1] == b"*IDN?\r\n"


def test_lmx_tune_formats_integer_hz_and_reports_success(device):
    device._fake.next_response = b"OK\r\n"
    assert device.lmx_tune(10_000_000_000.0) is True
    assert device._fake.written[-1] == b"LMX TUNE 10000000000\r\n"


def test_lmx_tune_reports_failure_on_err(device):
    device._fake.next_response = b"ERR\r\n"
    assert device.lmx_tune(10_000_000_000.0) is False


def test_get_lmx_lock_passes_through_status_text(device):
    for status in ("LOCKED", "UNLOCKED", "INVALID"):
        device._fake.next_response = f"{status}\r\n".encode("ascii")
        assert device.get_lmx_lock() == status


def test_set_i_v_formats_six_decimal_places(device):
    device._fake.next_response = b"OK\r\n"
    device.set_i_v(0.1234565)
    assert device._fake.written[-1] == b"SET I_V 0.123456\r\n" or device._fake.written[-1] == b"SET I_V 0.123457\r\n"


def test_get_i_v_parses_float(device):
    device._fake.next_response = b"0.250000\r\n"
    assert device.get_i_v() == pytest.approx(0.25)


def test_set_tx_filter_formats_hex(device):
    device._fake.next_response = b"OK\r\n"
    device.set_tx_filter(0x3F)
    assert device._fake.written[-1] == b"SET TXFILTER 0x3F\r\n"


def test_get_tx_filter_parses_hex(device):
    device._fake.next_response = b"0x2A\r\n"
    assert device.get_tx_filter() == 0x2A


def test_timeout_raises_device_error(device):
    # No response programmed - queue runs dry after echo/blank, simulating a timeout.
    device._fake.next_response = b""
    with pytest.raises(DeviceError):
        device.get_idn()


def test_echo_and_blank_line_are_skipped(device):
    # Regression: _query() must skip the echoed command and blank line.
    device._fake.next_response = b"FR3 1CH REV1.4,STM32H573VIT6,FW1.0\r\n"
    assert device.get_idn() == "FR3 1CH REV1.4,STM32H573VIT6,FW1.0"


def test_io_error_raises_device_error(device):
    device._fake.write = MagicMock(side_effect=OSError("port gone"))
    with pytest.raises(DeviceError):
        device.get_idn()


def test_read_lmx_register_parses_hex(device):
    device._fake.next_response = b"0x8DF9\r\n"
    assert device.read_lmx_register(74) == 0x8DF9
    assert device._fake.written[-1] == b"LMX REG74?\r\n"


def test_board_serial_roundtrip(device):
    device._fake.next_response = b"1001\r\n"
    assert device.get_board_serial() == 1001
