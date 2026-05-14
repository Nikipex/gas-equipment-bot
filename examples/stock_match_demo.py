from pathlib import Path

from app.integrations.one_c.stock_parser import parse_1c_stock_report
from app.services.import_service import ImportService
from app.services.stock_match_service import StockMatchService


def main():
    print("🚀 DEMO START")

    supplier_file = Path("data/demo/supplier_sample_real.xlsx")
    stock_file = Path("data/raw/Анализ доступности товаров на складах.xlsx")

    if not supplier_file.exists():
        print(f"Не найден supplier file: {supplier_file}")
        print("Сначала создай его через build_supplier_sample_from_stock.py")
        return

    if not stock_file.exists():
        print(f"Не найден stock file: {stock_file}")
        return

    products = ImportService().import_file(supplier_file)
    print(f"Загружено товаров поставщика: {len(products)}")

    stock_df = parse_1c_stock_report(stock_file)
    print(f"Строк остатков: {len(stock_df)}")

    # 🔍 Диагностика: есть ли бренды из supplier в остатках
    print("\n🔎 Проверка наличия брендов в остатках:")
    keywords = ["baxi", "kermi", "purmo", "navien", "protherm"]

    for keyword in keywords:
        subset = stock_df[
            stock_df["product_name"].astype(str).str.lower().str.contains(keyword, na=False)
        ]
        print(f"\n=== {keyword.upper()} ===")
        print(f"Найдено строк: {len(subset)}")

        if not subset.empty:
            print(subset[["product_name", "free_stock_qty"]].head(10).to_string(index=False))

    matcher = StockMatchService(stock_df)
    matcher.build_index()

    results = matcher.match_products(products[:20])

    matched_count = sum(1 for r in results if r.matched)
    print(f"\nСовпадений найдено: {matched_count}/{len(results)}")

    for r in results:
        print("\n" + "-" * 60)
        print(f"Товар: {r.product.name}")
        print(f"Matched: {r.matched}")
        print(f"Причина: {r.match_reason}")
        print(f"Остаток: {r.total_qty}")
        print(f"Склад: {r.first_warehouse}")
        print(f"Название в 1С: {r.first_stock_name}")


if __name__ == "__main__":
    main()