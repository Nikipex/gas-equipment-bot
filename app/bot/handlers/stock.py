"""Supplier stock search handler."""

from __future__ import annotations

import html
import re
import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards.main_menu import MenuButtons, main_menu_kb
from app.services.supplier_cache_service import SupplierCacheService

router = Router()
_supplier_cache_service = SupplierCacheService()
_last_supplier_queries: dict[int, str] = {}


class SupplierStockState(StatesGroup):
    waiting_for_query = State()
    waiting_for_discount = State()
    waiting_for_markup = State()


@router.message(F.text == MenuButtons.SUPPLIER_STOCK)
async def start_supplier_stock_search(message: Message, state: FSMContext) -> None:
    await state.set_state(SupplierStockState.waiting_for_query)
    await message.answer(
        "🏬 Введите товар для поиска по остаткам поставщиков.\n\n"
        "Пример:\n"
        "автоматика 630\n"
        "tgv 307\n"
        "artu tgv -5% +1000 до 100\n\n"
        "Для отмены введите /cancel или 'отмена'.",
        reply_markup=main_menu_kb,
    )


@router.message(SupplierStockState.waiting_for_query)
async def process_supplier_stock_query(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()

    if text.lower() in {"/cancel", "отмена"}:
        await state.clear()
        await message.answer("❌ Поиск по поставщикам отменён", reply_markup=main_menu_kb)
        return

    await state.clear()
    await send_supplier_stock_results(message, text)


@router.callback_query(F.data == "supplier_stock:discount")
async def ask_discount(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SupplierStockState.waiting_for_discount)
    await callback.message.answer(
        "➖ Введите процент скидки от цены поставщика.\n\n"
        "Например: <b>5</b>\n"
        "Допустимо от 1 до 12.",
        reply_markup=main_menu_kb,
    )
    await callback.answer()


@router.message(SupplierStockState.waiting_for_discount)
async def apply_discount(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().replace(",", ".")

    if text.lower() in {"/cancel", "отмена"}:
        await state.clear()
        await message.answer("❌ Скидка отменена", reply_markup=main_menu_kb)
        return

    try:
        value = float(text)
    except ValueError:
        await message.answer("❌ Введите число от 1 до 12.")
        return

    if value < 1 or value > 12:
        await message.answer("❌ Скидка должна быть от 1 до 12%.")
        return

    user_id = message.from_user.id
    base_query = _last_supplier_queries.get(user_id)

    if not base_query:
        await state.clear()
        await message.answer("❌ Нет последнего поиска поставщиков.", reply_markup=main_menu_kb)
        return

    query = _replace_discount_part(base_query, f"-{value:g}%")
    _last_supplier_queries[user_id] = query

    await state.clear()
    await message.answer(build_supplier_stock_text(query), reply_markup=_supplier_actions_keyboard())


@router.callback_query(F.data == "supplier_stock:markup")
async def ask_markup(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SupplierStockState.waiting_for_markup)
    await callback.message.answer(
        "➕ Введите сумму прибавки к цене после скидки.\n\n"
        "Например: <b>1000</b>",
        reply_markup=main_menu_kb,
    )
    await callback.answer()


@router.message(SupplierStockState.waiting_for_markup)
async def apply_markup(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().replace(",", ".")

    if text.lower() in {"/cancel", "отмена"}:
        await state.clear()
        await message.answer("❌ Прибавка отменена", reply_markup=main_menu_kb)
        return

    try:
        value = float(text)
    except ValueError:
        await message.answer("❌ Введите сумму числом. Например: 1000")
        return

    if value < 0:
        await message.answer("❌ Прибавка не может быть отрицательной.")
        return

    user_id = message.from_user.id
    base_query = _last_supplier_queries.get(user_id)

    if not base_query:
        await state.clear()
        await message.answer("❌ Нет последнего поиска поставщиков.", reply_markup=main_menu_kb)
        return

    query = _replace_markup_part(base_query, f"+{value:g}")
    _last_supplier_queries[user_id] = query

    await state.clear()
    await message.answer(build_supplier_stock_text(query), reply_markup=_supplier_actions_keyboard())


@router.callback_query(F.data.startswith("supplier_stock:"))
async def process_supplier_stock_callback(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    base_query = _last_supplier_queries.get(user_id)

    if not base_query:
        await callback.answer("Нет последнего поиска поставщиков", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]

    if action == "price":
        text = build_supplier_price_text(base_query)
        await callback.message.answer(text, reply_markup=_supplier_actions_keyboard())
        await callback.answer("Составил прайс")
        return

    if action == "round10":
        query = _replace_round_part(base_query, "до 10")
    elif action == "round100":
        query = _replace_round_part(base_query, "до 100")
    else:
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    _last_supplier_queries[user_id] = query
    await callback.message.answer(build_supplier_stock_text(query), reply_markup=_supplier_actions_keyboard())
    await callback.answer("Пересчитал")


async def send_supplier_stock_results(message: Message, query: str) -> None:
    if message.from_user:
        _last_supplier_queries[message.from_user.id] = query

    await message.answer(
        build_supplier_stock_text(query),
        reply_markup=_supplier_actions_keyboard(),
    )


def build_supplier_stock_text(query: str) -> str:
    result = _supplier_cache_service.search(query, limit=15)

    if result.empty:
        return f"❌ У поставщиков ничего не найдено по запросу: <b>{html.escape(query)}</b>"

    lines = [
        f"🏬 <b>Остатки у поставщиков:</b> {html.escape(query)}",
        "",
    ]

    for index, row in enumerate(result.to_dict("records"), start=1):
        supplier = html.escape(str(row.get("supplier_name") or "неизвестный поставщик"))
        product = html.escape(str(row.get("product_name") or "без названия"))
        price = _format_price(row.get("price"))
        calculated_price = _format_price(row.get("calculated_price")) if "calculated_price" in row else None
        stock = _format_stock(row.get("stock"))
        warehouse_stock_text = _format_warehouse_stock_text(row.get("warehouse_stocks"))

        details = [
            f"{index}. <b>{product}</b>",
            f"🏷️ Поставщик: {supplier}",
            f"💰 Цена поставщика: {price}",
        ]

        if calculated_price:
            details.append(f"🏷️ Цена после формулы: {calculated_price}")

        details.append(f"📦 Остаток общий: {stock}")
        if warehouse_stock_text:
            details.append(warehouse_stock_text)
        lines.append("\n".join(details))

    return "\n\n".join(lines)


def build_supplier_price_text(query: str) -> str:
    result = _supplier_cache_service.search(query, limit=30)

    if result.empty:
        return f"❌ Не из чего составить прайс по запросу: <b>{html.escape(query)}</b>"

    lines = [
        f"📋 <b>Прайс по остаткам поставщика:</b> {html.escape(query)}",
        "",
    ]

    for index, row in enumerate(result.to_dict("records"), start=1):
        product = html.escape(str(row.get("product_name") or "без названия"))
        price_value = row.get("calculated_price") if "calculated_price" in row else row.get("price")
        price = _format_price(price_value)

        lines.append(
            f"{index}. <b>{product}</b>\n"
            f"🏷️ Цена: {price}"
        )

    return "\n\n".join(lines)


def _supplier_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Прайс из найденного", callback_data="supplier_stock:price"),
            ],
            [
                InlineKeyboardButton(text="➖ Скидка %", callback_data="supplier_stock:discount"),
                InlineKeyboardButton(text="➕ Прибавка ₽", callback_data="supplier_stock:markup"),
            ],
            [
                InlineKeyboardButton(text="🔢 До 10", callback_data="supplier_stock:round10"),
                InlineKeyboardButton(text="🔢 До 100", callback_data="supplier_stock:round100"),
            ],
        ]
    )


def _replace_discount_part(query: str, formula: str) -> str:
    text = re.sub(r"-\d+(?:[.,]\d+)?\s*%", " ", query)
    text = re.sub(r"\s+", " ", text).strip()
    return f"{text} {formula}".strip()


def _replace_markup_part(query: str, formula: str) -> str:
    text = re.sub(r"\+\d+(?:[.,]\d+)?\s*(?:р|руб|₽)?", " ", query)
    text = re.sub(r"\s+", " ", text).strip()
    return f"{text} {formula}".strip()


def _replace_round_part(query: str, round_text: str) -> str:
    text = re.sub(r"до\s*(100|10)", " ", query.lower())
    text = re.sub(r"\s+", " ", text).strip()
    return f"{text} {round_text}".strip()


def _format_price(value: object) -> str:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return "не найдена"

    if price <= 0:
        return "не найдена"

    return f"{price:,.0f} ₽".replace(",", " ")


def _format_stock(value: object) -> str:
    try:
        stock = float(value)
    except (TypeError, ValueError):
        return "не найден"

    if stock < 0:
        return "не найден"

    if stock.is_integer():
        return f"{int(stock)}"

    return f"{stock:g}"


def _format_warehouse_stock_text(value: object) -> str:
    if value is None:
        return ""

    try:
        data = json.loads(str(value))
    except Exception:
        return ""

    if not isinstance(data, dict) or not data:
        return ""

    lines = []
    for warehouse, stock in data.items():
        try:
            stock_float = float(stock)
            stock_text = str(int(stock_float)) if stock_float.is_integer() else f"{stock_float:g}"
        except Exception:
            stock_text = str(stock)

        lines.append(f"   • {warehouse}: {stock_text}")

    return "🏬 По складам:\n" + "\n".join(lines)
