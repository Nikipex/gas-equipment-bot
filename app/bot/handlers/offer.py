"""Mini-price handler — FSM flow for merge-aware pricing queries."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger

from app.bot.keyboards.main_menu import MenuButtons, main_menu_kb
from app.bot.runtime_catalog import get_pricing_service
from app.bot.states.search_states import MiniPrice
from app.services.pricing_service import PricingService

router = Router(name="offer")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@router.message(F.text == MenuButtons.QUOTE)
async def start_miniprice(message: Message, state: FSMContext) -> None:
    """Enter mini-price query flow."""
    await state.set_state(MiniPrice.waiting_for_query)
    await message.answer(
        "📋 Введите запрос для просчета.\n"
        "<i>Например: BAXI, радиатор 500, котел 24 кВт</i>\n\n"
        "Для отмены введите /cancel или 'отмена'.",
        reply_markup=main_menu_kb,
    )
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info("Пользователь {} вошёл в просчет", user_id)


@router.message(MiniPrice.waiting_for_query, F.text)
async def process_miniprice_query(message: Message, state: FSMContext) -> None:
    """Process user query and return mini-price results."""
    query = (message.text or "").strip()

    # --- cancellation ---
    if query.lower() in {"/cancel", "отмена", "назад"}:
        await _cancel(message, state)
        return

    if not query:
        await message.answer(
            "⚠️ Пустой запрос. Введите название товара или бренд.",
            reply_markup=main_menu_kb,
        )
        return

    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info("Просчет запрос от {}: '{}'", user_id, query)

    try:
        pricing = get_pricing_service()
    except Exception as e:
        logger.exception("Не удалось инициализировать PricingService")
        await message.answer(
            f"❌ Ошибка загрузки каталога/остатков: {e}",
            reply_markup=main_menu_kb,
        )
        await state.clear()
        return

    offers = pricing.get_miniprice(query, limit=5)

    if offers:
        text = pricing.format_miniprice(offers)
        logger.info("Просчет: {} предложений для '{}'", len(offers), query)
    else:
        text = (
            f"❌ Ничего не найдено по запросу: <b>{query}</b>\n\n"
            "Попробуйте уточнить бренд, категорию или модель."
        )
        logger.info("Просчет: нет результатов для '{}'", query)

    await message.answer(text, reply_markup=main_menu_kb, parse_mode="HTML")
    await state.clear()


# ---------------------------------------------------------------------------
# Cancel helper
# ---------------------------------------------------------------------------


async def _cancel(message: Message, state: FSMContext) -> None:
    """Cancel mini-price flow and return to menu."""
    await state.clear()
    await message.answer("❌ Просчет отменён", reply_markup=main_menu_kb)
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info("Пользователь {} отменил просчет", user_id)
