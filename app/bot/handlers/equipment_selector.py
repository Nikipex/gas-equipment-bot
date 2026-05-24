"""AI equipment selector Telegram handler.

This handler intentionally does NOT scrape external selector websites.
It acts as an engineering-style assistant: understands the request,
normalizes requirements, suggests equipment classes/models, and tells
the manager what to verify in 1C / supplier stock commands.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from aiogram import Router
from aiogram.types import Message
from loguru import logger

from app.bot.keyboards.main_menu import main_menu_kb
from app.services.ai.equipment_intent_parser import EquipmentIntentParser

from app.services.equipment.equipment_search_pipeline import EquipmentSearchPipeline
from app.services.equipment.product_specs_service import ProductSpecsService, build_specs_text

router = Router()
intent_parser = EquipmentIntentParser()
equipment_pipeline = EquipmentSearchPipeline()
search_pipeline = equipment_pipeline
product_specs_service = ProductSpecsService()


@dataclass(frozen=True)
class EquipmentIntent:
    category: str
    brand: str | None
    power_kw: float | None
    volume_l: int | None
    circuits: int | None
    chamber: str | None
    install_type: str | None
    raw_text: str






@router.message(lambda message: message.text and message.text.lower().startswith(("/spec ", "/characteristics ", "характеристики ")))
async def process_product_specs(message: Message) -> None:
    text = message.text or ""

    query = text
    for prefix in ["/spec", "/characteristics", "характеристики"]:
        if query.lower().startswith(prefix):
            query = query[len(prefix):].strip()
            break

    if not query:
        await message.answer(
            "Напиши модель после команды. Например: <code>характеристики Лемакс Патриот 10</code>",
            reply_markup=main_menu_kb,
        )
        return

    matches = product_specs_service.find(query, limit=5)

    if not matches:
        await message.answer(
            "❌ Не нашёл товар в прайсах. Попробуй указать бренд/модель точнее.",
            reply_markup=main_menu_kb,
        )
        return

    await message.answer(
        build_specs_text(matches[0])[:3900],
        reply_markup=main_menu_kb,
    )


@router.message(lambda message: message.text and message.text.lower().startswith("/debug_equipment "))
async def debug_equipment_intent(message: Message) -> None:
    text = (message.text or "").replace("/debug_equipment", "", 1).strip()

    intent = await intent_parser.parse(text)
    result = await search_pipeline.search(intent)

    lines = [
        "🧪 <b>Debug equipment intent</b>",
        "",
        f"<b>raw:</b> <code>{html.escape(text)}</code>",
        f"<b>category:</b> <code>{intent.category}</code>",
        f"<b>brand:</b> <code>{intent.brand}</code>",
        f"<b>power_kw:</b> <code>{intent.power_kw}</code>",
        f"<b>volume_l:</b> <code>{intent.volume_l}</code>",
        f"<b>volume_min_l:</b> <code>{intent.volume_min_l}</code>",
        f"<b>volume_max_l:</b> <code>{intent.volume_max_l}</code>",
        f"<b>boiler_type:</b> <code>{getattr(intent, 'boiler_type', None)}</code>",
        f"<b>water_heater_type:</b> <code>{getattr(intent, 'water_heater_type', None)}</code>",
        f"<b>tank_material:</b> <code>{getattr(intent, 'tank_material', None)}</code>",
        f"<b>tank_coating:</b> <code>{getattr(intent, 'tank_coating', None)}</code>",
        f"<b>heating_element:</b> <code>{getattr(intent, 'heating_element', None)}</code>",
        f"<b>recirculation:</b> <code>{getattr(intent, 'recirculation', None)}</code>",
        f"<b>chamber:</b> <code>{intent.chamber}</code>",
        f"<b>circuits:</b> <code>{intent.circuits}</code>",
        f"<b>install_type:</b> <code>{intent.install_type}</code>",
        f"<b>query:</b> <code>{html.escape(intent.query_for_supplier_search)}</code>",
        "",
        f"<b>strict_found:</b> <code>{len(result.candidates)}</code>",
        f"<b>fallback_found:</b> <code>{len(result.fallback_candidates or [])}</code>",
    ]

    await message.answer("\n".join(lines), reply_markup=main_menu_kb)


@router.message(lambda message: message.text and message.text.lower().startswith(("подбор ", "подбери ", "подобрать ")))
async def process_equipment_selection(message: Message) -> None:
    text = message.text or ""
    intent = await intent_parser.parse(text)

    logger.info(f"AI equipment selector request: category={intent.category} query={intent.query_for_supplier_search} text={text}")

    await message.answer(
        "🧠 Анализирую запрос как ассистент по подбору оборудования…",
        reply_markup=main_menu_kb,
    )

    answer = _build_answer(intent)

    try:
        search_result = await equipment_pipeline.search(intent)
        supplier_block = _build_supplier_block(intent, search_result)

        if supplier_block and (
            getattr(search_result, "candidates", None)
            or getattr(search_result, "fallback_candidates", None)
        ):
            answer = supplier_block
        elif supplier_block:
            answer = answer + "\n\n" + supplier_block

    except Exception as exc:
        logger.exception(f"Equipment supplier search failed: {exc}")

    await message.answer(
        answer[:3900],
        reply_markup=main_menu_kb,
    )


def _parse_intent(text: str) -> EquipmentIntent:
    low = text.lower().replace("ё", "е")

    category = _detect_category(low)
    brand = _detect_brand(low)

    power_kw = None
    power_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:квт|kw)", low)
    if power_match:
        power_kw = float(power_match.group(1).replace(",", "."))

    volume_l = None
    volume_match = re.search(r"(\d{2,4})\s*(?:л|литр|литров)", low)
    if volume_match:
        volume_l = int(volume_match.group(1))

    circuits = None
    if re.search(r"двухконт|2\s*конт|2\s*контура|два\s*конт", low):
        circuits = 2
    elif re.search(r"одноконт|1\s*конт|1\s*контур|один\s*конт", low):
        circuits = 1

    chamber = None
    if re.search(r"турбо|закрыт|коакс|коаксиал", low):
        chamber = "закрытая камера / турбо"
    elif re.search(r"атмо|открыт", low):
        chamber = "открытая камера / атмосферный"

    install_type = None
    if re.search(r"настенн|настен", low):
        install_type = "настенный"
    elif re.search(r"напольн", low):
        install_type = "напольный"

    return EquipmentIntent(
        category=category,
        brand=brand,
        power_kw=power_kw,
        volume_l=volume_l,
        circuits=circuits,
        chamber=chamber,
        install_type=install_type,
        raw_text=text,
    )


def _detect_category(low: str) -> str:
    if re.search(r"бойлер|водонагрев|накопительн", low):
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


def _detect_brand(low: str) -> str | None:
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
        "будерус": "Buderus",
        "buderus": "Buderus",
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
    }

    for token, brand in brands.items():
        if token in low:
            return brand

    return None


def _build_answer(intent: EquipmentIntent) -> str:
    if intent.category == "boiler":
        return _boiler_answer(intent)
    if intent.category == "water_heater":
        return _water_heater_answer(intent)
    if intent.category == "gas_column":
        return _gas_column_answer(intent)
    if intent.category == "radiator":
        return _radiator_answer(intent)
    if intent.category == "pump":
        return _pump_answer(intent)
    if intent.category == "chimney":
        return _chimney_answer(intent)
    if intent.category == "stabilizer":
        return _stabilizer_answer(intent)

    return (
        "🧩 <b>Подбор оборудования</b>\n\n"
        f"Запрос: <code>{html.escape(intent.raw_text)}</code>\n\n"
        "Пока не смог уверенно определить категорию. Лучше уточнить: котел, бойлер, колонка, радиатор, насос, дымоход или стабилизатор.\n\n"
        "Пример: <code>подбор котел настенный турбо 24 кВт 2 контура</code>"
    )


def _summary(intent: EquipmentIntent) -> str:
    parts = []

    if intent.brand:
        parts.append(f"бренд: <b>{html.escape(intent.brand)}</b>")
    if intent.power_kw:
        parts.append(f"мощность: <b>{intent.power_kw:g} кВт</b>")
    if intent.volume_l:
        parts.append(f"объем: <b>{intent.volume_l} л</b>")
    if intent.install_type:
        parts.append(f"монтаж: <b>{html.escape(_label_install_type(intent.install_type) or intent.install_type)}</b>")
    if intent.chamber:
        parts.append(f"камера: <b>{html.escape(_label_chamber(intent.chamber) or intent.chamber)}</b>")
    if intent.circuits:
        parts.append(f"контуры: <b>{intent.circuits}</b>")

    return "Параметры: " + (", ".join(parts) if parts else "уточняются по запросу")


def _boiler_answer(intent: EquipmentIntent) -> str:
    power = intent.power_kw or 24
    install = _label_install_type(intent.install_type) or "настенный"
    chamber = _label_chamber(intent.chamber) or "закрытая камера / турбо"
    circuits = intent.circuits or 2

    models = [
        "Baxi ECO 4s / ECO Four / Eco Nova — массовые настенные 24 кВт",
        "Navien Deluxe / Deluxe S / Smart — частая альтернатива по 24 кВт",
        "Ferroli Fortuna / Divabel / Divatech — варианты по 24 кВт",
        "Ariston Clas / Alteas / Genus — если нужен Ariston в настенном сегменте",
        "Protherm Гепард / Пантера — если нужен Protherm",
    ]

    if intent.brand:
        brand_low = intent.brand.lower()
        models = [m for m in models if brand_low in m.lower()] or models

    return (
        "🧩 <b>Подбор котла</b>\n\n"
        f"{_summary(intent)}\n\n"
        f"По смыслу запроса: <b>{html.escape(install)}</b> газовый котел, примерно <b>{power:g} кВт</b>, "
        f"<b>{html.escape(chamber)}</b>, <b>{circuits}</b> контур(а).\n\n"
        "Что предложить менеджеру как рыночные варианты:\n"
        + "\n".join(f"• {html.escape(x)}" for x in models[:7])
        + "\n\n"
        "Что проверить перед предложением клиенту:\n"
        "• наличие на Южном складе / в 1С\n"
        "• актуальную цену у поставщиков\n"
        "• совместимость дымохода\n"
        "• нужна ли ГВС, бойлер косвенного нагрева или только отопление\n\n"
        "Следующий шаг: нажми «Остатки у поставщиков» или «Найти товар» по конкретной модели."
    )


def _water_heater_answer(intent: EquipmentIntent) -> str:
    volume = intent.volume_l or 80

    models = [
        "Ariston Lydos / ABS PRO / VLS — популярные электрические накопительные",
        "Thermex IF / Flat Plus / TitaniumHeat — частые бытовые варианты",
        "Royal Thermo накопительные — если нужен Royal Thermo",
        "Baxi бойлеры косвенного нагрева — если есть котел отопления",
        "Hajdu / Drazice — часто смотрят под косвенный нагрев",
    ]

    if intent.brand:
        brand_low = intent.brand.lower()
        models = [m for m in models if brand_low in m.lower()] or models

    return (
        "🧩 <b>Подбор бойлера / водонагревателя</b>\n\n"
        f"{_summary(intent)}\n\n"
        f"По запросу ориентир: накопительный водонагреватель примерно <b>{volume} л</b>.\n\n"
        "Рыночные варианты/линейки:\n"
        + "\n".join(f"• {html.escape(x)}" for x in models)
        + "\n\n"
        "Уточнить перед подбором:\n"
        "• электрический или косвенного нагрева\n"
        "• вертикальный или горизонтальный монтаж\n"
        "• сухой/мокрый ТЭН\n"
        "• габариты и место установки\n\n"
        "Дальше проверь конкретную модель через остатки/прайсы поставщиков."
    )


def _gas_column_answer(intent: EquipmentIntent) -> str:
    return (
        "🧩 <b>Подбор газовой колонки</b>\n\n"
        f"{_summary(intent)}\n\n"
        "Базовые варианты для ориентира:\n"
        "• Ariston Fast / Next\n"
        "• Baxi газовые колонки\n"
        "• Bosch / Thermex / Zanussi в зависимости от наличия\n\n"
        "Что важно уточнить:\n"
        "• производительность, л/мин\n"
        "• дымоудаление: атмосферная или турбо\n"
        "• давление воды\n"
        "• тип розжига\n\n"
        "Дальше лучше проверять конкретные модели через поставщиков."
    )


def _radiator_answer(intent: EquipmentIntent) -> str:
    return (
        "🧩 <b>Подбор радиатора</b>\n\n"
        f"{_summary(intent)}\n\n"
        "Ориентиры:\n"
        "• Royal Thermo — биметалл/алюминий/панельные варианты\n"
        "• Rifar — биметалл\n"
        "• Rommer / Global / Stout — альтернативы по наличию\n\n"
        "Что уточнить:\n"
        "• тип: биметалл, алюминий, стальной панельный\n"
        "• высота: 200 / 350 / 500\n"
        "• секции или размер панели\n"
        "• боковое/нижнее подключение\n\n"
        "Потом проверяем конкретную позицию в 1С и прайсах."
    )


def _pump_answer(intent: EquipmentIntent) -> str:
    return (
        "🧩 <b>Подбор насоса</b>\n\n"
        f"{_summary(intent)}\n\n"
        "Ориентиры:\n"
        "• циркуляционные 25/4, 25/6, 25/8\n"
        "• Grundfos / Wilo как премиум-ориентир\n"
        "• Stout / Valfex / Джилекс как альтернативы по наличию\n\n"
        "Что уточнить:\n"
        "• циркуляционный или поверхностный\n"
        "• монтажная длина\n"
        "• резьба\n"
        "• напор и расход\n\n"
        "Дальше проверяем остатки у поставщиков по конкретной модели."
    )


def _chimney_answer(intent: EquipmentIntent) -> str:
    return (
        "🧩 <b>Подбор дымохода</b>\n\n"
        f"{_summary(intent)}\n\n"
        "Ориентиры:\n"
        "• коаксиальный комплект под турбо-котел\n"
        "• колено 60/100 или 80/125\n"
        "• удлинитель / труба / наконечник\n\n"
        "Что уточнить:\n"
        "• бренд котла\n"
        "• диаметр\n"
        "• длина трассы\n"
        "• нужны ли колена и адаптеры\n\n"
        "Дальше проверяем совместимость с конкретным котлом."
    )


def _stabilizer_answer(intent: EquipmentIntent) -> str:
    return (
        "🧩 <b>Подбор стабилизатора / ИБП</b>\n\n"
        f"{_summary(intent)}\n\n"
        "Ориентиры:\n"
        "• стабилизатор для котла 500–1000 ВА\n"
        "• ИБП для котла, если нужна автономность\n"
        "• Штиль / Энергия / Бастион / Rucelf по наличию\n\n"
        "Что уточнить:\n"
        "• нужен стабилизатор или ИБП\n"
        "• мощность котла и насоса\n"
        "• нужна ли работа от аккумулятора\n"
        "• время автономии\n\n"
        "Дальше проверяем конкретную модель и наличие."
    )


def _build_supplier_block(intent, search_result) -> str:
    candidates = getattr(search_result, "candidates", []) or []
    fallback_candidates = getattr(search_result, "fallback_candidates", None) or []

    lines = ["🔎 <b>Прайсы поставщиков</b>"]

    lines.append("")
    lines.append("🧾 <b>Что понял по запросу:</b>")
    lines.extend(_format_detected_filters(intent))

    if candidates:
        lines.append("")
        lines.append("✅ <b>Подходящие позиции:</b>")

        if intent.brand and getattr(search_result, "exact_brand_found", False):
            lines.append(f"Бренд совпал: <b>{html.escape(intent.brand)}</b>")

        lines.append("")
        lines.extend(_format_candidate_lines(candidates[:5], icon="✅"))
        lines.append("")
        lines.append("📌 <b>Перед предложением клиенту:</b>")
        lines.extend(_manager_checklist(intent))
        return "\n".join(lines)

    if fallback_candidates:
        lines.append("")
        lines.append("⚠️ <b>Точного совпадения по всем условиям не нашёл.</b>")
        lines.append("Показываю ближайшие похожие варианты:")
        lines.append("")
        lines.extend(_format_candidate_lines(fallback_candidates[:5], icon="⚠️"))

        note = _build_fallback_note(intent)
        if note:
            lines.append("")
            lines.append(note)

        return "\n".join(lines)

    lines.append("")
    lines.append("❌ <b>В свежих прайсах не нашёл подходящих позиций.</b>")
    note = _build_empty_result_note(intent)
    if note:
        lines.append("")
        lines.append(note)

    return "\n".join(lines)


def _format_detected_filters(intent) -> list[str]:
    items = []

    labels = {
        "category": {
            "boiler": "котёл",
            "water_heater": "бойлер / водонагреватель",
            "pump": "насос",
            "chimney": "дымоход / коаксиал",
            "radiator": "радиатор",
            "stabilizer": "стабилизатор / ИБП",
            "generic": "оборудование",
        },
        "boiler_type": {
            "wall": "настенный",
            "floor": "напольный",
            "parapet": "парапетный",
        },
        "water_heater_type": {
            "electric": "электрический",
            "indirect": "косвенного нагрева",
            "tank_in_tank": "бак-в-баке",
        },
        "chamber": {
            "open": "открытая / атмосферный",
            "closed": "закрытая / турбо",
        },
        "install_type": {
            "wall": "настенный",
            "floor": "напольный",
        },
        "orientation": {
            "vertical": "выход дымохода вверх / вертикальный",
            "horizontal": "выход дымохода назад / горизонтальный",
        },
        "gas_automation": {
            "sit": "SIT",
            "tgv": "TGV",
        },
        "connection": {
            "side": "боковой подвод",
        },
        "body_shape": {
            "round": "круглый корпус",
            "rectangular": "прямоугольный корпус",
        },
        "flue_exit": {
            "vertical": "верхний / вертикальный выход дымохода",
            "horizontal": "задний / горизонтальный выход дымохода",
        },
        "tank_material": {
            "stainless": "нержавейка",
        },
        "tank_coating": {
            "enamel": "эмаль",
        },
        "heating_element": {
            "dry": "сухой ТЭН",
            "wet": "мокрый ТЭН",
        },
    }

    category = getattr(intent, "category", None)
    if category:
        items.append(f"• тип: <b>{labels['category'].get(category, category)}</b>")

    brand = getattr(intent, "brand", None)
    if brand:
        items.append(f"• бренд: <b>{html.escape(str(brand))}</b>")

    for attr, label_name in [
        ("boiler_type", "boiler_type"),
        ("water_heater_type", "water_heater_type"),
        ("install_type", "install_type"),
        ("chamber", "chamber"),
        ("orientation", "orientation"),
        ("gas_automation", "gas_automation"),
        ("connection", "connection"),
        ("body_shape", "body_shape"),
        ("flue_exit", "flue_exit"),
        ("tank_material", "tank_material"),
        ("tank_coating", "tank_coating"),
        ("heating_element", "heating_element"),
    ]:
        value = getattr(intent, attr, None)
        if value:
            items.append(f"• {attr}: <b>{labels[label_name].get(value, value)}</b>")

    power_min = getattr(intent, "power_min_kw", None)
    power_max = getattr(intent, "power_max_kw", None)
    power = getattr(intent, "power_kw", None)

    if power_min and power_max:
        items.append(f"• мощность: <b>{power_min:g}-{power_max:g} кВт</b>")
    elif power:
        items.append(f"• мощность: <b>{power:g} кВт</b>")

    volume = getattr(intent, "volume_l", None)
    volume_min = getattr(intent, "volume_min_l", None)
    volume_max = getattr(intent, "volume_max_l", None)

    if volume_min and volume_max:
        items.append(f"• объём: <b>{volume_min}-{volume_max} л</b>")
    elif volume:
        items.append(f"• объём: <b>{volume} л</b>")

    circuits = getattr(intent, "circuits", None)
    if circuits:
        items.append(f"• контуры: <b>{circuits}</b>")

    chimney = getattr(intent, "chimney_diameter_mm", None)
    if chimney:
        items.append(f"• дымоход: <b>{chimney} мм</b>")

    recirculation = getattr(intent, "recirculation", None)
    if recirculation:
        items.append("• рециркуляция: <b>нужна</b>")

    return items or ["• явных фильтров мало — ищу по смыслу запроса"]


def _manager_checklist(intent) -> list[str]:
    if getattr(intent, "category", None) == "boiler":
        return [
            "• проверить дымоход / камеру сгорания",
            "• уточнить 1 или 2 контура",
            "• сверить наличие и цену перед КП",
        ]

    if getattr(intent, "category", None) == "water_heater":
        return [
            "• проверить объём и монтаж",
            "• сверить материал бака / ТЭН / рециркуляцию",
            "• уточнить гарантию и актуальный остаток",
        ]

    return [
        "• сверить точную модель",
        "• проверить остаток и цену",
        "• уточнить совместимость с объектом клиента",
    ]


def _format_candidate_lines(candidates, icon: str) -> list[str]:
    lines: list[str] = []

    for index, item in enumerate(candidates[:5], start=1):
        price = _format_money(getattr(item, "price", None))
        stock = _format_stock(getattr(item, "stock", None))

        lines.append(f"{index}. {icon} <b>{html.escape(str(item.product_name))}</b>")
        lines.append(f"   💰 {price} | 📦 {stock}")

        reason = _label_relaxation_reason(getattr(item, "relaxation_reason", None))
        if reason:
            lines.append(f"   ↳ {reason}")

    return lines


def _build_fallback_note(intent) -> str | None:
    if intent.category == "boiler" and intent.circuits:
        return "⚠️ Проверь контурность: похожая позиция может отличаться от запроса."

    if intent.category == "water_heater":
        return "⚠️ Похожее не значит полная замена: проверь тип бойлера, объем, материал бака и рециркуляцию."

    return None


def _build_empty_result_note(intent) -> str | None:
    if intent.category == "water_heater":
        hints = []

        if getattr(intent, "recirculation", None):
            hints.append("без рециркуляции")

        if getattr(intent, "tank_material", None):
            hints.append("с другим материалом бака")

        if getattr(intent, "volume_l", None) or getattr(intent, "volume_min_l", None):
            hints.append("с соседним объемом")

        if getattr(intent, "water_heater_type", None) in {"indirect", "tank_in_tank"}:
            hints.append("по брендам ACV / Drazice / Hajdu / Baxi")

        if hints:
            return "Можно попробовать расширить поиск: " + ", ".join(hints) + "."

        return "Можно уточнить бренд, объем, тип бака или монтаж."

    if intent.category == "boiler":
        return "Можно попробовать без точной серии или уточнить контурность/камеру."

    return None


def _format_money(value) -> str:
    if value is None:
        return "цена не указана"

    try:
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except Exception:
        return str(value)


def _format_stock(value) -> str:
    if value is None:
        return "остаток не указан"

    try:
        if value != value:  # NaN
            return "остаток не указан"
        return f"{float(value):g} шт."
    except Exception:
        return str(value)


def _label_chamber(value: str | None) -> str | None:
    if value == "closed":
        return "закрытая камера / турбо"
    if value == "open":
        return "открытая камера / атмосферный"
    return value


def _label_install_type(value: str | None) -> str | None:
    if value == "wall":
        return "настенный"
    if value == "floor":
        return "напольный"
    return value



def _label_relaxation_reason(reason: str | None) -> str | None:
    labels = {
        "closest_safe": "ближайшее безопасное совпадение",
        "same_volume_other_heating_element": "тот же объем, но другой тип ТЭНа",
        "same_heating_element_nearby_volume": "тот же тип ТЭНа, но соседний объем",
        "same_volume_other_water_heater_type": "тот же объем, но другой тип бойлера",
        "same_brand_power_other_specs": "тот же бренд/мощность, но отличаются камера или контуры",
        "same_series_other_specs": "та же серия, но отличаются параметры",
    }
    return labels.get(reason)
