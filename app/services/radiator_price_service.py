"""Excel radiator client price lookup service."""

from __future__ import annotations

import re
from pathlib import Path

from app.services.radiator_price_loader import (
    DEFAULT_PRICE_DIR,
    extract_radiator_size,
    find_radiator_price,
    normalize_connection,
)


class RadiatorPriceService:
    """Finds client radiator price in local Excel price files."""

    def __init__(self, price_dir: Path = DEFAULT_PRICE_DIR) -> None:
        self.price_dir = price_dir

    def extract_profile(self, query: str) -> str | None:
        """
        Examples:
            прайс 4300
            22 500 1000 прайс 4100
            radiator 500x22x1000 3950
        """

        match = re.search(
            r"(?:прайс|price)\s*[:№#-]?\s*(\d{3,6})",
            query.lower(),
        )

        if match:
            return match.group(1)

        # fallback:
        # если просто написали "4300"
        standalone = re.findall(r"\b(3\d{3}|4\d{3}|5\d{3})\b", query)
        if standalone:
            return standalone[-1]

        return None

    @staticmethod
    def calculate_price(
        purchase_price: float | None,
        client_type: str = "default",
    ) -> float | None:
        """Fallback calculated client price from 1C purchase price."""
        if purchase_price is None or purchase_price <= 0:
            return None

        markup_percent = {
            "default": 25.0,
            "retail": 35.0,
            "installer": 25.0,
            "dealer": 15.0,
        }.get(client_type, 25.0)

        raw_price = purchase_price * (1 + markup_percent / 100)
        return round(raw_price / 100) * 100

    def get_price_for_product(
        self,
        product_name: str,
        profile: str | None,
    ) -> float | None:

        if not profile:
            return None

        size = extract_radiator_size(product_name)
        if size is None:
            return None

        connection = normalize_connection(product_name)

        row = find_radiator_price(
            radiator_type=size[0],
            height=size[1],
            length=size[2],
            profile=profile,
            connection=connection,
            price_dir=self.price_dir,
        )

        return row.price if row else None


radiator_price_service = RadiatorPriceService()
