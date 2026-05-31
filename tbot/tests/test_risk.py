"""Тесты риск-менеджера: лимиты, корректный учёт PnL и средней цены."""
from tbot.core.config import Settings
from tbot.core.models import Order, Side, Trade
from tbot.core.risk import RiskManager
from tbot.core.timeutil import utcnow


def _t(side, qty, price, fee=0.0):
    import uuid
    return Trade(id=str(uuid.uuid4()), figi="X", side=side, quantity=qty,
                 price=price, fee=fee, time=utcnow())


def _ord(side, qty):
    import uuid
    return Order(id=str(uuid.uuid4()), figi="X", side=side, quantity=qty, price=None)


def test_open_then_close_realizes_correct_pnl():
    rm = RiskManager(Settings(max_position_rub=10_000, max_daily_loss_rub=10_000))
    # купили 2 по 100
    rm.register_trade(_t(Side.BUY, 2, 100.0))
    # продали 2 по 105 → PnL = (105-100)*2 = +10
    pnl = rm.register_trade(_t(Side.SELL, 2, 105.0))
    assert pnl == 10.0
    assert rm.daily_pnl() == 10.0
    assert rm.position("X") == (0, 0.0)


def test_average_price_on_increase():
    rm = RiskManager(Settings(max_position_rub=10_000, max_daily_loss_rub=10_000))
    rm.register_trade(_t(Side.BUY, 1, 100.0))
    rm.register_trade(_t(Side.BUY, 3, 110.0))
    qty, avg = rm.position("X")
    assert qty == 4
    # средняя: (100 + 110*3)/4 = 107.5
    assert abs(avg - 107.5) < 1e-9


def test_partial_close_keeps_avg_and_realizes_pnl():
    rm = RiskManager(Settings(max_position_rub=10_000, max_daily_loss_rub=10_000))
    rm.register_trade(_t(Side.BUY, 4, 100.0))    # avg 100
    pnl = rm.register_trade(_t(Side.SELL, 1, 110.0))   # частично продали
    assert pnl == 10.0
    qty, avg = rm.position("X")
    assert qty == 3 and avg == 100.0


def test_flip_long_to_short_resets_avg():
    rm = RiskManager(Settings(max_position_rub=100_000, max_daily_loss_rub=100_000))
    rm.register_trade(_t(Side.BUY, 2, 100.0))
    pnl = rm.register_trade(_t(Side.SELL, 5, 110.0))   # 2 закрытие + 3 шорт по 110
    assert pnl == (110.0 - 100.0) * 2
    qty, avg = rm.position("X")
    assert qty == -3
    assert avg == 110.0


def test_daily_loss_limit_blocks_orders():
    rm = RiskManager(Settings(max_position_rub=10_000, max_daily_loss_rub=5))
    rm.register_trade(_t(Side.BUY, 1, 100.0))
    rm.register_trade(_t(Side.SELL, 1, 90.0))     # PnL = -10, лимит = 5
    ok, why = rm.check_order(_ord(Side.BUY, 1), 100.0)
    assert ok is False and "лимит убытка" in why


def test_position_size_limit_blocks_orders():
    rm = RiskManager(Settings(max_position_rub=99, max_daily_loss_rub=10_000))
    ok, why = rm.check_order(_ord(Side.BUY, 1), 100.0)
    assert ok is False and "лимит позиции" in why
