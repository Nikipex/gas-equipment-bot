from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from loguru import logger

from app.services.ai.equipment_intent_parser import EquipmentIntent
from app.services.supplier_cache_service import SupplierCacheService
from app.integrations.web.market_discovery_service import MarketDiscoveryService


@dataclass(frozen=True)
class EquipmentCandidate:
    product_name: str
    supplier_name: str
    price: float | None
    stock: float | None
    score: float | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class EquipmentSearchResult:
    query: str
    candidates: list[EquipmentCandidate]
    exact_brand_found: bool = False


class EquipmentSearchPipeline:
    def __init__(self) -> None:
        self.supplier_cache = SupplierCacheService()
        self.market_discovery = MarketDiscoveryService()

    async def search(self, intent: EquipmentIntent, limit: int = 10) -> EquipmentSearchResult:
        query = intent.query_for_supplier_search
        candidates: list[EquipmentCandidate] = []

        try:
            frames = []
            search_queries = await self._build_enriched_search_queries(intent)

            for search_query in search_queries:
                df = self.supplier_cache.search(query=search_query, limit=max(limit * 5, 30))
                if df is not None and not df.empty:
                    frames.append(df)

            if frames:
                df = pd.concat(frames, ignore_index=True).drop_duplicates()
            else:
                df = pd.DataFrame()

            candidates = _dataframe_to_candidates(df)
        except Exception as exc:
            logger.exception("Equipment supplier cache search failed: {}", exc)
            candidates = []

        exact_brand_found = _has_exact_brand(intent, candidates)

        candidates = _filter_candidates(intent, candidates)
        candidates = _rank_candidates(intent, candidates)

        return EquipmentSearchResult(
            query=query,
            candidates=candidates[:limit],
            exact_brand_found=exact_brand_found,
        )


    async def _build_enriched_search_queries(self, intent: EquipmentIntent) -> list[str]:
        queries = list(_build_search_queries(intent))

        # Fast web discovery: find real market model names, then search supplier cache by models.
        try:
            if intent.category in {"boiler", "water_heater", "gas_column", "pump", "radiator"}:
                discovered = await self.market_discovery.discover_models(
                    intent.query_for_supplier_search,
                    limit=8,
                )

                for item in discovered:
                    model_query = getattr(item, "model_query", None) or item.title
                    if model_query:
                        queries.insert(0, model_query)
        except Exception as exc:
            logger.warning("Market discovery skipped: {}", exc)

        result = []
        seen = set()

        for q in queries:
            q = " ".join(str(q).split()).strip()
            if not q:
                continue

            key = q.lower()
            if key in seen:
                continue

            seen.add(key)
            result.append(q)

        return result


def _build_search_queries(intent: EquipmentIntent) -> list[str]:
    queries: list[str] = []

    base = intent.query_for_supplier_search.strip()
    if base:
        queries.append(base)

    brand = intent.brand or ""

    if intent.category == "boiler":
        if brand and intent.power_kw:
            queries.append(f"{brand} {intent.power_kw:g}")
            queries.append(f"{brand} {int(intent.power_kw)}")
            queries.append(f"{brand} {int(intent.power_kw)}F")
            queries.append(f"{brand} F{int(intent.power_kw)}")
            queries.append(f"{brand} котел {int(intent.power_kw)}")
            queries.append(f"{brand} газовый {int(intent.power_kw)}")

        if intent.chamber == "closed":
            queries.append(f"{brand} турбо {int(intent.power_kw or 24)}")
            queries.append(f"{brand} закрытая камера {int(intent.power_kw or 24)}")

        if intent.chamber == "open":
            queries.append(f"{brand} атмо {int(intent.power_kw or 24)}")
            queries.append(f"{brand} открытая камера {int(intent.power_kw or 24)}")

    elif intent.category == "water_heater":
        if brand and intent.volume_l:
            queries.append(f"{brand} {intent.volume_l}")
            queries.append(f"{brand} {intent.volume_l}л")
            queries.append(f"{brand} бойлер {intent.volume_l}")
            queries.append(f"{brand} водонагреватель {intent.volume_l}")

    elif intent.category == "pump":
        if brand:
            queries.append(brand)
        queries.append(intent.raw_text)

    # dedupe preserving order
    result = []
    seen = set()
    for q in queries:
        q = " ".join(str(q).split()).strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            result.append(q)

    return result


