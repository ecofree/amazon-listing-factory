from __future__ import annotations

import json
import re
from typing import Any

from .image_task_inputs import func_story_title_is_specific
from .text_evidence import has_bad_encoding


class VisualDesignKitCompileError(ValueError):
    pass


_PALETTE_COLOR_TOKEN = (
    r"(?:blue|green|red|orange|yellow|purple|pink|beige|cream|brown|gray|grey|navy|teal|sage|lavender|plum|mauve|camel|gold|brass|ochre|terracotta|rust|taupe|khaki|olive|cobalt|coral|burgundy|maroon|amber|lilac|indigo|charcoal|slate|greige|ivory|off-white|white|black|silver|bronze|copper)"
)
_PALETTE_COLOR_WORDS = re.compile(
    rf"(?<![A-Za-z]){_PALETTE_COLOR_TOKEN}(?:-[A-Za-z]+)?(?![A-Za-z])",
    re.IGNORECASE,
)
_PALETTE_HEX = re.compile(r"#[0-9a-fA-F]{3,8}")
_PALETTE_COLOR_ANNOTATION = re.compile(
    rf"\((?=[^)]*(?:#[0-9a-fA-F]{{3,8}}\b|\b{_PALETTE_COLOR_TOKEN}(?:-[A-Za-z]+)?\b))[^)]*\)",
    re.IGNORECASE,
)
_PALETTE_MATERIAL_PHRASE = re.compile(
    r"\b(?:warm|cool|light|dark|pale|natural|honey|espresso|white|black|gray|grey|red|"
    r"blue|green|gold|silver|brass|charcoal|slate)\s+(?:oak|wood|walnut|maple|"
    r"cherry|ash|pine|birch|metal|hardware)\b",
    re.IGNORECASE,
)
def _sanitize_role_image_direction(value: Any) -> str:
    """Keep composition intent while routing all staging color to the child palette."""
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return text
    # Color parentheticals are planner-side annotations, not composition
    # instructions. Remove the whole annotation before stripping color words;
    # otherwise the old sanitizer leaves malformed fragments such as "()" or
    # "deep ()", which can be interpreted as an image-model instruction.
    text = _PALETTE_COLOR_ANNOTATION.sub("", text)
    text = _PALETTE_MATERIAL_PHRASE.sub("", text)
    text = _PALETTE_HEX.sub("", text)
    text = _PALETTE_COLOR_WORDS.sub("", text)
    text = re.sub(r"\s*-\s*toned\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*\)|\[\s*\]|\{\s*\}", "", text)
    text = re.sub(r"(?<=\w)-(?=\s|[,.;:])", "", text)
    text = re.sub(r"\s*-\s*(?=[,.;:])", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"([,;:])\s*([,;:])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return " ".join(text.split()).strip(" ;,()[]{}")


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
    "scene": {"shopping_purpose", "image_direction"},
    "func": {"shopping_purpose", "image_direction", "func_story_contract"},
    "size": {"shopping_purpose", "image_direction", "measurement_authority", "invent_text"},
}
# Every non-main brief must carry a positive per-image direction.  Making it
# optional let flash-class planners omit it silently, so func/size prompts
# reached the image model with family art direction as their only design
# input.  Absence is now a compile error; the planner repair loop reports the
# missing field and gets one bounded chance to fix it.
_BRIEF_OPTIONAL_FIELDS = {"scene": set(), "func": set(), "size": set()}
# A complete art-direction field can legitimately be longer than a short
# label.  Keep a bounded contract, but do not reject a coherent provider
# response merely because it explains the physical design in detail.
_ART_DIRECTION_FIELD_MAX = 2200
_SOURCE_BRIEF_FIELD_MAX = 700
_SHOPPING_PURPOSE_MAX = 320
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])(?:\d+(?:\.\d+)?|\.\d+)(?![A-Za-z0-9])")
_COUNT_COMPONENT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<number>\d+(?:\.\d+)?)\s+"
    r"(?P<descriptor>(?:[A-Za-z][A-Za-z-]*\s+){0,3})"
    r"(?P<component>slats?|drawers?|shelves?|rails?|doors?|wheels?|"
    r"compartments?|tiers?|hooks?|baskets?|bins?|racks?)\b",
    re.I,
)
_MEASUREMENT_RE = re.compile(
    r"(?<![A-Za-z0-9])\d+(?:\.\d+)?\s*"
    r"(?:in(?:ch(?:es)?)?|ft|feet|foot|cm|mm|lb|lbs|pounds?|kg)(?![A-Za-z])",
    re.I,
)
_OPPOSING_CLAIM_TERMS = ({"floor", "wall"}, {"left", "right"}, {"top", "bottom"}, {"open", "closed"})
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
_GENERIC_FUNC_LABELS = {
    "safe and secure design",
    "classic design",
    "key features",
    "storage features",
    "bed frame features",
    "premium cabinet material",
    "cabinet design details",
    "generous storage space",
    "organized living space",
    "ample underbed storage",
    "stable structure",
    "space saving storage",
    "easy access storage",
}


