"""Dynamic price list handler."""

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards.main_menu import main_menu_kb
from app.services.price_list_service import PriceListService

router = Router()
_price_list_service = PriceListService()
_last_price_requests: dict[int, str] = {}


@router.message(lambda message: message.text and message.text.lower().startswith(("прайс ", "price ")))
async def process_price_list(message: Message) -> None:
    await send_price_list(message, message.text or "")


@router.callback_query(F.data.startswith("price_round:"))
async def process_price_round(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    text = _last_price_requests.get(user_id)

    if not text:
        await callback.answer("Нет последнего прайса для округления", show_alert=True)
        return

    step = int(callback.data.split(":")[1])
    await callback.message.answer(
        await build_price_list_text(text, round_step=step),
        reply_markup=_price_keyboard(),
    )
    await callback.answer(f"Округлил до {step}")


@router.callback_query(F.data == "price_show_purchase")
async def process_show_purchase(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    text = _last_price_requests.get(user_id)

    if not text:
        await callback.answer("Нет последнего прайса", show_alert=True)
        return

    await callback.message.answer(
        await build_price_list_text(text, force_show_purchase=True),
        reply_markup=_price_keyboard(),
    )
    await callback.answer("Показал закупку")


async def send_price_list(message: Message, text: str) -> None:
    _last_price_requests[message.from_user.id] = text

    result = await build_price_list_text(text)
    await message.answer(
        result,
        reply_markup=_price_keyboard(),
    )


async def build_price_list_text(
    text: str,
    round_step: int | None = None,
    force_show_purchase: bool = False,
) -> str:
    request, lines = _price_list_service.build(text, limit=30, round_step=round_step)

    if force_show_purchase:
        request.show_purchase = True

    if not request.query:
        return "❌ Укажи, по чему сделать прайс. Например: <b>прайс фондитал +20%</b>"

    if not lines:
        return f"❌ Не нашёл товары в наличии по запросу: <b>{html.escape(request.query)}</b>"

    if request.markup_percent is not None:
        markup_text = f"+{request.markup_percent:g}%"
    elif request.markup_amount is not None:
        markup_text = f"+{request.markup_amount:g} ₽"
    else:
        markup_text = "без наценки"

    response = [
        f"📋 <b>Прайс:</b> {html.escape(request.query)}",
        f"Наценка: <b>{markup_text}</b>",
    ]

    if request.round_step:
        response.append(f"🔢 Округление: до {request.round_step}")

    response.append("")

    for index, line in enumerate(lines, start=1):
        item = line.item
        details = [f"{index}. <b>{html.escape(item.product_name)}</b>"]

        if request.show_stock:
            details.append(f"📦 В наличии: {item.stock_qty:g} шт")

        if request.show_purchase:
            details.append(f"💸 Закупка: {_format_price(item.purchase_price or 0)}")

        details.append(f"🏷️ Цена: {_format_price(line.sale_price)}")

        response.append("\n".join(details))

    return "\n\n".join(response)


def _price_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔢 До 10", callback_data="price_round:10"),
                InlineKeyboardButton(text="🔢 До 100", callback_data="price_round:100"),
            ],
            [
                InlineKeyboardButton(text="🔒 Показать закупку", callback_data="price_show_purchase"),
            ],
        ]
    )


def _format_price(value: float) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")
