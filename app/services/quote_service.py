"""Quote calculation service."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.postgres_catalog_service import CatalogItem, PostgresCatalogService
from app.services.radiator_price_service import radiator_price_service


@dataclass
class QuoteLine:
    query: str
    qty: float
    item: CatalogItem | None
    purchase_price: float | None
    line_total: float | None


class QuoteService:
    def __init__(self) -> None:
        self.catalog = PostgresCatalogService()

    def calculate(
        self,
        text: str,
        round_step: int | None = None,
        markup_percent: float | None = None,
        markup_amount: float | None = None,
    ) -> list[QuoteLine]:
        lines: list[QuoteLine] = []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if line.lower().startswith(("просчет", "просчёт", "расчет", "расчёт")):
                continue

            raw_query, qty = self._parse_line(line)
            if not raw_query:
                continue

            query = _normalize_quote_query(raw_query)
            price_profile = _extract_price_profile(query)

            results = self.catalog.search(query, limit=10)
            item = _pick_best_quote_item(results, query)

            purchase_price = None
            line_total = None

            if item:
                radiator_price = (
                    radiator_price_service.get_price_for_product(item.product_name, price_profile)
                    if price_profile
                    else None
                )

                base_price = radiator_price or item.excel_client_price or item.purchase_price

                if base_price:
                    final_price = _apply_markup(float(base_price), markup_percent, markup_amount)
                    purchase_price = _round_price(final_price, round_step)
                    line_total = purchase_price * qty

            if item is None and price_profile:
                direct_name = _build_direct_radiator_name(query)
                if direct_name:
                    radiator_price = radiator_price_service.get_price_for_product(
                        direct_name,
                        price_profile,
                    )

                    if radiator_price:
                        item = CatalogItem(
                            product_name=direct_name,
                            product_group="radiator price fallback",
                            stock_qty=None,
                            purchase_price=None,
                            is_alternative=False,
                            excel_price_profile=price_profile,
                            excel_client_price=radiator_price,
                        )
                        final_price = _apply_markup(float(radiator_price), markup_percent, markup_amount)
                        purchase_price = _round_price(final_price, round_step)
                        line_total = purchase_price * qty

            lines.append(
                QuoteLine(
                    query=query,
                    qty=qty,
                    item=item,
                    purchase_price=purchase_price,
                    line_total=line_total,
                )
            )

        return lines

    @staticmethod
    def _parse_line(line: str) -> tuple[str, float]:
        match = re.search(r"(?:[-—xх*]\s*)?(\d+(?:[.,]\d+)?)\s*(?:шт)?\s*$", line, re.I)
        if not match:
            return line.strip(), 1.0

        qty = float(match.group(1).replace(",", "."))
        query = line[: match.start()].strip(" -—xх*")
        return query, qty


def _normalize_quote_query(query: str) -> str:
    """Normalize quote line query before catalog search.

    Supports compact radiator codes:
    225001200 -> радиатор 500 22 1200 прайс 4300
    22500600  -> радиатор 500 22 0600 прайс 4300
    """
    clean = query.strip()
    low = clean.lower().replace("ё", "е")

    price_profile = _extract_price_profile(clean)

    compact_match = re.search(r"\b(10|11|20|21|22|30|33)(200|300|500|600|900)(\d{3,4})\b", low)
    if compact_match:
        radiator_type = compact_match.group(1)
        height = compact_match.group(2)
        length = compact_match.group(3).zfill(4)

        normalized = f"радиатор {height} {radiator_type} {length}"
        if price_profile:
            normalized += f" прайс {price_profile}"
        return normalized

    return clean


def _extract_price_profile(query: str) -> str | None:
    match = re.search(r"(?:прайс|price)\s*[:№#-]?\s*(\d{3,6})", query.lower())
    return match.group(1) if match else None


def _build_direct_radiator_name(query: str) -> str | None:
    low = query.lower().replace("ё", "е")

    nums = [int(x) for x in re.findall(r"\b\d{2,4}\b", low)]
    height = next((x for x in nums if x in {200, 300, 500, 600, 900}), None)
    radiator_type = next((x for x in nums if x in {10, 11, 20, 21, 22, 30, 33}), None)
    length = next((x for x in nums if 300 <= x <= 3000 and x != height), None)

    if height and radiator_type and length:
        return f"Стальной радиатор   {height}//{radiator_type}*{str(length).zfill(4)}    (1,2)"

    return None


def _pick_best_quote_item(items: list[CatalogItem], query: str = "") -> CatalogItem | None:
    """Pick safest item for quote.

    Quote mode must be stricter than regular search:
    - if query has model token CTN, CTFS must not pass;
    - if query has explicit latin model/series tokens, they must exist in product name;
    - prefer (1,2) radiator core over VK/нижнее;
    - prefer in-stock item only after model correctness.
    """
    if not items:
        return None

    query_norm = _normalize_for_quote_match(query)

    # Important model tokens from user query.
    # Ignore generic words and price profile words.
    query_tokens = re.findall(r"[a-zа-я]+|\d+", query_norm)
    generic = {
        "радиатор", "стальной", "котел", "котёл", "газовый", "настенный",
        "прайс", "price", "шт", "штук",
        "baxi", "бакси", "navien", "навьен", "fondital", "фондитал",
        "minorca", "минорка",
    }

    # Letter model tokens like CTN / CTFS / ECO / NOVA / Deluxe.
    # For quote we especially protect short latin model codes.
    required_letter_tokens = [
        token
        for token in query_tokens
        if token.isalpha()
        and token not in generic
        and len(token) >= 2
    ]

    # Numeric model tokens, but ignore price profiles like 4100/4300.
    required_numeric_tokens = [
        token
        for token in query_tokens
        if token.isdigit()
        and not (len(token) >= 4 and int(token) >= 1000)
    ]

    def has_token(name_norm: str, token: str) -> bool:
        return re.search(rf"(?<![a-zа-я0-9]){re.escape(token)}(?![a-zа-я0-9])", name_norm) is not None

    strict_candidates: list[CatalogItem] = []

    for item in items:
        name_norm = _normalize_for_quote_match(item.product_name)

        # If user wrote explicit model code, wrong model must be rejected.
        if required_letter_tokens and not all(has_token(name_norm, token) for token in required_letter_tokens):
            continue

        # Numeric tokens should be present as separate model numbers where possible.
        if required_numeric_tokens and not all(token in name_norm for token in required_numeric_tokens):
            continue

        strict_candidates.append(item)

    # If strict filter kills everything, better return None than wrong CTFS for CTN.
    candidates = strict_candidates
    if not candidates:
        return None

    def score(item: CatalogItem) -> tuple[int, int, int, float]:
        name = item.product_name.lower().replace("ё", "е")
        name_norm = _normalize_for_quote_match(item.product_name)

        has_12 = "(1,2)" in name
        is_vk = "vk" in name or "ниж" in name or "низ" in name
        stock = float(item.stock_qty or 0)

        exact_phrase = 1 if query_norm and query_norm in name_norm else 0

        return (
            exact_phrase,
            1 if has_12 and not is_vk else 0,
            1 if stock > 0 else 0,
            stock,
        )

    return sorted(candidates, key=score, reverse=True)[0]


def _round_price(value: float, step: int | None) -> float:
    if step and step > 0:
        return round(value / step) * step
    return round(value, 0)



def _apply_markup(
    value: float,
    markup_percent: float | None = None,
    markup_amount: float | None = None,
) -> float:
    if markup_percent is not None:
        return value * (1 + markup_percent / 100)
    if markup_amount is not None:
        return value + markup_amount
    return value



def _normalize_for_quote_match(value: str) -> str:
    value = str(value or "").lower().replace("ё", "е")
    value = value.replace("с", "c") if value.strip() in {"с"} else value
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()
