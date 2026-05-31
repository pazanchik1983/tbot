"""Заглушка-брокер для оффлайн-разработки, тестов и роли 'Финам/BCS' до реализации.

Поправлено:
- все datetime — tz-aware UTC;
- корректная остановка/перезапуск потоков (Event сбрасывается на connect);
- потоки помечены как daemon и собираются на disconnect();
- отдельный детерминистический seed для воспроизводимых тестов;
- цены не уплывают в отрицательные значения (для облигаций ограничение [50; 150]).
"""
from __future__ import annotations

import random
import threading
import time
import uuid
from datetime import timedelta
from typing import Callable, Iterable

from loguru import logger

from tbot.brokers.base import BrokerBase
from tbot.core.models import (Candle, Instrument, Order, OrderStatus, Position,
                              Side, Trade)
from tbot.core.timeutil import utcnow

_OFZ_DEMO = [
    Instrument(figi="BBG00X1F0M14", ticker="SU26238", name="ОФЗ 26238",
               lot=1, nominal=1000.0, kind="bond"),
    Instrument(figi="BBG00X1F0M15", ticker="SU26240", name="ОФЗ 26240",
               lot=1, nominal=1000.0, kind="bond"),
    Instrument(figi="BBG00X1F0M16", ticker="SU26243", name="ОФЗ 26243",
               lot=1, nominal=1000.0, kind="bond"),
]


class StubBroker(BrokerBase):
    name = "stub"

    def __init__(self, label: str = "stub", seed: int | None = None) -> None:
        self.label = label
        self._connected = False
        self._rng = random.Random(seed)
        self._prices: dict[str, float] = {i.figi: 98.0 + self._rng.random() * 4
                                          for i in _OFZ_DEMO}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._positions: dict[str, Position] = {}
        self._trades: list[Trade] = []
        self._lock = threading.RLock()

    # ---------- connect ----------
    def connect(self) -> None:
        self._stop.clear()
        self._connected = True

    def disconnect(self) -> None:
        self._stop.set()
        self._connected = False
        for th in self._threads:
            th.join(timeout=2.0)
        self._threads.clear()

    def is_connected(self) -> bool:
        return self._connected

    # ---------- инструменты ----------
    def list_bonds(self) -> list[Instrument]:
        return list(_OFZ_DEMO)

    # ---------- свечи ----------
    def _step_price(self, figi: str, sigma: float = 0.05) -> float:
        p = self._prices.get(figi, 99.0)
        p = max(50.0, min(150.0, p + self._rng.gauss(0, sigma)))
        self._prices[figi] = p
        return p

    def get_candles(self, figi, frm, to, interval="1m") -> list[Candle]:
        if frm > to:
            return []
        step = timedelta(minutes=1)
        out: list[Candle] = []
        t = frm
        # лимит, чтобы не зациклиться при некорректном диапазоне
        max_iter = 10_000
        i = 0
        while t < to and i < max_iter:
            o = self._prices.get(figi, 99.0)
            c = self._step_price(figi)
            h = max(o, c) + abs(self._rng.gauss(0, 0.03))
            l = min(o, c) - abs(self._rng.gauss(0, 0.03))
            out.append(Candle(time=t, open=o, high=h, low=l, close=c,
                              volume=self._rng.randint(10, 200)))
            t += step
            i += 1
        return out

    def subscribe_candles(self, figis: Iterable[str], interval: str,
                          on_candle: Callable[[str, Candle], None]) -> None:
        figis = list(figis)
        if not figis:
            return

        def loop():
            while not self._stop.is_set():
                for f in figis:
                    o = self._prices.get(f, 99.0)
                    c = self._step_price(f)
                    h = max(o, c) + abs(self._rng.gauss(0, 0.02))
                    l = min(o, c) - abs(self._rng.gauss(0, 0.02))
                    cnd = Candle(time=utcnow(), open=o, high=h, low=l, close=c,
                                 volume=self._rng.randint(5, 50))
                    try:
                        on_candle(f, cnd)
                    except Exception as e:                   # pragma: no cover
                        logger.exception("stub on_candle: {}", e)
                # короткий чувствительный sleep к остановке
                self._stop.wait(1.0)

        th = threading.Thread(target=loop, daemon=True, name=f"stub-stream-{id(figis)}")
        th.start()
        self._threads.append(th)

    def get_last_price(self, figi: str) -> float | None:
        return self._prices.get(figi)

    # ---------- ордеры ----------
    def place_order(self, order: Order) -> Order:
        with self._lock:
            order.broker_order_id = str(uuid.uuid4())
            order.status = OrderStatus.FILLED
            price = order.price or self._prices.get(order.figi, 99.0)
            tr = Trade(id=str(uuid.uuid4()), figi=order.figi, side=order.side,
                       quantity=order.quantity, price=price, order_id=order.id,
                       time=utcnow())
            self._trades.append(tr)
            pos = self._positions.get(order.figi, Position(figi=order.figi,
                                                           quantity=0, avg_price=0))
            signed = order.side.sign * order.quantity
            new_q = pos.quantity + signed
            if new_q == 0:
                pos.avg_price = 0.0
            elif pos.quantity == 0 or (pos.quantity > 0) == (signed > 0):
                # открытие/наращивание — пересчёт средней
                pos.avg_price = ((pos.avg_price * pos.quantity) + (price * signed)) / new_q
            # уменьшение — средняя не меняется
            pos.quantity = new_q
            self._positions[order.figi] = pos
        return order

    def cancel_order(self, order_id: str) -> bool:
        return True

    def list_positions(self) -> list[Position]:
        with self._lock:
            return [Position(figi=p.figi, quantity=p.quantity,
                             avg_price=p.avg_price) for p in self._positions.values()]

    def list_trades(self, since=None) -> list[Trade]:
        with self._lock:
            if since is None:
                return list(self._trades)
            return [t for t in self._trades if t.time >= since]
