"""Единая работа со временем — везде tz-aware UTC.

Цель: убрать DeprecationWarning от datetime.utcnow() и исключить
сравнение naive-времени из stub-брокера с aware-временем из gRPC-стрима
Т-Инвестиций (это типичный источник трудноуловимых багов).
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Текущий момент в UTC, всегда tz-aware."""
    return datetime.now(timezone.utc)


def ensure_aware(dt: datetime) -> datetime:
    """Если datetime без таймзоны — считаем, что это UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
