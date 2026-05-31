"""Бэктест на синтетике от stub-брокера: проверяем структуру результата."""
from datetime import timedelta

from tbot.agents.backtest import backtest
from tbot.brokers.stub_broker import StubBroker
from tbot.core.timeutil import utcnow


def test_backtest_runs_on_stub():
    br = StubBroker(seed=11); br.connect()
    cs = br.get_candles("BBG00X1F0M14", utcnow() - timedelta(hours=12), utcnow())
    res = backtest(cs, fee_per_trade=0.0, slippage=0.0)
    assert res.n_bars == len(cs)
    assert res.n_trades >= 0
    assert isinstance(res.total_pnl, float)
    assert len(res.equity_curve) >= 1
    br.disconnect()


def test_backtest_no_trades_on_short_history():
    res = backtest([], warmup=60)
    assert res.n_trades == 0 and res.total_pnl == 0.0
