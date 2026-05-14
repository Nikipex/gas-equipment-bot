"""Excel / CSV file reader with basic cleaning.

Loads spreadsheet files into a pandas DataFrame and provides
utilities for normalising column names and dropping empty rows.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from loguru import logger


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_excel(file_path: str | Path) -> pd.DataFrame:
    """Read an Excel (.xlsx) or CSV (.csv) file and return a raw DataFrame.

    The function auto-detects format by extension.  For multi-sheet Excel
    files it reads the **first** sheet only (most common for supplier
    price-lists).

    Args:
        file_path: Absolute or relative path to the file.

    Returns:
        Raw ``pd.DataFrame`` with data as-is from the file.

    Raises:
        FileNotFoundError: If *file_path* does not exist.
        ValueError: If the file extension is not supported.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    suffix = path.suffix.lower()
    logger.info("Чтение файла {} (формат {})", path.name, suffix)

    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path, engine="openpyxl")
    elif suffix == ".csv":
        df = pd.read_csv(path, encoding="utf-8")
    else:
        raise ValueError(f"Неподдерживаемый формат файла: {suffix}")

    logger.info("Прочитано {} строк, {} колонок", len(df), len(df.columns))
    return df


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise column names and remove empty / header-noise rows.

    Transformations applied:
    1. Column names → ``lowercase``, stripped, spaces replaced with ``_``.
    2. Rows that are entirely NaN are dropped.
    3. Leading / trailing whitespace in string cells is stripped.

    Args:
        df: Raw DataFrame from :func:`read_excel`.

    Returns:
        Cleaned ``pd.DataFrame`` (copy — the original is not mutated).
    """
    df = df.copy()

    # --- normalise column names ---
    df.columns = pd.Index([_normalise_col_name(c) for c in df.columns])

    # --- drop fully-empty rows ---
    before = len(df)
    df = df.dropna(how="all").reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        logger.debug("Удалено {} пустых строк", dropped)

    # --- strip whitespace in string columns ---
    str_cols = df.select_dtypes(include="object").columns
    for col in str_cols:
        df[col] = df[col].astype(str).str.strip()
        # replace "nan" strings left after astype
        df[col] = df[col].replace("nan", pd.NA)

    logger.info("DataFrame очищен: {} строк, колонки {}", len(df), list(df.columns))
    return df


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------


def _normalise_col_name(name: object) -> str:
    """Lower-case, strip and replace whitespace / special chars with ``_``."""
    s = str(name).strip().lower()
    s = re.sub(r"[\s\-/]+", "_", s)
    s = re.sub(r"[^\w]", "", s)  # drop remaining non-word chars
    return s
