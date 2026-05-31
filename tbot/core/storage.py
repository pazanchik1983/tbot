"""Хранилище свечей, сделок, ордеров — SQLite через SQLAlchemy.

Поправлено:
- engine ленивый, thread-safe (`check_same_thread=False`);
- путь к БД можно подменить (полезно для тестов);
- запись/чтение в коротких сессиях, без долгоживущих транзакций.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock

from loguru import logger
from sqlalchemy import (Column, DateTime, Float, Integer, String, create_engine,
                        select)
from sqlalchemy.orm import DeclarativeBase, Session

from tbot.core.config import app_data_dir
from tbot.core.models import Side, Trade


class Base(DeclarativeBase):
    pass


class TradeRow(Base):
    __tablename__ = "trades"
    id = Column(String, primary_key=True)
    figi = Column(String, index=True)
    side = Column(String)
    quantity = Column(Integer)
    price = Column(Float)
    fee = Column(Float, default=0.0)
    pnl = Column(Float, nullable=True)
    time = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    order_id = Column(String, nullable=True)


class CandleRow(Base):
    __tablename__ = "candles"
    figi = Column(String, primary_key=True)
    time = Column(DateTime(timezone=True), primary_key=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Integer)


_engine = None
_engine_lock = Lock()
_db_path_override: Path | None = None


def set_db_path(p: Path | None) -> None:
    """Подменить путь к БД (для тестов). None — вернуть к дефолту."""
    global _db_path_override, _engine
    _db_path_override = p
    with _engine_lock:
        _engine = None


def _db_path() -> Path:
    return _db_path_override if _db_path_override else app_data_dir() / "tbot.db"


def engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            url = f"sqlite:///{_db_path()}"
            _engine = create_engine(
                url, future=True, echo=False,
                connect_args={"check_same_thread": False})
            Base.metadata.create_all(_engine)
            logger.debug("SQLite инициализирован: {}", _db_path())
        return _engine


def save_trade(t: Trade) -> None:
    with Session(engine()) as s:
        s.merge(TradeRow(
            id=t.id, figi=t.figi, side=t.side.value, quantity=t.quantity,
            price=t.price, fee=t.fee, pnl=t.pnl, time=t.time, order_id=t.order_id))
        s.commit()


def list_trades(figi: str | None = None, limit: int = 500) -> list[Trade]:
    with Session(engine()) as s:
        stmt = select(TradeRow).order_by(TradeRow.time.desc()).limit(limit)
        if figi:
            stmt = stmt.where(TradeRow.figi == figi)
        rows = s.execute(stmt).scalars().all()
        return [Trade(id=r.id, figi=r.figi, side=Side(r.side), quantity=r.quantity,
                      price=r.price, fee=r.fee or 0.0, pnl=r.pnl, time=r.time,
                      order_id=r.order_id) for r in rows]
