"""Фабрика брокеров."""
from __future__ import annotations

from loguru import logger

from tbot.brokers.base import BrokerBase
from tbot.brokers.stub_broker import StubBroker
from tbot.core.config import Settings, get_api_token


def make_broker(settings: Settings) -> BrokerBase:
    name = settings.broker
    token = get_api_token(name) or ""

    if name == "tinkoff":
        try:
            from tbot.brokers.tinkoff_broker import TinkoffBroker
        except Exception as e:                                 # pragma: no cover
            logger.error("TinkoffBroker недоступен ({}). Использую stub.", e)
            return StubBroker(label="tinkoff-fallback")
        return TinkoffBroker(token=token, sandbox=settings.sandbox,
                             account_id=settings.account_id)

    if name in ("finam_stub", "bcs_stub"):
        logger.warning("{} пока stub — используется демо-брокер", name)
        return StubBroker(label=name)

    if name == "stub":
        return StubBroker()

    raise ValueError(f"Неизвестный брокер: {name}")
