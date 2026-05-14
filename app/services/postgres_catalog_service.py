"""Readonly PostgreSQL catalog service for 1C procurement/search marts."""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import create_engine


DEFAULT_DATABASE_URL = "postgresql+psycopg2://nikitos:123456@127.0.0.1:5433/torg_full"


@dataclass
class CatalogItem:
    product_name: str
    product_group: str
    stock_qty: float | None
    purchase_price: float | None = None
    is_alternative: bool = False


class PostgresCatalogService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = (
            database_url
            or os.getenv("PROCUREMENT_DATABASE_URL")
            or DEFAULT_DATABASE_URL
        )
        self.engine = create_engine(self.database_url)

    def search(self, query: str, limit: int = 10) -> list[CatalogItem]:
        query = query.strip()
        raw_tokens = [t.lower() for t in re.split(r"\s+", query) if len(t) >= 2]

        token_aliases = {
            "низ": "ниж",
            "ниж": "ниж",
            "нижн": "ниж",
            "нижнее": "ниж",
            "нижний": "ниж",
            "подключение": "подкл",
            "подкл": "подкл",
        }

        tokens = [token_aliases.get(t, t) for t in raw_tokens]

        if not tokens:
            return []

        params: dict[str, object] = {"limit": limit}

        for i, token in enumerate(tokens):
            params[f"q{i}"] = f"%{token}%"

        min_match_score = 2 if len(tokens) >= 2 else 1

        numeric_tokens = [t for t in tokens if t.isdigit()]
        has_radiator_query = any(t.startswith("радиатор") for t in tokens)

        def numeric_strict_expr(name_col: str) -> str:
            if not numeric_tokens:
                return "1=1"

            parts = []
            for i, token in enumerate(tokens):
                if token.isdigit():
                    key = f"q{i}"
                    # ВАЖНО: только named params, без сырых '%300%'
                    parts.append(f"{name_col} ILIKE %({key})s")

            return " AND ".join(parts) if parts else "1=1"

        strict_dash = numeric_strict_expr("d.product_name") if has_radiator_query else "1=1"
        strict_rad = numeric_strict_expr("r.product_name") if has_radiator_query else "1=1"
        strict_stock = numeric_strict_expr("s.product_name") if has_radiator_query else "1=1"
        strict_ref = numeric_strict_expr("n._description") if has_radiator_query else "1=1"

        def score_expr(name_col: str, code_col: str) -> str:
            parts: list[str] = []
            for i, token in enumerate(tokens):
                key = f"q{i}"

                # Числа типа 24/13/30 не ищем в коде товара,
                # иначе будут ложные совпадения по артикулам.
                if token.isdigit():
                    parts.append(
                        f"CASE WHEN {name_col} ILIKE %({key})s THEN 1 ELSE 0 END"
                    )
                else:
                    parts.append(
                        f"CASE WHEN {name_col} ILIKE %({key})s "
                        f"OR {code_col} ILIKE %({key})s THEN 1 ELSE 0 END"
                    )

            return " + ".join(parts)

        score_dash = score_expr("d.product_name", "d.product_code")
        score_rad = score_expr("r.product_name", "r.product_code")
        score_stock = score_expr("s.product_name", "s.product_code")
        score_ref = score_expr("n._description", "n._code")

        sql = f"""
            WITH purchase_prices AS (
                SELECT
                    product_id_hex,
                    purchase_price
                FROM public.latest_purchase_prices
            ),

            dashboard AS (
                SELECT
                    d.product_name,
                    d.product_code,
                    d.product_id_hex,
                    d.product_group,
                    d.stock_qty,
                    pp.purchase_price,
                    ({score_dash}) AS match_score,
                    1 AS source_priority
                FROM public.procurement_south_dashboard d
                LEFT JOIN purchase_prices pp
                    ON pp.product_id_hex = d.product_id_hex
                WHERE ({score_dash}) >= {min_match_score}
                  AND ({strict_dash})
            ),

            radiators AS (
                SELECT
                    r.product_name,
                    r.product_code,
                    r.product_id_hex,
                    'радиаторы' AS product_group,
                    r.free_stock_qty AS stock_qty,
                    pp.purchase_price,
                    ({score_rad}) AS match_score,
                    2 AS source_priority
                FROM public.radiator_procurement_mvp r
                LEFT JOIN purchase_prices pp
                    ON pp.product_id_hex = r.product_id_hex
                WHERE ({score_rad}) >= {min_match_score}
                  AND ({strict_rad})
            ),

            south_stock AS (
                SELECT
                    s.product_name,
                    s.product_code,
                    encode(n_s._idrref, 'hex') AS product_id_hex,
                    COALESCE(d.product_group, 'не классифицировано') AS product_group,

                    s.stock_qty AS stock_qty,

                    pp.purchase_price,
                    ({score_stock}) AS match_score,
                    3 AS source_priority
                FROM public.stock_south_warehouse_agg s
                LEFT JOIN public._reference80 n_s
                    ON n_s._code = s.product_code
                LEFT JOIN public.procurement_south_dashboard d
                    ON d.product_code = s.product_code
                LEFT JOIN purchase_prices pp
                    ON pp.product_id_hex = encode(n_s._idrref, 'hex')
                WHERE ({score_stock}) >= {min_match_score}
                  AND ({strict_stock})
            ),

            live_ref AS (
                SELECT
                    n._description AS product_name,
                    n._code AS product_code,
                    encode(n._idrref, 'hex') AS product_id_hex,
                    COALESCE(d.product_group, 'не классифицировано') AS product_group,
                    d.stock_qty,
                    pp.purchase_price,
                    ({score_ref}) AS match_score,
                    4 AS source_priority
                FROM public._reference80 n
                LEFT JOIN public.procurement_south_dashboard d
                    ON d.product_code = n._code
                LEFT JOIN purchase_prices pp
                    ON pp.product_id_hex = encode(n._idrref, 'hex')
                WHERE COALESCE(n._folder, false) = false
                  AND char_length(trim(COALESCE(n._description, ''))) > 5
                  AND ({score_ref}) >= {min_match_score}
                  AND ({strict_ref})
            ),

            unioned AS (
                SELECT * FROM dashboard
                UNION ALL
                SELECT * FROM radiators
                UNION ALL
                SELECT * FROM south_stock
                UNION ALL
                SELECT * FROM live_ref
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
                purchase_price
            FROM dedup
            WHERE rn = 1
            ORDER BY
                match_score DESC,
                source_priority,
                COALESCE(stock_qty, 0) DESC,
                product_name
            LIMIT %(limit)s
        """

        df = pd.read_sql(sql, self.engine, params=params)

        if df.empty and has_radiator_query:
            alternatives = self._search_radiator_alternatives(tokens, limit=4)
            if alternatives:
                return alternatives

        return [
            CatalogItem(
                product_name=str(row["product_name"]),
                product_group=str(row["product_group"]),
                stock_qty=None if pd.isna(row["stock_qty"]) else float(row["stock_qty"] or 0),
                purchase_price=None if pd.isna(row["purchase_price"]) else float(row["purchase_price"] or 0),
                is_alternative=True,
            )
            for _, row in df.iterrows()
        ]

    def _search_radiator_alternatives(self, tokens: list[str], limit: int = 4) -> list[CatalogItem]:
        """Fallback: if exact radiator is absent, return closest in-stock sizes."""

        nums = [int(t) for t in tokens if t.isdigit()]
        if not nums:
            return []

        radiator_types = {10, 11, 20, 21, 22, 30, 33}
        radiator_heights = {200, 300, 500, 600, 900}

        radiator_type = next((n for n in nums if n in radiator_types), None)
        radiator_height = next((n for n in nums if n in radiator_heights), None)
        radiator_length = max((n for n in nums if n >= 400), default=None)

        if radiator_height is None or radiator_length is None:
            return []

        need_low = any(t in {"низ", "ниж", "нижн", "нижнее", "нижний", "подкл"} for t in tokens)

        type_filter = ""
        params: dict[str, object] = {
            "limit": limit,
            "height": str(radiator_height),
            "target_length": radiator_length,
            "low_pattern": "%ниж%",
        }

        if radiator_type is not None:
            type_filter = "AND m[2] = %(radiator_type)s"
            params["radiator_type"] = str(radiator_type)

        low_filter = "AND lower(product_name) ILIKE %(low_pattern)s" if need_low else ""

        sql = f"""
            WITH purchase_prices AS (
                SELECT
                    product_id_hex,
                    purchase_price
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
                WHERE lower(s.product_name) ILIKE '%%радиатор%%'
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

        return [
            CatalogItem(
                product_name=str(row["product_name"]),
                product_group=str(row["product_group"]),
                stock_qty=None if pd.isna(row["stock_qty"]) else float(row["stock_qty"] or 0),
                purchase_price=None if pd.isna(row["purchase_price"]) else float(row["purchase_price"] or 0),
                is_alternative=True,
            )
            for _, row in df.iterrows()
        ]


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
        for i, item in enumerate(items, start=1):
            safe_name = html.escape(item.product_name)
            stock_qty = item.stock_qty

            if stock_qty is None:
                stock_text = "📦 В наличии: не подтянут"
                purchase_label = "💸 Закупка 1С"
            elif stock_qty <= 0:
                stock_text = "❌ <b>Нет в наличии</b>"
                purchase_label = "🔴 Последняя закупка 1С"
            else:
                stock_text = f"📦 В наличии: {_format_stock_qty(stock_qty)}"
                purchase_label = "💸 Закупка 1С"

            lines.append(
                f"<b>{i}. {safe_name}</b>\n"
                f"{stock_text}\n"
                f"{purchase_label}: {_format_price(item.purchase_price)}"
            )

        return "\n\n".join(lines)


def _format_stock_qty(value: float | None) -> str:
    if value is None:
        return "не подтянут"
    return f"{value:g} шт"


def _format_price(value: float | None) -> str:
    if value is None or value <= 0:
        return "не подтянута"
    return f"{value:,.0f} ₽".replace(",", " ")
