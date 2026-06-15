from __future__ import annotations

import html
import re
from dataclasses import dataclass

from loguru import logger

from app.services.ai.equipment_intent_parser import EquipmentIntentParser
from app.services.ai.yandex_gpt_service import YandexGPTService
from app.services.postgres_catalog_service import CatalogItem, PostgresCatalogService


@dataclass
class AlternativeResult:
    source: CatalogItem | None
    alternatives: list[CatalogItem]
    ai_note: str


class AlternativeEquipmentService:
    def __init__(self) -> None:
        self.catalog = PostgresCatalogService()
        self.parser = EquipmentIntentParser()
        self.ai = YandexGPTService()

    async def find_alternatives(self, query: str, limit: int = 6) -> AlternativeResult:
        intent = await self.parser.parse(query)

        source_items = self.catalog.search(query, limit=5)
        source = source_items[0] if source_items else None
        source_name = source.product_name if source else query

        search_queries = self._build_alternative_queries(query, source_name, intent)
        candidates: list[CatalogItem] = []

        for q in search_queries:
            try:
                candidates.extend(self.catalog.search(q, limit=12))
            except Exception as exc:
                logger.warning("Alternative search failed for query={!r}: {}: {}", q, type(exc).__name__, exc)

        alternatives = self._rank_and_filter(
            source_name=source_name,
            candidates=candidates,
            category=intent.category,
            limit=limit,
        )

        ai_note = self._build_ai_note(source_name, alternatives, intent.category)

        return AlternativeResult(
            source=source,
            alternatives=alternatives,
            ai_note=ai_note,
        )

    def _build_alternative_queries(self, original_query: str, source_name: str, intent) -> list[str]:
        text = f"{original_query} {source_name}".lower().replace("ё", "е")
        category = intent.category

        queries: list[str] = []

        if category == "boiler" or self._looks_like_boiler(text):
            power = intent.power_kw or self._extract_power(text)
            circuits = intent.circuits or self._extract_circuits(text)
            chamber = intent.chamber or self._extract_chamber(text)
            install = intent.install_type or self._extract_install_type(text)

            base = ["котел"]
            if install == "wall":
                base.append("настенный")
            elif install == "floor":
                base.append("напольный")

            if chamber == "closed":
                base.extend(["турбо", "закрытая"])
            elif chamber == "open":
                base.extend(["атмо", "открытая"])

            if circuits == 2:
                base.append("двухконтурный")
            elif circuits == 1:
                base.append("одноконтурный")

            if power:
                p = int(round(float(power)))
                queries.extend([
                    " ".join(base + [str(p)]),
                    f"baxi {p}",
                    f"navien {p}",
                    f"federica bugatti {p}",
                    f"ferroli {p}",
                    f"ariston {p}",
                    f"lemax {p}",
                ])
            else:
                queries.append(" ".join(base))

        elif category == "water_heater" or self._looks_like_water_heater(text):
            volume = intent.volume_l or self._extract_volume(text)
            base = ["бойлер"]
            if volume:
                v = int(volume)
                queries.extend([
                    f"бойлер {v}",
                    f"водонагреватель {v}",
                    f"ariston {v}",
                    f"thermex {v}",
                    f"oasis {v}",
                ])
            else:
                queries.extend(["бойлер", "водонагреватель"])

        elif category == "pump" or self._looks_like_pump(text):
            pump_size = self._extract_pump_size(text)
            if pump_size:
                a, b = pump_size
                queries.extend([
                    f"насос {a}/{b}",
                    f"насос {a}-{b}",
                    f"насос {a} {b}",
                    f"циркуляционный насос {a}/{b}",
                ])
            else:
                queries.extend(["насос циркуляционный", "насос"])

        else:
            queries.extend([
                original_query,
                source_name,
            ])

        # убираем бренд исходника, чтобы не залипать только на нём
        cleaned: list[str] = []
        for q in queries:
            q2 = self._remove_source_brand(q, text)
            if q2 and q2 not in cleaned:
                cleaned.append(q2)

        return cleaned[:10]

    def _rank_and_filter(
        self,
        *,
        source_name: str,
        candidates: list[CatalogItem],
        category: str,
        limit: int,
    ) -> list[CatalogItem]:
        source_norm = self._norm(source_name)

        dedup: dict[str, CatalogItem] = {}
        for item in candidates:
            name_norm = self._norm(item.product_name)
            if not name_norm or name_norm == source_norm:
                continue
            if name_norm in source_norm or source_norm in name_norm:
                continue
            if self._is_bad_candidate(item.product_name, category):
                continue
            if not self._is_compatible(source_name, item.product_name, category):
                continue
            dedup[name_norm] = item

        ranked = sorted(
            dedup.values(),
            key=lambda item: self._score_item(source_name, item, category),
            reverse=True,
        )

        return ranked[:limit]

    def _score_item(self, source_name: str, item: CatalogItem, category: str) -> float:
        source = source_name.lower().replace("ё", "е")
        name = item.product_name.lower().replace("ё", "е")
        score = 0.0

        if item.stock_qty and item.stock_qty > 0:
            score += 25

        if category == "boiler" or self._looks_like_boiler(source):
            score += 15 if self._looks_like_boiler(name) else -50

            src_power = self._extract_power(source)
            dst_power = self._extract_power(name)
            if src_power and dst_power:
                diff = abs(src_power - dst_power)
                if diff == 0:
                    score += 40
                elif diff <= 2:
                    score += 20
                elif diff <= 4:
                    score += 8

            if self._extract_circuits(source) and self._extract_circuits(source) == self._extract_circuits(name):
                score += 15

            if self._extract_chamber(source) and self._extract_chamber(source) == self._extract_chamber(name):
                score += 15

        elif category == "water_heater" or self._looks_like_water_heater(source):
            score += 15 if self._looks_like_water_heater(name) else -50
            src_volume = self._extract_volume(source)
            dst_volume = self._extract_volume(name)
            if src_volume and dst_volume:
                diff = abs(src_volume - dst_volume)
                if diff == 0:
                    score += 35
                elif diff <= 20:
                    score += 15

        elif category == "pump" or self._looks_like_pump(source):
            score += 15 if self._looks_like_pump(name) else -50
            if self._extract_pump_size(source) and self._extract_pump_size(source) == self._extract_pump_size(name):
                score += 40

        # другой бренд — плюс, потому что ищем аналоги, а не дубль
        if self._brand(source) and self._brand(name) and self._brand(source) != self._brand(name):
            score += 10

        return score

    def _build_ai_note(self, source_name: str, alternatives: list[CatalogItem], category: str) -> str:
        if not alternatives:
            return ""

        try:
            return self.ai.explain_equipment_alternatives(
                source_name=source_name,
                category=category,
                candidates=[
                    {
                        "name": item.product_name,
                        "stock_qty": item.stock_qty,
                        "purchase_price": item.purchase_price,
                    }
                    for item in alternatives
                ],
            )
        except Exception as exc:
            logger.warning("AI alternative explanation failed: {}: {}", type(exc).__name__, exc)
            return (
                "⚠️ AI-пояснение временно недоступно.\n"
                "Кандидаты ниже подобраны по названию, мощности/объёму/типу и остаткам из базы."
            )

    def format_result(self, result: AlternativeResult, query: str) -> str:
        if not result.alternatives:
            return (
                "🔁 <b>Аналогичное оборудование</b>\n\n"
                f"По запросу <b>{html.escape(query)}</b> аналоги не найдены.\n"
                "Попробуйте указать модель точнее: бренд, мощность, литраж или тип."
            )

        lines = ["🔁 <b>Аналогичное оборудование</b>"]

        if result.source:
            lines.extend([
                "",
                "🔎 <b>Исходная позиция:</b>",
                html.escape(result.source.product_name),
                f"Остаток: {self._fmt_stock(result.source.stock_qty)}",
            ])
        else:
            lines.extend(["", f"🔎 Запрос: <b>{html.escape(query)}</b>"])

        lines.append("")
        lines.append("📦 <b>Подобранные аналоги из базы:</b>")

        for i, item in enumerate(result.alternatives, 1):
            lines.append("")
            lines.append(f"{i}. <b>{html.escape(item.product_name)}</b>")
            lines.append(f"   Остаток: {self._fmt_stock(item.stock_qty)}")
            if item.purchase_price:
                lines.append(f"   Закупка: {item.purchase_price:,.0f} ₽".replace(",", " "))

        if result.ai_note:
            lines.extend(["", html.escape(result.ai_note)])

        lines.extend([
            "",
            "⚠️ Перед КП сверить подключение, дымоход/габариты, комплектацию и актуальную цену.",
        ])

        return "\n".join(lines)

    def _is_compatible(self, source_name: str, candidate_name: str, category: str) -> bool:
        source = source_name.lower().replace("ё", "е")
        cand = candidate_name.lower().replace("ё", "е")

        if category == "boiler" or self._looks_like_boiler(source):
            src_chamber = self._extract_chamber(source)
            cand_chamber = self._extract_chamber(cand)

            # Жёстко: турбо/закрытая камера не равно атмо/открытая камера.
            if src_chamber and cand_chamber and src_chamber != cand_chamber:
                return False

            # FF/F обычно турбо, CF/C обычно атмо. Не мешаем.
            if self._has_ff_marker(source) and self._has_cf_marker(cand):
                return False
            if self._has_cf_marker(source) and self._has_ff_marker(cand):
                return False

            src_circuits = self._extract_circuits(source)
            cand_circuits = self._extract_circuits(cand)
            if src_circuits and cand_circuits and src_circuits != cand_circuits:
                return False

            src_power = self._extract_power(source)
            cand_power = self._extract_power(cand)
            if src_power and cand_power and abs(src_power - cand_power) > 3:
                return False

        if category == "water_heater" or self._looks_like_water_heater(source):
            src_kind = self._extract_water_heater_kind(source)
            cand_kind = self._extract_water_heater_kind(cand)

            # Электрический накопительный не смешиваем с косвенным/послойным.
            if src_kind and cand_kind and src_kind != cand_kind:
                return False

            src_volume = self._extract_volume(source)
            cand_volume = self._extract_volume(cand)
            if src_volume and cand_volume and abs(src_volume - cand_volume) > 30:
                return False

        if category == "pump" or self._looks_like_pump(source):
            src_size = self._extract_pump_size(source)
            cand_size = self._extract_pump_size(cand)

            # Для насосов 25/6 не должен превращаться в 25/4.
            if src_size and cand_size and src_size != cand_size:
                return False

        return True

    @staticmethod
    def _has_ff_marker(text: str) -> bool:
        low = text.lower().replace("ё", "е")
        return bool(re.search(r"\bff\b|\bf\b|турбо|закрыт|коакс", low))

    @staticmethod
    def _has_cf_marker(text: str) -> bool:
        low = text.lower().replace("ё", "е")
        return bool(re.search(r"\bcf\b|\bc\b|атмо|открыт", low))

    @staticmethod
    def _extract_water_heater_kind(text: str) -> str | None:
        low = text.lower().replace("ё", "е")
        if "косвен" in low or "змеевик" in low or "послой" in low:
            return "indirect"
        if "электр" in low or "тэн" in low or "тен" in low or "водонагреватель" in low:
            return "electric"
        return None

    @staticmethod
    def _fmt_stock(value) -> str:
        if value is None:
            return "нет данных"
        try:
            num = float(value)
            if num.is_integer():
                return str(int(num))
            return f"{num:.1f}"
        except Exception:
            return str(value)

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()

    @staticmethod
    def _brand(text: str) -> str | None:
        brands = ["baxi", "navien", "federica", "bugatti", "ferroli", "ariston", "lemax", "fondital", "bosch", "buderus", "thermex", "oasis"]
        low = text.lower().replace("ё", "е")
        for brand in brands:
            if brand in low:
                return brand
        return None

    @staticmethod
    def _remove_source_brand(query: str, source_text: str) -> str:
        # Не вырезаем все бренды: просто не даём поиску залипнуть на исходном бренде.
        source_brand = AlternativeEquipmentService._brand(source_text)
        if not source_brand:
            return query
        return re.sub(rf"\b{re.escape(source_brand)}\b", " ", query, flags=re.I).strip()

    @staticmethod
    def _looks_like_boiler(text: str) -> bool:
        return bool(re.search(r"кот[её]л|baxi|navien|federica|bugatti|ferroli|ariston|lemax|fondital|eco|deluxe", text))

    @staticmethod
    def _looks_like_water_heater(text: str) -> bool:
        return bool(re.search(r"бойлер|водонагрев|thermex|ariston|oasis|pro1|vls", text))

    @staticmethod
    def _looks_like_pump(text: str) -> bool:
        return bool(re.search(r"насос|циркуляц|25[/\-\s]?6|25[/\-\s]?4|25[/\-\s]?8|ups|upc", text))

    @staticmethod
    def _extract_power(text: str) -> float | None:
        low = text.lower().replace(",", ".")
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:квт|kw)", low)
        if m:
            return float(m.group(1))

        # BAXI/NAVIEN-style model power: 24F, 24 K, ECO 24
        for pattern in [
            r"\b(10|11|12|13|16|18|20|24|28|30|32|35|40)\s*f\b",
            r"\b(10|11|12|13|16|18|20|24|28|30|32|35|40)f\b",
            r"\b(10|11|12|13|16|18|20|24|28|30|32|35|40)\s*k\b",
            r"\b(10|11|12|13|16|18|20|24|28|30|32|35|40)k\b",
            r"\b(10|11|12|13|16|18|20|24|28|30|32|35|40)\b",
        ]:
            m = re.search(pattern, low)
            if m:
                return float(m.group(1))
        return None

    @staticmethod
    def _extract_circuits(text: str) -> int | None:
        low = text.lower().replace("ё", "е")
        if re.search(r"\b1\.\d+\s*f\b|\b1\.24f\b|одноконт|1\s*конт", low):
            return 1
        if re.search(r"\b(?:24|28|31)\s*f\b|\b(?:24|28|31)f\b|\bf(?:24|28|31)\b|двухконт|2\s*конт", low):
            return 2
        return None

    @staticmethod
    def _extract_chamber(text: str) -> str | None:
        low = text.lower().replace("ё", "е")
        if re.search(r"турбо|закрыт|коакс|коаксиал|f\b", low):
            return "closed"
        if re.search(r"атмо|открыт", low):
            return "open"
        return None

    @staticmethod
    def _extract_install_type(text: str) -> str | None:
        low = text.lower().replace("ё", "е")
        if re.search(r"настенн|настен", low):
            return "wall"
        if re.search(r"напольн|аогв|ксг", low):
            return "floor"
        return None

    @staticmethod
    def _extract_volume(text: str) -> int | None:
        low = text.lower()
        m = re.search(r"(\d{2,4})\s*(?:л|литр)", low)
        if m:
            return int(m.group(1))
        m = re.search(r"\b(30|50|80|100|120|150|200)\b", low)
        return int(m.group(1)) if m else None

    @staticmethod
    def _extract_pump_size(text: str) -> tuple[int, int] | None:
        low = text.lower()
        m = re.search(r"\b(25|32|40)\s*[/\-\s]\s*(4|6|8|10|12|40|60|80)\b", low)
        if not m:
            return None

        diameter = int(m.group(1))
        head = int(m.group(2))

        # 25/6 == 25-60, 25/4 == 25-40, 25/8 == 25-80
        if head in {4, 6, 8}:
            head *= 10

        return diameter, head

    @staticmethod
    def _is_bad_candidate(name: str, category: str) -> bool:
        low = name.lower().replace("ё", "е")

        bad_common = [
            "форсун", "теплообменник", "плата", "датчик", "клапан", "манометр",
            "комплект", "дымоход", "коаксиал", "колено", "адаптер", "муфта",
            "запчаст", "ремкомплект",
        ]

        if any(x in low for x in bad_common):
            return True

        if category == "boiler" and not AlternativeEquipmentService._looks_like_boiler(low):
            return True

        if category == "water_heater" and not AlternativeEquipmentService._looks_like_water_heater(low):
            return True

        if category == "pump" and not AlternativeEquipmentService._looks_like_pump(low):
            return True

        return False
