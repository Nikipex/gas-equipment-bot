"""/start command handler."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.bot.keyboards.main_menu import main_menu_kb

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Greet the user and show the main menu."""
    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Я бот для поиска газового оборудования.\n"
        "Выберите действие из меню ниже 👇",
        reply_markup=main_menu_kb,
    )
