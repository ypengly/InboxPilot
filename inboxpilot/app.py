from __future__ import annotations
import logging
import sys

from .config import Settings, data_dir
from .db import Database
from .security import TokenStore


def main() -> int:
    logging.basicConfig(filename=data_dir() / "inboxpilot.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from PySide6.QtWidgets import QApplication
    from .ui.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName("InboxPilot")
    win = MainWindow(Database(data_dir() / "inboxpilot.db"), Settings(), TokenStore())
    win.show()
    return app.exec()
