"""AI intent handler."""

from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from app.bot.handlers.price_list import send_price_list
from app.bot.handlers.stock import send_supplier_stock_results
from app.bot.keyboards.main_menu import main_menu_kb
from app.services.ai.ai_router_service import AIRouterService

router = Router()
_ai_router = AIRouterService()


@router.message(lambda message: message.text and message.text.lower().startswith(("ии ", "ai ")))
async def process_ai_intent(message: Message) -> None:
    raw_text = message.text or ""
    text = raw_text.split(" ", 1)[1].strip() if " " in raw_text else ""

    if not text:
        await message.answer(
            "❌ Напиши команду после <b>ии</b>.\n\n"
            "Пример:\n"
            "<code>ии найди baxi eco 4s 24 у поставщиков, скидка 5, до сотен</code>",
            reply_markup=main_menu_kb,
        )
        return

    try:
        intent = _ai_router.parse(text)
    except Exception as exc:
        await message.answer(
            f"❌ ИИ-слой не ответил: <code>{type(exc).__name__}: {exc}</code>",
            reply_markup=main_menu_kb,
        )
        return

    intent_name = intent.get("intent")
    query = (intent.get("query") or "").strip()

    if not query:
        await message.answer(
            "🤖 Не смог выделить товар из команды.",
            reply_markup=main_menu_kb,
        )
        return

    command_text = _build_command_text(intent)

    if intent_name == "supplier_search":
        await message.answer(
            f"🤖 Понял команду:\n<code>{command_text}</code>"
        )
        await send_supplier_stock_results(message, command_text)
        return

    if intent_name == "price_list":
        await message.answer(
            f"🤖 Понял команду:\n<code>прайс {command_text}</code>"
        )
        await send_price_list(message, f"прайс {command_text}")
        return

    await message.answer(
        "🤖 Команду понял, но пока не знаю, куда её направить.\n\n"
        f"<code>{intent}</code>",
        reply_markup=main_menu_kb,
    )


def _build_command_text(intent: dict) -> str:
    parts: list[str] = []

    supplier_key = intent.get("supplier_key")
    if supplier_key:
        parts.append(str(supplier_key))

    query = intent.get("query")
    if query:
        parts.append(str(query))

    discount = intent.get("discount_percent")
    if discount is not None:
        parts.append(f"-{float(discount):g}%")

    markup = intent.get("markup_amount")
    if markup is not None:
        parts.append(f"+{float(markup):g}")

    round_step = intent.get("round_step")
    if round_step is not None:
        parts.append(f"до {int(round_step)}")

    return " ".join(parts).strip()
