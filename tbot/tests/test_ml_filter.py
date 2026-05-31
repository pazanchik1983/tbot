"""Тесты ML-фильтра."""
from datetime import timedelta

from tbot.agents.features import candles_to_df
from tbot.agents.ml_filter import MLFilter
from tbot.brokers.stub_broker import StubBroker
from tbot.core.models import Side
from tbot.core.timeutil import utcnow


def test_predict_neutral_when_no_model():
    b = StubBroker(seed=3); b.connect()
    cs = b.get_candles("BBG00X1F0M14", utcnow() - timedelta(hours=2), utcnow())
    df = candles_to_df(cs)
    ml = MLFilter(broker="test_unit_a")
    p = ml.predict_proba(df, Side.BUY)
    assert p == 0.5    # нейтрально без модели
    b.disconnect()


def test_retrain_skips_single_class():
    b = StubBroker(seed=4); b.connect()
    cs = b.get_candles("BBG00X1F0M14", utcnow() - timedelta(hours=4), utcnow())
    df = candles_to_df(cs)
    ml = MLFilter(broker="test_unit_b")
    for _ in range(25):                          # все profitable=True
        ml.add_sample(df, Side.BUY, profitable=True)
    assert ml.retrain() is False                 # один класс → не обучаемся
    assert ml.model is None


def test_retrain_two_classes_ok():
    b = StubBroker(seed=5); b.connect()
    cs = b.get_candles("BBG00X1F0M14", utcnow() - timedelta(hours=4), utcnow())
    df = candles_to_df(cs)
    ml = MLFilter(broker="test_unit_c")
    for i in range(40):
        ml.add_sample(df, Side.BUY if i % 2 == 0 else Side.SELL,
                      profitable=(i % 3 == 0))
    assert ml.retrain() is True
    p = ml.predict_proba(df, Side.BUY)
    assert 0.0 <= p <= 1.0
