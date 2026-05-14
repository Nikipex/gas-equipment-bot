from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger


class ProductRepository:
    """Репозиторий для работы с товарами из CSV."""

    def __init__(self, csv_path: Optional[str] = None):
        self.csv_path = Path(csv_path) if csv_path else Path("data/demo/products.csv")
        self._df: Optional[pd.DataFrame] = None
        self._load()

    def _load(self) -> None:
        """Загружает CSV в DataFrame."""
        try:
            self._df = pd.read_csv(self.csv_path, encoding="utf-8")
            logger.info(f"Загружено {len(self._df)} товаров из {self.csv_path}")
        except FileNotFoundError:
            logger.error(f"CSV файл не найден: {self.csv_path}")
            self._df = pd.DataFrame(columns=["product_key", "product_name", "brand", "category"])
        except Exception as e:
            logger.error(f"Ошибка загрузки CSV: {e}")
            self._df = pd.DataFrame(columns=["product_key", "product_name", "brand", "category"])

    def reload(self) -> None:
        self._load()

    def search_by_name(self, query: str, limit: int = 5) -> list[dict]:
        """Поиск товаров по названию."""
        if self._df is None or self._df.empty:
            return []

        normalized_query = self._normalize(query)

        df_search = self._df.copy()
        df_search["product_name_norm"] = df_search["product_name"].astype(str).apply(self._normalize)

        mask = df_search["product_name_norm"].str.contains(normalized_query, na=False, regex=False)
        results = df_search[mask].head(limit)

        return results[["product_key", "product_name", "brand", "category"]].to_dict(orient="records")

    @staticmethod
    def _normalize(text: str) -> str:
        if not text:
            return ""
        return str(text).strip().lower().replace("ё", "е")