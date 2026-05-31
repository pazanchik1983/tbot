"""Абстрактный брокер. Любой брокер (Т-Инвест/Финам/BCS) реализует этот интерфейс."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable, Iterable

from tbot.core.models import Candle, Instrument, Order, Position, Trade


class BrokerBase(ABC):
    name: str = "abstract"

    # ---- подключение ----
    @abstractmethod
    def connect(self) -> None: ...
    @abstractmethod
    def disconnect(self) -> None: ...
    @abstractmethod
    def is_connected(self) -> bool: ...

    # ---- справочники ----
    @abstractmethod
    def list_bonds(self) -> list[Instrument]:
        """Список доступных облигаций (ОФЗ среди прочего)."""

    def list_ofz(self) -> list[Instrument]:
        """ОФЗ = облигации с эмитентом 'Минфин РФ'. По умолчанию фильтр по тикеру SU/RU."""
        out = []
        for b in self.list_bonds():
            t = (b.ticker or "").upper()
            if t.startswith("SU") or "ОФЗ" in (b.name or "").upper():
                out.append(b)
        return out

    # ---- данные ----
    @abstractmethod
    def get_candles(self, figi: str, frm: datetime, to: datetime,
                    interval: str = "1m") -> list[Candle]: ...

    @abstractmethod
    def subscribe_candles(self, figis: Iterable[str], interval: str,
                          on_candle: Callable[[str, Candle], None]) -> None: ...

    @abstractmethod
    def get_last_price(self, figi: str) -> float | None: ...

    # ---- торговля ----
    @abstractmethod
    def place_order(self, order: Order) -> Order: ...
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...
    @abstractmethod
    def list_positions(self) -> list[Position]: ...
    @abstractmethod
    def list_trades(self, since: datetime | None = None) -> list[Trade]: ...
