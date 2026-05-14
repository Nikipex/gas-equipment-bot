"""End-to-end demo: import an Excel file → search products.

Run from the project root::

    python -m examples.import_demo
"""

from __future__ import annotations

from pathlib import Path
from app.integrations.one_c.stock_parser import parse_1c_stock_report

from app.services.import_service import ImportService
from app.services.merge_service import MergeService
from app.services.pricing_service import PricingService
from app.services.search_service import SearchService


def main() -> None:
    sample_path = Path("data/demo/supplier_sample_real.xlsx")

    if not sample_path.exists():
        print("❌ Реальный demo-файл не найден. Сначала создайте его:")
        print("   PYTHONPATH=. python examples/build_supplier_sample_from_stock.py")
        return

    # ── 1. Import ──────────────────────────────────────────────
    importer = ImportService()
    products = importer.import_file(sample_path)

    print(f"\n📦 Импортировано товаров: {len(products)}\n")
    for p in products:
        print(f"  • {p.name}  |  бренд={p.brand}  |  артикул={p.sku}  |  цена={p.price}  |  остаток={p.stock}")

    # ── 1b. Merge ─────────────────────────────────────────────
    merger = MergeService(products)
    groups = merger.merge_products()

    print(f"\n🔗 Дедупликация: {len(products)} товаров → {len(groups)} групп\n")
    for g in groups:
        tag = "🟢" if len(g.products) > 1 else "⚪"
        print(f"  {tag} [GROUP] {g.canonical_name}")
        print(f"     key={g.group_key}  |  sku={g.sku}  |  items={len(g.products)}")
        for p in g.products:
            print(f"       - {p.name}  (sku={p.sku}, цена={p.price})")
        print()


    # ── 2. Search ──────────────────────────────────────────────
    search = SearchService(products)

    for q in ["baxi", "navien", "коаксиальный", "котел baxi eco nova 24f"]:
        print(f"\n🔎 Поиск: «{q}»")
        results = search.search(q, top_n=5)
        if not results:
            print("   (ничего не найдено)")
        for r in results:
            print(f"   [{r.score:>6.1f}]  {r.product.name}  ({r.product.brand}) [{r.product.category}]")

    # ── 3. Mini-price (merge-aware) ───────────────────────────
    stock_file = Path("data/raw/Анализ доступности товаров на складах.xlsx")
    stock_df = parse_1c_stock_report(stock_file) if stock_file.exists() else None
    pricing = PricingService(products, stock_df=stock_df)

    print("\n" + "═" * 50)

    for q in ["baxi", "navien", "котел baxi eco nova 24f", "водонагреватель baxi"]:
        print(f"\n📦 Мини-прайс: '{q}'")
        result = pricing.format_miniprice(pricing.get_miniprice(q))
        print(result)
        if stock_df is None:
            print("   (1C stock file не найден, обогащение остатками пропущено)")

    print("\n✅ Демо завершено успешно!")



if __name__ == "__main__":
    main()
