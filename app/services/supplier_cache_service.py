"""Supplier products CSV cache service."""

from __future__ import annotations

import re
from pathlib import Path
import json

import pandas as pd

from app.services.supplier_parser_service import SupplierParseResult, SupplierProduct

CACHE_PATH = Path("data/supplier_prices/processed/supplier_products.csv")


class SupplierCacheService:
    def __init__(self, cache_path: Path = CACHE_PATH) -> None:
        self.cache_path = cache_path
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

    def save_parse_result(self, result: SupplierParseResult) -> int:
        products = [_product_to_row(product) for product in result.products if _is_good_product(product)]

        if not products:
            return 0

        new_df = pd.DataFrame(products)
        old_df = self._read_cache()

        supplier_key = str(new_df["supplier_key"].iloc[0])

        if not old_df.empty and "supplier_key" in old_df.columns:
            old_df = old_df[old_df["supplier_key"].astype(str) != supplier_key].copy()

        combined = pd.concat([old_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(
            subset=["supplier_key", "product_name"],
            keep="last",
        )

        combined.to_csv(self.cache_path, index=False)
        return len(new_df)

    def search(self, query: str, limit: int = 10) -> pd.DataFrame:
        df = self._read_cache()
        if df.empty:
            return df

        clean_query, discount_percent, markup_amount, round_step = _parse_price_formula(query)
        tokens = _query_tokens(clean_query)
        if not tokens:
            return df.head(0)

        is_boiler_query = _is_boiler_query(clean_query, tokens)
        requested_brand = _requested_brand(tokens)
        requested_series = _requested_series(tokens)
        requested_model_numbers = [token for token in tokens if token.isdigit()]

        result = df.copy()
        result["name_norm"] = result["product_name"].astype(str).map(_normalize_for_search)

        if is_boiler_query:
            result = result[~result["name_norm"].map(_is_boiler_accessory_name)].copy()

        if requested_brand:
            result = result[result["name_norm"].map(lambda value: _brand_allowed(value, requested_brand))].copy()

        if requested_series:
            result = result[result["name_norm"].str.contains(requested_series, regex=False, na=False)].copy()

        for model_number in requested_model_numbers:
            result = result[result["name_norm"].str.contains(model_number, regex=False, na=False)].copy()

        for idx, token in enumerate(tokens):
            result[f"match_{idx}"] = result["name_norm"].str.contains(token, regex=False, na=False).astype(int)

        match_columns = [f"match_{idx}" for idx in range(len(tokens))]
        result["match_score"] = result[match_columns].sum(axis=1)

        min_score = 1 if len(tokens) == 1 else 2
        result = result[result["match_score"] >= min_score].copy()

        if result.empty and len(tokens) > 1 and not _has_numeric_token(tokens):
            result = df.copy()
            result["name_norm"] = result["product_name"].astype(str).map(_normalize_for_search)
            if is_boiler_query:
                result = result[~result["name_norm"].map(_is_boiler_accessory_name)].copy()

            if requested_brand:
                result = result[result["name_norm"].map(lambda value: _brand_allowed(value, requested_brand))].copy()

            if requested_series:
                result = result[result["name_norm"].str.contains(requested_series, regex=False, na=False)].copy()

            for model_number in requested_model_numbers:
                result = result[result["name_norm"].str.contains(model_number, regex=False, na=False)].copy()

            for idx, token in enumerate(tokens):
                result[f"match_{idx}"] = result["name_norm"].str.contains(token, regex=False, na=False).astype(int)
            result["match_score"] = result[[f"match_{idx}" for idx in range(len(tokens))]].sum(axis=1)
            result = result[result["match_score"] >= 1].copy()

        if result.empty:
            return result

        result["stock_sort"] = pd.to_numeric(result.get("stock"), errors="coerce").fillna(0)
        result["price_sort"] = pd.to_numeric(result.get("price"), errors="coerce").fillna(10**12)

        if discount_percent is not None or markup_amount is not None or round_step is not None:
            base_price = pd.to_numeric(result.get("price"), errors="coerce")
            calculated_price = base_price.copy()

            if discount_percent is not None:
                calculated_price = calculated_price * (1 - discount_percent / 100)

            if markup_amount is not None:
                calculated_price = calculated_price + markup_amount

            if round_step is not None and round_step > 0:
                calculated_price = (calculated_price / round_step).round() * round_step

            result["calculated_price"] = calculated_price.round(0)

        result = result.sort_values(
            ["match_score", "stock_sort", "price_sort"],
            ascending=[False, False, True],
        )

        drop_columns = [
            column
            for column in result.columns
            if column.startswith("match_") or column in {"name_norm", "stock_sort", "price_sort"}
        ]

        return result.drop(columns=drop_columns).head(limit)

    def _read_cache(self) -> pd.DataFrame:
        if not self.cache_path.exists():
            return pd.DataFrame(
                columns=[
                    "supplier_key",
                    "supplier_name",
                    "product_name",
                    "price",
                    "stock",
                    "warehouse_stocks",
                    "source_file",
                    "row_number",
                ]
            )

        return pd.read_csv(self.cache_path)


def _product_to_row(product: SupplierProduct) -> dict[str, object]:
    return {
        "supplier_key": product.supplier_key,
        "supplier_name": product.supplier_name,
        "product_name": product.product_name,
        "price": product.price,
        "stock": product.stock,
        "warehouse_stocks": json.dumps(product.warehouse_stocks, ensure_ascii=False),
        "source_file": product.source_file,
        "row_number": product.row_number,
    }


def _is_good_product(product: SupplierProduct) -> bool:
    name = product.product_name.strip().lower()

    if len(name) < 5:
        return False

    garbage_exact = {
        "итого",
        "всего",
        "номенклатура",
        "наименование",
        "товар",
        "прайс",
    }

    if name in garbage_exact:
        return False

    # Для supplier cache цена обязательна.
    # Строки категорий/разделов обычно идут без цены и засоряют поиск.
    if product.price is None or product.price <= 0:
        return False

    return True


def _parse_price_formula(
    query: str,
) -> tuple[str, float | None, float | None, int | None]:
    text = query.strip()

    discount_percent = None
    markup_amount = None
    round_step = None

    discount_match = re.search(r"-(\d+(?:[.,]\d+)?)\s*%", text)
    if discount_match:
        discount_percent = float(discount_match.group(1).replace(",", "."))
        text = text.replace(discount_match.group(0), " ")

    markup_match = re.search(r"\+(\d+(?:[.,]\d+)?)\s*(?:р|руб|₽)?", text)
    if markup_match:
        markup_amount = float(markup_match.group(1).replace(",", "."))
        text = text.replace(markup_match.group(0), " ")

    round_match = re.search(r"до\s*(100|10)", text.lower())
    if round_match:
        round_step = int(round_match.group(1))
        text = re.sub(r"до\s*(100|10)", " ", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text).strip()

    return text, discount_percent, markup_amount, round_step


def _normalize_text(value: object) -> str:
    text = str(value).lower().replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _query_tokens(query: str) -> list[str]:
    text = _normalize_text(query)

    aliases = {
        # latin/cyrillic brands
        "baxi": "baxi",
        "бакси": "baxi",
        "bosch": "bosch",
        "бош": "bosch",
        "ariston": "ariston",
        "аристон": "ariston",
        "navien": "navien",
        "навьен": "navien",
        "fondital": "fondital",
        "фондитал": "fondital",

        # model transliteration
        "eco": "eco",
        "эко": "eco",
        "nova": "nova",
        "нова": "nova",
        "four": "four",
        "фор": "four",
        "nts": "nts",
        "нтс": "nts",
        "nтs": "nts",
        "ntс": "nts",
        "nтc": "nts",
        "tgv": "tgv",
        "тгв": "tgv",

        # product words
        "котел": "котел",
        "котёл": "котел",
        "boiler": "котел",
        "автомат": "автоматика",
        "авт": "автоматика",
    }

    tokens = []
    for token in text.split():
        token = aliases.get(token, token)
        if len(token) < 2:
            continue

        tokens.append(token)

        # 24f / 24fi / 30v -> also search by numeric model core.
        numeric_core = re.match(r"^(\d{2,3})[a-zа-я]+$", token)
        if numeric_core:
            tokens.append(numeric_core.group(1))

    # remove duplicates, preserve order
    seen = set()
    unique_tokens = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        unique_tokens.append(token)

    return unique_tokens


def _has_numeric_token(tokens: list[str]) -> bool:
    return any(token.isdigit() for token in tokens)


def _normalize_for_search(value: object) -> str:
    tokens = _query_tokens(str(value))
    return " ".join(tokens)


def _is_boiler_query(clean_query: str, tokens: list[str]) -> bool:
    text = _normalize_text(clean_query)
    boiler_markers = {
        "котел",
        "baxi",
        "bosch",
        "ariston",
        "navien",
        "fondital",
        "mizudo",
        "daesung",
        "бакси",
        "бош",
        "аристон",
        "навьен",
        "фондитал",
    }
    return any(marker in tokens or marker in text for marker in boiler_markers)


def _is_boiler_accessory_name(name_norm: str) -> bool:
    accessory_markers = (
        "коакс",
        "дымоход",
        "комплект",
        "отвод",
        "колено",
        "переход",
        "адаптер",
        "труба",
        "хомут",
        "втулка",
        "муфта",
        "анти лед",
        "антилед",
        "датчик",
        "плата",
        "насос",
        "кран",
        "фильтр",
    )
    return any(marker in name_norm for marker in accessory_markers)


def _requested_brand(tokens: list[str]) -> str | None:
    brands = {"baxi", "bosch", "ariston", "navien", "fondital", "mizudo", "daesung"}
    for token in tokens:
        if token in brands:
            return token
    return None


def _requested_series(tokens: list[str]) -> str | None:
    # Если менеджер указал серию, не подмешиваем соседние серии только по мощности.
    strict_series = {"nts", "eco", "4s", "nova", "clas", "one", "gaz", "6000"}
    for token in tokens:
        if token in strict_series:
            return token
    return None


def _brand_allowed(name_norm: str, requested_brand: str) -> bool:
    known_brands = {"baxi", "bosch", "ariston", "navien", "fondital", "mizudo", "daesung", "юнипамп", "unipump"}

    if requested_brand in name_norm:
        return True

    # BAXI в прайсах иногда записан только как "Эко 4S..." без бренда.
    # Но не пропускаем явные чужие бренды типа Юнипамп/Unipump.
    if requested_brand == "baxi" and any(token in name_norm for token in ("eco", "4s", "nova")):
        if any(foreign in name_norm for foreign in ("юнипамп", "unipump", "акваробот", "universal", "станция")):
            return False
        return True

    # Bosch часто пишут кириллицей, но aliases уже должны превратить в bosch.
    # Если в названии нет явного чужого бренда, оставляем как fallback.
    foreign_brands = known_brands - {requested_brand}

    return not any(brand in name_norm for brand in foreign_brands)
