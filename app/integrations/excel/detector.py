"""Column structure detector for Excel / CSV files.

Uses fuzzy matching to identify which DataFrame columns correspond to
canonical product attributes (name, price, stock, sku).
"""

from __future__ import annotations

from difflib import SequenceMatcher

import pandas as pd
from loguru import logger


# ---------------------------------------------------------------------------
# Canonical column names → known aliases (Russian + English)
# ---------------------------------------------------------------------------

COLUMN_ALIASES: dict[str, list[str]] = {
    "name": [
        "наименование", "название", "товар", "номенклатура",
        "name", "product_name", "product", "описание",
    ],
    "price": [
        "цена", "стоимость", "price", "розница",
        "цена_розн", "цена_опт", "прайс",
    ],
    "stock": [
        "остаток", "количество", "кол_во", "stock",
        "qty", "quantity", "наличие", "кол",
    ],
    "sku": [
        "артикул", "article", "sku", "код",
        "код_товара", "product_key", "арт",
    ],
    "brand": [
        "бренд", "brand", "производитель", "марка",
        "торговая_марка",
    ],
    "category": [
        "категория", "category", "группа", "раздел",
        "тип",
    ],
}

# Minimum similarity ratio to consider a column a match.
_MIN_SIMILARITY: float = 0.55


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """Match DataFrame columns to canonical product attributes.

    For each canonical key (``name``, ``price``, ``stock``, ``sku``,
    ``brand``, ``category``) the function finds the best-matching
    DataFrame column using ``difflib.SequenceMatcher``.

    Args:
        df: Cleaned DataFrame (column names should already be normalised).

    Returns:
        Mapping ``{canonical_key: actual_column_name | None}``.
        ``None`` means no column matched the canonical key above the
        similarity threshold.
    """
    columns = [str(c).lower() for c in df.columns]
    mapping: dict[str, str | None] = {}

    for canonical, aliases in COLUMN_ALIASES.items():
        best_col: str | None = None
        best_score: float = 0.0

        for col in columns:
            # 1) exact match — immediate win
            if col in aliases or col == canonical:
                best_col = col
                best_score = 1.0
                break

            # 2) fuzzy match against every alias
            for alias in aliases:
                score = SequenceMatcher(None, col, alias).ratio()
                if score > best_score:
                    best_score = score
                    best_col = col

        if best_score >= _MIN_SIMILARITY:
            mapping[canonical] = best_col
            logger.debug(
                "Колонка '{}' → '{}' (score={:.2f})", best_col, canonical, best_score,
            )
        else:
            mapping[canonical] = None
            logger.debug("Канонический ключ '{}' — совпадений не найдено", canonical)

    logger.info("Результат детекции колонок: {}", mapping)
    return mapping
