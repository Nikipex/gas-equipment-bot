"""Main menu keyboard."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


class MenuButtons:
    """Menu button labels — single source of truth."""

    SEARCH = "🔍 Найти товар"
    STOCK = "📦 Остатки"
    PRICE = "💰 Прайс"
    MINI_PRICE = "📋 Мини-прайс"


main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=MenuButtons.SEARCH), KeyboardButton(text=MenuButtons.STOCK)],
        [KeyboardButton(text=MenuButtons.PRICE), KeyboardButton(text=MenuButtons.MINI_PRICE)],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие…",
)
def get_main_menu_keyboard():
    return main_menu_kb