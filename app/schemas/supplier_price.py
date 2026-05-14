"""Supplier price schema."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class SupplierPriceRead(BaseModel):
    """Read-only supplier price entry."""

    id: int
    product_id: int
    supplier: str
    price: Decimal
    currency: str = "RUB"
    valid_from: datetime
    valid_to: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
