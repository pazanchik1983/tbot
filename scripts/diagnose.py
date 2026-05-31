"""Диагностический прогон против API Т-Инвестиций.

Запуск (Linux/Mac):
    TINKOFF_TOKEN='t.xxxxx' python -m scripts.diagnose --sandbox
Запуск (Windows PowerShell):
    $env:TINKOFF_TOKEN='t.xxxxx'; python -m scripts.diagnose --sandbox

Флаги:
    --sandbox           использовать песочницу (рекомендуется)
    --live              использовать боевой контур (только чтение — ордера выключены)
    --allow-orders      разрешить выставление 1 виртуального ордера в песочнице
    --bonds-limit N     ограничить число ОФЗ при перечислении (по умолчанию 5)
    --hours N           глубина истории свечей в часах (по умолчанию 4)

Скрипт НЕ сохраняет токен на диск, читает только из переменной окружения.
Все суммы — символические; в боевом режиме ордера не выставляются вообще.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import timedelta

from tbot.core.timeutil import utcnow

REPORT: list[tuple[str, bool, str]] = []   # (имя_шага, ok, детали)


def step(name: str):
    """Декоратор, который заворачивает шаг в try/except и пишет в отчёт."""
    def deco(fn):
        def wrapper(*a, **kw):
            t0 = time.perf_counter()
            print(f"\n▶ {name} ... ", end="", flush=True)
            try:
                res = fn(*a, **kw)
                dt = (time.perf_counter() - t0) * 1000
                print(f"OK ({dt:.0f} ms)")
                REPORT.append((name, True, f"{dt:.0f} ms"))
                return res
            except Exception as e:
                dt = (time.perf_counter() - t0) * 1000
                tb = traceback.format_exc(limit=3)
                print(f"FAIL ({dt:.0f} ms)\n{tb}")
                REPORT.append((name, False, f"{type(e).__name__}: {e}"))
                return None
        return wrapper
    return deco


@dataclass
class Args:
    sandbox: bool
    live: bool
    allow_orders: bool
    bonds_limit: int
    hours: int


def parse_args() -> Args:
    p = argparse.ArgumentParser()
    p.add_argument("--sandbox", action="store_true")
    p.add_argument("--live", action="store_true")
    p.add_argument("--allow-orders", action="store_true")
    p.add_argument("--bonds-limit", type=int, default=5)
    p.add_argument("--hours", type=int, default=4)
    ns = p.parse_args()
    if not ns.sandbox and not ns.live:
        ns.sandbox = True
    if ns.sandbox and ns.live:
        sys.exit("Выберите либо --sandbox, либо --live")
    return Args(ns.sandbox, ns.live, ns.allow_orders, ns.bonds_limit, ns.hours)


def main() -> int:
    args = parse_args()
    token = os.environ.get("TINKOFF_TOKEN") or os.environ.get("TBOT_TOKEN")
    if not token:
        sys.exit("Не задан TINKOFF_TOKEN (env). См. инструкцию в шапке файла.")

    # Маскируем токен в выводе, чтобы случайно не попал в логи
    print(f"Токен: {token[:4]}…{token[-4:]} ({len(token)} символов)")
    print(f"Режим: {'SANDBOX' if args.sandbox else 'LIVE (read-only)'}")
    print(f"Allow orders: {args.allow_orders and args.sandbox}")

    from tbot.brokers.tinkoff_broker import TinkoffBroker, _SDK_OK
    if not _SDK_OK:
        sys.exit("Не установлен пакет tinkoff-investments. pip install -r requirements.txt")

    br = TinkoffBroker(token=token, sandbox=args.sandbox)

    @step("Подключение (Client init + аккаунты)")
    def s_connect():
        br.connect()
        return br.account_id

    account_id = s_connect()

    @step("list_bonds (загрузка всех облигаций)")
    def s_bonds():
        bonds = br.list_bonds()
        return bonds

    bonds = s_bonds() or []
    print(f"   всего облигаций: {len(bonds)}")

    @step("list_ofz (фильтр ОФЗ)")
    def s_ofz():
        ofz = br.list_ofz()
        return ofz

    ofz = s_ofz() or []
    print(f"   ОФЗ найдено: {len(ofz)}")
    for b in ofz[:args.bonds_limit]:
        print(f"     - {b.ticker:10s} {b.figi:15s} {b.name}")

    if not ofz:
        print("\n⚠ ОФЗ не найдены — дальше идём на первой попавшейся облигации.")
        sample = bonds[:1]
    else:
        sample = ofz[:1]
    if not sample:
        print("Нет инструментов для дальнейших проверок.")
        return _summary()
    figi = sample[0].figi
    print(f"\nИнструмент для проверок: {sample[0].ticker} ({figi})")

    @step(f"get_candles 1m за {args.hours}ч")
    def s_candles():
        end = utcnow(); start = end - timedelta(hours=args.hours)
        cs = br.get_candles(figi, start, end, "1m")
        if cs:
            print(f"   получено {len(cs)} свечей, "
                  f"первая {cs[0].time.isoformat()}, последняя {cs[-1].time.isoformat()}")
        return cs

    candles = s_candles() or []

    @step("get_last_price")
    def s_last():
        p = br.get_last_price(figi)
        print(f"   last={p}")
        return p

    s_last()

    @step("list_positions")
    def s_pos():
        pos = br.list_positions()
        print(f"   позиций: {len(pos)}")
        return pos

    s_pos()

    @step("list_trades (последние 7 дней)")
    def s_trades():
        tr = br.list_trades()
        print(f"   сделок: {len(tr)}")
        return tr

    s_trades()

    # Ордер — только если разрешено и только в песочнице
    if args.sandbox and args.allow_orders:
        import uuid
        from tbot.core.models import Order, Side

        @step("post_sandbox_order (1 лот, market, BUY)")
        def s_order():
            o = Order(id=str(uuid.uuid4()), figi=figi, side=Side.BUY,
                      quantity=1, price=None)
            placed = br.place_order(o)
            print(f"   order_id={placed.id}, broker_order_id={placed.broker_order_id}, "
                  f"status={placed.status.value}")
            return placed

        s_order()

    # Мини-бэктест на свежих свечах (если хватает)
    if candles and len(candles) > 70:
        from tbot.agents.backtest import backtest

        @step("Бэктест стратегии на загруженных свечах")
        def s_bt():
            res = backtest(candles, fee_per_trade=0.0, slippage=0.0)
            print(f"   bars={res.n_bars} trades={res.n_trades} "
                  f"pnl={res.total_pnl:+.4f} maxDD={res.max_drawdown:.4f} "
                  f"win%={res.win_rate*100:.1f}")
            return res

        s_bt()

    br.disconnect()
    return _summary()


def _summary() -> int:
    print("\n" + "=" * 60)
    print("ИТОГ:")
    fails = 0
    for name, ok, detail in REPORT:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name:48s} {detail}")
        if not ok:
            fails += 1
    print(f"\nВсего шагов: {len(REPORT)}, провалов: {fails}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
