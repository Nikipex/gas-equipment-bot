from __future__ import annotations

import asyncio
import html

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.keyboards.main_menu import MainMenuButtons, main_menu_kb
from app.bot.states.search_states import SearchModeStates
from app.integrations.suppliers.web_supplier_search_service import WebSupplierSearchService

router = Router()

SUPPLIER_SITE_TIMEOUT_SECONDS = 15


@router.message(lambda message: message.text == MainMenuButtons.SUPPLIER_SITES)
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


@router.message(lambda message: message.text == MainMenuButtons.GLOBAL_SEARCH)
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

    await message.answer(
        f"🌐 Ищу на сайтах поставщиков:\n<code>{html.escape(query)}</code>",
        reply_markup=main_menu_kb,
    )

    try:
        service = WebSupplierSearchService()

        results = await service.search_all(
            query=query,
            limit_per_supplier=3,
            headless=True,
        )

    except asyncio.TimeoutError:
        await message.answer(
            "⏱ Поиск по сайтам поставщиков не уложился в быстрый таймаут.\n"
            "Попробуй уточнить модель или использовать поиск по Excel-прайсам.",
            reply_markup=main_menu_kb,
        )
        return

    except Exception as exc:
        await message.answer(
            "❌ Ошибка поиска по сайтам поставщиков:\n"
            f"<code>{html.escape(type(exc).__name__)}: {html.escape(str(exc))}</code>",
            reply_markup=main_menu_kb,
        )
        return

    if not results:
        await message.answer(
            "❌ На сайтах поставщиков ничего не найдено.",
            reply_markup=main_menu_kb,
        )
        return

    await message.answer(
        _build_supplier_sites_response(query, results)[:3900],
        reply_markup=main_menu_kb,
    )


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

    await message.answer(
        "🌍 <b>Глобальный поиск</b>\n\n"
        f"Запрос:\n<code>{html.escape(query)}</code>\n\n"
        "⚠️ Пока это отдельный режим-заготовка. "
        "Следующий этап — подключить внешний web-search/RAG по моделям, "
        "не смешивая его с реальными остатками поставщиков.",
        reply_markup=main_menu_kb,
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
