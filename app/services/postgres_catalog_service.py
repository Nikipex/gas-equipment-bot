
"""Readonly PostgreSQL catalog service for 1C procurement/search marts."""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from typing import Iterable

import pandas as pd
from rapidfuzz import fuzz
from sqlalchemy import create_engine

from app.services.radiator_price_service import radiator_price_service


DEFAULT_DATABASE_URL = "postgresql+psycopg2://nikitos:123456@127.0.0.1:5433/torg_full"


@dataclass
class CatalogItem:
    product_name: str
    product_group: str
    stock_qty: float | None
    purchase_price: float | None = None
    is_alternative: bool = False
    excel_price_profile: str | None = None
    excel_client_price: float | None = None


@dataclass(frozen=True)
class SearchQuery:
    original: str
    clean: str
    price_profile: str | None
    tokens: list[str]
    text_tokens: list[str]
    numeric_tokens: list[str]
    required_groups: list[list[str]]
    is_radiator: bool


class PostgresCatalogService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = (
            database_url
            or os.getenv("PROCUREMENT_DATABASE_URL")
            or DEFAULT_DATABASE_URL
        )
        self.engine = create_engine(self.database_url)

    def search(self, query: str, limit: int = 10) -> list[CatalogItem]:
        search = _prepare_search_query(query)
        if not search.tokens:
            return []

        params: dict[str, object] = {"limit": limit}
        min_match_score = _min_match_score(search)

        sql = _build_search_sql(search, params, min_match_score)
        df = pd.read_sql(sql, self.engine, params=params)
        df = _rerank_dataframe(df, search, limit)

        if df.empty and search.is_radiator:
            alternatives = self._search_radiator_alternatives(
                search,
                limit=4,
            )
            if alternatives:
                return alternatives

        return _rows_to_catalog_items(df, search.price_profile)

    def _search_radiator_alternatives(
        self,
        search: SearchQuery,
        limit: int = 4,
    ) -> list[CatalogItem]:
        """If exact radiator is absent, return closest in-stock sizes."""
        nums = [int(token) for token in search.numeric_tokens]
        if not nums:
            return []

        radiator_types = {10, 11, 20, 21, 22, 30, 33}
        radiator_heights = {200, 300, 500, 600, 900}

        radiator_type = next((num for num in nums if num in radiator_types), None)
        radiator_height = next((num for num in nums if num in radiator_heights), None)
        radiator_length = max((num for num in nums if 400 <= num <= 3000), default=None)

        if radiator_height is None or radiator_length is None:
            return []

        need_low = any(token in {"низ", "ниж", "нижн", "нижнее", "нижний"} for token in search.tokens)

        params: dict[str, object] = {
            "limit": limit,
            "height": str(radiator_height),
            "target_length": radiator_length,
            "radiator_pattern": "%радиатор%",
            "low_pattern": "%ниж%",
        }

        type_filter = ""
        if radiator_type is not None:
            type_filter = "AND radiator_type = %(radiator_type)s"
            params["radiator_type"] = str(radiator_type)

        low_filter = "AND lower(product_name) ILIKE %(low_pattern)s" if need_low else ""

        sql = f"""
            WITH purchase_prices AS (
                SELECT product_id_hex, purchase_price
                FROM public.latest_purchase_prices
            ),

            raw AS (
                SELECT
                    s.product_name,
                    s.product_code,
                    encode(n._idrref, 'hex') AS product_id_hex,
                    s.stock_qty,
                    pp.purchase_price,
                    regexp_match(
                        lower(s.product_name),
                        '([0-9]{{3}})//([0-9]{{2}})\\*([0-9]{{3,4}})'
                    ) AS m
                FROM public.stock_south_warehouse_agg s
                LEFT JOIN public._reference80 n
                    ON n._code = s.product_code
                LEFT JOIN purchase_prices pp
                    ON pp.product_id_hex = encode(n._idrref, 'hex')
                WHERE lower(s.product_name) ILIKE %(radiator_pattern)s
                  AND s.stock_qty > 0
                  {low_filter}
            ),

            parsed AS (
                SELECT
                    product_name,
                    stock_qty,
                    purchase_price,
                    (m[1]) AS radiator_height,
                    (m[2]) AS radiator_type,
                    (m[3])::int AS radiator_length
                FROM raw
                WHERE m IS NOT NULL
            )

            SELECT
                product_name,
                'радиаторы / ближайший размер' AS product_group,
                stock_qty,
                purchase_price
            FROM parsed
            WHERE radiator_height = %(height)s
              {type_filter}
              AND radiator_length <> %(target_length)s
            ORDER BY
                ABS(radiator_length - %(target_length)s),
                radiator_length,
                product_name
            LIMIT %(limit)s
        """

        df = pd.read_sql(sql, self.engine, params=params)
        return _rows_to_catalog_items(df, search.price_profile, is_alternative=True)

    @staticmethod
    def format_results(items: list[CatalogItem], query: str) -> str:
        safe_query = html.escape(query)

        if not items:
            return f"❌ Ничего не найдено по запросу: <b>{safe_query}</b>"

        has_alternatives = any(item.is_alternative for item in items)
        if has_alternatives:
            lines = [
                f"🔍 <b>Результаты по запросу:</b> {safe_query}",
                "",
                "❌ <b>Точного радиатора в наличии нет.</b>",
                "📏 <b>Ближайшие размеры из остатков:</b>",
                "",
            ]
        else:
            lines = [f"🔍 <b>Результаты по запросу:</b> {safe_query}", ""]

        for index, item in enumerate(items, start=1):
            safe_name = html.escape(item.product_name)
            stock_text, purchase_label = _stock_and_purchase_labels(item.stock_qty)

            details = [
                f"<b>{index}. {safe_name}</b>",
                stock_text,
                f"{purchase_label}: {_format_price(item.purchase_price)}",
            ]

            if _is_radiator_item(item) and item.excel_client_price is not None and item.excel_price_profile:
                safe_profile = html.escape(item.excel_price_profile)
                details.append(f"📄 Прайс {safe_profile}: {_format_price(item.excel_client_price)}")

            lines.append("\n".join(details))

        return "\n\n".join(lines)


