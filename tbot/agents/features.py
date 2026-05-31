"""Извлечение технических индикаторов из ряда свечей.

Особенности:
- все индикаторы безопасны к NaN/делению на ноль;
- последняя строка features всегда без NaN (для inference);
- если истории мало — вернёт пустой DataFrame.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import BollingerBands

FEATURE_COLS = [
    "ret_1", "ret_5", "ret_15",
    "rsi_14", "macd", "macd_signal", "macd_diff",
    "ema_fast_dist", "ema_slow_dist",
    "bb_pos", "atr_norm",
]

MIN_HISTORY = 35   # минимальное число свечей для надёжного расчёта


def candles_to_df(candles) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame([{"time": c.time, "open": float(c.open), "high": float(c.high),
                        "low": float(c.low), "close": float(c.close),
                        "volume": int(c.volume)} for c in candles])
    df = df.sort_values("time").drop_duplicates("time", keep="last").reset_index(drop=True)
    return df


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a.div(b.replace(0, np.nan))


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or len(df) < MIN_HISTORY:
        return pd.DataFrame(columns=FEATURE_COLS)
    out = pd.DataFrame(index=df.index)
    c = df["close"].astype(float)
    out["ret_1"] = c.pct_change(1)
    out["ret_5"] = c.pct_change(5)
    out["ret_15"] = c.pct_change(15)
    out["rsi_14"] = RSIIndicator(c, window=14, fillna=False).rsi() / 100.0
    macd = MACD(c, fillna=False)
    out["macd"] = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    out["macd_diff"] = macd.macd_diff()
    ema_fast = EMAIndicator(c, window=9, fillna=False).ema_indicator()
    ema_slow = EMAIndicator(c, window=21, fillna=False).ema_indicator()
    out["ema_fast_dist"] = _safe_div(c - ema_fast, c)
    out["ema_slow_dist"] = _safe_div(c - ema_slow, c)
    bb = BollingerBands(c, window=20, window_dev=2, fillna=False)
    width = (bb.bollinger_hband() - bb.bollinger_lband()).replace(0, np.nan)
    out["bb_pos"] = _safe_div(c - bb.bollinger_lband(), width)
    tr = (df["high"].astype(float) - df["low"].astype(float)).abs()
    out["atr_norm"] = _safe_div(tr.rolling(14).mean(), c)
    # Чистим бесконечности и NaN
    out = out[FEATURE_COLS].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out
