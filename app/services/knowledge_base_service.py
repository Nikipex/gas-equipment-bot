from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


KB_ROOT = Path("data/knowledge_base")
INDEX_PATH = Path("data/knowledge_base_index/index.json")


@dataclass(frozen=True)
class KnowledgeChunk:
    source: str
    text: str
    score: float


def _normalize_query_text(value: str) -> str:
    text = str(value or "").lower().replace("ё", "е")

    replacements = {
        "бакси": "baxi",
        "баксиэ": "baxi",
        "навьен": "navien",
        "навиен": "navien",
        "аристон": "ariston",
        "лемакс": "lemax",
        "классик": "classic",
        "премиум": "premium",
        "сибирия": "siberia",
        "сиберия": "siberia",
        "федерика": "federica",
        "бугатти": "bugatti",
        "бугати": "bugatti",
        "арту": "artu",
        "радиатор": "radiator",
        "радиаторы": "radiator",
        "бойлер": "boiler",
        "бойлеры": "boiler",
        "котел": "boiler",
        "котлы": "boiler",
        "котёл": "boiler",
    }

    for src, dst in replacements.items():
        text = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", dst, text)

    return text



class KnowledgeBaseService:
    def __init__(self, kb_root: Path = KB_ROOT, index_path: Path = INDEX_PATH) -> None:
        self.kb_root = kb_root
        self.index_path = index_path

    def build_index(self) -> dict:
        docs: list[dict] = []

        for path in sorted(self.kb_root.rglob("*")):
            if not path.is_file():
                continue

            suffix = path.suffix.lower()
            if suffix not in {".txt", ".md", ".pdf"}:
                continue

            try:
                text = self._read_file(path)
            except Exception as exc:
                logger.warning("Failed to read KB file {}: {}: {}", path, type(exc).__name__, exc)
                continue

            text = self._clean_text(text)
            if not text:
                continue

            chunks = self._chunk_text(text, max_chars=1800)

            for idx, chunk in enumerate(chunks):
                docs.append(
                    {
                        "source": str(path),
                        "source_norm": _normalize_query_text(str(path)),
                        "chunk_id": idx,
                        "text": chunk,
                        "text_norm": _normalize_query_text(chunk),
                    }
                )

        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps({"docs": docs}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info("Knowledge base index built: {} chunks", len(docs))
        return {"docs": docs}

    def search(self, query: str, limit: int = 4) -> list[KnowledgeChunk]:
        index = self._load_or_build_index()
        docs = index.get("docs", [])

        q_tokens = self._tokens(query)
        if not q_tokens:
            return []

        scored: list[KnowledgeChunk] = []

        for doc in docs:
            text = str(doc.get("text", ""))
            searchable = f"{doc.get('source_norm', '')}\n{doc.get('text_norm', '')}"
            score = self._score(q_tokens, searchable)

            if score <= 0:
                continue

            scored.append(
                KnowledgeChunk(
                    source=str(doc.get("source", "")),
                    text=text,
                    score=score,
                )
            )

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]

    def build_context(self, query: str, limit: int = 4) -> str:
        chunks = self.search(query, limit=limit)
        if not chunks:
            return ""

        parts = []
        for i, chunk in enumerate(chunks, 1):
            parts.append(
                f"[Источник {i}: {chunk.source}, score={chunk.score:.2f}]\\n"
                f"{chunk.text}"
            )

        return "\\n\\n---\\n\\n".join(parts)

    def _load_or_build_index(self) -> dict:
        if not self.index_path.exists():
            return self.build_index()

        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return self.build_index()

    def _read_file(self, path: Path) -> str:
        suffix = path.suffix.lower()

        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore")

        if suffix == ".pdf":
            return self._read_pdf(path)

        return ""

    def _read_pdf(self, path: Path) -> str:
        try:
            from pypdf import PdfReader
        except Exception:
            try:
                from PyPDF2 import PdfReader
            except Exception as exc:
                raise RuntimeError("No PDF reader installed. Install pypdf.") from exc

        reader = PdfReader(str(path))
        parts: list[str] = []

        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue

        return "\\n".join(parts)

    @staticmethod
    def _clean_text(text: str) -> str:
        text = text.replace("\\x00", " ")
        text = re.sub(r"[ \\t]+", " ", text)
        text = re.sub(r"\\n{3,}", "\\n\\n", text)
        return text.strip()

    @staticmethod
    def _chunk_text(text: str, max_chars: int = 1800) -> list[str]:
        paragraphs = [p.strip() for p in re.split(r"\\n\\s*\\n", text) if p.strip()]
        chunks: list[str] = []
        current = ""

        for paragraph in paragraphs:
            if len(current) + len(paragraph) + 2 <= max_chars:
                current = f"{current}\\n\\n{paragraph}".strip()
            else:
                if current:
                    chunks.append(current)
                current = paragraph

        if current:
            chunks.append(current)

        return chunks

    @staticmethod
    def _tokens(text: str) -> list[str]:
        text = _normalize_query_text(text)
        tokens = re.findall(r"[a-zа-я0-9]{3,}", text)
        stop = {
            "что", "как", "для", "или", "это", "если", "чем", "какая",
            "разница", "между", "котел", "котлы", "газовый", "газовые",
            "реально", "аналог", "какой", "какие",
        }
        return [t for t in tokens if t not in stop]

    @staticmethod
    def _score(query_tokens: list[str], text: str) -> float:
        low = _normalize_query_text(text)
        score = 0.0

        for token in query_tokens:
            count = low.count(token)
            if count:
                score += min(count, 5)

        # Бонус за совпадение нескольких токенов.
        matched = sum(1 for token in query_tokens if token in low)
        if matched >= 2:
            score += matched * 2

        return score


knowledge_base_service = KnowledgeBaseService()
