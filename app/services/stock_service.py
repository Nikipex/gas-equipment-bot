"""Stock service — business logic for stock lookups."""

from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.stock_snapshot import StockSnapshot
from app.repositories.stock_repository import StockRepository


class StockService:
    """Orchestrates stock-related operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = StockRepository(session)

    async def get_latest(self, product_id: int) -> StockSnapshot | None:
        logger.info("Stock lookup: product_id={}", product_id)
        return await self._repo.get_latest_by_product(product_id)
