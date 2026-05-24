from __future__ import annotations

import re


BRAND_ALIASES = {
    "бакси": "baxi",
    "аристон": "ariston",
    "вайлант": "vaillant",
    "навьен": "navien",
    "навиен": "navien",
    "бош": "bosch",
    "ферроли": "ferroli",
    "иммергаз": "immergas",
    "термекс": "thermex",
    "мидеа": "midea",
    "лемакс": "lemax",
}


def normalize_model_text(text: object) -> str:
    value = str(text or "").lower().replace("ё", "е")

    for ru, en in BRAND_ALIASES.items():
        value = value.replace(ru, en)

    value = value.replace("×", "x")
    value = value.replace(",", ".")
    value = re.sub(r"[-_/()+,;:]+", " ", value)

    # Baxi luna-3 / luna3 / luna 3
    value = re.sub(r"\bluna\s*3\b", "luna 3", value)
    value = value.replace("luna3", "luna 3")

    # 1.310 -> 310, 1.240 -> 240
    value = re.sub(r"\b1\.(\d{2,4})\b", r"\1", value)

    # 24F / 24 F
    value = re.sub(r"\b(\d{2,3})\s*([a-zа-я])\b", r"\1\2", value)

    # ECO FOUR / ECO4 / ECO 4
    value = value.replace("ecofour", "eco four")
    value = value.replace("eco4", "eco 4")
    value = value.replace("econova", "eco nova")
    value = value.replace("ecolife", "eco life")

    value = re.sub(r"\s+", " ", value).strip()
    return value


def model_tokens(text: object) -> list[str]:
    norm = normalize_model_text(text)
    tokens = []

    for token in norm.split():
        if len(token) < 2:
            continue
        if token in {"котел", "котёл", "газовый", "настенный", "напольный", "бойлер"}:
            continue
        tokens.append(token)

    return tokens


def score_model_match(query: object, product_name: object) -> int:
    q = normalize_model_text(query)
    n = normalize_model_text(product_name)

    score = 0

    if q and q in n:
        score += 250

    q_tokens = model_tokens(q)
    n_tokens = set(model_tokens(n))

    for token in q_tokens:
        if token in n_tokens:
            score += 35
        elif token in n:
            score += 20

    # Числовые модели особенно важны: 310 / 24f / 80 / 100
    q_numbers = re.findall(r"\b\d+[a-zа-я]?\b", q)
    for num in q_numbers:
        if num in n:
            score += 45

    # Штрафы за лишние модификации, если их не просили
    optional_words = ["comfort", "plus", "pro", "classic", "deluxe", "smart", "акция"]
    for word in optional_words:
        if word in n and word not in q:
            score -= 10

    return score


def dedupe_model_key(product_name: object) -> str:
    n = normalize_model_text(product_name)

    for word in ["comfort", "plus", "pro", "classic", "new", "акция"]:
        n = n.replace(word, "")

    n = re.sub(r"\s+", " ", n).strip()
    return n
