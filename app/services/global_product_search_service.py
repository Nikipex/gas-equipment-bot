from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus


@dataclass(frozen=True)
class GlobalSearchResult:
    title: str
    url: str
    description: str


class GlobalProductSearchService:
    def search(self, query: str) -> list[GlobalSearchResult]:
        clean = " ".join(str(query or "").split())
        if not clean:
            return []

        return [
            GlobalSearchResult(
                title="Яндекс: товар + характеристики",
                url=f"https://yandex.ru/search/?text={quote_plus(clean + ' купить характеристики')}",
                description="Магазины, карточки и характеристики.",
            ),
            GlobalSearchResult(
                title="Яндекс Картинки",
                url=f"https://yandex.ru/images/search?text={quote_plus(clean)}",
                description="Фото, внешний вид, шильдик, карточки товара.",
            ),
            GlobalSearchResult(
                title="Инструкции / паспорта",
                url=f"https://yandex.ru/search/?text={quote_plus(clean + ' инструкция паспорт pdf')}",
                description="PDF, паспорта, монтажные схемы.",
            ),
            GlobalSearchResult(
                title="Рыночная цена",
                url=f"https://yandex.ru/search/?text={quote_plus(clean + ' цена купить')}",
                description="Ориентир по рынку.",
            ),
        ]
