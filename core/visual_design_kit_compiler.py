from __future__ import annotations

import re
from typing import Any

from .visual_semantics import CLAIM_REVIEW_POLICY, claim_key
from .image_reference_context import validate_supporting_sources
from .text_evidence import has_bad_encoding


class VisualDesignKitCompileError(ValueError):
    pass


def cleaned_source_claims(source: dict[str, Any]) -> list[dict[str, str]]:
    """Expose only usable evidence concepts to planning and story binding.

    Raw OCR remains available for audit/classification, but one-character
    fragments and mojibake must not become planner evidence or renderable copy.
    """
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for claim in source.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        evidence_id = str(claim.get("evidence_id") or "").strip()
        text = " ".join(str(claim.get("text") or "").split())
        words = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text)
        if (
            not evidence_id
            or not text
            or has_bad_encoding(text)
            or len(words) < 2
            or any(
                len(word) == 1
                and word.casefold() not in {"x", "a", "i"}
                and not word.isdigit()
                for word in words
            )
        ):
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append({"evidence_id": evidence_id, "text": text})
    return result


_ART_DIRECTION_FIELDS = {
    "audience_and_market",
    "palette_direction",
    "photography_direction",
    "environment_and_staging",
    "typography_direction",
    "graphic_direction",
    "cohesion_rule",
    "negative_visuals",
}
# Gemini is the single visual authority. The compiler validates and binds its
# design to immutable product evidence; it does not replace design fields.
_PLANNER_ART_DIRECTION_FIELDS = _ART_DIRECTION_FIELDS
_BRIEF_BINDING_FIELDS = {
    "source_id",
    "source_intent_revision_id",
    "source_sha256",
    "role",
}
_BRIEF_ROLE_FIELDS = {
    "main": {"shopping_purpose", "image_direction"},
    "scene": {"shopping_purpose", "image_direction"},
    "func": {"shopping_purpose", "image_direction", "func_story_contract", "claim_reviews"},
    "size": {"shopping_purpose", "image_direction", "measurement_authority", "invent_text"},
}
# Every brief must carry a positive per-image direction. Making it
# optional let flash-class planners omit it silently, so func/size prompts
# reached the image model with family art direction as their only design
# input.  Absence is now a compile error; the planner repair loop reports the
# missing field and gets one bounded chance to fix it.
_BRIEF_OPTIONAL_FIELDS = {"main": set(), "scene": set(), "func": set(), "size": set()}
# A complete art-direction field can legitimately be longer than a short
# label.  Keep a bounded contract, but do not reject a coherent provider
# response merely because it explains the physical design in detail.
_ART_DIRECTION_FIELD_MAX = 2200
_SOURCE_BRIEF_FIELD_MAX = 700
_SHOPPING_PURPOSE_MAX = 320
_MEASUREMENT_RE = re.compile(
    r"(?<![A-Za-z0-9])\d+(?:\.\d+)?\s*"
    r"(?:in(?:ch(?:es)?)?|ft|feet|foot|cm|mm|lb|lbs|pounds?|kg)(?![A-Za-z])",
    re.I,
)
_PRODUCT_PART_STATE_MUTATION_RE = re.compile(
    r"\b(?:add|remove|replace|relocate|reverse)\s+(?:the\s+)?"
    r"(?:product|trees?|pots?|bases?|trunks?|flowers?|branches?|foliage|doors?|drawers?|shelves|panels?|mirrors?|supports?|ladders?|slides?|hinges?|handles?)\b|"
    r"\b(?:change|convert|reconfigure|transform)\s+(?:the\s+)?"
    r"(?:product|trees?|pots?|bases?|trunks?|flowers?|branches?|foliage|doors?|drawers?|shelves|panels?|mirrors?|supports?|ladders?|slides?)"
    r"(?:\s+from\b|\s+to\b)|"
    r"\b(?:show|render)\b[^.]{0,100}\b(?:open|closed|folded|extended)\b[^.]{0,60}\bin every role\b",
    re.I,
)
_RENDERABLE_COPY_INSTRUCTION_RE = re.compile(
    r"(?:^|[\r\n;])\s*(?:text|title|caption|slogan|headline|label|copy)\s*:\s*"
    r"|\b(?:render|write|print|spell|include|display|show|place)\s+(?:the\s+)?(?:following\s+)?"
    r"(?:text|title|caption|slogan|headline|label|words|copy)\b"
    r"|\b(?:set|name|call)\s+(?:the\s+)?(?:visible\s+)?"
    r"(?:text|title|caption|slogan|headline|label|copy)\s+(?:to|as|reading|saying)\b"
    r"|\b(?:text|title|caption|slogan|headline|label|copy)\b[^.\r\n]{0,48}"
    r"\b(?:reads?|reading|says?|saying|worded\s+as)\b",
    re.I,
)