def _dataframe_to_candidates(df: pd.DataFrame) -> list[EquipmentCandidate]:
    if df is None or df.empty:
        return []

    result: list[EquipmentCandidate] = []

    for _, row in df.iterrows():
        raw = row.to_dict()

        product_name = _first_value(
            raw,
            [
                "product_name",
                "name",
                "title",
                "Наименование",
                "Номенклатура",
                "Товар",
            ],
        )

        if not product_name:
            continue

        supplier_name = _first_value(
            raw,
            [
                "supplier_name",
                "supplier",
                "Поставщик",
                "source",
            ],
        ) or "unknown"

        price = _to_float(
            _first_value(
                raw,
                [
                    "price",
                    "Цена",
                    "price_value",
                    "supplier_price",
                ],
            )
        )

        stock = _to_float(
            _first_value(
                raw,
                [
                    "stock",
                    "Остаток",
                    "quantity",
                    "qty",
                    "available",
                ],
            )
        )

        score = _to_float(
            _first_value(
                raw,
                [
                    "score",
                    "match_score",
                    "rank_score",
                ],
            )
        )

        result.append(
            EquipmentCandidate(
                product_name=str(product_name),
                supplier_name=str(supplier_name),
                price=price,
                stock=stock,
                score=score,
                raw=raw,
            )
        )

    return result


def _has_exact_brand(
    intent: EquipmentIntent,
    candidates: list[EquipmentCandidate],
) -> bool:
    if not intent.brand:
        return False

    return any(_brand_matches(intent.brand, c.product_name) for c in candidates)


def _filter_candidates(
    intent: EquipmentIntent,
    candidates: list[EquipmentCandidate],
) -> list[EquipmentCandidate]:
    if not candidates:
        return []

    filtered = candidates

    if intent.brand:
        strict = [
            c for c in filtered
            if _brand_matches(intent.brand, c.product_name)
        ]

        # Если нашли брендовые позиции — используем только их.
        # Если не нашли — оставляем широкий recall, чтобы не получить пустоту.
        if strict:
            filtered = strict

    if intent.category == "boiler":
        filtered = [
            c for c in filtered
            if not _is_boiler_accessory(c.product_name)
        ]

        chamber_filtered = [
            c for c in filtered
            if _boiler_chamber_matches(intent.chamber, c.product_name)
        ]

        # Для атмосферных нельзя показывать явные турбо-позиции как fallback.
        # Лучше пусто, чем неправильный подбор.
        if intent.chamber == "open":
            filtered = chamber_filtered
        elif chamber_filtered:
            filtered = chamber_filtered

        model_terms = _model_terms_from_intent(intent)
        model_filtered = [
            c for c in filtered
            if _model_matches_intent(intent, c.product_name)
        ]

        # Если пользователь явно указал серию/модель, не подсовываем другую серию.
        if model_terms:
            filtered = model_filtered
        elif model_filtered:
            filtered = model_filtered

        if intent.circuits:
            circuit_filtered = [
                c for c in filtered
                if _detect_product_circuits(c.product_name) == intent.circuits
            ]

            # Если контурность явно понята из запроса/модели,
            # не подсовываем котел другой контурности.
            filtered = circuit_filtered

        if intent.power_kw:
            power_filtered = [
                c for c in filtered
                if _contains_number_close(_normalize_model_text(c.product_name), intent.power_kw)
            ]

            # Для котлов мощность — жесткий параметр, если есть совпадения.
            if power_filtered:
                filtered = power_filtered

    if intent.category == "water_heater":
        if _is_indirect_water_heater_request(intent):
            filtered = [
                c for c in filtered
                if _looks_like_indirect_water_heater(c.product_name)
            ]

    return filtered


def _is_indirect_water_heater_request(intent: EquipmentIntent) -> bool:
    raw = intent.raw_text.lower().replace("ё", "е")
    query = intent.query_for_supplier_search.lower().replace("ё", "е")
    return "косвен" in raw or "косвен" in query


