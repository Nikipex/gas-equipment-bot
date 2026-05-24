from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from app.services.equipment.product_specs_service import ProductSpecsService
from app.services.equipment.supplier_product_enricher import enrich_product


ENRICHED_PATH = Path("data/supplier_prices/processed/enriched_supplier_products.csv")


class ProductAnalogService:
    def __init__(self, path: Path = ENRICHED_PATH) -> None:
        self.path = path
        self.specs = ProductSpecsService(path)

    def find_analogs(self, query: str, limit: int = 7) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        source_matches = self.specs.find(query, limit=1)
        if not source_matches:
            return None, []

        source = source_matches[0]
        source_name = str(source.get("product_name", ""))
        source_facts = enrich_product(source_name)
        source_category = source_facts.category or _infer_category_from_name(source_name)

        if not self.path.exists():
            return source, []

        df = pd.read_csv(self.path)
        if df.empty or "product_name" not in df.columns:
            return source, []

        out = df.copy()
        out["product_name_norm"] = out["product_name"].astype(str).map(_norm)

        source_norm = _norm(source_name)
        source_brand = _detect_brand(source_name)

        # Не возвращаем сам товар
        out = out[out["product_name_norm"] != source_norm]

        # Категория обязательна, если смогли определить.
        # Но у части товаров enriched category может быть пустой,
        # поэтому добавляем fallback по названию кандидата.
        if source_category and "category" in out.columns:
            out["_candidate_category"] = out["category"]
            missing_category = out["_candidate_category"].isna()

            out.loc[missing_category, "_candidate_category"] = out.loc[
                missing_category,
                "product_name",
            ].map(_infer_category_from_name)

            out = out[out["_candidate_category"] == source_category]

        # Для котлов сохраняем ключевые технические параметры
        if source_category == "boiler":
            name = out["product_name_norm"]

            # Отсекаем электрокотлы и комплектуху, если исходник газовый.
            if not any(x in _norm(source_name) for x in ["электро", "эван"]):
                out = out[~name.str.contains("электрокотел|электр", regex=True, na=False)]

            out = _filter_optional(out, "boiler_type", source_facts.boiler_type)
            out = _filter_power_close(out, source_facts.power_kw, tolerance=1.5)

            # Для парапетников контурность часто не указана в названии,
            # поэтому не убиваем аналоги типа Артек КСГЗ-10-А.
            circuits_soft = source_facts.boiler_type == "parapet"
            out = _filter_optional(out, "circuits", getattr(source_facts, "circuits", None), soft=circuits_soft)

            out = _filter_optional(out, "chamber", getattr(source_facts, "chamber", None))
            out = _filter_optional(out, "gas_automation", getattr(source_facts, "gas_automation", None), soft=True)

        # Для бойлеров сохраняем объем/тип/форму/ТЭН/бак, если есть
        elif source_category == "water_heater":
            out = _filter_optional(out, "equipment_type", source_facts.equipment_type)
            out = _filter_volume_close(out, source_facts.volume_l, tolerance=10)
            out = _filter_optional(out, "form_factor", getattr(source_facts, "form_factor", None), soft=True)
            out = _filter_optional(out, "heating_element", getattr(source_facts, "heating_element", None), soft=True)
            out = _filter_optional(out, "tank_material", getattr(source_facts, "tank_material", None), soft=True)
            out = _filter_optional(out, "tank_coating", getattr(source_facts, "tank_coating", None), soft=True)

        # По возможности убираем тот же бренд, чтобы показать именно замену
        if source_brand:
            brand_mask = out["product_name_norm"].str.contains(source_brand, regex=False, na=False)
            no_brand = out[~brand_mask]
            if not no_brand.empty:
                out = no_brand

        source_low = _norm(source_name)

        # Отсечка явного мусора для настенных газовых котлов 24F/24K.
        # Не требуем турбо/двухконтурность жестко, чтобы не потерять Vaillant/прочие аналоги.
        if source_category == "boiler" and any(x in source_low for x in ["24f", "24k", "турбо", "без трубы"]):
            name = out["product_name_norm"]

            out = out[~name.str.contains("электрокотел|электр|эван", regex=True, na=False)]
            out = out[~name.str.contains("аогв|ксг|кс-г|ксгв|газовик|арту|artu|патриот|парапет|наполь", regex=True, na=False)]

            name = out["product_name_norm"]
            wall_like = name.str.contains("24f|24k|24 квт|24квт|vuw|turbo|турбо|atmo|настен|закр|без трубы|двухконт", regex=True, na=False)
            if wall_like.any():
                out = out.loc[wall_like]

        if out.empty:
            return source, []

        out["analog_score"] = _score_analogs(out, source_facts)
        out = out.sort_values(
            ["analog_score", "stock", "price"],
            ascending=[False, False, True],
            na_position="last",
        )

        return source, out.head(limit).to_dict("records")


