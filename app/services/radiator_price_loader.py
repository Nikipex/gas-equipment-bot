

"""Excel loader for radiator client price lists.

Reads local radiator price files from data/radiator_prices and normalizes them
into a simple searchable structure:

    profile, radiator_type, height, length, connection, price

The loader is intentionally tolerant: it scans every row/cell and tries to
extract radiator dimensions from row text, then takes the price from the same
row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_PRICE_DIR = Path("data/radiator_prices")


@dataclass(frozen=True)
class RadiatorPriceRow:
    """Normalized radiator price row from Excel/CSV price list."""

    profile: str
    radiator_type: str
    height: str
    length: str
    connection: str
    price: float
    source_file: str

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        return (
            self.profile,
            self.radiator_type,
            self.height,
            self.length,
            self.connection,
        )


class RadiatorPriceLoader:
    """Loads and normalizes radiator Excel price lists."""

    def __init__(self, price_dir: Path = DEFAULT_PRICE_DIR) -> None:
        self.price_dir = price_dir

    def load(self) -> list[RadiatorPriceRow]:
        """Load all supported price files from the configured directory."""
        if not self.price_dir.exists():
            return []

        rows: list[RadiatorPriceRow] = []
        for file in self._iter_price_files():
            rows.extend(self._load_file(file))

        return rows

    def load_index(self) -> dict[tuple[str, str, str, str, str], RadiatorPriceRow]:
        """Load prices as a lookup index."""
        result: dict[tuple[str, str, str, str, str], RadiatorPriceRow] = {}
        for row in self.load():
            result[row.key] = row
        return result

    def _iter_price_files(self) -> Iterable[Path]:
        patterns = ("*.xlsx", "*.xls", "*.csv")
        for pattern in patterns:
            yield from sorted(self.price_dir.glob(pattern))

    def _load_file(self, file: Path) -> list[RadiatorPriceRow]:
        profile = _extract_profile_from_filename(file)
        if profile is None:
            return []

        try:
            if file.suffix.lower() == ".csv":
                sheets = {"csv": pd.read_csv(file, header=None)}
            else:
                sheets = pd.read_excel(file, sheet_name=None, header=None)
        except Exception:
            return []

        result: list[RadiatorPriceRow] = []
        for df in sheets.values():
            result.extend(_extract_rows_from_dataframe(df, profile, file.name))

        return result


@lru_cache(maxsize=1)
def load_radiator_price_index(
    price_dir: str | Path = DEFAULT_PRICE_DIR,
) -> dict[tuple[str, str, str, str, str], RadiatorPriceRow]:
    """Cached helper for fast runtime lookup."""
    return RadiatorPriceLoader(Path(price_dir)).load_index()


def clear_radiator_price_cache() -> None:
    """Clear cached Excel price index after files are changed."""
    load_radiator_price_index.cache_clear()


def find_radiator_price(
    radiator_type: str | int,
    height: str | int,
    length: str | int,
    profile: str | int,
    connection: str = "бок",
    price_dir: str | Path = DEFAULT_PRICE_DIR,
) -> RadiatorPriceRow | None:
    """Find exact radiator price by normalized dimensions and profile."""
    key = (
        str(profile),
        str(radiator_type),
        str(height),
        str(length),
        normalize_connection(connection),
    )
    return load_radiator_price_index(price_dir).get(key)


def _extract_rows_from_dataframe(
    df: pd.DataFrame,
    profile: str,
    source_file: str,
) -> list[RadiatorPriceRow]:
    if df.empty:
        return []

    result: list[RadiatorPriceRow] = []
    current_connection = "бок"

    for _, row in df.iterrows():
        row_values = row.tolist()

        row_text = " ".join(str(v) for v in row_values if pd.notna(v))
        header_connection = _detect_connection_from_text(row_text)
        if header_connection:
            current_connection = header_connection

        for cell_idx, cell_value in enumerate(row_values):
            if pd.isna(cell_value):
                continue

            cell_text = str(cell_value)
            if "радиатор" not in cell_text.lower():
                continue

            size = extract_radiator_size(cell_text)
            if size is None:
                continue

            # Цена должна быть справа от найденной позиции.
            # Не берём числа из самого названия: 22 / 500 / 1000.
            price = _extract_price_to_the_right(row_values[cell_idx + 1:])
            if price is None:
                continue

            radiator_type, height, length = size
            connection = normalize_connection(cell_text)
            if connection == "бок":
                connection = current_connection

            result.append(
                RadiatorPriceRow(
                    profile=profile,
                    radiator_type=radiator_type,
                    height=height,
                    length=length,
                    connection=connection,
                    price=price,
                    source_file=source_file,
                )
            )

    return result


def _extract_price_to_the_right(values: list[object]) -> float | None:
    for value in values:
        if pd.isna(value):
            continue

        text = str(value).strip().lower()

        # дошли до следующей позиции/шапки — дальше не идём
        if "радиатор" in text:
            break
        if "боковое" in text or "нижнее" in text:
            break

        price = _to_float(value)
        if price is None:
            continue

        # отсекаем размеры/тип/толщину
        if price in {10, 11, 20, 21, 22, 30, 33, 200, 300, 500, 600, 900, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 2800, 3000}:
            continue

        # цена радиатора в прайсе нормальная, не 1.2 и не 1000 из размера
        if price >= 1500:
            return price

    return None


def extract_radiator_size(text: str) -> tuple[str, str, str] | None:
    """Extract radiator size as (type, height, length)."""
    value = text.lower().replace("х", "x").replace("×", "x")

    # Examples:
    # 500x22x1000
    # 500*22*1000
    direct = re.search(r"(?<!\d)(\d{3})\s*[x*/\\]+\s*(\d{2})\s*[x*/\\]+\s*(\d{3,4})(?!\d)", value)
    if direct:
        height = direct.group(1)
        radiator_type = direct.group(2)
        length = str(int(direct.group(3)))
        return radiator_type, height, length

    # Examples from 1C names:
    # 500//22*1000
    one_c = re.search(r"(?<!\d)(\d{3})//(\d{2})\*(\d{3,4})(?!\d)", value)
    if one_c:
        height = one_c.group(1)
        radiator_type = one_c.group(2)
        length = str(int(one_c.group(3)))
        return radiator_type, height, length

    # Query style:
    # радиатор 22 500 1000
    nums = [int(item) for item in re.findall(r"\d+", value)]
    radiator_types = {10, 11, 20, 21, 22, 30, 33}
    radiator_heights = {200, 300, 500, 600, 900}

    radiator_type = next((num for num in nums if num in radiator_types), None)
    height = next((num for num in nums if num in radiator_heights), None)
    length = max((num for num in nums if 400 <= num <= 3000), default=None)

    if radiator_type is None or height is None or length is None:
        return None

    return str(radiator_type), str(height), str(length)


def normalize_connection(value: str | None) -> str:
    if not value:
        return "бок"

    text = value.lower()
    if "ниж" in text or "низ" in text or "vk" in text:
        return "низ"
    return "бок"


def _detect_connection_from_text(text: str) -> str | None:
    value = text.lower()
    if "нижнее" in value or "нижн" in value:
        return "низ"
    if "боковое" in value or "бок" in value:
        return "бок"
    return None


def _extract_profile_from_filename(file: Path) -> str | None:
    match = re.search(r"(\d{3,6})", file.stem)
    return match.group(1) if match else None


def _extract_price_from_values(values: list[object]) -> float | None:
    """Extract row price.

    In current price files the price is usually the last meaningful money-like
    value in the row. We ignore small values that are likely type/height/length.
    """
    candidates: list[float] = []

    for value in values:
        parsed = _to_float(value)
        if parsed is None:
            continue
        if parsed >= 1000:
            candidates.append(parsed)

    if not candidates:
        return None

    return candidates[-1]


def _to_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None

    cleaned = str(value)
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = cleaned.replace("₽", "")
    cleaned = cleaned.replace("руб", "")
    cleaned = cleaned.replace(" ", "")
    cleaned = cleaned.replace(",", ".")

    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not match:
        return None

    return float(match.group(0))