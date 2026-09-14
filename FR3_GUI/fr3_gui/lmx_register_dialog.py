"""Non-modal dialog for reading LMX2820 registers directly - a bring-up/
debug tool. "Read All Registers" fills the whole table; a single register
number + "Read" updates just that row and the result label."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .device import LMX_REGISTER_COUNT
from .worker import DeviceWorker


class LmxRegisterDialog(QDialog):
    def __init__(self, worker: DeviceWorker, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LMX2820 Registers")
        self.resize(320, 560)
        self._worker = worker

        worker.all_lmx_registers_read.connect(self._populate_table)
        worker.lmx_register_read.connect(self._show_single_register)

        layout = QVBoxLayout(self)

        lookup_row = QHBoxLayout()
        self.reg_spin = QSpinBox()
        self.reg_spin.setRange(0, LMX_REGISTER_COUNT - 1)
        read_button = QPushButton("Read")
        read_button.clicked.connect(self._read_single)
        self.single_result_label = QLabel("-")
        self.single_result_label.setMinimumWidth(60)
        lookup_row.addWidget(QLabel("Register:"))
        lookup_row.addWidget(self.reg_spin)
        lookup_row.addWidget(read_button)
        lookup_row.addWidget(self.single_result_label)
        lookup_row.addStretch(1)
        layout.addLayout(lookup_row)

        self.refresh_button = QPushButton("Read All Registers")
        self.refresh_button.clicked.connect(self._read_all)
        layout.addWidget(self.refresh_button)

        self.table = QTableWidget(LMX_REGISTER_COUNT, 2)
        self.table.setHorizontalHeaderLabels(["Register", "Value"])
        self.table.verticalHeader().setVisible(False)
        for addr in range(LMX_REGISTER_COUNT):
            reg_item = QTableWidgetItem(f"R{addr}")
            reg_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            value_item = QTableWidgetItem("-")
            value_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(addr, 0, reg_item)
            self.table.setItem(addr, 1, value_item)
        layout.addWidget(self.table, stretch=1)

        self._read_all()

    def _read_single(self) -> None:
        self._worker.request_lmx_register(self.reg_spin.value())

    def _read_all(self) -> None:
        self._worker.request_all_lmx_registers()

    def _show_single_register(self, addr: int, value: int) -> None:
        self.single_result_label.setText(f"0x{value:04X}")
        self._set_table_value(addr, value)

    def _populate_table(self, values: dict) -> None:
        for addr, value in values.items():
            self._set_table_value(addr, value)

    def _set_table_value(self, addr: int, value: int) -> None:
        if 0 <= addr < self.table.rowCount():
            self.table.item(addr, 1).setText(f"0x{value:04X}")
