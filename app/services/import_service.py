"""Import pipeline — orchestrates file reading, detection, mapping
and normalisation into a list of :class:`NormalizedProduct`.

This service is the single entry point for ingesting external data
(Excel / CSV files) into the system.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from app.integrations.excel.detector import detect_columns
from app.integrations.excel.mapper import map_to_canonical
from app.integrations.excel.reader import clean_dataframe, read_excel
from app.schemas.normalized_product import NormalizedProduct
from app.utils.normalization import clean_product_name, extract_brand


class ImportService:
    """Pipeline: file → reader → detector → mapper → normalisation.

    Usage::

        svc = ImportService()
        products = svc.import_file("data/raw/supplier.xlsx")
    """

    def import_file(self, file_path: str | Path) -> list[NormalizedProduct]:
        """Run the full import pipeline on a single file.

        Args:
            file_path: Path to an ``.xlsx`` or ``.csv`` file.

        Returns:
            List of normalised :class:`NormalizedProduct` instances.

        Raises:
            FileNotFoundError: If *file_path* does not exist.
            ValueError: If the file format is unsupported.
        """
        logger.info("=== Импорт файла: {} ===", file_path)

        # 1. Read raw data
        raw_df = read_excel(file_path)

        # 2. Clean
        clean_df = clean_dataframe(raw_df)

        # 3. Detect column mapping
        column_map = detect_columns(clean_df)

        # 4. Map to canonical dicts
        records = map_to_canonical(clean_df, column_map)

        # 5. Build NormalizedProduct list
        products = self._normalise_records(records)

        logger.info("=== Импорт завершён: {} товаров ===", len(products))
        return products

    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_records(
        records: list[dict],  # type: ignore[type-arg]
    ) -> list[NormalizedProduct]:
        """Convert raw dicts into validated NormalizedProduct instances."""
        products: list[NormalizedProduct] = []

        for raw in records:
            name: str = raw.get("name") or ""
            if not name:
                continue

            brand = raw.get("brand") or extract_brand(name)
            name_normalized = clean_product_name(name, brand=brand)

            product = NormalizedProduct(
                name=name,
                name_normalized=name_normalized,
                brand=brand,
                category=raw.get("category"),
                sku=raw.get("sku"),
                price=raw.get("price"),
                stock=raw.get("stock"),
            )
            products.append(product)

        return products
