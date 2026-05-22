from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ProductFacts:
    category: str | None
    equipment_type: str | None
    boiler_type: str | None
    power_kw: float | None
    volume_l: int | None
    circuits: int | None
    orientation: str | None
    gas_automation: str | None
    connection: str | None
    chimney_diameter_mm: int | None
    is_accessory: bool


def enrich_product(name: str) -> ProductFacts:
    text = normalize(name)

    is_accessory = _is_accessory(text)

    category = None
    equipment_type = None
    boiler_type = None

    if _is_boiler(text):
        category = "boiler"
        equipment_type = "boiler"
        boiler_type = _boiler_type(text)

    elif _is_water_heater(text):
        category = "water_heater"
        equipment_type = _water_heater_type(text)

    elif "насос" in text:
        category = "pump"
        equipment_type = "pump"

    power_kw = _extract_power_kw(text)
    volume_l = _extract_volume_l(text)
    circuits = _extract_circuits(text) if category == "boiler" else None
    orientation = _extract_orientation(text) if category == "boiler" else None
    gas_automation = _extract_gas_automation(text) if category == "boiler" else None
    connection = _extract_connection(text) if category == "boiler" else None
    chimney_diameter_mm = _extract_chimney_diameter_mm(text) if category == "boiler" else None

    return ProductFacts(
        category=category,
        equipment_type=equipment_type,
        boiler_type=boiler_type,
        power_kw=power_kw,
        volume_l=volume_l,
        circuits=circuits,
        orientation=orientation,
        gas_automation=gas_automation,
        connection=connection,
        chimney_diameter_mm=chimney_diameter_mm,
        is_accessory=is_accessory,
    )


def normalize(value: str) -> str:
    text = str(value or "").lower().replace("ё", "е")
    text = text.replace(",", ".")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_boiler(text: str) -> bool:
    if _is_accessory(text):
        return False

    if any(x in text for x in [
        "котел",
        "котёл",
        "аогв",
        "ксг",
        "кс-г",
        "ксгв",
        "ксгз",
        "патриот",
        "classic",
        "clever",
        "газовик",
        "форвард",
    ]):
        return True

    return False


def _is_water_heater(text: str) -> bool:
    if _is_accessory(text):
        return False

    return any(x in text for x in ["бойлер", "водонагрев", "drazice", "hajdu", "acv"])


def _boiler_type(text: str) -> str | None:
    if any(x in text for x in ["парапет", "ксгз", "патриот"]):
        return "parapet"

    if any(x in text for x in [
        "аогв",
        "ксг",
        "кс-г",
        "ксгв",
        "наполь",
        "classic",
        "clever",
        "газовик",
    ]):
        return "floor"

    if any(x in text for x in ["настен", "турбо", "24f", "f24", "fi", "ff"]):
        return "wall"

    return None


def _water_heater_type(text: str) -> str | None:
    if any(x in text for x in ["бак в баке", "tank in tank", "acv smart", "acv comfort"]):
        return "tank_in_tank"

    if any(x in text for x in ["косвен", "змеевик", "drazice", "hajdu", "baxi ub"]):
        return "indirect"

    if any(x in text for x in ["электр", "тэн", "тен", "thermex", "ariston", "аристон", "midea"]):
        return "electric"

    return None


def _is_accessory(text: str) -> bool:
    bad = [
        "тэн для",
        "тен для",
        "для бойлер",
        "горелка",
        "ггу",
        "щиток",
        "авт.",
        "радиатор",
        "dakor",
        "oc-",
        "бк-",
        "дымоход",
        "коаксиал",
        "зонт",
        "фланец",
        "мембрана",
        "датчик",
        "плата",
        "клапан",
        "комплект",
        "электродвигатель",
    ]
    return any(x in text for x in bad)


def _extract_circuits(text: str) -> int | None:
    # 2-контурные
    if any(x in text for x in [
        "двухконт",
        "2 конт",
        "2х",
        "гор.вода",
        "+гор.вода",
        "ксгв",
        "аогвк",
    ]):
        return 2

    if re.search(r"\b\d{2}\s*f\b|\bf\d{2}\b", text):
        return 2

    # 1-контурные
    if any(x in text for x in [
        "одноконт",
        "1 конт",
        "ксг-",
        "кс-г",
        "аогв-",
        "патриот",
    ]):
        return 1

    if re.search(r"\b1\.\d+\s*f\b", text):
        return 1

    return None


def _extract_orientation(text: str) -> str | None:
    if any(x in text for x in ["вертик", "верт.", "верт-"]):
        return "vertical"

    if any(x in text for x in ["гориз", "гор.", "горизонт"]):
        return "horizontal"

    return None


def _extract_gas_automation(text: str) -> str | None:
    if "sit" in text:
        return "sit"

    if "tgv" in text or "тgv" in text:
        return "tgv"

    return None


def _extract_connection(text: str) -> str | None:
    if "боковой подвод" in text or "бок." in text:
        return "side"

    return None


def _extract_chimney_diameter_mm(text: str) -> int | None:
    m = re.search(r"дым\.?\s*(\d{2,3})", text)
    if m:
        value = int(m.group(1))
        if 50 <= value <= 300:
            return value

    m = re.search(r"дымоход\.?\s*(\d{2,3})", text)
    if m:
        value = int(m.group(1))
        if 50 <= value <= 300:
            return value

    return None


def _extract_power_kw(text: str) -> float | None:
    patterns = [
        r"ксгз?[-\s]*(\d+(?:\.\d+)?)",
        r"кс-г[-\s]*(\d+(?:\.\d+)?)",
        r"аогв[-\s]*(\d+(?:\.\d+)?)",
        r"патриот\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*квт",
        r"(\d{2})f\b",
        r"f(\d{2})\b",
    ]

    for pattern in patterns:
        m = re.search(pattern, text)
        if not m:
            continue

        value = float(m.group(1))
        if 5 <= value <= 100:
            return value

    m = re.search(r"(\d{2,3})\s*кв\.?м", text)
    if m:
        area = float(m.group(1))
        if 50 <= area <= 400:
            return round(area / 10, 1)

    return None


def _extract_volume_l(text: str) -> int | None:
    patterns = [
        r"(\d{2,4})\s*л\b",
        r"\b(\d{2,4})\s*v\b",
        r"\b(\d{2,4})\s*h\b",
    ]

    for pattern in patterns:
        m = re.search(pattern, text)
        if not m:
            continue

        value = int(m.group(1))
        if 5 <= value <= 1000:
            return value

    return None
