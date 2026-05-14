"""Stock schema."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class StockRead(BaseModel):
    """Read-only stock snapshot."""

    id: int
    product_id: int
    warehouse: str
    quantity: int
    snapshot_date: datetime

    model_config = {"from_attributes": True}
