"""Loguru-based logging setup."""

from __future__ import annotations

import sys

from loguru import logger

from app.core.config import settings


def setup_logging() -> None:
    """Configure loguru with rotation, format and level from settings."""
    logger.remove()  # remove default stderr handler

    logger.add(
        sys.stderr,
        level=settings.log_level.upper(),
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    logger.add(
        "logs/bot_{time:YYYY-MM-DD}.log",
        level=settings.log_level.upper(),
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        encoding="utf-8",
    )

    logger.info("Logging configured  (level={})", settings.log_level)
