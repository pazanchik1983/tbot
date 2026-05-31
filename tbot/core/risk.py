"""Риск-менеджмент.

Контролирует:
  - дневной лимит убытка;
  - максимальный размер позиции в рублях по инструменту;
  - суммарный размер всех позиций (gross exposure).
"""
from __future__ import annotations

from datetime import date

from loguru import logger

from tbot.core.config import Settings
from tbot.core.models import Order, Side, Trade


class RiskManager:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._daily_pnl: float = 0.0
        self._today: date = date.today()
        # позиция по figi: (qty_lots_signed, avg_price)
        self._positions: dict[str, tuple[int, float]] = {}

    # ---------- внутреннее ----------
    def _rollover(self) -> None:
        if date.today() != self._today:
            self._today = date.today()
            self._daily_pnl = 0.0

    # ---------- учёт фактических сделок ----------
    def register_trade(self, t: Trade) -> float:
        """Обновляет позицию и возвращает реализованный PnL по этой сделке."""
        self._rollover()
        qty, avg = self._positions.get(t.figi, (0, 0.0))
        signed = t.side.sign * t.quantity
        realized = 0.0

        # Если сделка уменьшает текущую позицию — это закрытие
        if qty != 0 and (qty > 0) != (signed > 0):
            closing = min(abs(qty), abs(signed))
            realized = (t.price - avg) * (1 if qty > 0 else -1) * closing - t.fee
            new_qty = qty + signed
            if (qty > 0 and new_qty < 0) or (qty < 0 and new_qty > 0):
                # переворот: оставшийся хвост — новая позиция по цене сделки
                avg = t.price
            elif new_qty == 0:
                avg = 0.0
            # avg при простом уменьшении не меняется
            qty = new_qty
        else:
            # наращивание: пересчитываем среднюю
            new_qty = qty + signed
            if new_qty == 0:
                avg = 0.0
            else:
                avg = ((avg * qty) + (t.price * signed)) / new_qty if qty != 0 else t.price
            qty = new_qty

        self._positions[t.figi] = (qty, avg)
        self._daily_pnl += realized
        t.pnl = realized
        return realized

    # ---------- проверка перед ордером ----------
    def check_order(self, order: Order, ref_price: float) -> tuple[bool, str]:
        self._rollover()
        if ref_price <= 0:
            return False, "Нет валидной цены для проверки риска"
        if order.quantity <= 0:
            return False, "Количество должно быть положительным"
        if self._daily_pnl <= -abs(self.s.max_daily_loss_rub):
            return False, f"Достигнут дневной лимит убытка {self.s.max_daily_loss_rub:.0f}₽"

        cur_qty, _ = self._positions.get(order.figi, (0, 0.0))
        new_qty = cur_qty + order.side.sign * order.quantity
        new_notional = abs(new_qty) * ref_price
        if new_notional > self.s.max_position_rub:
            return False, (f"Превышен лимит позиции по {order.figi}: "
                           f"{new_notional:.0f} > {self.s.max_position_rub:.0f}₽")

        gross = sum(abs(q) * ref_price for q, _ in self._positions.values())
        if gross + abs(order.quantity) * ref_price > self.s.max_position_rub * 4:
            return False, "Превышен суммарный лимит экспозиции (4× max_position)"
        return True, "ok"

    # ---------- наблюдатели ----------
    def daily_pnl(self) -> float:
        self._rollover()
        return self._daily_pnl

    def position(self, figi: str) -> tuple[int, float]:
        return self._positions.get(figi, (0, 0.0))
