"""Тёмная тема в стиле торговых терминалов."""

DARK_QSS = """
QMainWindow, QDialog { background: #0f1216; color: #d6d9df; }
QWidget { color: #d6d9df; font-family: 'Segoe UI'; font-size: 12px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #1a1f27; border: 1px solid #2a323d; border-radius: 4px;
    padding: 4px 6px; selection-background-color: #2e6cdf;
}
QPushButton {
    background: #1f2630; border: 1px solid #2a323d; border-radius: 4px;
    padding: 6px 14px;
}
QPushButton:hover { background: #2a323d; }
QPushButton:pressed { background: #14181f; }
QPushButton#primary { background: #2e6cdf; border-color: #2e6cdf; color: white; }
QPushButton#primary:hover { background: #4079e6; }
QPushButton#danger { background: #c0392b; border-color: #c0392b; color: white; }

QHeaderView::section {
    background: #161a20; color: #9aa3b1; padding: 6px;
    border: none; border-right: 1px solid #20262f;
}
QTableWidget, QListWidget {
    background: #11151a; alternate-background-color: #141921;
    gridline-color: #20262f; border: 1px solid #1f252e;
}
QTableWidget::item:selected, QListWidget::item:selected {
    background: #2e6cdf; color: white;
}
QStatusBar { background: #0c0f13; color: #9aa3b1; }
QSplitter::handle { background: #20262f; }
QLabel#ticker { font-size: 16px; font-weight: 600; }
QLabel#priceUp { color: #2ecc71; font-weight: 600; }
QLabel#priceDown { color: #e74c3c; font-weight: 600; }
QTabBar::tab { background: #161a20; padding: 6px 12px; border: 1px solid #20262f; }
QTabBar::tab:selected { background: #1f2630; }
"""
