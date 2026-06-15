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


    def explain_equipment_alternatives(self, source_name: str, category: str, candidates: list[dict]) -> str:
        if not self.api_key:
            raise RuntimeError("YANDEX_GPT_API_KEY is empty")

        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }

        candidates_text = "\n".join(
            f"{i}. {item.get('name')} | остаток={item.get('stock_qty')} | закупка={item.get('purchase_price')}"
            for i, item in enumerate(candidates, 1)
        )

        system_prompt = """
Ты помощник менеджера по газовому и отопительному оборудованию.

Твоя задача — коротко объяснить, почему найденные товары могут быть аналогами.

ВАЖНО:
- Не выдумывай товары, цены и остатки.
- Работай только с переданным списком кандидатов.
- Не утверждай 100% совместимость.
- Обязательно напомни сверить подключение, дымоход/габариты и комплектацию.
- Пиши коротко, по делу, без markdown-заголовков.
""".strip()

        user_prompt = f"""
Исходная позиция:
{source_name}

Категория:
{category}

Кандидаты из базы:
{candidates_text}

Сделай короткое пояснение:
1) по какому принципу подобраны аналоги
2) какие 2-3 кандидата выглядят наиболее близкими
3) что обязательно проверить перед КП
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
                {"role": "user", "text": user_prompt},
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


    def think_about_equipment(self, question: str, context: str = "") -> str:
        if not self.api_key:
            raise RuntimeError("YANDEX_GPT_API_KEY is empty")

        if not self.model_uri:
            raise RuntimeError("YANDEX_GPT_MODEL_URI is empty")

        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }

        system_prompt = """
Ты внутренний AI Sales Engineer для менеджеров компании по продаже газового и отопительного оборудования.

Главная задача:
дать менеджеру конкретный технический ответ, как будто он спросил опытного коллегу в отделе продаж.

НЕ НАДО:
- писать корпоративную воду;
- постоянно говорить "уточните требования";
- выносить наружу свои размышления;
- писать однотипные блоки "Риски" и "Фраза клиенту" в каждом ответе;
- говорить "улучшенные характеристики" без расшифровки;
- превращать каждый ответ в юридическую перестраховку.

НАДО:
- дать прямой вывод в первых 1-2 строках;
- объяснить техническую суть простым языком;
- если сравнение — сравнить по конкретным параметрам;
- если аналог — сказать, можно ли рассматривать как аналог и где ограничения;
- если точных паспортных данных нет, не выдумывать цифры, но объяснить что именно нужно сверить;
- писать как старший менеджер/технарь, а не как энциклопедия.

Формат по умолчанию:

Коротко:
прямой ответ без воды.

По сути:
разжуй техническую и коммерческую логику нормальным языком.

Технически:
- сравни конкретные параметры, если они есть в контексте
- не перечисляй лишнее, если вопрос простой
- не пиши паспортную перестраховку без необходимости

Как продавать:
когда предлагать первый вариант, когда второй, какой аргумент дать клиенту.

Как сказать клиенту:
дай готовую короткую фразу человеческим языком, если вопрос звучит как:
"как объяснить", "что сказать", "как донести", "чем аргументировать".

Что обязательно сверить:
только реально важные 3-5 пунктов, если без проверки можно ошибиться.

Правила:
- Если есть внутренний контекст, используй его как основу.
- Если внутреннего контекста нет, дай практический ответ, но честно пометь, что паспортные цифры надо сверить.
- Не выдумывай точные цены, остатки, КПД, вес, если они не даны.
- Не давай инструкции по газовому монтажу. Монтаж и подключение выполняет специалист с допуском.
- Ответ должен быть плотным и полезным.
- Не искажай названия брендов и моделей из контекста.
- Пиши бренды ровно так, как они указаны: BAXI, Navien, Ariston, Federica Bugatti, Лемакс, Сибирия, Арту.
- Не превращай Ariston в 'Aris on', Bugatti в 'Buga i', Navien в 'Навиен' внутри списка моделей.


ОСОБОЕ ПРАВИЛО ПО ПОСТАВЩИКАМ:
- Supplier cache / прайсы поставщиков — это не подтвержденный резерв.
- Если товар найден у поставщика, пиши: "можно проверить у поставщика", "есть в прайсе", "по прайсу найдено".
- Не пиши "точно есть" без подтвержденного остатка.
- Разделяй склад компании и поставщиков.
- Если на складе компании нет, но поставщик найден — предложи вариант: "проверить наличие у поставщика".

ОСОБОЕ ПРАВИЛО ПО ОСТАТКАМ:
- Не пиши "есть на складе", если в контексте нет конкретного остатка.
- Если говоришь про наличие, обязательно укажи свободный остаток/всего/резерв, если эти данные есть.
- Если в контексте написано "остаток=0", "не найдено" или данных по складу нет — пиши "наличие нужно проверить".
- Не превращай похожую модель в доступную модель без подтверждения остатка из PostgreSQL.
- Для аналогов разделяй: "подходит по характеристикам" и "подтверждено по складу".

ОСОБОЕ ПРАВИЛО ДЛЯ БАЗЫ ЗНАНИЙ:
- Если во внутреннем контексте есть информация по вопросу, отвечай по ней уверенно.
- Не пиши постоянно "нужно сверить", если ответ уже есть в контексте.
- Не пересказывай весь контекст подряд — сделай вывод для менеджера.
- Если вопрос про сравнение, дай конкретную разницу.
- Если вопрос про аналог, скажи прямо: можно рассматривать или нет.
- Если данных в контексте мало, честно скажи, каких именно данных не хватает, но сначала дай практический вывод.
- Не выводи свои размышления наружу.
- Не используй фразы "может быть", "вероятно", "возможно", если в контексте есть прямое утверждение.

""".strip()

        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0.15,
                "maxTokens": "2000",
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": (
                    "ВОПРОС МЕНЕДЖЕРА:\n"
                    f"{question}\n\n"
                    "ВНУТРЕННИЙ КОНТЕКСТ / СПРАВОЧНИК:\n"
                    f"{context if context else 'Нет отдельного справочного контекста.'}\n\n"
                    "ТРЕБОВАНИЕ К ОТВЕТУ:\n"
                    "- Если есть внутренний контекст, используй его как основу.\n"
                    "- Не отвечай общими словами.\n"
                    "- Дай конкретное сравнение/решение.\n"
                    "- Если точные данные по модели нужно сверить, скажи что именно сверить, но сначала дай полезный вывод."
                )},
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
