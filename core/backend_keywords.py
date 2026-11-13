from __future__ import annotations

import re
from typing import Any

from .product_family import supports_fact


# Amazon's backend search-term field rejects the exact byte boundary in some
# template/API paths; keep one byte of headroom for the serialized field.
MAX_BACKEND_KEYWORD_BYTES = 249

STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "your",
    "our",
    "into",
    "than",
}


def generate_backend_keywords(
    *,
    category_id: str,
    title: str,
    bullets: list[str],
    description: str,
    product_specific: dict[str, Any],
    extra_terms: list[str] | tuple[str, ...] | None = None,
    brand: str = "",
) -> str:
    """Build Amazon backend search terms using single-space-separated terms under 250 bytes."""

    frontend_text = f"{title} {' '.join(bullets)} {description}".lower()
    blocked_words = _frontend_words(frontend_text)
    brand_words = _frontend_words(str(brand or "").lower())
    candidates: list[str] = []
    from .search_terms import category_search_policy
    candidates.extend(category_search_policy(category_id).get('backend_synonyms',[]))
    mounting_terms = {
        'wall cabinet': r'\bwall[- ]?(?:mount(?:ed)?|hung)\b',
        'recessed cabinet': r'\brecess(?:ed)?\b',
        'over toilet storage': r'\bover[- ](?:the[- ])?toilet\b',
    }
    candidates.extend(term for term, pattern in mounting_terms.items() if supports_fact(product_specific, pattern))
    fact_terms=_short_fact_terms(product_specific)
    # Configured search phrases are not product evidence. Only admit their
    # substantive words when already supported by generic category/fact terms.
    supported=_frontend_words(' '.join([*candidates,*fact_terms]))
    candidates.extend(str(item) for item in (extra_terms or ()) if item
        and (_frontend_words(str(item))-STOP_WORDS)<=supported)
    candidates.extend(fact_terms)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        term = _clean_term(candidate)
        conditions = (
            (r'\bwall[- ](?:mounted[- ]|mount[- ]|mirror[- ])?cabinet\b|\bwall[- ]mount(?:ed)?\b', mounting_terms['wall cabinet']),
            (r'\brecess(?:ed)?\b', mounting_terms['recessed cabinet']),
            (r'\bover[- ](?:the[- ])?toilet\b', mounting_terms['over toilet storage']),
        )
        if any(re.search(trigger, term) and not supports_fact(product_specific, evidence) for trigger, evidence in conditions):
            continue
        if not term or term in seen:
            continue
        if _contains_asin(term) or any(word in brand_words for word in term.split()):
            continue
        words = [word for word in term.split() if word not in STOP_WORDS]
        if not words:
            continue
        # Keep useful phrases such as "faux plant" even when one word already appears
        # on the frontend, but drop exact frontend phrases to avoid wasting the field.
        if term in frontend_text:
            continue
        if len(words) == 1 and words[0] in blocked_words:
            continue
        normalized = " ".join(words)
        if normalized and normalized not in seen:
            unique.append(normalized)
            seen.add(normalized)

    result: list[str] = []
    used = 0
    for word in dict.fromkeys(word for term in unique for word in re.findall(r'[a-z0-9]+', term)):
        add = len(word.encode("utf-8")) + (1 if result else 0)
        if used + add <= MAX_BACKEND_KEYWORD_BYTES:
            result.append(word)
            used += add
    return " ".join(result)


def _frontend_words(text: str) -> set[str]:
    return {word for word in re.findall(r"\b[a-z][a-z0-9-]{2,}\b", text.lower()) if word not in STOP_WORDS}


def _clean_term(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9\s-]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _contains_asin(value: str) -> bool:
    return bool(re.search(r"\bB0[A-Z0-9]{8}\b", str(value or ""), re.I))


def _short_fact_terms(product_specific: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("material", "tree_type", "style", "shape", "mounting_type", "room_type"):
        value = product_specific.get(key) if isinstance(product_specific, dict) else None
        if not isinstance(value, str) or not value.strip() or len(value) > 60:
            continue
        for part in re.split(r"[,;/]", value):
            cleaned = _clean_term(part)
            if cleaned and len(cleaned) >= 3:
                out.append(cleaned)
    return out
