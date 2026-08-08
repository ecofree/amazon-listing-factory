from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from .title_quality import listing_title_quality_issues


class CopyWriterError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class CopyWriterConfig:
    enabled: bool
    api_key: str
    base_url: str
    model: str
    timeout: int
    retry_attempts: int = 2
    retry_base_seconds: float = 0.5
    max_tokens: int = 5000
    json_mode: bool = True
    temperature: float = 0.15


COPY_CACHE_MAX_ENTRIES = 256
_LOGGER = logging.getLogger(__name__)
COPY_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
COPY_WRITER_PROMPT_VERSION = "copy-writer-v24-bounded-highlight-selection"
_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
TITLE_PREFERRED_CHARS = 68
TITLE_MAX_CHARS = 75
ITEM_HIGHLIGHT_MIN_COUNT = 2
ITEM_HIGHLIGHT_MAX_COUNT = 5
ITEM_HIGHLIGHT_MAX_WORDS = 6
ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS = 120
ITEM_HIGHLIGHT_SEPARATOR = ", "
BULLET_PREFERRED_CHARS = BULLET_MODEL_MAX_CHARS = 120
BULLET_AUDIT_MAX_CHARS = 150
_BULLET_LENGTH_ISSUE_RE = re.compile(r"bullet\s+(\d+)\s+has\s+\d+", re.I)
DESCRIPTION_MAX_CHARS = 2000
_TITLE_DIMENSION_RE = re.compile(
    r"(?:\b(?:california\s+king|twin(?:\s+xl)?|full(?!-)|queen|king)\b|"
    r"\b\d+(?:\.\d+)?(?:\s*x\s*\d+(?:\.\d+)?){0,2}"
    r"(?:\s*(?:in(?:ch(?:es)?)?\.?|ft\.?|feet|foot|cm|mm)\b|\s*\"))",
    re.I,
)

AMAZON_FORBIDDEN_CLAIMS = (
    "- Do NOT use subjective superlatives: 'best', 'top', 'premium quality', 'perfect', 'ideal', 'superior'.\n"
    "- Do NOT use calls to action or promotional claims: 'buy now', 'order now', 'limited time', 'sale', 'discount', or 'free shipping'.\n"
    "- Do NOT use marketplace badges or rank claims: 'Amazon's Choice', 'Best Seller', or 'As seen on'.\n"
    "- Do NOT use medical, regulatory, or satisfaction claims such as 'FDA approved', 'clinically proven', or '100% satisfaction'.\n"
    "- Do NOT make guarantee or warranty claims unless explicitly stated in product facts.\n"
    "- Do NOT claim 'waterproof' unless an IPX rating or waterproof fact is supplied.\n"
    "- Do NOT claim 'safety certified', 'child-safe', or 'non-toxic' without explicit certification.\n"
    "- Do NOT reference competitor products, pricing, sales rank, reviews, or marketplace rank."
)

HARD_SUBJECTIVE_FORBIDDEN_PATTERNS = (
    re.compile(r"\bbest\b", re.I),
    re.compile(r"\btop(?:[- ]?(?:rated|quality|choice|seller|pick|tier)|\s+of\s+the\s+line)\b", re.I),
    re.compile(r"\bpremium\s+quality\b", re.I),
    re.compile(r"\bsuperior\b", re.I),
)

PROMOTIONAL_FORBIDDEN_PATTERNS = (
    re.compile(r"\bbuy\s+now\b", re.I),
    re.compile(r"\border\s+now\b", re.I),
    re.compile(r"\blimited\s+time\b", re.I),
    re.compile(r"\bsale\b", re.I),
    re.compile(r"\bdiscount\b", re.I),
    re.compile(r"\bfree\s+shipping\b", re.I),
    re.compile(r"\bfda\s+approved\b", re.I),
    re.compile(r"\bclinically\s+proven\b", re.I),
    re.compile(r"\b100%\s+satisfaction\b", re.I),
    re.compile(r"\bamazon'?s\s+choice\b", re.I),
    re.compile(r"\bbest\s+seller\b", re.I),
    re.compile(r"\bas\s+seen\s+on\b", re.I),
)

ENVIRONMENTAL_FORBIDDEN_PATTERNS = (
    re.compile(r"\beco[- ]?friendly\b", re.I),
    re.compile(r"\bbiodegradable\b", re.I),
    re.compile(r"\borganic\b", re.I),
    re.compile(r"\bsustainable\b", re.I),
    re.compile(r"\brecyclable\b", re.I),
    re.compile(r"\bcarbon[- ]?neutral\b", re.I),
)

EXTERNAL_REFERENCE_PATTERNS = (
    re.compile(r"https?://", re.I),
    re.compile(r"\bwww\.", re.I),
    re.compile(r"\bvisit\s+(?:our|us|my)\b", re.I),
    re.compile(r"\bemail\s+us\b", re.I),
)

SPECIAL_TITLE_CHARS = re.compile(r"[~!*$?{}#<>@]")
ALLOWED_TITLE_ACRONYMS = {"LED", "USB", "USB-C", "MDF", "PVC", "PE", "PEVA", "ABS", "R2"}

COPY_SENSITIVE_PARAM_FRAGMENTS = (
    "asin",
    "brand",
    "manufacturer",
    "merchant",
    "rating",
    "rank",
    "review",
    "seller",
    "sku",
    "store",
)


def load_copy_writer_config(env: dict[str, str] | None = None) -> CopyWriterConfig:
    values = {**(env or {}), **os.environ}
    enabled_raw = values.get("AMAZON_FACTORY_COPY_POLISH")
    if enabled_raw is None:
        enabled_raw = values.get("COPY_AI_ENABLED", "true")
    enabled = str(enabled_raw).strip().lower() not in {"0", "false", "no", "off"}
    key_env = values.get("COPY_AI_KEY_ENV") or "DEEPSEEK_API_KEY"
    api_key = values.get(key_env, "") or values.get("DEEPSEEK_API_KEY", "")
    base_url = values.get("COPY_AI_BASE_URL") or values.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
    model = values.get("COPY_AI_MODEL") or values.get("DEEPSEEK_MODEL") or "deepseek-chat"
    timeout_raw = values.get("AMAZON_FACTORY_COPY_TIMEOUT") or values.get("COPY_AI_TIMEOUT") or "30"
    try:
        timeout = max(5, int(float(timeout_raw)))
    except (TypeError, ValueError):
        timeout = 30
    retry_attempts = _coerce_int(
        values.get("AMAZON_FACTORY_COPY_RETRY_ATTEMPTS") or values.get("COPY_AI_RETRY_ATTEMPTS"),
        default=2,
        minimum=1,
        maximum=2,
    )
    retry_base_seconds = _coerce_float(
        values.get("AMAZON_FACTORY_COPY_RETRY_BASE_SECONDS") or values.get("COPY_AI_RETRY_BASE_SECONDS"),
        default=0.5,
        minimum=0.0,
        maximum=30.0,
    )
    max_tokens = _coerce_int(
        values.get("AMAZON_FACTORY_COPY_MAX_TOKENS") or values.get("COPY_AI_MAX_TOKENS"),
        default=5000,
        minimum=1200,
        maximum=8000,
    )
    temperature = _coerce_float(
        values.get("AMAZON_FACTORY_COPY_TEMPERATURE") or values.get("COPY_AI_TEMPERATURE"),
        default=0.15,
        minimum=0.0,
        maximum=1.0,
    )
    json_mode = str(values.get("COPY_AI_JSON_MODE", "1")).strip().lower() not in {"0", "false", "no", "off"}
    return CopyWriterConfig(
        enabled=enabled,
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model=model,
        timeout=timeout,
        retry_attempts=retry_attempts,
        retry_base_seconds=retry_base_seconds,
        max_tokens=max_tokens,
        json_mode=json_mode,
        temperature=temperature,
    )


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(float(value))))
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return default


def configured(env: dict[str, str] | None = None) -> bool:
    config = load_copy_writer_config(env)
    return config.enabled and bool(config.api_key)


