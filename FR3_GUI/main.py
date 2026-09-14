import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from fr3_gui.device_tab import STYLE_SHEET
from fr3_gui.logging_setup import configure_logging
from fr3_gui.main_window import MainWindow
from fr3_gui.no_wheel_filter import NoWheelFilter

# Bundled resource (see fr3_gui.spec's datas) - resolves the same from
# source or a frozen build.
ICON_PATH = Path(__file__).resolve().parent / "fr3_gui" / "resources" / "icon.png"


def main() -> int:
    configure_logging()
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE_SHEET)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    # Parented to app so it lives as long as the app does.
    app.installEventFilter(NoWheelFilter(app))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
