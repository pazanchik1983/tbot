"""Главное окно.

Поправлено:
- bus.subscribe оборачивается в Qt-сигнал (потокобезопасно), но регистрируется
  единожды; при закрытии окна отписываемся;
- при смене инструмента старая подписка брокера останавливается (disconnect+reconnect-стрима);
- агент при перезапуске чисто отписывается через shutdown();
- ручной ордер использует тот же RiskManager;
- при отказе подключения интерфейс остаётся в рабочем состоянии (stub).
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from loguru import logger
from PyQt6 import QtCore, QtGui, QtWidgets

from tbot.agents.runtime import AgentRuntime
from tbot.brokers.base import BrokerBase
from tbot.brokers.factory import make_broker
from tbot.core.config import Settings, save_settings
from tbot.core.event_bus import (T_CANDLE, T_LOG, T_ORDER_NEW, T_SIGNAL,
                                 T_TRADE, bus)
from tbot.core.models import Instrument, Order, Side, Trade
from tbot.core.risk import RiskManager
from tbot.core.storage import list_trades, save_trade
from tbot.core.timeutil import utcnow
from tbot.ui.chart_widget import ChartWidget
from tbot.ui.settings_dialog import SettingsDialog


class MainWindow(QtWidgets.QMainWindow):
    sig_log = QtCore.pyqtSignal(str)
    sig_candle = QtCore.pyqtSignal(object, object)
    sig_trade = QtCore.pyqtSignal(object)
    sig_signal = QtCore.pyqtSignal(object)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.s = settings
        self.broker: BrokerBase | None = None
        self.risk = RiskManager(settings)
        self.agent: AgentRuntime | None = None
        self.current_figi: str | None = None
        self.instruments: dict[str, Instrument] = {}

        self.setWindowTitle("T-Bot — Т-Инвестиции / ОФЗ")
        self.resize(1320, 820)

        self._build_ui()
        self._wire_bus()

        QtCore.QTimer.singleShot(200, self._try_connect)

    # ---------- UI ----------
    def _build_ui(self) -> None:
        tb = self.addToolBar("Main"); tb.setMovable(False)

        self.act_connect = QtGui.QAction("🔌 Подключиться", self)
        self.act_connect.triggered.connect(self._toggle_connect)
        tb.addAction(self.act_connect)

        self.act_start = QtGui.QAction("▶ Запустить агента", self)
        self.act_start.triggered.connect(self._toggle_agent)
        self.act_start.setEnabled(False)
        tb.addAction(self.act_start)

        tb.addSeparator()
        act_settings = QtGui.QAction("⚙ Настройки", self)
        act_settings.triggered.connect(self._open_settings)
        tb.addAction(act_settings)

        act_retrain = QtGui.QAction("🧠 Переобучить агента", self)
        act_retrain.triggered.connect(self._retrain_now)
        tb.addAction(act_retrain)

        central = QtWidgets.QWidget(); self.setCentralWidget(central)
        lay = QtWidgets.QHBoxLayout(central); lay.setContentsMargins(6, 6, 6, 6)
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal); lay.addWidget(split)

        # инструменты
        left = QtWidgets.QWidget(); ll = QtWidgets.QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QtWidgets.QLabel("Инструменты (ОФЗ)"))
        self.search = QtWidgets.QLineEdit(); self.search.setPlaceholderText("поиск…")
        self.search.textChanged.connect(self._filter_instruments)
        ll.addWidget(self.search)
        self.instr_table = QtWidgets.QTableWidget(0, 3)
        self.instr_table.setHorizontalHeaderLabels(["Тикер", "Название", "Lot"])
        self.instr_table.horizontalHeader().setStretchLastSection(True)
        self.instr_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.instr_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.instr_table.itemSelectionChanged.connect(self._on_instr_selected)
        ll.addWidget(self.instr_table, 1)
        split.addWidget(left)

        # график
        center = QtWidgets.QWidget(); cl = QtWidgets.QVBoxLayout(center); cl.setContentsMargins(0, 0, 0, 0)
        hdr = QtWidgets.QHBoxLayout()
        self.lbl_ticker = QtWidgets.QLabel("—"); self.lbl_ticker.setObjectName("ticker")
        self.lbl_price = QtWidgets.QLabel(""); self.lbl_price.setObjectName("priceUp")
        hdr.addWidget(self.lbl_ticker); hdr.addSpacing(20); hdr.addWidget(self.lbl_price)
        hdr.addStretch(1)
        self.qty_spin = QtWidgets.QSpinBox(); self.qty_spin.setRange(1, 10000); self.qty_spin.setValue(1)
        self.btn_buy = QtWidgets.QPushButton("BUY"); self.btn_buy.setObjectName("primary")
        self.btn_sell = QtWidgets.QPushButton("SELL"); self.btn_sell.setObjectName("danger")
        self.btn_buy.clicked.connect(lambda: self._manual_order(Side.BUY))
        self.btn_sell.clicked.connect(lambda: self._manual_order(Side.SELL))
        for w in (QtWidgets.QLabel("кол-во:"), self.qty_spin, self.btn_buy, self.btn_sell):
            hdr.addWidget(w)
        cl.addLayout(hdr)
        self.chart = ChartWidget(); cl.addWidget(self.chart, 1)
        split.addWidget(center)

        # вкладки справа
        right = QtWidgets.QTabWidget()
        self.trades_table = QtWidgets.QTableWidget(0, 5)
        self.trades_table.setHorizontalHeaderLabels(["Время", "Тикер", "Сторона", "Цена", "Кол-во"])
        self.trades_table.horizontalHeader().setStretchLastSection(True)
        right.addTab(self.trades_table, "Сделки")
        self.signals_list = QtWidgets.QListWidget(); right.addTab(self.signals_list, "Сигналы")
        self.log_view = QtWidgets.QPlainTextEdit(); self.log_view.setReadOnly(True)
        right.addTab(self.log_view, "Лог")
        split.addWidget(right)

        split.setStretchFactor(0, 2); split.setStretchFactor(1, 6); split.setStretchFactor(2, 3)

        sb = self.statusBar()
        self.lbl_status = QtWidgets.QLabel("Не подключено")
        self.lbl_pnl = QtWidgets.QLabel("PnL день: 0.00 ₽")
        sb.addWidget(self.lbl_status, 1)
        sb.addPermanentWidget(self.lbl_pnl)

    # ---------- bus → UI signals ----------
    def _wire_bus(self) -> None:
        # обработчики bus, которые конвертят в Qt-сигналы (потокобезопасно)
        self._h_log = lambda m: self.sig_log.emit(str(m))
        self._h_candle = lambda p: self.sig_candle.emit(p[0], p[1]) if isinstance(p, tuple) else None
        self._h_trade = lambda t: self.sig_trade.emit(t)
        self._h_signal = lambda s: self.sig_signal.emit(s)
        self._h_order = lambda o: self.sig_log.emit(
            f"Ордер: {o.side.value} {o.quantity} @ {o.price or 'market'} (id={o.id[:8]})")

        bus.subscribe(T_LOG, self._h_log)
        bus.subscribe(T_CANDLE, self._h_candle)
        bus.subscribe(T_TRADE, self._h_trade)
        bus.subscribe(T_SIGNAL, self._h_signal)
        bus.subscribe(T_ORDER_NEW, self._h_order)

        self.sig_log.connect(self._append_log)
        self.sig_candle.connect(self._on_candle_ui)
        self.sig_trade.connect(self._on_trade_ui)
        self.sig_signal.connect(self._on_signal_ui)

    def _unwire_bus(self) -> None:
        for topic, h in [(T_LOG, self._h_log), (T_CANDLE, self._h_candle),
                         (T_TRADE, self._h_trade), (T_SIGNAL, self._h_signal),
                         (T_ORDER_NEW, self._h_order)]:
            bus.unsubscribe(topic, h)

    # ---------- подключение ----------
    def _try_connect(self) -> None:
        # снять старого брокера
        self._teardown_broker()
        try:
            self.broker = make_broker(self.s)
            self.broker.connect()
            self._on_connected()
        except Exception as e:
            self._append_log(f"Не подключено: {e}")
            self.lbl_status.setText("Не подключено — откройте Настройки")
            self.act_connect.setText("🔌 Подключиться")
            self.act_start.setEnabled(False)

    def _toggle_connect(self) -> None:
        if self.broker and self.broker.is_connected():
            self._teardown_broker()
            self.act_connect.setText("🔌 Подключиться")
            self.act_start.setEnabled(False)
            self.lbl_status.setText("Отключено")
        else:
            self._try_connect()

    def _teardown_broker(self) -> None:
        self._stop_agent()
        if self.broker:
            try: self.broker.disconnect()
            except Exception as e: logger.warning("disconnect: {}", e)
        self.broker = None
        self.current_figi = None

    def _on_connected(self) -> None:
        assert self.broker is not None
        self.act_connect.setText("⛔ Отключиться")
        self.act_start.setEnabled(True)
        mode = "sandbox" if self.s.sandbox else "LIVE"
        self.lbl_status.setText(f"Подключено: {self.s.broker} [{mode}]")
        self._reload_instruments()
        self._reload_trade_history()

    def _reload_instruments(self) -> None:
        assert self.broker is not None
        try:
            bonds = self.broker.list_ofz()
        except Exception as e:
            self._append_log(f"Не удалось загрузить инструменты: {e}")
            bonds = []
        self.instruments = {b.figi: b for b in bonds}
        self._render_instruments(bonds)
        self._append_log(f"Загружено ОФЗ: {len(bonds)}")

    def _render_instruments(self, items: list[Instrument]) -> None:
        self.instr_table.setRowCount(0)
        for i, b in enumerate(items):
            self.instr_table.insertRow(i)
            self.instr_table.setItem(i, 0, QtWidgets.QTableWidgetItem(b.ticker))
            self.instr_table.setItem(i, 1, QtWidgets.QTableWidgetItem(b.name))
            self.instr_table.setItem(i, 2, QtWidgets.QTableWidgetItem(str(b.lot)))
            self.instr_table.item(i, 0).setData(QtCore.Qt.ItemDataRole.UserRole, b.figi)

    def _filter_instruments(self, text: str) -> None:
        text = text.lower().strip()
        for r in range(self.instr_table.rowCount()):
            t = (self.instr_table.item(r, 0).text() or "").lower()
            n = (self.instr_table.item(r, 1).text() or "").lower()
            self.instr_table.setRowHidden(r, bool(text) and (text not in t and text not in n))

    def _on_instr_selected(self) -> None:
        items = self.instr_table.selectedItems()
        if not items or not self.broker:
            return
        figi = self.instr_table.item(items[0].row(), 0).data(
            QtCore.Qt.ItemDataRole.UserRole)
        if figi == self.current_figi:
            return

        # пересоздаём стрим: останавливаем брокерские потоки и поднимаем заново
        try:
            self.broker.disconnect()
            self.broker.connect()
        except Exception as e:
            self._append_log(f"Переподключение: {e}")

        self.current_figi = figi
        instr = self.instruments.get(figi)
        if instr:
            self.lbl_ticker.setText(f"{instr.ticker} — {instr.name}")
        self._load_chart_for(figi)
        try:
            self.broker.subscribe_candles(
                [figi], "1m",
                on_candle=lambda f, c: bus.publish(T_CANDLE, (f, c)))
        except Exception as e:
            self._append_log(f"Подписка не запущена: {e}")

    def _load_chart_for(self, figi: str) -> None:
        end = utcnow()
        start = end - timedelta(days=2)
        try:
            candles = self.broker.get_candles(figi, start, end, "1m")
        except Exception as e:
            self._append_log(f"Свечи не загружены: {e}"); candles = []
        self.chart.set_candles(candles)
        if self.agent:
            self.agent.warmup(figi, candles)
        trades = list_trades(figi=figi, limit=200)
        self.chart.set_trades(trades)
        self._update_levels_from_trades(trades)
        try:
            last = self.broker.get_last_price(figi)
            if last is not None:
                self.lbl_price.setText(f"{last:.4f} ₽")
        except Exception:
            pass

    def _update_levels_from_trades(self, trades: list[Trade]) -> None:
        buys = sorted({round(t.price, 4) for t in trades if t.side == Side.BUY})[-10:]
        sells = sorted({round(t.price, 4) for t in trades if t.side == Side.SELL})[-10:]
        self.chart.set_levels(buys, sells)

    def _reload_trade_history(self) -> None:
        trades = list_trades(limit=500)
        self.trades_table.setRowCount(0)
        for i, t in enumerate(trades):
            self.trades_table.insertRow(i)
            self.trades_table.setItem(i, 0, QtWidgets.QTableWidgetItem(
                t.time.strftime("%Y-%m-%d %H:%M:%S")))
            self.trades_table.setItem(i, 1, QtWidgets.QTableWidgetItem(t.figi))
            it_side = QtWidgets.QTableWidgetItem(t.side.value)
            it_side.setForeground(QtGui.QColor("#2ecc71" if t.side == Side.BUY else "#e74c3c"))
            self.trades_table.setItem(i, 2, it_side)
            self.trades_table.setItem(i, 3, QtWidgets.QTableWidgetItem(f"{t.price:.4f}"))
            self.trades_table.setItem(i, 4, QtWidgets.QTableWidgetItem(str(t.quantity)))

    # ---------- агент ----------
    def _toggle_agent(self) -> None:
        if self.agent and self.agent.is_enabled():
            self._stop_agent()
        else:
            self._start_agent()

    def _start_agent(self) -> None:
        if not self.broker:
            return
        if self.agent is not None:
            self.agent.shutdown()
        self.agent = AgentRuntime(self.s, self.broker, self.risk)
        # если уже есть выбранный инструмент — прогреем буфер
        if self.current_figi:
            try:
                end = utcnow(); start = end - timedelta(days=2)
                self.agent.warmup(self.current_figi,
                                  self.broker.get_candles(self.current_figi, start, end, "1m"))
            except Exception as e:
                self._append_log(f"warmup: {e}")
        self.agent.start()
        self.act_start.setText("⏸ Остановить агента")

    def _stop_agent(self) -> None:
        if self.agent:
            self.agent.stop()
            self.agent.shutdown()
            self.agent = None
        self.act_start.setText("▶ Запустить агента")

    def _retrain_now(self) -> None:
        if self.agent is None:
            QtWidgets.QMessageBox.information(self, "Агент",
                                              "Запустите агента хотя бы раз, чтобы накопить сделки.")
            return
        if self.agent.ml.retrain():
            QtWidgets.QMessageBox.information(self, "Готово", "ML-фильтр переобучен.")
        else:
            QtWidgets.QMessageBox.information(self, "Информация",
                                              "Недостаточно сделок или только один класс. "
                                              "Накопите ещё немного истории.")

    # ---------- ручная торговля ----------
    def _manual_order(self, side: Side) -> None:
        if not self.broker or not self.current_figi:
            QtWidgets.QMessageBox.information(self, "Ордер",
                                              "Сначала выберите инструмент и подключитесь.")
            return
        try:
            ref = self.broker.get_last_price(self.current_figi) or 0.0
        except Exception:
            ref = 0.0
        order = Order(id=str(uuid.uuid4()), figi=self.current_figi, side=side,
                      quantity=int(self.qty_spin.value()), price=None)
        ok, reason = self.risk.check_order(order, ref or 100.0)
        if not ok:
            QtWidgets.QMessageBox.warning(self, "Ордер отклонён", reason)
            return
        try:
            placed = self.broker.place_order(order)
            bus.publish(T_ORDER_NEW, placed)
            # для брокеров с мгновенным fill — синтетический трейд
            if placed.status.value == "FILLED":
                tr = Trade(id=str(uuid.uuid4()), figi=self.current_figi, side=side,
                           quantity=int(self.qty_spin.value()),
                           price=ref or 100.0, order_id=placed.id, time=utcnow())
                bus.publish(T_TRADE, tr)
            self._append_log(f"Ручной ордер {side.value} отправлен.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))

    # ---------- настройки ----------
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.s, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            save_settings(self.s)
            self._append_log("Настройки сохранены. Переподключаюсь…")
            self._try_connect()

    # ---------- слоты UI ----------
    def _append_log(self, msg: str) -> None:
        ts = utcnow().astimezone().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{ts}] {msg}")
        # Чтобы лог не разрастался бесконечно
        if self.log_view.blockCount() > 2000:
            cur = self.log_view.textCursor()
            cur.movePosition(QtGui.QTextCursor.MoveOperation.Start)
            for _ in range(500):
                cur.select(QtGui.QTextCursor.SelectionType.LineUnderCursor)
                cur.removeSelectedText()
                cur.deleteChar()
        logger.info("UI: {}", msg)

    def _on_candle_ui(self, figi, candle) -> None:
        if figi != self.current_figi:
            return
        self.chart.add_candle(candle)
        self.lbl_price.setText(f"{candle.close:.4f} ₽")

    def _on_trade_ui(self, trade: Trade) -> None:
        try:
            save_trade(trade)
        except Exception as e:
            self._append_log(f"save_trade: {e}")
        self._reload_trade_history()
        if trade.figi == self.current_figi:
            tr = list_trades(figi=trade.figi, limit=200)
            self.chart.set_trades(tr)
            self._update_levels_from_trades(tr)
        self.lbl_pnl.setText(f"PnL день: {self.risk.daily_pnl():+.2f} ₽")

    def _on_signal_ui(self, sig) -> None:
        line = (f"{sig.created_at.astimezone().strftime('%H:%M:%S')}  {sig.figi}  "
                f"{sig.side.value}  conf={sig.confidence:.2f}  — {sig.reason}")
        self.signals_list.insertItem(0, line)
        if self.signals_list.count() > 200:
            self.signals_list.takeItem(self.signals_list.count() - 1)

    def closeEvent(self, e: QtGui.QCloseEvent) -> None:
        self._teardown_broker()
        self._unwire_bus()
        super().closeEvent(e)
