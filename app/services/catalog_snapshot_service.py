from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from loguru import logger
from sqlalchemy import create_engine


SNAPSHOT_DIR = Path("data/fallback")
SNAPSHOT_PATH = SNAPSHOT_DIR / "catalog_snapshot.csv"
META_PATH = SNAPSHOT_DIR / "catalog_snapshot_meta.json"

SOUTH_WAREHOUSE_GUID = "83ee60f67771497111e9dbb16ec97a48"


@dataclass
class SnapshotCatalogItem:
    product_code: str
    product_name: str
    stock_qty: float
    stock_total_qty: float
    reserved_qty: float
    purchase_price: float | None
    snapshot_created_at: str


class CatalogSnapshotService:
    def build_snapshot(self) -> int:
        database_url = os.getenv("PROCUREMENT_DATABASE_URL")
        if not database_url:
            raise RuntimeError("PROCUREMENT_DATABASE_URL is empty")

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

        engine = create_engine(database_url, pool_pre_ping=True)

        sql = f"""
        WITH total_stock AS (
            SELECT
                s._fld9098rref AS product_id,
                SUM(s._fld9106) AS total_stock_qty,
                SUM(s._fld9107) AS stock_amount
            FROM public._accumrgt9117 s
            WHERE s._fld9099rref = decode('{SOUTH_WAREHOUSE_GUID}','hex')
              AND s._period = TIMESTAMP '3999-11-01 00:00:00'
            GROUP BY s._fld9098rref
        ),
        reserved_stock AS (
            SELECT
                r._fld9301rref AS product_id,
                SUM(GREATEST(COALESCE(r._fld9305, 0), 0)) AS reserved_stock_qty
            FROM public._accumrgt9308 r
            WHERE r._fld9300rref = decode('{SOUTH_WAREHOUSE_GUID}','hex')
              AND r._period = TIMESTAMP '3999-11-01 00:00:00'
            GROUP BY r._fld9301rref
        ),
        stock AS (
            SELECT
                COALESCE(t.product_id, r.product_id) AS product_id,
                COALESCE(t.total_stock_qty, 0) AS total_stock_qty,
                COALESCE(r.reserved_stock_qty, 0) AS reserved_stock_qty,
                GREATEST(
                    COALESCE(t.total_stock_qty, 0) - COALESCE(r.reserved_stock_qty, 0),
                    0
                ) AS free_stock_qty
            FROM total_stock t
            FULL OUTER JOIN reserved_stock r
                ON r.product_id = t.product_id
        ),
        latest_purchase AS (
            SELECT DISTINCT ON (r._fld9098rref)
                r._fld9098rref AS product_id,
                ROUND(r._fld9107 / NULLIF(r._fld9106, 0), 2) AS purchase_price
            FROM public._accumrg9097 r
            WHERE r._active = true
              AND r._recordkind = 0
              AND r._fld9106 <> 0
            ORDER BY r._fld9098rref, r._period DESC
        )
        SELECT
            encode(n._idrref, 'hex') AS product_id_hex,
            n._code::text AS product_code,
            n._description::text AS product_name,
            COALESCE(st.free_stock_qty, 0)::numeric AS stock_qty,
            COALESCE(st.total_stock_qty, 0)::numeric AS stock_total_qty,
            COALESCE(st.reserved_stock_qty, 0)::numeric AS reserved_qty,
            lp.purchase_price::numeric AS purchase_price
        FROM public._reference80 n
        LEFT JOIN stock st
            ON st.product_id = n._idrref
        LEFT JOIN latest_purchase lp
            ON lp.product_id = n._idrref
        WHERE n._marked = false
          AND n._description IS NOT NULL
          AND n._description::text <> ''
        """

        df = pd.read_sql_query(sql, engine)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        df["snapshot_created_at"] = created_at

        tmp_path = SNAPSHOT_PATH.with_suffix(".csv.tmp")
        df.to_csv(tmp_path, index=False)
        tmp_path.replace(SNAPSHOT_PATH)

        meta = {
            "created_at": created_at,
            "rows": int(len(df)),
            "source": "postgres_last_known_good",
        }
        META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info("Catalog snapshot saved: rows={}, path={}", len(df), SNAPSHOT_PATH)
        return int(len(df))

    def search(self, query: str, limit: int = 10) -> list[SnapshotCatalogItem]:
        if not SNAPSHOT_PATH.exists():
            return []

        df = pd.read_csv(SNAPSHOT_PATH)
        if df.empty:
            return []

        tokens = self._tokens(query)
        if not tokens:
            return []

        df = df.copy()
        df["name_norm"] = df["product_name"].astype(str).map(self._norm)
        df["score"] = 0

        for token in tokens:
            df["score"] += df["name_norm"].str.contains(token, regex=False, na=False).astype(int)

        df = df[df["score"] > 0].copy()
        if df.empty:
            return []

        df = df.sort_values(["score", "stock_qty"], ascending=[False, False]).head(limit)

        items: list[SnapshotCatalogItem] = []
        for _, row in df.iterrows():
            purchase_price = row.get("purchase_price")
            if pd.isna(purchase_price):
                purchase_price = None

            items.append(
                SnapshotCatalogItem(
                    product_code=str(row.get("product_code") or ""),
                    product_name=str(row.get("product_name") or ""),
                    stock_qty=float(row.get("stock_qty") or 0),
                    stock_total_qty=float(row.get("stock_total_qty") or 0),
                    reserved_qty=float(row.get("reserved_qty") or 0),
                    purchase_price=None if purchase_price is None else float(purchase_price),
                    snapshot_created_at=str(row.get("snapshot_created_at") or ""),
                )
            )

        return items

    def meta_text(self) -> str:
        if not META_PATH.exists():
            return "snapshot отсутствует"
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
            return f"{meta.get('created_at')} / rows={meta.get('rows')}"
        except Exception:
            return "snapshot meta error"

    @staticmethod
    def _norm(value: object) -> str:
        text = str(value or "").lower().replace("ё", "е")
        text = re.sub(r"[^a-zа-я0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _tokens(cls, value: str) -> list[str]:
        stop = {"котел", "котёл", "газ", "газовый", "радиатор", "насос", "бойлер"}
        return [t for t in cls._norm(value).split() if len(t) >= 2 and t not in stop]


catalog_snapshot_service = CatalogSnapshotService()
