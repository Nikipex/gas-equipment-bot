from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.services.equipment.product_specs_service import ProductSpecsService


@dataclass(frozen=True)
class QuoteLine:
    query: str
    qty: float
    product_name: str | None
    price: float | None
    stock: float | None
    line_total: float | None


class QuoteBuilderService:
    def __init__(self) -> None:
        self.specs = ProductSpecsService()

    def build(self, text: str) -> list[QuoteLine]:
        discount_percent = _extract_discount_percent(text)
        round_to = _extract_round_to(text)

        lines = []

        for raw_line in text.splitlines():
            raw_line = raw_line.strip(" -•\t")
            if not raw_line:
                continue

            if _is_quote_rule_line(raw_line):
                continue

            qty = _extract_qty(raw_line)
            query = _clean_query(raw_line)

            if not query:
                continue

            matches = self.specs.find(query, limit=1)

            if not matches:
                lines.append(
                    QuoteLine(
                        query=query,
                        qty=qty,
                        product_name=None,
                        price=None,
                        stock=None,
                        line_total=None,
                    )
                )
                continue

            row = matches[0]
            price = _to_float(row.get("price"))
            stock = _to_float(row.get("stock"))

            if price is not None:
                price = _apply_price_rules(
                    price,
                    discount_percent=discount_percent,
                    round_to=round_to,
                )

            lines.append(
                QuoteLine(
                    query=query,
                    qty=qty,
                    product_name=str(row.get("product_name")),
                    price=price,
                    stock=stock,
                    line_total=price * qty if price is not None else None,
                )
            )

        return lines


def build_quote_text(lines: list[QuoteLine]) -> str:
    result = [
        "🧾 <b>Черновик КП</b>",
        "",
    ]

    total = 0.0
    has_total = False

    for idx, item in enumerate(lines, start=1):
        if item.product_name:
            result.append(f"{idx}. <b>{_esc(item.product_name)}</b>")
            result.append(f"   Кол-во: <b>{item.qty:g} шт.</b>")
            result.append(f"   Цена: <b>{_format_money(item.price)}</b>")
            result.append(f"   Остаток: <b>{_format_stock(item.stock)}</b>")

            if item.line_total is not None:
                result.append(f"   Сумма: <b>{_format_money(item.line_total)}</b>")
                total += item.line_total
                has_total = True
        else:
            result.append(f"{idx}. ⚠️ <b>{_esc(item.query)}</b>")
            result.append("   Не нашёл точное совпадение в прайсах.")

        result.append("")

    if has_total:
        result.append(f"💰 <b>Итого: {_format_money(total)}</b>")
        result.append("")

    result.append("📌 <b>Перед отправкой клиенту:</b>")
    result.append("• проверить актуальность цен")
    result.append("• проверить свободный остаток")
    result.append("• при необходимости согласовать скидку / доставку")

    return "\n".join(result)




def _is_quote_rule_line(line: str) -> bool:
    low = line.lower().strip()

    has_discount = bool(re.search(r"(?:скидка|скинуть|минус)\s*\d+(?:[,.]\d+)?\s*%|-\d+(?:[,.]\d+)?\s*%", low))
    has_round = "округл" in low

    # строка только про правила цены, без товара
    if has_discount or has_round:
        product_words = [
            "котел", "котёл", "бойлер", "водонагрев", "насос",
            "радиатор", "лемакс", "ariston", "midea", "baxi", "бакси",
            "orso", "thermex", "аристон", "мидеа",
        ]
        if not any(word in low for word in product_words):
            return True

    return False


def _extract_discount_percent(text: str) -> float:
    patterns = [
        r"(?:скидка|скинуть|минус)\s*(\d+(?:[,.]\d+)?)\s*%",
        r"-(\d+(?:[,.]\d+)?)\s*%",
    ]

    low = text.lower()

    for pattern in patterns:
        m = re.search(pattern, low)
        if m:
            value = float(m.group(1).replace(",", "."))
            if 0 <= value <= 50:
                return value

    return 0.0


def _extract_round_to(text: str) -> int | None:
    low = text.lower()

    m = re.search(r"округл\w*\s*(?:до)?\s*(\d{2,4})", low)
    if m:
        value = int(m.group(1))
        if value in {10, 50, 100, 500, 1000}:
            return value

    if "округлить" in low or "округли" in low:
        return 100

    return None


def _apply_price_rules(
    price: float,
    *,
    discount_percent: float,
    round_to: int | None,
) -> float:
    if discount_percent:
        price = price * (1 - discount_percent / 100)

    if round_to:
        price = round(price / round_to) * round_to

    return float(price)


def _extract_qty(line: str) -> float:
    patterns = [
        r"(?:x|х|\*)\s*(\d+(?:[,.]\d+)?)",
        r"(\d+(?:[,.]\d+)?)\s*(?:шт|штук|ед)",
        r"[-—]\s*(\d+(?:[,.]\d+)?)\s*$",
    ]

    for pattern in patterns:
        m = re.search(pattern, line.lower())
        if m:
            return float(m.group(1).replace(",", "."))

    return 1.0


def _clean_query(line: str) -> str:
    line = re.sub(r"(?:x|х|\*)\s*\d+(?:[,.]\d+)?", "", line, flags=re.I)
    line = re.sub(r"\d+(?:[,.]\d+)?\s*(?:шт|штук|ед)", "", line, flags=re.I)
    line = re.sub(r"[-—]\s*\d+(?:[,.]\d+)?\s*$", "", line)
    line = line.strip(" :;,-—")
    return line


def _to_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _format_money(value: float | None) -> str:
    if value is None:
        return "не указана"
    return f"{value:,.0f} ₽".replace(",", " ")


def _format_stock(value: float | None) -> str:
    if value is None:
        return "не указан"
    return f"{value:g} шт."


def _esc(value: str) -> str:
    import html
    return html.escape(str(value))
