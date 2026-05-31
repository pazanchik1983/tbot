"""Точка входа: `python -m tbot`."""
from __future__ import annotations

import sys
from loguru import logger

from tbot.core.config import load_settings
from tbot.core.logging_setup import setup_logging


def main() -> int:
    setup_logging()
    settings = load_settings()
    logger.info("Запуск T-Bot v{}", settings.app_version)

    # UI запускается лениво, чтобы можно было использовать ядро без PyQt
    from tbot.ui.app import run_app
    return run_app(settings)


if __name__ == "__main__":
    sys.exit(main())
