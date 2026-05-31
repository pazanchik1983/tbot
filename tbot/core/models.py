"""Доменные модели: свеча, инструмент, сигнал, ордер, сделка.

Все datetime — tz-aware UTC (см. tbot.core.timeutil).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

from tbot.core.timeutil import utcnow


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderStatus(str, Enum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(slots=True)
class Instrument:
    figi: str
    ticker: str
    name: str
    lot: int = 1
    currency: str = "RUB"
    kind: Literal["bond", "share", "future", "currency"] = "bond"
    # специфика облигаций
    nominal: float | None = None
    aci_value: float | None = None        # НКД
    maturity: datetime | None = None      # дата погашения
    coupon_quantity_per_year: int | None = None
    min_price_increment: float = 0.0001   # шаг цены


@dataclass(slots=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(slots=True)
class Signal:
    figi: str
    side: Side
    confidence: float           # 0..1 (мета-фильтр ML)
    reason: str                 # человекочитаемое объяснение
    price_hint: float | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class Order:
    id: str
    figi: str
    side: Side
    quantity: int               # лоты
    price: float | None         # None = по рынку
    status: OrderStatus = OrderStatus.NEW
    created_at: datetime = field(default_factory=utcnow)
    broker_order_id: str | None = None


@dataclass(slots=True)
class Trade:
    """Исполненная сделка (фактическая, после fill)."""
    id: str
    figi: str
    side: Side
    quantity: int
    price: float
    fee: float = 0.0
    pnl: float | None = None    # PnL после закрытия (заполняется ядром)
    time: datetime = field(default_factory=utcnow)
    order_id: str | None = None


@dataclass(slots=True)
class Position:
    figi: str
    quantity: int               # лоты, может быть отрицательной для шорта
    avg_price: float
    unrealized_pnl: float = 0.0
