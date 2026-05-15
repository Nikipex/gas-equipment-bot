"""Price list mode handler."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app.bot.keyboards.main_menu import MenuButtons, main_menu_kb
from app.bot.handlers.price_list import send_price_list

router = Router()


class PriceState(StatesGroup):
    waiting_for_query = State()


@router.message(F.text == MenuButtons.PRICE)
async def start_price_mode(message: Message, state: FSMContext) -> None:
    await state.set_state(PriceState.waiting_for_query)
    await message.answer(
        "💰 Введите запрос для прайса.\n\n"
        "Пример:\n"
        "fondital +20%\n"
        "baxi +3000\n"
        "радиатор 22 500 +15%\n\n"
        "Для отмены введите /cancel или 'отмена'.",
        reply_markup=main_menu_kb,
    )


@router.message(PriceState.waiting_for_query)
async def process_price_mode(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()

    if text.lower() in {"/cancel", "отмена"}:
        await state.clear()
        await message.answer("❌ Прайс отменён", reply_markup=main_menu_kb)
        return

    await state.clear()

    # Пользователь после кнопки пишет просто "fondital +20%",
    # а price_list handler ожидает формат "прайс fondital +20%".
    if text.lower().startswith(("прайс ", "price ")):
        await send_price_list(message, text)
    else:
        await send_price_list(message, f"прайс {text}")