def _looks_like_indirect_water_heater(name: str) -> bool:
    text = name.lower().replace("ё", "е")

    bad = [
        "электр",
        "тэн",
        "ten",
        "thermo ",
        "titaniumheat",
        "водонагреватель электр",
    ]

    if any(x in text for x in bad):
        return False

    good = [
        "косвен",
        "змеевик",
        "бойлер baxi ub",
        "drazice",
        "hajdu",
        "acv",
        "baxi ub",
        "baxi v",
    ]

    return any(x in text for x in good)


def _brand_matches(brand: str | None, product_name: str) -> bool:
    if not brand:
        return True

    name = product_name.lower().replace("ё", "е")
    brand_norm = brand.lower().replace("ё", "е")

    aliases = {
        "ariston": ["ariston", "аристон"],
        "baxi": ["baxi", "бакси"],
        "navien": ["navien", "навьен", "навиен"],
        "ferroli": ["ferroli", "ферроли"],
        "protherm": ["protherm", "протерм"],
        "bosch": ["bosch", "бош"],
        "buderus": ["buderus", "будерус"],
        "grundfos": ["grundfos", "грундфос"],
        "wilo": ["wilo", "вило"],
        "royal thermo": ["royal thermo", "роял термо"],
        "thermex": ["thermex", "термекс"],
        "stout": ["stout", "стоут"],
    }

    tokens = aliases.get(brand_norm, [brand_norm])
    return any(token in name for token in tokens)


def _boiler_chamber_matches(chamber: str | None, product_name: str) -> bool:
    if not chamber:
        return True

    name = product_name.lower().replace("ё", "е")

    turbo_markers = [
        "турбо",
        "turbo",
        "коакс",
        "coax",
        "закрыт",
        "24f",
        "f24",
        "fi",
    ]

    open_markers = [
        "атмо",
        "atmo",
        "открыт",
        "24i",
        "i24",
    ]

    if chamber == "closed":
        bad_closed = open_markers + ["slim", " in ", " in", "iN".lower(), "дымоход"]
        if any(x in name for x in bad_closed):
            return False
        return any(x in name for x in turbo_markers) or not any(x in name for x in open_markers)

    if chamber == "open":
        # Для атмосферных отсекаем явные турбо-маркеры.
        return not any(x in name for x in turbo_markers)

    return True


def _is_boiler_accessory(name: str) -> bool:
    text = name.lower().replace("ё", "е")
    bad = [
        "дымоход",
        "коаксиал",
        "колено",
        "труба",
        "адаптер",
        "плата",
        "датчик",
        "насос",
        "клапан",
        "форсун",
        "жиклер",
        "комплект",
        "термостат",
        "система удаленного",
        "connect",
        "блок управления",
        "блок уплавления",
        "блок управления",
        "ampera",
        "зонт",
        "вытяжной",
        "вытяжного",
        "впг",
        "водонагреватель",
        "бойлер",
        "бак ",
        "змеевик",
        "тэн",
    ]
    return any(x in text for x in bad)


def _rank_candidates(
    intent: EquipmentIntent,
    candidates: list[EquipmentCandidate],
) -> list[EquipmentCandidate]:
    def score(candidate: EquipmentCandidate) -> tuple[float, float, float]:
        name = candidate.product_name.lower().replace("ё", "е")

        s = candidate.score or 0.0

        if intent.brand and intent.brand.lower() in name:
            s += 100

        if intent.power_kw:
            if _contains_number_close(name, intent.power_kw):
                s += 40
            elif intent.category == "boiler":
                s -= 80

        if intent.volume_l and str(intent.volume_l) in name:
            s += 40

        if intent.chamber == "closed" and any(x in name for x in ["turbo", "турбо", "f24", "24f", "fi"]):
            s += 10

        if intent.circuits == 2 and any(x in name for x in ["двухконт", "2 конт", "24f", "f24"]):
            s += 5

        stock_score = candidate.stock or 0
        price_score = -(candidate.price or 10**12)

        return (s, stock_score, price_score)

    return sorted(candidates, key=score, reverse=True)


