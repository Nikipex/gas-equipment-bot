"""Map detected DataFrame columns to a canonical product structure.

Takes the raw DataFrame + column mapping from the detector and produces
a list of flat dictionaries ready for normalisation and schema validation.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pandas as pd
from loguru import logger

from app.utils.normalization import extract_brand


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def map_to_canonical(
    df: pd.DataFrame,
    column_map: dict[str, str | None],
) -> list[dict[str, str | Decimal | int | None]]:
    """Rename detected columns and build canonical product dictionaries.

    For each row the function emits a dict with keys:
    ``name``, ``price``, ``stock``, ``sku``, ``brand``, ``category``.

    If ``brand`` is not present as a column, it is extracted from the
    product name via :func:`app.utils.normalization.extract_brand`.

    Args:
        df: Cleaned DataFrame.
        column_map: ``{canonical_key: actual_column_name | None}`` from
            :func:`~app.integrations.excel.detector.detect_columns`.

    Returns:
        List of product dictionaries in canonical form.
    """
    records: list[dict[str, str | Decimal | int | None]] = []

    for _, row in df.iterrows():
        name = _get(row, column_map, "name")
        if not name:
            continue  # пропускаем строки без наименования

        brand = _get(row, column_map, "brand")
        if not brand:
            brand = extract_brand(name)

        record: dict[str, str | Decimal | int | None] = {
            "name": name,
            "price": _to_decimal(_get(row, column_map, "price")),
            "stock": _to_int(_get(row, column_map, "stock")),
            "sku": _get(row, column_map, "sku"),
            "brand": brand,
            "category": _get(row, column_map, "category"),
        }
        records.append(record)

    logger.info("Маппинг завершён: {} записей", len(records))
    return records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(
    row: pd.Series,  # type: ignore[type-arg]
    column_map: dict[str, str | None],
    key: str,
) -> str | None:
    """Safely extract a value from *row* using the column mapping."""
    col = column_map.get(key)
    if col is None or col not in row.index:
        return None
    val = row[col]
    if pd.isna(val):
        return None
    return str(val).strip() or None


def _to_decimal(value: str | None) -> Decimal | None:
    """Convert string to :class:`Decimal`, returning ``None`` on failure."""
    if value is None:
        return None
    try:
        # handle comma as decimal separator (common in RU locales)
        return Decimal(value.replace(",", ".").replace(" ", ""))
    except (InvalidOperation, AttributeError):
        return None


def _to_int(value: str | None) -> int | None:
    """Convert string to ``int``, returning ``None`` on failure."""
    if value is None:
        return None
    try:
        return int(float(value.replace(",", ".").replace(" ", "")))
    except (ValueError, AttributeError):
        return None
