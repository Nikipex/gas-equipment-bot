"""Search 2.0 — multi-factor, category- & brand-aware product search.

Scoring factors
===============

| Factor              | Points                              |
|---------------------|-------------------------------------|
| Exact query match   | +100                                |
| All tokens matched  | +60                                 |
| Per-token hit       | +15 each                            |
| Brand match         | +50                                 |
| Category match      | +40                                 |
| Category conflict   | −20                                 |
| Partial / fuzzy     | +20 × similarity (≥ 0.30)          |

Results below ``min_score`` (default **15**) are excluded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger

from app.schemas.normalized_product import NormalizedProduct
from app.utils.matching import similarity
from app.utils.normalization import extract_brand, normalize_text


# ---------------------------------------------------------------------------
# Score weights (module-level constants — easy to tune)
# ---------------------------------------------------------------------------

_SCORE_EXACT: int = 100
_SCORE_ALL_TOKENS: int = 60
_SCORE_TOKEN: int = 15
_SCORE_BRAND: int = 50
_SCORE_CATEGORY_MATCH: int = 40
_SCORE_CATEGORY_CONFLICT: int = -20
_SCORE_PARTIAL: int = 20
_FUZZY_THRESHOLD: float = 0.30
_DEFAULT_MIN_SCORE: float = 15.0
_SCORE_MODEL_TOKEN: int = 35
_SCORE_MODEL_ALL: int = 80
_SCORE_PHRASE_SUBSTRING: int = 45
_SCORE_WEAK_MODEL_PENALTY: int = -80
_SCORE_SERIES_TOKEN: int = 70
_SCORE_SERIES_ALL: int = 120
_SCORE_SERIES_CONFLICT: int = -140
_SCORE_SERIES_MISSING: int = -120
_SCORE_ACCESSORY_CONFLICT: int = -160
_SCORE_CATEGORY_NAME_MISSING: int = -120
_MODEL_TOKEN_RE = re.compile(r"^[a-zа-я0-9-]{2,}$", re.IGNORECASE)
_GENERIC_TOKENS: set[str] = {
    "котел", "котёл", "котлы",
    "радиатор", "радиаторы",
    "бойлер", "бойлеры",
    "колонка", "колонки",
    "газовая", "газовые",
    "коаксиал", "коаксиалы", "коаксиальный", "коаксиальные",
    "комплект", "универсальный", "универсальная", "универсальные",
    "для", "на", "все", "кроме", "и", "или",
}

_SERIES_TOKENS: set[str] = {
    "4s",
    "nova",
    "four",
    "luna",
    "luna-3",
    "ace",
    "deluxe",
    "ampera",
    "sig",
}

# Brand-only + category-conflict dampening factor.
_BRAND_ONLY_CONFLICT_FACTOR: float = 0.4


# ---------------------------------------------------------------------------
# Category detection map
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "котлы": ["котел", "котлы", "котёл", "котёлы"],
    "радиаторы": ["радиатор", "радиаторы"],
    "бойлеры": ["бойлер", "бойлеры"],
    "газовые колонки": ["колонка", "колонки", "газовая колонка", "газовые колонки"],
    "коаксиалы": ["коаксиал", "коаксиалы", "коаксиальный", "коаксиальные"],
}

# Category-specific required name tokens and accessory tokens
_CATEGORY_REQUIRED_NAME_TOKENS: dict[str, list[str]] = {
    "котлы": ["котел", "котёл"],
    "радиаторы": ["радиатор"],
    "бойлеры": ["бойлер", "водонагреватель"],
    "газовые колонки": ["колонка"],
    "коаксиалы": ["коаксиал", "коаксиальный"],
}

_CATEGORY_ACCESSORY_TOKENS: dict[str, list[str]] = {
    "котлы": [
        "стабилизатор",
        "инверторный",
        "датчик",
        "манометр",
        "адаптер",
        "комплект",
        "коаксиал",
        "коаксиальный",
        "переход",
        "картридж",
        "фильтр",
    ],
}

# Pre-built reverse lookup: keyword → canonical category.
_KEYWORD_TO_CATEGORY: dict[str, str] = {
    kw: cat for cat, kws in _CATEGORY_KEYWORDS.items() for kw in kws
}

# Sort by length descending so multi-word keywords match first.
_SORTED_KEYWORDS: list[str] = sorted(
    _KEYWORD_TO_CATEGORY, key=len, reverse=True
)


# ---------------------------------------------------------------------------
# Result container (unchanged public API)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScoredResult:
    """A single search result with its relevance score."""

    product: NormalizedProduct
    score: float


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SearchService:
    """Category- & brand-aware search over normalised products.

    The **public API is unchanged** from v1 — only the internal scoring
    logic has been upgraded.

    Usage::

        svc = SearchService(products)
        results = svc.search("котел baxi 24")
    """

    def __init__(
        self,
        products: list[NormalizedProduct],
        *,
        min_score: float = _DEFAULT_MIN_SCORE,
    ) -> None:
        self._products = products
        self._min_score = min_score

    @property
    def product_count(self) -> int:
        """Number of indexed products."""
        return len(self._products)

    def load(self, products: list[NormalizedProduct]) -> None:
        """Replace the product catalogue (e.g. after a fresh import)."""
        self._products = products
        logger.info("SearchService: загружено {} товаров", len(products))

    # ------------------------------------------------------------------
    # Public search (API unchanged)
    # ------------------------------------------------------------------

    def search(self, query: str, top_n: int = 10) -> list[ScoredResult]:
        """Search products and return results sorted by score descending.

        Args:
            query: User search string (will be normalised internally).
            top_n: Maximum number of results.

        Returns:
            List of :class:`ScoredResult` with ``score >= min_score``,
            ordered from most to least relevant.
        """
        if not query or not query.strip():
            return []

        norm_query = normalize_text(query)
        tokens = tokenize_query(norm_query)
        model_tokens = extract_model_tokens(tokens)
        series_tokens = extract_series_tokens(tokens)
        model_phrase = build_model_phrase(model_tokens)
        query_brand = extract_brand(query)
        query_category = detect_query_category(norm_query)

        logger.info(
            "Search 2.0: query='{}' tokens={} model_tokens={} series_tokens={} brand={} category={}",
            query, tokens, model_tokens, series_tokens, query_brand, query_category,
        )

        scored: list[ScoredResult] = []

        for product in self._products:
            score = score_product(
                product=product,
                norm_query=norm_query,
                tokens=tokens,
                query_brand=query_brand,
                query_category=query_category,
                model_tokens=model_tokens,
                series_tokens=series_tokens,
                model_phrase=model_phrase,
            )
            if score >= self._min_score:
                scored.append(ScoredResult(product=product, score=score))

        scored.sort(key=lambda r: r.score, reverse=True)
        results = scored[:top_n]
        logger.info(
            "Search 2.0: {} подходящих (min_score={}), вернуто top {}",
            len(scored), self._min_score, len(results),
        )
        return results


# ---------------------------------------------------------------------------
# Query analysis helpers (module-level, testable independently)
# ---------------------------------------------------------------------------


def detect_query_category(query: str) -> str | None:
    """Detect a product category from the search query.

    Scans *query* (already normalised / lowered) against known category
    keywords.  Multi-word keywords are checked first.

    >>> detect_query_category("котел baxi 24")
    'котлы'
    >>> detect_query_category("радиатор 500x1000")
    'радиаторы'
    >>> detect_query_category("navien")
    """
    for kw in _SORTED_KEYWORDS:
        if kw in query:
            return _KEYWORD_TO_CATEGORY[kw]
    return None


def tokenize_query(query: str) -> list[str]:
    """Split a normalised query into meaningful tokens.

    Drops single-character tokens and pure-punctuation noise.

    >>> tokenize_query("котел baxi eco 24")
    ['котел', 'baxi', 'eco', '24']
    """
    raw = re.split(r"\s+", query.strip())
    return [t for t in raw if len(t) > 1 or t.isdigit()]


def extract_model_tokens(tokens: list[str]) -> list[str]:
    """Return query tokens that look like model / SKU / series tokens.

    Examples: eco, 4s, 24, 24f, luna-3, ace.
    Generic category words are excluded.
    """
    model_tokens: list[str] = []
    for token in tokens:
        if token in _GENERIC_TOKENS:
            continue
        if not _MODEL_TOKEN_RE.match(token):
            continue
        if token.isdigit() and len(token) == 1:
            continue
        model_tokens.append(token)
    return model_tokens


def build_model_phrase(tokens: list[str]) -> str:
    """Build a compact phrase from model tokens for substring checks."""
    return " ".join(tokens).strip()


def extract_series_tokens(tokens: list[str]) -> list[str]:
    """Return high-signal series tokens that distinguish product families."""
    return [token for token in tokens if token in _SERIES_TOKENS]


def extract_series_tokens_from_name(name_norm: str) -> list[str]:
    """Return series tokens present in the normalized product name."""
    present: list[str] = []
    for token in _SERIES_TOKENS:
        if token in name_norm:
            present.append(token)
    return present


def has_any_keyword(text: str, keywords: list[str]) -> bool:
    """Check whether any keyword is present in the normalized text."""
    return any(keyword in text for keyword in keywords)


def is_generic_category_query(tokens: list[str], query_category: str | None) -> bool:
    """True when the query is essentially only a category word like 'котел'."""
    if not query_category:
        return False
    category_keywords = set(_CATEGORY_KEYWORDS.get(query_category, []))
    meaningful_tokens = [token for token in tokens if token not in _GENERIC_TOKENS]
    return len(meaningful_tokens) == 0 and any(token in category_keywords for token in tokens)


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------


def score_product(
    *,
    product: NormalizedProduct,
    norm_query: str,
    tokens: list[str],
    query_brand: str | None,
    query_category: str | None,
    model_tokens: list[str],
    series_tokens: list[str],
    model_phrase: str,
) -> float:
    """Calculate full relevance score for *product* against the query.

    Combines exact match, token coverage, brand, category and fuzzy
    similarity into a single score.
    """
    name_norm = product.name_normalized
    score: float = 0.0
    compact_name = re.sub(r"\s+", " ", name_norm).strip()
    product_series_tokens = extract_series_tokens_from_name(name_norm)

    # --- 1. Exact match (full query is a substring of normalised name) ---
    if norm_query in name_norm:
        score += _SCORE_EXACT

    # --- 2. Token-based scoring ---
    matched_tokens: list[str] = []
    for token in tokens:
        if token in name_norm:
            matched_tokens.append(token)
            score += _SCORE_TOKEN

    all_matched = len(matched_tokens) == len(tokens) and len(tokens) > 0
    if all_matched:
        score += _SCORE_ALL_TOKENS

    # --- 2b. Model-token scoring (series / model / size tokens matter more) ---
    matched_model_tokens: list[str] = []
    for token in model_tokens:
        if token in name_norm:
            matched_model_tokens.append(token)
            score += _SCORE_MODEL_TOKEN

    all_model_matched = (
        len(model_tokens) > 0 and len(matched_model_tokens) == len(model_tokens)
    )
    if all_model_matched:
        score += _SCORE_MODEL_ALL

    if model_phrase and model_phrase in compact_name:
        score += _SCORE_PHRASE_SUBSTRING


    # --- 2c. Series-token scoring (hard product-family discriminator) ---
    matched_series_tokens: list[str] = []
    for token in series_tokens:
        if token in name_norm:
            matched_series_tokens.append(token)
            score += _SCORE_SERIES_TOKEN

    all_series_matched = (
        len(series_tokens) > 0 and len(matched_series_tokens) == len(series_tokens)
    )
    if all_series_matched:
        score += _SCORE_SERIES_ALL

    if series_tokens and not matched_series_tokens:
        score += _SCORE_SERIES_MISSING


    # --- 3. Brand match ---
    brand_match = (
        query_brand is not None
        and product.brand is not None
        and product.brand.lower() == query_brand.lower()
    )
    if brand_match:
        score += _SCORE_BRAND

    # --- 4. Category match / conflict ---
    category_match = False
    category_conflict = False

    if query_category and product.category:
        prod_cat = product.category.lower().strip()
        if prod_cat == query_category:
            category_match = True
            score += _SCORE_CATEGORY_MATCH
        else:
            category_conflict = True
            score += _SCORE_CATEGORY_CONFLICT

    # --- 4a. Category-specific anti-noise rules ---
    required_name_tokens = _CATEGORY_REQUIRED_NAME_TOKENS.get(query_category or "", [])
    accessory_tokens = _CATEGORY_ACCESSORY_TOKENS.get(query_category or "", [])

    has_required_name_token = has_any_keyword(name_norm, required_name_tokens)
    has_accessory_token = has_any_keyword(name_norm, accessory_tokens)
    generic_category_query = is_generic_category_query(tokens, query_category)

    # Example: query 'котел' should not rank stabilizers / adapters / sensors
    # above real boilers, even if their imported category is 'котлы'.
    if query_category and required_name_tokens and not has_required_name_token:
        score += _SCORE_CATEGORY_NAME_MISSING

    if query_category and accessory_tokens and has_accessory_token and not has_required_name_token:
        score += _SCORE_ACCESSORY_CONFLICT

    if generic_category_query and required_name_tokens and not has_required_name_token:
        score += _SCORE_ACCESSORY_CONFLICT

    # --- 4b. Penalise weak model overlap for model-heavy queries ---
    if len(model_tokens) >= 2 and len(matched_model_tokens) <= 1:
        score += _SCORE_WEAK_MODEL_PENALTY

    # Hard extra penalty when query has a specific series token but the product
    # belongs to another known series family.
    conflicting_series_tokens = [
        token for token in product_series_tokens if token not in series_tokens
    ]
    if series_tokens and not matched_series_tokens and conflicting_series_tokens:
        score += _SCORE_SERIES_CONFLICT

    # --- 5. Partial / fuzzy similarity ---
    sim = similarity(norm_query, name_norm)
    if sim >= _FUZZY_THRESHOLD:
        fuzzy_bonus = _SCORE_PARTIAL * sim
        if len(model_tokens) >= 2 and len(matched_model_tokens) <= 1:
            fuzzy_bonus *= 0.35
        if series_tokens and not matched_series_tokens:
            fuzzy_bonus *= 0.20
        score += fuzzy_bonus

    # --- 6. Brand-only + category-conflict dampening ---
    # If the *only* substantial signal is brand and the category clearly
    # conflicts — dampen the score to push irrelevant results down.
    if brand_match and category_conflict and not all_matched:
        score *= _BRAND_ONLY_CONFLICT_FACTOR

    logger.debug(
        "  → {} | score={:.1f} tokens_hit={}/{} model_hit={}/{} series_hit={}/{} brand={} cat={}/{} req_name={} accessory={} sim={:.2f}",
        product.name,
        score,
        len(matched_tokens),
        len(tokens),
        len(matched_model_tokens),
        len(model_tokens),
        len(matched_series_tokens),
        len(series_tokens),
        "✓" if brand_match else "✗",
        query_category or "—",
        product.category or "—",
        "✓" if has_required_name_token else "✗",
        "✓" if has_accessory_token else "✗",
        sim,
    )

    return score
