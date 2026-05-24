from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.services.equipment.supplier_product_enricher import enrich_product
from app.services.equipment.chimney_enricher import enrich_chimney


SOURCE = Path("data/supplier_prices/processed/supplier_products.csv")
TARGET = Path("data/supplier_prices/processed/enriched_supplier_products.csv")


def main() -> None:
    df = pd.read_csv(SOURCE)

    facts_rows = []

    for _, row in df.iterrows():
        name = str(row.get("product_name", ""))
        facts = enrich_product(name)
        chimney_data = enrich_chimney({"product_name": name})

        facts_rows.append(
            {
                "category": chimney_data.get("category") or facts.category,
                "equipment_type": facts.equipment_type,
                "boiler_type": facts.boiler_type,
                "power_kw": facts.power_kw,
                "volume_l": facts.volume_l,
                "form_factor": facts.form_factor,
                "circuits": facts.circuits,
                "orientation": facts.orientation,
                "gas_automation": facts.gas_automation,
                "connection": facts.connection,
                "chimney_diameter_mm": facts.chimney_diameter_mm,
                "body_shape": facts.body_shape,
                "flue_exit": facts.flue_exit,
                "is_accessory": facts.is_accessory,
                "chimney_system": chimney_data.get("chimney_system"),
                "chimney_type": chimney_data.get("chimney_type"),
                "chimney_diameter": chimney_data.get("chimney_diameter"),
                "chimney_brand": chimney_data.get("chimney_brand"),
            }
        )

    facts_df = pd.DataFrame(facts_rows)
    out = pd.concat([df, facts_df], axis=1)

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(TARGET, index=False)

    print("SOURCE:", SOURCE)
    print("TARGET:", TARGET)
    print("ROWS:", len(out))
    print()

    preview_cols = [
        "product_name",
        "category",
        "boiler_type",
        "power_kw",
        "volume_l",
        "form_factor",
        "circuits",
        "orientation",
        "gas_automation",
        "connection",
        "chimney_system",
        "chimney_type",
        "chimney_diameter",
        "chimney_brand",
        "body_shape",
        "flue_exit",
        "is_accessory",
    ]

    existing_cols = [c for c in preview_cols if c in out.columns]
    print(out[existing_cols].head(30).to_string())


if __name__ == "__main__":
    main()
