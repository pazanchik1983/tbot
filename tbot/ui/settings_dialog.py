"""Диалог настроек: смена брокера, API-ключа, риск-параметров."""
from __future__ import annotations

from PyQt6 import QtWidgets

from tbot.core.config import (Settings, delete_api_token, get_api_token,
                              save_settings, set_api_token)

BROKERS = [
    ("tinkoff", "Т-Инвестиции"),
    ("finam_stub", "Финам (заглушка)"),
    ("bcs_stub", "БКС (заглушка)"),
]


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.resize(520, 420)
        self.s = settings

        form = QtWidgets.QFormLayout(self)

        # --- Брокер ---
        self.broker_box = QtWidgets.QComboBox()
        for code, label in BROKERS:
            self.broker_box.addItem(label, code)
        idx = next((i for i, (c, _) in enumerate(BROKERS) if c == settings.broker), 0)
        self.broker_box.setCurrentIndex(idx)
        self.broker_box.currentIndexChanged.connect(self._on_broker_change)
        form.addRow("Брокер:", self.broker_box)

        # --- Режим: песочница / боевой ---
        self.sandbox_box = QtWidgets.QCheckBox("Песочница (рекомендуется)")
        self.sandbox_box.setChecked(settings.sandbox)
        form.addRow("Режим:", self.sandbox_box)

        # --- API-токен ---
        h = QtWidgets.QHBoxLayout()
        self.token_edit = QtWidgets.QLineEdit()
        self.token_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("Вставьте API-токен …")
        self._load_token_to_field()
        self.show_btn = QtWidgets.QPushButton("👁")
        self.show_btn.setFixedWidth(36)
        self.show_btn.setCheckable(True)
        self.show_btn.toggled.connect(self._toggle_token_visibility)
        self.clear_btn = QtWidgets.QPushButton("Удалить")
        self.clear_btn.clicked.connect(self._clear_token)
        h.addWidget(self.token_edit, 1)
        h.addWidget(self.show_btn)
        h.addWidget(self.clear_btn)
        wrap = QtWidgets.QWidget(); wrap.setLayout(h)
        form.addRow("API-ключ:", wrap)

        # --- account_id ---
        self.acc_edit = QtWidgets.QLineEdit(settings.account_id or "")
        self.acc_edit.setPlaceholderText("оставьте пустым — возьмётся первый счёт")
        form.addRow("Account ID:", self.acc_edit)

        # --- Риск-параметры ---
        self.max_pos = QtWidgets.QDoubleSpinBox()
        self.max_pos.setRange(0, 1e9); self.max_pos.setValue(settings.max_position_rub)
        self.max_pos.setSuffix(" ₽"); self.max_pos.setSingleStep(1000)
        form.addRow("Макс. позиция:", self.max_pos)

        self.max_loss = QtWidgets.QDoubleSpinBox()
        self.max_loss.setRange(0, 1e9); self.max_loss.setValue(settings.max_daily_loss_rub)
        self.max_loss.setSuffix(" ₽"); self.max_loss.setSingleStep(500)
        form.addRow("Лимит убытка/день:", self.max_loss)

        self.qty = QtWidgets.QSpinBox()
        self.qty.setRange(1, 10000); self.qty.setValue(settings.default_quantity)
        form.addRow("Объём по умолч. (лоты):", self.qty)

        self.retrain = QtWidgets.QSpinBox()
        self.retrain.setRange(5, 1000); self.retrain.setValue(settings.auto_retrain_every_n_trades)
        form.addRow("Переобучать каждые N сделок:", self.retrain)

        # --- Кнопки ---
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    # ---------- helpers ----------
    def _current_broker_code(self) -> str:
        return self.broker_box.currentData()

    def _load_token_to_field(self) -> None:
        tok = get_api_token(self._current_broker_code()) or ""
        self.token_edit.setText(tok)

    def _on_broker_change(self, _) -> None:
        self._load_token_to_field()

    def _toggle_token_visibility(self, on: bool) -> None:
        self.token_edit.setEchoMode(
            QtWidgets.QLineEdit.EchoMode.Normal if on
            else QtWidgets.QLineEdit.EchoMode.Password)

    def _clear_token(self) -> None:
        delete_api_token(self._current_broker_code())
        self.token_edit.clear()
        QtWidgets.QMessageBox.information(self, "Готово", "API-ключ удалён.")

    def _on_save(self) -> None:
        broker = self._current_broker_code()
        # Подтверждение боевого режима
        if not self.sandbox_box.isChecked():
            r = QtWidgets.QMessageBox.warning(
                self, "Боевой режим",
                "Вы выключили песочницу. Ордера будут отправляться на реальный счёт.\n"
                "Продолжить?",
                QtWidgets.QMessageBox.StandardButton.Yes |
                QtWidgets.QMessageBox.StandardButton.No)
            if r != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        tok = self.token_edit.text().strip()
        if tok:
            set_api_token(broker, tok)
        self.s.broker = broker            # type: ignore
        self.s.sandbox = self.sandbox_box.isChecked()
        self.s.account_id = self.acc_edit.text().strip() or None
        self.s.max_position_rub = float(self.max_pos.value())
        self.s.max_daily_loss_rub = float(self.max_loss.value())
        self.s.default_quantity = int(self.qty.value())
        self.s.auto_retrain_every_n_trades = int(self.retrain.value())
        save_settings(self.s)
        self.accept()