def compile_visual_design_kit_response(
    raw: Any, *, source_manifest: list[dict[str, Any]], category_id: str = "",
    claim_reviews: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keep shared design valid while isolating incomplete individual briefs."""
    if not isinstance(raw, dict):
        raise VisualDesignKitCompileError("planner response must be an object")
    art_direction = _compile_art_direction(raw.get("family_art_direction"))
    raw_briefs = raw.get("source_briefs")
    if not isinstance(raw_briefs, list):
        raise VisualDesignKitCompileError("source_briefs must be a list")
    expected_ids = {str(source["source_id"]) for source in source_manifest}
    raw_by_source = {}
    for row in raw_briefs:
        if not isinstance(row, dict) or row.get("source_id") not in expected_ids:
            raise VisualDesignKitCompileError("source brief has an unknown source_id")
        if row["source_id"] in raw_by_source:
            raise VisualDesignKitCompileError("duplicate source brief")
        raw_by_source[row["source_id"]] = row
    product_claims = _global_product_claims(source_manifest)
    briefs = []
    for source in source_manifest:
        draft = raw_by_source.get(str(source["source_id"])) or {}
        try:
            brief = _compile_source_brief(
                source, draft, product_claims=product_claims,
                category_id=category_id, claim_reviews=claim_reviews or {},
            )
            brief["supporting_sources"] = validate_supporting_sources(draft.get("supporting_sources", []), source_manifest, source["source_id"])
            brief["status"] = "ready"
            _validate_briefs([brief], [source], product_claims=product_claims, category_id=category_id)
        except ValueError as exc:
            brief = {
                "source_id": source["source_id"], "source_sha256": source["source_sha256"],
                "source_intent_revision_id": source["input_revision_id"], "role": source["role"],
                "status": "pending", "error": str(exc), "draft": draft,
            }
        briefs.append(brief)
    result = {"family_art_direction": art_direction, "source_briefs": briefs}
    validate_compiled_visual_design_kit(result, source_manifest=source_manifest, category_id=category_id)
    return result


def claim_review_requests(raw: Any, source_manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect scoped claims for the independent reviewer before compilation."""
    sources = {source["source_id"]: source for source in source_manifest}
    product_claims = _global_product_claims(source_manifest)
    requests = {}
    for brief in raw.get("source_briefs") or []:
        source = sources.get(brief.get("source_id")) if isinstance(brief, dict) else None
        if not source or source["role"] != "func":
            continue
        available = _available_claims(source, product_claims)
        story = brief.get("func_story") or {}
        if not isinstance(story, dict):
            continue
        labels = story.get("labels") if isinstance(story.get("labels"), list) else []
        for value in [story.get("title"), *labels]:
            try:
                bound = _copy_binding(value, available)
            except VisualDesignKitCompileError:
                continue
            evidence = {key: available[key] for key in bound["evidence_ids"]}
            if bound["text"] in evidence.values():
                continue
            key = claim_key(bound["text"], evidence)
            requests[key] = {"key": key, "proposed_text": bound["text"], "evidence": evidence}
    return list(requests.values())


def validate_compiled_visual_design_kit(
    data: Any,
    *,
    source_manifest: list[dict[str, Any]],
    category_id: str = "",
) -> None:
    if not isinstance(data, dict) or set(data) != {"family_art_direction", "source_briefs"}:
        raise VisualDesignKitCompileError("planner response fields do not match the current VisualDesignKit contract")
    _validate_art_direction(data["family_art_direction"])
    for brief in data["source_briefs"]:
        if brief.get("status") == "ready":
            validate_supporting_sources(brief["supporting_sources"], source_manifest, brief["source_id"])
    _validate_briefs(
        data["source_briefs"],
        source_manifest,
        product_claims=_global_product_claims(source_manifest),
        category_id=category_id,
    )


def _compile_art_direction(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VisualDesignKitCompileError("family_art_direction is missing")
    result = {
        field: _required_text(
            value.get(field),
            f"family_art_direction.{field}",
            _ART_DIRECTION_FIELD_MAX,
        )
        for field in _PLANNER_ART_DIRECTION_FIELDS - {"negative_visuals"}
    }
    negative = _text_list(value.get("negative_visuals"), maximum=6)
    if not 2 <= len(negative) <= 6:
        raise VisualDesignKitCompileError("family_art_direction needs 2-6 negative visuals")
    for index, item in enumerate(negative):
        _reject_renderable_copy_instruction(
            item, f"family_art_direction.negative_visuals[{index}]"
        )
    result["negative_visuals"] = negative
    return result


def _compile_source_brief(
    source: dict[str, Any], draft: dict[str, Any], *,
    product_claims: list[dict[str, Any]] | None = None, category_id: str = "",
    claim_reviews: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    role = str(source["role"])
    result = {
        "source_id": str(source["source_id"]),
        "source_intent_revision_id": str(source["input_revision_id"]),
        "source_sha256": str(source["source_sha256"]),
        "role": role,
        "shopping_purpose": _source_brief_text(draft.get("shopping_purpose"), "shopping_purpose", _SHOPPING_PURPOSE_MAX, category_id=category_id),
        "image_direction": _source_brief_text(draft.get("image_direction"), "image_direction", _SOURCE_BRIEF_FIELD_MAX, category_id=category_id),
    }
    if role == "func":
        result["func_story_contract"] = _compile_func_story(source, draft.get("func_story"), product_claims=product_claims, claim_reviews=claim_reviews)
        available = _available_claims(source, product_claims)
        used_keys = {claim_key(row["text"], {key: available[key] for key in row["evidence_ids"]})
                    for row in result["func_story_contract"]["bindings"]}
        result["claim_reviews"] = {key: value for key, value in claim_reviews.items() if key in used_keys}
    elif role == "size":
        result.update(measurement_authority="complete_source_measurement_diagram", invent_text=False)
    return result


def _compile_func_story(
    source: dict[str, Any], value: Any, *,
    product_claims: list[dict[str, Any]] | None = None,
    claim_reviews: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    available = _available_claims(source, product_claims)
    if not isinstance(value, dict) or set(value) != {"title", "labels"} or not isinstance(value.get("labels"), list):
        raise VisualDesignKitCompileError("func story needs an explicit title choice and label list")
    title = value["title"]
    bindings = [_bind_func_story_text(row, available, claim_reviews=claim_reviews)
                for row in ([title] if title is not None else []) + value["labels"]]
    strings = [row["text"] for row in bindings]
    if len(strings) != len(set(text.casefold() for text in strings)) or sum(map(len, strings)) > 1200:
        raise VisualDesignKitCompileError("func copy is duplicated or exceeds its content budget")
    return {"mode": "source_claims", "title": strings[0] if title is not None else "",
            "labels": strings[1:] if title is not None else strings, "bindings": bindings}


def _copy_binding(value: Any, available: dict[str, str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"evidence_ids", "text"}:
        raise VisualDesignKitCompileError("func story copy is malformed")
    ids = value.get("evidence_ids")
    text = value.get("text")
    if (
        not isinstance(ids, list) or not ids or any(not isinstance(key, str) or key not in available for key in ids)
        or len(ids) != len(set(ids)) or not isinstance(text, str) or not text.strip()
        or len(text) > 240 or has_bad_encoding(text)
    ):
        raise VisualDesignKitCompileError("func story copy has invalid text or evidence scope")
    return {"evidence_ids": list(ids), "text": text}


def _bind_func_story_text(
    value: Any, available: dict[str, str], *,
    claim_reviews: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    bound = _copy_binding(value, available)
    evidence = {key: available[key] for key in bound["evidence_ids"]}
    if bound["text"] in evidence.values():
        return bound
    key = claim_key(bound["text"], evidence)
    review = (claim_reviews or {}).get(key) or {}
    if review.get("status") != "supported" or review.get("policy") != CLAIM_REVIEW_POLICY or review.get("key") != key or not review.get("response_sha256"):
        raise VisualDesignKitCompileError("func claim requires independent evidence review: " + str(review.get("reason") or bound["text"]))
    return bound


def _validate_art_direction(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != _ART_DIRECTION_FIELDS:
        raise VisualDesignKitCompileError("family_art_direction fields do not match the V11 contract")
    for field in _ART_DIRECTION_FIELDS - {"negative_visuals"}:
        _valid_text(
            value[field],
            f"family_art_direction.{field}",
            5,
            _ART_DIRECTION_FIELD_MAX,
        )
        if _MEASUREMENT_RE.search(value[field]):
            raise VisualDesignKitCompileError(
                f"family_art_direction.{field} contains a product measurement"
            )
        if _PRODUCT_PART_STATE_MUTATION_RE.search(value[field]):
            raise VisualDesignKitCompileError(
                f"family_art_direction.{field} changes a source-visible product state"
            )
    _valid_text_list(
        value["negative_visuals"],
        "family_art_direction.negative_visuals",
        2,
        6,
        180,
    )


def _validate_briefs(
    briefs: Any,
    sources: list[dict[str, Any]],
    *,
    product_claims: list[dict[str, Any]] | None = None,
    category_id: str = "",
) -> None:
    expected = {
        row["source_id"]: row
        for row in sources
        if row.get("role") in {"main", "scene", "func", "size"}
    }
    if not isinstance(briefs, list) or len(briefs) != len(expected):
        raise VisualDesignKitCompileError(
            "source_briefs do not cover every source exactly once"
        )
    seen: set[str] = set()
    for index, brief in enumerate(briefs):
        source_id = str(brief.get("source_id") or "") if isinstance(brief, dict) else ""
        if source_id not in expected or source_id in seen:
            raise VisualDesignKitCompileError(
                f"source_briefs[{index}] has a missing, duplicate, or unknown source_id"
            )
        seen.add(source_id)
        source = expected[source_id]
        role = str(source["role"])
        if brief.get("status") == "pending":
            if set(brief) != _BRIEF_BINDING_FIELDS | {"status", "error", "draft"} or not brief.get("error") or not isinstance(brief.get("draft"), dict):
                raise VisualDesignKitCompileError("invalid pending source brief")
            _validate_source_binding(brief, source, index)
            continue
        if brief.get("status") != "ready":
            raise VisualDesignKitCompileError("source brief readiness is missing")
        required_fields = _BRIEF_BINDING_FIELDS | _BRIEF_ROLE_FIELDS[role] | {"status", "supporting_sources"}
        allowed_fields = required_fields | _BRIEF_OPTIONAL_FIELDS[role]
        missing_fields = sorted(required_fields - set(brief))
        unknown_fields = sorted(set(brief) - allowed_fields)
        if missing_fields or unknown_fields or brief.get("role") != role:
            detail = "; ".join(
                part for part in (
                    f"missing: {', '.join(missing_fields)}" if missing_fields else "",
                    f"unknown: {', '.join(unknown_fields)}" if unknown_fields else "",
                    "role mismatch" if brief.get("role") != role else "",
                ) if part
            )
            raise VisualDesignKitCompileError(
                f"source_briefs[{index}] fields do not match its {role} contract ({detail})"
            )
        _validate_source_binding(brief, source, index)
        _valid_text(
            brief["shopping_purpose"],
            f"source_briefs[{index}].shopping_purpose",
            5,
            _SHOPPING_PURPOSE_MAX,
        )
        _image_direction_text(
            brief["image_direction"],
            f"source_briefs[{index}].image_direction",
            category_id=category_id,
        )
        if role == "func":
            _validate_func_brief(
                brief, source, index, product_claims=product_claims,
            )
        elif (
            role == "size"
            and (
                brief["measurement_authority"] != "complete_source_measurement_diagram"
                or brief["invent_text"] is not False
            )
        ):
            raise VisualDesignKitCompileError(
                f"source_briefs[{index}] changed size measurement authority"
            )


def _validate_source_binding(
    brief: dict[str, Any],
    source: dict[str, Any],
    index: int,
) -> None:
    if (
        brief["role"] != source["role"]
        or brief["source_intent_revision_id"] != source["input_revision_id"]
        or brief["source_sha256"] != source["source_sha256"]
    ):
        raise VisualDesignKitCompileError(
            f"source_briefs[{index}] source binding changed"
        )


def _validate_func_brief(
    brief: dict[str, Any], source: dict[str, Any], index: int, *,
    product_claims: list[dict[str, Any]] | None = None,
) -> None:
    story = brief.get("func_story_contract")
    if not isinstance(story, dict) or set(story) != {"mode", "title", "labels", "bindings"} or story.get("mode") != "source_claims":
        raise VisualDesignKitCompileError(f"source_briefs[{index}] has no canonical FuncStoryContract")
    if not isinstance(story["labels"], list) or not isinstance(story["bindings"], list):
        raise VisualDesignKitCompileError("func story lists are malformed")
    strings = ([story["title"]] if story["title"] else []) + story["labels"]
    if len(strings) != len(story["bindings"]) or len(strings) != len(set(strings)):
        raise VisualDesignKitCompileError("func copy bindings changed")
    available = _available_claims(source, product_claims)
    for text, binding in zip(strings, story["bindings"]):
        if _bind_func_story_text(binding, available, claim_reviews=brief["claim_reviews"])["text"] != text:
            raise VisualDesignKitCompileError("func text disagrees with its reviewed binding")


def _available_claims(
    source: dict[str, Any],
    product_claims: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    rows = [
        *cleaned_source_claims(source),
        *compatible_product_claims({
            "claims": source.get("claims") or [],
            "product_claims": (
                product_claims
                if product_claims is not None
                else source.get("product_claims") or []
            ),
        }),
    ]
    return {
        str(row.get("evidence_id") or ""): str(row.get("text") or "")
        for row in rows
        if isinstance(row, dict)
        and str(row.get("evidence_id") or "")
        and str(row.get("text") or "").strip()
    }


def _global_product_claims(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one immutable child-level product-fact set for all sources."""
    unique: dict[str, dict[str, Any]] = {}
    for source in sources:
        for claim in source.get("product_claims") or []:
            if not isinstance(claim, dict):
                continue
            evidence_id = str(claim.get("evidence_id") or "")
            if evidence_id and evidence_id not in unique:
                unique[evidence_id] = claim
    return list(unique.values())


def compatible_product_claims(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose source statements, not a regex-derived truth verdict."""
    return [row for row in source.get("product_claims") or [] if isinstance(row, dict) and row.get("evidence_id") and row.get("text")]


def _text_list(value: Any, *, maximum: int) -> list[str]:
    values = value if isinstance(value, list) else []
    rows: list[str] = []
    for item in values:
        text = _optional_text(item, 180)
        if text and text not in rows:
            rows.append(text)
    return rows[:maximum]


def _required_text(value: Any, label: str, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise VisualDesignKitCompileError(f"{label} is missing")
    if len(text) > maximum:
        raise VisualDesignKitCompileError(f"{label} exceeds {maximum} characters")
    _reject_renderable_copy_instruction(text, label)
    return text


def _source_brief_text(
    value: Any,
    label: str,
    maximum: int,
    *,
    category_id: str = "",
) -> str:
    text = _required_text(value, label, maximum)
    if _product_state_mutation(text, category_id=category_id):
        raise VisualDesignKitCompileError(
            f"{label} tries to change a source-visible product state"
        )
    return text


def _validate_scene_state_boundary(value: str, label: str, *, category_id: str) -> None:
    if _product_state_mutation(value, category_id=category_id):
        raise VisualDesignKitCompileError(
            f"{label} tries to change a source-visible product state"
        )


def _image_direction_text(value: Any, label: str, *, category_id: str) -> str:
    """Validate required func/size visual guidance without treating layout language as copy.

    Func/size directions may naturally mention titles, labels, or callouts as
    visual objects.  Exact readable strings remain owned by FuncStoryContract
    and MeasurementContract; rejecting ordinary words such as "show labels"
    here would turn a quality hint into a new planner blocker.
    """
    _valid_text(value, label, 5, _SOURCE_BRIEF_FIELD_MAX)
    text = str(value)
    _validate_scene_state_boundary(text, label, category_id=category_id)
    return text


def _product_state_mutation(value: str, *, category_id: str = "") -> bool:
    """Reject sold-product state changes while allowing known scene restyling.

    Artificial-tree scene references often contain doors, walls, floors, or
    furniture. Those are staging, not sold parts. Mask only those explicit
    environment nouns before applying the existing product-state rule; tree,
    pot, base, trunk, and support wording remains protected.
    """
    text = str(value or "")
    if category_id == "artificial_tree":
        text = re.sub(
            r"\b(?:door|doors|siding|wall|walls|floor|flooring|tiles?|mat|mats|rug|rugs|"
            r"sofa|bench|shelf|shelves|furniture|window|windows|paint|wreath|wreaths|"
            r"vase|vases|pottery|props|decor|decoration|cat)\b",
            "staging",
            text,
            flags=re.I,
        )
    return bool(_PRODUCT_PART_STATE_MUTATION_RE.search(text))


def _reject_renderable_copy_instruction(value: str, label: str) -> None:
    if _RENDERABLE_COPY_INSTRUCTION_RE.search(value):
        raise VisualDesignKitCompileError(
            f"{label} contains a renderable-copy instruction; readable copy belongs only to FuncStoryContract or MeasurementContract"
        )


def _optional_text(value: Any, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= maximum:
        return text
    return text[: maximum + 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")


def _valid_text_list(
    value: Any,
    label: str,
    minimum: int,
    maximum: int,
    item_maximum: int,
) -> None:
    if (
        not isinstance(value, list)
        or not minimum <= len(value) <= maximum
        or len(value) != len(set(value))
    ):
        raise VisualDesignKitCompileError(
            f"{label} must contain {minimum}-{maximum} unique items"
        )
    for index, item in enumerate(value):
        _valid_text(item, f"{label}[{index}]", 2, item_maximum)


def _valid_text(value: Any, label: str, minimum: int, maximum: int) -> None:
    if (
        not isinstance(value, str)
        or not minimum <= len(value) <= maximum
        or value != value.strip()
        or not value
    ):
        raise VisualDesignKitCompileError(
            f"{label} is missing or outside its length budget"
        )
    if (
        has_bad_encoding(value)
        or "\ufffd" in value
        or re.search(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", value)
        or re.search(r"[\u0400-\u04ff\u4e00-\u9fff]", value)
    ):
        raise VisualDesignKitCompileError(
            f"{label} contains malformed or non-English text"
        )
