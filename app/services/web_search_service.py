from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from urllib.parse import quote_plus, unquote, urlparse, parse_qs

import requests
from loguru import logger


@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str
    page_text: str = ""


class WebSearchService:
    def __init__(self) -> None:
        self.enabled = os.getenv("WEB_SEARCH_ENABLED", "0") == "1"
        self.max_results = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "4"))
        self.fetch_pages = int(os.getenv("WEB_SEARCH_FETCH_PAGES", "2"))

    def build_context(self, question: str) -> str:
        if not self.enabled:
            return ""

        if not self._should_search(question):
            return ""

        results = self.search(question, limit=self.max_results)
        if not results:
            return ""

        parts = ["# Web Search Context", "Используй web-контекст для фактов, но не выдумывай данные, которых там нет."]

        for i, r in enumerate(results, 1):
            text = r.page_text or r.snippet
            text = self._clip(text, 3500)

            parts.append(
                f"\n## Источник {i}\n"
                f"Название: {r.title}\n"
                f"URL: {r.url}\n"
                f"Фрагмент:\n{text}"
            )

        return "\n\n".join(parts)

    def search(self, query: str, limit: int = 4) -> list[WebSearchResult]:
        try:
            search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
            resp = requests.get(
                search_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "ru,en;q=0.9",
                },
                timeout=15,
            )
            resp.raise_for_status()

            results = self._parse_duckduckgo(resp.text)[:limit]

            for r in results[: self.fetch_pages]:
                r.page_text = self._fetch_page_text(r.url)

            return results

        except Exception as exc:
            logger.warning("Web search failed: {}: {}", type(exc).__name__, exc)
            return []

    def _parse_duckduckgo(self, text: str) -> list[WebSearchResult]:
        blocks = re.findall(
            r'<div class="result results_links.*?</div>\s*</div>',
            text,
            flags=re.S,
        )

        results: list[WebSearchResult] = []

        for block in blocks:
            title_match = re.search(r'<a rel="nofollow" class="result__a" href="(.*?)">(.*?)</a>', block, flags=re.S)
            snippet_match = re.search(r'<a class="result__snippet".*?>(.*?)</a>', block, flags=re.S)

            if not title_match:
                continue

            url = html.unescape(title_match.group(1))
            title = self._strip_html(title_match.group(2))
            snippet = self._strip_html(snippet_match.group(1)) if snippet_match else ""

            url = self._clean_ddg_url(url)

            if not url.startswith("http"):
                continue

            results.append(WebSearchResult(title=title, url=url, snippet=snippet))

        return results

    def _fetch_page_text(self, url: str) -> str:
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "ru,en;q=0.9",
                },
                timeout=12,
            )
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "").lower()
            if "text/html" not in content_type:
                return ""

            text = resp.text
            text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
            text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
            text = self._strip_html(text)
            text = re.sub(r"\s+", " ", text).strip()

            return self._clip(text, 5000)

        except Exception:
            return ""

    @staticmethod
    def _strip_html(value: str) -> str:
        value = re.sub(r"<.*?>", " ", value, flags=re.S)
        value = html.unescape(value)
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _clean_ddg_url(url: str) -> str:
        if "duckduckgo.com/l/?" not in url:
            return url

        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg", [""])[0]
        return unquote(uddg) if uddg else url

    @staticmethod
    def _clip(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return value[:limit] + "\n[...обрезано...]"

    @staticmethod
    def _should_search(question: str) -> bool:
        q = question.lower().replace("ё", "е")
        triggers = [
            "габарит", "размер", "вес", "кпд", "расход газа",
            "диаметр", "дымоход", "паспорт", "характеристик",
            "чем отличается", "разница", "аналог", "реально",
            "лемакс", "baxi", "бакси", "navien", "навьен",
            "сиберия", "арту", "ariston", "аристон",
        ]
        return any(t in q for t in triggers)


web_search_service = WebSearchService()
