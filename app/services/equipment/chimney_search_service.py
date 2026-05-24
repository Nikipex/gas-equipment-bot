from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd


ENRICHED_PATH = Path("data/supplier_prices/processed/enriched_supplier_products.csv")


class ChimneySearchService:
    def __init__(self, path: Path = ENRICHED_PATH) -> None:
        self.path = path

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        df = pd.read_csv(self.path)
        if df.empty or "product_name" not in df.columns:
            return []

        intent = parse_chimney_query(query)

        out = df.copy()
        out["_name"] = out["product_name"].astype(str).str.lower().str.replace("ё", "е", regex=False)

        # Базово ищем только дымоходку/коаксиалы.
        # У части аксессуаров category пустая, но chimney_type/system заполнены.
        if "category" in out.columns:
            chimney_mask = out["category"].eq("chimney")

            if "chimney_type" in out.columns:
                chimney_mask = chimney_mask | out["chimney_type"].notna()

            if "chimney_system" in out.columns:
                chimney_mask = chimney_mask | out["chimney_system"].notna()

            chimney = out[chimney_mask]
            if not chimney.empty:
                out = chimney.copy()

        if intent["system"] and "chimney_system" in out.columns:
            # Для конденсатосборников 60/100 система может быть не заполнена,
            # поэтому не убиваем выдачу только из-за пустого chimney_system.
            if intent["type"] == "condensate":
                x = out[
                    (out["chimney_system"] == intent["system"])
                    | (out["chimney_diameter"].astype(str).str.contains("/", regex=False, na=False))
                ]
            else:
                x = out[out["chimney_system"] == intent["system"]]

            if not x.empty:
                out = x.copy()

        if intent["type"] and "chimney_type" in out.columns:
            x = out[out["chimney_type"] == intent["type"]]
            if not x.empty:
                out = x.copy()
            elif intent["type"] == "condensate":
                name_mask = out["_name"].str.contains("конденсат", regex=False, na=False)
                out = out[name_mask].copy()

        if intent["diameter"] and "chimney_diameter" in out.columns:
            x = out[out["chimney_diameter"].astype(str) == str(intent["diameter"])]
            if not x.empty:
                out = x.copy()

        if intent["brand"] and "chimney_brand" in out.columns:
            x = out[
                (out["chimney_brand"].astype(str) == intent["brand"])
                | out["_name"].str.contains(intent["brand"], regex=False, na=False)
            ]
            if not x.empty:
                out = x.copy()

        if intent["length_m"] is not None:
            # Мягкий фильтр по длине: если ничего не нашли, не убиваем выдачу.
            length_patterns = _length_patterns(intent["length_m"])
            mask = False
            for pattern in length_patterns:
                mask = mask | out["_name"].str.contains(pattern, regex=True, na=False)
            x = out[mask]
            if not x.empty:
                out = x.copy()

        out = out.copy()
        out["chimney_score"] = score_chimney(out, intent)
        out = out.sort_values(
            ["chimney_score", "stock", "price"],
            ascending=[False, False, True],
            na_position="last",
        )

        return out.head(limit).drop(columns=["_name"], errors="ignore").to_dict("records")


def parse_chimney_query(query: str) -> dict[str, Any]:
    low = query.lower().replace("ё", "е")

    system = None
    if "коакс" in low or "60/100" in low or "80/125" in low or "80/80" in low:
        system = "coaxial"
    elif "дымоход" in low or "труба" in low or "зонт" in low or "тройник" in low:
        system = "classic"

    item_type = None
    if "конденсат" in low:
        item_type = "condensate"
    elif "адаптер" in low or "переход" in low:
        item_type = "adapter"
    elif "колено" in low or "отвод" in low or "угол" in low or "уголок" in low:
        item_type = "elbow"
    elif "удлин" in low:
        item_type = "extension"
    elif "комплект" in low:
        item_type = "kit"
    elif "труба" in low:
        item_type = "pipe"
    elif "зонт" in low:
        item_type = "cap"
    elif "тройник" in low:
        item_type = "tee"
    elif "фланец" in low:
        item_type = "flange"
    elif "заглуш" in low:
        item_type = "plug"

    diameter = None
    m = re.search(r"(60/100|80/125|80/80|110/160)", low)
    if m:
        diameter = m.group(1)
    else:
        m = re.search(r"(?:d|dn|диам|диаметр|ø)?\s*[- ]?(\d{2,3})\s*(?:мм)?", low)
        if m:
            value = int(m.group(1))
            if 60 <= value <= 300:
                diameter = str(value)

    brand = None
    brands = {
        "baxi": ["baxi", "бакси"],
        "ariston": ["ariston", "аристон"],
        "vaillant": ["vaillant", "вайлант"],
        "bosch": ["bosch", "бош"],
        "navien": ["navien", "навьен", "навиен"],
        "immergas": ["immergas", "иммергаз"],
    }

    for normalized, aliases in brands.items():
        if any(alias in low for alias in aliases):
            brand = normalized
            break

    length_m = None
    m = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:м|метр)", low)
    if m:
        length_m = float(m.group(1).replace(",", "."))

    return {
        "system": system,
        "type": item_type,
        "diameter": diameter,
        "brand": brand,
        "length_m": length_m,
    }


