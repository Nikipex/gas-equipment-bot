from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from app.services.ai.equipment_intent_parser import EquipmentIntent


ENRICHED_PATH = Path("data/supplier_prices/processed/enriched_supplier_products.csv")


class EnrichedSupplierSearchService:
    def __init__(self, path: Path = ENRICHED_PATH) -> None:
        self.path = path

    def search(self, intent: EquipmentIntent, limit: int = 20) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame()

        df = pd.read_csv(self.path)

        if df.empty:
            return df

        df = self._filter(intent, df)
        df = self._score(intent, df)

        if "match_score" in df.columns:
            df = df.sort_values(
                by=["match_score", "stock", "price"],
                ascending=[False, False, True],
                na_position="last",
            )

        return df.head(limit)

    def _filter(self, intent: EquipmentIntent, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()

        if "is_accessory" in out.columns:
            out = out[out["is_accessory"] != True]

        if intent.category and "category" in out.columns:
            out = out[out["category"] == intent.category]

        if intent.category == "boiler":
            if getattr(intent, "boiler_type", None) and "boiler_type" in out.columns:
                out = out[out["boiler_type"] == intent.boiler_type]

            if intent.power_kw and "power_kw" in out.columns:
                out = out[out["power_kw"].notna()]
                out = out[(out["power_kw"] - float(intent.power_kw)).abs() <= 1.0]

        if intent.category == "water_heater":
            if getattr(intent, "water_heater_type", None) and "equipment_type" in out.columns:
                out = out[out["equipment_type"] == intent.water_heater_type]

            min_l = intent.volume_min_l
            max_l = intent.volume_max_l

            if intent.volume_l and not min_l and not max_l:
                min_l = max(intent.volume_l - 5, 0)
                max_l = intent.volume_l + 5

            if min_l and max_l and "volume_l" in out.columns:
                out = out[out["volume_l"].notna()]
                out = out[(out["volume_l"] >= min_l) & (out["volume_l"] <= max_l)]

        name = out["product_name"].astype(str).str.lower().str.replace("ё", "е", regex=False)

        if intent.brand:
            brand = _brand_aliases(intent.brand)
            mask = False
            for item in brand:
                mask = mask | name.str.contains(item, regex=False)

            # Бренд — критичный фильтр. Если в enriched нет бренда,
            # лучше вернуть пусто и дать pipeline уйти в старый fuzzy/fallback,
            # чем показать Midea/Thermex по запросу Ariston.
            out = out[mask]
            name = out["product_name"].astype(str).str.lower().str.replace("ё", "е", regex=False)

        if intent.category == "water_heater":
            if getattr(intent, "heating_element", None) == "dry":
                mask = (
                    name.str.contains("сухой тэн", regex=False)
                    | name.str.contains("сухой тен", regex=False)
                    | name.str.contains("dry", regex=False)
                )
                out = out[mask]

            elif getattr(intent, "heating_element", None) == "wet":
                mask = (
                    name.str.contains("мокрый тэн", regex=False)
                    | name.str.contains("мокрый тен", regex=False)
                )
                out = out[mask]

            if getattr(intent, "tank_material", None) == "stainless":
                name = out["product_name"].astype(str).str.lower().str.replace("ё", "е", regex=False)
                out = out[
                    name.str.contains("нерж", regex=False)
                    | name.str.contains("inox", regex=False)
                ]

            if getattr(intent, "tank_coating", None) == "enamel":
                name = out["product_name"].astype(str).str.lower().str.replace("ё", "е", regex=False)
                out = out[
                    name.str.contains("эмаль", regex=False)
                    | name.str.contains("биостекло", regex=False)
                    | name.str.contains("стеклофарфор", regex=False)
                ]

        return out

    def _score(self, intent: EquipmentIntent, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        score = pd.Series(0, index=out.index, dtype=float)

        if "stock" in out.columns:
            score += out["stock"].fillna(0).clip(lower=0).clip(upper=100) * 0.01

        if intent.power_kw and "power_kw" in out.columns:
            score += (1.0 - (out["power_kw"].fillna(intent.power_kw) - intent.power_kw).abs().clip(upper=5) / 5) * 20

        if intent.volume_l and "volume_l" in out.columns:
            score += (1.0 - (out["volume_l"].fillna(intent.volume_l) - intent.volume_l).abs().clip(upper=50) / 50) * 20

        name = out["product_name"].astype(str).str.lower().str.replace("ё", "е", regex=False)

        if intent.category == "boiler":
            if getattr(intent, "boiler_type", None) == "parapet":
                score += name.str.contains("парапет|патриот|ксгз", regex=True).astype(int) * 30

            if getattr(intent, "boiler_type", None) == "floor":
                score += name.str.contains("ксг|аогв|tgv", regex=True).astype(int) * 20

        if intent.brand:
            for alias in _brand_aliases(intent.brand):
                score += name.str.contains(alias, regex=False).astype(int) * 30

        out["match_score"] = score
        return out


def _brand_aliases(brand: str) -> list[str]:
    key = brand.lower().replace("ё", "е")

    aliases: dict[str, list[str]] = {
        "baxi": ["baxi", "бакси"],
        "ariston": ["ariston", "аристон"],
        "navien": ["navien", "навьен", "навиен"],
        "ferroli": ["ferroli", "ферроли"],
        "thermex": ["thermex", "термекс"],
        "midea": ["midea", "мидеа"],
        "lemax": ["lemaks", "лемакс"],
        "лемакс": ["lemaks", "лемакс"],
    }

    return aliases.get(key, [key])
