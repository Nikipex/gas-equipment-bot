from __future__ import annotations

from loguru import logger

from app.services.passport_registry_service import passport_registry_service
from app.services.postgres_catalog_service import PostgresCatalogService


class StockAwareAnalogsService:
    def __init__(self) -> None:
        self.catalog = PostgresCatalogService()

    def build_context(self, question: str, limit: int = 5) -> str:
        try:
            analogs = passport_registry_service.find_analogs_for_question(question, limit=limit)
            if not analogs:
                return ""

            lines = ["# Stock-Aware Analogs Context"]
            lines.append("")
            lines.append("Похожие модели с проверкой по PostgreSQL-каталогу:")
            lines.append("")

            for idx, item in enumerate(analogs, start=1):
                query = self._search_query(item)
                catalog_results = self.catalog.search(query, limit=3)

                lines.append(f"## {idx}. {item.get('brand')} {item.get('model')}")
                lines.append(
                    f"Параметры из registry: "
                    f"{item.get('power_kw')} кВт, "
                    f"контуры={item.get('circuits')}, "
                    f"камера={item.get('chamber')}, "
                    f"установка={item.get('installation')}"
                )

                if not catalog_results:
                    lines.append("Каталог/остатки: не найдено в PostgreSQL search.")
                    lines.append("")
                    continue

                lines.append("Найдено в каталоге:")
                for r in catalog_results:
                    lines.append(
                        f"- {r.product_name}; "
                        f"остаток={r.stock_qty}; "
                        f"всего={r.stock_total_qty}; "
                        f"резерв={r.reserved_qty}; "
                        f"закупка={r.purchase_price}"
                    )

                lines.append("")

            lines.append(
                "Важно: если у аналога остаток 0 или товар не найден в PostgreSQL, "
                "не утверждай, что он доступен. Пиши, что наличие нужно проверить."
            )

            return "\n".join(lines)

        except Exception as exc:
            logger.exception("Stock-aware analogs failed: {}", exc)
            return ""

    @staticmethod
    def _search_query(item: dict) -> str:
        return " ".join(
            str(x).strip()
            for x in [item.get("brand"), item.get("model")]
            if x
        )


stock_aware_analogs_service = StockAwareAnalogsService()
