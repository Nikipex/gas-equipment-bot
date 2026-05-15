"""Dynamic price list generation service."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.postgres_catalog_service import CatalogItem, PostgresCatalogService


@dataclass
class PriceListLine:
    item: CatalogItem
    sale_price: float


@dataclass
class PriceListRequest:
    query: str
    markup_percent: float | None = None
    markup_amount: float | None = None
    show_stock: bool = True
    show_purchase: bool = True
    round_step: int | None = None


class PriceListService:
    def __init__(self) -> None:
        self.catalog = PostgresCatalogService()

    def build(self, text: str, limit: int = 20, round_step: int | None = None) -> tuple[PriceListRequest, list[PriceListLine]]:
        request = self._parse_request(text)
        if round_step:
            request.round_step = round_step

        results = self.catalog.search(request.query, limit=limit)

        lines: list[PriceListLine] = []
        for item in results:
            if item.stock_qty is None or item.stock_qty <= 0:
                continue
            if item.purchase_price is None or item.purchase_price <= 0:
                continue

            sale_price = self._apply_markup(item.purchase_price, request)
            lines.append(PriceListLine(item=item, sale_price=sale_price))

        return request, lines

    @staticmethod
    def _parse_request(text: str) -> PriceListRequest:
        clean = text.lower().strip()
        clean = re.sub(r"^(прайс|price)\s+", "", clean).strip()

        show_stock = True
        show_purchase = True

        if "клиентский" in clean or "для клиента" in clean:
            show_stock = False
            show_purchase = False

        if "без остатков" in clean or "без остатка" in clean:
            show_stock = False

        if "без закупки" in clean or "без закуп" in clean:
            show_purchase = False

        round_step = None
        round_match = re.search(r"округл(?:ение|ить)?\s*(10|100)", clean)
        if round_match:
            round_step = int(round_match.group(1))

        clean = re.sub(
            r"клиентский|для клиента|без остатков|без остатка|без закупки|без закуп|округл(?:ение|ить)?\s*(?:10|100)",
            " ",
            clean,
        )
        clean = re.sub(r"\s+", " ", clean).strip()

        percent_match = re.search(r"\+?\s*(\d+(?:[.,]\d+)?)\s*%", clean)
        amount_match = re.search(r"\+\s*(\d+(?:[.,]\d+)?)\s*(?:р|руб|₽)?", clean)

        markup_percent = None
        markup_amount = None

        if percent_match:
            markup_percent = float(percent_match.group(1).replace(",", "."))
            query = clean[: percent_match.start()].strip()
        elif amount_match:
            markup_amount = float(amount_match.group(1).replace(",", "."))
            query = clean[: amount_match.start()].strip()
        else:
            query = clean

        return PriceListRequest(
            query=query,
            markup_percent=markup_percent,
            markup_amount=markup_amount,
            show_stock=show_stock,
            show_purchase=show_purchase,
            round_step=round_step,
        )

    @staticmethod
    def _apply_markup(purchase_price: float, request: PriceListRequest) -> float:
        if request.markup_percent is not None:
            price = purchase_price * (1 + request.markup_percent / 100)
        elif request.markup_amount is not None:
            price = purchase_price + request.markup_amount
        else:
            price = purchase_price

        return _round_price(price, request.round_step)


def _round_price(value: float, step: int | None) -> float:
    if step and step > 0:
        return round(value / step) * step
    return round(value, 0)
