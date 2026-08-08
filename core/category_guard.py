from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .plugin import ProductPlugin, discover_plugins
from .product_family import read_product_family


class CategoryMismatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class CategoryMatchResult:
    category_id: str
    positive_hits: list[str]
    negative_hits: list[str]
    suggested_category: str
    suggested_hits: list[str]


@dataclass(frozen=True)
class CategoryRouteResult:
    category_id: str
    positive_hits: list[str]
    score: int
    title: str
    all_scores: dict[str, int]
    confidence: str = "low"


def assert_family_matches_plugin(job_dir: str | Path, plugin: ProductPlugin) -> CategoryMatchResult:
    family = read_product_family(job_dir)
    _assert_family_identity(family, plugin)
    result = check_family_matches_plugin(family, plugin)
    if result.negative_hits or (_requires_positive(plugin) and not result.positive_hits):
        suggestion = ""
        if result.suggested_category and result.suggested_category != plugin.category_id:
            suggestion = f" Suggested category: {result.suggested_category} ({', '.join(result.suggested_hits[:6])})."
        raise CategoryMismatchError(
            f"Fetched ASIN content does not match category '{plugin.category_id}'. "
            f"Positive hits: {', '.join(result.positive_hits) or 'none'}. "
            f"Negative hits: {', '.join(result.negative_hits) or 'none'}.{suggestion}"
        )
    return result


def _assert_family_identity(family: dict[str, Any], plugin: ProductPlugin) -> None:
    if family.get("category_id") != plugin.category_id or family.get("product_type") != plugin.product_type:
        raise CategoryMismatchError("ProductFamilyV3 category/product type does not match the selected plugin")
    if plugin.category_id not in family.get("product_specific", {}):
        raise CategoryMismatchError("ProductFamilyV3 has no category-specific family facts")
    children = family["family"]["children"]
    asins = [child["asin"] for child in children]
    if len(asins) != len(set(asins)):
        raise CategoryMismatchError("ProductFamilyV3 contains duplicate child ASINs")
    if any(plugin.category_id not in child["product_specific"] for child in children):
        raise CategoryMismatchError("ProductFamilyV3 child has no category-specific facts")


def check_family_matches_plugin(family: dict[str, Any], plugin: ProductPlugin) -> CategoryMatchResult:
    text = _family_text(family)
    cfg = _match_config(plugin)
    priority_hits = _hits(text, cfg.get("priority_keywords"))
    positive_hits = list(dict.fromkeys([*priority_hits, *_hits(text, cfg.get("positive_keywords"))]))
    raw_negative_hits = _hits(text, _match_config(plugin).get("negative_keywords"))
    if priority_hits:
        raw_negative_hits = []
    target_score = _score_hits(positive_hits, raw_negative_hits)
    suggested_category = ""
    suggested_hits: list[str] = []
    suggested_score = -10_000
    for candidate in discover_plugins().values():
        if candidate.category_id == plugin.category_id:
            continue
        cfg = _match_config(candidate)
        candidate_hits = _hits(text, cfg.get("positive_keywords"))
        candidate_negative_hits = _hits(text, cfg.get("negative_keywords"))
        candidate_score = _score_hits(candidate_hits, candidate_negative_hits)
        if candidate_score > suggested_score:
            suggested_category = candidate.category_id
            suggested_hits = candidate_hits
            suggested_score = candidate_score
    negative_hits = raw_negative_hits
    if raw_negative_hits and positive_hits and target_score > 0 and target_score > suggested_score:
        negative_hits = []
    return CategoryMatchResult(
        category_id=plugin.category_id,
        positive_hits=positive_hits,
        negative_hits=negative_hits,
        suggested_category=suggested_category,
        suggested_hits=suggested_hits,
    )


def guess_category_from_raw(raw: dict[str, Any]) -> CategoryRouteResult:
    title = str(raw.get("title") or raw.get("productTitle") or "").strip()
    text = " ".join(_flatten_text(raw)).lower()
    return guess_category_from_text(text, title=title)


