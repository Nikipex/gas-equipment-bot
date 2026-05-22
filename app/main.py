"""Application entry point — starts the Telegram bot."""

from __future__ import annotations

import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from app.bot.routers import main_router
from app.core.config import settings
from app.core.env import load_environment
from app.core.logging import setup_logging


async def main() -> None:
    load_environment()
    """Configure and start the bot with long-polling."""
    setup_logging()
    logger.info("Starting Gas Equipment Bot…")

    telegram_proxy_url = os.getenv("TELEGRAM_PROXY_URL")

    if telegram_proxy_url:
        logger.info("Using Telegram proxy")

    session = AiohttpSession(proxy=telegram_proxy_url) if telegram_proxy_url else None

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )

    dp = Dispatcher()
    dp.include_router(main_router)

    # Drop pending updates on startup, then start polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning(f"delete_webhook failed, continue polling anyway: {type(e).__name__}: {e}")

    logger.info("Polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
