"""Supplier price repository — async CRUD operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.supplier_price import SupplierPrice


class SupplierPriceRepository:
    """Data-access layer for supplier prices."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_product(
        self, product_id: int, limit: int = 50
    ) -> list[SupplierPrice]:
        stmt = (
            select(SupplierPrice)
            .where(SupplierPrice.product_id == product_id)
            .order_by(SupplierPrice.price.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_best_price(self, product_id: int) -> SupplierPrice | None:
        stmt = (
            select(SupplierPrice)
            .where(SupplierPrice.product_id == product_id)
            .order_by(SupplierPrice.price.asc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
