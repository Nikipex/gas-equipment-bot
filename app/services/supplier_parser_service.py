

"""Supplier price Excel parser service.

MVP parser:
- reads xlsx/xls/csv files;
- detects product, price and stock columns by headers and sample values;
- returns normalized supplier product rows;
- builds a short preview for Telegram.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
import json

import pandas as pd


SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv"}

PRODUCT_HEADER_HINTS = (
    "номенклатура",
    "наименование",
    "название",
    "товар",
    "позиция",
    "name",
    "product",
)

PRICE_HEADER_HINTS = (
    "цена",
    "стоимость",
    "прайс",
    "опт",
    "price",
)

STOCK_HEADER_HINTS = (
    "остаток",
    "наличие",
    "количество",
    "кол-во",
    "склад",
    "stock",
    "qty",
    "quantity",
)


@dataclass(frozen=True)
class SupplierProduct:
    supplier_key: str
    supplier_name: str
    product_name: str
    price: float | None
    stock: float | None
    source_file: str
    row_number: int
    warehouse_stocks: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class SupplierParseResult:
    supplier_key: str
    supplier_name: str
    source_file: str
    product_column: str | None
    price_column: str | None
    stock_column: str | None
    total_rows: int
    parsed_rows: int
    products: list[SupplierProduct]


class SupplierParserService:
    """Parse supplier price files into normalized rows."""

    def parse_file(
        self,
        file_path: str | Path,
        supplier_name: str | None = None,
        limit: int | None = None,
    ) -> SupplierParseResult:
        path = Path(file_path)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension: {path.suffix}")

        supplier = supplier_name or _guess_supplier_name(path)
        supplier_key = _guess_supplier_key(path, supplier)
        df = _read_table(path)
        df = _cleanup_dataframe(df)

        product_column = _detect_product_column(df)
        price_column = _detect_price_column(df)
        stock_column = _detect_stock_column(df)

        products: list[SupplierProduct] = []
        if product_column is not None:
            iterable_df = df if limit is None else df.head(limit)
            for index, row in iterable_df.iterrows():
                product_name = _clean_text(row.get(product_column))
                if not _is_valid_product_name(product_name):
                    continue

                price = _parse_number(row.get(price_column)) if price_column else None
                stock, warehouse_stocks = _parse_stock_value(row, stock_column)

                products.append(
                    SupplierProduct(
                        supplier_key=supplier_key,
                        supplier_name=supplier,
                        product_name=product_name,
                        price=price,
                        stock=stock,
                        source_file=path.name,
                        row_number=int(index) + 1,
                        warehouse_stocks=warehouse_stocks,
                    )
                )

        return SupplierParseResult(
            supplier_key=supplier_key,
            supplier_name=supplier,
            source_file=path.name,
            product_column=product_column,
            price_column=price_column,
            stock_column=stock_column,
            total_rows=len(df),
            parsed_rows=len(products),
            products=products,
        )

    def build_preview_text(self, result: SupplierParseResult, limit: int = 10) -> str:
        lines = [
            "📊 <b>Прайс поставщика распознан</b>",
            "",
            f"🏷️ Поставщик: <b>{result.supplier_name}</b>",
            f"🔑 Ключ поставщика: <code>{result.supplier_key}</code>",
            f"📄 Файл: <code>{result.source_file}</code>",
            f"📦 Строк в файле: <b>{result.total_rows}</b>",
            f"✅ Распознано позиций: <b>{result.parsed_rows}</b>",
            "",
            "🔎 <b>Найденные колонки:</b>",
            f"• товар: <code>{result.product_column or 'не найдено'}</code>",
            f"• цена: <code>{result.price_column or 'не найдено'}</code>",
            f"• остаток: <code>{result.stock_column or 'не найдено'}</code>",
        ]

        if not result.products:
            lines.extend([
                "",
                "❌ Не удалось вытащить позиции из файла.",
                "Возможно, у прайса сложная шапка или товары находятся на другом листе.",
            ])
            return "\n".join(lines)

        lines.extend(["", "🧾 <b>Первые позиции:</b>", ""])

        for index, product in enumerate(result.products[:limit], start=1):
            price_text = _format_price(product.price)
            stock_text = _format_stock(product.stock)
            warehouse_text = _format_warehouse_stocks(product.warehouse_stocks)
            lines.append(
                f"{index}. <b>{_escape_preview(product.product_name)}</b>\n"
                f"💰 Цена: {price_text}\n"
                f"📦 Остаток: {stock_text}{warehouse_text}"
            )

        return "\n\n".join(lines)


def _parse_stock_value(row: pd.Series, stock_column: str | None) -> tuple[float | None, dict[str, float]]:
    warehouse_columns = _detect_warehouse_columns_from_row(row)

    warehouse_stocks: dict[str, float] = {}
    for column in warehouse_columns:
        value = _parse_number(row.get(column))
        if value is not None and value > 0:
            warehouse_stocks[str(column)] = value

    if warehouse_stocks:
        return float(sum(warehouse_stocks.values())), warehouse_stocks

    if stock_column:
        value = _parse_number(row.get(stock_column))
        if value is not None and value > 0:
            return value, {str(stock_column): value}
        return None, {}

    return None, {}



def _is_warehouse_column(column: object) -> bool:
    column_norm = _clean_text(column).lower()
    warehouse_hints = (
        "крд",
        "крым",
        "краснодар",
        "ростов",
        "мск",
        "москва",
    )
    return any(hint in column_norm for hint in warehouse_hints)


def _detect_warehouse_columns_from_row(row: pd.Series) -> list[str]:
    return [column for column in row.index if _is_warehouse_column(column)]


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return pd.read_csv(path)

    # header=None is intentional: supplier price lists often have multi-row
    # headers, merged cells, or title rows. We detect the best header row below.
    raw_df = pd.read_excel(path, header=None)
    return _promote_best_header_row(raw_df)


def _promote_best_header_row(raw_df: pd.DataFrame, max_scan_rows: int = 20) -> pd.DataFrame:
    best_index = 0
    best_score = -1

    scan_rows = min(max_scan_rows, len(raw_df))
    for row_index in range(scan_rows):
        values = [_clean_text(value).lower() for value in raw_df.iloc[row_index].tolist()]
        score = 0
        score += _row_hint_score(values, PRODUCT_HEADER_HINTS) * 3
        score += _row_hint_score(values, PRICE_HEADER_HINTS) * 2
        score += _row_hint_score(values, STOCK_HEADER_HINTS)

        if score > best_score:
            best_score = score
            best_index = row_index

    headers = []
    seen: dict[str, int] = {}
    for column_index, value in enumerate(raw_df.iloc[best_index].tolist()):
        header = _clean_text(value) or f"column_{column_index + 1}"
        normalized = header.lower()
        seen[normalized] = seen.get(normalized, 0) + 1
        if seen[normalized] > 1:
            header = f"{header}_{seen[normalized]}"
        headers.append(header)

    df = raw_df.iloc[best_index + 1 :].copy()
    df.columns = headers
    return df


def _cleanup_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").copy()
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    return df.reset_index(drop=True)


def _detect_product_column(df: pd.DataFrame) -> str | None:
    columns = list(df.columns)
    hinted = _find_column_by_header(columns, PRODUCT_HEADER_HINTS)
    if hinted:
        return hinted

    best_column = None
    best_score = -1
    for column in columns:
        series = df[column].dropna().head(50)
        score = 0
        for value in series:
            text = _clean_text(value)
            if _is_valid_product_name(text):
                score += 1
        if score > best_score:
            best_score = score
            best_column = column

    return best_column


def _detect_price_column(df: pd.DataFrame) -> str | None:
    columns = list(df.columns)
    hinted = _find_column_by_header(columns, PRICE_HEADER_HINTS)
    if hinted:
        return hinted

    return _detect_numeric_column(df, prefer_price=True)


def _detect_stock_column(df: pd.DataFrame) -> str | None:
    columns = list(df.columns)

    # Если в прайсе есть отдельные складские колонки типа КРД/Крым,
    # не выбираем одну из них как "остаток"; дальше _parse_stock_value()
    # соберёт breakdown по всем складам.
    warehouse_columns = [
        column for column in columns
        if _is_warehouse_column(column)
    ]
    if warehouse_columns:
        return None

    hinted = _find_column_by_header(columns, STOCK_HEADER_HINTS)
    if hinted:
        return hinted

    return None


def _detect_numeric_column(df: pd.DataFrame, prefer_price: bool) -> str | None:
    best_column = None
    best_score = -1

    for column in df.columns:
        values = [_parse_number(value) for value in df[column].dropna().head(100)]
        numeric_values = [value for value in values if value is not None]
        if not numeric_values:
            continue

        if prefer_price:
            score = sum(1 for value in numeric_values if 50 <= value <= 10_000_000)
        else:
            score = sum(1 for value in numeric_values if 0 <= value <= 100_000)

        if score > best_score:
            best_score = score
            best_column = column

    return best_column


def _find_column_by_header(columns: list[str], hints: tuple[str, ...]) -> str | None:
    for column in columns:
        normalized = _clean_text(column).lower()
        if any(hint in normalized for hint in hints):
            return column
    return None


def _row_hint_score(values: list[str], hints: tuple[str, ...]) -> int:
    return sum(1 for value in values for hint in hints if hint in value)


def _parse_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None

    if isinstance(value, int | float):
        return float(value)

    text = _clean_text(value)
    if not text:
        return None

    text = text.replace("\u00a0", " ")
    text = re.sub(r"[^0-9,.-]+", "", text)
    text = text.replace(" ", "")

    if text.count(",") == 1 and text.count(".") == 0:
        text = text.replace(",", ".")
    elif text.count(",") > 0 and text.count(".") > 0:
        text = text.replace(",", "")

    try:
        return float(text)
    except ValueError:
        return None


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _is_valid_product_name(value: str) -> bool:
    if len(value) < 5:
        return False
    if value.lower() in {"итого", "всего", "nan", "none"}:
        return False
    return bool(re.search(r"[a-zA-Zа-яА-Я]", value))


def _guess_supplier_name(path: Path) -> str:
    name = path.stem.lower()
    name = re.sub(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_", "", name)
    name = re.sub(r"_?прайс.*$", "", name)
    name = re.sub(r"_?price.*$", "", name)
    name = re.sub(r"_+", " ", name).strip()
    return name or "unknown supplier"


def _format_price(value: float | None) -> str:
    if value is None or value <= 0:
        return "не найдена"
    return f"{value:,.0f} ₽".replace(",", " ")


def _format_stock(value: float | None) -> str:
    if value is None:
        return "не найден"
    return f"{value:g}"


def _escape_preview(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

def _format_warehouse_stocks(value: dict[str, float]) -> str:
    if not value:
        return ""

    parts = []
    for warehouse, stock in value.items():
        if float(stock).is_integer():
            stock_text = str(int(stock))
        else:
            stock_text = f"{stock:g}"
        parts.append(f"{warehouse}: {stock_text}")

    return "\n   " + "; ".join(parts)


def _guess_supplier_key(path: Path, supplier_name: str) -> str:
    raw = f"{path.name} {supplier_name}".lower().replace("ё", "е")

    rules = {
        "yulas": ("юлас", "yulas"),
        "ib": (" иб ", "_иб_", "иб.", "иб-", "ib", "бакси", "иммергаз", "аристон", "дражице", "навьен", "термекс", "бош", "эван", "дакор"),
    }

    padded = f" {raw} "
    for key, markers in rules.items():
        if any(marker in padded for marker in markers):
            return key

    key = re.sub(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_", "", supplier_name.lower())
    key = re.sub(r"[^a-zа-я0-9]+", "_", key)
    key = re.sub(r"_+", "_", key).strip("_")
    return key or "unknown_supplier"
