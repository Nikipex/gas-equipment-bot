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
    volume_min_l: int | None = None
    volume_max_l: int | None = None
    circuits: int | None = None
    boiler_type: str | None = None
    water_heater_type: str | None = None
    tank_material: str | None = None
    tank_coating: str | None = None
    heating_element: str | None = None
    recirculation: bool | None = None
    chamber: str | None = None
    install_type: str | None = None
    orientation: str | None = None
    gas_automation: str | None = None
    connection: str | None = None
    chimney_diameter_mm: int | None = None
    query_for_supplier_search: str = ""
    raw_text: str = ""


class EquipmentIntentParser:
    async def parse(self, text: str) -> EquipmentIntent:
        low = text.lower().replace("ё", "е")

        category = self._detect_category(low)
        brand = self._detect_brand(low)
        power_kw = self._extract_power(low)
        volume_l = self._extract_volume(low)
        volume_min_l, volume_max_l = self._extract_volume_range(low)
        water_heater_type = self._extract_water_heater_type(low)
        tank_material = self._extract_tank_material(low)
        tank_coating = self._extract_tank_coating(low)
        heating_element = self._extract_heating_element(low)
        recirculation = self._extract_recirculation(low)
        circuits = self._extract_circuits(low)
        boiler_type = self._extract_boiler_type(low)
        chamber = self._extract_chamber(low)
        install_type = self._extract_install_type(low)
        orientation = self._extract_orientation(low)
        gas_automation = self._extract_gas_automation(low)
        connection = self._extract_connection(low)
        chimney_diameter_mm = self._extract_chimney_diameter_mm(low)

        query = self._build_supplier_query(
            category=category,
            brand=brand,
            power_kw=power_kw,
            volume_l=volume_l,
            volume_min_l=volume_min_l,
            volume_max_l=volume_max_l,
            circuits=circuits,
            boiler_type=boiler_type,
            water_heater_type=water_heater_type,
            tank_material=tank_material,
            tank_coating=tank_coating,
            heating_element=heating_element,
            recirculation=recirculation,
            chamber=chamber,
            install_type=install_type,
            orientation=orientation,
            gas_automation=gas_automation,
            connection=connection,
            chimney_diameter_mm=chimney_diameter_mm,
            raw_text=text,
        )

        return EquipmentIntent(
            category=category,
            brand=brand,
            power_kw=power_kw,
            volume_l=volume_l,
            volume_min_l=volume_min_l,
            volume_max_l=volume_max_l,
            circuits=circuits,
            boiler_type=boiler_type,
            water_heater_type=water_heater_type,
            tank_material=tank_material,
            tank_coating=tank_coating,
            heating_element=heating_element,
            recirculation=recirculation,
            chamber=chamber,
            install_type=install_type,
            orientation=orientation,
            gas_automation=gas_automation,
            connection=connection,
            chimney_diameter_mm=chimney_diameter_mm,
            query_for_supplier_search=query,
            raw_text=text,
        )


    def _extract_model_tail(self, raw_text: str, brand: str | None) -> str | None:
        text = raw_text.lower().replace("ё", "е")

        # Убираем служебные слова, оставляем модельные куски.
        remove = [
            "подбор", "подбери", "подобрать", "нужен", "нужна", "нужно", "ищем", "клиенту", "котел", "котёл", "газовый",
            "настенный", "напольный", "турбо", "атмо", "атмосферный",
            "закрытая", "открытая", "камера", "на", "квт", "kw",
        ]

        for word in remove:
            text = text.replace(word, " ")

        brand_aliases = {
            "Baxi": ["baxi", "бакси"],
            "Ariston": ["ariston", "аристон"],
            "Midea": ["midea", "мидеа"],
            "Thermex": ["thermex", "термекс"],
            "Edisson": ["edisson", "эдисон"],
            "Garanterm": ["garanterm", "гарантерм"],
            "Midea": ["midea", "мидеа"],
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
            "midea": "Midea",
            "мидеа": "Midea",
            "thermex": "Thermex",
            "термекс": "Thermex",
            "edisson": "Edisson",
            "эдисон": "Edisson",
            "garanterm": "Garanterm",
            "гарантерм": "Garanterm",
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
        m = re.search(r"(?:литр\w*\s*на\s*)(\d{2,4})", low)
        if m:
            return int(m.group(1))

        m = re.search(r"(\d{2,4})\s*(?:л|литр|литров)", low)
        if m:
            return int(m.group(1))

        # Для бойлеров/водонагревателей часто пишут просто "Аристон 80 сухой тэн"
        if re.search(r"бойлер|водонагрев|ariston|аристон|thermex|термекс", low):
            nums = [int(x) for x in re.findall(r"(?<!\d)(\d{2,4})(?!\d)", low)]
            nums = [x for x in nums if 30 <= x <= 500]
            if nums:
                return nums[0]

        return None



    def _extract_orientation(self, low: str) -> str | None:
        if "вертик" in low or "верт" in low:
            return "vertical"
        if "гориз" in low or "горизонт" in low or "гор." in low:
            return "horizontal"
        return None

    def _extract_gas_automation(self, low: str) -> str | None:
        if "sit" in low:
            return "sit"
        if "tgv" in low or "тgv" in low:
            return "tgv"
        return None

    def _extract_connection(self, low: str) -> str | None:
        if "боковой" in low or "бок.подвод" in low or "боковой подвод" in low:
            return "side"
        return None

    def _extract_chimney_diameter_mm(self, low: str) -> int | None:
        import re

        patterns = [
            r"(?:дым|дымоход)\.?\s*(\d{2,3})",
            r"(\d{2,3})\s*(?:мм)?\s*(?:дым|дымоход)",
        ]

        for pattern in patterns:
            m = re.search(pattern, low)
            if not m:
                continue

            value = int(m.group(1))
            if 50 <= value <= 300:
                return value

        return None

    def _extract_volume_range(self, low: str) -> tuple[int | None, int | None]:
        import re

        # "100-120", "100 до 120", "от 100 до 120"
        m = re.search(r"(?:от\s*)?(\d{2,4})\s*(?:-|–|—|до)\s*(\d{2,4})\s*(?:л|литр|литров)?", low)
        if m:
            left = int(m.group(1))
            right = int(m.group(2))
            return min(left, right), max(left, right)

        # "литров на 100-120"
        m = re.search(r"литр\w*\s*на\s*(\d{2,4})\s*(?:-|–|—|до)\s*(\d{2,4})", low)
        if m:
            left = int(m.group(1))
            right = int(m.group(2))
            return min(left, right), max(left, right)

        return None, None

    def _extract_water_heater_type(self, low: str) -> str | None:
        if "бак в баке" in low or "бак-в-баке" in low or "tank in tank" in low:
            return "tank_in_tank"

        if "косвен" in low or "косвенник" in low:
            return "indirect"

        if "электр" in low or "тэн" in low or "тен" in low:
            return "electric"

        if "газов" in low and ("накоп" in low or "бойлер" in low):
            return "gas_storage"

        return None

    def _extract_tank_material(self, low: str) -> str | None:
        if "нерж" in low or "нержав" in low or "inox" in low:
            return "stainless"
        return None

    def _extract_tank_coating(self, low: str) -> str | None:
        if "эмаль" in low or "эмал" in low or "биостекло" in low or "стеклофарфор" in low:
            return "enamel"
        return None


    def _extract_heating_element(self, low: str) -> str | None:
        if "сухой тэн" in low or "сухой тен" in low or "dry" in low or "стеатит" in low:
            return "dry"

        if "мокрый тэн" in low or "мокрый тен" in low:
            return "wet"

        return None

    def _extract_recirculation(self, low: str) -> bool | None:
        if "рециркуляц" in low or "рецирк" in low:
            return True
        return None

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


    def _extract_boiler_type(self, low: str) -> str | None:
        if "парапет" in low:
            return "parapet"

        if "напольн" in low or "аогв" in low or "ксг" in low:
            return "floor"

        if "настенн" in low or "настен" in low:
            return "wall"

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
        volume_min_l: int | None,
        volume_max_l: int | None,
        circuits: int | None,
        boiler_type: str | None,
        water_heater_type: str | None,
        tank_material: str | None,
        tank_coating: str | None,
        heating_element: str | None,
        recirculation: bool | None,
        chamber: str | None,
        install_type: str | None,
        orientation: str | None = None,
        gas_automation: str | None = None,
        connection: str | None = None,
        chimney_diameter_mm: int | None = None,
        raw_text: str = "",
    ) -> str:
        parts: list[str] = []

        if brand:
            parts.append(brand)

        model_tail = self._extract_model_tail(raw_text, brand)
        if model_tail:
            parts.append(model_tail)

        if category == "boiler":
            if boiler_type == "parapet":
                parts.append("парапетный котел")
            elif boiler_type == "floor":
                parts.append("напольный котел")
            else:
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
            if water_heater_type == "tank_in_tank":
                parts.append("бойлер бак в баке")
            elif water_heater_type == "indirect":
                parts.append("бойлер косвенного нагрева")
            else:
                parts.append("водонагреватель")

            if install_type == "wall":
                parts.append("настенный")
            elif install_type == "floor":
                parts.append("напольный")

            if recirculation:
                parts.append("с рециркуляцией")

            if tank_material == "stainless":
                parts.append("нержавейка")
            elif tank_coating == "enamel":
                parts.append("эмаль")

            if heating_element == "dry":
                parts.append("сухой тэн")
            elif heating_element == "wet":
                parts.append("мокрый тэн")

            if volume_min_l and volume_max_l:
                parts.append(f"{volume_min_l}-{volume_max_l} л")
            elif volume_l:
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
