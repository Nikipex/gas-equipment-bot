import re
from dataclasses import dataclass


@dataclass
class RankedCandidate:
    title: str
    score: float


def normalize(text: str) -> str:
    return (
        text.lower()
        .replace("-", "")
        .replace(".", "")
        .replace("ё", "е")
    )


def rank_teplocel(query: str, title: str) -> float:
    q = normalize(query)
    t = normalize(title)

    score = 0.0

    if "baxi" in q and "baxi" in t:
        score += 0.25

    if "eco4s" in q and "eco4s" in t:
        score += 0.35

    q24 = bool(re.search(r"\b24f\b|\b24 f\b", q))
    t24 = bool(re.search(r"\b24f\b|\b24 f\b", t))

    q124 = bool(re.search(r"\b124f\b|\b124 f\b", q))
    t124 = bool(re.search(r"\b124f\b|\b124 f\b", t))

    if q24 and t24:
        score += 0.35

    if q24 and t124:
        score -= 0.50

    if q124 and t124:
        score += 0.35

    return round(score, 3)
