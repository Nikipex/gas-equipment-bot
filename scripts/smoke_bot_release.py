from __future__ import annotations

import asyncio
import importlib
import subprocess
import sys
from pathlib import Path

import pandas as pd


REQUIRED_FILES = [
    "data/supplier_prices/processed/supplier_products.csv",
    "data/supplier_prices/processed/enriched_supplier_products.csv",
    "app/bot/handlers/equipment_selector.py",
    "scripts/test_equipment_quality.py",
]


def ok(name: str) -> None:
    print(f"✅ {name}")


def fail(name: str, error: object) -> None:
    print(f"❌ {name}")
    print(f"   {error}")
    raise SystemExit(1)


def check_files() -> None:
    for path in REQUIRED_FILES:
        if not Path(path).exists():
            fail("required files", f"missing: {path}")
    ok("required files exist")


def check_compile() -> None:
    files = [
        "app/bot/handlers/equipment_selector.py",
        "app/services/ai/equipment_intent_parser.py",
        "app/services/equipment/product_specs_service.py",
        "app/services/equipment/quote_builder_service.py",
        "app/services/equipment/product_analog_service.py",
        "app/services/equipment/chimney_enricher.py",
        "app/services/equipment/chimney_search_service.py",
        "scripts/rebuild_enriched_supplier_products.py",
        "scripts/test_equipment_quality.py",
    ]

    for file in files:
        subprocess.run([sys.executable, "-m", "py_compile", file], check=True)

    ok("python compile")


def check_imports() -> None:
    modules = [
        "app.bot.handlers.equipment_selector",
        "app.services.ai.equipment_intent_parser",
        "app.services.equipment.equipment_search_pipeline",
        "app.services.equipment.product_specs_service",
        "app.services.equipment.quote_builder_service",
        "app.services.equipment.product_analog_service",
        "app.services.equipment.chimney_search_service",
    ]

    for module in modules:
        importlib.import_module(module)

    ok("critical imports")


def check_enriched_csv() -> None:
    df = pd.read_csv("data/supplier_prices/processed/enriched_supplier_products.csv")

    if len(df) < 100:
        fail("enriched csv", f"too few rows: {len(df)}")

    required_cols = [
        "product_name",
        "price",
        "stock",
        "category",
        "boiler_type",
        "power_kw",
        "volume_l",
        "form_factor",
        "chimney_system",
        "chimney_type",
        "chimney_diameter",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        fail("enriched csv columns", f"missing columns: {missing}")

    checks = {
        "boilers": df["category"].eq("boiler").sum(),
        "water_heaters": df["category"].eq("water_heater").sum(),
        "chimney": df["category"].eq("chimney").sum(),
        "coaxial": df["chimney_system"].eq("coaxial").sum(),
        "classic_chimney": df["chimney_system"].eq("classic").sum(),
    }

    for name, count in checks.items():
        if count <= 0:
            fail("enriched csv content", f"{name} count is zero")

    ok("enriched csv structure/content")


async def check_core_scenarios() -> None:
    from app.services.ai.equipment_intent_parser import EquipmentIntentParser
    from app.services.equipment.equipment_search_pipeline import EquipmentSearchPipeline
    from app.services.equipment.product_specs_service import ProductSpecsService
    from app.services.equipment.quote_builder_service import QuoteBuilderService
    from app.services.equipment.product_analog_service import ProductAnalogService
    from app.services.equipment.chimney_search_service import ChimneySearchService

    parser = EquipmentIntentParser()
    pipeline = EquipmentSearchPipeline()
    specs = ProductSpecsService()
    quote = QuoteBuilderService()
    analogs = ProductAnalogService()
    chimney = ChimneySearchService()

    intent = await parser.parse("подбери бойлер плоский настенный, на 50 литров")
    if intent.category != "water_heater" or intent.form_factor != "flat" or intent.volume_l != 50:
        fail("intent parser", intent)

    result = await pipeline.search(intent)
    if not result.candidates:
        fail("equipment search", "no candidates for flat 50l water heater")

    if not specs.find("Лемакс Патриот 10"):
        fail("product specs", "Лемакс Патриот 10 not found")

    quote_lines = quote.build("""
-7% округлить до 100
Лемакс Патриот 10 x2
Ariston PRO1 R 80 DRY x1
""")
    if len(quote_lines) != 2:
        fail("quote builder", f"expected 2 lines, got {len(quote_lines)}")

    source, analog_rows = analogs.find_analogs("Бакси ECO LIFE 24F")
    if not source or not analog_rows:
        fail("analog search", "Baxi analogs not found")

    analog_names = " ".join(str(x.get("product_name", "")).lower() for x in analog_rows)
    if "эван" in analog_names or "лемакс газовик" in analog_names:
        fail("analog search", f"garbage analog found: {analog_names[:300]}")

    chimney_rows = chimney.search("коаксиальный комплект 60/100")
    if not chimney_rows:
        fail("chimney search", "coaxial kit not found")

    condensate_rows = chimney.search("конденсатосборник 60/100")
    if not condensate_rows:
        fail("chimney search", "condensate 60/100 not found")

    ok("core service scenarios")


def run_quality_gate() -> None:
    subprocess.run([sys.executable, "scripts/test_equipment_quality.py"], check=True)
    ok("quality gate")


async def main() -> None:
    print("=" * 100)
    print("BOT RELEASE SMOKE TEST")
    print("=" * 100)

    check_files()
    check_compile()
    check_imports()
    check_enriched_csv()
    await check_core_scenarios()
    run_quality_gate()

    print("=" * 100)
    print("✅ RELEASE SMOKE PASSED")
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
