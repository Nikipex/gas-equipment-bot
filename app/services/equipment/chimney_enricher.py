import re


def enrich_chimney(row: dict) -> dict:
    name = str(row.get("product_name", "")).lower()

    row["chimney_system"] = None
    row["chimney_type"] = None
    row["chimney_diameter"] = None
    row["chimney_brand"] = None

    if "коакс" in name:
        row["category"] = "chimney"
        row["chimney_system"] = "coaxial"

    elif "дымоход" in name:
        row["category"] = "chimney"
        row["chimney_system"] = "classic"

    mapping = {
        "конденсат": "condensate",
        "адаптер": "adapter",
        "колено": "elbow",
        "отвод": "elbow",
        "труба": "pipe",
        "удлин": "extension",
        "комплект": "kit",
        "зонт": "cap",
        "тройник": "tee",
        "фланец": "flange",
        "заглуш": "plug",
    }

    for k, v in mapping.items():
        if k in name:
            row["chimney_type"] = v
            break

    m = re.search(r"(60/100|80/125|80/80|110/160)", name)

    if m:
        row["chimney_diameter"] = m.group(1)

    else:
        m = re.search(
            r"(?:диам|диаметр|d|dn|ø)\s*[- ]*\s*(\d{2,3})",
            name,
        )

        if m:
            row["chimney_diameter"] = m.group(1)

    brands = [
        "baxi",
        "ariston",
        "vaillant",
        "bosch",
        "navien",
        "immergas",
    ]

    for b in brands:
        if b in name:
            row["chimney_brand"] = b
            break

    return row
