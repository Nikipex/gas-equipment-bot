from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from app.services.ai.equipment_intent_parser import EquipmentIntentParser
from app.services.equipment.equipment_search_pipeline import EquipmentSearchPipeline
from app.services.equipment.product_specs_service import ProductSpecsService, build_specs_text
from app.services.equipment.quote_builder_service import QuoteBuilderService, build_quote_text
from app.services.equipment.product_analog_service import ProductAnalogService, build_analogs_text
from app.services.equipment.chimney_search_service import ChimneySearchService, build_chimney_text


@dataclass(frozen=True)
class SearchCase:
    name: str
    query: str
    must_include_any: list[str] | None = None
    must_include_all: list[str] | None = None
    must_not_include_any: list[str] | None = None
    min_results: int = 1


@dataclass(frozen=True)
class IntentCase:
    name: str
    query: str
    checks: dict[str, object]


@dataclass(frozen=True)
class SpecsCase:
    name: str
    query: str
    must_include_any: list[str] | None = None
    must_include_all: list[str] | None = None
    must_not_include_any: list[str] | None = None


def norm(value: object) -> str:
    return str(value or "").lower().replace("ё", "е")


INTENT_CASES = [
    IntentCase(
        name="power range is not volume range",
        query="подбери напольник бюджетный, на 10-12 кВт",
        checks={
            "category": "boiler",
            "boiler_type": "floor",
            "power_min_kw": 10.0,
            "power_max_kw": 12.0,
            "volume_min_l": None,
            "volume_max_l": None,
        },
    ),
    IntentCase(
        name="flat water heater",
        query="подбери бойлер плоский настенный, на 50 литров",
        checks={
            "category": "water_heater",
            "volume_l": 50,
            "form_factor": "flat",
            "install_type": "wall",
        },
    ),
    IntentCase(
        name="round water heater",
        query="подбери бойлер круглый настенный, на 50 литров",
        checks={
            "category": "water_heater",
            "volume_l": 50,
            "form_factor": "round",
            "install_type": "wall",
        },
    ),
    IntentCase(
        name="parapet boiler",
        query="подбери парапетный котел на 10 кВт",
        checks={
            "category": "boiler",
            "boiler_type": "parapet",
            "power_kw": 10.0,
        },
    ),
    IntentCase(
        name="boiler flue exit vertical",
        query="напольный котел 12 квт с верхним выходом дымохода",
        checks={
            "category": "boiler",
            "boiler_type": "floor",
            "flue_exit": "vertical",
        },
    ),
    IntentCase(
        name="boiler body round",
        query="круглый напольный котел 12 квт",
        checks={
            "category": "boiler",
            "boiler_type": "floor",
            "body_shape": "round",
        },
    ),
    IntentCase(
        name="Midea brand",
        query="подбор бойлер Мидеа 80л",
        checks={
            "category": "water_heater",
            "brand": "Midea",
            "volume_l": 80,
        },
    ),
]


SEARCH_CASES = [
    SearchCase(
        name="flat 50l water heater excludes round",
        query="подбери бойлер плоский настенный, на 50 литров",
        must_include_any=["плоск", "slim", "if", "vls", "fem"],
        must_not_include_any=[" круг", "круг."],
        min_results=1,
    ),
    SearchCase(
        name="round 50l water heater excludes flat",
        query="подбери бойлер круглый настенный, на 50 литров",
        must_include_any=["круг"],
        must_not_include_any=["плоск", "slim"],
        min_results=1,
    ),
    SearchCase(
        name="dry heating element excludes wet",
        query="нужен бойлер Ariston 80л сухой тэн",
        must_include_any=["dry", "сухой"],
        must_not_include_any=["мокрый"],
        min_results=1,
    ),
    SearchCase(
        name="wet heating element excludes dry",
        query="нужен бойлер 100л мокрый тэн",
        must_include_any=["мокрый"],
        must_not_include_any=["dry", "сухой"],
        min_results=1,
    ),
    SearchCase(
        name="parapet 10kw excludes floor ORSO",
        query="подбери парапетный котел на 10 кВт",
        must_include_any=["парапет", "патриот", "ксгз"],
        must_not_include_any=["orso ксг-10", "orso ксг"],
        min_results=1,
    ),
    SearchCase(
        name="Baxi exact brand excludes Navien",
        query="подбери котел Бакси 24 квт турбо двухконтурный",
        must_include_any=["бакси", "baxi"],
        must_not_include_any=["navien", "навьен", "навиен"],
        min_results=1,
    ),
    SearchCase(
        name="budget floor boiler 10-12 sorted cheap",
        query="подбери напольник бюджетный, на 10-12 кВт",
        must_include_any=["аогв", "ксг", "orso", "rga", "vargaz"],
        must_not_include_any=["настенный", "турбо"],
        min_results=1,
    ),
    SearchCase(
        name="side connection floor boiler",
        query="напольный котел 12 квт боковой подвод",
        must_include_any=["бок"],
        min_results=1,
    ),
    SearchCase(
        name="vertical TGV floor boiler",
        query="напольный котел 12 квт двухконтурный вертикальный tgv",
        must_include_all=["tgv", "вертик"],
        must_not_include_any=["гор.)", "гориз"],
        min_results=1,
    ),
]


