"""Адаптеры брокеров."""
from tbot.brokers.base import BrokerBase
from tbot.brokers.factory import make_broker

__all__ = ["BrokerBase", "make_broker"]