SQL_SOURCES = [
    {
        "name": "dashboard",
        "priority": 1,
        "product_name": "d.product_name",
        "product_code": "d.product_code",
        "product_id": "d.product_id_hex",
        "product_group": "d.product_group",
        "stock_qty": "d.stock_qty",
        "from": "public.procurement_south_dashboard d",
        "joins": """
                LEFT JOIN purchase_prices pp
                    ON pp.product_id_hex = d.product_id_hex
        """,
        "price_join_id": "d.product_id_hex",
        "base_where": "1=1",
    },
    {
        "name": "radiators",
        "priority": 2,
        "product_name": "r.product_name",
        "product_code": "r.product_code",
        "product_id": "r.product_id_hex",
        "product_group": "'радиаторы'",
        "stock_qty": "r.free_stock_qty",
        "from": "public.radiator_procurement_mvp r",
        "joins": """
                LEFT JOIN purchase_prices pp
                    ON pp.product_id_hex = r.product_id_hex
        """,
        "price_join_id": "r.product_id_hex",
        "base_where": "1=1",
    },
    {
        "name": "south_stock",
        "priority": 3,
        "product_name": "s.product_name",
        "product_code": "s.product_code",
        "product_id": "encode(n_s._idrref, 'hex')",
        "product_group": "COALESCE(d.product_group, 'не классифицировано')",
        "stock_qty": "s.stock_qty",
        "from": "public.stock_south_warehouse_agg s",
        "joins": """
                LEFT JOIN public._reference80 n_s
                    ON n_s._code = s.product_code
                LEFT JOIN public.procurement_south_dashboard d
                    ON d.product_code = s.product_code
                LEFT JOIN purchase_prices pp
                    ON pp.product_id_hex = encode(n_s._idrref, 'hex')
        """,
        "price_join_id": "encode(n_s._idrref, 'hex')",
        "base_where": "1=1",
    },
    {
        "name": "live_ref",
        "priority": 4,
        "product_name": "n._description",
        "product_code": "n._code",
        "product_id": "encode(n._idrref, 'hex')",
        "product_group": "COALESCE(d.product_group, 'не классифицировано')",
        "stock_qty": "d.stock_qty",
        "from": "public._reference80 n",
        "joins": """
                LEFT JOIN public.procurement_south_dashboard d
                    ON d.product_code = n._code
                LEFT JOIN purchase_prices pp
                    ON pp.product_id_hex = encode(n._idrref, 'hex')
        """,
        "price_join_id": "encode(n._idrref, 'hex')",
        "base_where": "COALESCE(n._folder, false) = false AND char_length(trim(COALESCE(n._description, ''))) > 5",
    },
]


