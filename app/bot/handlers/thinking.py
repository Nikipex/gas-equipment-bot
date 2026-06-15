from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger

from app.bot.keyboards.main_menu import MenuButtons, get_main_menu_keyboard
from app.bot.states.thinking_states import ThinkingState
from app.services.ai_thinking_service import ai_thinking_service

router = Router()


@router.message(F.text == MenuButtons.THINKING)
async def start_thinking(message: Message, state: FSMContext):
    await state.set_state(ThinkingState.waiting_for_question)

    await message.answer(
        "🧠 <b>Размышления</b>\n\n"
        "Задайте свободный вопрос по газовому оборудованию.\n"
        "Например:\n"
        "• а что если заменить BAXI на Navien?\n"
        "• какой котел предложить на дом 120 м²?\n"
        "• чем объяснить клиенту разницу между 11 и 22 радиатором?\n\n"
        "Для отмены введите /cancel или «отмена».",
        reply_markup=get_main_menu_keyboard(),
    )


@router.message(ThinkingState.waiting_for_question, F.text)
async def process_thinking_question(message: Message, state: FSMContext):
    question = message.text.strip()

    if question.lower() in {"/cancel", "отмена", "назад"}:
        await state.clear()
        await message.answer(
            "❌ Режим размышлений отменён",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    await message.answer("🧠 Думаю над вопросом...")

    answer = ai_thinking_service.ask(question)

    await message.answer(answer, reply_markup=get_main_menu_keyboard())
    await state.clear()

    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info(f"Пользователь {user_id} задал AI-вопрос: {question!r}")
