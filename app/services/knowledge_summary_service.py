from __future__ import annotations

from pathlib import Path

from loguru import logger

from app.services.ai.yandex_gpt_service import YandexGPTService
from app.services.knowledge_base_service import KnowledgeBaseService


class KnowledgeSummaryService:
    def __init__(self) -> None:
        self.gpt = YandexGPTService()
        self.reader = KnowledgeBaseService()

    def create_summary_for_file(self, path: Path) -> Path | None:
        try:
            text = self.reader._read_file(path)
            text = self.reader._clean_text(text)

            if not text:
                return None

            text = text[:12000]

            summary = self._summarize(text, source_name=path.name)

            summary_path = path.with_suffix(path.suffix + ".summary.md")
            summary_path.write_text(summary, encoding="utf-8")

            return summary_path

        except Exception as exc:
            logger.exception("Failed to create knowledge summary for {}: {}", path, exc)
            return None

    def _summarize(self, text: str, source_name: str) -> str:
        prompt = f"""
Ты создаёшь внутреннюю карточку базы знаний для менеджеров по газовому и отопительному оборудованию.

Источник:
{source_name}

Текст документа:
{text}

Сделай краткую markdown-карточку.

Формат:

# Knowledge Summary: <название модели/документа>

## Что это

## Бренд / модель

## Категория

## Ключевые характеристики

## Что важно менеджеру

## Аналоги / замены, если видно из текста

## Что сверить перед КП

Правила:
- Не выдумывай точные характеристики.
- Если точных данных нет, не пиши их.
- Пиши коротко и прикладно.
- Не используй длинную воду.
""".strip()

        return self.gpt.think_about_equipment(prompt, context="")


knowledge_summary_service = KnowledgeSummaryService()