def rewrite_listing_copy(
    *,
    env: dict[str, str] | None,
    category: str,
    brand: str,
    row_type: str,
    source_title: str,
    source_bullets: list[str],
    source_description: str,
    product_specific: dict[str, Any],
) -> dict[str, Any]:
    config = load_copy_writer_config(env)
    if not config.enabled:
        raise CopyWriterError("Copy AI is disabled")
    if not config.api_key:
        raise CopyWriterError("Copy AI API key is not configured")
    product_specific = _copy_safe_product_specific(product_specific, brand=brand, source_title=source_title)
    market_context = _copy_market_context(
        env=env,
        category=category,
        source_title=source_title,
        product_specific=product_specific,
    )
    forbidden_reference_brands = _reference_brand_candidates(
        target_brand=brand,
        source_title=source_title,
        source_bullets=source_bullets,
        source_description=source_description,
        product_specific=product_specific,
        market_context=market_context,
    )
    cache_key = _cache_key(
        config,
        category,
        brand,
        row_type,
        source_title,
        source_bullets,
        source_description,
        product_specific,
        market_context,
        forbidden_reference_brands,
    )
    if cache_key in _CACHE:
        cached = _CACHE.pop(cache_key)
        _CACHE[cache_key] = cached
        return cached
    result = _rewrite_listing_copy_with_openai(
        config=config,
        category=category,
        brand=brand,
        row_type=row_type,
        source_title=source_title,
        source_bullets=source_bullets,
        source_description=source_description,
        product_specific=product_specific,
        market_context=market_context,
        forbidden_reference_brands=forbidden_reference_brands,
    )
    result["_model"] = config.model
    result["_request_fingerprint"] = cache_key
    _store_cache(cache_key, result)
    return result


def listing_copy_request_fingerprint(
    *,
    env: dict[str, str] | None,
    category: str,
    brand: str,
    row_type: str,
    source_title: str,
    source_bullets: list[str],
    source_description: str,
    product_specific: dict[str, Any],
) -> str:
    config = load_copy_writer_config(env)
    safe_specific = _copy_safe_product_specific(
        product_specific, brand=brand, source_title=source_title
    )
    market_context = _copy_market_context(
        env=env,
        category=category,
        source_title=source_title,
        product_specific=safe_specific,
    )
    forbidden = _reference_brand_candidates(
        target_brand=brand,
        source_title=source_title,
        source_bullets=source_bullets,
        source_description=source_description,
        product_specific=safe_specific,
        market_context=market_context,
    )
    return _cache_key(
        config,
        category,
        brand,
        row_type,
        source_title,
        source_bullets,
        source_description,
        safe_specific,
        market_context,
        forbidden,
    )


def _copy_safe_product_specific(product_specific: dict[str, Any], *, brand: str, source_title: str) -> dict[str, Any]:
    if not isinstance(product_specific, dict):
        return {}
    candidates = _copy_brand_candidates(
        explicit_brand=brand,
        source_title=source_title,
        source_bullets=[],
        source_description="",
        product_specific=product_specific,
    )
    safe = _copy_safe_product_specific_value(product_specific, candidates)
    return safe if isinstance(safe, dict) else {}


def _copy_brand_candidates(
    *,
    explicit_brand: str,
    source_title: str,
    source_bullets: list[str] | None = None,
    source_description: str = "",
    product_specific: dict[str, Any],
) -> tuple[str, ...]:
    candidates: list[str] = []
    for value in (explicit_brand, _leading_nonbrand_prefix(str(source_title or ""))):
        cleaned = _brand_candidate(value)
        if cleaned and cleaned.lower() not in {item.lower() for item in candidates}:
            candidates.append(cleaned)
    for value in [*(source_bullets or []), source_description]:
        cleaned = _brand_candidate(_leading_nonbrand_prefix(str(value or "")))
        if cleaned and _loose_text_brand_candidate(cleaned) and cleaned.lower() not in {item.lower() for item in candidates}:
            candidates.append(cleaned)
    _collect_brand_candidates(product_specific, candidates)
    return tuple(candidates)


def _loose_text_brand_candidate(value: str) -> bool:
    text = str(value or "").strip()
    normalized = re.sub(r"[^a-z0-9]+", "", text.lower())
    if not normalized:
        return False
    if any(fragment in normalized for fragment in ("brand", "maker", "seller", "store", "shop", "merchant")):
        return True
    letters = re.sub(r"[^A-Za-z]+", "", text)
    return bool(letters) and letters == letters.upper() and len(letters) >= 3


def _collect_brand_candidates(value: Any, candidates: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "", str(key).lower())
            if any(fragment in normalized for fragment in ("brand", "manufacturer", "seller", "store", "merchant")):
                cleaned = _brand_candidate(nested)
                if cleaned and cleaned.lower() not in {item.lower() for item in candidates}:
                    candidates.append(cleaned)
            elif isinstance(nested, (dict, list)):
                _collect_brand_candidates(nested, candidates)
    elif isinstance(value, list):
        for item in value[:30]:
            _collect_brand_candidates(item, candidates)


