"""YandexGPT-powered intent parser.

AI is used only to convert manager natural language into a strict command.
All prices, stock and supplier data remain calculated by deterministic services.
"""

from __future__ import annotations

import json
import os

from loguru import logger
from openai import OpenAI

from app.services.ai.intent_models import AiIntent


SYSTEM_PROMPT = """
Ты intent parser для b2b-бота по газовому оборудованию.

Твоя задача — вернуть только JSON без markdown.

Разрешенные intent:
- supplier_search: поиск остатков у поставщиков
- price_list: составить прайс/список цен
- quote: просчет нескольких позиций
- unknown: если команда непонятна

Правила:
- Не считай цены сам.
- Не придумывай остатки.
- Не придумывай поставщиков.
- query должен быть короткой поисковой строкой.
- supplier_key может быть только: "ib", "yulas" или null.
- round_step может быть только 10, 100 или null.
- discount_percent допустим от 1 до 12 или null.
- markup_amount — фиксированная прибавка в рублях или null.
- client_mode=true если просят "для клиента", "без закупки", "без остатков".
- show_stock=false если просят убрать остатки.
- show_purchase=false если просят убрать закупку.

Примеры:

Текст: "найди у поставщиков baxi eco 4s 24, скидка 5, округли до сотен"
JSON:
{"intent":"supplier_search","query":"baxi eco 4s 24","supplier_key":null,"discount_percent":5,"markup_amount":null,"round_step":100,"client_mode":false,"show_stock":true,"show_purchase":true}

Текст: "сделай клиентский прайс по фондитал +20 процентов без закупки"
JSON:
{"intent":"price_list","query":"fondital","supplier_key":null,"discount_percent":null,"markup_amount":null,"round_step":null,"client_mode":true,"show_stock":true,"show_purchase":false}

Текст: "иб аристон nts 30"
JSON:
{"intent":"supplier_search","query":"ariston nts 30","supplier_key":"ib","discount_percent":null,"markup_amount":null,"round_step":null,"client_mode":false,"show_stock":true,"show_purchase":true}
""".strip()


class YandexGptIntentService:
    def __init__(self) -> None:
        self.enabled = os.getenv("AI_INTENT_ENABLED", "false").lower() == "true"
        self.api_key = os.getenv("YANDEX_API_KEY")
        self.folder_id = os.getenv("YANDEX_FOLDER_ID")
        self.model = os.getenv("YANDEX_MODEL", "yandexgpt/rc")
        self.base_url = os.getenv("YANDEX_BASE_URL", "https://ai.api.cloud.yandex.net/v1")

    def parse(self, text: str) -> AiIntent:
        if not self.enabled or not self.api_key:
            return AiIntent(intent="unknown", query="", raw_text=text)

        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            default_headers=_build_headers(self.folder_id),
        )

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content or "{}"
            data = json.loads(content)

            return AiIntent(
                intent=data.get("intent", "unknown"),
                query=str(data.get("query") or "").strip(),
                supplier_key=data.get("supplier_key"),
                discount_percent=_to_float_or_none(data.get("discount_percent")),
                markup_amount=_to_float_or_none(data.get("markup_amount")),
                round_step=_to_round_step(data.get("round_step")),
                client_mode=bool(data.get("client_mode", False)),
                show_stock=bool(data.get("show_stock", True)),
                show_purchase=bool(data.get("show_purchase", True)),
                raw_text=text,
            )

        except Exception as exc:
            logger.exception("YandexGPT intent parsing failed: {}", exc)
            return AiIntent(intent="unknown", query="", raw_text=text)


def _build_headers(folder_id: str | None) -> dict[str, str]:
    headers = {}

    if folder_id:
        headers["x-folder-id"] = folder_id

    return headers


def _to_float_or_none(value: object) -> float | None:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_round_step(value: object) -> int | None:
    try:
        step = int(value)
    except (TypeError, ValueError):
        return None

    if step in {10, 100}:
        return step

    return None
