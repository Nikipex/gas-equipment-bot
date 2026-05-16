"""AI intent models for manager natural-language commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


IntentName = Literal[
    "supplier_search",
    "price_list",
    "quote",
    "unknown",
]


@dataclass(frozen=True)
class AiIntent:
    intent: IntentName
    query: str
    supplier_key: str | None = None
    discount_percent: float | None = None
    markup_amount: float | None = None
    round_step: int | None = None
    client_mode: bool = False
    show_stock: bool = True
    show_purchase: bool = True
    raw_text: str = ""

    def to_command_text(self) -> str:
        parts = [self.query.strip()]

        if self.supplier_key:
            parts.insert(0, self.supplier_key)

        if self.discount_percent is not None:
            parts.append(f"-{self.discount_percent:g}%")

        if self.markup_amount is not None:
            parts.append(f"+{self.markup_amount:g}")

        if self.round_step is not None:
            parts.append(f"до {self.round_step}")

        return " ".join(part for part in parts if part).strip()