def _brand_candidate(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:-")
    if not text or len(text) > 60:
        return ""
    if re.search(r"\b(?:cabinet|tree|bed|chair|storage|shelf|shelves|door|frame|bathroom|medicine|artificial)\b", text, re.I):
        return ""
    return text


def _copy_safe_product_specific_value(value: Any, candidates: tuple[str, ...], *, depth: int = 0) -> Any:
    if depth > 4:
        return None
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, nested in value.items():
            key_text = str(key or "")
            normalized = re.sub(r"[^a-z0-9]+", "", key_text.lower())
            if any(fragment in normalized for fragment in COPY_SENSITIVE_PARAM_FRAGMENTS):
                continue
            cleaned = _copy_safe_product_specific_value(nested, candidates, depth=depth + 1)
            if cleaned not in (None, "", [], {}):
                out[key_text] = cleaned
            if len(out) >= 80:
                break
        return out
    if isinstance(value, list):
        out = []
        for item in value[:20]:
            cleaned = _copy_safe_product_specific_value(item, candidates, depth=depth + 1)
            if cleaned not in (None, "", [], {}):
                out.append(cleaned)
        return out
    if isinstance(value, (int, float, bool)):
        return value
    return _clean_copy_param_text(_redact_copy_terms(value, candidates), 500)


def _redact_copy_terms(text: Any, candidates: tuple[str, ...]) -> str:
    out = str(text or "")
    for candidate in sorted({item for item in candidates if item}, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(candidate)}\b", "", out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip(" ,;:-")


def _clean_copy_param_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.translate(str.maketrans({"[": "", "]": "", "\u3010": "", "\u3011": ""}))
    text = re.sub(r"^(?:description|features?|about this item)\s*:\s*", "", text, flags=re.I)
    return _limit_text(re.sub(r"\s+", " ", text).strip(" ,;:"), limit)


def _rewrite_listing_copy_with_openai(
    *,
    config: CopyWriterConfig,
    category: str,
    brand: str,
    row_type: str,
    source_title: str,
    source_bullets: list[str],
    source_description: str,
    product_specific: dict[str, Any],
    market_context: dict[str, Any] | None = None,
    forbidden_reference_brands: tuple[str, ...] = (),
) -> dict[str, Any]:
    row_scope = (
        "Parent row: use only family-common known_product_facts; omit child color, size, style, and other variation values."
        if str(row_type).strip().lower() == "parent"
        else "Child row: use only this child's supplied facts and variation values."
    )
    source_for_model = {
        "title": _redact_reference_brands(source_title, forbidden_reference_brands),
        "item_highlights": [_redact_reference_brands(item, forbidden_reference_brands) for item in source_bullets],
        "description": _redact_reference_brands(source_description, forbidden_reference_brands),
    }
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You write compliant Amazon US listing copy that is ready for Amazon upload. Return JSON only. "
                    "Use only facts supplied by the user. Do not invent certifications, materials, sizes, capacities, included accessories, or safety claims. "
                    "Apify source item_highlights is optional and may be absent or combined with commas/semicolons. Use it as evidence when present, but do not copy the source title or item highlights verbatim. If the source title is missing or overlong, write a new brandless title from the supplied product facts; never truncate the source mechanically. If source item_highlights are absent, synthesize short highlights from supplied product facts without blocking. Use plain ASCII punctuation. Do not use brackets, numbering, markdown, or emoji. "
                    "Item Weight or product weight means the product's own mass. It never authorizes a weight capacity, load capacity, supports-up-to, or holds-up-to claim; only an explicit supplied load_capacity fact does. "
                    "Output must be in English. Return exactly four keys: title, item_highlights, bullets, description. Put the final JSON object in assistant message.content; do not leave content empty or put the answer only in reasoning_content.\n"
                    "Keyword and format rules:\n"
                    "- Do not put any brand name in the title; Amazon receives brand in its separate brand field.\n"
                    "- Keep source-supported product structure nouns exact across the family. Do not replace stairs with ladder, drawers with shelves, sliding door with hinged door, or any other visible structure with a convenient synonym. Parent copy may use only structure terms supported by every child in its supplied common facts.\n"
                    f"- Title hard max: {TITLE_MAX_CHARS} characters.\n"
                    "- Use operator-style title thinking: broad high-traffic terms are category anchors, not enough by themselves. Add source-supported qualifiers that narrow competition and match buyer intent, such as tall, narrow, slim, floor, freestanding, height, size, door/shelf count, pack count, no box spring needed, or maintenance-free.\n"
                    "- Title priority is: confirmed size when used, exact product entity, competition-narrowing qualifier, purchase-decision parameter, then precise use scenario. Cut generic scene words before hard facts.\n"
                    "- If the title includes a confirmed size or product dimension, put that size at the very beginning. Never move a size to the end. Example: '67 Inch Tall Bathroom Cabinet for Narrow Spaces'.\n"
                    "- Write one natural title phrase. Do not use vertical bars or other marketing separators.\n"
                    "- Move low-title-signal accessory or compliance details to bullets/description unless market references clearly support them in titles. This includes anti-tipping devices, wall anchors, rubber feet, included hardware, planter color, pot color, decorative trunk material, and assembly instructions.\n"
                    "- Title must not repeat any content word more than twice. Prepositions, articles, and conjunctions are exceptions. Count words inside hyphenated compounds too; if a size phrase already uses Full twice, write 'Guardrails' instead of 'Full-Length Guardrails'.\n"
                    "- Do not include color in the title for normal variation families; Amazon variation fields carry color.\n"
                    "- Never output the requested brand, reference-ASIN, competitor, source, or top-clicked brand in the title.\n"
                    "- Use local search-term references only to choose structure and priority. Never copy competitor titles or competitor brands.\n"
                    "- Each bullet must start with a concise Title Case feature label followed by a colon, for example 'Sturdy Frame: ...'.\n"
                    f"- Each bullet must focus on one unique selling point and target at most {BULLET_MODEL_MAX_CHARS} characters. Results over {BULLET_AUDIT_MAX_CHARS} characters are rejected.\n"
                    f"- Description target: 700-1200 characters; hard max: {DESCRIPTION_MAX_CHARS}; write readable natural copy that covers important supplied parameters.\n"
                    "- Explain what the product is, where it is used, and the supplied dimensions, material, structure, included components, capacity, or compatibility that matter to a buyer. Do not force a section heading or repeat the same fact to reach the target length.\n"
                    "Positive retail writing guidance:\n"
                    "- Write like a senior Amazon US listing specialist: concrete, buyer-aware, and specific without hype.\n"
                    "- Bullet hierarchy: 1 primary buyer benefit, 2 key differentiator, 3 practical dimensions/capacity/fit, 4 durability or trust signal, 5 included parts/setup/maintenance.\n"
                    "- Start bullets with varied benefit-led labels; do not reuse the same opener pattern.\n"
                    "- Prefer measurable facts and buyer situations over generic phrases. '66 lb per shelf' beats 'sturdy construction'.\n"
                    "- Avoid AI filler phrases such as suitable for, straightforward, designed to, premium, best, perfect, and versatile placement unless the phrase is unavoidable in a supplied fact.\n"
                    "- Keep the description concrete and natural; organization is flexible as long as supplied facts remain accurate.\n"
                    f"Amazon claim restrictions:\n{AMAZON_FORBIDDEN_CLAIMS}"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "Rewrite the brandless listing title, synthesize multiple source-supported Item Highlights, write five bullets, and write the product description.",
                        "constraints": {
                            "title_preferred_chars": TITLE_PREFERRED_CHARS,
                            "title_max_chars": TITLE_MAX_CHARS,
                            "bullet_count": 5,
                            "bullet_preferred_chars": BULLET_PREFERRED_CHARS,
                            "bullet_max_chars": BULLET_MODEL_MAX_CHARS,
                            "description_target_chars": "700-1200",
                            "description_max_chars": DESCRIPTION_MAX_CHARS,
                            "style": "concise, specific, natural retail copy; obey every hard length limit; cover supplied buyer-relevant facts without inventing or mechanically repeating them",
                            "bullet_hierarchy": [
                                "Bullet 1: primary buyer benefit or pain point solved",
                                "Bullet 2: key differentiator versus generic alternatives",
                                "Bullet 3: practical spec, dimension, compatibility, capacity, or fit",
                                "Bullet 4: durability, material, safety hardware, or trust signal using supplied facts only",
                                "Bullet 5: included parts, setup, maintenance, or package contents",
                            ],
                            "description_strategy": "Explain the product, buyer use, and concrete supplied details in a natural order; no required section heading.",
                            "avoid_ai_phrases": ["suitable for", "straightforward", "designed to", "premium", "best", "perfect", "versatile placement"],
                            "title_priority": [
                                "confirmed product size or dimension when included in the title",
                                "exact product entity",
                                "competition-narrowing qualifier that is supported by source facts",
                                "hard purchase-decision parameter such as size, height, configuration, door/drawer/shelf count, no box spring needed, or maintenance-free",
                                "precise use scenario",
                                "source-supported blocker term only when market references show it is common in titles",
                            ],
                            "title_operator_strategy": [
                                "Do not stop at a broad high-volume head term when a supported qualifier can narrow competition.",
                                "Use high-volume search terms as anchors, then add one or two factual limiting words that reduce competition and clarify buyer intent.",
                                "Prefer qualifiers that shoppers compare before buying: tall/narrow/slim/floor/freestanding, exact height or size, pack count, door/shelf/drawer count, mattress support, maintenance-free, or indoor/outdoor use.",
                                "Do not repeat any content word more than twice in the title; count words inside hyphenated compounds such as Full-Length.",
                                "When a required size phrase already spends the word budget, prefer a synonym or shorter feature phrase instead of repeating the same word again.",
                                "Avoid low-signal decorative details in the title when they are not search terms or Top clicked title patterns; move them to bullets or description.",
                                "Avoid putting safety hardware, anchors, rubber feet, assembly hardware, planter color, pot color, or decorative trunk material in the title unless the market references make that phrase clearly title-relevant.",
                                "Write one natural phrase without vertical bars or marketing separators.",
                            ],
                            "title_word_repetition_limit": {
                                "max_per_content_word": 2,
                                "exceptions": "prepositions, articles, and conjunctions",
                                "hyphenated_words_count": True,
                            },
                            "forbidden": [
                                "square brackets",
                                "Chinese brackets",
                                "numbered bullets",
                                "vertical bars or marketing separators in the title",
                                "same content word repeated more than twice in the title",
                                "Description:",
                                "Features:",
                                "copying source bullet sentences",
                                "unsupported claims",
                                "subjective superlatives",
                                "unsupported warranty, guarantee, waterproof, safety, certification, or weight-capacity claims",
                            ],
                            "amazon_forbidden_claims": AMAZON_FORBIDDEN_CLAIMS,
                            "forbidden_reference_brands": list(forbidden_reference_brands),
                            "row_scope": row_scope,
                        },
                        "category": category,
                        "brand": brand,
                        "row_type": row_type,
                        "source": {
                            **source_for_model,
                        },
                        "known_product_facts": product_specific,
                        "concrete_facts_to_cover": _concrete_prompt_facts(product_specific),
                        "fact_semantics": {
                            "item_weight": "product's own mass only; never express as load or weight capacity",
                            "load_capacity": "the only structured fact that authorizes supports-up-to or holds-up-to copy",
                        },
                        "market_search_reference": _market_context_for_model(market_context),
                            "output_schema": {
                             "title": f"brandless natural phrase preferably <={TITLE_PREFERRED_CHARS} chars, hard max <={TITLE_MAX_CHARS} chars; if a confirmed size is used it must be the first phrase",
                             "item_highlights": f"array of {ITEM_HIGHLIGHT_MIN_COUNT}-{ITEM_HIGHLIGHT_MAX_COUNT} distinct source-supported phrases, each 2-{ITEM_HIGHLIGHT_MAX_WORDS} words; their comma-and-space joined text must be under {ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS} characters",
                             "bullets": [
                                f"exactly five strings, target <={BULLET_MODEL_MAX_CHARS} chars, audit hard max <={BULLET_AUDIT_MAX_CHARS} chars",
                                "each bullet starts with CAPITALIZED FEATURE LABEL: followed by description",
                                "each bullet focuses on a different selling point",
                            ],
                             "description": f"English string targeting 700-1200 chars, hard max {DESCRIPTION_MAX_CHARS}, covering supplied buyer-relevant facts naturally",
                             "evidence": "not required in the response; the caller records source provenance",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": config.temperature,
        "max_tokens": _copy_max_tokens(config),
    }
    if "deepseek.com" in config.base_url.lower():
        payload["thinking"] = {"type": "disabled"}
    if config.json_mode:
        payload["response_format"] = {"type": "json_object"}
    result: dict[str, Any] | None = None
    parse_attempts = 3
    for attempt in range(1, parse_attempts + 1):
        body = _post_chat_completion(config, payload)
        try:
            result = _parse_copy_response(
                body,
                category=category,
                row_type=row_type,
                product_specific=product_specific,
                brand=brand,
                market_context=market_context,
                forbidden_reference_brands=forbidden_reference_brands,
            )
            _validate_no_reference_brands(result, forbidden_reference_brands)
            break
        except CopyWriterError as exc:
            error_text = str(exc)
            if _is_non_json_copy_error(error_text):
                if attempt >= parse_attempts:
                    raise CopyWriterError(str(exc), retryable=True) from exc
                payload = _copy_json_repair_payload(payload, error_text, invalid_body=body)
                continue
            if _only_title_validation_errors(error_text):
                result = _repair_title_only_with_ai(
                    config=config,
                    invalid_body=body,
                    validation_error=error_text,
                    category=category,
                    product_specific=product_specific,
                    brand=brand,
                    market_context=market_context,
                    forbidden_reference_brands=forbidden_reference_brands,
                )
                break
            if _only_item_highlight_validation_errors(error_text):
                result = _repair_item_highlights_only_with_ai(
                    config=config,
                    invalid_body=body,
                    source_item_highlights=list(_copy_payload_user(payload).get("source", {}).get("item_highlights") or []),
                    category=category,
                    product_specific=product_specific,
                    brand=brand,
                    market_context=market_context,
                    forbidden_reference_brands=forbidden_reference_brands,
                )
                break
            if _only_bullet_length_errors(error_text):
                result = _repair_long_bullets_with_ai(
                    config=config,
                    invalid_body=body,
                    validation_error=error_text,
                    category=category,
                    product_specific=product_specific,
                    brand=brand,
                    market_context=market_context,
                    forbidden_reference_brands=forbidden_reference_brands,
                )
                break
            if attempt >= parse_attempts:
                raise CopyWriterError(str(exc), retryable=True) from exc
            payload = _copy_validation_repair_payload(payload, error_text, invalid_body=body)
    if result is None:
        raise CopyWriterError("Copy AI response could not be parsed", retryable=True)
    result["_provider"] = config.base_url
    if market_context:
        result["_market_search_reference"] = {
            "source": market_context.get("source", ""),
            "search_categories": market_context.get("search_categories", []),
            "reference_count": len(market_context.get("references") or []),
        }
    return result


def _is_non_json_copy_error(error_text: str) -> bool:
    text = str(error_text or "").lower()
    markers = (
        "not openai-compatible json",
        "did not contain a json object",
        "response is not strict json",
        "response json is not an object",
        "not a json object",
    )
    return any(marker in text for marker in markers)


def _copy_json_repair_payload(
    payload: dict[str, Any], error_text: str, *, invalid_body: str,
) -> dict[str, Any]:
    repaired = _copy_payload_clone(payload)
    user_payload = _copy_payload_user(repaired)
    user_payload["task"] = "Return final Amazon listing copy as strict JSON only."
    user_payload["json_repair_reason"] = _response_snippet(error_text, limit=300)
    user_payload["invalid_response_to_repair"] = _copy_invalid_response_text(invalid_body)
    user_payload["output_contract"] = {
        "required_keys": ["title", "item_highlights", "bullets", "description"],
        "title": "string only",
        "item_highlights": f"array of {ITEM_HIGHLIGHT_MIN_COUNT}-{ITEM_HIGHLIGHT_MAX_COUNT} strings whose comma-separated total is under {ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS} characters",
        "bullets": "array of exactly five strings",
        "description": "string only",
        "forbidden_output": [
            "reasoning",
            "analysis",
            "markdown",
            "headings",
            "comments",
            "prose before JSON",
            "prose after JSON",
            "code fences",
        ],
    }
    repaired["messages"] = [
        {
            "role": "system",
            "content": (
                "You are a strict JSON-only Amazon listing copy generator. "
                "Do not include reasoning, analysis, headings, markdown, comments, or prose outside JSON. "
                "Return exactly one valid JSON object in message.content. "
                "The JSON object must have title, item_highlights, bullets, and description keys only. "
                "Use only supplied source facts and keep every brand name out of the title."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]
    repaired["temperature"] = 0
    if "response_format" in payload:
        repaired["response_format"] = payload["response_format"]
    return repaired


def _copy_validation_repair_payload(
    payload: dict[str, Any], error_text: str, *, invalid_body: str,
) -> dict[str, Any]:
    repaired = _copy_payload_clone(payload)
    user_payload = _copy_payload_user(repaired)
    user_payload["task"] = "Regenerate the final listing copy and correct the validation error."
    user_payload["validation_error"] = _response_snippet(error_text, limit=1000)
    user_payload["invalid_copy_to_repair"] = _copy_invalid_response_text(invalid_body)
    if "title exceeds" in error_text.lower():
        user_payload["title_repair_contract"] = {
            "target": f"{TITLE_PREFERRED_CHARS} characters or fewer",
            "hard_limit": f"{TITLE_MAX_CHARS} characters maximum; count spaces and punctuation",
            "shape": "confirmed size first when used + compact product noun + strongest buyer qualifier",
            "remove_first": [
                "decorative adjectives",
                "secondary hardware or included accessory details",
                "repeated category words",
                "extra room/use cases",
                "vertical bars and marketing separators",
            ],
            "forbidden": "Do not preserve a long title structure and merely swap synonyms.",
        }
    if "bullet exceeds" in error_text.lower() or "bullets" in error_text.lower():
        user_payload["bullet_repair_contract"] = {
            "hard_limit": f"{BULLET_MODEL_MAX_CHARS} characters target, never over {BULLET_AUDIT_MAX_CHARS}; count spaces and punctuation",
            "shape": "Short Title Case Label: one concrete buyer benefit",
            "remove_first": [
                "secondary examples",
                "extra clauses after and/while/with",
                "repeated room or use cases",
                "generic adjectives",
                "facts already covered by another bullet",
            ],
            "forbidden": "Do not return any bullet over 120 characters.",
        }
    if "item highlight" in error_text.lower() or "item_highlights" in error_text.lower():
        user_payload["item_highlights_repair_contract"] = {
            "shape": f"{ITEM_HIGHLIGHT_MIN_COUNT}-{ITEM_HIGHLIGHT_MAX_COUNT} distinct concrete source-supported phrases",
            "word_limit": f"2-{ITEM_HIGHLIGHT_MAX_WORDS} words per phrase",
            "joined_character_limit": f"under {ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS} characters including comma-and-space separators",
            "source": "synthesize only from source.item_highlights and confirmed product facts",
            "forbidden": "Do not return sentences, duplicate phrases, copied source statements, unsupported claims, or an empty array.",
        }
    user_payload["repair_rules"] = [
        "Return exactly title, item_highlights, bullets, and description as JSON.",
        "Count every character including spaces and punctuation before returning.",
        f"Keep the title at or below {TITLE_MAX_CHARS} characters.",
        f"Keep every bullet at or below {BULLET_AUDIT_MAX_CHARS} characters and target {BULLET_MODEL_MAX_CHARS}.",
        "If the title was too long, rebuild it as a short buyer-facing title instead of editing word-by-word.",
        "Remove the exact forbidden claim named by validation instead of paraphrasing it.",
        "Never convert Item Weight or product weight into load capacity, weight capacity, supports-up-to, or holds-up-to copy.",
        "Use only supplied facts and keep the title free of brand names.",
    ]
    repaired["messages"] = [
        {
            "role": "system",
            "content": (
                "Repair Amazon listing copy after deterministic validation. Return one strict JSON object only. "
                "Obey the shorter repair limits in repair_rules. Do not explain the correction or add facts."
            ),
        },
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    repaired["temperature"] = 0
    return repaired


def _only_title_validation_errors(error_text: str) -> bool:
    issues = [part.strip().lower() for part in str(error_text or "").split(";") if part.strip()]
    return bool(issues) and all("title" in issue for issue in issues)


def _only_bullet_length_errors(error_text: str) -> bool:
    issues = [part.strip() for part in str(error_text or "").split(";") if part.strip()]
    return bool(issues) and all(_BULLET_LENGTH_ISSUE_RE.search(issue) for issue in issues)


def _only_item_highlight_validation_errors(error_text: str) -> bool:
    issues = [part.strip().lower() for part in str(error_text or "").split(";") if part.strip()]
    return bool(issues) and all("item highlight" in issue for issue in issues)


def _repair_long_bullets_with_ai(
    *,
    config: CopyWriterConfig,
    invalid_body: str,
    validation_error: str,
    category: str,
    product_specific: dict[str, Any],
    brand: str,
    market_context: dict[str, Any] | None,
    forbidden_reference_brands: tuple[str, ...],
) -> dict[str, Any]:
    invalid = _copy_response_content_object(invalid_body)
    if set(invalid) != {"title", "item_highlights", "bullets", "description"}:
        raise CopyWriterError("Bullet repair requires a complete validated copy object")
    bullets = invalid.get("bullets")
    indexes = sorted({int(match.group(1)) - 1 for match in _BULLET_LENGTH_ISSUE_RE.finditer(validation_error)})
    if not isinstance(bullets, list) or not indexes or any(index < 0 or index >= len(bullets) for index in indexes):
        raise CopyWriterError("Bullet repair could not identify the invalid bullet")
    repair_payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Shorten only the supplied Amazon bullet points. Return strict JSON with exactly one key "
                    "named replacement_bullets. Preserve each index and its source-supported meaning. "
                    "Do not add facts or explain."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "invalid_bullets": [
                            {"index": index + 1, "text": str(bullets[index])}
                            for index in indexes
                        ],
                        "contract": {
                            "target": "105 characters or fewer per bullet",
                            "hard_limit": f"{BULLET_MODEL_MAX_CHARS} characters per bullet including spaces and punctuation",
                            "shape": "Short Title Case Label: one concrete buyer benefit",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": 700,
    }
    if config.json_mode:
        repair_payload["response_format"] = {"type": "json_object"}
    expected = {index + 1 for index in indexes}
    last_error: CopyWriterError | None = None
    for _ in range(2):
        repaired_body = _post_chat_completion(config, repair_payload)
        repaired = _copy_response_content_object(repaired_body)
        rows = repaired.get("replacement_bullets") if set(repaired) == {"replacement_bullets"} else None
        replacements = {
            int(row.get("index")): _model_text(row.get("text"))
            for row in rows or []
            if isinstance(row, dict) and str(row.get("index") or "").isdigit()
        }
        if set(replacements) != expected or any(
            not text or len(text) > BULLET_MODEL_MAX_CHARS for text in replacements.values()
        ):
            last_error = CopyWriterError("Copy bullet repair did not return every requested bullet within the hard limit")
            continue
        merged_bullets = list(bullets)
        for one_based, text in replacements.items():
            merged_bullets[one_based - 1] = text
        merged = {**invalid, "bullets": merged_bullets}
        merged_body = json.dumps({"choices": [{"message": {"content": json.dumps(merged, ensure_ascii=False)}}]})
        return _parse_copy_response(
            merged_body,
            category=category,
            product_specific=product_specific,
            brand=brand,
            market_context=market_context,
            forbidden_reference_brands=forbidden_reference_brands,
        )
    raise CopyWriterError(
        str(last_error or "Copy bullet repair failed"), retryable=True,
    ) from last_error


def _repair_title_only_with_ai(
    *,
    config: CopyWriterConfig,
    invalid_body: str,
    validation_error: str,
    category: str,
    product_specific: dict[str, Any],
    brand: str,
    market_context: dict[str, Any] | None,
    forbidden_reference_brands: tuple[str, ...],
) -> dict[str, Any]:
    invalid = _copy_response_content_object(invalid_body)
    if set(invalid) != {"title", "item_highlights", "bullets", "description"}:
        raise CopyWriterError("Title repair requires a complete validated copy object")
    repair_payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Compress one Amazon US title. Return JSON with exactly one key named title. "
                    "Use only words and facts already present in the supplied title. Preserve exact product structure nouns; do not replace them with near synonyms. Remove every brand name and vertical bar. "
                    "If the title contains a size or dimension, keep it at the beginning. "
                    "Count every character including spaces and punctuation. Do not explain."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "invalid_title": str(invalid.get("title") or ""),
                        "validation_error": str(validation_error or "")[:500],
                        "title_only_contract": {
                            "target": "55 characters or fewer",
                            "hard_limit": f"{TITLE_MAX_CHARS} characters",
                            "shape": "confirmed size first when present + compact product noun + one strongest existing qualifier",
                            "ending": "end with the product noun or a descriptive word; never end with a standalone measurement, weight, model code, separator, or punctuation",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": 300,
    }
    if config.json_mode:
        repair_payload["response_format"] = {"type": "json_object"}
    last_error: CopyWriterError | None = None
    for _ in range(2):
        repaired_body = _post_chat_completion(config, repair_payload)
        repaired = _copy_response_content_object(repaired_body)
        title = _model_text(repaired.get("title")) if set(repaired) == {"title"} and isinstance(repaired.get("title"), str) else ""
        if not title:
            last_error = CopyWriterError("Copy title repair did not return exactly one title string")
            continue
        merged = {**invalid, "title": title}
        merged_body = json.dumps({"choices": [{"message": {"content": json.dumps(merged, ensure_ascii=False)}}]})
        try:
            return _parse_copy_response(
                merged_body,
                category=category,
                product_specific=product_specific,
                brand=brand,
                market_context=market_context,
                forbidden_reference_brands=forbidden_reference_brands,
            )
        except CopyWriterError as exc:
            last_error = exc
            repair_payload["messages"][1]["content"] = json.dumps(
                {
                    "invalid_title": title,
                    "validation_error": str(exc),
                    "title_only_contract": {
                        "target": "50 characters or fewer",
                        "hard_limit": f"{TITLE_MAX_CHARS} characters",
                        "shape": "confirmed size first when present + compact product noun + one existing qualifier",
                    },
                },
                ensure_ascii=False,
            )
    raise CopyWriterError(
        str(last_error or "Copy title repair failed"), retryable=True,
    ) from last_error


def _repair_item_highlights_only_with_ai(
    *,
    config: CopyWriterConfig,
    invalid_body: str,
    source_item_highlights: list[str],
    category: str,
    product_specific: dict[str, Any],
    brand: str,
    market_context: dict[str, Any] | None,
    forbidden_reference_brands: tuple[str, ...],
) -> dict[str, Any]:
    invalid = _copy_response_content_object(invalid_body)
    if set(invalid) != {"title", "item_highlights", "bullets", "description"}:
        raise CopyWriterError("Item Highlight repair requires a complete validated copy object")
    repair_payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Repair only the supplied Amazon Item Highlights. Return strict JSON with exactly one key "
                    "named item_highlights. Use short distinct phrases supported by the supplied candidates. "
                    "Do not add facts or explain."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "invalid_item_highlights": invalid.get("item_highlights"),
                        "source_item_highlights": source_item_highlights,
                        "contract": {
                            "count": f"{ITEM_HIGHLIGHT_MIN_COUNT}-{ITEM_HIGHLIGHT_MAX_COUNT}",
                            "words_per_phrase": f"2-{ITEM_HIGHLIGHT_MAX_WORDS}",
                            "joined_limit": f"under {ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS} characters including comma-and-space separators",
                            "separator": ITEM_HIGHLIGHT_SEPARATOR,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": 500,
    }
    if config.json_mode:
        repair_payload["response_format"] = {"type": "json_object"}
    repaired_body = _post_chat_completion(config, repair_payload)
    repaired = _copy_response_content_object(repaired_body)
    highlights = repaired.get("item_highlights") if set(repaired) == {"item_highlights"} else None
    if not isinstance(highlights, list) or not all(isinstance(item, str) for item in highlights):
        raise CopyWriterError(
            "Copy Item Highlight repair did not return an item_highlights string array",
            retryable=True,
        )
    selected = _select_item_highlights_within_budget(highlights)
    merged = {**invalid, "item_highlights": selected}
    merged_body = json.dumps({"choices": [{"message": {"content": json.dumps(merged, ensure_ascii=False)}}]})
    try:
        return _parse_copy_response(
            merged_body,
            category=category,
            product_specific=product_specific,
            brand=brand,
            market_context=market_context,
            forbidden_reference_brands=forbidden_reference_brands,
        )
    except CopyWriterError as exc:
        raise CopyWriterError(str(exc), retryable=True) from exc


def _select_item_highlights_within_budget(values: list[str]) -> list[str]:
    """Select whole AI-authored phrases; never truncate or rewrite their meaning."""
    phrases: list[str] = []
    seen: set[str] = set()
    for value in _normalize_item_highlights(values):
        phrase = _model_text(value)
        normalized = re.sub(r"\W+", " ", phrase.casefold()).strip()
        if not phrase or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        phrases.append(phrase)
        if len(phrases) >= 12:
            break
    for count in range(min(ITEM_HIGHLIGHT_MAX_COUNT, len(phrases)), ITEM_HIGHLIGHT_MIN_COUNT - 1, -1):
        for indexes in combinations(range(len(phrases)), count):
            selected = [phrases[index] for index in indexes]
            if len(ITEM_HIGHLIGHT_SEPARATOR.join(selected)) < ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS:
                return selected
    return phrases


def _copy_payload_clone(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _copy_payload_user(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(payload["messages"][1]["content"])


def _copy_invalid_response_text(body: str) -> str:
    try:
        content = json.loads(body)["choices"][0]["message"]["content"]
    except Exception:
        content = body
    return _response_snippet(str(content or ""), limit=3500)


def _copy_market_context(
    *,
    env: dict[str, str] | None,
    category: str,
    source_title: str,
    product_specific: dict[str, Any],
) -> dict[str, Any]:
    try:
        from .search_terms import title_reference_context

        return title_reference_context(
            category=category,
            source_title=source_title,
            product_specific=product_specific,
            env={**(env or {}), **os.environ},
        )
    except Exception as exc:
        _LOGGER.warning("Copy market-reference context unavailable (%s); continuing without local references", type(exc).__name__)
        return {}


def _market_context_for_model(market_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(market_context, dict) or not market_context:
        return {}
    out = dict(market_context)
    refs = []
    for ref in out.get("references") or []:
        if not isinstance(ref, dict):
            continue
        cleaned = dict(ref)
        cleaned.pop("top_clicked_brands", None)
        refs.append(cleaned)
    out["references"] = refs
    return out


def _reference_brand_candidates(
    *,
    target_brand: str,
    source_title: str,
    source_bullets: list[str],
    source_description: str,
    product_specific: dict[str, Any],
    market_context: dict[str, Any],
) -> tuple[str, ...]:
    target_norm = _brand_norm(target_brand)
    candidates: list[str] = []

    def add(value: Any) -> None:
        cleaned = _reference_brand_candidate(value)
        if not cleaned:
            return
        normalized = _brand_norm(cleaned)
        if not normalized or normalized == target_norm:
            return
        if normalized in {_brand_norm(item) for item in candidates}:
            return
        candidates.append(cleaned)

    for value in _copy_brand_candidates(
        explicit_brand="",
        source_title=source_title,
        source_bullets=source_bullets,
        source_description=source_description,
        product_specific=product_specific,
    ):
        add(value)
    _collect_reference_brand_fields(product_specific, add)
    if isinstance(market_context, dict):
        for ref in market_context.get("references") or []:
            if not isinstance(ref, dict):
                continue
            for brand in ref.get("top_clicked_brands") or []:
                add(brand)
    return tuple(candidates)


def _collect_reference_brand_fields(value: Any, add) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key or "")
            if re.search(r"(?:^|_|\b)(brand|manufacturer|maker|seller|store|merchant)(?:$|_|\b)", key_text, re.I):
                add(nested)
            elif isinstance(nested, (dict, list)):
                _collect_reference_brand_fields(nested, add)
    elif isinstance(value, list):
        for item in value[:50]:
            _collect_reference_brand_fields(item, add)


def _reference_brand_candidate(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:-")
    if not text or len(text) > 60:
        return ""
    if re.search(r"[\n\r{}[\]\"]", text):
        return ""
    if re.search(r"\b(?:cabinet|tree|bed|chair|storage|shelf|shelves|door|frame|bathroom|medicine|artificial|floor|wall|wood|metal|white|black|gray|grey)\b", text, re.I):
        return ""
    normalized = _brand_norm(text)
    if len(normalized) < 3:
        return ""
    return text


def _brand_norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _redact_reference_brands(value: Any, forbidden_brands: tuple[str, ...]) -> str:
    text = str(value or "")
    for brand in sorted({item for item in forbidden_brands if item}, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(brand)}\b", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" ,;:-")


def _validate_no_reference_brands(result: dict[str, Any], forbidden_brands: tuple[str, ...]) -> None:
    if not forbidden_brands:
        return
    text = " ".join(
        [
            str(result.get("title") or ""),
            " ".join(str(item) for item in result.get("item_highlights", []) if str(item or "").strip()) if isinstance(result.get("item_highlights"), list) else "",
            " ".join(str(item) for item in result.get("bullets", []) if str(item or "").strip()) if isinstance(result.get("bullets"), list) else "",
            str(result.get("description") or ""),
        ]
    )
    hits = []
    for brand in sorted({item for item in forbidden_brands if item}, key=len, reverse=True):
        if _contains_reference_brand_text(text, (brand,)):
            hits.append(brand)
    if hits:
        raise CopyWriterError("Copy AI response contains forbidden reference brand: " + ", ".join(dict.fromkeys(hits)))


def _contains_reference_brand_text(text: Any, forbidden_brands: tuple[str, ...]) -> bool:
    value = str(text or "")
    for brand in sorted({item for item in forbidden_brands if item}, key=len, reverse=True):
        if re.search(rf"\b{re.escape(brand)}\b", value, re.I):
            return True
    return False


def _concrete_prompt_facts(product_specific: dict[str, Any]) -> dict[str, str]:
    if not isinstance(product_specific, dict):
        return {}
    important_keys = (
        "product_type",
        "dimensions",
        "length",
        "width",
        "height",
        "size",
        "material",
        "frame_material",
        "finish_type",
        "color",
        "mounting_type",
        "number_of_doors",
        "number_of_drawers",
        "number_of_shelves",
        "has_adjustable_shelves",
        "load_capacity",
        "load_capacity_unit",
        "weight_capacity",
        "item_weight",
        "item_weight_unit",
        "tree_type",
        "pot_material",
        "room_type",
        "included_components",
        "recommended_mattress_thickness",
        "box_spring_required",
    )
    flat = _flatten_spec_mapping(product_specific)
    out: dict[str, str] = {}
    for key in important_keys:
        value = flat.get(key)
        if value in (None, "", [], {}) or not _include_spec_prompt_fact(key, value):
            continue
        label = key.replace("_", " ").title()
        out[label] = _spec_prompt_value(value)
    return out


def _flatten_spec_mapping(value: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def visit(item: Any, depth: int = 0) -> None:
        if depth > 5 or not isinstance(item, dict):
            return
        for key, nested in item.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key or "").lower()).strip("_")
            if not normalized or re.search(r"(?:brand|manufacturer|seller|asin|sku|review|rating|rank|source)", normalized):
                continue
            if isinstance(nested, dict):
                visit(nested, depth + 1)
            elif isinstance(nested, list):
                text = ", ".join(str(part) for part in nested[:8] if str(part or "").strip())
                if text:
                    out.setdefault(normalized, text)
            else:
                out.setdefault(normalized, nested)

    visit(value)
    return out


def _spec_prompt_value(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:")
    return text[:160]


def _include_spec_prompt_fact(key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        return True
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key or "").lower()).strip("_")
    if value is True:
        return True
    # Most False booleans in extracted facts mean "not confirmed" rather than a
    # customer-facing negative claim. Keep only fields where "No" is useful.
    return normalized in {"box_spring_required"}


def rewrite_title(**kwargs: Any) -> str:
    return str(rewrite_listing_copy(**kwargs).get("title") or "")


def _post_chat_completion(config: CopyWriterConfig, payload: dict[str, Any]) -> str:
    attempts = _copy_retry_attempts(config)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            _chat_url(config.base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=config.timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in COPY_RETRY_STATUS_CODES or attempt >= attempts:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                raise CopyWriterError(
                    f"Copy AI HTTP {exc.code}: {detail}",
                    retryable=exc.code in COPY_RETRY_STATUS_CODES,
                ) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            last_exc = exc
            if attempt >= attempts:
                raise CopyWriterError(f"Copy AI request failed: {exc}", retryable=True) from exc
        except Exception as exc:
            raise CopyWriterError(f"Copy AI request failed: {exc}") from exc
        _sleep_before_copy_retry(attempt, config)
    raise CopyWriterError(
        f"Copy AI request failed after {attempts} attempts: {last_exc}", retryable=True
    )


def _copy_retry_attempts(config: CopyWriterConfig) -> int:
    return max(1, min(2, int(config.retry_attempts or 2)))


def _copy_max_tokens(config: CopyWriterConfig) -> int:
    return max(1200, min(8000, int(config.max_tokens or 5000)))


def _sleep_before_copy_retry(attempt: int, config: CopyWriterConfig) -> None:
    base = max(0.0, float(config.retry_base_seconds or 0.0))
    delay = min(30.0, base * (2 ** max(0, attempt - 1)))
    if delay > 0:
        time.sleep(delay)


def _store_cache(cache_key: str, result: dict[str, Any]) -> None:
    if cache_key in _CACHE:
        _CACHE.pop(cache_key)
    _CACHE[cache_key] = result
    while len(_CACHE) > COPY_CACHE_MAX_ENTRIES:
        _CACHE.popitem(last=False)


def _chat_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return f"{url}/chat/completions"
    return f"{url}/chat/completions"


def _parse_copy_response(
    body: str,
    *,
    category: str = "",
    row_type: str = "child",
    product_specific: dict[str, Any] | None = None,
    brand: str = "",
    market_context: dict[str, Any] | None = None,
    forbidden_reference_brands: tuple[str, ...] = (),
) -> dict[str, Any]:
    parsed = _copy_response_content_object(body)
    if set(parsed) != {"title", "item_highlights", "bullets", "description"}:
        raise CopyWriterError("Copy AI response must contain title, item_highlights, bullets, and description keys only")
    if not all(isinstance(parsed.get(key), str) for key in ("title", "description")):
        raise CopyWriterError("Copy AI title and description must be strings")
    item_highlights_raw = parsed.get("item_highlights")
    if not isinstance(item_highlights_raw, list) or not all(isinstance(item, str) for item in item_highlights_raw):
        raise CopyWriterError("Copy AI item_highlights must be an array of strings")
    bullets_raw = parsed.get("bullets")
    if not isinstance(bullets_raw, list) or len(bullets_raw) != 5 or not all(isinstance(item, str) for item in bullets_raw):
        raise CopyWriterError("Copy AI response must contain exactly five string bullets")
    title = _model_text(parsed["title"])
    item_highlights = _normalize_item_highlights(item_highlights_raw)
    optional_parent_highlights = str(row_type or "").strip().casefold() == "parent"
    if optional_parent_highlights:
        item_highlights = [
            item for item in item_highlights
            if 2 <= len(item.split()) <= ITEM_HIGHLIGHT_MAX_WORDS
        ]
    bullets = [_model_text(item) for item in bullets_raw]
    description = _model_text(parsed["description"])
    if not title or not description or any(not item for item in item_highlights) or any(not item for item in bullets):
        raise CopyWriterError("Copy AI response missed title, bullets, or description")
    validation_result = {"title": title, "item_highlights": item_highlights, "bullets": bullets, "description": description}
    issues: list[str] = []
    if brand and _contains_reference_brand_text(title, (brand,)):
        issues.append("Copy AI title must not contain the requested brand")
    try:
        _validate_no_reference_brands(validation_result, forbidden_reference_brands)
    except CopyWriterError as exc:
        issues.append(str(exc))
    if len(title) > TITLE_MAX_CHARS:
        issues.append(f"Copy title exceeds {TITLE_MAX_CHARS} characters")
    if "|" in title:
        issues.append("Copy title must not contain vertical bars")
    title_dimension = _TITLE_DIMENSION_RE.search(title)
    if title_dimension and not _TITLE_DIMENSION_RE.match(title):
        issues.append("Copy title size or dimension must appear at the beginning")
    normalized_highlights = [re.sub(r"\W+", " ", item.casefold()).strip() for item in item_highlights]
    if not optional_parent_highlights and not ITEM_HIGHLIGHT_MIN_COUNT <= len(item_highlights) <= ITEM_HIGHLIGHT_MAX_COUNT:
        issues.append(f"Copy Item Highlights must contain {ITEM_HIGHLIGHT_MIN_COUNT}-{ITEM_HIGHLIGHT_MAX_COUNT} phrases")
    if not optional_parent_highlights and any(not 2 <= len(item.split()) <= ITEM_HIGHLIGHT_MAX_WORDS for item in item_highlights):
        issues.append(f"Copy Item Highlight phrases must contain 2-{ITEM_HIGHLIGHT_MAX_WORDS} words each")
    if not optional_parent_highlights and len(set(normalized_highlights)) != len(normalized_highlights):
        issues.append("Copy Item Highlights must be distinct")
    if not optional_parent_highlights and len(ITEM_HIGHLIGHT_SEPARATOR.join(item_highlights)) >= ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS:
        issues.append(f"Copy Item Highlights joined text must be under {ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS} characters")
    oversized = [
        (index + 1, len(item))
        for index, item in enumerate(bullets)
        if len(item) > BULLET_AUDIT_MAX_CHARS
    ]
    if oversized:
        details = ", ".join(f"bullet {index} has {length}" for index, length in oversized)
        issues.append(f"Copy bullet exceeds {BULLET_AUDIT_MAX_CHARS} characters: {details}")
    if len(description) > DESCRIPTION_MAX_CHARS:
        issues.append(f"Copy description exceeds {DESCRIPTION_MAX_CHARS} characters")
    if re.search(r"(?:&|\band|\bwith|\bfor|\bof|\||[,;:])\s*$", title, flags=re.I):
        issues.append("Copy title ends with an incomplete phrase")
    normalized_bullets = [re.sub(r"\W+", " ", item.lower()).strip() for item in bullets]
    if len(set(normalized_bullets)) < len(normalized_bullets):
        issues.append("Copy AI response contains duplicate bullets")
    # Claim support comes from structured product facts only; raw source
    # (reference listing) text must never authorize a claim in our copy.
    try:
        _validate_copy_compliance(
            validation_result,
            category=category,
            product_specific=product_specific or {},
        )
    except CopyWriterError as exc:
        issues.append(str(exc))
    if issues:
        raise CopyWriterError("; ".join(dict.fromkeys(issues)))
    return {"title": title, "item_highlights": item_highlights, "bullets": bullets, "description": description}


def _model_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_item_highlights(values: Any) -> list[str]:
    """Normalize provider/source highlight containers at the Copy boundary."""
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in re.split(r"[,;|\r\n]+", str(value or "")):
            phrase = _model_text(part)
            key = re.sub(r"\W+", " ", phrase.casefold()).strip()
            if not phrase or not key or key in seen:
                continue
            seen.add(key)
            result.append(phrase)
    return result


def _copy_response_content_object(body: str) -> dict[str, Any]:
    try:
        data = json.loads(body)
        choice = data["choices"][0]
        message = choice["message"]
    except Exception as exc:
        raise CopyWriterError("Copy AI response is not OpenAI-compatible JSON: malformed response envelope") from exc
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        finish_reason = str(choice.get("finish_reason") or "unknown")[:80]
        reasoning_present = bool(message.get("reasoning_content"))
        raise CopyWriterError(
            "Copy AI response is not OpenAI-compatible JSON: assistant message.content is empty "
            f"(finish_reason={finish_reason}, reasoning_content_present={reasoning_present})"
        )
    return _loads_json_object(str(content))


def _leading_nonbrand_prefix(title: str) -> str:
    tokens = re.findall(r"\S+", title)
    if not tokens:
        return ""
    starter_words = {
        "adjustable",
        "artificial",
        "bathroom",
        "bed",
        "black",
        "bunk",
        "cabinet",
        "christmas",
        "floor",
        "folding",
        "freestanding",
        "full",
        "farmhouse",
        "gray",
        "green",
        "king",
        "linen",
        "medicine",
        "metal",
        "mirror",
        "mirrored",
        "modern",
        "narrow",
        "olive",
        "platform",
        "queen",
        "ready",
        "realistic",
        "slim",
        "storage",
        "tall",
        "tree",
        "twin",
        "wall",
        "white",
        "wood",
        "wooden",
    }
    for index, token in enumerate(tokens[:7]):
        normalized = re.sub(r"[^a-z0-9]+", "", token.lower())
        if not normalized:
            continue
        if normalized[0].isdigit() or normalized in starter_words:
            return " ".join(tokens[:index])
    if re.match(r"^[A-Z][A-Za-z0-9&'-]{2,}$", tokens[0]):
        return tokens[0]
    return ""


def _loads_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CopyWriterError(
            f"Copy AI response is not strict JSON; response_snippet={_response_snippet(text)}"
        ) from exc
    if not isinstance(parsed, dict):
        raise CopyWriterError("Copy AI response JSON is not an object")
    return parsed


def _response_snippet(text: str, limit: int = 500) -> str:
    snippet = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(snippet) > limit:
        snippet = snippet[:limit] + "..."
    return snippet


def _validate_copy_compliance(
    result: dict[str, Any],
    *,
    category: str,
    product_specific: dict[str, Any],
) -> None:
    title = str(result.get("title") or "")
    text = " ".join(
        [
            title,
            " ".join(str(item) for item in result.get("item_highlights", []) if item),
            " ".join(str(item) for item in result.get("bullets", []) if item),
            str(result.get("description") or ""),
        ]
    )
    fact_text = json.dumps(product_specific or {}, ensure_ascii=False, sort_keys=True, default=str).lower()
    violations: list[str] = []
    for pattern in HARD_SUBJECTIVE_FORBIDDEN_PATTERNS:
        match = pattern.search(text)
        if match:
            violations.append(match.group(0))
    for pattern in PROMOTIONAL_FORBIDDEN_PATTERNS:
        match = pattern.search(text)
        if match:
            violations.append(match.group(0))
    for pattern in EXTERNAL_REFERENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            violations.append(f"external reference: {match.group(0)}")
    environmental_fact = re.search(
        r"\b(?:eco|biodegradable|organic|sustainable|recyclable|carbon|environmentally?\s+friendly)\b",
        fact_text,
        re.I,
    )
    for pattern in ENVIRONMENTAL_FORBIDDEN_PATTERNS:
        match = pattern.search(text)
        if match and not environmental_fact:
            violations.append(f"unsupported environmental claim: {match.group(0)}")
    if re.search(r"\bpatent(?:ed| pending)?\b", text, re.I) and "patent" not in fact_text:
        violations.append("unsupported patent claim")
    price_match = re.search(
        r"(?:[$]\s*\d+(?:\.\d{2})?|\b(?:only|just)\s+[$]\s*\d+(?:\.\d{2})?|\b\d+(?:\.\d{2})?\s*(?:usd|dollars?)\b)",
        text,
        re.I,
    )
    if price_match:
        violations.append("price information")
    if SPECIAL_TITLE_CHARS.search(title):
        violations.append("special character in title")
    for issue in listing_title_quality_issues(title, category=category):
        violations.append(f"title quality: {issue}")
    if title.rstrip().endswith("."):
        violations.append("title ends with period")
    first_title_word = (re.findall(r"\b[A-Z][A-Z0-9-]{4,}\b", title) or [""])[0]
    for word in re.findall(r"\b[A-Z][A-Z0-9-]{4,}\b", title):
        if word not in ALLOWED_TITLE_ACRONYMS and word != first_title_word:
            violations.append(f"all-caps title word: {word}")
    if re.search(r"\b(?:guarantee|guaranteed|warranty|warranties)\b", text, re.I) and not re.search(r"\b(?:guarantee|warranty)\b", fact_text, re.I):
        violations.append("unsupported warranty/guarantee")
    if re.search(r"\bwaterproof\b", text, re.I) and not re.search(r"\b(?:waterproof|ipx)\b", fact_text, re.I):
        violations.append("unsupported waterproof")
    if re.search(r"\b(?:safety certified|child-safe|non-toxic|cpsc compliant|ul listed)\b", text, re.I) and not re.search(
        r"\b(?:certif|cpsc|ul listed|non-toxic|child-safe)\b", fact_text,
        re.I,
    ):
        violations.append("unsupported certification/safety claim")
    capacity_claim = re.search(r"\b(?:weight capacity|load capacity|supports up to|holds up to|up to \d+ ?(?:lb|lbs|pounds|kg))\b", text, re.I)
    capacity_fact = re.search(
        r"\b(?:weight_capacity|load_capacity|maximum_weight|max_weight|weight capacity|load capacity|capacity of|supports up to|holds up to)\b",
        fact_text,
        re.I,
    )
    if capacity_claim and not capacity_fact:
        violations.append("unsupported weight capacity")
    if re.search(r"\bergonomic\b", text, re.I) and not re.search(r"\b(?:ergonomic|ansi|bifma)\b", fact_text, re.I):
        violations.append("unsupported ergonomic")
    if re.search(r"\brust[- ]?proof\b", text, re.I) and "rust" not in fact_text:
        violations.append("unsupported rust-proof")
    if re.search(r"\bshatterproof\b", text, re.I) and not re.search(r"\b(?:shatterproof|tempered)\b", fact_text, re.I):
        violations.append("unsupported shatterproof")
    if re.search(r"\buv[- ]?resistan(?:t|ce)\b", text, re.I) and "uv" not in fact_text:
        violations.append("unsupported UV resistance")
    if re.search(r"\b(?:fire[- ]?retardant|flame[- ]?resistant|hypoallergenic|allergen[- ]?free)\b", text, re.I) and not re.search(r"\b(?:fire|flame|hypoallergenic|allergen)\b", fact_text, re.I):
        violations.append("unsupported safety/material claim")
    if violations:
        unique = ", ".join(dict.fromkeys(violations))
        raise CopyWriterError(f"Copy AI response contains forbidden Amazon claim: {unique}")


def _limit_text(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rstrip()
    for separator in (". ", "; ", ", ", " "):
        index = cut.rfind(separator)
        if index >= int(limit * 0.65):
            cut = cut[:index].rstrip(" ,;:")
            break
    return cut.rstrip(".") + "."

def _cache_key(config: CopyWriterConfig, *items: Any) -> str:
    material = json.dumps(
        [copy_request_identity(config), *items],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def copy_request_identity(config: CopyWriterConfig) -> dict[str, Any]:
    return {
        "prompt_version": COPY_WRITER_PROMPT_VERSION,
        "provider": config.base_url,
        "model": config.model,
        "max_tokens": config.max_tokens,
        "json_mode": config.json_mode,
        "temperature": config.temperature,
    }
