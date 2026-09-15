"""Configuration Helper: from the desired FR1 (IF) frequency, FR3 (RF)
frequency, and sideband, computes and auto-tunes the LMX2820 frequency that
produces that FR3 output.

When RF filters are present, also plots the desired/undesired sideband and
LO leakage positions against a candidate filter's measured S21, and offers
"Suggest Filter". The suggestion is board-wide, not TX/RX-specific: it's
published via the filter_suggested signal / suggested_bits attribute for
TX/RX Settings to apply on their own ("Use Suggested Filter") - this widget
never drives TX/RX filter hardware itself.

FR1, FR3, and sideband are always live inputs, regardless of LO source.
With the internal LO, they drive the LMX2820 auto-tune as usual. With an
external LO, there's no synthesizer to solve for - instead, the required
LO frequency is computed the same way and shown as plain text in
external_lo_value_label (owned by the LO Source group), telling the user
what to feed in. It's never itself an independent input.

Sideband/LO levels on the graph are illustrative only; the filter S21 is
real measured data (am3153_filter.py), plotted raw and normalized.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .am3153_filter import FILTER_BANKS, get_response
from .local_settings import load_tx_helper_inputs, save_tx_helper_inputs
from .widgets import SteppedDoubleSpinBox
from .worker import DeviceWorker

# Max matches the LMX2820 hardware/firmware's own tuning ceiling
# (LMX_FREQ_MAX_HZ in board_config.h). Min is a stricter GUI-enforced
# floor above the hardware's actual 6.0GHz limit - applies to both
# Internal (auto-tune) and External (informational display) LO, since
# it's a floor on the requested LO frequency itself, not a chip capability
# check. A computed LO frequency outside [MIN, MAX] can't be applied.
LMX_FREQ_MIN_HZ = 7.0e9
LMX_FREQ_MAX_HZ = 22.6e9

Y_MIN_DB = -50.0
Y_MAX_DB = 0.0
# Headroom above/below the 0dB/-50dB tick marks, so their labels have room
# to render fully instead of being half-clipped at the plot's edge - the
# desired/undesired rectangles extend all the way down to this true bottom
# edge (not just to Y_MIN_DB), so they visually reach the bottom of the
# plot with no gap underneath them.
Y_VIEW_PADDING_DB = 2.0
Y_VIEW_BOTTOM_DB = Y_MIN_DB - Y_VIEW_PADDING_DB
Y_VIEW_TOP_DB = Y_MAX_DB + Y_VIEW_PADDING_DB

DESIRED_TOP_DB = Y_MAX_DB
DESIRED_BOTTOM_DB = Y_VIEW_BOTTOM_DB
UNDESIRED_TOP_DB = -15.0
UNDESIRED_BOTTOM_DB = Y_VIEW_BOTTOM_DB
LO_TOP_DB = Y_MAX_DB
LO_BOTTOM_DB = Y_MIN_DB

# Mixer's own sideband suppression before any filtering (matches the
# graph's desired/undesired gap). Added to every rejection score on top of
# the filter's own S21 difference between the two bands.
BASELINE_SUPPRESSION_DB = DESIRED_TOP_DB - UNDESIRED_TOP_DB

# Minimum desired/undesired rejection (dB, baseline included) for
# "Suggest Filter" to consider a configuration qualified.
MIN_REJECTION_DB = 40.0


class _NoWheelZoomPlotWidget(pg.PlotWidget):
    """A plain PlotWidget, except mouse-wheel scroll does nothing (instead
    of pyqtgraph's default zoom) - this graph sits in a scrollable settings
    panel, so scrolling over it while reading values shouldn't zoom it.
    Overridden at the widget level (the real wheel event's first point of
    entry), not on the ViewBox - pyqtgraph's own GraphicsView base class
    handles wheel-zoom itself before a ViewBox-level override ever sees it."""

    def wheelEvent(self, ev):
        ev.ignore()


def _rect_outline(x0: float, x1: float, y0: float, y1: float, color: str, name: str) -> pg.PlotDataItem:
    """3 sides only; omits the bottom edge, which sits on the frequency
    axis and would just overdraw it."""
    return pg.PlotDataItem(
        x=[x0, x0, x1, x1], y=[y0, y1, y1, y0],
        pen=pg.mkPen(color, width=4), name=name,
    )


def _hatched_fill(x0: float, x1: float, y0: float, y1: float, color: str) -> pg.BarGraphItem:
    brush = QBrush(QColor(color))
    brush.setStyle(Qt.BDiagPattern)
    return pg.BarGraphItem(x0=[x0], x1=[x1], y0=[y0], y1=[y1], brush=brush, pen=pg.mkPen(None))


def _band_mean_power(response, lo_hz: float, hi_hz: float) -> float:
    """Mean linear power over [lo_hz, hi_hz]. S21 dB is voltage-ratio dB,
    so 10**(dB/10) gives a power ratio; the mean (not sum) is independent
    of how many measurement points fall in the window."""
    mask = (response.freq_hz >= lo_hz) & (response.freq_hz <= hi_hz)
    if not np.any(mask):
        return 0.0
    return float(np.mean(10.0 ** (response.s21_db[mask] / 10.0)))


REJECTION_DISPLAY_CAP_DB = 50.0
POOR_REJECTION_WARNING_DB = 20.0


def _format_rejection(rejection_db: float) -> str:
    """Caps the displayed value above REJECTION_DISPLAY_CAP_DB (avoids
    implying false precision) and flags anything below
    POOR_REJECTION_WARNING_DB, including negative rejection."""
    if rejection_db > REJECTION_DISPLAY_CAP_DB:
        text = f"rejection > {REJECTION_DISPLAY_CAP_DB:.0f}dB"
    else:
        text = f"rejection: {rejection_db:.1f} dB"
    if rejection_db < POOR_REJECTION_WARNING_DB:
        text += ". Warning: Poor sideband rejection"
    return text


class ConfigurationHelper(QWidget):
    # Emitted with the new suggested_bits whenever "Suggest Filter" runs -
    # TX/RX Settings' own "Use Suggested Filter" buttons listen for this
    # rather than owning any filter-suggestion logic themselves.
    filter_suggested = Signal(int)

    def __init__(
        self,
        set_freq_display: Callable[[float], None],
        lo_int_radio: QRadioButton,
        external_lo_value_label: QLabel,
        worker: DeviceWorker,
        tab_key: str,
        has_rf_filters: bool,
        is_populating: Callable[[], bool],
        on_lo_tuned: Optional[Callable[[], None]] = None,
        parent=None,
    ):
        super().__init__(parent)
        # set_freq_display (freq_ghz) writes the LMX2820 group's own
        # "Frequency" display - owned by the device tab, not this section,
        # since that board might not even have a Configuration Helper
        # (freq_spin is then directly tunable instead of a read-only
        # display, which this section has no business knowing about).
        # external_lo_value_label is owned by the LO Source group and only
        # read/written here - a plain, non-interactive label; this section
        # is the only writer of its text.
        self._set_freq_display = set_freq_display
        self._lo_int_radio = lo_int_radio
        self._external_lo_value_label = external_lo_value_label
        self._worker = worker
        self._tab_key = tab_key
        self._has_rf_filters = has_rf_filters
        self._is_populating = is_populating
        self._on_lo_tuned = on_lo_tuned
        self.suggested_bits: Optional[int] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        self.fr1_spin = SteppedDoubleSpinBox()
        self.fr1_spin.setRange(1.0, 4.0)
        self.fr1_spin.setDecimals(3)
        self.fr1_spin.setSuffix(" GHz")
        self.fr1_spin.setSingleStep(0.5)
        self.fr1_spin.setValue(2.0)
        form.addRow("<b>FR1 Frequency</b>", self.fr1_spin)

        self.fr3_spin = SteppedDoubleSpinBox()
        self.fr3_spin.setRange(5.5, 27.0)  # 5.5GHz inclusive is the floor
        self.fr3_spin.setDecimals(3)
        self.fr3_spin.setSuffix(" GHz")
        self.fr3_spin.setSingleStep(0.5)
        self.fr3_spin.setValue(10.0)
        form.addRow("<b>FR3 Frequency</b>", self.fr3_spin)

        self.bw_spin = QDoubleSpinBox()
        self.bw_spin.setRange(0.1, 1.0)
        self.bw_spin.setDecimals(3)
        self.bw_spin.setSuffix(" GHz")
        self.bw_spin.setSingleStep(0.1)
        self.bw_spin.setValue(0.5)
        form.addRow("<b>Signal Bandwidth</b>", self.bw_spin)

        self.upper_sideband_radio = QRadioButton("Upper Sideband (FR1 IQ Through)")
        self.lower_sideband_radio = QRadioButton("Lower Sideband (FR1 IQ Swap)")
        self.upper_sideband_radio.setChecked(True)
        sideband_row = QHBoxLayout()
        # Zeroed - a QHBoxLayout picks up the platform's default widget
        # margins once assigned to a widget, which otherwise pushes the
        # radios down relative to the label's own zero-margin text.
        sideband_row.setContentsMargins(0, 0, 0, 0)
        sideband_row.addWidget(self.upper_sideband_radio)
        sideband_row.addWidget(self.lower_sideband_radio)
        sideband_row.addStretch(1)
        sideband_row_widget = QWidget()
        sideband_row_widget.setLayout(sideband_row)
        form.addRow("TX-side Up-conversion Sideband", sideband_row_widget)
        outer.addLayout(form)

        # Per-machine, per-unit override of the defaults above, if present.
        saved_inputs = load_tx_helper_inputs(self._tab_key)
        if saved_inputs is not None:
            self.fr1_spin.setValue(saved_inputs[0])
            self.fr3_spin.setValue(saved_inputs[1])
            self.bw_spin.setValue(saved_inputs[2])

        # Seeded from whatever FR1/FR3 end up showing at startup (default or
        # restored above) - _on_fr1_fr3_committed() keeps this in sync with
        # the last combination that actually produced a valid LO frequency,
        # so an invalid attempt has something concrete to snap back to.
        self._last_valid_fr1_ghz = self.fr1_spin.value()
        self._last_valid_fr3_ghz = self.fr3_spin.value()

        self.lo_status_label = QLabel()
        self.lo_status_label.setStyleSheet("color: gray;")
        outer.addWidget(self.lo_status_label)

        if self._has_rf_filters:
            self._build_filter_ui(outer)

        self.fr1_spin.valueChanged.connect(self._save_inputs)
        self.fr3_spin.valueChanged.connect(self._save_inputs)
        self.bw_spin.valueChanged.connect(self._save_inputs)
        # editingFinished (typing, then Enter/focus-loss) and stepped
        # (arrow buttons/keys, applied immediately rather than waiting for
        # focus-loss) both retune - covering every way to change the value.
        # valueChanged alone would also fire, and retune, on every digit
        # while still typing a number.
        self.fr1_spin.editingFinished.connect(self._on_fr1_fr3_committed)
        self.fr3_spin.editingFinished.connect(self._on_fr1_fr3_committed)
        self.fr1_spin.stepped.connect(self._on_fr1_fr3_committed)
        self.fr3_spin.stepped.connect(self._on_fr1_fr3_committed)
        self.upper_sideband_radio.toggled.connect(self._on_sideband_toggled)
        self._lo_int_radio.toggled.connect(self._on_lo_source_changed)

        # external_lo_value_label (owned by the LO Source group) is a plain
        # text display - keep it live off FR1/FR3/sideband rather than
        # stuck at whatever it last showed.
        self.fr1_spin.valueChanged.connect(self._update_external_lo_display)
        self.fr3_spin.valueChanged.connect(self._update_external_lo_display)
        self._update_external_lo_display()

        if self._has_rf_filters:
            # fr1/fr3/bw feed the filter score directly - re-suggest on
            # change rather than just redrawing, when auto-select is on.
            # external_lo_value_label needs no listener of its own here -
            # it's a pure readout of fr1/fr3/sideband now, not an independent
            # input, so those three already cover it.
            self.fr1_spin.valueChanged.connect(self._on_scoring_input_changed)
            self.fr3_spin.valueChanged.connect(self._on_scoring_input_changed)
            self.bw_spin.valueChanged.connect(self._on_scoring_input_changed)
            self._redraw()

    def _build_filter_ui(self, outer: QVBoxLayout) -> None:
        suggest_row = QHBoxLayout()
        self.suggest_button = QPushButton("Suggest Filter")
        self.suggest_button.setAutoDefault(False)
        self.suggest_button.setDefault(False)
        self.suggest_button.clicked.connect(self._suggest_filter)
        self.suggest_result_label = QLabel()
        suggest_row.addWidget(self.suggest_button)
        suggest_row.addWidget(self.suggest_result_label)
        suggest_row.addStretch(1)
        outer.addLayout(suggest_row)

        self.auto_select_filter_checkbox = QCheckBox("Automatically Select Filter")
        # Set before connecting toggled, so this default doesn't itself
        # trigger a suggestion before the rest of the section even exists.
        self.auto_select_filter_checkbox.setChecked(True)
        self.auto_select_filter_checkbox.toggled.connect(self._on_auto_select_filter_toggled)
        outer.addWidget(self.auto_select_filter_checkbox)
        self.suggest_button.setEnabled(not self.auto_select_filter_checkbox.isChecked())

        self.plot = _NoWheelZoomPlotWidget()
        # Tall enough for the 5-row legend plus the plot itself - this
        # widget's own natural sizeHint is far too short to fit both.
        self.plot.setMinimumHeight(320)
        self.plot.setBackground(self.palette().color(QPalette.Window))
        self.plot.setLabel("bottom", "Frequency", units="Hz", color="black", **{"font-weight": "bold"})
        self.plot.setLabel("left", "Level (dB, illustrative)", color="black", **{"font-weight": "bold"})
        self.plot.getAxis("bottom").setTextPen("black")
        self.plot.getAxis("left").setTextPen("black")
        self.plot.getAxis("left").setTicks([[(v, str(int(v))) for v in range(0, int(Y_MIN_DB) - 1, -10)]])
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        # verSpacing tightened and offset raised - the default top offset
        # (30px) plus 5 legend rows can run the last row past the plot
        # widget's own visible bottom edge, making it effectively disappear.
        legend = self.plot.addLegend(offset=(30, 5), verSpacing=-5)
        legend.setLabelTextColor("black")
        # Exact bounds (not pyqtgraph's own fractional padding) so they
        # stay in lockstep with Y_VIEW_BOTTOM_DB/Y_VIEW_TOP_DB above, which
        # the desired/undesired rectangles also extend to.
        self.plot.setYRange(Y_VIEW_BOTTOM_DB, Y_VIEW_TOP_DB, padding=0)
        # Hides the "A" auto-range corner button - clicking it would fit the
        # view to every plotted item's full extent (the raw filter S21 data
        # spans well past this graph's intentional 6-30GHz/0 to -50dB window),
        # not just the current sideband/LO region.
        self.plot.hideButtons()
        outer.addWidget(self.plot)

    # ---- LO frequency computation/application ----

    def _compute_required_lo_hz(self) -> float:
        fr1_hz = self.fr1_spin.value() * 1e9
        fr3_hz = self.fr3_spin.value() * 1e9
        if self.upper_sideband_radio.isChecked():
            return fr3_hz - fr1_hz
        return fr3_hz + fr1_hz

    def _is_configuration_valid(self) -> bool:
        """False when the current FR1/FR3/sideband combination would
        require the LMX2820 to tune outside its valid range - the graph
        and filter suggestion freeze on the last valid configuration
        rather than plotting/scoring a frequency the hardware could never
        actually be at."""
        return LMX_FREQ_MIN_HZ <= self._compute_required_lo_hz() <= LMX_FREQ_MAX_HZ

    def _compute_alternate_sideband_lo_hz(self) -> float:
        """What _compute_required_lo_hz() would return with the sideband
        flipped - used to suggest a fix when the current sideband puts the
        required LO out of range."""
        fr1_hz = self.fr1_spin.value() * 1e9
        fr3_hz = self.fr3_spin.value() * 1e9
        if self.upper_sideband_radio.isChecked():
            return fr3_hz + fr1_hz
        return fr3_hz - fr1_hz

    def _apply_lo_frequency(self) -> None:
        """Tunes the LMX2820 per FR1/FR3/sideband. Only with the internal
        LO, and never during snapshot restore (that's the board's own
        already-applied state, not a fresh retune request)."""
        if self._is_populating() or not self._lo_int_radio.isChecked():
            return
        lo_hz = self._compute_required_lo_hz()
        if not (LMX_FREQ_MIN_HZ <= lo_hz <= LMX_FREQ_MAX_HZ):
            sideband_name = "Upper" if self.upper_sideband_radio.isChecked() else "Lower"
            # lo_status_label auto-detects HTML (same as the <b> labels
            # used throughout this file's QFormLayout rows) - no explicit
            # setTextFormat() needed for the bold section headers below.
            message = (
                f"<b>Requested:</b> FR1: {self.fr1_spin.value():.6f} GHz, "
                f"FR3: {self.fr3_spin.value():.6f} GHz, Sideband: {sideband_name}. "
                f"<b>Error:</b> The required LO frequency ({lo_hz / 1e9:.6f} GHz) is "
                f"outside the LMX2820's {LMX_FREQ_MIN_HZ / 1e9:.1f}-"
                f"{LMX_FREQ_MAX_HZ / 1e9:.1f}GHz range - not applied."
            )
            alt_lo_hz = self._compute_alternate_sideband_lo_hz()
            if LMX_FREQ_MIN_HZ <= alt_lo_hz <= LMX_FREQ_MAX_HZ:
                alt_name = "lower" if self.upper_sideband_radio.isChecked() else "upper"
                message += (
                    f" <b>Solution:</b> Try using the {alt_name} sideband instead "
                    f"(the required LO will be {alt_lo_hz / 1e9:.6f} GHz)."
                )
            self.lo_status_label.setText(message)
            return
        self._worker.submit("lmx_tune", lo_hz)
        self._set_freq_display(lo_hz / 1e9)
        self.lo_status_label.setText(f"LO Frequency: {lo_hz / 1e9:.6f} GHz (applied)")
        if self._on_lo_tuned is not None:
            self._on_lo_tuned()

    def _on_fr1_fr3_committed(self) -> None:
        """FR1 or FR3 was just committed - typed then Enter/focus-loss, or
        an arrow button/key nudge (see the editingFinished/stepped wiring
        above). _apply_lo_frequency() still runs first so its usual
        out-of-range message (Internal LO) is based on the value actually
        just entered. But an invalid combination must not just go
        un-applied - it also can't be left sitting in the box looking like
        it took effect, so FR1/FR3 snap back to the last valid combination
        afterward. Only a genuinely valid combination updates that
        fallback in the first place."""
        self._apply_lo_frequency()
        if self._is_configuration_valid():
            self._last_valid_fr1_ghz = self.fr1_spin.value()
            self._last_valid_fr3_ghz = self.fr3_spin.value()
        else:
            self.fr1_spin.setValue(self._last_valid_fr1_ghz)
            self.fr3_spin.setValue(self._last_valid_fr3_ghz)

    def _on_sideband_toggled(self, upper_checked: bool) -> None:
        # Sideband flips which frequency is desired vs. undesired, so it
        # affects the filter score just as much as fr1/fr3/bw do.
        if self._has_rf_filters:
            self._on_scoring_input_changed()
        self._update_external_lo_display()
        if self._is_populating():
            return
        if not self._is_configuration_valid():
            # This sideband would put the required LO out of range - must
            # not reach the hardware at all (previously, set_iq_swap was
            # sent unconditionally here, before this check, applying the
            # rejected sideband to the board's actual IQ swap state even
            # though the LMX2820 correctly refused to retune - a real
            # GUI/hardware mismatch). The radio also snaps back to its
            # previous selection instead of looking like the change took.
            # _apply_lo_frequency() still shows its usual out-of-range
            # message (Internal LO) for the sideband just rejected -
            # preserved across the revert below rather than letting the
            # resulting re-sync silently overwrite it.
            self._apply_lo_frequency()
            rejection_message = self.lo_status_label.text()
            self.upper_sideband_radio.blockSignals(True)
            self.lower_sideband_radio.blockSignals(True)
            try:
                self.upper_sideband_radio.setChecked(not upper_checked)
                self.lower_sideband_radio.setChecked(upper_checked)
            finally:
                self.upper_sideband_radio.blockSignals(False)
                self.lower_sideband_radio.blockSignals(False)
            if self._has_rf_filters:
                self._on_scoring_input_changed()
            self._update_external_lo_display()
            self.lo_status_label.setText(rejection_message)
            return
        self._worker.submit("set_iq_swap", not upper_checked)
        self._apply_lo_frequency()

    def _on_lo_source_changed(self, internal_selected: bool) -> None:
        # FR1/FR3/sideband stay live inputs either way; only the auto-tune
        # (LMX2820) vs. the external_lo_value_label readout differ by source.
        if not internal_selected:
            self.lo_status_label.setText("")
        else:
            # Switching back to Internal - FR1/FR3/sideband may well have
            # changed while External was selected (that's the point of
            # keeping them live), so retune now instead of leaving the
            # LMX2820 (and its Frequency display) stale from the last time
            # Internal was active.
            self._apply_lo_frequency()
        self._update_external_lo_display()
        if self._has_rf_filters:
            # Re-suggest (not just redraw), or auto-select goes stale.
            self._on_scoring_input_changed()

    def _update_external_lo_display(self) -> None:
        """Keeps external_lo_value_label (owned by the LO Source group, a
        plain text label - not an input) showing the LO frequency required
        for the current FR1/FR3/sideband inputs - what to feed in when
        External LO is selected. Same formula as the LMX2820 auto-tune;
        runs regardless of LO source so it's never stale by the time
        External LO gets selected."""
        lo_hz = self._compute_required_lo_hz()
        self._external_lo_value_label.setText(f"{lo_hz / 1e9:.6f} GHz")

    def _save_inputs(self) -> None:
        save_tx_helper_inputs(self._tab_key, self.fr1_spin.value(), self.fr3_spin.value(), self.bw_spin.value())

    # ---- filter suggestion / graph (only when has_rf_filters) ----

    def seed_display_filter(self, bits: int) -> None:
        """Called once, after the board's snapshot arrives, so the graph
        starts on the board's real TX filter instead of Bypass. Doesn't
        emit filter_suggested - TX/RX already got this value from the
        snapshot directly, and RX must not have it overwritten by TX's
        value here. No-op once a real suggestion exists."""
        if self.suggested_bits is None:
            self.suggested_bits = bits
            if self._has_rf_filters:
                self._redraw()

    def _on_auto_select_filter_toggled(self, checked: bool) -> None:
        self.suggest_button.setEnabled(not checked)
        if checked:
            self._suggest_filter()

    def _on_scoring_input_changed(self) -> None:
        """fr1/fr3/bw/sideband changed - re-suggest if that's being kept in
        sync automatically, otherwise just redraw with the same filter as
        before (_suggest_filter() already redraws internally, so exactly
        one of the two happens here, never both)."""
        if self.auto_select_filter_checkbox.isChecked():
            self._suggest_filter()
        else:
            self._redraw()

    def _sideband_centers(self) -> tuple[float, float]:
        """Returns (desired_center_hz, undesired_center_hz)."""
        f_lo_hz = self._compute_required_lo_hz()
        f_in_hz = self.fr1_spin.value() * 1e9
        if self.upper_sideband_radio.isChecked():
            return f_lo_hz + f_in_hz, f_lo_hz - f_in_hz
        return f_lo_hz - f_in_hz, f_lo_hz + f_in_hz

    def _score_for_bits(self, bits: int) -> tuple[float, float]:
        """Returns (desired_power_passed, rejection_db) for one filter
        configuration, given the currently configured FR1/FR3/bw/sideband
        state. rejection_db already includes BASELINE_SUPPRESSION_DB."""
        desired_center, undesired_center = self._sideband_centers()
        half_bw_hz = (self.bw_spin.value() * 1e9) / 2.0
        desired_range = (desired_center - half_bw_hz, desired_center + half_bw_hz)
        undesired_range = (undesired_center - half_bw_hz, undesired_center + half_bw_hz)

        response = get_response(bits)
        desired_power = _band_mean_power(response, *desired_range)
        undesired_power = _band_mean_power(response, *undesired_range)
        filter_only_rejection_db = 10.0 * np.log10(desired_power / max(undesired_power, 1e-30))
        return desired_power, filter_only_rejection_db + BASELINE_SUPPRESSION_DB

    def _redraw(self) -> None:
        if not self._is_configuration_valid():
            # Leave whatever was last plotted for a valid configuration on
            # screen, rather than drawing a frequency the LMX2820 could
            # never actually be tuned to.
            return
        self.plot.clear()

        f_lo_hz = self._compute_required_lo_hz()
        bw_hz = self.bw_spin.value() * 1e9
        half_bw_hz = bw_hz / 2.0
        desired_center, undesired_center = self._sideband_centers()

        self.plot.addItem(_hatched_fill(
            undesired_center - half_bw_hz, undesired_center + half_bw_hz,
            UNDESIRED_BOTTOM_DB, UNDESIRED_TOP_DB, "r",
        ))
        self.plot.addItem(_rect_outline(
            undesired_center - half_bw_hz, undesired_center + half_bw_hz,
            UNDESIRED_BOTTOM_DB, UNDESIRED_TOP_DB, "r", "Undesired sideband (Pre-filtering)",
        ))
        self.plot.addItem(_hatched_fill(
            desired_center - half_bw_hz, desired_center + half_bw_hz,
            DESIRED_BOTTOM_DB, DESIRED_TOP_DB, "g",
        ))
        self.plot.addItem(_rect_outline(
            desired_center - half_bw_hz, desired_center + half_bw_hz,
            DESIRED_BOTTOM_DB, DESIRED_TOP_DB, "g", "Desired sideband (Pre-filtering)",
        ))
        self.plot.plot(
            [f_lo_hz, f_lo_hz], [LO_BOTTOM_DB, LO_TOP_DB],
            pen=pg.mkPen("k", width=4), name="LO Leakage (Static)",
        )
        # angle=90 points up (pyqtgraph's default angle=0 points left);
        # pos is the arrow's tip.
        self.plot.addItem(pg.ArrowItem(pos=(f_lo_hz, LO_TOP_DB), angle=90, pen="k", brush="k"))

        # Bypass until a suggestion has actually been made - not TX or RX's
        # own current filter setting, since this graph previews a candidate
        # rather than tracking either one's live hardware state.
        response = get_response(self.suggested_bits if self.suggested_bits is not None else 0x00)
        self.plot.plot(
            response.freq_hz, response.s21_db,
            pen=pg.mkPen("b", width=4, style=Qt.DashLine), name="Filter S21 (raw)",
        )
        # Normalized to 0dB peak: only passband shape/position relative to
        # the illustrative reference levels matters here, not absolute loss.
        normalized_s21 = response.s21_db - response.s21_db.max()
        self.plot.plot(
            response.freq_hz, normalized_s21,
            pen=pg.mkPen("b", width=4), name="Filter S21 (normalized)",
        )

        edges = [
            desired_center - half_bw_hz, desired_center + half_bw_hz,
            undesired_center - half_bw_hz, undesired_center + half_bw_hz,
            f_lo_hz,
        ]
        low, high = min(edges), max(edges)
        margin = (high - low) * 0.15 or 1e9
        self.plot.setXRange(low - margin, high + margin, padding=0)

    def _suggest_filter(self) -> None:
        """Searches all 48 non-Bypass configs (3 bands x 16 sub-states).
        Picks the one with the most desired sideband energy among those
        reaching MIN_REJECTION_DB, or the highest-rejection one if none
        qualify. LO leakage is not part of this scoring."""
        if not self._is_configuration_valid():
            # Freeze on the last suggestion made for a valid configuration
            # rather than scoring filters against a frequency the LMX2820
            # could never actually be tuned to.
            return
        candidates = []
        for _, bank_nibble in FILTER_BANKS:
            if bank_nibble == 0x0:  # Bypass excluded
                continue
            for config_nibble in range(16):
                bits = (bank_nibble << 4) | config_nibble
                desired_power, rejection_db = self._score_for_bits(bits)
                candidates.append((bits, desired_power, rejection_db))

        qualifying = [c for c in candidates if c[2] >= MIN_REJECTION_DB]
        met_threshold = bool(qualifying)
        best_bits, _, best_rejection_db = max(
            qualifying if met_threshold else candidates,
            key=(lambda c: c[1]) if met_threshold else (lambda c: c[2]),
        )
        bank_name = next(name for name, nibble in FILTER_BANKS if nibble == (best_bits >> 4) & 0x0F)

        # A recommendation only - this widget doesn't drive TX or RX filter
        # hardware itself; TX/RX Settings' own "Use Suggested Filter"
        # buttons apply it if the user chooses to.
        self.suggested_bits = best_bits
        self.filter_suggested.emit(best_bits)
        self._redraw()

        if met_threshold:
            self.suggest_result_label.setText(
                f"Suggested: {bank_name}, 0x{best_bits & 0x0F:X} ({_format_rejection(best_rejection_db)})"
            )
        else:
            self.suggest_result_label.setText(
                f"No configuration reaches {MIN_REJECTION_DB:.0f}dB rejection - best "
                f"available: {bank_name}, 0x{best_bits & 0x0F:X} ({_format_rejection(best_rejection_db)})"
            )