SPECS_CASES = [
    SpecsCase(
        name="Lemax Patriot specs",
        query="Лемакс Патриот 10",
        must_include_all=["характеристики", "лемакс патриот", "парапетный", "10 квт", "контуры"],
        must_not_include_any=["\\n"],
    ),
    SpecsCase(
        name="ORSO specs",
        query="ORSO КСГ-12 TGV",
        must_include_all=["orso", "напольный", "12 квт", "tgv"],
        must_not_include_any=["\\n"],
    ),
    SpecsCase(
        name="Midea flat specs",
        query="Midea FEM 50",
        must_include_all=["midea", "50 л", "плоский"],
        must_not_include_any=["\\n"],
    ),
]


async def run_intent_cases(parser: EquipmentIntentParser) -> tuple[int, int]:
    passed = 0
    total = len(INTENT_CASES)

    print("\n" + "=" * 100)
    print("INTENT TESTS")
    print("=" * 100)

    for case in INTENT_CASES:
        intent = await parser.parse(case.query)
        failures = []

        for attr, expected in case.checks.items():
            actual = getattr(intent, attr, None)
            if actual != expected:
                failures.append(f"{attr}: expected={expected!r}, actual={actual!r}")

        if failures:
            print(f"❌ FAIL | {case.name}")
            print(f"   query: {case.query}")
            for failure in failures:
                print(f"   - {failure}")
        else:
            passed += 1
            print(f"✅ PASS | {case.name}")

    return passed, total


async def run_search_cases(parser: EquipmentIntentParser, pipeline: EquipmentSearchPipeline) -> tuple[int, int]:
    passed = 0
    total = len(SEARCH_CASES)

    print("\n" + "=" * 100)
    print("SEARCH TESTS")
    print("=" * 100)

    for case in SEARCH_CASES:
        intent = await parser.parse(case.query)
        result = await pipeline.search(intent)
        candidates = result.candidates or []
        names = [str(getattr(c, "product_name", "")) for c in candidates[:10]]
        joined = norm(" | ".join(names))

        failures = []

        if len(candidates) < case.min_results:
            failures.append(f"results: expected >= {case.min_results}, actual={len(candidates)}")

        if case.must_include_any:
            if not any(norm(x) in joined for x in case.must_include_any):
                failures.append(f"must include any: {case.must_include_any}")

        if case.must_include_all:
            missing = [x for x in case.must_include_all if norm(x) not in joined]
            if missing:
                failures.append(f"must include all missing: {missing}")

        if case.must_not_include_any:
            bad = [x for x in case.must_not_include_any if norm(x) in joined]
            if bad:
                failures.append(f"must NOT include found: {bad}")

        if failures:
            print(f"❌ FAIL | {case.name}")
            print(f"   query: {case.query}")
            print(f"   intent: {intent}")
            print("   results:")
            for name in names[:5]:
                print(f"   - {name}")
            for failure in failures:
                print(f"   - {failure}")
        else:
            passed += 1
            print(f"✅ PASS | {case.name}")

    return passed, total


def run_specs_cases(service: ProductSpecsService) -> tuple[int, int]:
    passed = 0
    total = len(SPECS_CASES)

    print("\n" + "=" * 100)
    print("SPECS TESTS")
    print("=" * 100)

    for case in SPECS_CASES:
        rows = service.find(case.query)
        failures = []

        if not rows:
            failures.append("no rows found")
            text = ""
        else:
            text = build_specs_text(rows[0])

        low = norm(text)

        if case.must_include_any:
            if not any(norm(x) in low for x in case.must_include_any):
                failures.append(f"must include any: {case.must_include_any}")

        if case.must_include_all:
            missing = [x for x in case.must_include_all if norm(x) not in low]
            if missing:
                failures.append(f"must include all missing: {missing}")

        if case.must_not_include_any:
            bad = [x for x in case.must_not_include_any if norm(x) in low]
            if bad:
                failures.append(f"must NOT include found: {bad}")

        if failures:
            print(f"❌ FAIL | {case.name}")
            print(f"   query: {case.query}")
            print(f"   preview: {text[:500]!r}")
            for failure in failures:
                print(f"   - {failure}")
        else:
            passed += 1
            print(f"✅ PASS | {case.name}")

    return passed, total




