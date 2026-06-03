"""Quote calculation handler."""

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards.main_menu import MenuButtons, main_menu_kb
from app.services.quote_service import QuoteService

router = Router()
_quote_service = QuoteService()
_last_quote_requests: dict[int, str] = {}


class QuoteState(StatesGroup):
    waiting_for_lines = State()


@router.message(F.text == MenuButtons.QUOTE)
async def start_quote(message: Message, state: FSMContext) -> None:
    await state.set_state(QuoteState.waiting_for_lines)
    await message.answer(
        "🧾 Введите позиции для просчета.\n\n"
        "Пример:\n"
        "baxi eco nova 24 - 2\n"
        "brs 32/6g - 4\n"
        "navien ngb 13 - 1\n\n"
        "Для отмены введите /cancel или 'отмена'.",
        reply_markup=main_menu_kb,
    )


@router.message(QuoteState.waiting_for_lines)
async def process_quote_state(message: Message, state: FSMContext) -> None:
    text = message.text or ""

    if text.lower().strip() in {"/cancel", "отмена"}:
        await state.clear()
        await message.answer("❌ Просчет отменён", reply_markup=main_menu_kb)
        return

    await state.clear()
    await _send_quote(message, text)


@router.message(lambda message: message.text and message.text.lower().startswith(("просчет", "просчёт", "расчет", "расчёт")))
async def process_quote_direct(message: Message) -> None:
    await _send_quote(message, message.text or "")


@router.callback_query(F.data.startswith("quote_round:"))
async def process_quote_round(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    text = _last_quote_requests.get(user_id)

    if not text:
        await callback.answer("Нет последнего просчета для округления", show_alert=True)
        return

    step = int(callback.data.split(":")[1])
    await callback.message.answer(
        build_quote_text(text, round_step=step),
        reply_markup=_quote_keyboard(),
    )
    await callback.answer(f"Округлил до {step}")


@router.callback_query(F.data.startswith("quote_markup_percent:"))
async def process_quote_markup_percent(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    text = _last_quote_requests.get(user_id)

    if not text:
        await callback.answer("Нет последнего просчета", show_alert=True)
        return

    percent = float(callback.data.split(":")[1])
    await callback.message.answer(
        build_quote_text(text, markup_percent=percent),
        reply_markup=_quote_keyboard(),
    )
    await callback.answer(f"Добавил +{percent:g}%")


@router.callback_query(F.data.startswith("quote_markup_amount:"))
async def process_quote_markup_amount(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    text = _last_quote_requests.get(user_id)

    if not text:
        await callback.answer("Нет последнего просчета", show_alert=True)
        return

    amount = float(callback.data.split(":")[1])
    await callback.message.answer(
        build_quote_text(text, markup_amount=amount),
        reply_markup=_quote_keyboard(),
    )
    await callback.answer(f"Добавил +{amount:g} ₽")


async def _send_quote(message: Message, text: str) -> None:
    _last_quote_requests[message.from_user.id] = text
    await message.answer(
        build_quote_text(text),
        reply_markup=_quote_keyboard(),
    )


def build_quote_text(
    text: str,
    round_step: int | None = None,
    markup_percent: float | None = None,
    markup_amount: float | None = None,
) -> str:
    lines = _quote_service.calculate(
        text,
        round_step=round_step,
        markup_percent=markup_percent,
        markup_amount=markup_amount,
    )

    if not lines:
        return "❌ Не смог разобрать позиции для просчёта."

    response = ["🧾 <b>Просчёт заявки</b>"]

    if markup_percent is not None:
        response.append(f"📈 Наценка: +{markup_percent:g}%")

    if markup_amount is not None:
        response.append(f"➕ Наценка: +{_format_price(markup_amount)} / шт")

    if round_step:
        response.append(f"🔢 Округление: до {round_step}")

    response.append("")
    total = 0.0

    for index, line in enumerate(lines, start=1):
        if not line.item:
            response.append(f"{index}. ❌ Не найдено: <b>{html.escape(line.query)}</b>")
            continue

        purchase = line.purchase_price
        if purchase is None or purchase <= 0:
            response.append(
                f"{index}. <b>{html.escape(line.item.product_name)}</b>\n"
                f"Кол-во: {line.qty:g} шт\n"
                f"Закупка: не подтянута"
            )
            continue

        line_total = line.line_total or 0
        total += line_total

        price_label = "Прайс" if getattr(line.item, "excel_client_price", None) else "Закупка"

        response.append(
            f"{index}. <b>{html.escape(line.item.product_name)}</b>\n"
            f"Кол-во: {line.qty:g} шт\n"
            f"{price_label}: {_format_price(purchase)}\n"
            f"Сумма: {_format_price(line_total)}"
        )

    response.append("")
    response.append(f"💰 <b>Итого по закупке:</b> {_format_price(total)}")

    return "\n\n".join(response)


def _quote_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📈 +10%", callback_data="quote_markup_percent:10"),
                InlineKeyboardButton(text="📈 +15%", callback_data="quote_markup_percent:15"),
            ],
            [
                InlineKeyboardButton(text="➕ +1000 ₽", callback_data="quote_markup_amount:1000"),
                InlineKeyboardButton(text="➕ +2000 ₽", callback_data="quote_markup_amount:2000"),
            ],
            [
                InlineKeyboardButton(text="🔢 До 10", callback_data="quote_round:10"),
                InlineKeyboardButton(text="🔢 До 100", callback_data="quote_round:100"),
            ],
        ]
    )


def _format_price(value: float) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")
