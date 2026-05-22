from __future__ import annotations

import html

from aiogram import Router
from aiogram.types import Message

from app.bot.keyboards.main_menu import main_menu_kb
from app.integrations.suppliers.web_supplier_search_service import WebSupplierSearchService

router = Router()


@router.message(
    lambda message: message.text
    and message.text.lower().startswith(
        (
            "найди у поставщиков ",
            "поиск у поставщиков ",
            "сайты ",
            "поставщики ",
        )
    )
)
async def search_supplier_sites(message: Message) -> None:
    text = message.text or ""
    query = _extract_query(text)

    if not query:
        await message.answer(
            "Напиши запрос после команды. Например:\n"
            "<code>найди у поставщиков Baxi Eco 4s 24F</code>",
            reply_markup=main_menu_kb,
        )
        return

    await message.answer(
        f"🌐 Ищу на сайтах поставщиков:\n<code>{html.escape(query)}</code>",
        reply_markup=main_menu_kb,
    )

    try:
        service = WebSupplierSearchService()

        results = await service.search_all(
            query=query,
            limit_per_supplier=5,
            headless=True,
        )

        if not results:
            await message.answer(
                "❌ На сайтах поставщиков ничего не найдено.",
                reply_markup=main_menu_kb,
            )
            return

        response = [
            "🌐 <b>Сайты поставщиков</b>",
            "",
            f"Запрос: <code>{html.escape(query)}</code>",
            "",
        ]

        for index, item in enumerate(results, start=1):
            response.append(
                f"{index}. <b>{html.escape(item.supplier_name)}</b>"
            )
            response.append(
                f"   {html.escape(item.title)}"
            )

            if item.price:
                response.append(
                    f"   💰 Цена сайта: <b>{html.escape(str(item.price))}</b>"
                )

                calculated_price = _calculate_supplier_price(
                    supplier_name=item.supplier_name,
                    title=item.title,
                    raw_price=str(item.price),
                )

                if calculated_price:
                    response.append(
                        f"   🧮 Цена после скидки: <b>{html.escape(calculated_price)}</b>"
                    )

            if item.stock:
                response.append(
                    f"   📦 Остаток: {html.escape(str(item.stock))}"
                )

            response.append("")

        await message.answer(
            "\n".join(response),
            reply_markup=main_menu_kb,
        )

    except Exception as exc:
        await message.answer(
            "❌ Ошибка поиска по сайтам поставщиков:\n"
            f"<code>{html.escape(type(exc).__name__)}: {html.escape(str(exc))}</code>",
            reply_markup=main_menu_kb,
        )


def _extract_query(text: str) -> str:
    clean = text.strip()

    prefixes = [
        "найди у поставщиков",
        "поиск у поставщиков",
        "сайты",
        "поставщики",
    ]

    lower = clean.lower()

    for prefix in prefixes:
        if lower.startswith(prefix):
            return clean[len(prefix):].strip(" :,-")

    return clean



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

    # Правило пока только для котлов Baxi.
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
