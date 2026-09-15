"""One tab's UI for a single connected board. Reacts to DeviceWorker
signals only - never touches the serial port directly. The _populating
flag on each widget guards against re-sending a command while it's being
set programmatically (e.g. auto-populate)."""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .configuration_helper import ConfigurationHelper
from .discovery import DeviceInfo
from .lmx_register_dialog import LmxRegisterDialog
from .lo_suppression import suggest_iv_qv
from .widgets import BankConfigFilterControl, VoltageControl
from .worker import DeviceWorker

logger = logging.getLogger(__name__)

LOCK_COLORS = {
    "LOCKED": "#1a7f1a",
    "UNLOCKED": "#a01414",
    "INVALID": "#c47f00",
}

# Brand color RAL 1018 (#F8F32B) is too light for borders/text on this UI's
# background, so this darker shade of the same hue is used instead.
BRAND_YELLOW_DARK = "#8C7B00"

# App-wide (see main.py). Plain QGroupBox = light card look. #section
# (the 3 top-level Clocking and LO / TX / RX boxes) gets a bolder border.
STYLE_SHEET = f"""
QGroupBox {{
    font-weight: bold;
    border: 1px solid #c0c0c0;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
}}
QGroupBox#section {{
    border: 2px solid {BRAND_YELLOW_DARK};
    border-radius: 8px;
    margin-top: 0px;
    padding-top: 12px;
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: #d0d0d0;
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: #d0d0d0;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {BRAND_YELLOW_DARK};
    border: 1px solid #5c5000;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
"""


