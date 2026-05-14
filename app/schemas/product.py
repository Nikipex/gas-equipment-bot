"""Product schema."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ProductRead(BaseModel):
    """Read-only representation of a product."""

    id: int
    article: str
    name: str
    brand: str | None = None
    category: str | None = None
    description: str | None = None
    unit: str = "шт"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    """Payload for creating a product."""

    article: str
    name: str
    brand: str | None = None
    category: str | None = None
    description: str | None = None
    unit: str = "шт"
