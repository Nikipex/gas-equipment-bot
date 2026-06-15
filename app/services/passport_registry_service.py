from __future__ import annotations

import json
import re
from pathlib import Path


REGISTRY_DIR = Path("data/passport_registry")


def _norm(value: str) -> str:
    text = str(value or "").lower().replace("ё", "е")
    repl = {
        "бакси": "baxi",
        "навьен": "navien",
        "навиен": "navien",
        "лемакс": "lemax",
        "классик": "classic",
        "премиум": "premium",
        "сиберия": "siberia",
    }
    for a, b in repl.items():
        text = re.sub(rf"(?<!\w){re.escape(a)}(?!\w)", b, text)
    return text


class PassportRegistryService:
    def __init__(self):
        self.registry_dir = REGISTRY_DIR

    def _load_all(self) -> list[dict]:
        items = []

        for path in self.registry_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["_registry_file"] = str(path)
                items.append(data)
            except Exception:
                continue

        return items

    def search(self, text: str) -> list[dict]:
        q = _norm(text)
        matches = []

        for data in self._load_all():
            brand = _norm(str(data.get("brand", "")))
            model = _norm(str(data.get("model", "")))
            full = f"{brand} {model}".strip()

            score = 0

            if full and full in q:
                score += 20

            if model and model in q:
                score += 15

            if brand and brand in q:
                score += 5

            model_tokens = [t for t in re.findall(r"[a-zа-я0-9]+", model) if len(t) >= 2]
            for token in model_tokens:
                if token in q:
                    score += 2

            if score > 0:
                item = dict(data)
                item["_score"] = score
                matches.append(item)

        matches.sort(key=lambda x: x.get("_score", 0), reverse=True)
        return matches

    def get_by_model(self, model_name: str) -> dict | None:
        target = _norm(model_name)

        for data in self._load_all():
            model = _norm(str(data.get("model", "")))
            brand = _norm(str(data.get("brand", "")))
            full = f"{brand} {model}".strip()

            if target in {model, full}:
                return data

        return None

    def build_context(self, question: str, limit: int = 5) -> str:
        matches = self.search(question)[:limit]
        if not matches:
            return ""

        blocks = ["# Passport Registry Context"]

        for item in matches:
            blocks.append(self._format_item(item))

        return "\n\n---\n\n".join(blocks)

    def _format_item(self, item: dict) -> str:
        def val(key: str) -> str:
            value = item.get(key)
            if value is None:
                return "нет данных"
            if value is True:
                return "да"
            if value is False:
                return "нет"
            return str(value)

        return f"""## {val("brand")} {val("model")}

Категория: {val("category")}
Мощность: {val("power_kw")} кВт
Контуры: {val("circuits")}
Камера: {val("chamber")}
Установка: {val("installation")}
ГВС: {val("dhw")}
Коаксиал: {val("coaxial")}
КПД: {val("efficiency_percent")}
Вес: {val("weight_kg")}
Дымоход: {val("flue_type")}
Размер дымохода: {val("flue_size")}
Позиционирование: {val("sales_positioning")}
Источник: {val("source_file")}"""

    def build_comparison_context(self, question: str, limit: int = 4) -> str:
        matches = self.search(question)[:limit]

        if len(matches) < 2:
            return ""

        fields = [
            ("Бренд", "brand"),
            ("Модель", "model"),
            ("Категория", "category"),
            ("Мощность, кВт", "power_kw"),
            ("Контуры", "circuits"),
            ("Камера", "chamber"),
            ("Установка", "installation"),
            ("ГВС", "dhw"),
            ("Коаксиал", "coaxial"),
            ("КПД, %", "efficiency_percent"),
            ("Вес, кг", "weight_kg"),
            ("Дымоход", "flue_type"),
            ("Размер дымохода", "flue_size"),
            ("Позиционирование", "sales_positioning"),
        ]

        lines = ["# Passport Comparison Context"]
        lines.append("")
        lines.append("Найдены модели для сравнения. Используй эту таблицу как основу ответа.")
        lines.append("")
        lines.append("| Параметр | " + " | ".join(self._display_name(item) for item in matches) + " |")
        lines.append("|---|" + "|".join("---" for _ in matches) + "|")

        for title, key in fields:
            values = [self._value_to_text(item.get(key)) for item in matches]
            lines.append("| " + title + " | " + " | ".join(values) + " |")

        return "\n".join(lines)

    @staticmethod
    def _value_to_text(value) -> str:
        if value is None:
            return "нет данных"
        if value is True:
            return "да"
        if value is False:
            return "нет"
        return str(value)

    @staticmethod
    def _display_name(item: dict) -> str:
        brand = str(item.get("brand") or "").strip()
        model = str(item.get("model") or "").strip()
        return f"{brand} {model}".strip() or "модель"

    def find_analogs_for_question(self, question: str, limit: int = 5) -> list[dict]:
        source_matches = self.search(question)
        if not source_matches:
            return []

        source = source_matches[0]
        return self.find_analogs(source, limit=limit)

    def find_analogs(self, source: dict, limit: int = 5) -> list[dict]:
        candidates = []

        for item in self._load_all():
            if item.get("model") == source.get("model") and item.get("brand") == source.get("brand"):
                continue

            score = self._analog_score(source, item)
            if score <= 0:
                continue

            candidate = dict(item)
            candidate["_analog_score"] = score
            candidates.append(candidate)

        candidates.sort(key=lambda x: x.get("_analog_score", 0), reverse=True)
        return candidates[:limit]

    def build_analogs_context(self, question: str, limit: int = 5) -> str:
        source_matches = self.search(question)
        if not source_matches:
            return ""

        source = source_matches[0]
        analogs = self.find_analogs(source, limit=limit)

        if not analogs:
            return ""

        lines = ["# Passport Analogs Context"]
        lines.append("")
        lines.append(f"Исходная модель: {self._display_name(source)}")
        lines.append("")
        lines.append("Похожие модели из passport registry:")
        lines.append("")

        for idx, item in enumerate(analogs, start=1):
            lines.append(
                f"{idx}. {self._display_name(item)} "
                f"(score={item.get('_analog_score')}) — "
                f"{item.get('power_kw')} кВт, "
                f"контуры={item.get('circuits')}, "
                f"камера={item.get('chamber')}, "
                f"установка={item.get('installation')}, "
                f"коаксиал={item.get('coaxial')}"
            )

        lines.append("")
        lines.append("Используй эти аналоги только если они действительно совпадают по ключевым параметрам.")
        return "\n".join(lines)

    @staticmethod
    def _analog_score(source: dict, item: dict) -> int:
        score = 0

        if source.get("category") and source.get("category") == item.get("category"):
            score += 10

        if source.get("power_kw") is not None and item.get("power_kw") is not None:
            try:
                diff = abs(float(source.get("power_kw")) - float(item.get("power_kw")))
                if diff == 0:
                    score += 10
                elif diff <= 2:
                    score += 6
                elif diff <= 4:
                    score += 2
            except Exception:
                pass

        for key, points in [
            ("circuits", 8),
            ("chamber", 8),
            ("installation", 6),
            ("dhw", 4),
            ("coaxial", 4),
            ("flue_type", 3),
        ]:
            if source.get(key) is not None and source.get(key) == item.get(key):
                score += points

        return score


passport_registry_service = PassportRegistryService()
