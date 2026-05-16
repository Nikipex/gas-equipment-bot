"""Application entry point — starts the Telegram bot."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
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

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
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
