"""Equipment intent parser.

Rule-based first, LLM-ready later.
Turns messy manager text into structured equipment intent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EquipmentIntent:
    category: str
    brand: str | None = None
    power_kw: float | None = None
    volume_l: int | None = None
    circuits: int | None = None
    chamber: str | None = None
    install_type: str | None = None
    query_for_supplier_search: str = ""
    raw_text: str = ""


class EquipmentIntentParser:
    async def parse(self, text: str) -> EquipmentIntent:
        low = text.lower().replace("ё", "е")

        category = self._detect_category(low)
        brand = self._detect_brand(low)
        power_kw = self._extract_power(low)
        volume_l = self._extract_volume(low)
        circuits = self._extract_circuits(low)
        chamber = self._extract_chamber(low)
        install_type = self._extract_install_type(low)

        query = self._build_supplier_query(
            category=category,
            brand=brand,
            power_kw=power_kw,
            volume_l=volume_l,
            circuits=circuits,
            chamber=chamber,
            install_type=install_type,
            raw_text=text,
        )

        return EquipmentIntent(
            category=category,
            brand=brand,
            power_kw=power_kw,
            volume_l=volume_l,
            circuits=circuits,
            chamber=chamber,
            install_type=install_type,
            query_for_supplier_search=query,
            raw_text=text,
        )


    def _extract_model_tail(self, raw_text: str, brand: str | None) -> str | None:
        text = raw_text.lower().replace("ё", "е")

        # Убираем служебные слова, оставляем модельные куски.
        remove = [
            "подбор", "подбери", "подобрать", "котел", "котёл", "газовый",
            "настенный", "напольный", "турбо", "атмо", "атмосферный",
            "закрытая", "открытая", "камера", "на", "квт", "kw",
        ]

        for word in remove:
            text = text.replace(word, " ")

        brand_aliases = {
            "Baxi": ["baxi", "бакси"],
            "Ariston": ["ariston", "аристон"],
            "Navien": ["navien", "навьен", "навиен"],
            "Ferroli": ["ferroli", "ферроли"],
        }

        if brand:
            for alias in brand_aliases.get(brand, [brand.lower()]):
                text = text.replace(alias, " ")

        text = " ".join(text.split())

        # Не считаем одной только мощностью модель.
        if not text or text.replace(" ", "").isdigit():
            return None

        # Берем только если есть явные модельные слова.
        if any(x in text for x in ["eco", "эко", "nova", "life", "four", "4s", "slim", "luna", "deluxe", "pro1", "lydos", "abs"]):
            return text

        return None

    def _detect_category(self, low: str) -> str:
        if re.search(r"бойлер|водонагрев|накопительн|косвенник|косвенного", low):
            return "water_heater"
        if re.search(r"газов.*колонк|колонк", low):
            return "gas_column"
        if re.search(r"радиатор|биметалл|алюмин|панельн", low):
            return "radiator"
        if re.search(r"насос|циркуляцион|25/6|25-6", low):
            return "pump"
        if re.search(r"дымоход|коаксиал|колено|труба", low):
            return "chimney"
        if re.search(r"стабилизатор|ибп|ups|напряж", low):
            return "stabilizer"
        if re.search(r"котел|котёл|котлы|квт|контур|турбо|атмо|настенн|напольн", low):
            return "boiler"
        return "generic"

    def _detect_brand(self, low: str) -> str | None:
        brands = {
            "baxi": "Baxi",
            "бакси": "Baxi",
            "navien": "Navien",
            "навьен": "Navien",
            "навиен": "Navien",
            "ferroli": "Ferroli",
            "ферроли": "Ferroli",
            "ariston": "Ariston",
            "аристон": "Ariston",
            "protherm": "Protherm",
            "протерм": "Protherm",
            "bosch": "Bosch",
            "buderus": "Buderus",
            "будерус": "Buderus",
            "лемакс": "Лемакс",
            "lemax": "Лемакс",
            "royal thermo": "Royal Thermo",
            "роял термо": "Royal Thermo",
            "thermex": "Thermex",
            "термекс": "Thermex",
            "grundfos": "Grundfos",
            "wilo": "Wilo",
            "rifar": "Rifar",
            "rommer": "Rommer",
            "stout": "Stout",
        }

        for token, brand in brands.items():
            if token in low:
                return brand

        return None

    def _extract_power(self, low: str) -> float | None:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:квт|kw)", low)
        if not m:
            return None
        return float(m.group(1).replace(",", "."))

    def _extract_volume(self, low: str) -> int | None:
        m = re.search(r"(\d{2,4})\s*(?:л|литр|литров)", low)
        if not m:
            return None
        return int(m.group(1))

    def _extract_circuits(self, low: str) -> int | None:
        # Baxi-style model logic:
        # 1.24F / 1.24 F = одноконтурный
        # 24F / 24 F / F24 = двухконтурный
        if re.search(r"\b1\.\d+\s*f\b|\b1\.24f\b", low):
            return 1

        if re.search(r"\b(?:24|28|31)\s*f\b|\b(?:24|28|31)f\b|\bf(?:24|28|31)\b", low):
            return 2

        if re.search(r"двухконт|2\s*конт|2\s*контура|два\s*конт", low):
            return 2

        if re.search(r"одноконт|1\s*конт|1\s*контур|один\s*конт", low):
            return 1

        return None

    def _extract_chamber(self, low: str) -> str | None:
        if re.search(r"турбо|закрыт|коакс|коаксиал", low):
            return "closed"
        if re.search(r"атмо|открыт", low):
            return "open"
        return None

    def _extract_install_type(self, low: str) -> str | None:
        if re.search(r"настенн|настен", low):
            return "wall"
        if re.search(r"напольн", low):
            return "floor"
        return None

    def _build_supplier_query(
        self,
        *,
        category: str,
        brand: str | None,
        power_kw: float | None,
        volume_l: int | None,
        circuits: int | None,
        chamber: str | None,
        install_type: str | None,
        raw_text: str,
    ) -> str:
        parts: list[str] = []

        if brand:
            parts.append(brand)

        model_tail = self._extract_model_tail(raw_text, brand)
        if model_tail:
            parts.append(model_tail)

        if category == "boiler":
            parts.append("котел")
            if install_type == "wall":
                parts.append("настенный")
            elif install_type == "floor":
                parts.append("напольный")

            if chamber == "closed":
                parts.append("турбо")
            elif chamber == "open":
                parts.append("атмо")

            if circuits == 2:
                parts.append("двухконтурный")
            elif circuits == 1:
                parts.append("одноконтурный")

            if power_kw:
                parts.append(f"{power_kw:g} кВт")

        elif category == "water_heater":
            if "косвен" in raw_text.lower() or "косвенник" in raw_text.lower():
                parts.append("бойлер косвенного нагрева")
            else:
                parts.append("водонагреватель")
            if volume_l:
                parts.append(f"{volume_l} л")

        elif category == "gas_column":
            parts.append("газовая колонка")

        elif category == "radiator":
            parts.append("радиатор")

        elif category == "pump":
            parts.append("насос")

        elif category == "chimney":
            parts.append("дымоход")

        elif category == "stabilizer":
            parts.append("стабилизатор")

        query = " ".join(parts).strip()
        return query or raw_text
