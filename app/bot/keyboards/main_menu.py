from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


class MenuButtons:
    SEARCH = "🔍 Найти товар"
    SUPPLIER_STOCK = "🏬 Остатки у поставщиков"
    SUPPLIER_SITES = "🌐 Сайты поставщиков"
    GLOBAL_SEARCH = "🌍 Глобальный поиск"
    PRICE = "💰 Мини-прайс"
    QUOTE = "🧾 Просчет"
    THINKING = "🧠 Размышления"
    KB_UPLOAD = "📚 Загрузить паспорт"


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=MenuButtons.SEARCH),
                KeyboardButton(text=MenuButtons.SUPPLIER_STOCK),
            ],
            [
                KeyboardButton(text=MenuButtons.SUPPLIER_SITES),
                KeyboardButton(text=MenuButtons.GLOBAL_SEARCH),
            ],
            [
                KeyboardButton(text=MenuButtons.PRICE),
                KeyboardButton(text=MenuButtons.QUOTE),
            ],
            [
                KeyboardButton(text=MenuButtons.THINKING),
                KeyboardButton(text=MenuButtons.KB_UPLOAD),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие или напишите запрос",
    )


main_menu_kb = get_main_menu_keyboard()
