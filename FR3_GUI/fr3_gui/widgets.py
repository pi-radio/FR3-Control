"""Small reusable input widgets shared by DeviceTab's sections."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QWidget,
)

from .am3153_filter import FILTER_BANKS

VOLT_MIN = -0.5
VOLT_MAX = 0.5
VOLT_STEP = 0.0001  # 100uV
VOLT_SLIDER_STEPS = round((VOLT_MAX - VOLT_MIN) / VOLT_STEP)  # 10000
DEBOUNCE_MS = 150

# Bit layout matches rf_filter.h exactly: MSB to LSB, VA down to V0.
FILTER_BITS = (("VA", 0x20), ("VB", 0x10), ("V3", 0x08), ("V2", 0x04), ("V1", 0x02), ("V0", 0x01))


class VoltageControl(QWidget):
    """A linear slider plus a numeric spin box, kept in sync, sending at
    most one command per DEBOUNCE_MS while the slider is being dragged."""

    value_changed = Signal(float)  # emitted on every commit - drag-settled or apply()

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self._populating = False

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, VOLT_SLIDER_STEPS)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(VOLT_MIN, VOLT_MAX)
        self.spin.setDecimals(4)
        self.spin.setSingleStep(VOLT_STEP)
        self.spin.setSuffix(" V")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.slider, stretch=1)
        layout.addWidget(self.spin)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._commit)

        self.slider.valueChanged.connect(self._slider_changed)
        self.spin.valueChanged.connect(self._spin_changed)

    def set_value(self, volts: float) -> None:
        self._populating = True
        try:
            self.spin.setValue(volts)
            self.slider.setValue(round((volts - VOLT_MIN) / VOLT_STEP))
        finally:
            self._populating = False

    def apply(self, volts: float) -> None:
        """Like set_value(), but commits immediately instead of waiting for
        the drag debounce - for a caller applying a suggested value."""
        self.set_value(volts)
        self._debounce.stop()
        self._commit()

    def _slider_changed(self, steps: int) -> None:
        if self._populating:
            return
        volts = VOLT_MIN + steps * VOLT_STEP
        self._populating = True
        try:
            self.spin.setValue(volts)
        finally:
            self._populating = False
        self._debounce.start()

    def _spin_changed(self, volts: float) -> None:
        if self._populating:
            return
        self._populating = True
        try:
            self.slider.setValue(round((volts - VOLT_MIN) / VOLT_STEP))
        finally:
            self._populating = False
        self._debounce.start()

    def _commit(self) -> None:
        self._on_change(self.spin.value())
        self.value_changed.emit(self.spin.value())


class HexSpinBox(QSpinBox):
    """QSpinBox's own hex display (setDisplayIntegerBase(16)) renders
    lowercase (e.g. "0xe") with no way to configure that - override the
    text conversion to force uppercase digits."""

    def textFromValue(self, value: int) -> str:
        # Qt wraps this with prefix()/suffix() itself - don't add them here too.
        return f"{value:X}"

    def valueFromText(self, text: str) -> int:
        text = text.strip()
        if text.startswith(self.prefix()):
            text = text[len(self.prefix()):]
        if self.suffix() and text.endswith(self.suffix()):
            text = text[: -len(self.suffix())]
        return int(text, 16)


class BankConfigFilterControl(QWidget):
    """Bank + Configuration selectors for an AM3153 filter, in place of raw
    hex entry: Bank picks VA/VB (upper nibble), Configuration picks V3-V0
    (lower nibble, 0x0-0xF) - disabled when Bypass is selected, since it's
    a don't-care in that case."""

    value_changed = Signal(int)

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self._populating = False

        self.bank_combo = QComboBox()
        for name, _ in FILTER_BANKS:
            self.bank_combo.addItem(name)
        self.bank_combo.currentIndexChanged.connect(self._commit)

        self.config_spin = HexSpinBox()
        self.config_spin.setRange(0, 15)
        self.config_spin.setPrefix("0x")
        self.config_spin.valueChanged.connect(self._commit)

        self.bit_readout = QLabel()
        self.bit_readout.setStyleSheet("font-family: monospace; color: #444;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Bank:"))
        layout.addWidget(self.bank_combo)
        layout.addWidget(QLabel("Configuration:"))
        layout.addWidget(self.config_spin)
        layout.addSpacing(16)
        layout.addWidget(self.bit_readout)
        layout.addStretch(1)

        self._refresh()

    def _current_value(self) -> int:
        bank_nibble = FILTER_BANKS[self.bank_combo.currentIndex()][1]
        return (bank_nibble << 4) | self.config_spin.value()

    def value(self) -> int:
        return self._current_value()

    def set_value(self, bits: int) -> None:
        self._populating = True
        try:
            bank_nibble = (bits >> 4) & 0x0F
            for index, (_, nibble) in enumerate(FILTER_BANKS):
                if nibble == bank_nibble:
                    self.bank_combo.setCurrentIndex(index)
                    break
            self.config_spin.setValue(bits & 0x0F)
        finally:
            self._populating = False
        self._refresh()

    def apply(self, bits: int) -> None:
        """Like set_value(), but actually commits - for a caller (e.g.
        "Suggest Filter") applying a chosen configuration."""
        bank_nibble = (bits >> 4) & 0x0F
        for index, (_, nibble) in enumerate(FILTER_BANKS):
            if nibble == bank_nibble:
                self.bank_combo.setCurrentIndex(index)
                break
        self.config_spin.setValue(bits & 0x0F)

    def _refresh(self) -> None:
        is_bypass = self.bank_combo.currentIndex() == 0
        self.config_spin.setEnabled(not is_bypass)

        value = self._current_value()
        parts = [f"{name}:{1 if (value & mask) else 0}" for name, mask in FILTER_BITS]
        self.bit_readout.setText(" ".join(parts))
        self.value_changed.emit(value)

    def _commit(self) -> None:
        self._refresh()
        if self._populating:
            return
        self._on_change(self._current_value())
