from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from app.services.equipment.supplier_product_enricher import enrich_product


ENRICHED_PATH = Path("data/supplier_prices/processed/enriched_supplier_products.csv")


class ProductSpecsService:
    def __init__(self, path: Path = ENRICHED_PATH) -> None:
        self.path = path

    def find(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        df = pd.read_csv(self.path)
        if df.empty or "product_name" not in df.columns:
            return []

        q = _norm(query)
        q_tokens = [x for x in q.split() if len(x) >= 2]

        if not q_tokens:
            return []

        names = df["product_name"].astype(str)
        norm_names = names.map(_norm)

        score = pd.Series(0, index=df.index, dtype=float)

        for token in q_tokens:
            score += norm_names.str.contains(token, regex=False).astype(int) * 10

        # бонус за полную подстроку
        score += norm_names.str.contains(q, regex=False).astype(int) * 50

        out = df.copy()
        out["spec_score"] = score
        out = out[out["spec_score"] > 0]
        out = out.sort_values(["spec_score", "stock"], ascending=[False, False], na_position="last")

        return out.head(limit).to_dict("records")


def build_specs_text(row: dict[str, Any]) -> str:
    name = str(row.get("product_name", ""))
    facts = enrich_product(name)

    lines = [
        "📋 <b>Характеристики товара</b>",
        "",
        f"<b>{_esc(name)}</b>",
        "",
    ]

    price = _format_money(row.get("price"))
    stock = _format_stock(row.get("stock"))

    lines.append(f"💰 Цена: <b>{price}</b>")
    lines.append(f"📦 Остаток: <b>{stock}</b>")

    supplier = row.get("supplier_name") or row.get("supplier_key")
    if supplier and str(supplier) != "nan":
        lines.append(f"🏷 Поставщик: <b>{_esc(str(supplier))}</b>")

    lines.append("")
    lines.append("🧾 <b>Что удалось распознать:</b>")

    specs = []

    if facts.category:
        specs.append(("Категория", _label_category(facts.category)))

    if facts.boiler_type:
        specs.append(("Тип котла", _label_boiler_type(facts.boiler_type)))

    if facts.equipment_type and facts.category == "water_heater":
        specs.append(("Тип бойлера", _label_water_heater_type(facts.equipment_type)))

    if facts.power_kw:
        specs.append(("Мощность", f"{facts.power_kw:g} кВт"))

    if facts.volume_l:
        specs.append(("Объём", f"{facts.volume_l} л"))

    if getattr(facts, "circuits", None):
        specs.append(("Контуры", str(facts.circuits)))

    if getattr(facts, "form_factor", None):
        specs.append(("Форма бойлера", _label_form_factor(facts.form_factor)))

    if getattr(facts, "body_shape", None):
        specs.append(("Корпус котла", _label_body_shape(facts.body_shape)))

    if getattr(facts, "flue_exit", None):
        specs.append(("Выход дымохода", _label_flue_exit(facts.flue_exit)))

    if getattr(facts, "gas_automation", None):
        specs.append(("Автоматика", facts.gas_automation.upper()))

    if getattr(facts, "connection", None):
        specs.append(("Подвод", "боковой"))

    if getattr(facts, "chimney_diameter_mm", None):
        specs.append(("Дымоход", f"{facts.chimney_diameter_mm} мм"))

    if facts.is_accessory:
        specs.append(("Тип позиции", "похоже на аксессуар / комплектующую"))

    if specs:
        for key, value in specs:
            lines.append(f"• {key}: <b>{_esc(value)}</b>")
    else:
        lines.append("• Автоматически распознанных характеристик мало — лучше уточнить по карточке поставщика.")

    lines.append("")
    lines.append("📌 <b>Менеджеру проверить:</b>")
    lines.append("• актуальность цены")
    lines.append("• остаток перед выставлением КП")
    lines.append("• совместимость с задачей клиента")

    return "\n".join(lines)


def _norm(value: object) -> str:
    import re

    text = str(value or "").lower().replace("ё", "е")
    text = text.replace(",", ".")
    text = re.sub(r"[^a-zа-я0-9.]+", " ", text)
    return re.sub(r"\\s+", " ", text).strip()


def _esc(value: str) -> str:
    import html

    return html.escape(str(value))


def _format_money(value: object) -> str:
    try:
        if pd.isna(value):
            return "не указана"
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except Exception:
        return "не указана"


def _format_stock(value: object) -> str:
    try:
        if pd.isna(value):
            return "не указан"
        return f"{float(value):g} шт."
    except Exception:
        return "не указан"


def _label_category(value: str) -> str:
    return {
        "boiler": "котёл",
        "water_heater": "бойлер / водонагреватель",
        "pump": "насос",
        "radiator": "радиатор",
        "chimney": "дымоход / коаксиал",
    }.get(value, value)


def _label_boiler_type(value: str) -> str:
    return {
        "wall": "настенный",
        "floor": "напольный",
        "parapet": "парапетный",
    }.get(value, value)


def _label_water_heater_type(value: str) -> str:
    return {
        "electric": "электрический",
        "indirect": "косвенного нагрева",
        "tank_in_tank": "бак-в-баке",
    }.get(value, value)


def _label_form_factor(value: str) -> str:
    return {
        "flat": "плоский",
        "round": "круглый",
    }.get(value, value)


def _label_body_shape(value: str) -> str:
    return {
        "round": "круглый",
        "rectangular": "прямоугольный",
    }.get(value, value)


def _label_flue_exit(value: str) -> str:
    return {
        "vertical": "верхний / вертикальный",
        "horizontal": "задний / горизонтальный",
    }.get(value, value)
