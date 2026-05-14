"""Price (прайс) handler."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.bot.keyboards.main_menu import MenuButtons, main_menu_kb

router = Router(name="price")


@router.message(F.text == MenuButtons.PRICE)
async def show_price(message: Message) -> None:
    """Show full price list (stub)."""
    await message.answer(
        "💰 Прайс-лист\n\n"
        "🛠 Функция в разработке.\n"
        "Здесь будет актуальный прайс-лист поставщиков.",
        reply_markup=main_menu_kb,
    )
