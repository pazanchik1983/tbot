"""Настройка логирования (loguru, ротация в %APPDATA%/TBot/logs)."""
from __future__ import annotations

import sys
from loguru import logger

from tbot.core.config import logs_dir


def setup_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(sys.stderr, level=level, enqueue=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
                      "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")
    logger.add(logs_dir() / "tbot.log",
               level="DEBUG", rotation="10 MB", retention="14 days",
               compression="zip", encoding="utf-8", enqueue=True)
