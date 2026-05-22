from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd
from rapidfuzz import fuzz


@dataclass(frozen=True)
class SupplierOffer:
    product_name: str
    supplier: str
    price: float | None
    stock: float | None
    score: float


class SelectorSupplierMatcher:
    def __init__(self, cache_path: str = "data/supplier_prices/processed/supplier_products.csv") -> None:
        self.df = pd.read_csv(cache_path)
        self.df["__norm"] = self.df["product_name"].fillna("").astype(str).map(self.normalize)

    def search(self, product_name: str, limit: int = 10) -> list[SupplierOffer]:
        query = self.normalize(product_name)

        if _is_too_generic_selector_title(query):
            return []

        offers: list[SupplierOffer] = []

        for _, row in self.df.iterrows():
            raw_name = str(row.get("product_name", ""))
            candidate = row["__norm"]

            if _is_accessory(candidate):
                continue

            if not _brand_compatible(query, candidate):
                continue

            score = max(
                fuzz.token_set_ratio(query, candidate),
                fuzz.partial_ratio(query, candidate),
            ) / 100

            if score < 0.70:
                continue

            offers.append(
                SupplierOffer(
                    product_name=raw_name,
                    supplier=str(row.get("supplier_key", "unknown")),
                    price=_to_float_or_none(row.get("price")),
                    stock=_to_float_or_none(row.get("stock")),
                    score=score,
                )
            )

        offers.sort(key=lambda x: (x.score, x.stock or 0, -(x.price or 10**12)), reverse=True)
        return offers[:limit]

    @staticmethod
    def normalize(text: str) -> str:
        text = str(text).lower().replace("ё", "е")

        aliases = {
            "бакси": "baxi",
            "бош": "bosch",
            "аристон": "ariston",
            "навьен": "navien",
            "фондитал": "fondital",
            "вайлант": "vaillant",
            "протерм": "protherm",
            "виссман": "viessmann",
            "висман": "viessmann",
            "котел": "",
            "котёл": "",
            "настенный": "",
            "газовый": "",
            "турбо": "",
            "двухконтурный": "",
            "одноконтурный": "",
            "без трубы": "",
            "без": "",
            "трубы": "",
        }

        for src, dst in aliases.items():
            text = text.replace(src, dst)

        text = re.sub(r"[^a-zа-я0-9]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        return text


def _is_too_generic_selector_title(query: str) -> bool:
    tokens = query.split()
    return len(tokens) <= 1 or "котельные" in query


def _is_accessory(candidate: str) -> bool:
    markers = (
        "коакс", "дымоход", "антилед", "отвод", "колено", "переход",
        "адаптер", "труба", "хомут", "втулка", "муфта", "датчик",
        "плата", "насос", "кран", "фильтр", "запчаст", "комплект",
        "жиклер", "форсунк",
    )
    return any(marker in candidate for marker in markers)


def _brand_compatible(query: str, candidate: str) -> bool:
    brands = {
        "baxi", "bosch", "ariston", "navien",
        "fondital", "vaillant", "protherm", "viessmann",
    }

    query_brand = next((brand for brand in brands if brand in query), None)

    if not query_brand:
        return True

    return query_brand in candidate


def _to_float_or_none(value):
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None
