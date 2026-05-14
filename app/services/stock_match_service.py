from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from loguru import logger

from app.schemas.normalized_product import NormalizedProduct


@dataclass(frozen=True, slots=True)
class StockEntry:
    """Одна запись об остатке из 1С."""

    warehouse: str
    product_name: str
    free_stock_qty: float
    product_key: Optional[str] = None


@dataclass(frozen=True, slots=True)
class StockMatchResult:
    """Результат сопоставления одного товара с остатками 1С."""

    product: NormalizedProduct
    matched: bool
    stock_entries: list[StockEntry] = field(default_factory=list)
    match_reason: Optional[str] = None  # "product_key" | "name" | None

    @property
    def total_qty(self) -> float:
        """Суммарный остаток по всем совпавшим строкам."""
        return sum(entry.free_stock_qty for entry in self.stock_entries)

    @property
    def first_warehouse(self) -> Optional[str]:
        """Первый склад из совпавших записей."""
        return self.stock_entries[0].warehouse if self.stock_entries else None

    @property
    def first_stock_name(self) -> Optional[str]:
        """Первое совпавшее имя товара из stock-данных."""
        return self.stock_entries[0].product_name if self.stock_entries else None


class StockMatchService:
    """
    Детерминированный сервис сопоставления товаров с остатками 1С.

    Порядок матчинга:
    1. exact product_key
    2. exact normalized name
    3. иначе нет совпадения
    """

    def __init__(self, stock_df: pd.DataFrame):
        self._stock_df = stock_df.copy()
        self._key_index: dict[str, list[StockEntry]] = {}
        self._name_index: dict[str, list[StockEntry]] = {}
        self._built: bool = False

    def build_index(self) -> None:
        """
        Строит индексы по product_key и product_name.

        Ожидаемые колонки в DataFrame:
        - warehouse
        - product_name
        - free_stock_qty
        - product_key
        """
        required_cols = {"warehouse", "product_name", "free_stock_qty", "product_key"}
        if not required_cols.issubset(self._stock_df.columns):
            missing = required_cols - set(self._stock_df.columns)
            raise ValueError(f"Отсутствуют обязательные колонки в stock DataFrame: {missing}")

        self._key_index.clear()
        self._name_index.clear()

        for _, row in self._stock_df.iterrows():
            warehouse = self._safe_str(row.get("warehouse"))
            product_name = self._safe_str(row.get("product_name"))
            free_stock_qty = self._safe_qty(row.get("free_stock_qty"))
            product_key = self._normalize_key(row.get("product_key"))

            entry = StockEntry(
                warehouse=warehouse,
                product_name=product_name,
                free_stock_qty=free_stock_qty,
                product_key=product_key or None,
            )

            if entry.product_key:
                self._key_index.setdefault(entry.product_key, []).append(entry)

            normalized_name = self._normalize_text(entry.product_name)
            if normalized_name:
                self._name_index.setdefault(normalized_name, []).append(entry)

        self._built = True
        logger.info(
            "StockMatchService: индексы построены (keys={}, names={}, rows={})",
            len(self._key_index),
            len(self._name_index),
            len(self._stock_df),
        )

    def is_ready(self) -> bool:
        """Проверяет, готов ли сервис к поиску."""
        return self._built

    def get_stock_for_product(self, product: NormalizedProduct) -> StockMatchResult:
        """
        Находит остатки для одного товара.

        Сначала ищет по product_key, затем по exact normalized name.
        """
        if not self._built:
            raise RuntimeError("Stock index not built. Сначала вызови build_index().")

        supplier_key = self.build_supplier_product_key(product)
        supplier_name = self._normalize_text(
            getattr(product, "name", "") or getattr(product, "name_normalized", "")
        )

        # 1. Поиск по product_key
        if supplier_key:
            if entries := self._key_index.get(supplier_key):
                logger.debug(
                    "Stock match by key '{}' for '{}'",
                    supplier_key,
                    getattr(product, "name", "<unknown>"),
                )
                return StockMatchResult(
                    product=product,
                    matched=True,
                    stock_entries=entries,
                    match_reason="product_key",
                )

        # 2. Поиск по нормализованному имени
        if supplier_name:
            if entries := self._name_index.get(supplier_name):
                logger.debug(
                    "Stock match by name '{}' for '{}'",
                    supplier_name,
                    getattr(product, "name", "<unknown>"),
                )
                return StockMatchResult(
                    product=product,
                    matched=True,
                    stock_entries=entries,
                    match_reason="name",
                )

        # 3. Нет совпадения
        logger.debug(
            "No stock match for '{}' (key='{}')",
            getattr(product, "name", "<unknown>"),
            supplier_key,
        )
        return StockMatchResult(
            product=product,
            matched=False,
            stock_entries=[],
            match_reason=None,
        )

    def match_products(self, products: list[NormalizedProduct]) -> list[StockMatchResult]:
        """Массовое сопоставление списка товаров с остатками."""
        if not self._built:
            raise RuntimeError("Stock index not built. Сначала вызови build_index().")

        logger.info("StockMatchService: старт массового матчинга (products={})", len(products))
        results = [self.get_stock_for_product(product) for product in products]
        matched_count = sum(1 for result in results if result.matched)
        logger.info(
            "StockMatchService: матчинг завершён ({}/{})",
            matched_count,
            len(results),
        )
        return results

    @staticmethod
    def build_supplier_product_key(product: NormalizedProduct) -> str:
        """
        Строит supplier-side ключ для сопоставления со stock product_key.

        Приоритет:
        1. name_normalized
        2. name
        """
        raw_value = getattr(product, "name_normalized", None) or getattr(product, "name", "")
        return StockMatchService._normalize_key(raw_value)

    @staticmethod
    def _normalize_text(text: object) -> str:
        """Нормализация имени для exact deterministic comparison."""
        if text is None:
            return ""

        value = str(text).strip().lower().replace("ё", "е")
        value = " ".join(value.split())
        return value

    @staticmethod
    def _normalize_key(value: object) -> str:
        """
        Нормализация product_key.

        Делаем совместимой с ключами из stock_parser:
        - trim
        - lowercase
        - ё -> е
        - collapse spaces
        """
        if value is None:
            return ""

        normalized = str(value).strip().lower().replace("ё", "е")
        normalized = " ".join(normalized.split())
        return normalized

    @staticmethod
    def _safe_str(value: object) -> str:
        """Безопасно превращает значение в строку."""
        if value is None or pd.isna(value):
            return ""
        return str(value).strip()

    @staticmethod
    def _safe_qty(value: object) -> float:
        """Безопасно превращает значение остатка в число."""
        if value is None or pd.isna(value):
            return 0.0

        try:
            return float(value)
        except (TypeError, ValueError):
            try:
                cleaned = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
                return float(cleaned)
            except (TypeError, ValueError):
                return 0.0