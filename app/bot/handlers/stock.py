"""Stock (остатки) handler."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.bot.keyboards.main_menu import MenuButtons, main_menu_kb

router = Router(name="stock")


@router.message(F.text == MenuButtons.STOCK)
async def show_stock(message: Message) -> None:
    """Show stock info (stub)."""
    await message.answer(
        "📦 Остатки на складе\n\n"
        "🛠 Функция в разработке.\n"
        "Здесь будут актуальные остатки по позициям.",
        reply_markup=main_menu_kb,
    )
