"""Bot routers."""

from __future__ import annotations

from aiogram import Router

from app.bot.handlers import price, price_list, quote, search, start, stock

main_router = Router()

# ВАЖНО: режимовые кнопки выше обычного поиска
main_router.include_router(start.router)
main_router.include_router(quote.router)
main_router.include_router(price.router)
main_router.include_router(price_list.router)
main_router.include_router(stock.router)
main_router.include_router(search.router)
