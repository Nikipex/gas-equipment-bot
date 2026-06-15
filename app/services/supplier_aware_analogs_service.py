from __future__ import annotations

from loguru import logger

from app.services.passport_registry_service import passport_registry_service
from app.services.supplier_cache_service import supplier_cache_service


class SupplierAwareAnalogsService:
    def build_context(self, question: str, limit: int = 5) -> str:
        try:
            analogs = passport_registry_service.find_analogs_for_question(question, limit=limit)
            if not analogs:
                return ""

            lines = ["# Supplier-Aware Analogs Context"]
            lines.append("")
            lines.append("Похожие модели с проверкой по supplier cache / прайсам поставщиков:")
            lines.append("")

            for idx, item in enumerate(analogs, start=1):
                query = self._search_query(item)
                lines.append(f"## {idx}. {item.get('brand')} {item.get('model')}")
                lines.append(
                    f"Параметры registry: "
                    f"{item.get('power_kw')} кВт, "
                    f"контуры={item.get('circuits')}, "
                    f"камера={item.get('chamber')}, "
                    f"установка={item.get('installation')}"
                )

                try:
                    df = supplier_cache_service.search(query=query, limit=5)
                except TypeError:
                    df = supplier_cache_service.search(query, limit=5)

                if df is None or df.empty:
                    lines.append("Поставщики: не найдено в supplier cache.")
                    lines.append("")
                    continue

                lines.append("Найдено у поставщиков:")

                for _, row in df.head(5).iterrows():
                    supplier = self._first_existing(row, ["supplier", "supplier_key", "supplier_name", "Поставщик"])
                    name = self._first_existing(row, ["name", "product_name", "Наименование", "Товар"])
                    price = self._first_existing(row, ["price", "purchase_price", "Цена", "Закупка"])
                    stock = self._first_existing(row, ["stock", "stock_qty", "quantity", "Остаток", "Наличие"])

                    lines.append(
                        f"- поставщик={supplier or 'не указан'}; "
                        f"товар={name or 'не указан'}; "
                        f"остаток/наличие={stock or 'нет данных'}; "
                        f"цена={price or 'нет данных'}"
                    )

                lines.append("")

            lines.append(
                "Важно: supplier cache не равен подтвержденному резерву. "
                "Если товар найден у поставщика, пиши 'можно проверить у поставщика', а не 'точно доступен'."
            )

            return "\n".join(lines)

        except Exception as exc:
            logger.exception("Supplier-aware analogs failed: {}", exc)
            return ""

    @staticmethod
    def _search_query(item: dict) -> str:
        return " ".join(
            str(x).strip()
            for x in [item.get("brand"), item.get("model")]
            if x
        )

    @staticmethod
    def _first_existing(row, keys: list[str]):
        for key in keys:
            if key in row and row.get(key) is not None:
                value = row.get(key)
                if str(value).strip() and str(value).lower() != "nan":
                    return value
        return None


supplier_aware_analogs_service = SupplierAwareAnalogsService()
