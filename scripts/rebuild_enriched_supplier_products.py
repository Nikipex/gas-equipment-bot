from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.services.equipment.supplier_product_enricher import enrich_product


SOURCE = Path("data/supplier_prices/processed/supplier_products.csv")
TARGET = Path("data/supplier_prices/processed/enriched_supplier_products.csv")


def main() -> None:
    df = pd.read_csv(SOURCE)

    facts_rows = []

    for _, row in df.iterrows():
        name = str(row.get("product_name", ""))
        facts = enrich_product(name)

        facts_rows.append(
            {
                "category": facts.category,
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
    print(out[["product_name", "category", "boiler_type", "power_kw", "volume_l", "form_factor", "circuits", "orientation", "gas_automation", "connection", "chimney_diameter_mm", "body_shape", "flue_exit", "is_accessory"]].head(30).to_string())


if __name__ == "__main__":
    main()
