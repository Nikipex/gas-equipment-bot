from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz


@dataclass(frozen=True)
class RankedSupplierCandidate:
    title: str
    href: str
    score: float
    reason: str


def rank_supplier_candidate(query: str, title: str, href: str | None = None) -> RankedSupplierCandidate:
    query_features = extract_features(query)
    title_features = extract_features(f"{title} {href or ''}")

    query_norm = query_features["normalized"]
    title_norm = title_features["normalized"]

    score = 0.0
    reasons: list[str] = []

    fuzzy = max(
        fuzz.token_set_ratio(query_norm, title_norm),
        fuzz.partial_ratio(query_norm, title_norm),
    ) / 100

    score += fuzzy * 0.25

    if query_features["brand"]:
        if query_features["brand"] == title_features["brand"]:
            score += 0.20
            reasons.append("brand")
        else:
            score -= 0.40
            reasons.append("brand_mismatch")

    if query_features["series"]:
        if query_features["series"] == title_features["series"]:
            score += 0.25
            reasons.append("series")
        elif title_features["series"]:
            score -= 0.15
            reasons.append("series_mismatch")

    if query_features["model"]:
        if query_features["model"] == title_features["model"]:
            score += 0.35
            reasons.append("model")
        elif is_model_close(query_features["model"], title_features["model"]):
            score += 0.10
            reasons.append("model_close")
        elif title_features["model"]:
            score -= 0.25
            reasons.append("model_mismatch")

    if query_features["power"] and title_features["power"]:
        diff = abs(query_features["power"] - title_features["power"])

        if diff <= 0.75:
            score += 0.12
            reasons.append("power")
        elif diff <= 2:
            score += 0.05
            reasons.append("power_close")
        else:
            score -= 0.20
            reasons.append("power_mismatch")

    # Критично: 24F != 1.24F
    if query_features["is_124"] != title_features["is_124"]:
        if query_features["model"] and title_features["model"]:
            score -= 0.45
            reasons.append("one_circuit_mismatch")

    if is_accessory(title_norm):
        score -= 0.60
        reasons.append("accessory")

    score = max(0.0, min(1.0, score))

    return RankedSupplierCandidate(
        title=title,
        href=href or "",
        score=round(score, 3),
        reason=", ".join(reasons) or "soft",
    )


def extract_features(value: str) -> dict:
    text = normalize(value)

    brand = None
    for item in [
        "baxi",
        "navien",
        "ariston",
        "bosch",
        "protherm",
        "fondital",
        "viessmann",
        "vaillant",
        "kentatsu",
        "lemaks",
    ]:
        if item in text:
            brand = item
            break

    series = None
    series_patterns = [
        ("eco4s", r"\beco\s*4s\b|\beco4s\b"),
        ("eco5compact", r"\beco\s*5\s*compact\b|\beco5compact\b"),
        ("ecolife", r"\beco\s*life\b|\becolife\b"),
        ("econova", r"\beco\s*nova\b|\beconova\b"),
        ("ecohome", r"\beco\s*home\b|\becohome\b"),
        ("ecofour", r"\beco\s*four\b|\becofour\b"),
        ("luna3", r"\bluna\s*3\b|\bluna3\b"),
        ("nuvola3", r"\bnuvola\s*3\b|\bnuvola3\b"),
        ("mainfour", r"\bmain\s*four\b|\bmainfour\b"),
        ("main5", r"\bmain\s*5\b|\bmain5\b"),
        ("deluxe", r"\bdeluxe\b"),
        ("cares", r"\bcares\b"),
    ]

    for name, pattern in series_patterns:
        if re.search(pattern, text):
            series = name
            break

    model = extract_model(text)
    power = extract_power(text, model)

    return {
        "normalized": text,
        "brand": brand,
        "series": series,
        "model": model,
        "power": power,
        "is_124": bool(model and model.startswith("1.24")),
    }


def normalize(value: str) -> str:
    text = str(value or "").lower().replace("ё", "е")

    aliases = {
        "бакси": "baxi",
        "навьен": "navien",
        "аристон": "ariston",
        "бош": "bosch",
        "котел": "",
        "котёл": "",
        "газовый": "",
        "настенный": "",
        "настен": "",
        "двухконтурный": "",
        "одноконтурный": "",
        "турбированный": "",
        "турбо": "",
    }

    for src, dst in aliases.items():
        text = text.replace(src, dst)

    text = text.replace("-", " ")
    text = re.sub(r"[^a-zа-я0-9\.]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def extract_model(text: str) -> str | None:
    patterns = [
        r"\b1\.24\s*f\b",
        r"\b1\.24f\b",
        r"\b1\.24\b",
        r"\b\d{3}\s*fi\b",
        r"\b\d{3}fi\b",
        r"\b\d{3}\s*i\b",
        r"\b\d{3}i\b",
        r"\b\d{2}\s*fi\b",
        r"\b\d{2}fi\b",
        r"\b\d{2}\s*f\b",
        r"\b\d{2}f\b",
        r"\b\d{2}\s*k\b",
        r"\b\d{2}k\b",
        r"\b\d{2}\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return re.sub(r"\s+", "", match.group(0))

    return None


def extract_power(text: str, model: str | None) -> float | None:
    match = re.search(r"мощность\s*(\d+(?:\.\d+)?)", text)

    if match:
        value = float(match.group(1))
        if 5 <= value <= 100:
            return value

    if not model:
        return None

    nums = re.findall(r"\d+(?:\.\d+)?", model)
    if not nums:
        return None

    value = float(nums[0])

    if value in (240, 280, 310):
        return value / 10

    if 5 <= value <= 100:
        return value

    return None


def is_model_close(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False

    left_power = extract_power(left, left)
    right_power = extract_power(right, right)

    if left_power and right_power and abs(left_power - right_power) <= 0.75:
        return True

    return False


def is_accessory(text: str) -> bool:
    bad = [
        "дымоход",
        "коаксиал",
        "жиклер",
        "жиклеры",
        "форсунк",
        "комплект",
        "адаптер",
        "колено",
        "труба",
        "датчик",
        "плата",
        "насос",
        "клапан",
        "подключения",
        "присоединения",
    ]

    return any(x in text for x in bad)