def compile_visual_design_kit_response(
    raw: Any,
    *,
    source_manifest: list[dict[str, Any]],
    category_id: str = "",
) -> dict[str, Any]:
    """Bind Gemini's aesthetic decision without granting it product-fact authority."""
    if not isinstance(raw, dict):
        raise VisualDesignKitCompileError("planner response must be an object")
    art_direction = _compile_art_direction(raw.get("family_art_direction"))
    raw_briefs = raw.get("source_briefs")
    if not isinstance(raw_briefs, list):
        raise VisualDesignKitCompileError("source_briefs must be a list")
    expected_ids = {
        str(source["source_id"])
        for source in source_manifest
        if source.get("role") in {"scene", "func", "size"}
    }
    raw_by_source: dict[str, dict[str, Any]] = {}
    for row in raw_briefs:
        if not isinstance(row, dict):
            continue
        source_id = str(row.get("source_id") or "")
        if source_id in raw_by_source:
            raise VisualDesignKitCompileError(f"source_briefs duplicate source_id: {source_id}")
        raw_by_source[source_id] = row
    if expected_ids and not expected_ids.intersection(raw_by_source):
        raise VisualDesignKitCompileError("source_briefs contain no known source_id")
    product_claims = _global_product_claims(source_manifest)
    briefs = []
    for source in source_manifest:
        if source.get("role") not in {"scene", "func", "size"}:
            continue
        draft = raw_by_source.get(str(source["source_id"])) or {}
        try:
            briefs.append(_compile_source_brief(
                source,
                draft,
                product_claims=product_claims,
                category_id=category_id,
            ))
        except VisualDesignKitCompileError:
            # A malformed provider-written func story is a responsibility
            # failure for this role.  Do not silently downgrade it to a
            # visual-only task: that path produced incomplete, generic
            # information graphics while reporting a successful brief.
            raise
    result = {
        "family_art_direction": art_direction,
        "source_briefs": briefs,
    }
    validate_compiled_visual_design_kit(
        result, source_manifest=source_manifest, category_id=category_id,
    )
    return result


def validate_compiled_visual_design_kit(
    data: Any,
    *,
    source_manifest: list[dict[str, Any]],
    category_id: str = "",
) -> None:
    if not isinstance(data, dict) or set(data) != {"family_art_direction", "source_briefs"}:
        raise VisualDesignKitCompileError("planner response fields do not match the current VisualDesignKit contract")
    _validate_art_direction(data["family_art_direction"])
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
    source: dict[str, Any],
    draft: dict[str, Any],
    *,
    product_claims: list[dict[str, Any]] | None = None,
    category_id: str = "",
) -> dict[str, Any]:
    role = str(source.get("role") or "")
    result: dict[str, Any] = {
        "source_id": str(source["source_id"]),
        "source_intent_revision_id": str(source["input_revision_id"]),
        "source_sha256": str(source["source_sha256"]),
        "role": role,
        "shopping_purpose": (
            _required_text(
                source.get("shopping_intent"),
                f"source_manifest[{source['source_id']}].shopping_intent",
                _SHOPPING_PURPOSE_MAX,
            )
            if role == "scene"
            else _source_brief_text(
                draft.get("shopping_purpose"),
                f"source_briefs[{source['source_id']}].shopping_purpose",
                _SHOPPING_PURPOSE_MAX,
                category_id=category_id,
            )
        ),
    }
    if role in {"scene", "func", "size"}:
        result["image_direction"] = _source_brief_text(
            draft.get("image_direction"),
            f"source_briefs[{source['source_id']}].image_direction",
            _SOURCE_BRIEF_FIELD_MAX,
            category_id=category_id,
        )
    if role == "func":
        result["func_story_contract"] = _compile_func_story(
            source,
            draft.get("func_story"),
            product_claims=product_claims,
        )
    elif role == "size":
        result.update({
            "shopping_purpose": "Present the complete source measurement diagram without changing any measurement relationship.",
            "measurement_authority": "complete_source_measurement_diagram",
            "invent_text": False,
        })
    return result


