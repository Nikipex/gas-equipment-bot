"""Normalised product schema — the canonical representation after import.

This schema is intentionally separate from
:class:`~app.schemas.product.ProductRead` to avoid coupling the import
pipeline with the existing database-backed product model.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class NormalizedProduct(BaseModel):
    """Product record after import normalisation.

    Used as the output of :class:`~app.services.import_service.ImportService`
    and as input for :class:`~app.services.search_service.SearchService`.
    """

    name: str
    name_normalized: str
    brand: str | None = None
    category: str | None = None
    sku: str | None = None
    price: Decimal | None = None
    stock: int | None = None
