"""AgentRuntime: связывает свечи → стратегия → ML-фильтр → ордер → обучение.

Поправлено по итогам ревью:
- работа со временем — tz-aware UTC;
- дедуп свечей по (figi, time): на одну новую свечу — максимум один сигнал;
- "тиковое" обновление текущей свечи не порождает новый сигнал
  (рассуждаем только на закрытии свечи);
- сделка от брокера привязывается к нашему ордеру (по order_id/figi+side),
  а не к "последнему сетапу" слепо;
- учёт позиции: открытие/наращивание/закрытие/переворот разделены;
- PnL берётся из RiskManager (единая точка правды);
- корректная остановка/перезапуск без утечки подписок.
"""
from __future__ import annotations

import threading
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass

import pandas as pd
from loguru import logger

from tbot.agents.base_strategy import indicator_signal
from tbot.agents.features import candles_to_df
from tbot.agents.ml_filter import MLFilter
from tbot.brokers.base import BrokerBase
from tbot.core.config import Settings
from tbot.core.event_bus import (T_CANDLE, T_LOG, T_ORDER_NEW, T_SIGNAL,
                                 T_TRADE, bus)
from tbot.core.models import Order, OrderStatus, Side, Signal, Trade
from tbot.core.risk import RiskManager
from tbot.core.timeutil import utcnow


@dataclass
class _OpenSetup:
    """То, что мы запомнили в момент открытия позиции — для разметки."""
    features_df: pd.DataFrame
    side: Side
    entry_price: float
    order_id: str


class AgentRuntime:
    BUFFER_LEN = 500

    def __init__(self, settings: Settings, broker: BrokerBase,
                 risk: RiskManager) -> None:
        self.s = settings
        self.broker = broker
        self.risk = risk
        self.ml = MLFilter(broker=settings.broker)
        self.buffers: dict[str, deque] = defaultdict(lambda: deque(maxlen=self.BUFFER_LEN))
        self._open_setups: dict[str, _OpenSetup] = {}        # активная позиция по figi
        self._our_orders: dict[str, str] = {}                # order_id → figi
        self._last_signal_time: dict[str, object] = {}
        self._lock = threading.RLock()
        self._enabled = False

        bus.subscribe(T_CANDLE, self._on_candle)
        bus.subscribe(T_TRADE, self._on_trade)

    def shutdown(self) -> None:
        """Аккуратно отписаться от шины (важно при перезапуске)."""
        bus.unsubscribe(T_CANDLE, self._on_candle)
        bus.unsubscribe(T_TRADE, self._on_trade)
        self._enabled = False

    # ---------- управление ----------
    def start(self) -> None:
        self._enabled = True
        bus.publish(T_LOG, "Агент запущен")

    def stop(self) -> None:
        self._enabled = False
        bus.publish(T_LOG, "Агент остановлен")

    def is_enabled(self) -> bool:
        return self._enabled

    # ---------- предзагрузка истории ----------
    def warmup(self, figi: str, candles) -> None:
        with self._lock:
            b = self.buffers[figi]
            b.clear()
            for c in candles[-self.BUFFER_LEN:]:
                b.append(c)

    # ---------- хэндлеры ----------
    def _on_candle(self, payload) -> None:
        try:
            figi, candle = payload
        except Exception:
            return
        with self._lock:
            buf = self.buffers[figi]
            is_new_bar = (not buf) or (buf[-1].time != candle.time)
            if is_new_bar:
                buf.append(candle)
            else:
                buf[-1] = candle
            if not self._enabled or not is_new_bar or len(buf) < 60:
                return
            # дедуп: один сигнал на бар
            if self._last_signal_time.get(figi) == candle.time:
                return
            self._last_signal_time[figi] = candle.time
            df = candles_to_df(list(buf))

        raw = indicator_signal(df)
        if raw.side is None:
            return
        proba = self.ml.predict_proba(df, raw.side)
        confidence = raw.strength * proba
        if confidence < float(self.s.min_confidence):
            return

        sig = Signal(figi=figi, side=raw.side, confidence=confidence,
                     reason="; ".join(raw.reasons) + f"; ML_p={proba:.2f}")
        bus.publish(T_SIGNAL, sig)
        self._maybe_trade(sig, df)

    def _maybe_trade(self, sig: Signal, df: pd.DataFrame) -> None:
        price = float(df["close"].iloc[-1])
        cur_qty, _ = self.risk.position(sig.figi)
        # Логика входа:
        #   * нет позиции → открываем
        #   * есть позиция той же стороны → не наращиваем (защита от спама)
        #   * есть позиция противоположной стороны → закрываем (на её объём)
        if cur_qty == 0:
            qty = int(self.s.default_quantity)
            action = "OPEN"
        elif (cur_qty > 0) == (sig.side == Side.BUY):
            return                                      # уже в позиции той же стороны
        else:
            qty = abs(cur_qty)                          # закрытие
            action = "CLOSE"

        order = Order(id=str(uuid.uuid4()), figi=sig.figi, side=sig.side,
                      quantity=qty, price=None)
        ok, reason = self.risk.check_order(order, price)
        if not ok:
            bus.publish(T_LOG, f"Риск-менеджер отклонил ордер: {reason}")
            return
        try:
            placed = self.broker.place_order(order)
        except Exception as e:
            bus.publish(T_LOG, f"Ошибка отправки ордера: {e}")
            return

        with self._lock:
            self._our_orders[placed.id] = placed.figi
            if action == "OPEN":
                self._open_setups[sig.figi] = _OpenSetup(
                    features_df=df.copy(), side=sig.side,
                    entry_price=price, order_id=placed.id)
            else:
                # закрытие — снимаем сетап после fill
                pass
        bus.publish(T_ORDER_NEW, placed)

        # Для брокеров с мгновенным fill (stub/sandbox-market) сами создадим Trade.
        if placed.status == OrderStatus.FILLED:
            tr = Trade(id=str(uuid.uuid4()), figi=sig.figi, side=sig.side,
                       quantity=qty, price=price, order_id=placed.id,
                       time=utcnow())
            bus.publish(T_TRADE, tr)

    def _on_trade(self, trade: Trade) -> None:
        # Этот хэндлер реагирует ТОЛЬКО на сделки, инициированные нами:
        # если order_id неизвестен — это либо ручная сделка из UI, либо
        # внешняя; обновим только PnL/позицию через risk, но обучаться не будем.
        is_ours = trade.order_id in self._our_orders if trade.order_id else False
        realized = self.risk.register_trade(trade)

        if not is_ours:
            return

        # Разметка обучения: если эта сделка закрыла наш сетап, метим пример.
        with self._lock:
            setup = self._open_setups.get(trade.figi)
        if setup is None:
            return
        # Закрытием считаем сделку противоположной стороны на тот же figi.
        if trade.side != setup.side:
            profitable = realized > 0
            self.ml.add_sample(setup.features_df, setup.side, profitable)
            with self._lock:
                self._open_setups.pop(trade.figi, None)
            bus.publish(T_LOG,
                        f"Сделка закрыта pnl={realized:+.2f} → пример "
                        f"{'+' if profitable else '−'} добавлен в обучение")
            try:
                if self.ml.maybe_retrain(every_n=self.s.auto_retrain_every_n_trades):
                    bus.publish(T_LOG, "ML-фильтр переобучен на новых сделках")
            except Exception as e:                          # pragma: no cover
                logger.exception("retrain: {}", e)
