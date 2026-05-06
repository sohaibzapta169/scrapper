from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from src.ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Financial Listings Monitoring Tool")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