STOP_WORDS = {
    "котел", "котёл", "настенный", "напольный", "газовый", "радиатор",
    "стальной", "панельный", "дымов", "дым", "верт", "вертик", "гориз",
    "бара", "бар", "sit", "кв", "квм", "квт", "м", "мм", "шт", "компл",
    "подкл", "подключение", "бок", "боковое", "низ", "ниж", "нижнее", "нижний",
}

TOKEN_SYNONYMS: dict[str, list[str]] = {
    "артек": ["артек", "atem", "атем", "житомир", "кс", "ксг"],
    "кс": ["кс", "ксг", "кстг"],
    "ксг": ["ксг", "кс", "кстг"],
    "сибирия": ["сибирия", "siberia"],
    "ардерия": ["ардерия", "arderia"],
    "arderia": ["arderia", "ардерия"],
    "навьен": ["навьен", "navien"],
    "навьен": ["навьен", "navien"],
    "baxi": ["baxi", "бакси"],
    "бакси": ["бакси", "baxi"],
}


def _prepare_search_query(query: str) -> SearchQuery:
    original = query.strip()
    price_profile = radiator_price_service.extract_profile(original.lower())

    clean = original.lower()
    clean = re.sub(r"(?:прайс|price)\s*[:№#-]?\s*\d{3,6}", " ", clean, flags=re.IGNORECASE)
    clean = clean.translate(str.maketrans({"-": " ", "/": " ", "\\": " ", "–": " ", "—": " ", ".": " ", ",": " ", "(": " ", ")": " "}))

    raw_tokens = [_normalize_token(token) for token in re.split(r"\s+", clean)]
    tokens = [token for token in raw_tokens if len(token) >= 2]
    tokens = _expand_short_numbers(tokens)

    text_tokens = [token for token in tokens if not token.isdigit()]
    numeric_tokens = [token for token in tokens if token.isdigit()]
    is_radiator = any(token.startswith("радиатор") for token in text_tokens)

    required_groups = _build_required_groups(text_tokens, numeric_tokens, is_radiator)

    return SearchQuery(
        original=original,
        clean=clean,
        price_profile=price_profile,
        tokens=tokens,
        text_tokens=text_tokens,
        numeric_tokens=numeric_tokens,
        required_groups=required_groups,
        is_radiator=is_radiator,
    )


def _build_required_groups(
    text_tokens: list[str],
    numeric_tokens: list[str],
    is_radiator: bool,
) -> list[list[str]]:
    if is_radiator:
        return []

    meaningful = [
        token for token in text_tokens
        if token not in STOP_WORDS and len(token) >= 3
    ]

    groups: list[list[str]] = []
    if meaningful:
        groups.append(_token_variants(meaningful[0]))

    # For models like "артек 10", "eco nova 24", "navien ngb 13" the first
    # numeric token is a real model discriminator. It is required, but only one
    # numeric token is required to avoid killing long copied 1C names.
    if numeric_tokens:
        groups.append(_token_variants(numeric_tokens[0]))

    return groups


