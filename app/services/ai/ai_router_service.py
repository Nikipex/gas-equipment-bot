from app.services.ai.yandex_gpt_service import (
    YandexGPTService,
)


class AIRouterService:
    def __init__(self) -> None:
        self.gpt = YandexGPTService()

    def parse(self, text: str) -> dict:
        return self.gpt.extract_intent(text)