def guess_category_from_text(text: str, *, title: str = "") -> CategoryRouteResult:
    normalized = text.lower()
    best_category = ""
    best_hits: list[str] = []
    best_score = 0
    scores: dict[str, int] = {}
    for candidate in discover_plugins().values():
        cfg = _match_config(candidate)
        priority_hits = _hits(normalized, cfg.get("priority_keywords"))
        positive_hits = list(dict.fromkeys([*priority_hits, *_hits(normalized, cfg.get("positive_keywords"))]))
        negative_hits = _hits(normalized, cfg.get("negative_keywords"))
        if priority_hits:
            negative_hits = []
        score = _score_hits(positive_hits, negative_hits)
        if priority_hits:
            score += 100
        scores[candidate.category_id] = score
        if score > best_score:
            best_category = candidate.category_id
            best_hits = positive_hits
            best_score = score
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    best_plugin = next((item for item in discover_plugins().values() if item.category_id == best_category), None)
    best_cfg = _match_config(best_plugin) if best_plugin is not None else {}
    has_priority = bool(_hits(normalized, best_cfg.get("priority_keywords")))
    margin = best_score - runner_up
    confidence = "high" if has_priority or margin >= 6 else ("medium" if margin >= 3 else "low")
    # An ambiguous low-signal match is not a safe category decision.  Return
    # no route so the caller can request review instead of creating a job with
    # the wrong product manifest.
    if confidence == "low":
        best_category = ""
        best_hits = []
    return CategoryRouteResult(
        category_id=best_category,
        positive_hits=best_hits,
        score=best_score,
        title=title,
        all_scores=scores,
        confidence=confidence,
    )


def _score_hits(positive_hits: list[str], negative_hits: list[str]) -> int:
    return len(positive_hits) * 3 - len(negative_hits) * 5


def _requires_positive(plugin: ProductPlugin) -> bool:
    cfg = _match_config(plugin)
    return str(cfg.get("require_positive_match", "true")).strip().lower() not in {"0", "false", "no"}


def _match_config(plugin: ProductPlugin) -> dict[str, Any]:
    cfg = plugin.merged_config().get("category_match")
    return cfg if isinstance(cfg, dict) else {}


def _hits(text: str, values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    hits: list[str] = []
    for value in values:
        needle = str(value or "").strip().lower()
        if needle and _keyword_in_text(needle, text) and needle not in hits:
            hits.append(needle)
    return hits


def _keyword_in_text(needle: str, text: str) -> bool:
    parts = [part for part in re.split(r"[\s_-]+", needle.strip().lower()) if part]
    if not parts:
        return False
    pattern = r"(?<![a-z0-9])" + r"[\s_-]+".join(re.escape(part) for part in parts) + r"(?![a-z0-9])"
    return bool(re.search(pattern, text.lower()))


def _family_text(family: dict[str, Any]) -> str:
    parts: list[str] = []
    source = family.get("source")
    if isinstance(source, dict):
        parts.extend(_flatten_text(source.get("seed_asin")))
    family_block = family.get("family")
    if isinstance(family_block, dict):
        parts.extend(_flatten_text(family_block.get("brand")))
        parts.extend(_flatten_text(family_block.get("variation_theme")))
        for child in family_block.get("children") or []:
            if isinstance(child, dict):
                for key in ("title", "bullets", "description"):
                    parts.extend(_flatten_text(child.get(key)))
                for key in ("specs", "variation_values", "product_specific"):
                    parts.extend(_flatten_values(child.get(key)))
    return " ".join(part.lower() for part in parts if part)


def _flatten_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_text(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for key, item in value.items():
            out.extend(_flatten_text(key))
            out.extend(_flatten_text(item))
        return out
    return [str(value)]


def _flatten_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_flatten_values(item))
        return out
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_values(item))
        return out
    return _flatten_text(value)