def _build_search_sql(
    search: SearchQuery,
    params: dict[str, object],
    min_match_score: int,
) -> str:
    source_ctes = []
    union_selects = []

    for source in SQL_SOURCES:
        name_col = str(source["product_name"])
        code_col = str(source["product_code"])
        match_expr = _score_expr(search, name_col, code_col, params, str(source["name"]))
        required_expr = _required_expr(search, name_col, code_col, params, str(source["name"]))
        numeric_expr = _radiator_numeric_expr(search, name_col, params, str(source["name"]))
        where_expr = f"({source['base_where']}) AND ({match_expr}) >= {min_match_score} AND ({required_expr}) AND ({numeric_expr})"

        source_ctes.append(
            f"""
            {source['name']} AS (
                SELECT
                    {name_col} AS product_name,
                    {code_col} AS product_code,
                    {source['product_id']} AS product_id_hex,
                    {source['product_group']} AS product_group,
                    {source['stock_qty']} AS stock_qty,
                    pp.purchase_price,
                    ({match_expr}) AS match_score,
                    {source['priority']} AS source_priority
                FROM {source['from']}
                {source['joins']}
                WHERE {where_expr}
            )
            """
        )
        union_selects.append(f"SELECT * FROM {source['name']}")

    return f"""
        WITH purchase_prices AS (
            SELECT product_id_hex, purchase_price
            FROM public.latest_purchase_prices
        ),

        {', '.join(source_ctes)},

        unioned AS (
            {' UNION ALL '.join(union_selects)}
        ),

        dedup AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY product_id_hex
                    ORDER BY
                        match_score DESC,
                        source_priority,
                        COALESCE(stock_qty, 0) DESC,
                        product_name
                ) AS rn
            FROM unioned
        )

        SELECT
            product_name,
            product_group,
            stock_qty,
            purchase_price,
            match_score,
            source_priority
        FROM dedup
        WHERE rn = 1
        ORDER BY
            match_score DESC,
            source_priority,
            COALESCE(stock_qty, 0) DESC,
            product_name
        LIMIT %(limit)s
    """


def _score_expr(
    search: SearchQuery,
    name_col: str,
    code_col: str,
    params: dict[str, object],
    source_name: str,
) -> str:
    parts: list[str] = []
    normalized_name = _normalized_sql(name_col)
    normalized_code = _normalized_sql(code_col)

    for token_index, token in enumerate(search.tokens):
        variant_parts: list[str] = []
        for variant_index, variant in enumerate(_token_variants(token)):
            key = f"score_{source_name}_{token_index}_{variant_index}"
            norm_key = f"score_norm_{source_name}_{token_index}_{variant_index}"
            params[key] = f"%{variant}%"
            params[norm_key] = f"%{_normalize_token(variant)}%"
            variant_parts.append(
                "("
                f"{name_col} ILIKE %({key})s "
                f"OR {code_col} ILIKE %({key})s "
                f"OR {normalized_name} ILIKE %({norm_key})s "
                f"OR {normalized_code} ILIKE %({norm_key})s"
                ")"
            )

        if variant_parts:
            parts.append("CASE WHEN " + " OR ".join(variant_parts) + " THEN 1 ELSE 0 END")

    return " + ".join(parts) if parts else "0"


def _required_expr(
    search: SearchQuery,
    name_col: str,
    code_col: str,
    params: dict[str, object],
    source_name: str,
) -> str:
    if not search.required_groups:
        return "1=1"

    normalized_name = _normalized_sql(name_col)
    normalized_code = _normalized_sql(code_col)
    required_parts: list[str] = []

    for group_index, group in enumerate(search.required_groups):
        group_parts: list[str] = []
        for variant_index, variant in enumerate(group):
            key = f"req_{source_name}_{group_index}_{variant_index}"
            norm_key = f"req_norm_{source_name}_{group_index}_{variant_index}"
            params[key] = f"%{variant}%"
            params[norm_key] = f"%{_normalize_token(variant)}%"
            group_parts.append(
                "("
                f"{name_col} ILIKE %({key})s "
                f"OR {code_col} ILIKE %({key})s "
                f"OR {normalized_name} ILIKE %({norm_key})s "
                f"OR {normalized_code} ILIKE %({norm_key})s"
                ")"
            )

        if group_parts:
            required_parts.append("(" + " OR ".join(group_parts) + ")")

    return " AND ".join(required_parts) if required_parts else "1=1"