class DeviceTab(QWidget):
    def __init__(self, info: DeviceInfo, parent=None):
        super().__init__(parent)
        self.tab_key = info.tab_key
        self._info = info
        self._caps = info.capabilities
        self._populating = False
        self._register_dialog: LmxRegisterDialog | None = None

        self.worker = DeviceWorker(info.device, info.capabilities)
        self.worker.values_read.connect(self._apply_snapshot)
        self.worker.lock_status_changed.connect(self._update_lock_status)
        self.worker.lmx_temperature_changed.connect(self._update_lmx_temperature)
        self.worker.command_error.connect(self._show_error)
        self.worker.connection_lost.connect(self._on_connection_lost)
        self.worker.start()

        outer = QVBoxLayout(self)
        self._header = self._build_header()
        outer.addWidget(self._header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setSpacing(24)

        # Built Clocking/LO first (Configuration Helper needs its widgets)
        # but added to the layout in the opposite order - the helper
        # belongs at the top visually.
        clocking_lo_section = None
        if self._caps.has_lmx2820 or self._caps.has_clock_switch or self._caps.has_lo_switch:
            clocking_lo_section = self._build_clocking_lo_section()
        configuration_helper_section = None
        if self._caps.has_lmx2820 and self._caps.has_iq_swap and self._caps.has_lo_switch:
            configuration_helper_section = self._build_configuration_helper_section()
        tx_section = None
        if self._caps.has_ltc2668 or self._caps.has_rf_filters:
            tx_section = self._build_tx_section()
        rx_section = self._build_rx_section() if self._caps.has_rf_filters else None

        if configuration_helper_section is not None:
            content_layout.addWidget(configuration_helper_section)
        if clocking_lo_section is not None:
            content_layout.addWidget(clocking_lo_section)
        if tx_section is not None:
            content_layout.addWidget(tx_section)
        if rx_section is not None:
            content_layout.addWidget(rx_section)

        content_layout.addStretch(1)
        scroll.setWidget(self._content)
        outer.addWidget(scroll, stretch=1)

        self.worker.request_snapshot()

    def natural_size(self) -> QSize:
        """Size needed to show this tab's header + full content with no
        scrolling - used by MainWindow to size the window at startup."""
        header_hint = self._header.sizeHint()
        content_hint = self._content.sizeHint()
        margins = self.layout().contentsMargins()
        width = max(header_hint.width(), content_hint.width()) + margins.left() + margins.right()
        height = header_hint.height() + content_hint.height() + margins.top() + margins.bottom()
        return QSize(width, height)

    def shutdown(self) -> None:
        logger.info("Tab shutting down: %s", self.tab_key)
        if self._register_dialog is not None:
            self._register_dialog.close()
        self.worker.stop()
        if not self.worker.wait(2000):
            logger.warning("Worker for %s did not stop within 2s", self.tab_key)

    # ---- header ----

    def _build_header(self) -> QWidget:
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 8)

        title = QLabel(
            f"<b>Hardware:</b> {self._info.board_name} (Rev {self._info.revision}). "
            f"<b>Serial Number:</b> {self._info.serial_number}. "
            f"<b>Port:</b> {self._info.port_name}."
        )

        # A plain colored circle widget, not a text glyph: a large Unicode
        # "●" character's font metrics don't vertically center against
        # small text the way a real geometric shape does.
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(14, 14)
        self.status_dot.setStyleSheet("background-color: #1a7f1a; border-radius: 7px;")
        self.status_text = QLabel("Connected")
        self.status_text.setStyleSheet("color: #1a7f1a; font-weight: bold;")

        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(self.status_dot, 0, Qt.AlignVCenter)
        layout.addWidget(self.status_text, 0, Qt.AlignVCenter)
        return box

    def _on_connection_lost(self) -> None:
        self.status_dot.setStyleSheet("background-color: #a01414; border-radius: 7px;")
        self.status_text.setStyleSheet("color: #a01414; font-weight: bold;")
        self.status_text.setText("Disconnected")
        self.setEnabled(False)

    def _show_error(self, message: str) -> None:
        self.status_text.setText(message)

    # ---- top-level sections ----

    def _build_section(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        """Heading button above a plain group box, collapsible by clicking
        it - starts expanded. A QToolButton rather than QGroupBox's own
        title: Qt's native Windows style ignores font-size/weight on
        QGroupBox::title, and a plain QLabel can't be clicked."""
        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        section = QGroupBox()
        section.setObjectName("section")
        layout = QVBoxLayout(section)
        layout.setSpacing(10)

        toggle_button = QToolButton()
        toggle_button.setCheckable(True)
        toggle_button.setChecked(True)
        toggle_button.setCursor(Qt.PointingHandCursor)
        toggle_button.setStyleSheet(
            "QToolButton {"
            "    border: none;"
            "    background: transparent;"
            "    padding: 0;"
            f"    font-size: 13pt; font-weight: bold; color: {BRAND_YELLOW_DARK};"
            "}"
        )

        def update_arrow(expanded: bool) -> None:
            toggle_button.setText(f"{'▼' if expanded else '▶'}  {title}")

        update_arrow(True)
        toggle_button.toggled.connect(update_arrow)
        toggle_button.toggled.connect(section.setVisible)

        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(0, 0, 0, 0)
        heading_row.addWidget(toggle_button)
        heading_row.addStretch(1)
        outer.addLayout(heading_row)
        outer.addWidget(section)

        return wrapper, layout

    def _build_clocking_lo_section(self) -> QWidget:
        section, layout = self._build_section("Clocking and LO")
        if self._caps.has_lmx2820:
            layout.addWidget(self._build_lmx_group())
        if self._caps.has_clock_switch:
            layout.addWidget(self._build_clock_group())
        if self._caps.has_lo_switch:
            layout.addWidget(self._build_lo_group())
        if self._caps.has_clock_switch and self._caps.has_lo_switch:
            self._align_internal_radio_widths()
        return section

    def _align_internal_radio_widths(self) -> None:
        """Widens the narrower "Internal" radio so both groups' "External"
        options start at the same horizontal position."""
        def text_width(radio: QRadioButton) -> int:
            return radio.fontMetrics().boundingRect(radio.text()).width()

        target = max(text_width(self.clock_int_radio), text_width(self.lo_int_radio)) + 30
        self.clock_int_radio.setMinimumWidth(target)
        self.lo_int_radio.setMinimumWidth(target)

    def _build_configuration_helper_section(self) -> QWidget:
        section, layout = self._build_section("Configuration Helper")
        self.configuration_helper = ConfigurationHelper(
            self._set_freq_display, self.lo_int_radio, self.external_lo_value_label,
            self.worker, self.tab_key, self._caps.has_rf_filters,
            is_populating=lambda: self._populating,
            on_lo_tuned=self._maybe_auto_suggest_iv_qv if self._caps.has_ltc2668 else None,
        )
        layout.addWidget(self.configuration_helper)
        return section

    def _build_tx_section(self) -> QWidget:
        section, layout = self._build_section("TX Settings")
        if self._caps.has_ltc2668:
            layout.addWidget(self._build_dac_group())
        if self._caps.has_rf_filters:
            layout.addWidget(self._build_tx_filter_group())
        return section

    def _build_rx_section(self) -> QGroupBox:
        section, layout = self._build_section("RX Settings")
        layout.addWidget(self._build_rx_filter_group())
        return section

    # ---- LMX2820 ----

    def _build_lmx_group(self) -> QGroupBox:
        group = QGroupBox("Local Oscillator (LMX2820)")
        self.lmx_group = group
        form = QFormLayout(group)

        self._freq_ghz = 6.0
        if self._caps.has_iq_swap:
            # Configuration Helper computes and applies this instead - a
            # plain read-only display here (no white box - matches
            # "Desired External LO Frequency" under LO Source), not
            # something to type into directly.
            self.freq_spin = None
            self.freq_display_label = QLabel("6.000000 GHz")
            form.addRow("<b>Frequency</b>", self.freq_display_label)
        else:
            # No Configuration Helper on this board - directly tunable.
            self.freq_spin = QDoubleSpinBox()
            self.freq_spin.setRange(6.0, 22.6)
            self.freq_spin.setDecimals(6)
            self.freq_spin.setSuffix(" GHz")
            self.freq_spin.setSingleStep(0.001)
            # editingFinished fires on Enter or focus loss - no Tune button.
            self.freq_spin.editingFinished.connect(self._tune_clicked)
            form.addRow("<b>Frequency</b>", self.freq_spin)

        self.power_spin = QSpinBox()
        self.power_spin.setRange(0, 7)
        self.power_spin.valueChanged.connect(self._power_changed)
        form.addRow("<b>LO Power/Drive (0-7)</b>", self.power_spin)

        power_hint = QLabel("Recommended value: 7")
        power_hint.setStyleSheet("color: gray;")
        form.addRow("", power_hint)

        self.power_on_radio = QRadioButton("Powered On")
        self.power_off_radio = QRadioButton("Powered Off")
        self.power_on_radio.toggled.connect(self._power_state_changed)
        power_row = QHBoxLayout()
        power_row.addWidget(self.power_on_radio)
        power_row.addWidget(self.power_off_radio)
        power_row.addStretch(1)
        power_row_widget = QWidget()
        power_row_widget.setLayout(power_row)
        form.addRow("", power_row_widget)

        self.lock_label = QLabel("UNKNOWN")
        self.lock_label.setStyleSheet("font-weight: bold;")
        form.addRow("<b>Lock status</b>", self.lock_label)

        self.temp_label = QLabel("—")
        self.temp_label.setToolTip(
            "Approximate - LMX2820's own sensor is accurate to only "
            "±5°C per datasheet (see README.md Section 6)."
        )
        form.addRow("<b>Temperature</b>", self.temp_label)

        registers_button = QPushButton("Read LMX Registers...")
        registers_button.setAutoDefault(False)
        registers_button.setDefault(False)
        registers_button.clicked.connect(self._open_register_dialog)
        form.addRow("", registers_button)

        return group

    def _set_freq_display(self, freq_ghz: float) -> None:
        """Single writer for the LMX2820 'Frequency' display - the
        read-only label (Configuration Helper present) or the directly
        tunable spin box (no Configuration Helper on this board). Also
        keeps _freq_ghz in sync for _get_freq_ghz()'s sake, since the
        label case has no .value() to read back."""
        self._freq_ghz = freq_ghz
        if self._caps.has_iq_swap:
            self.freq_display_label.setText(f"{freq_ghz:.6f} GHz")
        else:
            self.freq_spin.setValue(freq_ghz)

    def _get_freq_ghz(self) -> float:
        if self._caps.has_iq_swap:
            return self._freq_ghz
        return self.freq_spin.value()

    def _open_register_dialog(self) -> None:
        if self._register_dialog is None:
            self._register_dialog = LmxRegisterDialog(self.worker, self)
            self._register_dialog.finished.connect(self._on_register_dialog_closed)
            self._register_dialog.show()
        else:
            self._register_dialog.raise_()
            self._register_dialog.activateWindow()

    def _on_register_dialog_closed(self) -> None:
        self._register_dialog = None

    def _tune_clicked(self) -> None:
        freq_hz = self.freq_spin.value() * 1e9
        self.worker.submit("lmx_tune", freq_hz)

    def _power_changed(self, value: int) -> None:
        if self._populating:
            return
        self.worker.submit("set_lmx_power", value)

    def _power_state_changed(self, checked: bool) -> None:
        # Only "Powered On" is connected; checked reflects which is selected.
        # mute is the inverse of "powered on".
        if self._populating:
            return
        self.worker.submit("set_lmx_mute", not checked)

    def _update_lock_status(self, status: str) -> None:
        self.lock_label.setText(status)
        color = LOCK_COLORS.get(status, "black")
        self.lock_label.setStyleSheet(f"font-weight: bold; color: {color};")

    def _update_lmx_temperature(self, temperature_c: float) -> None:
        self.temp_label.setText(f"{temperature_c:.1f} °C")

    # ---- LTC2668 ----

    def _build_dac_group(self) -> QGroupBox:
        group = QGroupBox("I/Q DAC (LTC2668): Bias Voltages for LO Suppression")
        form = QFormLayout(group)

        self.i_v_control = VoltageControl(lambda v: self.worker.submit("set_i_v", v))
        self.q_v_control = VoltageControl(lambda v: self.worker.submit("set_q_v", v))
        form.addRow("I_V", self.i_v_control)
        form.addRow("Q_V", self.q_v_control)

        suggest_row = QHBoxLayout()
        self.suggest_iv_qv_button = QPushButton("Suggest I_V and Q_V")
        self.suggest_iv_qv_button.setAutoDefault(False)
        self.suggest_iv_qv_button.setDefault(False)
        self.suggest_iv_qv_button.clicked.connect(self._suggest_iv_qv)
        self.suggest_iv_qv_result_label = QLabel()
        suggest_row.addWidget(self.suggest_iv_qv_button)
        suggest_row.addWidget(self.suggest_iv_qv_result_label)
        suggest_row.addStretch(1)
        suggest_row_widget = QWidget()
        suggest_row_widget.setLayout(suggest_row)
        form.addRow("", suggest_row_widget)

        self.auto_iv_qv_checkbox = QCheckBox("Automatically set I_V and Q_V")
        # Set before connecting toggled, so this initial default doesn't
        # itself trigger a suggestion/apply before the board's own snapshot
        # has even arrived.
        self.auto_iv_qv_checkbox.setChecked(True)
        self.auto_iv_qv_checkbox.toggled.connect(self._on_auto_iv_qv_toggled)
        form.addRow("", self.auto_iv_qv_checkbox)
        self._update_suggest_iv_qv_availability()
        # I_V/Q_V are only manually editable when "Automatically set" isn't
        # handling them - matches the checkbox's own default state above.
        self.i_v_control.setEnabled(not self.auto_iv_qv_checkbox.isChecked())
        self.q_v_control.setEnabled(not self.auto_iv_qv_checkbox.isChecked())

        # Re-applies the suggestion whenever the LO is actually retuned, so
        # "automatic" mode doesn't go stale after the user changes frequency.
        # Only wired when freq_spin is the directly-tunable spin box (no
        # Configuration Helper) - with one, its own on_lo_tuned callback
        # already covers this after every auto-tune.
        if not self._caps.has_iq_swap:
            self.freq_spin.editingFinished.connect(self._maybe_auto_suggest_iv_qv)

        self._suppress_iv_qv_label_update = False
        self.i_v_control.value_changed.connect(self._on_iv_qv_manually_changed)
        self.q_v_control.value_changed.connect(self._on_iv_qv_manually_changed)

        return group

    def _update_suggest_iv_qv_availability(self) -> None:
        """Suggest/auto I_V-Q_V are only meaningful with the internal
        LMX2820 in use; the manual button is further disabled whenever
        "Automatically set" is handling it instead."""
        lo_internal = self.lo_int_radio.isChecked()
        self.auto_iv_qv_checkbox.setEnabled(lo_internal)
        self.suggest_iv_qv_button.setEnabled(lo_internal and not self.auto_iv_qv_checkbox.isChecked())

    def _on_auto_iv_qv_toggled(self, checked: bool) -> None:
        self._update_suggest_iv_qv_availability()
        self.i_v_control.setEnabled(not checked)
        self.q_v_control.setEnabled(not checked)
        if checked:
            self._suggest_iv_qv()

    def _maybe_auto_suggest_iv_qv(self) -> None:
        if self.auto_iv_qv_checkbox.isChecked():
            self._suggest_iv_qv()

    def _on_iv_qv_manually_changed(self, _value: float) -> None:
        # Also fires for _suggest_iv_qv()'s own apply() calls; skip
        # clearing the label there since it just set its own message.
        if self._suppress_iv_qv_label_update:
            return
        self.suggest_iv_qv_result_label.setText("")

    def _suggest_iv_qv(self) -> None:
        """Only meaningful with the internal LMX2820 (button is disabled
        otherwise - see _lo_changed). Below the calibration table's range,
        suggest_iv_qv() returns None and I_V/Q_V are left untouched."""
        freq_ghz = self._get_freq_ghz()
        suggestion = suggest_iv_qv(freq_ghz)
        if suggestion is None:
            self.suggest_iv_qv_result_label.setText("Use High-side LO and Lower Sideband")
            return
        i_v, q_v = suggestion
        self._suppress_iv_qv_label_update = True
        try:
            self.i_v_control.apply(i_v)
            self.q_v_control.apply(q_v)
        finally:
            self._suppress_iv_qv_label_update = False
        self.suggest_iv_qv_result_label.setText(f"Applied: I_V={i_v:.4f} V, Q_V={q_v:.4f} V")

    # ---- Clock source ----

    def _build_clock_group(self) -> QGroupBox:
        group = QGroupBox("Clock Source")
        self.clock_group = group
        layout = QHBoxLayout(group)
        self.clock_int_radio = QRadioButton("Internal: 10 MHz TCXO")
        self.clock_ext_radio = QRadioButton("External: 10 MHz REFCLK IN (SMA)")
        self.clock_int_radio.toggled.connect(self._clock_changed)
        layout.addWidget(self.clock_int_radio)
        layout.addWidget(self.clock_ext_radio)
        layout.addStretch(1)
        return group

    def _build_lo_group(self) -> QGroupBox:
        group = QGroupBox("LO Source")
        layout = QHBoxLayout(group)
        self.lo_int_radio = QRadioButton("Internal: LMX2820 PLL/VCO")
        self.lo_ext_radio = QRadioButton("External: LO IN (SMA)")
        self.lo_int_radio.toggled.connect(self._lo_changed)
        layout.addWidget(self.lo_int_radio)
        layout.addWidget(self.lo_ext_radio)

        layout.addSpacing(20)
        self.external_lo_label = QLabel("Desired External LO Frequency:")
        layout.addWidget(self.external_lo_label)
        # Plain text, not an editable control - computed by
        # ConfigurationHelper from FR1/FR3/sideband, not an independent
        # input; this just tells the user what to feed in.
        self.external_lo_value_label = QLabel("10.000000 GHz")
        self.external_lo_value_label.setEnabled(False)
        self.external_lo_label.setEnabled(False)  # Internal is the typical default state
        layout.addWidget(self.external_lo_value_label)

        layout.addStretch(1)
        return group

    def _clock_changed(self, checked: bool) -> None:
        # Only "Internal" is connected; checked reflects which is selected.
        if self._populating:
            return
        self.worker.submit("set_clock_internal", checked)

    def _lo_changed(self, checked: bool) -> None:
        # With an external LO, the internal LMX2820 and the reference clock
        # feeding it are both unused - grey them out. Runs even during
        # snapshot restore (_populating), so a restored "External" state is
        # reflected immediately without waiting for the user to touch it.
        self.lmx_group.setEnabled(checked)
        self.clock_group.setEnabled(checked)
        self.external_lo_value_label.setEnabled(not checked)
        self.external_lo_label.setEnabled(not checked)
        # Suggest/auto I_V-Q_V calibrate out the internal LMX2820's own LO
        # leakage - meaningless (and disabled) with an external LO in use.
        self._update_suggest_iv_qv_availability()

        if self._populating:
            return
        self.worker.submit("set_lo_internal", checked)

    # ---- RF filters ----

    def _build_tx_filter_group(self) -> QGroupBox:
        group = QGroupBox("TX Filter")
        form = QFormLayout(group)
        self.tx_filter_control = BankConfigFilterControl(lambda v: self.worker.submit("set_tx_filter", v))
        form.addRow("", self.tx_filter_control)
        form.addRow("", self._build_use_suggested_filter_column(self.tx_filter_control))
        return group

    def _build_rx_filter_group(self) -> QGroupBox:
        group = QGroupBox("RX Filter")
        form = QFormLayout(group)
        self.rx_filter_control = BankConfigFilterControl(lambda v: self.worker.submit("set_rx_filter", v))
        form.addRow("", self.rx_filter_control)
        form.addRow("", self._build_use_suggested_filter_column(self.rx_filter_control))
        return group

    def _build_use_suggested_filter_column(self, filter_control: BankConfigFilterControl) -> QWidget:
        """Shared by the TX/RX filter groups: while checked, keeps
        filter_control synced to Configuration Helper's suggestion and
        greyed out; unchecking hands it back to manual control."""
        checkbox = QCheckBox("Automatically apply the Suggested Filter from the Configuration Helper")
        checkbox.setChecked(True)
        filter_control.setEnabled(False)

        def on_toggled(checked: bool) -> None:
            filter_control.setEnabled(not checked)
            if checked and self.configuration_helper.suggested_bits is not None:
                filter_control.apply(self.configuration_helper.suggested_bits)

        checkbox.toggled.connect(on_toggled)

        def on_suggested(bits: int) -> None:
            if checkbox.isChecked():
                filter_control.apply(bits)

        self.configuration_helper.filter_suggested.connect(on_suggested)

        column = QVBoxLayout()
        column.setSpacing(2)
        column.addWidget(checkbox)
        column_widget = QWidget()
        column_widget.setLayout(column)
        return column_widget

    # ---- snapshot / auto-populate ----

    def _apply_snapshot(self, values: dict) -> None:
        self._populating = True
        try:
            if "lmx_freq_hz" in values:
                self._set_freq_display(values["lmx_freq_hz"] / 1e9)
            if "lmx_power" in values:
                self.power_spin.setValue(values["lmx_power"])
            if "lmx_mute" in values:
                is_muted = values["lmx_mute"]
                self.power_on_radio.setChecked(not is_muted)
                self.power_off_radio.setChecked(is_muted)
            if "lmx_lock" in values:
                self._update_lock_status(values["lmx_lock"])
            if "lmx_temperature_c" in values:
                self._update_lmx_temperature(values["lmx_temperature_c"])
            if "i_v" in values:
                self.i_v_control.set_value(values["i_v"])
            if "q_v" in values:
                self.q_v_control.set_value(values["q_v"])
            if "clock_internal" in values:
                self.clock_int_radio.setChecked(values["clock_internal"])
                self.clock_ext_radio.setChecked(not values["clock_internal"])
            if "lo_internal" in values:
                self.lo_int_radio.setChecked(values["lo_internal"])
                self.lo_ext_radio.setChecked(not values["lo_internal"])
            if "iq_swap" in values:
                self.configuration_helper.lower_sideband_radio.setChecked(values["iq_swap"])
                self.configuration_helper.upper_sideband_radio.setChecked(not values["iq_swap"])
            if "tx_filter" in values:
                self.tx_filter_control.set_value(values["tx_filter"])
                self.configuration_helper.seed_display_filter(values["tx_filter"])
            if "rx_filter" in values:
                self.rx_filter_control.set_value(values["rx_filter"])
        finally:
            self._populating = False
