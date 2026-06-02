"""Настройка логирования (loguru, ротация в %APPDATA%/TBot/logs)."""
from __future__ import annotations

import sys
from loguru import logger

from tbot.core.config import logs_dir

def setup_logging(level: str = "INFO") -> None:
    logger.remove()
    # В GUI-режиме (--windowed) sys.stderr может быть None
    if sys.stderr is not None:
        logger.add(sys.stderr, level=level, enqueue=True,
                   format="{time:HH:mm:ss} | {level: <8} | "
                   "{name}:{line} - {message}")
    logger.add(logs_dir() / "tbot.log",
               level="DEBUG", rotation="10 MB", retention="14 days",
               compression="zip", encoding="utf-8", enqueue=True)
