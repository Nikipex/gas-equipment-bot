from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from loguru import logger


@dataclass(frozen=True)
class MarketModelCandidate:
    title: str
    url: str
    model_query: str
    source: str = "web"


class MarketDiscoveryService:
    async def discover_models(self, query: str, limit: int = 10) -> list[MarketModelCandidate]:
        search_query = f"{query} купить характеристики"

        try:
            return await self._duckduckgo_search(search_query, limit=limit)
        except Exception as exc:
            logger.warning("Market discovery failed: {}", exc)
            return []

    async def _duckduckgo_search(self, query: str, limit: int) -> list[MarketModelCandidate]:
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"

        async with httpx.AsyncClient(
            timeout=8,
            headers={
                "User-Agent": "Mozilla/5.0",
            },
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        result: list[MarketModelCandidate] = []
        seen: set[str] = set()

        for a in soup.select("a.result__a"):
            title = _clean_title(a.get_text(" ", strip=True))
            href = a.get("href") or ""

            if not title or title.lower() in seen:
                continue

            if _looks_like_junk(title):
                continue

            model_query = extract_model_query(title) or title

            seen.add(title.lower())
            result.append(MarketModelCandidate(title=title, url=href, model_query=model_query))

            if len(result) >= limit:
                break

        return result


def _clean_title(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()

    remove_patterns = [
        r"\s*[-–—]\s*купить.*$",
        r"\s*[-–—]\s*цена.*$",
        r"\s*[-–—]\s*интернет.*$",
        r"\s*\|\s*.*$",
        r"\s*/\s*.*$",
    ]

    for pattern in remove_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    return text.strip()


def _looks_like_junk(title: str) -> bool:
    low = title.lower()

    bad = [
        "авито",
        "ozon",
        "wildberries",
        "яндекс маркет",
        "инструкция",
        "отзывы",
        "ремонт",
        "запчаст",
        "скачать",
        "pdf",
    ]

    return any(x in low for x in bad)


def extract_model_query(title: str) -> str | None:
    text = _clean_title(title)
    low = text.lower().replace("ё", "е")

    brand = None
    for src, normalized in [
        ("baxi", "Baxi"),
        ("бакси", "Baxi"),
        ("navien", "Navien"),
        ("ariston", "Ariston"),
        ("ferroli", "Ferroli"),
        ("protherm", "Protherm"),
        ("bosch", "Bosch"),
    ]:
        if src in low:
            brand = normalized
            break

    if not brand:
        return None

    # Берем самые полезные модельные куски.
    patterns = [
        r"eco[\s-]*4s\s*1?\.?\s*24\s*f",
        r"eco[\s-]*4s\s*24\s*f",
        r"eco[\s-]*four\s*24\s*f",
        r"eco[\s-]*nova\s*24\s*f",
        r"eco[\s-]*life\s*24\s*f",
        r"main[\s-]*four\s*24\s*f",
        r"luna[\s-]*3\s*240\s*fi",
        r"deluxe\s*c?\s*24k",
        r"ngb\s*210[\s-]*24k",
        r"clas\s*x?\s*24\s*ff",
        r"alteas\s*x?\s*24\s*ff",
        r"genus\s*x?\s*24\s*ff",
        r"[a-zа-я0-9]+[\s-]*(?:24f|f24|24\s*f|24k|24\s*k|240\s*fi)",
    ]

    for pattern in patterns:
        match = re.search(pattern, low, flags=re.IGNORECASE)
        if match:
            model = match.group(0)
            model = re.sub(r"\s+", " ", model).strip()
            return f"{brand} {model}"

    return None
