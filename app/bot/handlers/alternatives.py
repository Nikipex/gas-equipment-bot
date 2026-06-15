from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger

from app.bot.handlers.search import get_last_search_query
from app.bot.keyboards.main_menu import get_main_menu_keyboard
from app.services.equipment.alternative_equipment_service import AlternativeEquipmentService

router = Router()

_service: AlternativeEquipmentService | None = None


def _get_service() -> AlternativeEquipmentService:
    global _service
    if _service is None:
        _service = AlternativeEquipmentService()
    return _service


@router.callback_query(F.data == "alternatives:last_search")
async def show_alternatives(callback: CallbackQuery):
    user_id = callback.from_user.id if callback.from_user else None
    query = get_last_search_query(int(user_id)) if user_id else None

    if not query:
        await callback.answer("Нет последнего поиска", show_alert=True)
        return

    await callback.answer("Подбираю аналоги…")

    try:
        service = _get_service()
        result = await service.find_alternatives(query, limit=6)
        text = service.format_result(result, query)

        await callback.message.answer(
            text,
            reply_markup=get_main_menu_keyboard(),
        )

        logger.info(
            "Пользователь {} запросил аналоги для {!r}: {} результатов",
            user_id,
            query,
            len(result.alternatives),
        )

    except Exception as exc:
        logger.exception("Alternative equipment failed: {}", exc)
        await callback.message.answer(
            "❌ Не удалось подобрать аналоги.\n"
            "Попробуйте уточнить модель: бренд, мощность, литраж или тип оборудования.",
            reply_markup=get_main_menu_keyboard(),
        )
