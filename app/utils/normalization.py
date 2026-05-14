"""Text normalization helpers for product names, articles, etc."""

from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str) -> str:
    """Lowercase, strip, collapse whitespace and remove accents."""
    text = unicodedata.normalize("NFKD", text)
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_article(article: str) -> str:
    """Remove non-alphanumeric chars and uppercase for uniform comparison."""
    return re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]", "", article).upper()


# ---------------------------------------------------------------------------
# Brand extraction
# ---------------------------------------------------------------------------

# Canonical brand name → known variations (lowercase).
BRAND_SYNONYMS: dict[str, list[str]] = {
    "BAXI": ["baxi", "бакси"],
    "Navien": ["navien", "навьен", "навиен"],
    "Ariston": ["ariston", "аристон"],
    "Vaillant": ["vaillant", "вайлант", "вайллант"],
    "Protherm": ["protherm", "протерм"],
    "Buderus": ["buderus", "будерус"],
    "Bosch": ["bosch", "бош"],
    "Viessmann": ["viessmann", "висман", "виссманн"],
    "Ferroli": ["ferroli", "ферроли"],
    "Electrolux": ["electrolux", "электролюкс"],
    "Zanussi": ["zanussi", "занусси"],
    "Kermi": ["kermi", "керми"],
    "Purmo": ["purmo", "пурмо"],
    "Rifar": ["rifar", "рифар"],
    "VilTerm": ["vilterm", "вилтерм"],
    "Lidea": ["lidea", "лидея"],
}

# Pre-built lookup: lowercase variant → canonical brand.
_BRAND_LOOKUP: dict[str, str] = {
    variant: canonical
    for canonical, variants in BRAND_SYNONYMS.items()
    for variant in variants
}


def extract_brand(text: str) -> str | None:
    """Try to find a known brand inside *text*.

    Checks every word in the lowered text against the brand synonyms
    dictionary.  Returns the canonical brand name or ``None``.

    >>> extract_brand("Котел BAXI Eco Life 24F")
    'BAXI'
    >>> extract_brand("какой-то товар без бренда")
    """
    lowered = text.lower()
    for variant, canonical in _BRAND_LOOKUP.items():
        if variant in lowered:
            return canonical
    return None


def clean_product_name(text: str, brand: str | None = None) -> str:
    """Normalise a product name for indexing / comparison.

    Steps:
    1. Apply :func:`normalize_text` (lowercase, collapse whitespace, strip).
    2. Optionally remove the *brand* substring to get a "pure" product name.
    3. Strip common noise characters (``«»"'``).

    >>> clean_product_name("  Котел BAXI Eco Life  1.24 F  ", brand="BAXI")
    'котел eco life 1.24 f'
    """
    cleaned = normalize_text(text)
    if brand:
        cleaned = cleaned.replace(brand.lower(), "").strip()
    # remove noise punctuation
    cleaned = re.sub(r"[«»\"']", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned
