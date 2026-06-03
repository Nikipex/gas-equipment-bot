"""YandexGPT HTTP client."""

from __future__ import annotations

import json
import os
import re

import requests
from dotenv import load_dotenv


API_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


class YandexGPTService:
    def __init__(self) -> None:
        load_dotenv(".env", override=True)

        self.api_key = (
            os.getenv("YANDEX_GPT_API_KEY")
            or os.getenv("YANDEX_API_KEY")
            or ""
        ).strip()

        self.folder_id = (
            os.getenv("YANDEX_GPT_FOLDER_ID")
            or os.getenv("YANDEX_FOLDER_ID")
            or ""
        ).strip()

        raw_model_uri = (
            os.getenv("YANDEX_GPT_MODEL_URI")
            or ""
        ).strip()

        self.model_uri = self._resolve_model_uri(raw_model_uri)

    def _resolve_model_uri(self, raw_model_uri: str) -> str:
        if raw_model_uri.startswith("gpt://") and "/yandexgpt" in raw_model_uri:
            return raw_model_uri

        if not self.folder_id:
            raise RuntimeError("YANDEX_GPT_FOLDER_ID is empty")

        return f"gpt://{self.folder_id}/yandexgpt/latest"

    def extract_intent(self, text: str) -> dict:
        if not self.api_key:
            raise RuntimeError("YANDEX_GPT_API_KEY is empty")

        if not self.model_uri:
            raise RuntimeError("YANDEX_GPT_MODEL_URI is empty")

        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }

        system_prompt = """
Ты AI parser для procurement Telegram bot.

ТВОЯ ЗАДАЧА:
извлекать структуру команды.

Отвечай ТОЛЬКО JSON.
Без markdown.
Без пояснений.

Формат:
{
  "intent": "supplier_search",
  "query": "",
  "supplier_key": null,
  "discount_percent": null,
  "markup_amount": null,
  "round_step": null,
  "client_mode": false,
  "show_stock": true,
  "show_purchase": true
}

Правила:
- intent: supplier_search, price_list, stock_search, quote, unknown
- "до сотен" => round_step=100
- "до десятков" => round_step=10
- "скидка 5" => discount_percent=5
- "наценка 3000" или "прибавь 3000" => markup_amount=3000
- "для клиента" => client_mode=true
- "без остатков" => show_stock=false
- "без закупки" => show_purchase=false
- "иб" => supplier_key="ib"
- "юлас" => supplier_key="yulas"
""".strip()

        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0,
                "maxTokens": "400",
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": text},
            ],
        }

        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)

        if response.status_code >= 400:
            raise RuntimeError(
                f"YandexGPT API error {response.status_code}: "
                f"modelUri={self.model_uri!r}; "
                f"folder_id={self.folder_id!r}; "
                f"body={response.text}"
            )

        data = response.json()
        content = data["result"]["alternatives"][0]["message"]["text"].strip()
        content = _extract_json_text(content)

        try:
            return json.loads(content)
        except Exception:
            return {
                "intent": "unknown",
                "query": "",
                "supplier_key": None,
                "discount_percent": None,
                "markup_amount": None,
                "round_step": None,
                "client_mode": False,
                "show_stock": True,
                "show_purchase": True,
                "raw_response": content,
            }

    def summarize_product_global_search(self, query: str) -> str:
        if not self.api_key:
            raise RuntimeError("YANDEX_GPT_API_KEY is empty")

        if not self.model_uri:
            raise RuntimeError("YANDEX_GPT_MODEL_URI is empty")

        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }

        system_prompt = """
Ты опытный помощник менеджера по продаже и закупке газового/отопительного оборудования.

Твоя задача — по запросу менеджера дать практичную справку, чтобы он быстро понял, что искать и что проверить.

ВАЖНО:
- Не выдумывай точную цену.
- Не выдумывай наличие.
- Не утверждай, что товар точно существует, если модель редкая.
- Если запрос похож на конкретную модель, выдели вероятные признаки из названия.
- Если данных мало, напиши "нужно сверить по паспорту/карточке".
- Пиши коротко, но полезно.
- Не используй markdown-заголовки с **.
- Не пиши длинную воду.

Формат:

🔎 Что это может быть:
1-2 предложения. Укажи тип товара, вероятную мощность/исполнение, если видно из названия.

📌 Что проверить:
- мощность
- тип: напольный/настенный/парапетный/дымоходный/турбо
- контурность
- автоматика/газовый клапан, если применимо
- диаметр дымохода/выход дымохода, если применимо
- совместимость/комплектация

🔁 Что искать похожее:
2-5 коротких поисковых формулировок/аналогов. Не выдумывай конкретный бренд, если не уверен.

⚠️ Перед КП:
2-4 пункта, что менеджеру обязательно перепроверить.
""".strip()

        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0.2,
                "maxTokens": "700",
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": query},
            ],
        }

        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)

        if response.status_code >= 400:
            raise RuntimeError(
                f"YandexGPT API error {response.status_code}: "
                f"modelUri={self.model_uri!r}; "
                f"folder_id={self.folder_id!r}; "
                f"body={response.text}"
            )

        data = response.json()
        return data["result"]["alternatives"][0]["message"]["text"].strip()

    def think_about_equipment(self, question: str) -> str:
        if not self.api_key:
            raise RuntimeError("YANDEX_GPT_API_KEY is empty")

        if not self.model_uri:
            raise RuntimeError("YANDEX_GPT_MODEL_URI is empty")

        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }

        system_prompt = """
Ты AI-консультант для менеджеров компании по продаже газового и отопительного оборудования.

Темы:
- газовые котлы
- радиаторы
- бойлеры
- коаксиальные дымоходы
- насосы
- стабилизаторы
- подбор аналогов
- объяснение клиенту
- сценарии в стиле "а что если"

Правила:
- Отвечай по-русски.
- Пиши практично, как помощник менеджера.
- Не выдумывай точные цены и остатки.
- Если нужны цены/остатки, предложи проверить через поиск товара или поставщиков.
- Не давай опасные инструкции по монтажу газа.
- По газовым работам напоминай: подключение и монтаж выполняет специалист с допуском.
- Не пиши длинную воду.
- Структурируй ответ короткими блоками.
""".strip()

        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0.3,
                "maxTokens": "1200",
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": question},
            ],
        }

        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)

        if response.status_code >= 400:
            raise RuntimeError(
                f"YandexGPT API error {response.status_code}: "
                f"modelUri={self.model_uri!r}; "
                f"folder_id={self.folder_id!r}; "
                f"body={response.text}"
            )

        data = response.json()
        return data["result"]["alternatives"][0]["message"]["text"].strip()


def _extract_json_text(value: str) -> str:
    text = value.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]

    return text
