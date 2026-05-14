"""Fuzzy matching helpers for product search."""

from __future__ import annotations

from difflib import SequenceMatcher

from app.utils.normalization import normalize_text


def similarity(a: str, b: str) -> float:
    """Return similarity ratio (0..1) between two strings."""
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def best_matches(
    query: str,
    candidates: list[str],
    threshold: float = 0.4,
    top_n: int = 10,
) -> list[tuple[str, float]]:
    """Return top-N candidates exceeding the similarity threshold.

    Returns list of (candidate, score) sorted by score descending.
    """
    scored = [
        (c, similarity(query, c))
        for c in candidates
    ]
    scored = [(c, s) for c, s in scored if s >= threshold]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_n]