def build_analogs_text(source: dict[str, Any] | None, analogs: list[dict[str, Any]]) -> str:
    if source is None:
        return "❌ Не нашёл исходный товар в прайсах. Попробуй указать бренд/модель точнее."

    source_name = str(source.get("product_name", ""))
    source_facts = enrich_product(source_name)

    lines = [
        "🔁 <b>Аналоги товара</b>",
        "",
        "Исходная позиция:",
        f"<b>{_esc(source_name)}</b>",
        "",
        "🧾 <b>Ключевые признаки:</b>",
    ]

    facts = _format_source_facts(source_facts)
    lines.extend(facts or ["• мало распознанных признаков — аналоги могут быть примерными"])

    lines.append("")

    if not analogs:
        lines.append("❌ В прайсах не нашёл близких аналогов.")
        return "\n".join(lines)

    lines.append("✅ <b>Возможные аналоги:</b>")
    lines.append("")

    for idx, row in enumerate(analogs, start=1):
        lines.append(f"{idx}. <b>{_esc(str(row.get('product_name', '')))}</b>")
        lines.append(f"   💰 {_format_money(row.get('price'))} | 📦 {_format_stock(row.get('stock'))}")

    lines.append("")
    lines.append("📌 <b>Перед заменой проверить:</b>")
    lines.append("• мощность / объём")
    lines.append("• монтаж и подключение")
    lines.append("• совместимость с задачей клиента")
    lines.append("• гарантию и актуальный остаток")

    return "\n".join(lines)


def _filter_optional(df: pd.DataFrame, column: str, value: Any, *, soft: bool = False) -> pd.DataFrame:
    if value is None or column not in df.columns:
        return df

    x = df[df[column] == value]

    if soft and x.empty:
        return df

    return x


def _filter_power_close(df: pd.DataFrame, power_kw: float | None, *, tolerance: float) -> pd.DataFrame:
    if power_kw is None or "power_kw" not in df.columns:
        return df

    x = df[df["power_kw"].notna()]
    x = x[(x["power_kw"] - float(power_kw)).abs() <= tolerance]
    return x if not x.empty else df


def _filter_volume_close(df: pd.DataFrame, volume_l: int | None, *, tolerance: int) -> pd.DataFrame:
    if volume_l is None or "volume_l" not in df.columns:
        return df

    x = df[df["volume_l"].notna()]
    x = x[(x["volume_l"] - int(volume_l)).abs() <= tolerance]
    return x if not x.empty else df


