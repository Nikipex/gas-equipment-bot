from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from loguru import logger

from app.services.ai.equipment_intent_parser import EquipmentIntent
from app.services.supplier_cache_service import SupplierCacheService
from app.services.equipment.enriched_supplier_search_service import EnrichedSupplierSearchService
from app.integrations.web.market_discovery_service import MarketDiscoveryService


@dataclass(frozen=True)
class EquipmentCandidate:
    product_name: str
    supplier_name: str
    price: float | None
    stock: float | None
    score: float | None = None
    raw: dict[str, Any] | None = None
    relaxation_reason: str | None = None


@dataclass(frozen=True)
class EquipmentSearchResult:
    query: str
    candidates: list[EquipmentCandidate]
    fallback_candidates: list[EquipmentCandidate] | None = None
    exact_brand_found: bool = False


class EquipmentSearchPipeline:
    def __init__(self) -> None:
        self.supplier_cache = SupplierCacheService()
        self.enriched_search = EnrichedSupplierSearchService()
        self.market_discovery = MarketDiscoveryService()

    async def search(self, intent: EquipmentIntent, limit: int = 10) -> EquipmentSearchResult:
        query = intent.query_for_supplier_search
        candidates: list[EquipmentCandidate] = []

        try:
            enriched_df = self.enriched_search.search(intent, limit=max(limit * 3, 30))

            if enriched_df is not None and not enriched_df.empty:
                candidates = _dataframe_to_candidates(enriched_df)
                exact_brand_found = _has_exact_brand(intent, candidates)

                return EquipmentSearchResult(
                    query=query,
                    candidates=candidates[:limit],
                    fallback_candidates=[],
                    exact_brand_found=exact_brand_found,
                )

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

        strict_candidates = _filter_candidates(intent, candidates)
        strict_candidates = _rank_candidates(intent, strict_candidates)

        fallback_candidates: list[EquipmentCandidate] = []

        if not strict_candidates:
            fallback_candidates = _build_relaxed_fallback_candidates(intent, candidates)
            fallback_candidates = _rank_candidates(intent, fallback_candidates)

        return EquipmentSearchResult(
            query=query,
            candidates=strict_candidates[:limit],
            fallback_candidates=fallback_candidates[:limit],
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
        if getattr(intent, "boiler_type", None) == "parapet":
            power = int(intent.power_kw or 10)
            queries.append(f"парапетный котел {power}")
            queries.append(f"котел парапетный {power}")
            queries.append(f"АОГВ {power}")
            queries.append(f"КСГ {power}")
            queries.append(f"TGV {power}")

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
        volume = intent.volume_l or intent.volume_min_l or intent.volume_max_l

        if brand and volume:
            queries.append(f"{brand} {volume}")
            queries.append(f"{brand} {volume}л")
            queries.append(f"{brand} бойлер {volume}")
            queries.append(f"{brand} водонагреватель {volume}")

        if intent.water_heater_type == "indirect":
            for q in [
                f"бойлер косвенного нагрева {volume or ''}",
                f"косвенный бойлер {volume or ''}",
                f"Drazice {volume or ''}",
                f"Hajdu {volume or ''}",
                f"Baxi UB {volume or ''}",
                f"Baxi V {volume or ''}",
            ]:
                queries.append(q)

        if intent.water_heater_type == "tank_in_tank":
            for q in [
                f"бак в баке {volume or ''}",
                f"ACV {volume or ''}",
                f"ACV Smart {volume or ''}",
                f"ACV Comfort {volume or ''}",
            ]:
                queries.append(q)

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


def _with_relaxation_reason(
    candidates: list[EquipmentCandidate],
    reason: str,
) -> list[EquipmentCandidate]:
    return [
        EquipmentCandidate(
            product_name=c.product_name,
            supplier_name=c.supplier_name,
            price=c.price,
            stock=c.stock,
            score=c.score,
            raw=c.raw,
            relaxation_reason=reason,
        )
        for c in candidates
    ]


def _build_relaxed_fallback_candidates(
    intent: EquipmentIntent,
    candidates: list[EquipmentCandidate],
) -> list[EquipmentCandidate]:
    """Build controlled alternatives when strict search returns nothing."""
    if not candidates:
        return []

    buckets: list[EquipmentCandidate] = []

    # 1) Original fallback: closest safe alternatives.
    base = _build_fallback_candidates(intent, candidates)
    buckets.extend(_with_relaxation_reason(base, "closest_safe"))

    # 2) Water heater relaxations.
    if intent.category == "water_heater":
        wh = [
            c for c in candidates
            if _looks_like_water_heater(c.product_name)
        ]

        # same volume, but without heating element restriction
        if getattr(intent, "heating_element", None):
            same_volume = _filter_water_heater_volume_only(intent, wh)
            same_volume = [
                c for c in same_volume
                if not _heating_element_matches(intent.heating_element, c.product_name)
            ]
            buckets.extend(_with_relaxation_reason(same_volume, "same_volume_other_heating_element"))

        # same heating element, but nearby volume
        if getattr(intent, "heating_element", None) and (intent.volume_l or intent.volume_min_l):
            nearby = [
                c for c in wh
                if _heating_element_matches(intent.heating_element, c.product_name)
                and _water_heater_volume_near(c.product_name, intent)
            ]
            buckets.extend(_with_relaxation_reason(nearby, "same_heating_element_nearby_volume"))

        # indirect/tank-in-tank: same volume but broader water heaters, only if exact type not found
        if intent.water_heater_type in {"indirect", "tank_in_tank"}:
            same_volume = _filter_water_heater_volume_only(intent, wh)
            buckets.extend(_with_relaxation_reason(same_volume, "same_volume_other_water_heater_type"))

    # 3) Boiler relaxations.
    if intent.category == "boiler":
        boiler = [
            c for c in candidates
            if not _is_boiler_accessory(c.product_name)
        ]

        if getattr(intent, "boiler_type", None):
            boiler = [
                c for c in boiler
                if _boiler_type_matches(intent.boiler_type, c.product_name)
            ]

        if intent.brand:
            brand_boiler = [
                c for c in boiler
                if _brand_matches(intent.brand, c.product_name)
            ]
            if brand_boiler:
                boiler = brand_boiler

        # Same brand/power but only if it does not violate explicit critical specs.
        if intent.power_kw:
            same_power = [
                c for c in boiler
                if _contains_number_close(_normalize_model_text(c.product_name), intent.power_kw)
                and _critical_boiler_constraints_match(intent, c.product_name)
            ]
            buckets.extend(_with_relaxation_reason(same_power, "same_brand_power_other_specs"))

        # Same series but different circuits.
        model_terms = _model_terms_from_intent(intent)
        if model_terms:
            same_series = [
                c for c in boiler
                if _same_series_loose(intent, c.product_name)
                and _critical_boiler_constraints_match(intent, c.product_name)
            ]
            buckets.extend(_with_relaxation_reason(same_series, "same_series_other_specs"))

    return _dedupe_candidates(buckets)


def _dedupe_candidates(candidates: list[EquipmentCandidate]) -> list[EquipmentCandidate]:
    result: list[EquipmentCandidate] = []
    seen: set[str] = set()

    for c in candidates:
        key = _normalize_model_text(c.product_name)
        if key in seen:
            continue
        seen.add(key)
        result.append(c)

    return result


def _filter_water_heater_volume_only(
    intent: EquipmentIntent,
    candidates: list[EquipmentCandidate],
) -> list[EquipmentCandidate]:
    min_l = intent.volume_min_l
    max_l = intent.volume_max_l

    if intent.volume_l and not min_l and not max_l:
        min_l = max(intent.volume_l - 5, 0)
        max_l = intent.volume_l + 5

    if not min_l or not max_l:
        return candidates

    return [
        c for c in candidates
        if _water_heater_volume_in_range(c.product_name, min_l, max_l)
    ]


def _water_heater_volume_near(product_name: str, intent: EquipmentIntent) -> bool:
    target = intent.volume_l or intent.volume_min_l or intent.volume_max_l
    if not target:
        return False

    min_l = max(int(target) - 30, 0)
    max_l = int(target) + 30
    return _water_heater_volume_in_range(product_name, min_l, max_l)


def _same_series_loose(intent: EquipmentIntent, product_name: str) -> bool:
    terms = _model_terms_from_intent(intent)
    if not terms:
        return False

    name = _normalize_model_text(product_name).replace(" ", "")
    series_terms = [
        _normalize_model_text(t).replace(" ", "")
        for t in terms
        if not any(x in t for x in ["24f", "f24", "1.24f"])
    ]

    return bool(series_terms and any(t in name for t in series_terms))


def _build_fallback_candidates(
    intent: EquipmentIntent,
    candidates: list[EquipmentCandidate],
) -> list[EquipmentCandidate]:
    """Relax strict filters, but never cross into wrong equipment type."""
    if not candidates:
        return []

    filtered = candidates

    if intent.brand:
        brand_filtered = [
            c for c in filtered
            if _brand_matches(intent.brand, c.product_name)
        ]
        if brand_filtered:
            filtered = brand_filtered

    if intent.category == "water_heater":
        filtered = [
            c for c in filtered
            if _looks_like_water_heater(c.product_name)
        ]

        # Если просили косвенник / бак-в-баке, fallback не должен показывать электрические.
        if intent.water_heater_type == "indirect":
            filtered = [
                c for c in filtered
                if _looks_like_indirect_water_heater(c.product_name)
            ]

        if intent.water_heater_type == "tank_in_tank":
            filtered = [
                c for c in filtered
                if _looks_like_tank_in_tank(c.product_name)
            ]

        if getattr(intent, "heating_element", None):
            heating_filtered = [
                c for c in filtered
                if _heating_element_matches(intent.heating_element, c.product_name)
            ]
            filtered = heating_filtered

        # Рециркуляцию/материал можно ослабить, но объем держим жестко.
        min_l = intent.volume_min_l
        max_l = intent.volume_max_l

        if intent.volume_l and not min_l and not max_l:
            min_l = max(intent.volume_l - 5, 0)
            max_l = intent.volume_l + 5

        if min_l and max_l:
            volume_filtered = [
                c for c in filtered
                if _water_heater_volume_in_range(c.product_name, min_l, max_l)
            ]
            if volume_filtered:
                filtered = volume_filtered

    if intent.category == "boiler":
        filtered = [
            c for c in filtered
            if not _is_boiler_accessory(c.product_name)
        ]

        if getattr(intent, "boiler_type", None):
            type_filtered = [
                c for c in filtered
                if _boiler_type_matches(intent.boiler_type, c.product_name)
            ]
            filtered = type_filtered

        if intent.brand:
            brand_filtered = [
                c for c in filtered
                if _brand_matches(intent.brand, c.product_name)
            ]
            if brand_filtered:
                filtered = brand_filtered

        if intent.power_kw:
            power_filtered = [
                c for c in filtered
                if _contains_number_close(
                    _normalize_model_text(c.product_name),
                    intent.power_kw
                )
            ]
            if power_filtered:
                filtered = power_filtered

        # Критичные фильтры НЕ ослабляем

        if intent.chamber == "open":
            chamber_filtered = [
                c for c in filtered
                if any(
                    x in c.product_name.lower()
                    for x in [
                        "атмо",
                        "дымох",
                        "атмос",
                        "open"
                    ]
                )
            ]
            if chamber_filtered:
                filtered = chamber_filtered

        if intent.chamber == "closed":
            chamber_filtered = [
                c for c in filtered
                if any(
                    x in c.product_name.lower()
                    for x in [
                        "турбо",
                        "fi",
                        "ff",
                        "закр"
                    ]
                )
            ]
            if chamber_filtered:
                filtered = chamber_filtered

        if intent.circuits == 1:
            c1 = [
                c for c in filtered
                if any(
                    x in c.product_name.lower()
                    for x in [
                        "одноконт",
                        "1 конт",
                        "1к",
                        "1."
                    ]
                )
            ]
            if c1:
                filtered = c1

        if intent.circuits == 2:
            c2 = [
                c for c in filtered
                if any(
                    x in c.product_name.lower()
                    for x in [
                        "двухконт",
                        "2 конт",
                        "2х",
                        "24f",
                        "31f"
                    ]
                )
            ]
            if c2:
                filtered = c2

        # Если явно просили модель/серию, fallback не должен уходить в другой товар.
        model_terms = _model_terms_from_intent(intent)
        if model_terms:
            model_filtered = [
                c for c in filtered
                if _model_matches_intent(intent, c.product_name)
            ]

            # Если exact model пустой, разрешаем только тот же бренд + похожую серию,
            # но не Ладу/случайные Nova.
            if model_filtered:
                filtered = model_filtered

    filtered = [
        c for c in filtered
        if _critical_boiler_constraints_match(intent, c.product_name)
    ]

    return filtered


def _critical_boiler_constraints_match(intent: EquipmentIntent, product_name: str) -> bool:
    if intent.category != "boiler":
        return True

    name = product_name.lower().replace("ё", "е")

    if intent.chamber == "open":
        # Атмосферный / открытая камера: нельзя турбо/закрытую.
        if any(x in name for x in ["турбо", "fi", "ff", "24f", "f24", "коакс", "закрыт"]):
            return False

    if intent.chamber == "closed":
        # Турбо / закрытая камера: нельзя дымоходные атмосферники.
        if any(x in name for x in ["дымох", "атмо", "открыт", " in ", " in", "1.230 in", "1.620 in"]):
            return False

    if intent.circuits == 1:
        # Одноконтурный: нельзя двухконтурные 24F/F24.
        if any(x in name for x in ["двухконт", "2х", "2 конт", "24f", "f24", "31f"]):
            return False

    if intent.circuits == 2:
        # Двухконтурный: нельзя 1.xxx и одноконтурные.
        if any(x in name for x in ["одноконт", "1 конт", "1.24", "1.230", "1.620", "1.140"]):
            return False

    return True


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
        filtered = _filter_water_heaters(intent, filtered)

    return filtered


def _filter_water_heaters(
    intent: EquipmentIntent,
    candidates: list[EquipmentCandidate],
) -> list[EquipmentCandidate]:
    filtered = [
        c for c in candidates
        if _looks_like_water_heater(c.product_name)
    ]

    if intent.water_heater_type == "tank_in_tank":
        filtered = [
            c for c in filtered
            if _looks_like_tank_in_tank(c.product_name)
        ]

    elif intent.water_heater_type == "indirect" or _is_indirect_water_heater_request(intent):
        filtered = [
            c for c in filtered
            if _looks_like_indirect_water_heater(c.product_name)
        ]

    if intent.install_type:
        install_filtered = [
            c for c in filtered
            if _water_heater_install_matches(intent.install_type, c.product_name)
        ]
        if install_filtered:
            filtered = install_filtered

    if intent.recirculation:
        recirc_filtered = [
            c for c in filtered
            if _has_recirculation(c.product_name)
        ]
        filtered = recirc_filtered

    if intent.tank_material == "stainless":
        material_filtered = [
            c for c in filtered
            if _has_stainless_tank(c.product_name)
        ]
        filtered = material_filtered

    if intent.tank_coating == "enamel":
        enamel_filtered = [
            c for c in filtered
            if _has_enamel_tank(c.product_name)
        ]
        filtered = enamel_filtered

    if getattr(intent, "heating_element", None):
        heating_filtered = [
            c for c in filtered
            if _heating_element_matches(intent.heating_element, c.product_name)
        ]
        filtered = heating_filtered

    min_l = intent.volume_min_l
    max_l = intent.volume_max_l

    if intent.volume_l and not min_l and not max_l:
        min_l = max(intent.volume_l - 5, 0)
        max_l = intent.volume_l + 5

    if min_l and max_l:
        volume_filtered = [
            c for c in filtered
            if _water_heater_volume_in_range(c.product_name, min_l, max_l)
        ]
        filtered = volume_filtered

    return filtered


def _looks_like_water_heater(name: str) -> bool:
    text = name.lower().replace("ё", "е")

    good = [
        "бойлер",
        "водонагрев",
        "thermex",
        "ariston",
        "аристон",
        "midea",
        "haier",
        "electrolux",
        "drazice",
        "hajdu",
        "acv",
        "baxi v",
        "baxi ub",
        "бакси ub",
        "косвен",
        "змеевик",
    ]

    bad = [
        "духовка",
        "вытяжка",
        "коллектор",
        "радиатор",
        "котел",
        "котёл",
        "насос",
        "клапан",
        "фланец",
        "тэн для",
        "тен для",
        "для бойлеров",
        "комплект",
        "датчик",
        "мембрана",
    ]

    return any(x in text for x in good) and not any(x in text for x in bad)


def _looks_like_tank_in_tank(name: str) -> bool:
    text = name.lower().replace("ё", "е")
    good = [
        "бак в баке",
        "бак-в-баке",
        "tank in tank",
        "acv",
        "smart",
        "comfort",
        "комфорт",
    ]
    bad = ["электр", "тэн", "тен", "плоский", "pro1", "abs", "thermo", "titaniumheat"]

    return any(x in text for x in good) and not any(x in text for x in bad)


def _water_heater_install_matches(install_type: str, name: str) -> bool:
    text = name.lower().replace("ё", "е")

    if install_type == "wall":
        floor_markers = ["наполь", "нап."]
        return not any(x in text for x in floor_markers)

    if install_type == "floor":
        wall_markers = ["настен", "верт.", "горизонт", "v ", " h "]
        if "наполь" in text:
            return True
        return not any(x in text for x in wall_markers)

    return True


def _has_recirculation(name: str) -> bool:
    text = name.lower().replace("ё", "е")
    return "рецирк" in text or "рециркуляц" in text


def _has_stainless_tank(name: str) -> bool:
    text = name.lower().replace("ё", "е")
    return "нерж" in text or "нержав" in text or "inox" in text


def _has_enamel_tank(name: str) -> bool:
    text = name.lower().replace("ё", "е")
    return "эмаль" in text or "эмал" in text or "биостекло" in text or "стеклофарфор" in text


def _heating_element_matches(expected: str | None, name: str) -> bool:
    if not expected:
        return True

    text = name.lower().replace("ё", "е")

    dry_markers = ["сухой тэн", "сухой тен", "dry", "стеатит"]
    wet_markers = ["мокрый тэн", "мокрый тен"]

    if expected == "dry":
        if any(x in text for x in wet_markers):
            return False
        return any(x in text for x in dry_markers)

    if expected == "wet":
        if any(x in text for x in dry_markers):
            return False
        return any(x in text for x in wet_markers)

    return True


def _water_heater_volume_in_range(name: str, min_l: int, max_l: int) -> bool:
    import re

    text = name.lower().replace("ё", "е")

    nums = []
    for raw in re.findall(r"(?<!\d)(\d{2,4})(?!\d)", text):
        value = int(raw)
        if 10 <= value <= 1000:
            nums.append(value)

    return any(min_l <= value <= max_l for value in nums)


def _is_indirect_water_heater_request(intent: EquipmentIntent) -> bool:
    raw = intent.raw_text.lower().replace("ё", "е")
    query = intent.query_for_supplier_search.lower().replace("ё", "е")
    return "косвен" in raw or "косвен" in query


def _looks_like_indirect_water_heater(name: str) -> bool:
    text = name.lower().replace("ё", "е")

    bad = [
        "электр",
        "тэн",
        "тен",
        "водонагреватель электр",
        "thermo ",
        "titaniumheat",
        "pro1",
        "abs vls",
        "lydos",
        "nts ",
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
        "бакси ub",
        "бакси v",
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


def _boiler_type_matches(boiler_type: str | None, product_name: str) -> bool:
    if not boiler_type:
        return True

    name = product_name.lower().replace("ё", "е")

    if boiler_type == "parapet":
        # Парапетный — только явные парапетные позиции.
        # Обычные КСГ/АОГВ/TGV без слова "парапет" не пропускаем.
        good = [
            "парапет",
            "патриот",
            "ксгз",
        ]

        bad = [
            "настен",
            "наполь",
            "закр.камера",
            "закрытая камера",
            "закр камера",
            "турбо",
            "24f",
            "f24",
            "fi",
            "ff",
            "радиатор",
            "бимет",
            "алюм",
            "dakor",
            "oc-",
            "бк-",
            "ггу",
            "горелка",
            "щиток",
            "авт.",
        ]

        return any(x in name for x in good) and not any(x in name for x in bad)

    if boiler_type == "floor":
        # Напольные дымоходные: КСГ/АОГВ/TGV, но не парапетные.
        if "парапет" in name or "ксгз" in name or "патриот" in name:
            return False

        return any(x in name for x in ["наполь", "аогв", "ксг", "tgv", "тgv"]) and "настен" not in name

    if boiler_type == "wall":
        return "настен" in name or any(x in name for x in ["24f", "f24", "fi", "турбо"])

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
        "радиатор",
        "бимет",
        "алюм",
        "секц",
        "dakor",
        "oc-",
        "бк-",
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
