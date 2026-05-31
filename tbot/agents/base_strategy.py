"""Базовая стратегия: ансамбль индикаторов.

Возвращает RawSignal: сторону (или None) + силу 0..1 + объяснение.
ML-фильтр уже решает, исполнять ли сигнал.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from tbot.agents.features import compute_features
from tbot.core.models import Side


@dataclass
class RawSignal:
    side: Side | None
    strength: float
    reasons: list[str] = field(default_factory=list)


# Веса голосов (можно подбирать на бэктесте)
_W_RSI = 1.0
_W_MACD = 0.7
_W_EMA = 0.6
_W_BB = 0.5
_W_TOTAL = _W_RSI + _W_MACD + _W_EMA + _W_BB     # для нормировки силы

# Порог входа по сырой стратегии (до ML-фильтра)
_MIN_STRENGTH = 0.35


def indicator_signal(df: pd.DataFrame) -> RawSignal:
    feats = compute_features(df)
    if feats.empty:
        return RawSignal(None, 0.0, ["мало данных"])

    last = feats.iloc[-1]
    score = 0.0
    reasons: list[str] = []

    rsi = float(last["rsi_14"])
    if rsi < 0.30:
        score += _W_RSI
        reasons.append(f"RSI={rsi*100:.1f} (перепродан)")
    elif rsi > 0.70:
        score -= _W_RSI
        reasons.append(f"RSI={rsi*100:.1f} (перекуплен)")

    macd_diff = float(last["macd_diff"])
    if macd_diff > 0:
        score += _W_MACD;  reasons.append("MACD-hist > 0")
    elif macd_diff < 0:
        score -= _W_MACD;  reasons.append("MACD-hist < 0")

    if last["ema_fast_dist"] > 0 and last["ema_slow_dist"] > 0:
        score += _W_EMA;   reasons.append("Цена > EMA9 и EMA21")
    elif last["ema_fast_dist"] < 0 and last["ema_slow_dist"] < 0:
        score -= _W_EMA;   reasons.append("Цена < EMA9 и EMA21")

    bb = float(last["bb_pos"])
    if bb < 0.05:
        score += _W_BB;    reasons.append("Касание нижней BB")
    elif bb > 0.95:
        score -= _W_BB;    reasons.append("Касание верхней BB")

    strength = min(abs(score) / _W_TOTAL, 1.0)
    if strength < _MIN_STRENGTH:
        return RawSignal(None, strength, reasons + ["сигнал слабый"])
    return RawSignal(Side.BUY if score > 0 else Side.SELL, strength, reasons)