def _compile_func_story(
    source: dict[str, Any],
    value: Any,
    *,
    product_claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    available = _available_claims(source, product_claims)
    if not available:
        raise VisualDesignKitCompileError(
            f"source_briefs[{source['source_id']}] has no evidence-bound func claims"
        )
    # The planner chooses the visual treatment; it is not the authority for
    # renderable product copy. If it omits or corrupts the optional story
    # object, derive the short title from immutable evidence in this compiler
    # instead of failing the entire child or spending another model call.
    provider_story = value if isinstance(value, dict) else {}
    title_row = provider_story.get("title")
    label_rows = provider_story.get("labels")
    if not isinstance(label_rows, list):
        label_rows = []
    try:
        title = _bind_func_story_text(title_row, available)
    except VisualDesignKitCompileError:
        title = _bind_func_story_text(_fallback_func_story(available)["title"], available)
    if not func_story_title_is_specific(title["text"]):
        title = _bind_func_story_text(_fallback_func_story(available)["title"], available)
    labels: list[str] = []
    bindings = [title]
    seen_text = {title["text"].casefold()}
    # Extra labels are optional provider output. Freeze the first two in
    # planner/evidence order so information density stays stable without
    # turning an optional label into a blocking provider error.
    label_rows = label_rows[:2]
    for row in label_rows:
        # Providers sometimes bind a label to another source's OCR claim.
        # That claim must not become renderable copy, but one bad optional
        # label must not discard an otherwise valid child.  The title remains
        # a hard gate; unsupported labels are omitted exactly as the prompt
        # contract requires.
        try:
            bound = _bind_func_story_text(row, available)
        except VisualDesignKitCompileError:
            continue
        if _is_generic_func_label(bound["text"]):
            # Weak labels must not become renderable copy. Omit them without
            # blocking the child; remaining evidence-bound text is retained.
            continue
        if bound["text"].casefold() in seen_text:
            continue
        seen_text.add(bound["text"].casefold())
        labels.append(bound["text"])
        bindings.append(bound)
    numeric_label = _numeric_component_label(source, available)
    if numeric_label and not any(
        _same_numeric_component(numeric_label["text"], label)
        for label in [title["text"], *labels]
    ):
        # Counted components are stronger evidence than an optional second
        # marketing label. Keep the first planner label and use the remaining
        # slot for the deterministic, source-bound count when needed.
        if len(labels) >= 2:
            labels = labels[:1]
            bindings = bindings[:2]
        labels.append(numeric_label["text"])
        bindings.append(numeric_label)
    return {
        "mode": "source_claims",
        "title": title["text"],
        "labels": labels,
        "bindings": bindings,
    }


def _fallback_func_story(available: dict[str, str]) -> dict[str, Any]:
    """Recover a missing optional planner story from immutable evidence.

    A provider may omit one Func brief even though the child has valid product
    evidence. Use only the short fact heading before a structured claim's
    colon; no new fact or marketing promise is invented. If no specific
    evidence heading exists, the normal contract error remains fail-closed.
    """
    for evidence_id, claim in available.items():
        heading = str(claim or "").split(":", 1)[0].strip(" -\u2013\u2014;,.\t")
        words = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", heading)
        text = " ".join(words[:6])
        if func_story_title_is_specific(text):
            return {
                "title": {"evidence_ids": [evidence_id], "text": text},
                "labels": [],
            }
    raise VisualDesignKitCompileError("func story has no specific evidence-bound fallback")


def _bind_func_story_text(value: Any, available: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"evidence_ids", "text"}:
        raise VisualDesignKitCompileError("func story copy is malformed")
    evidence_ids = value.get("evidence_ids")
    if not isinstance(evidence_ids, list):
        raise VisualDesignKitCompileError("func story copy evidence_ids are malformed")
    evidence_ids = [str(item or "").strip() for item in evidence_ids]
    if not evidence_ids or len(evidence_ids) != len(set(evidence_ids)) or any(item not in available for item in evidence_ids):
        raise VisualDesignKitCompileError("func story copy is not evidence-bound")
    text = _buyer_copy(value.get("text"))
    evidence_texts = [available[item] for item in evidence_ids]
    evidence_text = " ".join(evidence_texts)
    if (
        not _buyer_label(text)
        or not _numeric_tokens(text).issubset(_numeric_tokens(evidence_text))
        or any(
            _claims_contradict(_claim_terms(text), _claim_terms(item))
            for item in evidence_texts
        )
    ):
        raise VisualDesignKitCompileError("func story copy is not evidence-bound")
    return {"evidence_ids": evidence_ids, "text": text}


def _buyer_copy(value: Any) -> str:
    text = _optional_text(value, 70)
    text = " ".join(text.split())
    return text.strip(" -–—,;:")


def _is_generic_func_label(value: Any) -> bool:
    normalized = " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))
    return normalized in _GENERIC_FUNC_LABELS


def _numeric_component_label(
    source: dict[str, Any],
    available: dict[str, str],
) -> dict[str, str] | None:
    """Promote an explicit component count without promoting measurements.

    The source claim supplies the component concept (for example ``Slats``);
    the product fact supplies the count.  Requiring both prevents unrelated
    capacity, dimension, and marketing numbers from becoming func copy.
    """
    source_claim_texts = [claim["text"] for claim in cleaned_source_claims(source)]
    # ``Slats`` is a valid source-visible concept even though the general
    # claim cleaner intentionally rejects one-word OCR fragments. Restrict
    # this exception to known physical component nouns rather than relaxing
    # the shared OCR contract.
    for claim in source.get("claims") or []:
        if isinstance(claim, dict) and not has_bad_encoding(str(claim.get("text") or "")):
            source_claim_texts.append(str(claim.get("text") or ""))
    source_components = {
        match.casefold().rstrip("s")
        for claim in source_claim_texts
        for match in re.findall(
            r"\b(?:slats?|drawers?|shelves?|rails?|doors?|wheels?|"
            r"compartments?|tiers?|hooks?|baskets?|bins?|racks?)\b",
            claim,
            re.I,
        )
    }
    if not source_components:
        return None
    for evidence_id, evidence_text in available.items():
        for match in _COUNT_COMPONENT_RE.finditer(evidence_text):
            component = match.group("component").casefold().rstrip("s")
            if component not in source_components:
                continue
            words = [
                match.group("number"),
                *match.group("descriptor").split(),
                match.group("component"),
            ]
            text = " ".join(words).strip()
            if _buyer_label(text):
                return {"evidence_ids": [evidence_id], "text": text}
    return None


def _same_numeric_component(left: Any, right: Any) -> bool:
    left_numbers = _numeric_tokens(left)
    right_numbers = _numeric_tokens(right)
    if not left_numbers or not left_numbers.issubset(right_numbers):
        return False
    components = {
        match.casefold().rstrip("s")
        for match in re.findall(
            r"\b(?:slats?|drawers?|shelves?|rails?|doors?|wheels?|"
            r"compartments?|tiers?|hooks?|baskets?|bins?|racks?)\b",
            str(left),
            re.I,
        )
    }
    return bool(components & {
        match.casefold().rstrip("s")
        for match in re.findall(
            r"\b(?:slats?|drawers?|shelves?|rails?|doors?|wheels?|"
            r"compartments?|tiers?|hooks?|baskets?|bins?|racks?)\b",
            str(right),
            re.I,
        )
    })


def _validate_art_direction(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != _ART_DIRECTION_FIELDS:
        raise VisualDesignKitCompileError("family_art_direction fields do not match the V10 contract")
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
        if row.get("role") in {"scene", "func", "size"}
    }
    if not isinstance(briefs, list) or len(briefs) != len(expected):
        raise VisualDesignKitCompileError(
            "source_briefs do not cover every non-main source exactly once"
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
        required_fields = _BRIEF_BINDING_FIELDS | _BRIEF_ROLE_FIELDS[role]
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
    brief: dict[str, Any],
    source: dict[str, Any],
    index: int,
    *,
    product_claims: list[dict[str, Any]] | None = None,
) -> None:
    available = _available_claims(source, product_claims)
    story = brief.get("func_story_contract")
    if not isinstance(story, dict) or set(story) != {
        "mode", "title", "labels", "bindings",
    }:
        raise VisualDesignKitCompileError(
            f"source_briefs[{index}] has no canonical FuncStoryContract"
        )
    if story.get("mode") != "source_claims":
        raise VisualDesignKitCompileError(
            f"source_briefs[{index}] has no canonical FuncStoryContract"
        )
    title = str(story.get("title") or "")
    labels = story.get("labels")
    bindings = story.get("bindings")
    if not isinstance(labels, list) or len(labels) > 3 or not isinstance(bindings, list):
        raise VisualDesignKitCompileError(
            f"source_briefs[{index}] has malformed FuncStoryContract labels"
        )
    strings = [title, *[str(value or "") for value in labels]]
    if len(bindings) != len(strings) or len(strings) != len(set(value.casefold() for value in strings)):
        raise VisualDesignKitCompileError(
            f"source_briefs[{index}] has inconsistent FuncStoryContract bindings"
        )
    for copy_index, item in enumerate(bindings):
        if not isinstance(item, dict) or set(item) != {"evidence_ids", "text"}:
            raise VisualDesignKitCompileError(
                f"source_briefs[{index}].func_story_contract.bindings[{copy_index}] is malformed"
            )
        evidence_ids = item.get("evidence_ids")
        if not isinstance(evidence_ids, list):
            raise VisualDesignKitCompileError(
                f"source_briefs[{index}].func_story_contract.bindings[{copy_index}] is malformed"
            )
        evidence_ids = [str(value or "").strip() for value in evidence_ids]
        text = str(item.get("text") or "")
        evidence_texts = [available[value] for value in evidence_ids if value in available]
        evidence_text = " ".join(evidence_texts)
        if (
            not evidence_ids
            or len(evidence_ids) != len(set(evidence_ids))
            or any(value not in available for value in evidence_ids)
            or text != strings[copy_index]
            or not _buyer_label(text)
            or not _numeric_tokens(text).issubset(_numeric_tokens(evidence_text))
            or any(
                _claims_contradict(_claim_terms(text), _claim_terms(item))
                for item in evidence_texts
            )
        ):
            raise VisualDesignKitCompileError(
                f"source_briefs[{index}] has unbound or malformed FuncStoryContract copy"
            )
    if not func_story_title_is_specific(title):
        raise VisualDesignKitCompileError(
            f"source_briefs[{index}] func story title is generic"
        )
    used_numbers = _numeric_tokens({
        "shopping_purpose": brief["shopping_purpose"],
        "func_story_contract": story,
    })
    authorized = _numeric_tokens(list(available.values()))
    if not used_numbers.issubset(authorized):
        raise VisualDesignKitCompileError(
            f"source_briefs[{index}] contains unsupported numeric func copy"
        )


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
    """Return trusted product facts unless source evidence explicitly contradicts them.

    Sparse OCR is not a fact authority. Requiring every ProductFamily fact to
    repeat OCR words discarded valid claims such as an adjustable shelf when a
    source image only exposed the word ``Storage``.
    """
    source_concepts = [_claim_terms(row.get("text")) for row in cleaned_source_claims(source)]
    return [
        row for row in source.get("product_claims") or []
        if isinstance(row, dict)
        and not any(
            _claims_contradict(_claim_terms(row.get("text")), evidence)
            for evidence in source_concepts
        )
    ]


def _claims_contradict(left: set[str], right: set[str]) -> bool:
    return any(
        bool(
            left & pair
            and right & pair
            and right & pair != pair
            and left & pair != right & pair
        )
        for pair in _OPPOSING_CLAIM_TERMS
    )


def _claim_terms(value: Any) -> set[str]:
    """Return only terms needed to detect explicit mutually-exclusive claims.

    A valid evidence identifier authorizes natural buyer-copy paraphrases.  We
    intentionally do not reimplement semantic similarity with hand-maintained
    stemming or synonym rules here.
    """
    return set(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _buyer_label(value: Any) -> bool:
    text = _optional_text(value, 70)
    words = re.findall(r"[A-Za-z0-9]+(?:[-'&][A-Za-z0-9]+)?", text)
    return bool(2 <= len(words) <= 6 and not has_bad_encoding(text))


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


def _numeric_tokens(value: Any) -> set[str]:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return {match.group(0).lstrip("0") or "0" for match in _NUMBER_RE.finditer(serialized)}
