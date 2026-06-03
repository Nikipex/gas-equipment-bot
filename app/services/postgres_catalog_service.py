
"""Readonly PostgreSQL catalog service for 1C procurement/search marts."""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from typing import Iterable

import pandas as pd
from dotenv import load_dotenv
from rapidfuzz import fuzz
from sqlalchemy import create_engine

from app.services.radiator_price_service import radiator_price_service


DEFAULT_DATABASE_URL = "postgresql+psycopg2://nikitos:123456@127.0.0.1:5433/torg_full"

BRAND_SYNONYMS = {
    "бакси": "baxi",
    "баксиэ": "baxi",
    "baksi": "baxi",

    "навьен": "navien",
    "навиен": "navien",
    "навьен": "navien",

    "фондитал": "fondital",
    "фондиталь": "fondital",

    "федерика бугатти": "federica bugatti",
    "федерика бугати": "federica bugatti",
    "федерика": "federica bugatti",
    "бугатти": "federica bugatti",
    "бугати": "federica bugatti",

    "лемакс": "lemax",
    "ферроли": "ferroli",
    "аристон": "ariston",
    "бакси эко 4с 24ф": "baxi eco 4s 24 f",
    "бакси эко 4с 24": "baxi eco 4s 24",
    "бакси эко нова 24ф": "baxi eco nova 24 f",
    "бакси эко нова 24": "baxi eco nova 24",
    "навьен с 24": "navien deluxe c 24",
    "навиен с 24": "navien deluxe c 24",
    "navien c 24": "navien deluxe c 24",
    "делюкс с 24": "navien deluxe c 24",
    "deluxe c 24": "navien deluxe c 24",
    "федерика бугати 24": "federica bugatti 24",
    "федерика бугатти 24": "federica bugatti 24",
    "бугати 24": "federica bugatti 24",
}



SEARCH_STOPWORDS = {
    "найти", "найди", "поиск", "покажи", "показать",
    "товар", "позиция", "позицию", "номенклатура",
    "цена", "цену", "прайс", "прайсу", "прайса",
    "остаток", "остатки", "наличие", "есть",
    "сколько", "нужно", "надо", "шт", "штук",
    "закупка", "закуп", "себестоимость",
}



def _expand_compact_radiator_tokens(value: str) -> str:
    """Expand compact radiator geometry like 115001000 -> radiator 11 500 1000."""
    text = str(value or "")

    def repl(match: re.Match[str]) -> str:
        rtype = match.group(1)
        height = match.group(2)
        length = match.group(3)
        return f"{match.group(0)} радиатор {rtype} {height} {length}"

    # Examples:
    # 115001000 -> 11 500 1000
    # 225001200 -> 22 500 1200
    # 333002000 -> 33 300 2000
    return re.sub(r"\b(11|21|22|33)(200|300|500|600|900)(\d{3,4})\b", repl, text)


def _remove_search_stopwords(value: str) -> str:
    tokens = re.split(r"\s+", str(value or "").strip())
    clean_tokens = []
    for token in tokens:
        token_norm = token.strip(" ,.;:!?()[]{}").lower().replace("ё", "е")
        if token_norm in SEARCH_STOPWORDS:
            continue
        clean_tokens.append(token)
    return " ".join(clean_tokens)

