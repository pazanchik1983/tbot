"""Простой векторизованный бэктест стратегии на исторических свечах.

Логика синхронизирована с AgentRuntime:
- по новой свече вычисляем RawSignal + (опционально) ML-фильтр;
- открытие/удержание/закрытие/переворот — как в рантайме;
- комиссия и проскальзывание задаются параметром;
- результат: total_pnl, число сделок, win-rate, max_drawdown.

Применение:
    from tbot.brokers.stub_broker import StubBroker
    from datetime import timedelta
    from tbot.core.timeutil import utcnow
    from tbot.agents.backtest import backtest

    br = StubBroker(seed=42); br.connect()
    cs = br.get_candles("BBG00X1F0M14", utcnow()-timedelta(days=3), utcnow())
    print(backtest(cs))
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from tbot.agents.base_strategy import indicator_signal
from tbot.agents.features import candles_to_df
from tbot.core.models import Candle, Side


@dataclass
class BacktestResult:
    n_bars: int
    n_trades: int
    wins: int
    losses: int
    total_pnl: float
    max_drawdown: float
    win_rate: float
    avg_pnl_per_trade: float
    equity_curve: list[float]

    def to_dict(self) -> dict:
        return asdict(self)


def backtest(candles: list[Candle], *,
             fee_per_trade: float = 0.0,
             slippage: float = 0.0,
             warmup: int = 60) -> BacktestResult:
    """Прогоняет стратегию по свечам и возвращает агрегированный результат."""
    if len(candles) <= warmup + 1:
        return BacktestResult(len(candles), 0, 0, 0, 0.0, 0.0, 0.0, 0.0, [0.0])

    equity = 0.0
    equity_curve: list[float] = [0.0]
    peak = 0.0
    max_dd = 0.0
    trades_pnls: list[float] = []
    pos_side: Side | None = None
    pos_entry: float = 0.0

    for i in range(warmup, len(candles)):
        window = candles[max(0, i - 300):i + 1]
        df = candles_to_df(window)
        raw = indicator_signal(df)
        price = float(candles[i].close)

        if pos_side is None:
            if raw.side is not None:
                pos_side = raw.side
                pos_entry = price + raw.side.sign * slippage
        else:
            # закрываем, если стратегия дала противоположный сигнал
            if raw.side is not None and raw.side != pos_side:
                exit_px = price - pos_side.sign * slippage   # неблагоприятная цена
                pnl = (exit_px - pos_entry) * pos_side.sign - fee_per_trade * 2
                equity += pnl
                trades_pnls.append(pnl)
                # переворот: сразу входим в противоположную сторону
                pos_side = raw.side
                pos_entry = price + raw.side.sign * slippage
        equity_curve.append(equity)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    # закрываем висящую позицию по последней цене
    if pos_side is not None:
        last_px = float(candles[-1].close) - pos_side.sign * slippage
        pnl = (last_px - pos_entry) * pos_side.sign - fee_per_trade * 2
        equity += pnl
        trades_pnls.append(pnl)
        equity_curve.append(equity)
        max_dd = max(max_dd, peak - equity)

    wins = sum(1 for p in trades_pnls if p > 0)
    losses = sum(1 for p in trades_pnls if p <= 0)
    n = len(trades_pnls)
    return BacktestResult(
        n_bars=len(candles), n_trades=n, wins=wins, losses=losses,
        total_pnl=float(equity),
        max_drawdown=float(max_dd),
        win_rate=float(wins / n) if n else 0.0,
        avg_pnl_per_trade=float(np.mean(trades_pnls)) if trades_pnls else 0.0,
        equity_curve=equity_curve,
    )
