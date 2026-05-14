"""Mini-price service — merge-aware, builds one offer per logical product.

Pipeline::

    query → search → merge matched products → best offer per group → format

This service does **not** touch the database and does **not** modify
the existing search or import APIs.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from loguru import logger

from app.schemas.normalized_product import NormalizedProduct
from app.services.merge_service import MergeService, MergedGroup
from app.services.search_service import SearchService, ScoredResult
from app.services.stock_match_service import StockMatchService


# ---------------------------------------------------------------------------
# Offer dataclass (lightweight, no Pydantic)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Offer:
    """A single product offer for the mini-price output."""

    product_name: str
    brand: str | None = None
    category: str | None = None
    sku: str | None = None
    price: float | None = None
    stock: int | None = None
    source: str | None = None
    source_count: int = 1
    warehouse_stock_qty: float | None = None
    warehouse_name: str | None = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PricingService:
    """Build merge-aware mini-price lists from search results.

    Usage::

        svc = PricingService(products)
        print(svc.format_miniprice(svc.get_miniprice("котел baxi")))
    """

    def __init__(
        self,
        products: list[NormalizedProduct],
        stock_df: pd.DataFrame | None = None,
    ) -> None:
        self._products = products
        self._search = SearchService(products)
        self._stock_matcher: StockMatchService | None = None

        if stock_df is not None and not stock_df.empty:
            self._stock_matcher = StockMatchService(stock_df)
            self._stock_matcher.build_index()
            logger.info(
                "PricingService: stock enrichment enabled (rows={})",
                len(stock_df),
            )
        else:
            logger.info("PricingService: stock enrichment disabled")

    # ------------------------------------------------------------------
    # Main entry point (public API unchanged)
    # ------------------------------------------------------------------

    def get_miniprice(self, query: str, limit: int = 5) -> list[Offer]:
        """Search → merge → best offer per group → top N.

        Args:
            query: User search string.
            limit: Max offers to return.

        Returns:
            Sorted list of :class:`Offer` — one per logical product.
        """
        results = self._search.search(query, top_n=limit * 3)

        # Merge matched products into logical groups
        matched_products = [r.product for r in results]
        groups = MergeService(matched_products).merge_products()

        logger.info(
            "PricingService: query='{}' → {} hits → {} groups",
            query, len(results), len(groups),
        )

        # Pick best offer from each group
        offers = [
            self._best_offer_in_group(g)
            for g in groups
            if self._group_has_pricing(g)
        ]

        if self._stock_matcher is not None:
            offers = [self._enrich_offer_with_stock(o) for o in offers]

        # Sort: in-stock first → more stock → cheaper
        offers = self._sort_offers(offers, limit=limit)

        logger.info("PricingService: returning {} unique offers", len(offers))
        return offers

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    @staticmethod
    def build_offers(results: list[ScoredResult]) -> list[Offer]:
        """Convert search results into :class:`Offer` objects.

        Products with **no price and no stock** are skipped.
        """
        offers: list[Offer] = []
        for r in results:
            p = r.product
            if p.price is None and p.stock is None:
                continue
            offers.append(Offer(
                product_name=p.name,
                brand=p.brand,
                category=p.category,
                sku=p.sku,
                price=float(p.price) if p.price is not None else None,
                stock=p.stock,
                source=None,
                source_count=1,
                warehouse_stock_qty=None,
                warehouse_name=None,
            ))
        return offers

    @staticmethod
    def select_best_offers(offers: list[Offer], limit: int = 5) -> list[Offer]:
        """Sort offers: in-stock first, then cheapest, return top *limit*."""
        def _sort_key(o: Offer) -> tuple[int, int, float]:
            has_stock = 0 if (o.stock is not None and o.stock > 0) else 1
            stock_qty = -(o.stock or 0)
            price_val = o.price if o.price is not None else float("inf")
            return (has_stock, stock_qty, price_val)

        return sorted(offers, key=_sort_key)[:limit]

    # ------------------------------------------------------------------
    # Merge-aware helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _best_offer_in_group(group: MergedGroup) -> Offer:
        """Select the single best representative offer from a merged group.

        If priced products exist, prefer: has stock → more stock → lower price.
        If no priced products exist, still return the best representative product so
        the offer can later be enriched with 1C warehouse stock.
        """
        priced = [p for p in group.products if p.price is not None]

        if priced:
            def _rank_priced(p: NormalizedProduct) -> tuple[int, int, float, str]:
                has_stock = 0 if (p.stock is not None and p.stock > 0) else 1
                stock_qty = -(p.stock or 0)
                price_val = float(p.price) if p.price is not None else float("inf")
                return (has_stock, stock_qty, price_val, p.name)

            best = min(priced, key=_rank_priced)
        else:
            def _rank_fallback(p: NormalizedProduct) -> tuple[int, str]:
                has_stock = 0 if (p.stock is not None and p.stock > 0) else 1
                return (has_stock, p.name)

            best = min(group.products, key=_rank_fallback)

        return Offer(
            product_name=group.canonical_name,
            brand=group.brand,
            category=group.category,
            sku=group.sku,
            price=float(best.price) if best.price is not None else None,
            stock=best.stock,
            source=None,
            source_count=len(group.products),
            warehouse_stock_qty=None,
            warehouse_name=None,
        )

    def _group_has_pricing(self, group: MergedGroup) -> bool:
        """Return True if the group is displayable.

        A group is displayable when:
        - at least one product has supplier price or supplier stock, OR
        - at least one product has matched 1C warehouse stock.
        """
        if any(p.price is not None or p.stock is not None for p in group.products):
            return True

        if self._stock_matcher is None:
            return False

        for product in group.products:
            match = self._stock_matcher.get_stock_for_product(product)
            if match.matched and match.total_qty > 0:
                return True

        return False

    @staticmethod
    def _sort_offers(offers: list[Offer], limit: int) -> list[Offer]:
        """Sort and truncate."""
        def _key(o: Offer) -> tuple[int, float, float]:
            effective_stock = (
                o.warehouse_stock_qty
                if o.warehouse_stock_qty is not None
                else (o.stock or 0)
            )
            has_stock = 0 if effective_stock > 0 else 1
            stock_qty = -effective_stock
            price_val = o.price if o.price is not None else float("inf")
            return (has_stock, stock_qty, price_val)

        return sorted(offers, key=_key)[:limit]

    def _enrich_offer_with_stock(self, offer: Offer) -> Offer:
        """Attach 1C warehouse stock to an offer when possible."""
        if self._stock_matcher is None:
            return offer

        product = next(
            (
                p for p in self._products
                if p.name == offer.product_name
            ),
            None,
        )
        if product is None:
            return offer

        match = self._stock_matcher.get_stock_for_product(product)
        if not match.matched:
            return offer

        return Offer(
            product_name=offer.product_name,
            brand=offer.brand,
            category=offer.category,
            sku=offer.sku,
            price=offer.price,
            stock=offer.stock,
            source=offer.source,
            source_count=offer.source_count,
            warehouse_stock_qty=match.total_qty,
            warehouse_name=match.first_warehouse,
        )

    # ------------------------------------------------------------------
    # Telegram formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_miniprice(offers: list[Offer]) -> str:
        """Format offers as a compact Telegram-friendly string."""
        if not offers:
            return "❌ Предложений не найдено"

        lines: list[str] = ["📦 <b>Мини-прайс:</b>\n"]

        for idx, o in enumerate(offers, 1):
            lines.append(f"{idx}. {o.product_name}")

            details: list[str] = []
            if o.price is not None:
                details.append(f"💰 {_fmt_price(o.price)} ₽")
            if o.stock is not None:
                details.append(f"📦 Поставщик: {_fmt_qty(float(o.stock))} шт")
            if details:
                lines.append("   " + " | ".join(details))

            tags: list[str] = []
            if o.brand:
                tags.append(f"🏷 {o.brand}")
            if o.category:
                tags.append(f"📁 {o.category}")
            if tags:
                lines.append("   " + " | ".join(tags))

            if o.warehouse_stock_qty is not None:
                warehouse_label = " ".join((o.warehouse_name or "Склад").split())
                lines.append(
                    f"   🏬 {warehouse_label}: {_fmt_qty(o.warehouse_stock_qty)} шт"
                )

            lines.append("")  # blank line between offers

        return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_price(value: float) -> str:
    """Format price with thousands separator (space), no decimals."""
    return f"{value:,.0f}".replace(",", " ")


def _fmt_qty(value: float) -> str:
    """Format quantity: integers without decimals, floats with up to 2 decimals."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")
