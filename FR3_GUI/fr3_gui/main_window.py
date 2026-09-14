"""Top-level window: turns discovery's connect/disconnect signals into tabs
appearing/disappearing. A tab can be removed via the worker's own
connection_lost (fast path) or discovery's port_gone (backstop) - both
funnel through _remove_tab(), safe to call twice."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from .device_tab import DeviceTab
from .discovery import DeviceInfo, DiscoveryWorker
from .version import __version__

logger = logging.getLogger(__name__)

# Fallback size if no device ever connects (nothing to fit-to-content from).
_DEFAULT_SIZE = (500, 400)


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Pi-Radio FR3 Board Control v{__version__}")
        self.resize(*_DEFAULT_SIZE)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._tabs_by_key: dict[str, DeviceTab] = {}
        self._port_to_key: dict[str, str] = {}
        self._sized_to_content = False

        self.discovery = DiscoveryWorker()
        self.discovery.device_connected.connect(self._on_device_connected)
        self.discovery.port_gone.connect(self._on_port_gone)
        self.discovery.start()

    def _on_device_connected(self, info: DeviceInfo) -> None:
        if info.tab_key in self._tabs_by_key:
            # Shouldn't normally happen (discovery keys by port, tabs by
            # serial), but never show the same physical unit twice.
            logger.warning("Ignoring duplicate connect for already-open tab %s", info.tab_key)
            return

        tab = DeviceTab(info)
        self._tabs_by_key[info.tab_key] = tab
        self._port_to_key[info.port_name] = info.tab_key
        tab.worker.connection_lost.connect(lambda key=info.tab_key: self._remove_tab(key))

        label = f"{info.board_name} #{info.serial_number}"
        self.tabs.addTab(tab, label)
        logger.info("Tab added: %s (%s)", info.tab_key, info.port_name)

        if not self._sized_to_content:
            self._fit_to_content(tab)
            self._sized_to_content = True

    def _fit_to_content(self, tab: DeviceTab) -> None:
        """Sizes the window once, at startup, so its first tab's content
        fits with no scrollbar (vertically) and no wasted width. Later
        manual resizes (or a later tab needing more room) are left alone -
        the scroll area handles anything after that."""
        hint = tab.natural_size()
        tab_bar_h = self.tabs.tabBar().sizeHint().height()
        margin = 40

        target_w = hint.width() + margin
        target_h = hint.height() + tab_bar_h + margin

        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            target_w = min(target_w, available.width() - 20)
            target_h = min(target_h, available.height() - 20)

        self.resize(target_w, target_h)

    def _on_port_gone(self, port_name: str) -> None:
        tab_key = self._port_to_key.pop(port_name, None)
        if tab_key is not None:
            self._remove_tab(tab_key)

    def _remove_tab(self, tab_key: str) -> None:
        tab = self._tabs_by_key.pop(tab_key, None)
        if tab is None:
            return  # already removed via the other notification path

        for port_name, key in list(self._port_to_key.items()):
            if key == tab_key:
                del self._port_to_key[port_name]

        index = self.tabs.indexOf(tab)
        if index != -1:
            self.tabs.removeTab(index)

        logger.info("Tab removed: %s", tab_key)
        tab.shutdown()
        tab.deleteLater()

    def closeEvent(self, event) -> None:
        self.discovery.stop()
        self.discovery.wait(2000)
        for tab in list(self._tabs_by_key.values()):
            tab.shutdown()
        super().closeEvent(event)
