"""Опциональный REST/WebSocket-сервер для удалённого клиента (например, Android).

Запуск:
    python -m tbot.api.server  --host 0.0.0.0 --port 8765 --token MY_SHARED_SECRET

Endpoints (минимум для мобильного клиента):
    GET  /health
    GET  /instruments
    GET  /candles?figi=...&minutes=120
    GET  /trades?figi=...
    POST /orders     {figi, side, quantity, price?}
    GET  /status     состояние агента и PnL
    WS   /stream     поток сигналов/сделок/свечей

Авторизация: заголовок `X-Auth: <token>` (общий секрет).
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone

import uvicorn
from fastapi import (Depends, FastAPI, Header, HTTPException, WebSocket,
                     WebSocketDisconnect)
from pydantic import BaseModel

from tbot.brokers.factory import make_broker
from tbot.core.config import load_settings
from tbot.core.event_bus import T_CANDLE, T_SIGNAL, T_TRADE, bus
from tbot.core.models import Order, Side
from tbot.core.storage import list_trades

API_TOKEN = "change-me"
app = FastAPI(title="T-Bot API", version="0.1.0")
settings = load_settings()
broker = None


def require_token(x_auth: str | None = Header(default=None)) -> None:
    if x_auth != API_TOKEN:
        raise HTTPException(status_code=401, detail="bad token")


class OrderRequest(BaseModel):
    figi: str
    side: str          # "BUY" / "SELL"
    quantity: int
    price: float | None = None


@app.on_event("startup")
def _startup():
    global broker
    broker = make_broker(settings)
    try:
        broker.connect()
    except Exception as e:
        print("broker connect:", e)


@app.get("/health")
def health():
    return {"ok": True, "broker": settings.broker, "sandbox": settings.sandbox,
            "connected": bool(broker and broker.is_connected())}


@app.get("/instruments", dependencies=[Depends(require_token)])
def instruments():
    return [b.__dict__ for b in (broker.list_ofz() if broker else [])]


@app.get("/candles", dependencies=[Depends(require_token)])
def candles(figi: str, minutes: int = 120):
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    return [{"t": c.time.isoformat(), "o": c.open, "h": c.high,
             "l": c.low, "c": c.close, "v": c.volume}
            for c in (broker.get_candles(figi, start, end, "1m") if broker else [])]


@app.get("/trades", dependencies=[Depends(require_token)])
def trades(figi: str | None = None):
    return [t.__dict__ for t in list_trades(figi=figi, limit=200)]


@app.post("/orders", dependencies=[Depends(require_token)])
def post_order(req: OrderRequest):
    import uuid
    o = Order(id=str(uuid.uuid4()), figi=req.figi, side=Side(req.side),
              quantity=req.quantity, price=req.price)
    placed = broker.place_order(o)
    return {"id": placed.id, "status": placed.status.value,
            "broker_order_id": placed.broker_order_id}


@app.websocket("/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def push(topic, payload):
        try:
            loop.call_soon_threadsafe(queue.put_nowait,
                                      {"topic": topic, "data": str(payload)})
        except Exception:
            pass

    bus.subscribe(T_CANDLE, lambda p: push("candle", p))
    bus.subscribe(T_TRADE, lambda p: push("trade", p))
    bus.subscribe(T_SIGNAL, lambda p: push("signal", p))
    try:
        while True:
            msg = await queue.get()
            await ws.send_text(json.dumps(msg, default=str, ensure_ascii=False))
    except WebSocketDisconnect:
        return


def main():
    global API_TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default="change-me")
    args = ap.parse_args()
    API_TOKEN = args.token
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
