from __future__ import annotations

import os

from openai import OpenAI


class QwenService:
    def __init__(self) -> None:
        self.base_url = "https://ai.api.cloud.yandex.net/v1"

    def ask(
        self,
        question: str,
        context: str = "",
        system_prompt: str = "",
        temperature: float = 0.3,
        max_output_tokens: int = 1800,
    ) -> str:
        api_key = os.getenv("QWEN_API_KEY", "")
        folder_id = os.getenv("QWEN_FOLDER_ID", "")
        model = os.getenv("QWEN_MODEL", "")

        if not api_key:
            raise RuntimeError("QWEN_API_KEY is empty")
        if not folder_id:
            raise RuntimeError("QWEN_FOLDER_ID is empty")
        if not model:
            raise RuntimeError("QWEN_MODEL is empty")

        input_text = question

        if context:
            input_text = (
                "ДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ:\n"
                f"{context}\n\n"
                "ВОПРОС:\n"
                f"{question}"
            )

        client = OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            project=folder_id,
        )

        response = client.responses.create(
            model=f"gpt://{folder_id}/{model}",
            temperature=temperature,
            instructions=system_prompt,
            input=input_text,
            max_output_tokens=max_output_tokens,
        )

        return response.output_text.strip()


qwen_service = QwenService()
