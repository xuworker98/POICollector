# -*- coding: utf-8 -*-
"""POICollector desktop entry point."""
from __future__ import annotations

import sys
from pathlib import Path

APP_SOURCE = Path(__file__).resolve().parent / "src" / "poi_collector"
if str(APP_SOURCE) not in sys.path:
    sys.path.insert(0, str(APP_SOURCE))

from PySide6.QtWidgets import QApplication

from ui import styles
from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("POICollector")
    app.setStyle("Fusion")
    app.setStyleSheet(styles.QSS)
    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
