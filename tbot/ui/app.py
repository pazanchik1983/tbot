"""Точка входа PyQt6-приложения."""
from __future__ import annotations

import sys

from PyQt6 import QtGui, QtWidgets

from tbot.core.config import Settings
from tbot.ui.main_window import MainWindow
from tbot.ui.styles import DARK_QSS


def run_app(settings: Settings) -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("T-Bot")
    app.setOrganizationName("TBot")
    app.setStyle("Fusion")
    if settings.theme == "dark":
        app.setStyleSheet(DARK_QSS)

    win = MainWindow(settings)
    win.show()
    return app.exec()
