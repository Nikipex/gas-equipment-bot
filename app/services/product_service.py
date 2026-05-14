from loguru import logger

from app.repositories.product_repository import ProductRepository


class ProductService:
    """Сервис для бизнес-логики поиска товаров."""

    def __init__(self, repository: ProductRepository):
        self.repository = repository

    def search(self, query: str, limit: int = 5) -> list[dict]:
        if not query or not query.strip():
            logger.warning("Пустой поисковый запрос")
            return []

        logger.info(f"Поиск товаров по запросу: '{query}'")
        results = self.repository.search_by_name(query, limit=limit)

        if results:
            logger.info(f"Найдено {len(results)} товаров")
        else:
            logger.info("Товары не найдены")

        return results

    def format_results(self, products: list[dict]) -> str:
        if not products:
            return "❌ Ничего не найдено"

        lines = ["🔎 <b>Найдено:</b>"]
        for idx, product in enumerate(products, 1):
            name = product.get("product_name", "Без названия")
            brand = product.get("brand", "")
            category = product.get("category", "")

            line = f"{idx}. {name}"
            if brand:
                line += f" <i>({brand})</i>"
            if category:
                line += f" — <b>{category}</b>"

            lines.append(line)

        return "\n".join(lines)