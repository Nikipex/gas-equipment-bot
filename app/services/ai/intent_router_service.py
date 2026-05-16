"""Route AI intents to existing deterministic command text."""

from __future__ import annotations

from app.services.ai.intent_models import AiIntent
from app.services.ai.yandex_gpt_intent_service import YandexGptIntentService


class IntentRouterService:
    def __init__(self) -> None:
        self.ai = YandexGptIntentService()

    def parse(self, text: str) -> AiIntent:
        return self.ai.parse(text)
