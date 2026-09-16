from __future__ import annotations

import re
from typing import Any

from .visual_semantics import CLAIM_REVIEW_POLICY, claim_key
from .image_reference_context import evidence_view_catalog, view_identity
from .text_evidence import has_bad_encoding, us_measurement_text


class VisualDesignKitCompileError(ValueError):
    def __init__(self, message: str, *, failure_owner: str = 'brief'):
        super().__init__(message)
        self.failure_owner = failure_owner


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
            or not words
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
DESIGN_FIELD_SCHEMAS = {
    "typography_direction": {
        "font_family": "one chosen font family, not alternatives",
        "title_style": "weight, case and hierarchy relative to the product",
        "body_style": "weight, spacing and line breaks for readable labels",
        "numeric_style": "measurement legibility and spacing; no literal values",
    },
    "graphic_direction": {
        "text_color": "one flat hex for ALL titles, captions and measurements; not gradients, outlines or shadows",
        "line_color": "one hex for leaders and measurement arrows",
        "icon_color": "one hex for unbacked icon strokes",
        "backing_color": "one hex for local backing when needed",
        "backed_symbol_color": "one contrasting hex for symbols on backing",
        "component_style": "choose stroke weight and a consistent meaningful icon family; text_placement owns label backgrounds, not this field",
    },
}
IMAGE_DIRECTION_SCHEMA = {
    "visual_goal": "one buyer-facing communication goal; not display copy",
    "creative_brief": "task-specific focal treatment and composition; do not repeat design_transfer or shared styling",
    "evidence_usage": [{"source_id": "source_00", "view_id": "view_01", "usage": "display", "covered_by": []}],
    "design_transfer": [{"reference_id": "approved ID", "inherit": "defining features used here", "adapt": "change and reason, or retain as approved"}],
    "layout": [{"source_id": "selected source_id", "view_id": "displayed view_id", "target_region": [0.1, 0.1, 0.9, 0.9]}],
    "text_placement": [{"text_ref": "title|label:0|measurements", "target_region": [0.1, 0.02, 0.9, 0.1], "backing": "none|local; choose local only for a specific label over busy pixels, not a capsule row"}],
    "scene_objects": ["target group.component from this child's palette; select only components used in this image, never source-object IDs"],
    "environment_mode": "designed_environment|graphic_canvas|source_setting; choose the target setting; source_setting retains only necessary installation relationships",
}
_BRIEF_BINDING_FIELDS = {
    "source_id",
    "source_intent_revision_id",
    "source_sha256",
    "role",
}
_BRIEF_ROLE_FIELDS = {
    "main": {"image_direction"},
    "scene": {"image_direction"},
    "func": {"image_direction", "display_copy_contract", "claim_reviews"},
    "size": {"image_direction", "measurement_authority", "display_copy_contract", "claim_reviews"},
}
# A complete art-direction field can legitimately be longer than a short
# label.  Keep a bounded contract, but do not reject a coherent provider
# response merely because it explains the physical design in detail.
_ART_DIRECTION_FIELD_MAX = 2200
_RENDERABLE_COPY_INSTRUCTION_RE = re.compile(
    r"(?:^|[\r\n;])\s*(?:text|title|caption|slogan|headline|label|copy)\s*:\s*"
    r"|\b(?:render|write|print|spell|include|display|show|place)\s+(?:the\s+)?(?:following\s+)?"
    r"(?:text|title|caption|slogan|headline|label|words|copy)\s*(?:[:=]|[\"\u201c])"
    r"|\b(?:set|name|call)\s+(?:the\s+)?(?:visible\s+)?"
    r"(?:text|title|caption|slogan|headline|label|copy)\s+(?:to|as|reading|saying)\b"
    r"|\b(?:text|title|caption|slogan|headline|label|copy)\b[^.\r\n]{0,48}"
    r"\b(?:reads?|reading|says?|saying|worded\s+as)\b",
    re.I,
)


