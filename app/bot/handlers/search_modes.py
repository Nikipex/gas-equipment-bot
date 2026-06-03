from __future__ import annotations

import asyncio
import html

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards.main_menu import MenuButtons, main_menu_kb
from app.bot.states.search_states import SearchModeStates
from app.bot.handlers.supplier_sites import run_supplier_sites_search
from app.integrations.suppliers.web_supplier_search_service import WebSupplierSearchService
from app.services.global_product_search_service import GlobalProductSearchService
from app.services.ai.yandex_gpt_service import YandexGPTService

router = Router()

SUPPLIER_SITE_TIMEOUT_SECONDS = 15


@router.message(lambda message: message.text == MenuButtons.SUPPLIER_SITES)
async def ask_supplier_site_search(message: Message, state: FSMContext) -> None:
    await state.set_state(SearchModeStates.waiting_supplier_site_query)

    await message.answer(
        "🌐 <b>Поиск по сайтам поставщиков</b>\n\n"
        "Введи товар / модель.\n\n"
        "<code>Baxi Luna-3 1.310 Fi</code>\n"
        "<code>Ariston PRO1 R 80 DRY</code>\n"
        "<code>коаксиальный комплект 60/100</code>",
        reply_markup=main_menu_kb,
    )


@router.message(lambda message: message.text == MenuButtons.GLOBAL_SEARCH)
async def ask_global_search(message: Message, state: FSMContext) -> None:
    await state.set_state(SearchModeStates.waiting_global_search_query)

    await message.answer(
        "🌍 <b>Глобальный поиск</b>\n\n"
        "Этот режим ищет варианты вне прайсов поставщиков.\n"
        "Пока не смешиваем его с остатками и ценами поставщиков.",
        reply_markup=main_menu_kb,
    )


@router.message(SearchModeStates.waiting_supplier_site_query)
async def process_supplier_site_query(
    message: Message,
    state: FSMContext,
) -> None:
    query = (message.text or "").strip()
    await state.clear()

    if not query:
        await message.answer("❌ Пустой запрос.", reply_markup=main_menu_kb)
        return

    await run_supplier_sites_search(message, query)


@router.message(SearchModeStates.waiting_global_search_query)
async def process_global_search_query(
    message: Message,
    state: FSMContext,
) -> None:
    query = (message.text or "").strip()
    await state.clear()

    if not query:
        await message.answer("❌ Пустой запрос.", reply_markup=main_menu_kb)
        return

    service = GlobalProductSearchService()
    results = service.search(query)

    ai_summary = None
    try:
        ai_summary = YandexGPTService().summarize_product_global_search(query)
    except Exception as exc:
        ai_summary = f"AI-сводка временно недоступна: {type(exc).__name__}"

    if not results:
        await message.answer("❌ Не удалось собрать ссылки для поиска.", reply_markup=main_menu_kb)
        return

    lines = [
        "🌍 <b>Глобальный поиск</b>",
        "",
        f"Запрос: <code>{html.escape(query)}</code>",
        "",
        "🧠 <b>AI-сводка</b>",
        html.escape(ai_summary or "Нет данных."),
        "",
        "🔗 <b>Ссылки для проверки</b>",
        "",
    ]

    for index, item in enumerate(results, start=1):
        lines.append(f"{index}. <a href=\"{html.escape(item.url)}\">{html.escape(item.title)}</a>")
        lines.append(f"   {html.escape(item.description)}")
        lines.append("")

    await message.answer(
        "\n".join(lines),
        reply_markup=main_menu_kb,
        disable_web_page_preview=True,
    )


def _build_supplier_sites_response(query: str, results) -> str:
    response = [
        "🌐 <b>Сайты поставщиков</b>",
        "",
        f"Запрос: <code>{html.escape(query)}</code>",
        "",
    ]

    for index, item in enumerate(results[:10], start=1):
        response.append(f"{index}. <b>{html.escape(str(item.supplier_name))}</b>")
        response.append(f"   {html.escape(str(item.title))}")

        if getattr(item, "price", None):
            response.append(f"   💰 Цена сайта: <b>{html.escape(str(item.price))}</b>")

            calculated_price = _calculate_supplier_price(
                supplier_name=str(item.supplier_name),
                title=str(item.title),
                raw_price=str(item.price),
            )

            if calculated_price:
                response.append(f"   🧮 Цена после скидки: <b>{html.escape(calculated_price)}</b>")

        if getattr(item, "stock", None):
            response.append(f"   📦 Остаток: {html.escape(str(item.stock))}")

        response.append("")

    return "\n".join(response)


def _calculate_supplier_price(
    supplier_name: str,
    title: str,
    raw_price: str,
) -> str | None:
    price = _parse_price(raw_price)

    if price is None:
        return None

    supplier = supplier_name.lower().replace("ё", "е")
    product = title.lower().replace("ё", "е")

    is_baxi_boiler = "baxi" in product or "бакси" in product

    if not is_baxi_boiler:
        return None

    discount = None

    if "terem" in supplier or "терем" in supplier:
        discount = 0.30

    elif "teplocel" in supplier or "теплоцель" in supplier:
        discount = 0.0714

    if discount is None:
        return None

    final_price = price * (1 - discount)
    return _format_price(final_price)


def _parse_price(value: str) -> float | None:
    import re

    clean = str(value or "").replace(",", ".")
    clean = re.sub(r"[^0-9.]", "", clean)

    if not clean:
        return None

    try:
        return float(clean)
    except Exception:
        return None


def _format_price(value: float) -> str:
    rounded = round(value)
    return f"{rounded:,.0f}".replace(",", " ") + " ₽"
