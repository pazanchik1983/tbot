"""Простая потокобезопасная синхронная шина событий (pub/sub).

Поправлено:
- thread-safe регистрация/публикация под RLock;
- исключение в одном обработчике не ломает остальных;
- weak-режим публикации (копия списка) безопасен при unsubscribe внутри handler-а.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable

from loguru import logger

Handler = Callable[[Any], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            if handler not in self._subs[topic]:
                self._subs[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            if handler in self._subs.get(topic, []):
                self._subs[topic].remove(handler)

    def unsubscribe_all(self, topic: str | None = None) -> None:
        with self._lock:
            if topic is None:
                self._subs.clear()
            else:
                self._subs.pop(topic, None)

    def publish(self, topic: str, payload: Any = None) -> None:
        with self._lock:
            handlers = list(self._subs.get(topic, []))
        for h in handlers:
            try:
                h(payload)
            except Exception as e:                       # pragma: no cover
                logger.exception("Handler error on '{}': {}", topic, e)


# Топики
T_CANDLE = "market.candle"          # payload: (figi, Candle)
T_PRICE = "market.price"            # payload: (figi, last_price)
T_SIGNAL = "agent.signal"           # payload: Signal
T_ORDER_NEW = "order.new"           # payload: Order
T_ORDER_UPDATE = "order.update"     # payload: Order
T_TRADE = "trade.executed"          # payload: Trade
T_POSITION = "position.update"      # payload: Position
T_LOG = "ui.log"                    # payload: str
T_STATUS = "ui.status"              # payload: dict


bus = EventBus()
