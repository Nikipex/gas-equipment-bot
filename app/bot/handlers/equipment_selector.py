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

router = Router()


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


@router.message(lambda message: message.text and message.text.lower().startswith(("подбор ", "подбери ", "подобрать ")))
async def process_equipment_selection(message: Message) -> None:
    text = message.text or ""
    intent = _parse_intent(text)

    logger.info(f"AI equipment selector request: category={intent.category} text={text}")

    await message.answer(
        "🧠 Анализирую запрос как ассистент по подбору оборудования…",
        reply_markup=main_menu_kb,
    )

    answer = _build_answer(intent)

    await message.answer(
        answer,
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
        parts.append(f"монтаж: <b>{html.escape(intent.install_type)}</b>")
    if intent.chamber:
        parts.append(f"камера: <b>{html.escape(intent.chamber)}</b>")
    if intent.circuits:
        parts.append(f"контуры: <b>{intent.circuits}</b>")

    return "Параметры: " + (", ".join(parts) if parts else "уточняются по запросу")


def _boiler_answer(intent: EquipmentIntent) -> str:
    power = intent.power_kw or 24
    install = intent.install_type or "настенный"
    chamber = intent.chamber or "закрытая камера / турбо"
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
