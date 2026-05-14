"""Parser for 1С:Предприятие Excel exports.

Typical 1C exports have a header block at the top (company name, date, etc.)
followed by a table with known column names.  This module detects the table
start row and normalises the output to a regular pandas DataFrame.

.. note::
    This is a **minimal stub** — extend as more 1C export formats are
    encountered in production.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from loguru import logger

# Known 1C column names → canonical names used in the project.
_1C_COLUMN_MAP: dict[str, str] = {
    "номенклатура": "name",
    "наименование": "name",
    "артикул": "sku",
    "код": "sku",
    "цена": "price",
    "количество": "stock",
    "остаток": "stock",
    "единица": "unit",
    "производитель": "brand",
}


def parse_1c_export(file_path: str | Path) -> pd.DataFrame:
    """Read a 1C Excel export and return a cleaned DataFrame.

    The function scans the first 20 rows looking for a row that contains
    at least two known 1C column headers.  Everything above that row is
    treated as a header block and discarded.

    Args:
        file_path: Path to the ``.xlsx`` file exported from 1C.

    Returns:
        ``pd.DataFrame`` with normalised column names.

    Raises:
        FileNotFoundError: If *file_path* does not exist.
        ValueError: If no recognisable header row is found.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл 1С не найден: {path}")

    logger.info("Парсинг 1С-выгрузки: {}", path.name)

    # Read raw — no header, so every row is data.
    raw = pd.read_excel(path, header=None, engine="openpyxl")

    header_row = _find_header_row(raw)
    if header_row is None:
        raise ValueError(
            "Не удалось определить строку заголовков в файле 1С. "
            "Проверьте формат выгрузки."
        )

    # Re-read with detected header row.
    df = pd.read_excel(path, header=header_row, engine="openpyxl")

    # Rename columns we recognise.
    rename_map: dict[str, str] = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in _1C_COLUMN_MAP:
            rename_map[col] = _1C_COLUMN_MAP[key]

    df = df.rename(columns=rename_map)
    df = df.dropna(how="all").reset_index(drop=True)

    logger.info("1С-парсинг завершён: {} строк, колонки {}", len(df), list(df.columns))
    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_header_row(raw: pd.DataFrame, max_scan: int = 20) -> int | None:
    """Scan first *max_scan* rows for a row containing ≥2 known 1C headers."""
    known = set(_1C_COLUMN_MAP.keys())
    for idx in range(min(max_scan, len(raw))):
        cells = {str(v).strip().lower() for v in raw.iloc[idx] if pd.notna(v)}
        matches = cells & known
        if len(matches) >= 2:
            logger.debug("Строка заголовков 1С найдена: строка {}", idx)
            return idx
    return None
