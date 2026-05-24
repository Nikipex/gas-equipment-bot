from __future__ import annotations

import html

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards.main_menu import MainMenuButtons, main_menu_kb
from app.bot.states.search_states import SearchModeStates

router = Router()


@router.message(lambda message: message.text == MainMenuButtons.SUPPLIER_SITES)
async def ask_supplier_site_search(message: Message, state: FSMContext) -> None:
    await state.set_state(SearchModeStates.waiting_supplier_site_query)

    await message.answer(
        "🌐 <b>Поиск по сайтам поставщиков</b>\n\n"
        "Введи товар / модель.\n\n"
        "<code>Baxi Luna-3 1.310 Fi</code>\n"
        "<code>Ariston PRO1 R 80 DRY</code>",
        reply_markup=main_menu_kb,
    )


@router.message(lambda message: message.text == MainMenuButtons.GLOBAL_SEARCH)
async def ask_global_search(message: Message, state: FSMContext) -> None:
    await state.set_state(SearchModeStates.waiting_global_search_query)

    await message.answer(
        "🌍 <b>Глобальный поиск</b>\n\n"
        "Этот режим ищет варианты вне прайсов поставщиков.",
        reply_markup=main_menu_kb,
    )


@router.message(SearchModeStates.waiting_supplier_site_query)
async def process_supplier_site_query(
    message: Message,
    state: FSMContext,
) -> None:

    query = (message.text or "").strip()

    await state.clear()

    await message.answer(
        "🌐 <b>Поиск по сайтам поставщиков</b>\n\n"
        f"Запрос:\n<code>{html.escape(query)}</code>\n\n"
        "Следующий этап — подключить supplier site service.",
        reply_markup=main_menu_kb,
    )


@router.message(SearchModeStates.waiting_global_search_query)
async def process_global_search_query(
    message: Message,
    state: FSMContext,
) -> None:

    query = (message.text or "").strip()

    await state.clear()

    await message.answer(
        "🌍 <b>Глобальный поиск</b>\n\n"
        f"Запрос:\n<code>{html.escape(query)}</code>",
        reply_markup=main_menu_kb,
    )
