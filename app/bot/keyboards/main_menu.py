"""Main menu keyboard."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


class MenuButtons:
    """Menu button labels — single source of truth."""

    SEARCH = "🔍 Найти товар"
    SUPPLIER_STOCK = "🏬 Остатки у поставщиков"
    SUPPLIER_SITES = "🌐 Сайты поставщиков"
    GLOBAL_SEARCH = "🌍 Глобальный поиск"
    PRICE = "💰 Прайс"
    QUOTE = "🧾 Просчет"


main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text=MenuButtons.SEARCH),
            KeyboardButton(text=MenuButtons.SUPPLIER_STOCK),
        ],
        [
            KeyboardButton(text=MenuButtons.PRICE),
            KeyboardButton(text=MenuButtons.QUOTE),
        ],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие…",
)


def get_main_menu_keyboard():
    return main_menu_kb
