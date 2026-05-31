"""Дымовые тесты: импорты, базовая работа индикаторов и stub-брокера."""
from datetime import timedelta

from tbot.agents.base_strategy import indicator_signal
from tbot.agents.features import candles_to_df, compute_features
from tbot.brokers.stub_broker import StubBroker
from tbot.core.models import Side
from tbot.core.timeutil import utcnow


def test_imports():
    import tbot.core.config            # noqa: F401
    import tbot.core.event_bus         # noqa: F401
    import tbot.core.risk              # noqa: F401
    import tbot.core.storage           # noqa: F401
    import tbot.agents.ml_filter       # noqa: F401
    import tbot.agents.runtime         # noqa: F401
    import tbot.agents.backtest        # noqa: F401


def test_stub_broker_candles():
    b = StubBroker(seed=1); b.connect()
    candles = b.get_candles("BBG00X1F0M14",
                            utcnow() - timedelta(hours=2),
                            utcnow(), "1m")
    assert len(candles) > 60
    df = candles_to_df(candles)
    feats = compute_features(df)
    assert not feats.empty
    # никаких NaN/Inf
    assert feats.isna().sum().sum() == 0
    b.disconnect()


def test_indicator_signal_shape():
    b = StubBroker(seed=2); b.connect()
    candles = b.get_candles("BBG00X1F0M14",
                            utcnow() - timedelta(hours=6),
                            utcnow(), "1m")
    df = candles_to_df(candles)
    sig = indicator_signal(df)
    assert sig.side in (None, Side.BUY, Side.SELL)
    assert 0.0 <= sig.strength <= 1.0
    b.disconnect()
