from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SelectorFilters:
    brand: str | None = None
    category: str | None = None
    mount_type: str | None = None
    chamber: str | None = None
    circuits: int | None = None
    power_min: float | None = None
    power_max: float | None = None


def norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).lower().replace("ё", "е").strip()


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        text = str(value).replace(",", ".")
        return float(text)
    except Exception:
        return None


def normalize_chamber(value: Any) -> str | None:
    text = norm(value)
    if any(x in text for x in ("закрыт", "турбо", "turbo", "closed")):
        return "closed"
    if any(x in text for x in ("открыт", "атмо", "atmo", "open")):
        return "open"
    return None


def normalize_circuits(value: Any) -> int | None:
    text = norm(value)
    if any(x in text for x in ("двух", "2-к", "2 к", "2х", "2 х", " 2 ", "two")):
        return 2
    if any(x in text for x in ("одно", "1-к", "1 к", "1х", "1 х", " 1 ", "single")):
        return 1
    return None


def normalize_mount_type(value: Any) -> str | None:
    text = norm(value)
    if any(x in text for x in ("настен", "wall")):
        return "wall"
    if any(x in text for x in ("наполь", "floor")):
        return "floor"
    return None


def build_filters(intent: Any) -> SelectorFilters:
    if hasattr(intent, "model_dump"):
        data = intent.model_dump()
    elif isinstance(intent, dict):
        data = intent
    else:
        data = getattr(intent, "__dict__", {}) or {}

    power_min = (
        data.get("power_min")
        or data.get("power_from")
        or data.get("min_power")
    )
    power_max = (
        data.get("power_max")
        or data.get("power_to")
        or data.get("max_power")
    )

    return SelectorFilters(
        brand=data.get("brand"),
        category=data.get("category"),
        mount_type=normalize_mount_type(
            data.get("mount_type")
            or data.get("installation")
            or data.get("type")
        ),
        chamber=normalize_chamber(
            data.get("chamber")
            or data.get("combustion_chamber")
            or data.get("camera")
        ),
        circuits=normalize_circuits(
            data.get("circuits")
            or data.get("contours")
            or data.get("circuit_count")
        ),
        power_min=as_float(power_min),
        power_max=as_float(power_max),
    )


def get_card_value(card: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in card and card[key] not in (None, ""):
            return card[key]

    params = card.get("params") or card.get("attributes") or {}
    if isinstance(params, dict):
        for key in keys:
            if key in params and params[key] not in (None, ""):
                return params[key]

    text = card.get("description") or card.get("specs") or card.get("raw_text")
    return text


def validate_selector_card(
    card: dict[str, Any],
    filters: SelectorFilters,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    name = norm(card.get("name") or card.get("title"))
    raw_text = " ".join(
        norm(x)
        for x in [
            card.get("name"),
            card.get("title"),
            card.get("description"),
            card.get("specs"),
            card.get("raw_text"),
            card.get("params"),
            card.get("attributes"),
        ]
    )

    if filters.brand and norm(filters.brand) not in name:
        reasons.append("brand_mismatch")

    power = as_float(
        get_card_value(
            card,
            "power_kw",
            "power",
            "capacity_kw",
            "мощность",
            "Мощность",
        )
    )

    if power is not None:
        if filters.power_min is not None and power < filters.power_min:
            reasons.append("power_too_low")
        if filters.power_max is not None and power > filters.power_max:
            reasons.append("power_too_high")

    if filters.chamber:
        chamber = normalize_chamber(
            get_card_value(
                card,
                "chamber",
                "combustion_chamber",
                "camera",
                "камера",
                "Камера сгорания",
            )
            or raw_text
        )
        if chamber != filters.chamber:
            reasons.append("chamber_mismatch")

    if filters.circuits:
        circuits = normalize_circuits(
            get_card_value(
                card,
                "circuits",
                "contours",
                "circuit_count",
                "контуры",
                "кол-во контуров",
            )
            or raw_text
        )
        if circuits != filters.circuits:
            reasons.append("circuits_mismatch")

    if filters.mount_type:
        mount_type = normalize_mount_type(
            get_card_value(
                card,
                "mount_type",
                "installation",
                "type",
                "тип",
                "монтаж",
            )
            or raw_text
        )

        # Если сайт вообще не отдал монтаж — не режем карточку.
        if mount_type is not None and mount_type != filters.mount_type:
            reasons.append("mount_type_mismatch")

    return len(reasons) == 0, reasons


def filter_selector_cards(
    cards: list[dict[str, Any]],
    filters: SelectorFilters,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for card in cards:
        is_valid, reasons = validate_selector_card(card, filters)
        if is_valid:
            valid.append(card)
        else:
            rejected.append(
                {
                    "name": card.get("name") or card.get("title"),
                    "reasons": reasons,
                }
            )

    return valid, rejected


def deduplicate_supplier_offers(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}

    for offer in offers:
        supplier = norm(offer.get("supplier") or offer.get("supplier_name"))
        product = norm(
            offer.get("product_name")
            or offer.get("name")
            or offer.get("title")
        )
        key = (supplier, product)

        price = as_float(offer.get("price")) or 0
        current = unique.get(key)

        if current is None:
            unique[key] = offer
            continue

        current_price = as_float(current.get("price")) or 0
        if current_price == 0 or (price > 0 and price < current_price):
            unique[key] = offer

    return sorted(unique.values(), key=lambda x: as_float(x.get("price")) or 10**18)
