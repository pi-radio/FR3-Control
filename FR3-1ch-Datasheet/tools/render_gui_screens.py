"""Renders the Pi-Radio GUI (FR3_GUI, GUI 1.4.1) to PNG images for the datasheet's "Using the Pi-Radio GUI" appendix,
without hardware and without showing a window: a DeviceTab is built against a simulated unit (FakeDevice, values from
Unit #6 on 2026-10-10) and grabbed off-screen.

    FR3_GUI\\venv\\Scripts\\python.exe tools\\render_gui_screens.py

Writes, in images/ (the appendix's section images are cropped from real screenshots: tools/crop_gui_screenshots.py):
  gui_lo_suppr_extlo.png the TX I/Q DAC group with the LO source set to External (the red "inactive" status)
  gui_tx_filter_manual.png  the TX Filter group with a filter chosen by hand (the "In use / Suggested" note)
The GUI's per-machine settings are neither read nor written (load/save are stubbed), so nothing on this machine changes.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASHEET = HERE.parent
GUI = DATASHEET.parent / "FR3_GUI"
sys.path.insert(0, str(GUI))

from PySide6.QtWidgets import QApplication, QCheckBox, QGroupBox  # noqa: E402

import fr3_gui.configuration_helper as helper_mod  # noqa: E402
from fr3_gui.capabilities import get_capabilities  # noqa: E402
from fr3_gui.device_tab import STYLE_SHEET, DeviceTab  # noqa: E402
from fr3_gui.discovery import DeviceInfo  # noqa: E402

# never touch the user's real per-machine GUI settings
helper_mod.load_tx_helper_inputs = lambda key: (2.0, 10.0, 0.5)
helper_mod.save_tx_helper_inputs = lambda *a, **k: None

IMAGES = DATASHEET / "images"
SECTIONS = DATASHEET / "sections"


class FakeDevice:
    """Answers the GUI's Device calls like Unit #6 (firmware 1.4.1) at FR1 2 GHz / FR3 10 GHz, upper sideband."""

    port_name = "COM7"

    def __init__(self, ext_lo: bool = False):
        self.lo_internal = not ext_lo

    def __getattr__(self, name):
        if name.startswith("set_") or name in ("lmx_tune", "cal_clear", "cal_set_entry", "cal_set_date"):
            return lambda *a, **k: True
        raise AttributeError(name)

    def close(self):
        pass

    def get_lmx_freq_hz(self): return 8_000_000_000
    def get_lmx_power(self): return 0
    def get_lmx_power_auto(self): return True
    def get_lmx_mute(self): return not self.lo_internal
    def get_lmx_lock(self): return "LOCKED"
    def get_lmx_temperature_c(self): return 78.0
    def get_i_v(self): return 0.018071
    def get_q_v(self): return 0.058907
    def get_clock_internal(self): return True
    def get_lo_internal(self): return self.lo_internal
    def get_iq_swap(self): return False
    def get_tx_filter(self): return 0x3E
    def get_rx_filter(self): return 0x3E

    def get_iq_bias(self):
        return {"auto": True, "state": "ON" if self.lo_internal else "EXTLO", "i_v": 0.018071, "q_v": 0.058907,
                "temp_c": 78.0}

    def get_cal_info(self):
        return {"n": 312, "format": 1, "crc_ok": True, "serial": 6, "date": 20261010}

    def get_cal_temps(self):
        return {"cold": (61.0, 67.8), "hot": (72.9, 83.1)}


def pump(app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)


def make_tab(app, ext_lo: bool) -> DeviceTab:
    caps = get_capabilities("FR3 1CH", "1.4")
    info = DeviceInfo(port_name="COM7", board_name="FR3 1CH", revision="1.4", serial_number=6, capabilities=caps,
                      device=FakeDevice(ext_lo=ext_lo))
    tab = DeviceTab(info)
    tab.resize(tab.natural_size())
    pump(app, 3.0)                                   # the snapshot + one 2 s status poll
    tab._content.adjustSize()
    return tab


def group_of(widget) -> QGroupBox:
    w = widget
    while w is not None and not isinstance(w, QGroupBox):
        w = w.parentWidget()
    return w


def checkbox(tab: DeviceTab, text: str, index: int = 0) -> QCheckBox:
    return [c for c in tab._content.findChildren(QCheckBox) if c.text() == text][index]


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(STYLE_SHEET)
    IMAGES.mkdir(exist_ok=True)

    tab = make_tab(app, ext_lo=False)
    use_suggested = "Use the Configuration Helper's suggested filter"

    # ---- the TX filter set by hand ----
    tx_box = checkbox(tab, use_suggested, 0)
    tx_box.setChecked(False)
    tab.tx_filter_control.apply(0x1C)
    pump(app, 0.3)
    group_of(tab.tx_filter_control).grab().save(str(IMAGES / "gui_tx_filter_manual.png"))
    tab.shutdown()

    # ---- external LO: the auto bias paused ----
    tab = make_tab(app, ext_lo=True)
    group_of(tab.iq_auto_checkbox).grab().save(str(IMAGES / "gui_lo_suppr_extlo.png"))
    tab.shutdown()
    print("wrote images/gui_tx_filter_manual.png, gui_lo_suppr_extlo.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
