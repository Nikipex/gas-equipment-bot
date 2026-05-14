"""Supplier price service — business logic for price comparisons."""

from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.supplier_price import SupplierPrice
from app.repositories.supplier_price_repository import SupplierPriceRepository


class SupplierPriceService:
    """Orchestrates supplier-price operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = SupplierPriceRepository(session)

    async def list_prices(self, product_id: int) -> list[SupplierPrice]:
        logger.info("Price list: product_id={}", product_id)
        return await self._repo.list_by_product(product_id)

    async def best_price(self, product_id: int) -> SupplierPrice | None:
        return await self._repo.get_best_price(product_id)
