from pathlib import Path

from app.integrations.one_c.stock_parser import parse_1c_stock_report


def main() -> None:
    print("DEMO STARTED")

    candidates = [
        Path("data/raw/Анализ доступности товаров на складах.xlsx"),
        Path("data/raw/Остатки 06.04.26.xls"),
        Path("data/demo/Анализ доступности товаров на складах.xlsx"),
        Path("Анализ доступности товаров на складах.xlsx"),
    ]

    file_path = next((p for p in candidates if p.exists()), None)

    if file_path is None:
        print("Файл остатков не найден.")
        print("Положи его в один из путей:")
        for candidate in candidates:
            print(f" - {candidate}")
        return

    df = parse_1c_stock_report(file_path)

    print(f"\nФайл: {file_path}")
    print(f"Строк распарсено: {len(df)}\n")

    if df.empty:
        print("Нет данных после парсинга.")
        return

    preview = df[["product_name", "free_stock_qty", "product_key"]].head(20)
    print(preview.to_string(index=False))


if __name__ == "__main__":
    main()