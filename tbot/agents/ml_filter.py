"""ML-фильтр самообучаемого агента.

Логика: базовая стратегия → RawSignal → этот фильтр предсказывает
P(сделка_прибыльная). Если P*strength ≥ порога → исполняем.

Самообучение: каждая закрытая сделка добавляется как обучающий пример
(features в момент входа + side → profitable y/n). Раз в N сделок
LightGBM-классификатор переобучается.

Защита от типовых багов:
- если в выборке только один класс — модель не обучаем, остаёмся
  в режиме "нейтрально 0.5";
- атомарная запись модели (через .tmp + replace);
- старая модель не используется, если набор фичей изменился.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

import warnings

import joblib
import numpy as np
import pandas as pd
from loguru import logger

# косметика: подавляем sklearn-предупреждение о feature names на чистом numpy
warnings.filterwarnings(
    "ignore",
    message="X does not have valid feature names.*",
    category=UserWarning,
)

try:
    from lightgbm import LGBMClassifier
    _LGB_OK = True
except Exception:                                # pragma: no cover
    _LGB_OK = False
    from sklearn.ensemble import GradientBoostingClassifier as LGBMClassifier  # type: ignore

from sklearn.preprocessing import StandardScaler

from tbot.agents.features import FEATURE_COLS, compute_features
from tbot.core.config import models_dir
from tbot.core.models import Side
from tbot.core.timeutil import utcnow

_NEUTRAL = 0.5
_MODEL_SCHEMA_VERSION = 1
_TRAIN_COLS = FEATURE_COLS + ["side"]


@dataclass
class TrainingSample:
    features: dict[str, float]
    side: Side
    profitable: bool
    created_at: datetime


class MLFilter:
    def __init__(self, broker: str = "tinkoff") -> None:
        self.broker = broker
        self.path = Path(models_dir()) / f"ml_filter_{broker}.pkl"
        self.model: Any | None = None
        self.scaler: StandardScaler | None = None
        self.samples: list[TrainingSample] = []
        self._lock = Lock()
        self._load()

    # ---------- persistence ----------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            blob = joblib.load(self.path)
            if blob.get("schema") != _MODEL_SCHEMA_VERSION:
                logger.warning("Старая версия модели — игнорирую (ребудем переобучение).")
                return
            self.model = blob["model"]
            self.scaler = blob["scaler"]
            self.samples = blob.get("samples", [])
            logger.info("ML-фильтр загружен: {} (samples={})",
                        self.path.name, len(self.samples))
        except Exception as e:                              # pragma: no cover
            logger.warning("Не удалось загрузить модель: {}", e)
            self.model = None; self.scaler = None

    def save(self) -> None:
        if self.model is None or self.scaler is None:
            return
        tmp = self.path.with_suffix(".tmp")
        try:
            joblib.dump({"schema": _MODEL_SCHEMA_VERSION,
                         "model": self.model, "scaler": self.scaler,
                         "samples": self.samples[-5000:]}, tmp)
            tmp.replace(self.path)
        except Exception as e:                              # pragma: no cover
            logger.error("save model: {}", e)
            if tmp.exists():
                try: tmp.unlink()
                except OSError: pass

    # ---------- inference ----------
    def predict_proba(self, df_candles: pd.DataFrame, side: Side) -> float:
        with self._lock:
            if self.model is None or self.scaler is None:
                return _NEUTRAL
            feats = compute_features(df_candles)
            if feats.empty:
                return _NEUTRAL
            x = feats.iloc[[-1]].copy()
            x["side"] = float(side.sign)
            try:
                X = self.scaler.transform(
                    np.asarray(x[_TRAIN_COLS].values, dtype=float))
                # На случай моделей, которые могли быть обучены при одном классе
                if not hasattr(self.model, "predict_proba"):
                    return _NEUTRAL
                probs = self.model.predict_proba(X)
                if probs.shape[1] < 2:                       # один класс
                    return _NEUTRAL
                return float(probs[0, 1])
            except Exception as e:                           # pragma: no cover
                logger.error("predict_proba: {}", e)
                return _NEUTRAL

    # ---------- learning ----------
    def add_sample(self, df_candles: pd.DataFrame, side: Side,
                   profitable: bool) -> None:
        feats = compute_features(df_candles)
        if feats.empty:
            return
        row = {k: float(v) for k, v in feats.iloc[-1].to_dict().items()}
        with self._lock:
            self.samples.append(TrainingSample(features=row, side=side,
                                               profitable=bool(profitable),
                                               created_at=utcnow()))

    def maybe_retrain(self, min_samples: int = 30, every_n: int = 20) -> bool:
        with self._lock:
            n = len(self.samples)
        if n < min_samples or n % every_n != 0:
            return False
        return self.retrain()

    def retrain(self) -> bool:
        with self._lock:
            samples = list(self.samples)
        if len(samples) < 20:
            logger.info("Слишком мало образцов для обучения ({}<20)", len(samples))
            return False

        rows = []
        for s in samples:
            r = dict(s.features)
            r["side"] = float(s.side.sign)
            r["y"] = int(s.profitable)
            rows.append(r)
        df = pd.DataFrame(rows)
        X = np.asarray(df[_TRAIN_COLS].values, dtype=float)
        y = np.asarray(df["y"].values, dtype=int)

        if len(np.unique(y)) < 2:
            logger.info("В выборке только один класс — пропускаю обучение.")
            return False

        # Скейлим и fit-им на безымянном numpy — иначе sklearn потом ругается
        # на отсутствие имён фичей при inference.
        scaler = StandardScaler()
        Xs = scaler.fit_transform(X)

        params = dict(n_estimators=200, learning_rate=0.05, max_depth=4,
                      random_state=42)
        if _LGB_OK:
            params.update(num_leaves=31, min_child_samples=5, verbose=-1)
        model = LGBMClassifier(**params)
        model.fit(Xs, y)
        try:
            acc = float(np.mean(model.predict(Xs) == y))
        except Exception:
            acc = float("nan")

        with self._lock:
            self.model = model
            self.scaler = scaler
            self.save()
        logger.info("ML-фильтр переобучен: samples={}, train_acc={:.3f}",
                    len(samples), acc)
        return True
