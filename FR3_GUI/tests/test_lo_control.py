"""Firmware 1.4.1 LO control: drive AUTO mode, calibration-driven I/Q bias, calibration upload/readback.
Command formatting and response parsing against the fake serial port (no hardware)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from fr3_gui.capabilities import get_capabilities
from fr3_gui.device import Device, DeviceError

from test_device import FakeSerial


@pytest.fixture
def device():
    with patch("fr3_gui.device.serial.Serial") as serial_ctor:
        fake = FakeSerial()
        serial_ctor.return_value = fake
        dev = Device("COM_FAKE")
        dev._fake = fake
        yield dev


def test_capability_only_on_rev_1_4():
    assert get_capabilities("FR3 1CH", "1.4").has_lo_control
    assert not get_capabilities("FR3 1CH", "1.1").has_lo_control
    assert not get_capabilities("OctoLO", "1.4").has_lo_control


def test_power_auto(device):
    device._fake.next_response = b"OK\r\n"
    assert device.set_lmx_power_auto()
    assert device._fake.written[-1] == b"LMX PWR AUTO\r\n"
    device._fake.next_response = b"MANUAL\r\n"
    assert device.get_lmx_power_auto() is False
    assert device._fake.written[-1] == b"LMX PWR MODE?\r\n"


@pytest.mark.parametrize("auto, command", [(True, b"IQBIAS AUTO\r\n"), (False, b"IQBIAS MANUAL\r\n")])
def test_set_iq_bias_auto(device, auto, command):
    device._fake.next_response = b"OK\r\n"
    assert device.set_iq_bias_auto(auto)
    assert device._fake.written[-1] == command


def test_set_iq_bias_auto_without_calibration(device):
    device._fake.next_response = b"ERR NOCAL\r\n"
    assert device.set_iq_bias_auto(True) is False


def test_get_iq_bias_auto(device):
    device._fake.next_response = b"AUTO ON I=0.019950 Q=-0.061300 T=63.6\r\n"
    assert device.get_iq_bias() == {"auto": True, "state": "ON", "i_v": 0.01995, "q_v": -0.0613, "temp_c": 63.6}


def test_get_iq_bias_manual(device):
    device._fake.next_response = b"MANUAL I=0.010000 Q=0.020000\r\n"
    assert device.get_iq_bias() == {"auto": False, "state": "", "i_v": 0.01, "q_v": 0.02, "temp_c": None}


def test_get_iq_bias_rejects_old_firmware_echo(device):
    device._fake.next_response = b"ERR:[IQBIAS?]len=7\r\n"
    with pytest.raises(DeviceError):
        device.get_iq_bias()


def test_cal_info(device):
    device._fake.next_response = b"N=312 FMT=1 CRC=OK SN=6 DATE=20261010\r\n"
    assert device.get_cal_info() == {"n": 312, "format": 1, "crc_ok": True, "serial": 6, "date": 20261010}
    device._fake.next_response = b"NONE\r\n"
    assert device.get_cal_info() is None


def test_cal_temps(device):
    device._fake.next_response = b"C=61.0..67.8 H=73.8..85.3\r\n"
    assert device.get_cal_temps() == {"cold": (61.0, 67.8), "hot": (73.8, 85.3)}
    device._fake.next_response = b"ERR NOCAL\r\n"
    assert device.get_cal_temps() is None


def test_cal_upload_line_fits_firmware_buffer(device):
    """The firmware keeps at most 63 characters of a line."""
    device._fake.next_response = b"OK\r\n"
    assert device.cal_set_entry(155, True, -0.499999, -0.499999, -40.0)
    line = device._fake.written[-1]
    assert line == b"CAL LO 155 H -0.499999 -0.499999 -40.0\r\n"
    assert len(line.rstrip(b"\r\n")) <= 63


def test_cal_commit_and_readback(device):
    device._fake.next_response = b"ERR INCOMPLETE\r\n"
    assert device.cal_commit() == "ERR INCOMPLETE"
    device._fake.next_response = b"0.019950 0.061300 63.6\r\n"
    assert device.cal_get_entry(10, False) == (0.01995, 0.0613, 63.6)
    assert device._fake.written[-1] == b"CAL LO? 10 C\r\n"
    device._fake.next_response = b"ERR\r\n"
    assert device.cal_get_entry(10, True) is None
