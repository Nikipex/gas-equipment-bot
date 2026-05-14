"""Stock repository — async CRUD operations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.stock_snapshot import StockSnapshot


class StockRepository:
    """Data-access layer for stock snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest_by_product(self, product_id: int) -> StockSnapshot | None:
        stmt = (
            select(StockSnapshot)
            .where(StockSnapshot.product_id == product_id)
            .order_by(StockSnapshot.snapshot_date.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_product(
        self, product_id: int, limit: int = 50
    ) -> list[StockSnapshot]:
        stmt = (
            select(StockSnapshot)
            .where(StockSnapshot.product_id == product_id)
            .order_by(StockSnapshot.snapshot_date.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
