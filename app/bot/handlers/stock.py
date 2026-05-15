"""Supplier stock handler placeholder."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.bot.keyboards.main_menu import MenuButtons, main_menu_kb

router = Router()


@router.message(F.text == MenuButtons.SUPPLIER_STOCK)
async def process_supplier_stock(message: Message) -> None:
    await message.answer(
        "🏬 <b>Остатки у поставщиков</b>\n\n"
        "🛠 Функция в разработке.\n"
        "Позже сюда подключим Excel-прайсы поставщиков и поиск по внешним остаткам.",
        reply_markup=main_menu_kb,
    )
