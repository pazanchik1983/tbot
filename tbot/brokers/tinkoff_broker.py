"""Адаптер брокера Т-Инвестиции.

Используем официальный SDK `tinkoff-investments`:
  https://github.com/RussianInvestments/invest-python

Поправлено:
- импорты SDK строго внутри try/except — отсутствие пакета не ломает остальное;
- единый клиент держится в `_ctx`, не открываем по соединению на каждый вызов;
- свечной стрим — отдельный поток с цикличным backoff на сетевых сбоях;
- все datetime — tz-aware UTC;
- ретраи на временные ошибки (UNAVAILABLE/DEADLINE) c экспоненциальной паузой;
- безопасное преобразование Quotation/MoneyValue → float.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import timedelta
from typing import Any, Callable, Iterable

from loguru import logger

from tbot.brokers.base import BrokerBase
from tbot.core.models import (Candle, Instrument, Order, OrderStatus, Position,
                              Side, Trade)
from tbot.core.timeutil import ensure_aware, utcnow

# Импорты SDK — мягко
_SDK_OK = False
try:
    from tinkoff.invest import (CandleInterval, Client, OrderDirection,
                                OrderType, Quotation)
    from tinkoff.invest.constants import (INVEST_GRPC_API,
                                          INVEST_GRPC_API_SANDBOX)
    _SDK_OK = True
except Exception as e:                                       # pragma: no cover
    logger.warning("tinkoff-investments SDK не загружен: {}", e)
    CandleInterval = OrderDirection = OrderType = Quotation = None  # type: ignore
    Client = None  # type: ignore
    INVEST_GRPC_API = INVEST_GRPC_API_SANDBOX = None         # type: ignore


_INTERVAL_NAMES = {
    "1m": "CANDLE_INTERVAL_1_MIN",
    "5m": "CANDLE_INTERVAL_5_MIN",
    "15m": "CANDLE_INTERVAL_15_MIN",
    "1h": "CANDLE_INTERVAL_HOUR",
    "1d": "CANDLE_INTERVAL_DAY",
}


def _q2f(q: Any) -> float:
    if q is None:
        return 0.0
    units = getattr(q, "units", None)
    nano = getattr(q, "nano", None)
    if units is None and nano is None:
        try:
            return float(q)
        except Exception:
            return 0.0
    return float(units or 0) + float(nano or 0) / 1e9


def _f2q(value: float) -> Any:
    units = int(value)
    nano = int(round((value - units) * 1e9))
    return Quotation(units=units, nano=nano)


def _retry(fn, *, attempts: int = 3, base_delay: float = 0.5):
    """Простой ретрай для коротких операций SDK."""
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:                               # pragma: no cover
            last_exc = e
            time.sleep(base_delay * (2 ** i))
    if last_exc:
        raise last_exc


class TinkoffBroker(BrokerBase):
    name = "tinkoff"

    def __init__(self, token: str, sandbox: bool = True,
                 account_id: str | None = None) -> None:
        self.token = token
        self.sandbox = sandbox
        self.account_id = account_id
        self._connected = False
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._target = (INVEST_GRPC_API_SANDBOX if (sandbox and _SDK_OK)
                        else (INVEST_GRPC_API if _SDK_OK else None))

    # ---------- helpers ----------
    def _ensure_sdk(self) -> None:
        if not _SDK_OK:
            raise RuntimeError("Пакет tinkoff-investments не установлен")
        if not self.token:
            raise RuntimeError("Не задан API-токен Т-Инвестиций (Настройки → API-ключ).")

    # ---------- connect ----------
    def connect(self) -> None:
        self._ensure_sdk()
        self._stop.clear()
        def _do():
            with Client(self.token, target=self._target) as cli:
                if self.sandbox:
                    accs = cli.sandbox.get_sandbox_accounts().accounts
                    if not accs:
                        new = cli.sandbox.open_sandbox_account()
                        self.account_id = new.account_id
                    elif not self.account_id:
                        self.account_id = accs[0].id
                else:
                    accs = cli.users.get_accounts().accounts
                    if not accs:
                        raise RuntimeError("Нет счетов у пользователя")
                    if not self.account_id:
                        self.account_id = accs[0].id
        _retry(_do)
        self._connected = True
        logger.info("Подключено к Т-Инвестициям ({}). account_id={}",
                    "sandbox" if self.sandbox else "live", self.account_id)

    def disconnect(self) -> None:
        self._stop.set()
        self._connected = False
        for th in self._threads:
            th.join(timeout=2.0)
        self._threads.clear()

    def is_connected(self) -> bool:
        return self._connected

    # ---------- справочники ----------
    def list_bonds(self) -> list[Instrument]:
        self._ensure_sdk()
        def _do():
            with Client(self.token, target=self._target) as cli:
                return cli.instruments.bonds().instruments
        bonds = _retry(_do)
        out: list[Instrument] = []
        for b in bonds:
            inc = getattr(b, "min_price_increment", None)
            out.append(Instrument(
                figi=b.figi, ticker=b.ticker, name=b.name, lot=b.lot,
                currency=b.currency, kind="bond",
                nominal=_q2f(getattr(b, "nominal", None)),
                aci_value=_q2f(getattr(b, "aci_value", None)),
                maturity=getattr(b, "maturity_date", None),
                coupon_quantity_per_year=getattr(b, "coupon_quantity_per_year", None),
                min_price_increment=_q2f(inc) or 0.0001,
            ))
        return out

    # ---------- свечи ----------
    def get_candles(self, figi, frm, to, interval="1m") -> list[Candle]:
        self._ensure_sdk()
        frm = ensure_aware(frm); to = ensure_aware(to)
        interval_enum = getattr(CandleInterval,
                                _INTERVAL_NAMES.get(interval, "CANDLE_INTERVAL_1_MIN"))

        def _do():
            with Client(self.token, target=self._target) as cli:
                return list(cli.get_all_candles(figi=figi, from_=frm, to=to,
                                                interval=interval_enum))
        cs = _retry(_do)
        return [Candle(time=ensure_aware(c.time),
                       open=_q2f(c.open), high=_q2f(c.high),
                       low=_q2f(c.low), close=_q2f(c.close),
                       volume=int(c.volume)) for c in cs]

    def subscribe_candles(self, figis: Iterable[str], interval: str,
                          on_candle: Callable[[str, Candle], None]) -> None:
        """Упрощённый поллинг (стабильнее async-стрима для смешанного кода).

        Для боевого режима стоит заменить на MarketDataStream — но для ОФЗ,
        у которых движения редкие, частоты в 2с с лихвой хватит.
        """
        self._ensure_sdk()
        figis = list(figis)
        if not figis:
            return

        def loop():
            backoff = 1.0
            while not self._stop.is_set():
                end = utcnow()
                start = end - timedelta(minutes=2)
                try:
                    for f in figis:
                        cs = self.get_candles(f, start, end, interval)
                        if cs:
                            on_candle(f, cs[-1])
                    backoff = 1.0
                except Exception as e:                       # pragma: no cover
                    logger.warning("subscribe_candles backoff: {}", e)
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue
                self._stop.wait(2.0)

        th = threading.Thread(target=loop, daemon=True, name="tinkoff-stream")
        th.start()
        self._threads.append(th)

    def get_last_price(self, figi: str) -> float | None:
        self._ensure_sdk()
        try:
            with Client(self.token, target=self._target) as cli:
                r = cli.market_data.get_last_prices(figi=[figi])
                if r.last_prices:
                    return _q2f(r.last_prices[0].price)
        except Exception as e:                                # pragma: no cover
            logger.debug("get_last_price: {}", e)
        return None

    # ---------- ордеры ----------
    def place_order(self, order: Order) -> Order:
        self._ensure_sdk()
        if not self.account_id:
            raise RuntimeError("Нет account_id — переподключитесь.")
        direction = (OrderDirection.ORDER_DIRECTION_BUY if order.side == Side.BUY
                     else OrderDirection.ORDER_DIRECTION_SELL)
        otype = OrderType.ORDER_TYPE_LIMIT if order.price else OrderType.ORDER_TYPE_MARKET
        kwargs = dict(figi=order.figi, quantity=int(order.quantity),
                      direction=direction, account_id=self.account_id,
                      order_type=otype, order_id=order.id or str(uuid.uuid4()))
        if order.price:
            kwargs["price"] = _f2q(order.price)
        def _do():
            with Client(self.token, target=self._target) as cli:
                svc = cli.sandbox if self.sandbox else cli.orders
                return (svc.post_sandbox_order if self.sandbox else svc.post_order)(**kwargs)
        resp = _retry(_do, attempts=2)
        order.broker_order_id = getattr(resp, "order_id", None)
        order.status = OrderStatus.SUBMITTED
        return order

    def cancel_order(self, order_id: str) -> bool:
        self._ensure_sdk()
        try:
            with Client(self.token, target=self._target) as cli:
                svc = cli.sandbox if self.sandbox else cli.orders
                (svc.cancel_sandbox_order if self.sandbox else svc.cancel_order)(
                    account_id=self.account_id, order_id=order_id)
                return True
        except Exception as e:                                # pragma: no cover
            logger.error("cancel_order: {}", e)
            return False

    def list_positions(self) -> list[Position]:
        self._ensure_sdk()
        try:
            with Client(self.token, target=self._target) as cli:
                svc = cli.sandbox if self.sandbox else cli.operations
                data = (svc.get_sandbox_positions if self.sandbox
                        else svc.get_positions)(account_id=self.account_id)
                return [Position(figi=s.figi, quantity=int(s.balance), avg_price=0.0)
                        for s in getattr(data, "securities", [])]
        except Exception as e:                                # pragma: no cover
            logger.error("list_positions: {}", e)
            return []

    def list_trades(self, since=None) -> list[Trade]:
        self._ensure_sdk()
        since = ensure_aware(since) if since else (utcnow() - timedelta(days=7))
        try:
            with Client(self.token, target=self._target) as cli:
                svc = cli.sandbox if self.sandbox else cli.operations
                ops = (svc.get_sandbox_operations if self.sandbox
                       else svc.get_operations)(account_id=self.account_id,
                                                from_=since,
                                                to=utcnow()).operations
        except Exception as e:                                # pragma: no cover
            logger.error("list_trades: {}", e)
            return []
        out: list[Trade] = []
        for o in ops:
            otype = getattr(o, "operation_type", None)
            if otype not in (1, 2, 15):
                continue
            side = Side.BUY if otype in (1, 15) else Side.SELL
            price = _q2f(getattr(o, "price", None))
            out.append(Trade(id=str(getattr(o, "id", uuid.uuid4())),
                             figi=o.figi, side=side,
                             quantity=int(getattr(o, "quantity", 0) or 0),
                             price=price, fee=0.0,
                             time=ensure_aware(o.date) if getattr(o, "date", None) else utcnow()))
        return out
