"""Виджет графика свечей с уровнями цены покупок/продаж и историей сделок.

Поправлено:
- защита от NaN/Inf и нулевой высоты свечи (минимальная высота для отрисовки);
- boundingRect честно отдаёт прямоугольник picture, а не нулевой;
- маркеры сделок индексируются по позиции бара (np.argmin по timestamp).
"""
from __future__ import annotations

from datetime import datetime, timezone

import math
import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets

from tbot.core.models import Candle, Side, Trade


# ---------------- CandlestickItem ----------------

class CandlestickItem(pg.GraphicsObject):
    def __init__(self) -> None:
        super().__init__()
        self._picture: QtGui.QPicture | None = None
        self._data: list[tuple[int, float, float, float, float]] = []

    def set_candles(self, candles: list[Candle]) -> None:
        clean = []
        for i, c in enumerate(candles):
            o, h, l, cl = float(c.open), float(c.high), float(c.low), float(c.close)
            if any(map(_bad_num, (o, h, l, cl))):
                continue
            # на всякий случай нормализуем h/l
            h = max(h, o, cl); l = min(l, o, cl)
            clean.append((i, o, h, l, cl))
        self._data = clean
        self._rebuild()

    def _rebuild(self) -> None:
        pic = QtGui.QPicture()
        p = QtGui.QPainter(pic)
        try:
            w = 0.4
            for x, o, h, l, c in self._data:
                up = c >= o
                color = QtGui.QColor("#2ecc71") if up else QtGui.QColor("#e74c3c")
                p.setPen(pg.mkPen(color, width=1))
                p.drawLine(QtCore.QPointF(x, l), QtCore.QPointF(x, h))
                p.setBrush(pg.mkBrush(color))
                body_h = max(abs(c - o), 1e-6)
                p.drawRect(QtCore.QRectF(x - w, min(o, c), 2 * w, body_h))
        finally:
            p.end()
        self._picture = pic
        self.prepareGeometryChange()
        self.update()

    def paint(self, painter, *_):
        if self._picture is not None:
            painter.drawPicture(0, 0, self._picture)

    def boundingRect(self):
        if self._picture is None or not self._data:
            return QtCore.QRectF()
        xs = [d[0] for d in self._data]
        highs = [d[2] for d in self._data]
        lows = [d[3] for d in self._data]
        return QtCore.QRectF(min(xs) - 1, min(lows), (max(xs) - min(xs)) + 2,
                             max(highs) - min(lows))


def _bad_num(x: float) -> bool:
    try:
        return math.isnan(x) or math.isinf(x)
    except Exception:
        return True


# ---------------- ChartWidget ----------------

class ChartWidget(QtWidgets.QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(300)
        self._candles: list[Candle] = []
        self._trades: list[Trade] = []
        self._levels: dict[Side, list[float]] = {Side.BUY: [], Side.SELL: []}

        layout = QtWidgets.QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)

        pg.setConfigOptions(antialias=True, background="#0f1216", foreground="#9aa3b1")
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.getAxis("left").setStyle(tickFont=QtGui.QFont("Segoe UI", 9))
        layout.addWidget(self.plot)

        self.candles_item = CandlestickItem(); self.plot.addItem(self.candles_item)
        self._level_lines: list[pg.InfiniteLine] = []
        self._trade_scatter = pg.ScatterPlotItem(size=12, pen=None)
        self.plot.addItem(self._trade_scatter)

        self._crosshair_v = pg.InfiniteLine(angle=90, movable=False,
                                            pen=pg.mkPen("#555", style=QtCore.Qt.PenStyle.DashLine))
        self._crosshair_h = pg.InfiniteLine(angle=0, movable=False,
                                            pen=pg.mkPen("#555", style=QtCore.Qt.PenStyle.DashLine))
        self.plot.addItem(self._crosshair_v, ignoreBounds=True)
        self.plot.addItem(self._crosshair_h, ignoreBounds=True)
        self.plot.scene().sigMouseMoved.connect(self._on_mouse_move)

    # ---------- API ----------
    def set_candles(self, candles: list[Candle]) -> None:
        # фильтрация мусора
        self._candles = [c for c in candles
                         if not any(map(_bad_num, (c.open, c.high, c.low, c.close)))]
        self.candles_item.set_candles(self._candles)
        self._refresh_trade_markers()
        if self._candles:
            n = len(self._candles)
            self.plot.setXRange(max(0, n - 120), n + 2, padding=0)
            window = self._candles[-120:]
            ys = [c.low for c in window] + [c.high for c in window]
            ys = [y for y in ys if not _bad_num(y)]
            if ys:
                lo, hi = min(ys), max(ys)
                if hi == lo:
                    hi = lo + 1.0
                self.plot.setYRange(lo, hi, padding=0.05)

    def add_candle(self, candle: Candle) -> None:
        if _bad_num(candle.open) or _bad_num(candle.close):
            return
        if self._candles and self._candles[-1].time == candle.time:
            self._candles[-1] = candle
        else:
            self._candles.append(candle)
            if len(self._candles) > 1000:
                self._candles = self._candles[-1000:]
        self.candles_item.set_candles(self._candles)

    def set_levels(self, buys: list[float], sells: list[float]) -> None:
        self._levels = {Side.BUY: buys, Side.SELL: sells}
        for ln in self._level_lines:
            self.plot.removeItem(ln)
        self._level_lines.clear()
        for p in buys:
            if _bad_num(p): continue
            ln = pg.InfiniteLine(pos=p, angle=0,
                                 pen=pg.mkPen("#2ecc71", width=1,
                                              style=QtCore.Qt.PenStyle.DashLine),
                                 label=f"BUY @ {p:.4f}",
                                 labelOpts={"position": 0.02, "color": "#2ecc71",
                                            "fill": (0, 0, 0, 120)})
            self.plot.addItem(ln); self._level_lines.append(ln)
        for p in sells:
            if _bad_num(p): continue
            ln = pg.InfiniteLine(pos=p, angle=0,
                                 pen=pg.mkPen("#e74c3c", width=1,
                                              style=QtCore.Qt.PenStyle.DashLine),
                                 label=f"SELL @ {p:.4f}",
                                 labelOpts={"position": 0.98, "color": "#e74c3c",
                                            "fill": (0, 0, 0, 120)})
            self.plot.addItem(ln); self._level_lines.append(ln)

    def set_trades(self, trades: list[Trade]) -> None:
        self._trades = list(trades)
        self._refresh_trade_markers()

    def _refresh_trade_markers(self) -> None:
        if not self._candles:
            self._trade_scatter.setData([])
            return
        times = np.array([_ts(c.time) for c in self._candles], dtype=float)
        spots = []
        for t in self._trades:
            target = _ts(t.time)
            if not times.size:
                continue
            idx = int(np.argmin(np.abs(times - target)))
            color = "#2ecc71" if t.side == Side.BUY else "#e74c3c"
            symbol = "t1" if t.side == Side.BUY else "t"
            spots.append({"pos": (idx, t.price), "size": 14,
                          "brush": pg.mkBrush(color), "symbol": symbol,
                          "pen": pg.mkPen("#0f1216", width=1)})
        self._trade_scatter.setData(spots)

    def _on_mouse_move(self, pos) -> None:
        if not self._candles:
            return
        vb = self.plot.getPlotItem().vb
        mp = vb.mapSceneToView(pos)
        self._crosshair_v.setPos(mp.x())
        self._crosshair_h.setPos(mp.y())


def _ts(dt: datetime) -> float:
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0