def _radiator_numeric_expr(
    search: SearchQuery,
    name_col: str,
    params: dict[str, object],
    source_name: str,
) -> str:
    if not search.is_radiator or not search.numeric_tokens:
        return "1=1"

    normalized_name = _normalized_sql(name_col)
    parts: list[str] = []
    for index, token in enumerate(search.numeric_tokens):
        key = f"rad_num_{source_name}_{index}"
        params[key] = f"%{token}%"
        parts.append(f"({name_col} ILIKE %({key})s OR {normalized_name} ILIKE %({key})s)")

    return " AND ".join(parts) if parts else "1=1"


def _rerank_dataframe(df: pd.DataFrame, search: SearchQuery, limit: int) -> pd.DataFrame:
    if df.empty:
        return df

    query_norm = _normalize_token(search.clean)

    def fuzzy_score(name: str) -> int:
        name_norm = _normalize_token(str(name))
        return int(fuzz.partial_ratio(query_norm, name_norm))

    df = df.copy()
    df["fuzzy_score"] = df["product_name"].apply(fuzzy_score)
    return (
        df.sort_values(
            by=["match_score", "fuzzy_score", "source_priority", "stock_qty"],
            ascending=[False, False, True, False],
        )
        .drop_duplicates(subset=["product_name"])
        .head(limit)
    )


def _rows_to_catalog_items(
    df: pd.DataFrame,
    price_profile: str | None,
    is_alternative: bool = False,
) -> list[CatalogItem]:
    items: list[CatalogItem] = []
    for _, row in df.iterrows():
        product_name = str(row["product_name"])
        excel_price = radiator_price_service.get_price_for_product(product_name, price_profile)

        items.append(
            CatalogItem(
                product_name=product_name,
                product_group=str(row["product_group"]),
                stock_qty=None if pd.isna(row["stock_qty"]) else float(row["stock_qty"] or 0),
                purchase_price=None if pd.isna(row["purchase_price"]) else float(row["purchase_price"] or 0),
                is_alternative=is_alternative,
                excel_price_profile=price_profile if excel_price is not None else None,
                excel_client_price=excel_price,
            )
        )

    return items


def _min_match_score(search: SearchQuery) -> int:
    if search.is_radiator:
        return min(2, len(search.tokens))
    return 1 if len(search.tokens) <= 2 else 2


def _expand_short_numbers(tokens: Iterable[str]) -> list[str]:
    result: list[str] = []
    for token in tokens:
        result.append(token)
        if token.isdigit() and len(token) <= 2:
            result.append(token.zfill(3))
    return list(dict.fromkeys(result))


def _token_variants(token: str) -> list[str]:
    variants = TOKEN_SYNONYMS.get(token, [token])
    if token.isdigit() and len(token) <= 2:
        variants = [*variants, token.zfill(3)]
    return list(dict.fromkeys(_normalize_token(variant) for variant in variants if _normalize_token(variant)))


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-zа-я0-9]+", "", value.lower())


def _normalized_sql(column: str) -> str:
    return f"regexp_replace(lower({column}), '[^a-zа-я0-9]+', '', 'g')"


def _stock_and_purchase_labels(stock_qty: float | None) -> tuple[str, str]:
    if stock_qty is None:
        return "📦 В наличии: не подтянут", "💸 Закупка 1С"
    if stock_qty <= 0:
        return "❌ <b>Нет в наличии</b>", "🔴 Последняя закупка 1С"
    return f"📦 В наличии: {_format_stock_qty(stock_qty)}", "💸 Закупка 1С"


def _is_radiator_item(item: CatalogItem) -> bool:
    value = f"{item.product_group} {item.product_name}".lower()
    return "радиатор" in value


def _format_stock_qty(value: float | None) -> str:
    if value is None:
        return "не подтянут"
    return f"{value:g} шт"


def _format_price(value: float | None) -> str:
    if value is None or value <= 0:
        return "не подтянута"
    return f"{value:,.0f} ₽".replace(",", " ")
