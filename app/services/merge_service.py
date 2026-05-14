"""Product deduplication & merge service.

Groups logically identical products from different sources into
:class:`MergedGroup` objects, enabling multi-source price comparison.

Merge strategy (deterministic, rule-based):

1. **Priority A — SKU match**:  products with the same normalised SKU
   are grouped together.
2. **Priority B — name fingerprint**:  if SKU is absent, a fingerprint
   built from ``brand + category + cleaned_name`` is used.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from loguru import logger

from app.schemas.normalized_product import NormalizedProduct


# ---------------------------------------------------------------------------
# Public models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MergedGroup:
    """A logical product with one or more source records."""

    group_key: str
    canonical_name: str
    brand: str | None
    category: str | None
    sku: str | None
    products: tuple[NormalizedProduct, ...]  # frozen → tuple instead of list


@dataclass(slots=True)
class MergeStats:
    """Quick summary of merge results."""

    raw_count: int = 0
    group_count: int = 0
    merged_by_sku: int = 0
    merged_by_name: int = 0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MergeService:
    """Group identical products from one or more import sources.

    Usage::

        svc = MergeService(products)
        groups = svc.merge_products()
    """

    def __init__(self, products: list[NormalizedProduct]) -> None:
        self._products = products

    def merge_products(self) -> list[MergedGroup]:
        """Run the full merge and return sorted groups."""
        buckets: dict[str, list[NormalizedProduct]] = defaultdict(list)
        stats = MergeStats(raw_count=len(self._products))

        for product in self._products:
            key = self._resolve_key(product)
            buckets[key].append(product)

        groups: list[MergedGroup] = []
        for key, members in buckets.items():
            canonical = choose_canonical_name(members)
            group = MergedGroup(
                group_key=key,
                canonical_name=canonical,
                brand=_first_non_empty(m.brand for m in members),
                category=_first_non_empty(m.category for m in members),
                sku=_first_non_empty(normalize_sku(m.sku) for m in members),
                products=tuple(members),
            )
            groups.append(group)

            # stats bookkeeping
            if key.startswith("sku:"):
                stats.merged_by_sku += 1
            else:
                stats.merged_by_name += 1

        groups.sort(key=lambda g: g.canonical_name)
        stats.group_count = len(groups)

        logger.info(
            "Merge: {} товаров → {} групп (SKU: {}, name: {})",
            stats.raw_count,
            stats.group_count,
            stats.merged_by_sku,
            stats.merged_by_name,
        )
        return groups

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_key(product: NormalizedProduct) -> str:
        """Pick the best grouping key for *product*."""
        norm_sku = normalize_sku(product.sku)
        if norm_sku:
            return f"sku:{norm_sku}"
        return f"fp:{build_name_fingerprint(product)}"


# ---------------------------------------------------------------------------
# Helpers (module-level for testability)
# ---------------------------------------------------------------------------


def normalize_sku(sku: str | None) -> str | None:
    """Normalise SKU for comparison.

    * uppercase
    * strip whitespace
    * collapse separators (``-``, ``_``, ``.``, `` ``) into nothing
    * keep only alphanumeric characters

    >>> normalize_sku("bx-eco-124f")
    'BXECO124F'
    >>> normalize_sku("BX ECO 124F")
    'BXECO124F'
    >>> normalize_sku(None)
    """
    if not sku:
        return None
    cleaned = re.sub(r"[\s\-_./]+", "", sku).upper()
    cleaned = re.sub(r"[^A-ZА-ЯЁ0-9]", "", cleaned)
    return cleaned or None


def build_name_fingerprint(product: NormalizedProduct) -> str:
    """Build a deterministic, order-independent fingerprint.

    Steps:
    1. Start from the full normalised name (brand already removed by
       :func:`clean_product_name`).
    2. Strip category noise words (радиатор, котел, etc.).
    3. Tokenise → sort alphabetically.
    4. Combine with brand + category prefix.

    This ensures cosmetic reorderings like
    ``"Радиатор Kermi FKO 22 500x1000"`` and
    ``"Kermi FKO 22 500x1000"`` collapse into the same key.
    """
    brand_part = (product.brand or "").lower().strip()
    cat_part = (product.category or "").lower().strip()

    tokens = tokenize_name_for_fingerprint(product.name_normalized)
    tokens = strip_noise_tokens(tokens)
    tokens = [normalize_model_token(t) for t in tokens]
    tokens = [t for t in tokens if t]  # drop empties after normalisation
    tokens.sort()

    return f"{brand_part}|{cat_part}|{' '.join(tokens)}"


# Category-derived noise words to strip from fingerprints.
_NOISE_WORDS: set[str] = {
    "радиатор", "радиаторы",
    "котел", "котёл", "котлы",
    "бойлер", "бойлеры",
    "колонка", "колонки",
    "газовая", "газовые",
    "комплект",
    "стальной", "стальные",
    "коаксиальный", "коаксиальные",
}


def tokenize_name_for_fingerprint(name_normalized: str) -> list[str]:
    """Split a normalised product name into meaningful tokens.

    Splits on whitespace, drops single-char non-digit tokens.
    """
    raw = re.split(r"\s+", name_normalized.strip())
    return [t for t in raw if len(t) > 1 or t.isdigit()]


def strip_noise_tokens(tokens: list[str]) -> list[str]:
    """Remove category noise words from token list."""
    return [t for t in tokens if t not in _NOISE_WORDS]


def normalize_model_token(token: str) -> str:
    """Normalise a single model/numeric token for stable comparison.

    * Collapses ``1.24`` → ``124``, ``1 24`` → ``124``
    * Strips stray punctuation
    * Keeps multi-part dimension tokens like ``500x1000``
    """
    # collapse dots/dashes between digits: "1.24" → "124"
    token = re.sub(r"(\d)[.\- ](\d)", r"\1\2", token)
    # remove remaining non-word chars (keep letters, digits, cyrillic)
    token = re.sub(r"[^a-zа-яё0-9x]", "", token)
    return token


def choose_canonical_name(products: list[NormalizedProduct]) -> str:
    """Pick the most informative product name from a group.

    Selects the longest original name (more detail = better).
    """
    return max(products, key=lambda p: len(p.name)).name


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------


def _first_non_empty(values: ...) -> str | None:  # type: ignore[override]
    """Return the first truthy value from an iterable, or ``None``."""
    for v in values:
        if v:
            return v
    return None