def compile_visual_design_kit_response(
    raw: Any, *, source_manifest: list[dict[str, Any]], category_id: str = "",
    claim_reviews: dict[str, dict[str, Any]] | None = None,
    design_references: list[dict[str, Any]] | None = None,
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
        review = {}
        try:
            validate_source_brief_draft(draft, source, art_direction, source_manifest, category_id)
            brief = _compile_source_brief(
                source, draft, product_claims=product_claims,
                category_id=category_id, claim_reviews=claim_reviews or {}, source_manifest=source_manifest,
            )
            request = design_binding_request(draft, art_direction, source=source, source_manifest=source_manifest, design_references=design_references)
            review = (claim_reviews or {}).get(request["key"], {})
            brief["design_review"] = review
            _validate_physical_review(request, review)
            approved = {row["source_id"]: row for row in design_references or []}
            if any(row["reference_id"] not in approved or source["role"] not in approved[row["reference_id"]]["roles"]
                   for row in brief["image_direction"]["design_transfer"]):
                raise VisualDesignKitCompileError("Selected design reference is not approved for this role")
            brief["status"] = "ready"
            _validate_briefs([brief], [source], product_claims=product_claims, category_id=category_id, source_manifest=source_manifest)
        except ValueError as exc:
            brief = {
                "source_id": source["source_id"], "source_sha256": source["source_sha256"],
                "source_intent_revision_id": source["input_revision_id"], "role": source["role"],
                "status": "pending", "error": str(exc), "draft": draft,
                "failure_owner": getattr(exc, 'failure_owner', 'brief'),
                "design_review": review,
            }
        briefs.append(brief)
    result = {"family_art_direction": art_direction, "source_briefs": briefs}
    validate_compiled_visual_design_kit(result, source_manifest=source_manifest, category_id=category_id, design_references=design_references)
    return result


def validate_source_brief_draft(draft: dict[str, Any], source: dict[str, Any], art: dict[str, Any],
                              sources: list[dict[str, Any]], category_id: str) -> None:
    """Local contract used before paid review and by final compilation."""
    errors = []
    if set(draft) - {'source_id', 'image_direction', 'display_copy'}:
        errors.append('Brief contains fields outside the current response schema')
    try:
        direction = _image_direction(draft.get('image_direction'), source, category_id=category_id, source_manifest=sources)
        palette = art['palette_direction']
        references = {group + '.' + component for group, parts in palette.items() for component in parts}
        if not set(direction['scene_objects']) <= references:
            errors.append('Role scene_objects must select defined target components')
    except ValueError as exc:
        errors.append(str(exc))
    if source['role'] in {'func', 'size'}:
        story = draft.get('display_copy')
        if not isinstance(story, dict) or set(story) != {'title', 'labels'} or not isinstance(story.get('labels'), list):
            errors.append('display copy needs an explicit title choice and label list')
        else:
            available = _available_claims(source, _global_product_claims(sources))
            for row in ([story['title']] if story['title'] is not None else []) + story['labels']:
                try:
                    _copy_binding(row, available)
                except ValueError as exc:
                    errors.append(str(exc))
    if errors:
        raise VisualDesignKitCompileError('; '.join(errors))


def claim_review_requests(raw: Any, source_manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect scoped claims for the independent reviewer before compilation."""
    sources = {source["source_id"]: source for source in source_manifest}
    product_claims = _global_product_claims(source_manifest)
    requests = {}
    for brief in raw.get("source_briefs") or []:
        source = sources.get(brief.get("source_id")) if isinstance(brief, dict) else None
        if not source or source["role"] not in {"func", "size"}:
            continue
        available = _available_claims(source, product_claims)
        story = brief.get("display_copy") or {}
        if not isinstance(story, dict):
            continue
        labels = story.get("labels") if isinstance(story.get("labels"), list) else []
        for value in [story.get("title"), *labels]:
            try:
                bound = _copy_binding(value, available)
            except VisualDesignKitCompileError:
                continue
            evidence = {key: available[key] for key in bound["evidence_ids"]}
            if not any(key.startswith('physical:') for key in evidence) and bound["text"] in [us_measurement_text(text) for text in evidence.values()]:
                continue
            key = claim_key(bound["text"], evidence)
            requests[key] = {"kind": "product_claim", "key": key, "source_id": source['source_id'],
                             "proposed_text": bound["text"], "evidence": evidence}
    return list(requests.values())


def design_binding_request(brief: dict[str, Any], art: dict[str, Any], *, source: dict[str, Any], source_manifest: list[dict[str, Any]] = (), design_references: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    direction = brief.get("image_direction") or {}
    if (isinstance(direction, dict) and isinstance(direction.get('text_placement'), list)
            and all(isinstance(row, dict) and isinstance(row.get('text_ref'), str) for row in direction['text_placement'])):
        direction = _project_text_placement(direction, brief, source)
    text = {key: direction.get(key) for key in ("visual_goal", "creative_brief", "design_transfer", "evidence_usage", "layout", "text_placement", "environment_mode", "scene_objects")} if isinstance(direction, dict) else {}
    text["role"] = source['role']
    required_facts = {
        'claims': [{key: row.get(key) for key in ('evidence_id', 'text')} for row in source.get('claims', [])],
        'measurements': [{key: row.get(key) for key in ('text', 'source_label', 'axis_hint', 'view_id', 'source_endpoints')}
                         for row in source.get('measurements', [])],
    } if source['role'] in {'func', 'size'} else {}
    catalog = evidence_view_catalog(list(source_manifest) or [source])
    usage = text.get('evidence_usage')
    usage = [row for row in usage if isinstance(row, dict) and all(isinstance(row.get(k), str) for k in ('source_id', 'view_id'))] if isinstance(usage, list) else []
    selected = {view_identity(row) for row in usage}
    selected.update(key for key, (owner, _) in catalog.items() if owner['source_id'] == source['source_id'])
    evidence = [{'source_id': owner['source_id'], 'source_sha256': owner['source_sha256'],
                 'source_revision': owner['input_revision_id'], 'view': view,
                 'required_annotation_regions': [m['source_region'] for m in owner.get('measurements', []) if m['view_id'] == view['view_id']],
                 'crops': [crop for crop in owner.get('crop_provenance', []) if crop['view_id'] == view['view_id']]}
                for key, (owner, view) in catalog.items() if key in selected]
    risks = ['target_consistency:' + source['source_id'], *[
        'coverage_transfer:' + view_identity(row) for row in usage if row.get('usage') == 'integrated']]
    if source['role'] in {'func', 'size'}:
        risks.append('product_coverage:' + source['source_id'])
    selected = {row.get('reference_id') for row in text.get('design_transfer') or [] if isinstance(row, dict)}
    scopes = [{**{key: row[key] for key in ('source_id', 'sha256', 'purpose', 'roles')},
               'approval_boundary': row['visual_review']['transfer_scope']}
              for row in design_references or [] if row['source_id'] in selected]
    risks.extend('reference_transfer:' + row['source_id'] for row in scopes)
    from .status import input_revision_id
    key = input_revision_id({"policy": CLAIM_REVIEW_POLICY, "shared_design": _compile_art_direction(art), "role_design": text,
        'source_revision': source['input_revision_id'], 'source_sha256': source['source_sha256'],
        'selected_evidence': evidence, 'required_facts': required_facts,
        'crop_policy': 'floor-ceil-original-png-v1', 'reference_scopes': scopes})
    return {"kind": "design_binding", "key": key, "source_id": brief.get("source_id"), "role_design": text,
            "reference_scopes": scopes, "physical_operations": sorted(set(risks)), "selected_evidence": evidence, 'required_facts': required_facts}


def _validate_physical_review(request: dict[str, Any], review: dict[str, Any]) -> None:
    findings = review.get('findings', [])
    conflicts = [row for row in findings if row.get('status') == 'contradiction']
    if conflicts:
        source_error = all(str(row.get('operation', '')).startswith('source_product:') for row in conflicts)
        raise VisualDesignKitCompileError('planning evidence conflict: ' + '; '.join(str(row['reason']) for row in conflicts),
                                         failure_owner='observation' if source_error else 'brief')
    supported = {row.get('operation') for row in findings if row.get('status') == 'supported'}
    missing = set(request['physical_operations']) - supported
    if missing:
        raise VisualDesignKitCompileError('Planning operation needs bound review: ' + ', '.join(sorted(missing)), failure_owner='review')


def validate_compiled_visual_design_kit(
    data: Any,
    *,
    source_manifest: list[dict[str, Any]],
    category_id: str = "",
    design_references: list[dict[str, Any]] | None = None,
) -> None:
    if not isinstance(data, dict) or set(data) != {"family_art_direction", "source_briefs"}:
        raise VisualDesignKitCompileError("planner response fields do not match the current VisualDesignKit contract")
    _validate_art_direction(data["family_art_direction"])
    sources = {row['source_id']: row for row in source_manifest}
    for brief in data["source_briefs"]:
        if brief.get("status") == "ready":
            review = brief.get("design_review")
            if not isinstance(review, dict):
                raise VisualDesignKitCompileError("Design review must be a bound record or an explicit empty record")
            request = design_binding_request(brief, data["family_art_direction"], source=sources[brief['source_id']], source_manifest=source_manifest, design_references=design_references)
            _validate_physical_review(request, review)
            if review and (review.get("key") != request["key"]
                           or review.get("policy") != CLAIM_REVIEW_POLICY
                           or not review.get("response_sha256")):
                raise VisualDesignKitCompileError("Design review no longer matches this child's design")
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
        for field in _ART_DIRECTION_FIELDS - {"negative_visuals", "palette_direction", *DESIGN_FIELD_SCHEMAS}
    }
    for field, schema in DESIGN_FIELD_SCHEMAS.items():
        result[field] = _design_mapping(value.get(field), schema, field)
    palette = value.get("palette_direction")
    if not isinstance(palette, dict) or not palette:
        raise VisualDesignKitCompileError("palette_direction needs named groups of physical design components")
    result['palette_direction'] = {}
    for group, parts in palette.items():
        if (not isinstance(group, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', group)
                or not isinstance(parts, dict) or not parts
                or any(not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', key) for key in parts)):
            raise VisualDesignKitCompileError('Palette groups need semantic component IDs, not an undivided color string')
        result['palette_direction'][group] = _design_mapping(parts, parts, 'palette_direction.' + group)
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
    source_manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    role = str(source["role"])
    result = {
        "source_id": str(source["source_id"]),
        "source_intent_revision_id": str(source["input_revision_id"]),
        "source_sha256": str(source["source_sha256"]),
        "role": role,
        "image_direction": _project_text_placement(
            _image_direction(draft.get("image_direction"), source, category_id=category_id, source_manifest=source_manifest), draft, source),
    }
    if role in {"func", "size"}:
        result["display_copy_contract"] = _compile_display_copy(source, draft.get("display_copy"), product_claims=product_claims, claim_reviews=claim_reviews)
        available = _available_claims(source, product_claims)
        used_keys = {claim_key(row["text"], {key: available[key] for key in row["evidence_ids"]})
                    for row in result["display_copy_contract"]["bindings"]}
        result["claim_reviews"] = {key: value for key, value in claim_reviews.items() if key in used_keys}
    if role == "size":
        result["measurement_authority"] = "located_source_measurements"
    return result


def _project_text_placement(direction: dict[str, Any], brief: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    # Review and execution use the same projection; unused copy has no placement.
    return {**direction, 'text_placement': [row for row in direction['text_placement']
            if row['text_ref'] in _text_refs(brief, source)]}


def _text_refs(brief: dict[str, Any], source: dict[str, Any]) -> set[str]:
    story = brief.get("display_copy_contract", brief.get('display_copy')) or {}
    if not isinstance(story, dict):
        story = {}
    refs = {"title"} if story.get("title") else set()
    refs.update(f"label:{i}" for i, _ in enumerate(story.get("labels") or []))
    if source["role"] == "size" or source.get("measurements"):
        refs.add("measurements")
    return refs


def _compile_display_copy(
    source: dict[str, Any], value: Any, *,
    product_claims: list[dict[str, Any]] | None = None,
    claim_reviews: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    available = _available_claims(source, product_claims)
    if not isinstance(value, dict) or set(value) != {"title", "labels"} or not isinstance(value.get("labels"), list):
        raise VisualDesignKitCompileError("display copy needs an explicit title choice and label list")
    title = value["title"]
    bindings, errors, owners = [], [], []
    entries = ([("title", title)] if title is not None else []) + [
        (f"label:{i}", row) for i, row in enumerate(value["labels"])]
    for location, row in entries:
        try:
            bindings.append(_bind_display_text(row, available, claim_reviews=claim_reviews))
        except VisualDesignKitCompileError as exc:
            errors.append(f"{location}: {exc}")
            owners.append(exc.failure_owner)
    if errors:
        raise VisualDesignKitCompileError("; ".join(errors), failure_owner='review' if set(owners) == {'review'} else 'brief')
    strings = [row["text"] for row in bindings]
    if len(strings) != len(set(text.casefold() for text in strings)) or sum(map(len, strings)) > 1200:
        raise VisualDesignKitCompileError("display copy is duplicated or exceeds its content budget")
    return {"mode": "source_claims", "title": strings[0] if title is not None else "",
            "labels": strings[1:] if title is not None else strings, "bindings": bindings}


def _copy_binding(value: Any, available: dict[str, str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"evidence_ids", "text"}:
        raise VisualDesignKitCompileError("display copy copy is malformed")
    ids = value.get("evidence_ids")
    text = value.get("text")
    if (
        not isinstance(ids, list) or not ids or any(not isinstance(key, str) or key not in available for key in ids)
        or len(ids) != len(set(ids)) or not isinstance(text, str) or not text.strip()
        or len(text) > 240 or has_bad_encoding(text)
    ):
        raise VisualDesignKitCompileError("display copy copy has invalid text or evidence scope")
    return {"evidence_ids": list(ids), "text": us_measurement_text(text)}


def _bind_display_text(
    value: Any, available: dict[str, str], *,
    claim_reviews: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    bound = _copy_binding(value, available)
    evidence = {key: available[key] for key in bound["evidence_ids"]}
    if not any(key.startswith('physical:') for key in evidence) and bound["text"] in [us_measurement_text(text) for text in evidence.values()]:
        return bound
    key = claim_key(bound["text"], evidence)
    review = (claim_reviews or {}).get(key) or {}
    if review.get("status") != "supported" or review.get("policy") != CLAIM_REVIEW_POLICY or review.get("key") != key or not review.get("response_sha256"):
        reason = str(review.get('reason') or bound['text'])
        owner = 'review' if not review or reason.startswith('Planning review unavailable:') else 'brief'
        raise VisualDesignKitCompileError("display claim requires independent evidence review: " + reason, failure_owner=owner)
    return bound


def _validate_art_direction(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != _ART_DIRECTION_FIELDS:
        raise VisualDesignKitCompileError("family_art_direction fields do not match the V11 contract")
    compiled = _compile_art_direction(value)
    if compiled != value:
        raise VisualDesignKitCompileError("art direction is not canonical")
    for field in _ART_DIRECTION_FIELDS - {"negative_visuals", "palette_direction", *DESIGN_FIELD_SCHEMAS}:
        _valid_text(
            value[field],
            f"family_art_direction.{field}",
            5,
            _ART_DIRECTION_FIELD_MAX,
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
    source_manifest: list[dict[str, Any]] | None = None,
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
            if (set(brief) != _BRIEF_BINDING_FIELDS | {"status", "error", "draft", "failure_owner", "design_review"}
                    or not isinstance(brief['design_review'], dict)
                    or brief['failure_owner'] not in {'observation', 'brief', 'review'} or not brief.get("error") or not isinstance(brief.get("draft"), dict)):
                raise VisualDesignKitCompileError("invalid pending source brief")
            _validate_source_binding(brief, source, index)
            continue
        if brief.get("status") != "ready":
            raise VisualDesignKitCompileError("source brief readiness is missing")
        required_fields = _BRIEF_BINDING_FIELDS | _BRIEF_ROLE_FIELDS[role] | {"status", "design_review"}
        allowed_fields = required_fields
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
        direction = _image_direction(brief["image_direction"], source, category_id=category_id, source_manifest=source_manifest or sources)
        if any(row["text_ref"] not in _text_refs(brief, source) for row in direction["text_placement"]):
            raise VisualDesignKitCompileError("text placement references absent role copy")
        if role in {"func", "size"}:
            _validate_display_brief(
                brief, source, index, product_claims=product_claims,
            )
        if (
            role == "size"
            and (
                brief["measurement_authority"] != "located_source_measurements"
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


def _validate_display_brief(
    brief: dict[str, Any], source: dict[str, Any], index: int, *,
    product_claims: list[dict[str, Any]] | None = None,
) -> None:
    story = brief.get("display_copy_contract")
    if not isinstance(story, dict) or set(story) != {"mode", "title", "labels", "bindings"} or story.get("mode") != "source_claims":
        raise VisualDesignKitCompileError(f"source_briefs[{index}] has no canonical DisplayCopyContract")
    if not isinstance(story["labels"], list) or not isinstance(story["bindings"], list):
        raise VisualDesignKitCompileError("display copy lists are malformed")
    strings = ([story["title"]] if story["title"] else []) + story["labels"]
    if len(strings) != len(story["bindings"]) or len(strings) != len(set(strings)):
        raise VisualDesignKitCompileError("display copy bindings changed")
    available = _available_claims(source, product_claims)
    for text, binding in zip(strings, story["bindings"]):
        if _bind_display_text(binding, available, claim_reviews=brief["claim_reviews"])["text"] != text:
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
    evidence = {
        str(row.get("evidence_id") or ""): str(row.get("text") or "")
        for row in rows
        if isinstance(row, dict)
        and str(row.get("evidence_id") or "")
        and str(row.get("text") or "").strip()
    }
    source_id = source['source_id']
    for view in (source.get('observation') or {}).get('physical_views', []):
        for feature in view['evidence']:
            for index, fact in enumerate(feature['physical_facts']):
                evidence[f"physical:{source_id}:{view['view_id']}:{feature['feature_id']}:{index}"] = fact
    for index, row in enumerate(source.get('measurements') or []):
        evidence[f'measurement:{source_id}:{index}'] = str(row.get('source_label') or row.get('text') or '')
    return evidence


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


def _design_mapping(value: Any, schema: dict[str, Any], label: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(schema):
        raise VisualDesignKitCompileError(f"{label} needs the current named design fields")
    return {key: _required_text(item, f"{label}.{key}", _ART_DIRECTION_FIELD_MAX)
            for key, item in value.items()}


def _image_direction(value: Any, source: dict[str, Any], *, category_id: str = "", source_manifest: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One creative contract with explicit evidence disposition, not one panel per crop."""
    if not isinstance(value, dict) or set(value) != set(IMAGE_DIRECTION_SCHEMA):
        raise VisualDesignKitCompileError("image_direction needs the current named design fields")
    if value["environment_mode"] not in {"designed_environment", "graphic_canvas", "source_setting"}:
        raise VisualDesignKitCompileError("image_direction has unknown environment_mode")
    objects = value['scene_objects']
    if (not isinstance(objects, list) or any(not isinstance(key, str)
            or not re.fullmatch(r'[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*', key) for key in objects)
            or len(objects) != len(set(objects))):
        raise VisualDesignKitCompileError('scene_objects must select unique target group.component identities')
    catalog = evidence_view_catalog(source_manifest or [source])
    usage = value['evidence_usage']
    if not isinstance(usage, list) or any(not isinstance(row, dict)
            or any(not isinstance(row.get(k), str) for k in ('source_id', 'view_id')) for row in usage):
        raise VisualDesignKitCompileError('evidence_usage needs source/view dispositions')
    errors = [f'evidence_usage[{i}] needs source_id, view_id, usage and covered_by (display uses [])'
              for i, row in enumerate(usage) if set(row) != {'source_id', 'view_id', 'usage', 'covered_by'}]
    ids = [view_identity(row) for row in usage]
    if len(ids) != len(set(ids)) or not set(ids) <= set(catalog):
        raise VisualDesignKitCompileError('Selected evidence must identify unique views of this child')
    views = {key: catalog[key][1] for key in ids}
    if errors:
        raise VisualDesignKitCompileError('; '.join(errors))
    for field, maximum in (("visual_goal", 240), ("creative_brief", 700)):
        _required_text(value[field], field, maximum)
        if re.search(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6})\b", value[field]):
            raise VisualDesignKitCompileError(f"{field} must reference shared color roles, not redefine colors")
    refs = value["design_transfer"]
    if not isinstance(refs, list) or any(not isinstance(row, dict) or set(row) != {"reference_id", "inherit", "adapt"} for row in refs):
        raise VisualDesignKitCompileError("design_transfer needs reference identity, inheritance and adaptation")
    ids = [row["reference_id"] for row in refs]
    if any(not isinstance(key, str) or not key for key in ids) or len(ids) != len(set(ids)):
        raise VisualDesignKitCompileError("design_transfer must use unique input identities")
    for row in refs:
        for field in ("inherit", "adapt"):
            _required_text(row[field], field, 350)
            if re.search(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6})\b", row[field]):
                raise VisualDesignKitCompileError("design_transfer must reference shared color roles, not redefine colors")
    for field, fields in (("layout", {"source_id", "view_id", "target_region"}), ("text_placement", {"text_ref", "target_region", "backing"})):
        rows = value[field]
        if not isinstance(rows, list):
            raise VisualDesignKitCompileError(f"{field} needs a region list")
        for row in rows:
            if not isinstance(row, dict) or set(row) != fields:
                raise VisualDesignKitCompileError(f"{field} has invalid region fields")
            if field == "text_placement" and not isinstance(row["text_ref"], str):
                raise VisualDesignKitCompileError("text_ref must name a role-copy entry")
            if field == 'text_placement' and row['backing'] not in {'none', 'local'}:
                raise VisualDesignKitCompileError('Text backing must be an explicit none/local design choice')
            if field == "layout" and not isinstance(row["view_id"], str):
                raise VisualDesignKitCompileError("view_id must name observed physical evidence")
            if field == 'layout' and not isinstance(row['source_id'], str):
                raise VisualDesignKitCompileError('Layout source_id must name selected evidence')
            for key in fields - {"text_ref", "view_id", "source_id", "backing"}:
                box = row[key]
                if not isinstance(box, list) or len(box) != 4 or any(type(x) not in (int, float) or not 0 <= x <= 1 for x in box) or not (box[0] < box[2] and box[1] < box[3]):
                    raise VisualDesignKitCompileError(f"{field}.{key} requires normalized left,top,right,bottom bounds")
    displayed = {view_identity(row) for row in usage if row["usage"] == "display"}
    if not displayed:
        raise VisualDesignKitCompileError("An image must display observed product evidence")
    if source['role'] in {'func', 'size'}:
        measured = {key for key in views if any(view_identity(row) == key and row['usage'] != 'verification' for row in usage)
                    for measurement in catalog[key][0].get('measurements', [])
                    if measurement['view_id'] == catalog[key][1]['view_id']}
        if not measured <= displayed:
            raise VisualDesignKitCompileError('Selected measurement views need visible endpoint geometry')
    for row in usage:
        links = row["covered_by"]
        if row["usage"] not in {"display", "integrated", "verification"}:
            raise VisualDesignKitCompileError("Unknown evidence disposition")
        if not isinstance(links, list) or any(not isinstance(key, str) or key not in displayed or key == view_identity(row) for key in links):
            raise VisualDesignKitCompileError("Covered evidence must reference displayed views")
        if (row["usage"] in {'display', 'verification'} and links) or (row["usage"] == 'integrated' and not links):
            raise VisualDesignKitCompileError("Only integrated evidence names its displayed coverage")
    selected = [view_identity(row) for row in value["layout"]]
    if not set(selected) <= displayed or len(selected) != len(set(selected)):
        raise VisualDesignKitCompileError("Optional layout can position displayed views only")
    return value


def _reject_renderable_copy_instruction(value: str, label: str) -> None:
    if _RENDERABLE_COPY_INSTRUCTION_RE.search(value):
        raise VisualDesignKitCompileError(
            f"{label} contains a renderable-copy instruction; readable copy belongs only to DisplayCopyContract or MeasurementContract"
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
