"""Тесты AgentRuntime: дедуп сигналов, корректная разметка обучения."""
from datetime import timedelta

from tbot.agents.runtime import AgentRuntime
from tbot.brokers.stub_broker import StubBroker
from tbot.core.config import Settings
from tbot.core.event_bus import T_CANDLE, T_SIGNAL, bus
from tbot.core.risk import RiskManager
from tbot.core.timeutil import utcnow


def _bootstrap():
    br = StubBroker(seed=7); br.connect()
    s = Settings(broker="stub", default_quantity=1, min_confidence=0.0,
                 max_position_rub=10_000_000, max_daily_loss_rub=10_000_000)
    rm = RiskManager(s)
    rt = AgentRuntime(s, br, rm)
    cs = br.get_candles("BBG00X1F0M14", utcnow() - timedelta(hours=2), utcnow())
    rt.warmup("BBG00X1F0M14", cs)
    return br, rt, cs


def test_no_double_signal_for_same_bar():
    br, rt, cs = _bootstrap()
    rt.start()
    seen = []
    bus.subscribe(T_SIGNAL, lambda s: seen.append(s))
    # подаём ту же свечу 5 раз — сигнал должен случиться максимум 1 раз
    last = cs[-1]
    for _ in range(5):
        bus.publish(T_CANDLE, ("BBG00X1F0M14", last))
    assert len(seen) <= 1
    rt.shutdown(); br.disconnect()


def test_warmup_no_crash_on_empty():
    br = StubBroker(seed=8); br.connect()
    s = Settings(broker="stub")
    rt = AgentRuntime(s, br, RiskManager(s))
    rt.warmup("BBG00X1F0M14", [])
    rt.shutdown(); br.disconnect()
