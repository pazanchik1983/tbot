"""Тесты конфига и хранилища: roundtrip, валидация, неизвестные поля."""
from tbot.core.config import (Settings, delete_api_token, get_api_token,
                              load_settings, save_settings, set_api_token)
from tbot.core.models import Side, Trade
from tbot.core.storage import list_trades, save_trade
from tbot.core.timeutil import utcnow


def test_settings_roundtrip_and_validation(tmp_path):
    s = Settings(broker="tinkoff", default_quantity=0, max_position_rub=-10,
                 min_confidence=2.0, auto_retrain_every_n_trades=0)
    save_settings(s)
    loaded = load_settings()
    # валидация прошла
    assert loaded.default_quantity >= 1
    assert loaded.max_position_rub >= 0
    assert loaded.min_confidence <= 1.0
    assert loaded.auto_retrain_every_n_trades >= 1


def test_settings_ignores_unknown_fields():
    raw = '{"broker": "stub", "wtf": 123, "default_quantity": 5}'
    s = Settings.from_json(raw)
    assert s.broker == "stub" and s.default_quantity == 5


def test_token_set_get_delete_with_fallback():
    set_api_token("stub", "TOKEN_XYZ")
    assert get_api_token("stub") == "TOKEN_XYZ"
    delete_api_token("stub")
    assert get_api_token("stub") in (None, "")


def test_storage_save_and_list():
    t = Trade(id="abc", figi="X", side=Side.BUY, quantity=1, price=100.0,
              time=utcnow())
    save_trade(t)
    rows = list_trades(figi="X", limit=10)
    assert any(r.id == "abc" for r in rows)
