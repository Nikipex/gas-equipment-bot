from __future__ import annotations

from pathlib import Path
from threading import Lock

from loguru import logger

from app.integrations.one_c.stock_parser import parse_1c_stock_report
from app.services.import_service import ImportService
from app.services.pricing_service import PricingService

_SUPPLIER_FILE = Path("data/demo/supplier_sample_real.xlsx")
_STOCK_FILE = Path("data/raw/Анализ доступности товаров на складах.xlsx")

_lock = Lock()
_cached_pricing_service: PricingService | None = None


def get_pricing_service(force_reload: bool = False) -> PricingService:
    global _cached_pricing_service

    with _lock:
        if _cached_pricing_service is not None and not force_reload:
            return _cached_pricing_service

        if not _SUPPLIER_FILE.exists():
            raise FileNotFoundError(
                f"Не найден supplier-файл: {_SUPPLIER_FILE}. "
                f"Сначала создай его через build_supplier_sample_from_stock.py"
            )

        products = ImportService().import_file(_SUPPLIER_FILE)

        stock_df = None
        if _STOCK_FILE.exists():
            stock_df = parse_1c_stock_report(_STOCK_FILE)
            logger.info(
                "runtime_catalog: stock file loaded (rows={})",
                len(stock_df),
            )
        else:
            logger.warning("runtime_catalog: stock file not found: {}", _STOCK_FILE)

        _cached_pricing_service = PricingService(products, stock_df=stock_df)

        logger.info(
            "runtime_catalog: PricingService ready (products={})",
            len(products),
        )
        return _cached_pricing_service


def reload_pricing_service() -> PricingService:
    return get_pricing_service(force_reload=True)