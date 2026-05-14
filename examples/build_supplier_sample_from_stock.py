from pathlib import Path

import pandas as pd

from app.integrations.one_c.stock_parser import parse_1c_stock_report


def detect_brand(name: str) -> str | None:
    text = str(name).lower()
    brands = ["baxi", "navien", "protherm", "kermi", "purmo", "ariston", "vaillant"]
    for brand in brands:
        if brand in text:
            return brand.title()
    return None


def detect_category(name: str) -> str:
    text = str(name).lower()

    if "котел" in text or "котёл" in text:
        return "котлы"
    if "радиатор" in text:
        return "радиаторы"
    if "бойлер" in text or "водонагреватель" in text:
        return "бойлеры"
    if "колонка" in text:
        return "газовые колонки"
    if "коаксиал" in text:
        return "коаксиалы"

    return "прочее"


def main() -> None:
    stock_file = Path("data/raw/Анализ доступности товаров на складах.xlsx")
    output_file = Path("data/demo/supplier_sample_real.xlsx")

    if not stock_file.exists():
        print(f"Не найден файл остатков: {stock_file}")
        return

    df = parse_1c_stock_report(stock_file)

    if df.empty:
        print("После парсинга остатков данных нет.")
        return

    # Берем только более-менее осмысленные товарные строки
    sample = df.copy()

    # Оставляем строки с буквами
    sample = sample[sample["product_name"].astype(str).str.contains(r"[A-Za-zА-Яа-я]", regex=True, na=False)]

    # Приоритет: реальные остатки > 0
    sample["has_stock"] = sample["free_stock_qty"] > 0

    # Бренды, которые нам интересны для матчинга
    target_brands = ["baxi", "navien", "protherm", "kermi", "purmo"]
    sample["brand"] = sample["product_name"].apply(detect_brand)
    sample = sample[
        sample["product_name"].astype(str).str.lower().str.contains("|".join(target_brands), na=False)
    ].copy()

    if sample.empty:
        print("Не найдено брендовых позиций для построения supplier sample.")
        return

    sample["category"] = sample["product_name"].apply(detect_category)

    # Сортируем: сначала товары с остатком, потом по имени
    sample = sample.sort_values(["has_stock", "product_name"], ascending=[False, True])

    # Берем ограниченный набор
    sample = sample.head(30).copy()

    # Формируем supplier-like таблицу
    supplier_df = pd.DataFrame(
        {
            "Наименование": sample["product_name"],
            "Артикул": [None] * len(sample),
            "Цена": [None] * len(sample),
            "Остаток": [None] * len(sample),  # supplier stock тут неважен, это тест пересечения
            "Категория": sample["category"],
        }
    )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    supplier_df.to_excel(output_file, index=False)

    print(f"Создан файл: {output_file}")
    print(f"Строк: {len(supplier_df)}")
    print("\nПример:")
    print(supplier_df.head(15).to_string(index=False))


if __name__ == "__main__":
    main()