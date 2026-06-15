"""Supplier products CSV cache service."""

from __future__ import annotations

import json
import re
from pathlib import Path

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
        result = self._search_internal(query, limit=limit)
        return result.head(limit)

    def compare(self, query: str, limit: int = 20) -> pd.DataFrame:
        result = self._search_internal(query, limit=limit)
        if result.empty:
            return result

        result = result.copy()
        price_source = "calculated_price" if "calculated_price" in result.columns else "price"
        result["offer_price"] = pd.to_numeric(result[price_source], errors="coerce")
        result["stock_numeric"] = pd.to_numeric(result.get("stock"), errors="coerce").fillna(0)
        result["product_key"] = result["product_name"].astype(str).map(_product_group_key)

        result = result[result["offer_price"].notna() & (result["offer_price"] > 0)].copy()
        if result.empty:
            return result

        result["is_best_price"] = False
        for _, group in result.groupby("product_key"):
            best_index = group.sort_values(["offer_price", "stock_numeric"], ascending=[True, False]).index[0]
            result.loc[best_index, "is_best_price"] = True

        return result.sort_values(
            ["product_key", "offer_price", "stock_numeric"],
            ascending=[True, True, False],
        ).head(limit)

    def _search_internal(self, query: str, limit: int = 30) -> pd.DataFrame:
        df = self._read_cache()
        if df.empty:
            return df

        clean_query, supplier_filter, discount_percent, markup_amount, round_step = _parse_supplier_query(query)
        tokens = _query_tokens(clean_query)
        if not tokens:
            return df.head(0)

        result = df.copy()

        if supplier_filter:
            result = result[result["supplier_key"].astype(str).str.lower() == supplier_filter].copy()
            if result.empty:
                return result

        result = _ensure_name_norm(result)

        is_boiler_query = _is_boiler_query(clean_query, tokens)
        requested_brand = _requested_brand(tokens)
        requested_series = _requested_series(tokens)
        requested_model_numbers = [token for token in tokens if token.isdigit()]

        result = _apply_supplier_strict_intent_filter(result, clean_query, tokens)
        if result.empty:
            return result

        if is_boiler_query:
            result = result[~result["name_norm"].map(_is_boiler_accessory_name)].copy()

        if requested_brand:
            result = _ensure_name_norm(result)
            result = result[result["name_norm"].map(lambda value: _brand_allowed(value, requested_brand))].copy()

        result = _ensure_name_norm(result)

        if requested_series:
            result = result[result["name_norm"].str.contains(requested_series, regex=False, na=False)].copy()

        for model_number in requested_model_numbers:
            filtered = result[result["name_norm"].map(lambda name: _name_has_exact_model_number(name, model_number))].copy()
            if not filtered.empty:
                result = filtered

        if result.empty:
            return result

        for idx, token in enumerate(tokens):
            result[f"match_{idx}"] = result["name_norm"].str.contains(token, regex=False, na=False).astype(int)

        match_columns = [f"match_{idx}" for idx in range(len(tokens))]
        result["match_score"] = result[match_columns].sum(axis=1)

        min_score = 1 if len(tokens) == 1 else 2
        result = result[result["match_score"] >= min_score].copy()

        if result.empty and len(tokens) > 1 and not _has_numeric_token(tokens):
            result = df.copy()

            if supplier_filter:
                result = result[result["supplier_key"].astype(str).str.lower() == supplier_filter].copy()

            result = _ensure_name_norm(result)

            if is_boiler_query:
                result = result[~result["name_norm"].map(_is_boiler_accessory_name)].copy()

            if requested_brand:
                result = result[result["name_norm"].map(lambda value: _brand_allowed(value, requested_brand))].copy()

            if requested_series:
                result = result[result["name_norm"].str.contains(requested_series, regex=False, na=False)].copy()

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

        price_column = "calculated_price" if "calculated_price" in result.columns else "price_sort"
        result["offer_price_sort"] = pd.to_numeric(result.get(price_column), errors="coerce").fillna(result["price_sort"])

        result = result.sort_values(
            ["match_score", "offer_price_sort", "stock_sort"],
            ascending=[False, True, False],
        )

        drop_columns = [
            column
            for column in result.columns
            if column.startswith("match_") or column in {"name_norm", "stock_sort", "price_sort", "offer_price_sort"}
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

        df = pd.read_csv(self.cache_path)

        if "supplier_key" not in df.columns:
            df["supplier_key"] = df["supplier_name"].astype(str).map(_legacy_supplier_key)

        if "warehouse_stocks" not in df.columns:
            df["warehouse_stocks"] = "{}"

        return df



def _normalize_supplier_query_for_intent(query: str) -> str:
    text = str(query or "").lower().replace("ё", "е")

    replacements = {
        "бакси": "baxi",
        "навьен": "navien",
        "навиен": "navien",
        "фондиталь": "fondital",
        "фондитал": "fondital",
        "федерика бугатти": "federica bugatti",
        "федерика бугати": "federica bugatti",
        "федерика": "federica bugatti",
        "бугатти": "federica bugatti",
        "бугати": "federica bugatti",
    }

    for src, dst in sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", dst, text)

    return text


def _name_has_exact_model_number(name: str, number: str) -> bool:
    value = str(name or "").lower().replace("ё", "е")

    patterns = [
        rf"(?<![\d.]){re.escape(number)}(?!\d)",       # 16 / 24, but not 160 or 1.24
        rf"(?<![\d.]){re.escape(number)}\s*f(?!\w)",   # 24 F
        rf"(?<![\d.]){re.escape(number)}f(?!\w)",      # 24F
        rf"(?<![\d.]){re.escape(number)}\s*k(?!\w)",   # 24 K
        rf"(?<![\d.]){re.escape(number)}k(?!\w)",      # 24K
        rf"ксг[-\s]*{re.escape(number)}(?!\d)",
        rf"ксгз[-\s]*{re.escape(number)}(?!\d)",
        rf"кс[-\s]*г[-\s]*{re.escape(number)}(?!\d)",
        rf"кс[-\s]*гз[-\s]*{re.escape(number)}(?!\d)",
    ]

    return any(re.search(pattern, value) for pattern in patterns)


def _apply_supplier_strict_intent_filter(
    result: pd.DataFrame,
    clean_query: str,
    tokens: list[str],
) -> pd.DataFrame:
    if result.empty or "name_norm" not in result.columns:
        return result

    q = _normalize_supplier_query_for_intent(clean_query)

    filters: list[tuple[str, callable]] = []

    if "артек" in q:
        filters.append(("brand_artek", lambda name: "артек" in name))

    if "baxi" in q:
        filters.append(("brand_baxi", lambda name: "baxi" in name or "бакси" in name))
        if "eco" in q and "4s" in q:
            filters.append(("line_eco4s", lambda name: "eco" in name and ("4s" in name or "4 s" in name or "eco-4s" in name)))
        elif "eco" in q and "nova" in q:
            filters.append(("line_econova", lambda name: "eco" in name and "nova" in name))

    if "navien" in q:
        filters.append(("brand_navien", lambda name: "navien" in name or "навьен" in name or "навиен" in name))
        if "deluxe" in q:
            filters.append(("line_deluxe", lambda name: "deluxe" in name))
        if re.search(r"\bc\b", q):
            filters.append(("line_c", lambda name: bool(re.search(r"(?<!\w)c(?!\w)|(?<!\w)с(?!\w)", name))))

    if "federica" in q or "bugatti" in q:
        filters.append(("brand_federica_bugatti", lambda name: "federica" in name and ("bugatti" in name or "bugati" in name)))

    if "fondital" in q:
        filters.append(("brand_fondital", lambda name: "fondital" in name))

    strict = result.copy()

    for _, predicate in filters:
        filtered = strict[strict["name_norm"].map(predicate)].copy()
        if not filtered.empty:
            strict = filtered

    common_model_numbers = {
        "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "18",
        "20", "21", "22", "24", "28", "30", "32", "35", "40",
    }
    requested_model_numbers = [token for token in tokens if token in common_model_numbers]

    for model_number in requested_model_numbers:
        filtered = strict[strict["name_norm"].map(lambda name: _name_has_exact_model_number(name, model_number))].copy()
        if not filtered.empty:
            strict = filtered

    return strict


def _ensure_name_norm(df: pd.DataFrame) -> pd.DataFrame:
    """Guarantee searchable normalized name column exists."""
    if df.empty:
        if "name_norm" not in df.columns:
            df = df.copy()
            df["name_norm"] = pd.Series(dtype="object")
        return df

    df = df.copy()
    if "product_name" not in df.columns:
        df["product_name"] = ""
    df["name_norm"] = df["product_name"].astype(str).map(_normalize_for_search)
    return df


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

    if name in {"итого", "всего", "номенклатура", "наименование", "товар", "прайс"}:
        return False

    if product.price is None or product.price <= 0:
        return False

    return True


def _parse_supplier_query(query: str) -> tuple[str, str | None, float | None, float | None, int | None]:
    text = query.strip()
    supplier_filter = None
    discount_percent = None
    markup_amount = None
    round_step = None

    supplier_match = re.search(
        r"(?:^|\s)(?:поставщик|supplier)\s*[:=]?\s*(ib|иб|yulas|юлас)(?:\s|$)",
        text,
        flags=re.IGNORECASE,
    )
    if supplier_match:
        supplier_filter = _normalize_supplier_key(supplier_match.group(1))
        text = text.replace(supplier_match.group(0), " ")

    first_token_match = re.match(r"^\s*(ib|иб|yulas|юлас)\s+", text, flags=re.IGNORECASE)
    if first_token_match:
        supplier_filter = _normalize_supplier_key(first_token_match.group(1))
        text = text[first_token_match.end():]

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
    return text, supplier_filter, discount_percent, markup_amount, round_step


def _normalize_supplier_key(value: str) -> str:
    value = value.lower().replace("ё", "е").strip()
    if value in {"иб", "ib"}:
        return "ib"
    if value in {"юлас", "yulas"}:
        return "yulas"
    return value


def _legacy_supplier_key(value: object) -> str:
    text = str(value).lower()
    if "юлас" in text or "yulas" in text:
        return "yulas"
    if "иб" in text or any(marker in text for marker in ("бакси", "иммергаз", "аристон", "дражице", "навьен", "термекс", "бош", "эван", "дакор")):
        return "ib"
    return "unknown_supplier"


def _normalize_text(value: object) -> str:
    text = str(value).lower().replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_for_search(value: object) -> str:
    return " ".join(_query_tokens(str(value)))


def _query_tokens(query: str) -> list[str]:
    text = _normalize_text(query)

    aliases = {
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
        "vaillant": "vaillant",
        "вайлант": "vaillant",
        "eco": "eco",
        "эко": "eco",
        "nova": "nova",
        "нова": "nova",
        "nts": "nts",
        "нтс": "nts",
        "nтs": "nts",
        "ntс": "nts",
        "nтc": "nts",
        "tgv": "tgv",
        "тгв": "tgv",
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

        numeric_core = re.match(r"^(\d{2,3})[a-zа-я]+$", token)
        if numeric_core:
            tokens.append(numeric_core.group(1))

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


def _is_boiler_query(clean_query: str, tokens: list[str]) -> bool:
    text = _normalize_text(clean_query)
    boiler_markers = {
        "котел", "baxi", "bosch", "ariston", "navien", "fondital",
        "mizudo", "daesung", "vaillant", "бакси", "бош", "аристон",
        "навьен", "фондитал", "вайлант",
    }
    return any(marker in tokens or marker in text for marker in boiler_markers)


def _is_boiler_accessory_name(name_norm: str) -> bool:
    accessory_markers = (
        "коакс", "дымоход", "комплект", "отвод", "колено", "переход",
        "адаптер", "труба", "хомут", "втулка", "муфта", "анти лед",
        "антилед", "датчик", "плата", "насос", "кран", "фильтр",
    )
    return any(marker in name_norm for marker in accessory_markers)


def _requested_brand(tokens: list[str]) -> str | None:
    brands = {"baxi", "bosch", "ariston", "navien", "fondital", "mizudo", "daesung", "vaillant"}
    for token in tokens:
        if token in brands:
            return token
    return None


def _requested_series(tokens: list[str]) -> str | None:
    strict_series = {"nts", "4s", "nova", "clas", "one", "gaz", "6000"}
    for token in tokens:
        if token in strict_series:
            return token
    return None


def _brand_allowed(name_norm: str, requested_brand: str) -> bool:
    known_brands = {
        "baxi", "bosch", "ariston", "navien", "fondital", "mizudo",
        "daesung", "vaillant", "юнипамп", "unipump",
    }

    if requested_brand in name_norm:
        return True

    if requested_brand == "baxi" and any(token in name_norm for token in ("eco", "4s", "nova")):
        if any(foreign in name_norm for foreign in ("юнипамп", "unipump", "акваробот", "universal", "станция", "vaillant", "вайлант")):
            return False
        return True

    foreign_brands = known_brands - {requested_brand}
    return not any(brand in name_norm for brand in foreign_brands)


def _product_group_key(value: object) -> str:
    tokens = _query_tokens(str(value))
    stop_tokens = {
        "котел", "турбо", "дым", "без", "трубы", "двухконтурный",
        "контурный", "тепл", "ка", "акция", "new", "су", "slim", "r",
    }

    strong = []
    for token in tokens:
        if token in stop_tokens:
            continue
        if token.isdigit() and int(token) < 10:
            continue
        strong.append(token)

    return " ".join(strong[:5]) or _normalize_text(value)


supplier_cache_service = SupplierCacheService()
