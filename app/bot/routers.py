"""Bot routers."""

from __future__ import annotations

from aiogram import Router

from app.bot.handlers import ai_intent, price, price_list, quote, search, start, stock, supplier_files, equipment_selector, supplier_sites, search_modes, thinking

main_router = Router()

# ВАЖНО: режимовые кнопки выше обычного поиска
main_router.include_router(search_modes.router)
main_router.include_router(thinking.router)
main_router.include_router(equipment_selector.router)
main_router.include_router(ai_intent.router)
main_router.include_router(start.router)
main_router.include_router(quote.router)
main_router.include_router(price.router)
main_router.include_router(price_list.router)
main_router.include_router(stock.router)
main_router.include_router(supplier_files.router)
main_router.include_router(supplier_sites.router)
main_router.include_router(search.router)

