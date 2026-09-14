"""Blocks mouse-wheel scrolling from changing the value of any spin box,
combo box, or slider anywhere in the app. Installed once, application-wide
(see main.py) - without this, scrolling down a settings panel silently
edits whatever numeric field the cursor happens to pass over."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QSlider

_NO_WHEEL_TYPES = (QAbstractSpinBox, QComboBox, QSlider)


class NoWheelFilter(QObject):
    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Wheel and isinstance(watched, _NO_WHEEL_TYPES):
            event.ignore()
            return True
        return super().eventFilter(watched, event)
