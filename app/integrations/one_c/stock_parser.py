from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from loguru import logger

TARGET_WAREHOUSE_DEFAULT = "ЮЖНЫЙ склад"
TEXT_COLUMN_IDX = 1
STOCK_COLUMN_IDX = 2

SERVICE_PREFIXES = [
    "Период:",
    "Показатели:",
    "Группировки строк:",
    "Отборы:",
    "Склад",
    "Номенклатура",
    "<Объект не найден>",
    "<Объект>",
]


def normalize_text(value: object) -> str:
    """Normalize text for comparisons and product keys."""
    if pd.isna(value):
        return ""

    text = str(value).strip().lower()
    text = text.replace("\xa0", " ")
    text = text.replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_product_key(name: object) -> str:
    """Create a stable product key for later matching."""
    text = normalize_text(name)
    if not text:
        return ""

    # Clean punctuation noise but preserve useful separators in model names.
    text = re.sub(r"[\"'`]+", "", text)
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_service_row(value: object) -> bool:
    """Detect service/header rows that should be skipped."""
    if pd.isna(value):
        return False

    value_str = str(value).strip()
    if value_str == "":
        return True

    value_normalized = normalize_text(value_str)
    for prefix in SERVICE_PREFIXES:
        if value_normalized.startswith(normalize_text(prefix)):
            return True

    return False


def is_warehouse_row(value: object) -> bool:
    """Detect warehouse section rows."""
    if pd.isna(value):
        return False

    value_normalized = normalize_text(value)
    return "склад" in value_normalized and not is_service_row(value)


def matches_target_warehouse(value: object, target_warehouse: str) -> bool:
    """Check whether warehouse row matches the requested warehouse."""
    if pd.isna(value):
        return False

    return normalize_text(value) == normalize_text(target_warehouse)


def is_valid_product_row(value: object) -> bool:
    """Detect valid product rows inside the warehouse section."""
    if pd.isna(value):
        return False

    value_str = str(value).strip()
    if not value_str:
        return False
    if is_service_row(value):
        return False
    if is_warehouse_row(value):
        return False
    if len(value_str) < 2:
        return False

    return True


def safe_numeric_value(value: object) -> float:
    """Convert stock cell to float safely."""
    if pd.isna(value):
        return 0.0

    try:
        if isinstance(value, str):
            cleaned = (
                value.replace("\xa0", "")
                .replace(" ", "")
                .replace(",", ".")
                .strip()
            )
            return float(cleaned)
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _read_excel_any(file_path: Path) -> pd.DataFrame:
    """Read .xlsx or .xls inventory file with the correct engine."""
    suffix = file_path.suffix.lower()

    if suffix == ".xlsx":
        return pd.read_excel(file_path, engine="openpyxl", header=None)

    if suffix == ".xls":
        try:
            return pd.read_excel(file_path, engine="xlrd", header=None)
        except ImportError as exc:
            raise ImportError(
                "Для чтения .xls файлов нужен пакет xlrd. "
                "Установи его командой: pip install xlrd"
            ) from exc

    raise ValueError(f"Неподдерживаемый формат файла: {file_path.suffix}")


def parse_1c_stock_report(
    file_path: str | Path,
    target_warehouse: str = TARGET_WAREHOUSE_DEFAULT,
) -> pd.DataFrame:
    """
    Parse 1C stock availability report and return rows for one warehouse.

    Output columns:
    - warehouse
    - product_name
    - free_stock_qty
    - product_key
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    logger.info(
        "Парсинг 1С-остатков: file='{}', warehouse='{}'",
        path.name,
        target_warehouse,
    )

    try:
        df = _read_excel_any(path)
    except Exception as exc:
        logger.error("Не удалось прочитать файл '{}': {}", path.name, exc)
        raise

    if df.empty:
        logger.warning("Файл '{}' пустой", path.name)
        return pd.DataFrame(
            columns=["warehouse", "product_name", "free_stock_qty", "product_key"]
        )

    # Use first row as header, preserve positional parsing afterwards.
    df.columns = df.iloc[0].tolist()
    df = df[1:].reset_index(drop=True)

    if len(df.columns) <= max(TEXT_COLUMN_IDX, STOCK_COLUMN_IDX):
        logger.error(
            "В файле '{}' недостаточно колонок: {}",
            path.name,
            len(df.columns),
        )
        return pd.DataFrame(
            columns=["warehouse", "product_name", "free_stock_qty", "product_key"]
        )

    current_warehouse: str | None = None
    in_target_warehouse = False
    warehouse_matches = 0
    product_rows: list[dict[str, object]] = []

    for idx in range(len(df)):
        row = df.iloc[idx]

        try:
            hierarchy_value = row.iloc[TEXT_COLUMN_IDX]
        except (IndexError, KeyError):
            continue

        try:
            stock_value = row.iloc[STOCK_COLUMN_IDX]
        except (IndexError, KeyError):
            stock_value = None

        if is_warehouse_row(hierarchy_value):
            warehouse_name = str(hierarchy_value).strip()
            current_warehouse = warehouse_name
            in_target_warehouse = matches_target_warehouse(
                hierarchy_value,
                target_warehouse,
            )
            if in_target_warehouse:
                warehouse_matches += 1
            continue

        if is_service_row(hierarchy_value):
            continue

        if not is_valid_product_row(hierarchy_value):
            continue

        if not in_target_warehouse:
            continue

        product_name = str(hierarchy_value).strip()
        free_stock_qty = safe_numeric_value(stock_value)

        product_rows.append(
            {
                "warehouse": current_warehouse or target_warehouse,
                "product_name": product_name,
                "free_stock_qty": free_stock_qty,
            }
        )

    output_df = pd.DataFrame(product_rows)

    if output_df.empty:
        logger.warning(
            "В файле '{}' не найдено товарных строк по складу '{}'",
            path.name,
            target_warehouse,
        )
        return pd.DataFrame(
            columns=["warehouse", "product_name", "free_stock_qty", "product_key"]
        )

    output_df["product_key"] = output_df["product_name"].apply(normalize_product_key)
    output_df = output_df[output_df["product_key"] != ""].reset_index(drop=True)

    logger.info(
        "Парсинг завершён: file='{}', warehouse_matches={}, rows={}",
        path.name,
        warehouse_matches,
        len(output_df),
    )

    return output_df