def run_quote_cases() -> tuple[int, int]:
    print("\n" + "=" * 100)
    print("QUOTE TESTS")
    print("=" * 100)

    service = QuoteBuilderService()

    text = """
Лемакс Патриот 10 x2
Ariston PRO1 R 80 DRY x1
Midea FEM 50 x3
"""

    lines = service.build(text)
    quote = build_quote_text(lines)
    low = norm(quote)

    failures = []

    for expected in [
        "лемакс патриот",
        "аристон pro1",
        "midea",
        "итого",
        "121 496",
    ]:
        if expected not in low:
            failures.append(f"missing: {expected}")

    if len(lines) != 3:
        failures.append(f"expected 3 lines, got {len(lines)}")

    if failures:
        print("❌ FAIL | quote builder basic")
        print(quote)
        for item in failures:
            print("   -", item)
        return 0, 1

    print("✅ PASS | quote builder basic")
    return 1, 1




def run_analog_cases() -> tuple[int, int]:
    print("\n" + "=" * 100)
    print("ANALOG TESTS")
    print("=" * 100)

    service = ProductAnalogService()

    cases = [
        {
            "name": "Baxi wall turbo analogs exclude garbage",
            "query": "Бакси ECO LIFE 24F",
            "must_include_any": ["buran", "вайлант", "vuw"],
            "must_not_include_any": ["эван", "лемакс", "artu", "аогв", "газовик"],
        },
        {
            "name": "Lemax Patriot analog finds Artek parapet",
            "query": "Лемакс Патриот 10",
            "must_include_any": ["артек", "ксгз", "парапет"],
            "must_not_include_any": ["orso ксг"],
        },
        {
            "name": "Midea flat 50 analogs stay flat",
            "query": "Midea FEM 50",
            "must_include_any": ["плоск", "slim", "if"],
            "must_not_include_any": ["круг."],
        },
    ]

    passed = 0

    for case in cases:
        source, analogs = service.find_analogs(case["query"])
        text = build_analogs_text(source, analogs)
        low = norm(text)

        failures = []

        if not analogs:
            failures.append("no analogs found")

        if not any(norm(x) in low for x in case["must_include_any"]):
            failures.append(f"must include any: {case['must_include_any']}")

        bad = [x for x in case["must_not_include_any"] if norm(x) in low]
        if bad:
            failures.append(f"must NOT include found: {bad}")

        if failures:
            print(f"❌ FAIL | {case['name']}")
            print(text)
            for item in failures:
                print("   -", item)
        else:
            passed += 1
            print(f"✅ PASS | {case['name']}")

    return passed, len(cases)




def run_chimney_cases() -> tuple[int, int]:
    print("\n" + "=" * 100)
    print("CHIMNEY TESTS")
    print("=" * 100)

    service = ChimneySearchService()

    cases = [
        {
            "name": "coaxial kit 60/100",
            "query": "коаксиальный комплект 60/100",
            "must_include_any": ["комплект", "60/100"],
            "must_not_include_any": ["электрокотел", "аогв"],
        },
        {
            "name": "Baxi adapter 60/100 to 80/80",
            "query": "адаптер 60/100 на 80/80 Baxi",
            "must_include_any": ["адаптер", "60/100", "80/80", "baxi"],
            "must_not_include_any": ["котел настенный"],
        },
        {
            "name": "elbow 80/125",
            "query": "колено 80/125",
            "must_include_any": ["отвод", "колено", "80/125"],
            "must_not_include_any": ["котел"],
        },
        {
            "name": "condensate d80",
            "query": "конденсатоотвод d80",
            "must_include_any": ["конденсат", "80"],
            "must_not_include_any": ["дымоход диаметр- 80 l"],
        },
        {
            "name": "condensate 60/100",
            "query": "конденсатосборник 60/100",
            "must_include_any": ["конденсат", "60/100"],
            "must_not_include_any": ["электрокотел"],
        },
    ]

    passed = 0

    for case in cases:
        rows = service.search(case["query"])
        text = build_chimney_text(case["query"], rows)
        low = norm(text)

        failures = []

        if not rows:
            failures.append("no rows found")

        if not any(norm(x) in low for x in case["must_include_any"]):
            failures.append(f"must include any: {case['must_include_any']}")

        bad = [x for x in case["must_not_include_any"] if norm(x) in low]
        if bad:
            failures.append(f"must NOT include found: {bad}")

        if failures:
            print(f"❌ FAIL | {case['name']}")
            print(text)
            for item in failures:
                print("   -", item)
        else:
            passed += 1
            print(f"✅ PASS | {case['name']}")

    return passed, len(cases)


async def main() -> None:
    parser = EquipmentIntentParser()
    pipeline = EquipmentSearchPipeline()
    specs_service = ProductSpecsService()

    total_passed = 0
    total_count = 0

    for passed, count in [
        await run_intent_cases(parser),
        await run_search_cases(parser, pipeline),
        run_specs_cases(specs_service),
        run_quote_cases(),
        run_analog_cases(),
        run_chimney_cases(),
    ]:
        total_passed += passed
        total_count += count

    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(f"PASSED: {total_passed}/{total_count}")

    if total_passed != total_count:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
