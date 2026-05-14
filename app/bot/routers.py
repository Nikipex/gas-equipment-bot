"""Router aggregation — include all handler routers into a single main router."""

from __future__ import annotations

from aiogram import Router

from app.bot.handlers import offer, price, search, start, stock

main_router = Router(name="main")

# Order matters: more specific routers first
main_router.include_routers(
    start.router,
    search.router,
    stock.router,
    price.router,
    offer.router,
)