def _score_analogs(df: pd.DataFrame, facts: Any) -> pd.Series:
    score = pd.Series(0, index=df.index, dtype=float)

    for col, value, weight in [
        ("category", facts.category, 100),
        ("boiler_type", getattr(facts, "boiler_type", None), 30),
        ("equipment_type", getattr(facts, "equipment_type", None), 30),
        ("circuits", getattr(facts, "circuits", None), 25),
        ("form_factor", getattr(facts, "form_factor", None), 20),
        ("heating_element", getattr(facts, "heating_element", None), 20),
        ("tank_material", getattr(facts, "tank_material", None), 15),
        ("tank_coating", getattr(facts, "tank_coating", None), 15),
    ]:
        if value is not None and col in df.columns:
            score += (df[col] == value).astype(int) * weight

    if getattr(facts, "power_kw", None) and "power_kw" in df.columns:
        diff = (df["power_kw"] - float(facts.power_kw)).abs()
        score += diff.fillna(999).map(lambda x: max(0, 30 - x * 10))

    if getattr(facts, "volume_l", None) and "volume_l" in df.columns:
        diff = (df["volume_l"] - int(facts.volume_l)).abs()
        score += diff.fillna(999).map(lambda x: max(0, 30 - x))

    return score


def _format_source_facts(facts: Any) -> list[str]:
    out = []

    if facts.category:
        out.append(f"• категория: <b>{_esc(_label_category(facts.category))}</b>")

    if getattr(facts, "boiler_type", None):
        out.append(f"• тип котла: <b>{_esc(_label_boiler_type(facts.boiler_type))}</b>")

    if getattr(facts, "power_kw", None):
        out.append(f"• мощность: <b>{facts.power_kw:g} кВт</b>")

    if getattr(facts, "volume_l", None):
        out.append(f"• объём: <b>{facts.volume_l} л</b>")

    if getattr(facts, "circuits", None):
        out.append(f"• контуры: <b>{facts.circuits}</b>")

    if getattr(facts, "form_factor", None):
        out.append(f"• форма: <b>{_esc(_label_form_factor(facts.form_factor))}</b>")

    if getattr(facts, "heating_element", None):
        out.append(f"• ТЭН: <b>{_esc(_label_heating_element(facts.heating_element))}</b>")

    return out



def _infer_category_from_name(name: str) -> str | None:
    low = _norm(name)

    if any(x in low for x in [
        "котел",
        "котёл",
        "24f",
        "24k",
        "турбо",
        "eco life",
        "eco nova",
        "eco four",
        "vuw",
        "аогв",
        "ксг",
    ]):
        return "boiler"

    if any(x in low for x in [
        "бойлер",
        "водонагрев",
        "pro1",
        "vls",
        "mwh",
        "thermex",
    ]):
        return "water_heater"

    return None


def _detect_brand(name: str) -> str | None:
    low = _norm(name)

    brands = [
        "baxi", "бакси", "navien", "навьен", "ariston", "аристон",
        "ferroli", "ферроли", "midea", "мидеа", "thermex", "термекс",
        "лемакс", "orso", "rga", "vargaz",
    ]

    for brand in brands:
        if brand in low:
            return brand

    return None


def _norm(value: object) -> str:
    import re

    text = str(value or "").lower().replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _esc(value: str) -> str:
    import html
    return html.escape(str(value))


def _format_money(value: object) -> str:
    try:
        if pd.isna(value):
            return "цена не указана"
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except Exception:
        return "цена не указана"


def _format_stock(value: object) -> str:
    try:
        if pd.isna(value):
            return "остаток не указан"
        return f"{float(value):g} шт."
    except Exception:
        return "остаток не указан"


def _label_category(value: str) -> str:
    return {
        "boiler": "котёл",
        "water_heater": "бойлер / водонагреватель",
    }.get(value, value)


def _label_boiler_type(value: str) -> str:
    return {
        "wall": "настенный",
        "floor": "напольный",
        "parapet": "парапетный",
    }.get(value, value)


def _label_form_factor(value: str) -> str:
    return {
        "flat": "плоский",
        "round": "круглый",
    }.get(value, value)


def _label_heating_element(value: str) -> str:
    return {
        "dry": "сухой",
        "wet": "мокрый",
    }.get(value, value)