def _normalize_model_text(value: str) -> str:
    text = str(value or "").lower().replace("ё", "е")

    aliases = {
        "эко": "eco",
        "еко": "eco",
        "фор": "four",
        "фоур": "four",
        "лайф": "life",
        "нова": "nova",
        "слим": "slim",
        "бакси": "baxi",
        "аристон": "ariston",
        "навьен": "navien",
        "навиен": "navien",
        "ферроли": "ferroli",
    }

    for src, dst in aliases.items():
        text = text.replace(src, dst)

    text = text.replace("-", " ")
    text = text.replace("_", " ")
    text = " ".join(text.split())
    return text


def _model_terms_from_intent(intent: EquipmentIntent) -> list[str]:
    raw = _normalize_model_text(intent.raw_text)
    query = _normalize_model_text(intent.query_for_supplier_search)
    text = f"{raw} {query}"

    terms = []

    patterns = [
        "eco nova",
        "eco life",
        "eco four",
        "eco 4s",
        "main four",
        "luna",
        "slim",
        "deluxe",
        "pro1",
        "abs vls",
        "lydos",
    ]

    for pattern in patterns:
        if pattern in text:
            terms.append(pattern)

    # 24F / F24 / 1.24F
    import re
    for m in re.findall(r"\b(?:1\.)?24\s*f\b|\bf\s*24\b|\b24f\b|\bf24\b", text):
        terms.append(m.replace(" ", ""))

    return list(dict.fromkeys(terms))


def _model_matches_intent(intent: EquipmentIntent, product_name: str) -> bool:
    terms = _model_terms_from_intent(intent)
    if not terms:
        return True

    name = _normalize_model_text(product_name)

    normalized_terms = []
    for term in terms:
        t = _normalize_model_text(term).replace(" ", "")
        normalized_terms.append(t)

    compact_name = name.replace(" ", "")

    # Если пользователь явно указал серию, она должна совпасть.
    series_terms = [t for t in normalized_terms if not any(x in t for x in ["24f", "f24", "1.24f"])]

    # Специальные алиасы сайта/прайса.
    series_aliases = {
        "ecofour": ["ecofour", "eco4", "экоfour", "экофор", "экоfour"],
        "eco4s": ["eco4s", "eco4 s"],
        "econova": ["econova", "eco nova"],
        "ecolife": ["ecolife", "eco life"],
    }

    if series_terms:
        matched = False
        for term in series_terms:
            aliases = series_aliases.get(term, [term])
            if any(alias.replace(" ", "") in compact_name for alias in aliases):
                matched = True
                break

        if not matched:
            return False

    # Если указал 24F/F24, исключаем iN/Slim/атмо и аксессуары.
    if any(x in normalized_terms for x in ["24f", "f24", "1.24f"]):
        if not any(x in compact_name for x in ["24f", "f24", "1.24f"]):
            return False

    return True



def _detect_product_circuits(name: str) -> int | None:
    low = name.lower().replace("ё", "е")

    dual = [
        "двухконтур",
        "2 конт",
        "2х конт",
        "24f",
        "28f",
        "31f",
    ]

    single = [
        "одноконтур",
        "1 конт",
        "1.24f",
        "1.140",
        "1.240",
        "1.280",
    ]

    if any(x in low for x in single):
        return 1

    if any(x in low for x in dual):
        return 2

    return None


def _contains_number_close(text: str, target: float) -> bool:
    import re

    for raw in re.findall(r"\d+(?:[.,]\d+)?", text):
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue

        if abs(value - target) <= 0.75:
            return True

        # 240 / 280 style model numbers
        if value >= 100 and abs((value / 10) - target) <= 0.75:
            return True

    return False


def _first_value(raw: dict[str, Any], keys: list[str]) -> Any | None:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None

    try:
        if isinstance(value, str):
            value = (
                value.replace("\xa0", "")
                .replace(" ", "")
                .replace(",", ".")
                .replace("₽", "")
                .replace("р.", "")
                .replace("руб.", "")
            )
        return float(value)
    except Exception:
        return None