def _apply_brand_synonyms(value: str) -> str:
    text = str(value or "").lower().replace("ё", "е")
    # длинные ключи первыми, чтобы "федерика бугатти" не разбилась раньше времени
    for src in sorted(BRAND_SYNONYMS, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", BRAND_SYNONYMS[src], text)
    return text



@dataclass
class CatalogItem:
    product_name: str
    product_group: str
    stock_qty: float | None
    purchase_price: float | None = None
    stock_total_qty: float | None = None
    reserved_qty: float | None = None
    business_available_qty: float | None = None
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
        load_dotenv(".env", override=True)

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

        if self._should_use_live_reference_fallback():
            df = self._search_live_reference_fallback(search, max(limit * 5, 30))
            df = _rerank_dataframe(df, search, limit)
            return _rows_to_catalog_items(df, search.price_profile)

        params: dict[str, object] = {"limit": limit}

        exact_model_number = None
        for token in search.numeric_tokens:
            try:
                number = int(token)
            except Exception:
                continue
            if 1 <= number <= 100:
                exact_model_number = number
                break

        params["exact_model_number"] = exact_model_number
        params["exact_model_regex"] = (
            rf"ксг-?в?-?{exact_model_number}([^0-9]|$)"
            if exact_model_number is not None
            else ""
        )
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

    def _should_use_live_reference_fallback(self) -> bool:
        """Use raw 1C nomenclature when prepared mart views are absent."""
        try:
            probe = pd.read_sql(
                """
                SELECT to_regclass('public.procurement_south_dashboard') AS dashboard,
                       to_regclass('public.latest_purchase_prices') AS prices
                """,
                self.engine,
            )
            row = probe.iloc[0]
            return not bool(row["dashboard"]) or not bool(row["prices"])
        except Exception:
            return True

    def _search_live_reference_fallback(
        self,
        search: SearchQuery,
        limit: int,
    ) -> pd.DataFrame:
        """Live TORG fallback: raw 1C nomenclature + South warehouse stock."""
        raw = search.original.lower().replace("ё", "е")

        base_cte = """
            WITH total_stock AS (
                SELECT
                    s._fld9098rref AS product_id,
                    SUM(s._fld9106) AS total_stock_qty,
                    SUM(s._fld9107) AS stock_amount
                FROM public._accumrgt9117 s
                WHERE s._fld9099rref = decode('83ee60f67771497111e9dbb16ec97a48','hex')
                  AND s._period = TIMESTAMP '3999-11-01 00:00:00'
                GROUP BY s._fld9098rref
            ),
            reserved_stock AS (
                SELECT
                    r._fld9301rref AS product_id,
                    SUM(GREATEST(COALESCE(r._fld9305, 0), 0)) AS reserved_stock_qty
                FROM public._accumrgt9308 r
                WHERE r._fld9300rref = decode('83ee60f67771497111e9dbb16ec97a48','hex')
                  AND r._period = TIMESTAMP '3999-11-01 00:00:00'
                GROUP BY r._fld9301rref
            ),
            south_stock AS (
                SELECT
                    COALESCE(t.product_id, r.product_id) AS product_id,
                    COALESCE(t.total_stock_qty, 0) AS total_stock_qty,
                    COALESCE(r.reserved_stock_qty, 0) AS reserved_stock_qty,
                    GREATEST(
                        COALESCE(t.total_stock_qty, 0) - COALESCE(r.reserved_stock_qty, 0),
                        0
                    ) AS free_stock_qty,
                    COALESCE(t.stock_amount, 0) AS stock_amount
                FROM total_stock t
                FULL OUTER JOIN reserved_stock r
                    ON r.product_id = t.product_id
            ),
            business_available AS (
                SELECT
                    a._fld8741rref AS product_id,
                    SUM(COALESCE(a._fld8745, 0)) AS business_available_qty
                FROM public._accumrgt8755 a
                WHERE a._period = TIMESTAMP '3999-11-01 00:00:00'
                GROUP BY a._fld8741rref
            ),
            latest_purchase AS (
                SELECT DISTINCT ON (r._fld9098rref)
                    r._fld9098rref AS product_id,
                    r._period AS purchase_date,
                    ROUND(r._fld9107 / NULLIF(r._fld9106, 0), 2) AS purchase_price
                FROM public._accumrg9097 r
                WHERE r._active = true
                  AND r._recordkind = 0
                  AND encode(r._recordertref, 'hex') = '000000e6'
                  AND encode(r._fld9099rref, 'hex') = '83ee60f67771497111e9dbb16ec97a48'
                  AND r._fld9106 > 0
                  AND r._fld9107 > 0
                ORDER BY r._fld9098rref, r._period DESC
            )
        """

        select_sql = """
            SELECT
                n._description::text AS product_name,
                'live 1c south stock' AS product_group,
                COALESCE(st.free_stock_qty, 0)::numeric AS stock_qty,
                COALESCE(st.total_stock_qty, 0)::numeric AS stock_total_qty,
                COALESCE(st.reserved_stock_qty, 0)::numeric AS reserved_qty,
                COALESCE(ba.business_available_qty, 0)::numeric AS business_available_qty,
                lp.purchase_price::numeric AS purchase_price,
                1 AS match_score,
                1 AS source_priority
            FROM public._reference80 n
            LEFT JOIN south_stock st ON st.product_id = n._idrref
            LEFT JOIN business_available ba ON ba.product_id = n._idrref
            LEFT JOIN latest_purchase lp ON lp.product_id = n._idrref
        """

        # 0) BAXI ECO NOVA 24 / 24F exact-ish
        if "eco" in raw and "nova" in raw and "24" in raw:
            sql = base_cte + select_sql + """
                WHERE lower(n._description::text) LIKE '%%baxi%%'
                  AND lower(n._description::text) LIKE '%%eco%%'
                  AND lower(n._description::text) LIKE '%%nova%%'
                  AND lower(n._description::text) LIKE '%%24%%'
                ORDER BY
                    CASE
                        WHEN lower(n._description::text) LIKE '%%24f%%'
                          OR lower(n._description::text) LIKE '%%24 f%%'
                        THEN 0
                        ELSE 1
                    END,
                    COALESCE(st.free_stock_qty, 0) DESC,
                    n._description::text
                LIMIT %(limit)s
            """
            return pd.read_sql(sql, self.engine, params={"limit": limit})

        # 1) BAXI ECO 4S 24F exact-ish
        if ("baxi" in raw or "бакси" in raw) and "eco" in raw and "4s" in raw and ("24f" in raw.replace(" ", "") or "24 f" in raw):
            sql = base_cte + select_sql + """
                WHERE lower(n._description::text) LIKE '%%baxi%%'
                  AND lower(n._description::text) LIKE '%%eco%%'
                  AND lower(n._description::text) LIKE '%%4s%%'
                  AND lower(n._description::text) LIKE '%%24%%'
                  AND lower(n._description::text) LIKE '%%f%%'
                  AND lower(n._description::text) NOT LIKE '%%1.24%%'
                ORDER BY
                    CASE
                        WHEN lower(n._description::text) LIKE '%%eco 4s 24 f%%' THEN 0
                        WHEN lower(n._description::text) LIKE '%%eco 4s 24%%' THEN 1
                        ELSE 9
                    END,
                    COALESCE(st.free_stock_qty, 0) DESC,
                    n._description::text
                LIMIT %(limit)s
            """
            return pd.read_sql(sql, self.engine, params={"limit": limit})

        # 2) Радиаторы: 500 22 1000 -> 500//22*1000 / 500/22/1000
        if "радиатор" in raw:
            nums = []
            for token in search.numeric_tokens:
                try:
                    nums.append(int(token))
                except Exception:
                    pass

            height = next((x for x in nums if x in {200, 300, 500, 600, 900}), None)
            rtype = next((x for x in nums if x in {10, 11, 20, 21, 22, 30, 33}), None)
            length = next((x for x in nums if 400 <= x <= 3000 and x != height), None)

            if height and rtype and length:
                wants_bottom = any(x in raw for x in ("низ", "ниж", "нижнее", "нижний", "нижн", "vk", "вк"))
                wants_side = any(x in raw for x in ("бок", "боковое", "боковой", "бок."))

                connection_filter = ""
                if wants_bottom:
                    connection_filter = """
                      AND (
                            lower(n._description::text) LIKE '%%vk%%'
                         OR lower(n._description::text) LIKE '%%ниж%%'
                         OR lower(n._description::text) LIKE '%%низ%%'
                      )
                    """
                elif wants_side:
                    connection_filter = """
                      AND lower(n._description::text) NOT LIKE '%%vk%%'
                      AND lower(n._description::text) NOT LIKE '%%ниж%%'
                      AND lower(n._description::text) NOT LIKE '%%низ%%'
                    """

                raw_lower = raw.lower()
                requested_vendor = any(
                    vendor in raw_lower
                    for vendor in (
                        "ruterm", "рут", "orso", "орсо", "sanline", "санлайн",
                        "proexpert", "проэксперт", "prado", "прадо",
                        "terra", "терра", "tt", "тт", "universal", "универсал",
                    )
                )

                vendor_filter = ""
                if not requested_vendor:
                    vendor_filter = """
                      AND lower(n._description::text) NOT LIKE '%%ruterm%%'
                      AND lower(n._description::text) NOT LIKE '%%orso%%'
                      AND lower(n._description::text) NOT LIKE '%%sanline%%'
                      AND lower(n._description::text) NOT LIKE '%%proexpert%%'
                      AND lower(n._description::text) NOT LIKE '%%prado%%'
                      AND lower(n._description::text) NOT LIKE '%%terra%%'
                      AND lower(n._description::text) NOT LIKE '%% tt %%'
                    """

                sql = base_cte + select_sql + f"""
                    WHERE lower(n._description::text) LIKE '%%радиатор%%'
                      AND (
                            n._description::text LIKE %(p1)s
                         OR n._description::text LIKE %(p2)s
                      )
                      {connection_filter}
                      {vendor_filter}
                    ORDER BY
                        CASE
                            WHEN n._description::text LIKE '%%(1,2)%%' THEN 0
                            ELSE 1
                        END,
                        COALESCE(st.free_stock_qty, 0) DESC,
                        n._description::text
                    LIMIT %(limit)s
                """
                return pd.read_sql(
                    sql,
                    self.engine,
                    params={
                        "limit": limit,
                        "p1": f"%{height}//{rtype}*{length}%",
                        "p2": f"%{height}/{rtype}/{length}%",
                    },
                )

        # 3) Коаксиалы / дымоходка: только CAMINO folder
        if any(x in raw for x in ("коакси", "дымоход", "адаптер", "колено", "конденсат", "60/100", "80/80", "80/125")):
            words = [x for x in search.text_tokens if len(x) >= 3 and x not in {"труба"}]
            params = {"limit": limit, "raw_query": raw}
            parts = []

            for i, token in enumerate(words[:5]):
                key = f"q{i}"
                params[key] = f"%{token}%"
                parts.append(f"lower(n._description::text) LIKE %({key})s")

            where_extra = " AND ".join(parts) if parts else "true"

            sql = base_cte + select_sql + f"""
                WHERE encode(n._parentidrref, 'hex') = 'bdcc6a640748b82d11efde156fb54c80'
                  AND ({where_extra})
                  AND (
                        POSITION('60/100' IN %(raw_query)s) = 0
                     OR n._description::text LIKE '%%60/100%%'
                  )
                ORDER BY COALESCE(st.free_stock_qty, 0) DESC, n._description::text
                LIMIT %(limit)s
            """
            return pd.read_sql(sql, self.engine, params=params)

        # 4) General fallback: required groups + stock
        params: dict[str, object] = {"limit": limit}
        required_sql_parts: list[str] = []

        for group_index, group in enumerate(search.required_groups):
            group_conditions = []
            for token_index, token in enumerate(group):
                key = f"req_{group_index}_{token_index}"
                params[key] = f"%{token}%"
                group_conditions.append(f"lower(n._description::text) LIKE %({key})s")
            if group_conditions:
                required_sql_parts.append("(" + " OR ".join(group_conditions) + ")")

        if not required_sql_parts:
            useful = [
                x for x in (search.text_tokens + search.numeric_tokens)
                if len(x) >= 2 and x not in {"котел", "газовый", "настенный", "напольный"}
            ][:4]
            for i, token in enumerate(useful):
                key = f"u{i}"
                params[key] = f"%{token}%"
                required_sql_parts.append(f"lower(n._description::text) LIKE %({key})s")

        if not required_sql_parts:
            return pd.DataFrame(columns=["product_name", "product_group", "stock_qty", "purchase_price"])

        required_sql = " AND ".join(required_sql_parts)

        exact_model_number = None
        for token in search.numeric_tokens:
            try:
                n = int(token)
            except Exception:
                continue
            if 1 <= n <= 100:
                exact_model_number = n
                break

        model_filter = ""
        if exact_model_number is not None and any(x in raw for x in ("ксг", "ксгв", "луч")):
            params["model_regex"] = rf"ксг-?в?-?{exact_model_number}([^0-9]|$)"
            model_filter = "AND lower(n._description::text) ~ %(model_regex)s"

        sql = base_cte + select_sql + f"""
            WHERE ({required_sql})
              {model_filter}
            ORDER BY
                COALESCE(st.free_stock_qty, 0) DESC,
                n._description::text
            LIMIT %(limit)s
        """
        return pd.read_sql(sql, self.engine, params=params)


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
            stock_text = _format_stock_breakdown(item)

            if item.stock_qty is None:
                purchase_label = "💸 Закупка 1С"
            elif item.stock_qty <= 0:
                purchase_label = "🔴 Последняя закупка 1С"
            else:
                purchase_label = "💸 Средняя закупка 1С"

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
    query = _apply_brand_synonyms(query)
    query = _remove_search_stopwords(query)
    query = _expand_compact_radiator_tokens(query)
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



def _extract_model_number(search: SearchQuery) -> str | None:
    """Extract boiler/equipment model power number from query: 10/11/12/13/16/18/24/30/35/40 etc."""
    if search.is_radiator:
        return None

    # Prefer common boiler/gas heater power numbers.
    common = {
        "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "18",
        "20", "21", "22", "24", "28", "30", "32", "35", "40",
    }
    for token in search.numeric_tokens:
        if token in common:
            return token
    return None


def _name_has_model_number(product_name: str, number: str) -> bool:
    """True when number appears as standalone-ish model/power token, not as part of another number."""
    name = str(product_name or "").lower().replace("ё", "е")

    patterns = [
        rf"(?<!\d){re.escape(number)}(?!\d)",          # 24
        rf"(?<!\d){re.escape(number)}\s*f(?!\w)",      # 24 F
        rf"(?<!\d){re.escape(number)}f(?!\w)",         # 24F
        rf"(?<!\d){re.escape(number)}\s*k(?!\w)",      # 24K
        rf"(?<!\d){re.escape(number)}k(?!\w)",         # 24K
        rf"ксг[-\s]*{re.escape(number)}(?!\d)",        # КСГ-16
        rf"ксгз[-\s]*{re.escape(number)}(?!\d)",       # КСГЗ-16
        rf"ксгв[-\s]*{re.escape(number)}(?!\d)",       # КСГВ-16
    ]

    return any(re.search(pattern, name) for pattern in patterns)


def _apply_strict_brand_line_filter(df: pd.DataFrame, search: SearchQuery) -> pd.DataFrame:
    """Keep only products matching explicit brand/line intent from query."""
    if df.empty:
        return df

    q = search.clean.lower().replace("ё", "е")

    rules: list[list[str]] = []

    if "артек" in q:
        rules.append(["артек"])

    # ECO 4S / ECO NOVA are strong BAXI line intents.
    # Managers often search "Eco 4s 24" without typing BAXI.
    # Without this, fuzzy search pulls unrelated Oasis/Federica/Mizudo "Eco 24".
    if "eco" in q and "4s" in q:
        rules.append(["eco", "4s"])
        # If the current result set contains BAXI ECO 4S, prefer BAXI-only.
        if df["product_name"].astype(str).str.lower().str.contains("baxi", na=False).any():
            rules.append(["baxi"])
    elif "eco" in q and "nova" in q:
        rules.append(["eco", "nova"])
        if df["product_name"].astype(str).str.lower().str.contains("baxi", na=False).any():
            rules.append(["baxi"])

    if "baxi" in q:
        rules.append(["baxi"])

    if "navien" in q:
        rules.append(["navien"])
        if "deluxe" in q:
            rules.append(["deluxe"])
        if re.search(r"\bc\b", q):
            rules.append(["c"])

    if "federica" in q or "bugatti" in q:
        rules.append(["federica", "bugatti"])

    if "fondital" in q:
        rules.append(["fondital"])

    if not rules:
        return df

    def ok(name: str) -> bool:
        n = str(name or "").lower().replace("ё", "е")
        return all(all(part in n for part in group) for group in rules)

    filtered = df[df["product_name"].apply(ok)].copy()
    return filtered if not filtered.empty else df

def _rerank_dataframe(df: pd.DataFrame, search: SearchQuery, limit: int) -> pd.DataFrame:
    if df.empty:
        return df

    query_norm = _normalize_token(search.clean)

    def fuzzy_score(name: str) -> int:
        name_norm = _normalize_token(str(name))
        return int(fuzz.partial_ratio(query_norm, name_norm))

    df = df.copy()
    df = _apply_strict_brand_line_filter(df, search)

    model_number = _extract_model_number(search)
    if model_number:
        df["model_number_match"] = df["product_name"].apply(lambda name: _name_has_model_number(str(name), model_number))
        strict_df = df[df["model_number_match"]].copy()
        if not strict_df.empty:
            df = strict_df
    else:
        df["model_number_match"] = False

    df["fuzzy_score"] = df["product_name"].apply(fuzzy_score)

    sort_columns = ["model_number_match", "match_score", "fuzzy_score", "source_priority", "stock_qty"]
    ascending = [False, False, False, True, False]

    return (
        df.sort_values(
            by=sort_columns,
            ascending=ascending,
        )
        .drop_duplicates(subset=["product_name"])
        .head(limit)
    )



def _normalize_stock_qty_for_business(product_name: str, stock_qty: object) -> float | None:
    """Business overrides for known 1C stock edge cases."""
    if pd.isna(stock_qty):
        return None

    name = str(product_name or "").lower().replace("ё", "е")
    qty = float(stock_qty or 0)

    # В 1С руками BAXI ECO 4S 24 / 24F сейчас нули,
    # а сырой регистр иногда возвращает 1 шт.
    if (
        "baxi" in name
        and "eco" in name
        and "4s" in name
        and "24" in name
        and "1.24" not in name
    ):
        return 0.0

    return qty

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
                stock_qty=_normalize_stock_qty_for_business(product_name, row["stock_qty"]),
                purchase_price=None if pd.isna(row["purchase_price"]) else float(row["purchase_price"] or 0),
                stock_total_qty=(
                    None
                    if "stock_total_qty" not in row.index or pd.isna(row.get("stock_total_qty"))
                    else float(row.get("stock_total_qty") or 0)
                ),
                reserved_qty=(
                    None
                    if "reserved_qty" not in row.index or pd.isna(row.get("reserved_qty"))
                    else float(row.get("reserved_qty") or 0)
                ),
                business_available_qty=(
                    None
                    if "business_available_qty" not in row.index or pd.isna(row.get("business_available_qty"))
                    else float(row.get("business_available_qty") or 0)
                ),
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



def _format_stock_breakdown(item: CatalogItem) -> str:
    """Human-readable 1C stock breakdown: total / reserved / free.

    Contract:
    - item.stock_total_qty = total stock from 1C register
    - item.reserved_qty = reserved stock
    - item.stock_qty = free stock
    """
    free_qty = item.stock_qty
    total_qty = getattr(item, "stock_total_qty", None)
    reserved_qty = getattr(item, "reserved_qty", None)

    if total_qty is None and reserved_qty is None:
        if free_qty is None:
            return "📦 Остаток 1С: нет данных"
        if free_qty <= 0:
            return "📦 Остаток 1С: нет в наличии"
        return f"📦 Свободно 1С: {_format_stock_qty(free_qty)}"

    total_qty = float(total_qty or 0)
    reserved_qty = float(reserved_qty or 0)

    # ВАЖНО:
    # Если есть total + reserved, свободный остаток считаем только один раз:
    # free = total - reserved.
    # Не используем item.stock_qty как total, иначе получаем двойное вычитание.
    free_qty = max(total_qty - reserved_qty, 0)

    if total_qty <= 0 and reserved_qty <= 0 and free_qty <= 0:
        return "📦 Остаток 1С: нет в наличии"

    warning = ""
    business_available_qty = getattr(item, "business_available_qty", None)

    if (
        free_qty > 0
        and business_available_qty is not None
        and float(business_available_qty or 0) <= 0
    ):
        warning = (
            "\n⚠️ Возможен фантомный остаток: "
            "в регистре остаток есть, но доступность к резерву в 1С может быть 0. "
            "Сверь карточку."
        )

    return (
        "📦 Остаток 1С:\n"
        f"   Всего: {_format_stock_qty(total_qty)}\n"
        f"   В резерве: {_format_stock_qty(reserved_qty)}\n"
        f"   Свободно: {_format_stock_qty(free_qty)}"
        f"{warning}"
    )

def _stock_and_purchase_labels(stock_qty: float | None) -> tuple[str, str]:
    if stock_qty is None:
        return "📦 В наличии: не подтянут", "💸 Закупка 1С"
    if stock_qty <= 0:
        return "❌ <b>Нет в наличии</b>", "🔴 Последняя закупка 1С"
    return f"📦 Остаток 1С: {_format_stock_qty(stock_qty)}", "💸 Средняя закупка 1С"


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
