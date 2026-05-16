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
