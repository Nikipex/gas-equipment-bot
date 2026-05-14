"""Generate a sample supplier Excel file with intentional duplicates
for testing merge behavior.

Run:  python -m scripts.create_sample_xlsx
"""

from pathlib import Path

import pandas as pd


def main() -> None:
    data = {
        "Наименование": [
            # ── Group 1: same SKU (3 variations) ──────────────
            "Котел BAXI Eco Life 1.24 F",       # original
            "BAXI Eco Life 1.24F",               # shorter name, collapsed dot
            "Котел Baxi Eco Life 1 24 F",        # different spacing

            # ── Group 2: no SKU, fallback merge (3 rows) ─────
            "Радиатор Kermi FKO 22 500x1000",
            "Kermi FKO 22 500x1000",             # no prefix
            "Радиатор KERMI 500x1000 FKO 22",   # reordered words

            # ── Group 3: control — must stay separate ─────────
            "Котел Navien Deluxe S 24K",
            "Радиатор Purmo Compact 22 500x800",

            # ── Extra unique products ─────────────────────────
            "Бойлер Protherm 100 л",
            "Газовая колонка BAXI GWH 10-2 CO P",
            "Коаксиальный комплект 60/100 1м Universal",
        ],
        "Артикул": [
            # Group 1: same SKU in different formats
            "BX-ECO-124F",
            "BX ECO 124F",
            "bx-eco-124f",

            # Group 2: no SKU
            None,
            None,
            None,

            # Group 3 + extras: unique SKUs
            "NV-DLX-S24K",
            "PM-C22-800",
            "PT-BLR-100",
            "BX-GWH-10",
            "UNI-COAX-60-1",
        ],
        "Цена": [
            45200, 44800, 46000,
            8900, 9100, 8700,
            38900, 7200,
            22000, 12500, 3200,
        ],
        "Остаток": [
            12, 5, 8,
            25, 10, 18,
            8, 30,
            7, 15, 40,
        ],
        "Категория": [
            "котлы", "котлы", "котлы",
            "радиаторы", "радиаторы", "радиаторы",
            "котлы", "радиаторы",
            "бойлеры", "газовые колонки", "коаксиалы",
        ],
    }

    df = pd.DataFrame(data)
    out = Path("data/demo/supplier_sample.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out, index=False, engine="openpyxl")
    print(f"✅ Создан файл: {out}  ({len(df)} строк)")


if __name__ == "__main__":
    main()