def score_chimney(df: pd.DataFrame, intent: dict[str, Any]) -> pd.Series:
    score = pd.Series(0, index=df.index, dtype=float)

    if intent["system"] and "chimney_system" in df.columns:
        score += (df["chimney_system"] == intent["system"]).astype(int) * 50

    if intent["type"] and "chimney_type" in df.columns:
        score += (df["chimney_type"] == intent["type"]).astype(int) * 40

    if intent["diameter"] and "chimney_diameter" in df.columns:
        score += (df["chimney_diameter"].astype(str) == str(intent["diameter"])).astype(int) * 30

    if intent["brand"]:
        name = df["product_name"].astype(str).str.lower().str.replace("ё", "е", regex=False)
        score += name.str.contains(intent["brand"], regex=False, na=False).astype(int) * 20

    return score


def build_chimney_text(query: str, rows: list[dict[str, Any]]) -> str:
    intent = parse_chimney_query(query)

    lines = [
        "🧱 <b>Подбор дымоходки / коаксиалов</b>",
        "",
        "🧾 <b>Что понял:</b>",
    ]

    labels = {
        "coaxial": "коаксиальная система",
        "classic": "обычный дымоход",
        "adapter": "адаптер / переход",
        "elbow": "колено / отвод",
        "extension": "удлинение",
        "kit": "комплект",
        "pipe": "труба",
        "condensate": "конденсатоотвод",
        "cap": "зонт",
        "tee": "тройник",
        "flange": "фланец",
        "plug": "заглушка",
    }

    if intent["system"]:
        lines.append(f"• система: <b>{labels.get(intent['system'], intent['system'])}</b>")
    if intent["type"]:
        lines.append(f"• тип: <b>{labels.get(intent['type'], intent['type'])}</b>")
    if intent["diameter"]:
        lines.append(f"• диаметр: <b>{intent['diameter']}</b>")
    if intent["brand"]:
        lines.append(f"• бренд/совместимость: <b>{intent['brand']}</b>")
    if intent["length_m"] is not None:
        lines.append(f"• длина: <b>{intent['length_m']:g} м</b>")

    if not any(intent.values()):
        lines.append("• явных фильтров мало — ищу по смыслу")

    lines.append("")

    if not rows:
        lines.append("❌ В прайсах не нашёл подходящих позиций.")
        return "\n".join(lines)

    lines.append("✅ <b>Нашёл:</b>")
    lines.append("")

    for i, row in enumerate(rows[:7], start=1):
        lines.append(f"{i}. <b>{_esc(str(row.get('product_name', '')))}</b>")
        lines.append(f"   💰 {_format_money(row.get('price'))} | 📦 {_format_stock(row.get('stock'))}")

    lines.append("")
    lines.append("📌 <b>Проверить:</b>")
    lines.append("• совместимость с конкретной моделью котла")
    lines.append("• диаметр и тип системы")
    lines.append("• длину трассы / количество колен")

    return "\n".join(lines)


def _length_patterns(length_m: float) -> list[str]:
    # 1 м может быть L-1,0м / 1000мм / 1м
    mm = int(length_m * 1000)
    comma = str(length_m).replace(".", ",")

    return [
        rf"l[- ]?{re.escape(comma)}\s*м",
        rf"{mm}\s*мм",
        rf"{int(length_m)}\s*м",
    ]


def _format_money(value: Any) -> str:
    try:
        if pd.isna(value):
            return "цена не указана"
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except Exception:
        return "цена не указана"


def _format_stock(value: Any) -> str:
    try:
        if pd.isna(value):
            return "остаток не указан"
        return f"{float(value):g} шт."
    except Exception:
        return "остаток не указан"


def _esc(value: str) -> str:
    import html
    return html.escape(str(value))
