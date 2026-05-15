"""Quote calculation service."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.postgres_catalog_service import CatalogItem, PostgresCatalogService


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

    def calculate(self, text: str, round_step: int | None = None) -> list[QuoteLine]:
        lines = []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if line.lower().startswith(("просчет", "просчёт", "расчет", "расчёт")):
                continue

            query, qty = self._parse_line(line)
            if not query:
                continue

            results = self.catalog.search(query, limit=1)
            item = results[0] if results else None

            purchase_price = None
            line_total = None

            if item and item.purchase_price:
                purchase_price = _round_price(item.purchase_price, round_step)
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


def _round_price(value: float, step: int | None) -> float:
    if step and step > 0:
        return round(value / step) * step
    return round(value, 0)
