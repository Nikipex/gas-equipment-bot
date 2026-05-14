"""Offer service — builds commercial offers from product + price + stock data."""

from __future__ import annotations

from loguru import logger


class OfferService:
    """Placeholder for commercial-offer generation logic.

    Future: combine product info, stock levels, and supplier prices
    into a formatted offer message or PDF.
    """

    async def build_mini_price(self, product_ids: list[int]) -> str:
        """Generate a compact price list (stub)."""
        logger.info("Building mini-price for {} products", len(product_ids))
        return "🛠 Мини-прайс: функция в разработке."
