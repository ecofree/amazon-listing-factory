from __future__ import annotations

import re
from typing import Any

from .visual_semantics import CLAIM_REVIEW_POLICY, claim_key
from .image_reference_context import evidence_view_catalog, view_identity, physical_views
from .image_task_inputs import task_specs, role_art_direction, shared_design_values
from .text_evidence import has_bad_encoding, us_measurement_text, extract_measurements


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
}
# Gemini owns child-wide direction; the image model designs each composition.
DESIGN_FIELD_SCHEMAS = {
    "typography_direction": {
        "font_family": "one chosen font family, not alternatives",
        "title_style": "weight, case and hierarchy relative to the product",
        "body_style": "body hierarchy and readability; exact sizing and line breaks belong to the image model",
        "numeric_style": "measurement legibility and spacing; no literal values",
    },
    "graphic_direction": {
        "text_color": "one flat hex for ALL titles, captions and measurements; not gradients, outlines or shadows",
        "line_color": "one hex for leaders and measurement arrows",
        "icon_color": "one hex for unbacked icon strokes",
        "backing_color": "one hex for local backing when needed",
        "backed_symbol_color": "one contrasting hex for symbols on backing",
        "icon_style": "outline|filled; one child-wide icon treatment, not a background policy",
        "line_style": "fine|medium; one child-wide leader stroke weight",
    },
}
IMAGE_DIRECTION_SCHEMA = {
    "visual_goal": "one buyer-facing communication goal; not display copy",
    "presentation": {
        "scope": "whole_product|detail_only; the extent to depict, not a fixed camera angle",
        "state": "product use/demonstration, necessary parts and physical support or installation; not layout, colors or source props",
        "components": ["bedding.duvet"],
    },
    "evidence_usage": [
        {"source_id": "source_00", "view_id": "view_01", "usage": "display", "covered_by": []},
        {"source_id": "source_00", "view_id": "view_02", "usage": "integrated", "covered_by": ["source_00/view_01"]},
    ],
    "design_transfer": [{"reference_id": "approved ID", "inherit": "defining features used here", "adapt": "change and reason, or retain as approved"}],
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
    raw: Any, *, source_manifest: list[dict[str, Any]], category_id: str = "", main_policy: str = '',
    product_claims: list[dict[str, Any]] = (),
    claim_reviews: dict[str, dict[str, Any]] | None = None,
    design_references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keep shared design valid while isolating incomplete individual briefs."""
    if not isinstance(raw, dict):
        raise VisualDesignKitCompileError("planner response must be an object")
    art_direction = _compile_art_direction(raw.get("family_art_direction"))
    raw_briefs = raw.get("image_briefs")
    if not isinstance(raw_briefs, list):
        raise VisualDesignKitCompileError("image_briefs must be a list")
    specs = task_specs({}, source_manifest, include_optional=True)
    expected_roles = {spec['role'] for spec in specs}
    raw_by_role = {}
    for row in raw_briefs:
        if not isinstance(row, dict) or row.get("role") not in expected_roles:
            raise VisualDesignKitCompileError("image brief has an unknown output role")
        if row["role"] in raw_by_role:
            raise VisualDesignKitCompileError("duplicate output brief")
        raw_by_role[row["role"]] = row
    briefs = []
    for spec in specs:
        source = spec['source'] or {}
        role = spec['role']
        draft = raw_by_role.get(role) or {}
        review = {}
        bound_reviews = {}
        try:
            if not source:
                raise VisualDesignKitCompileError(spec['reason'], failure_owner='observation')
            if draft.get('source_id') != source['source_id']:
                raise VisualDesignKitCompileError('Output evidence anchor does not match its inventory')
            validate_image_brief_draft(draft, source, art_direction, source_manifest, category_id, product_claims=product_claims, design_references=design_references)
            bound_reviews = {row['key']: claim_reviews[row['key']]
                             for row in claim_review_requests({'image_briefs': [draft]}, source_manifest, product_claims)
                             if row['key'] in (claim_reviews or {})}
            request = design_binding_request(draft, art_direction, main_policy=main_policy, source=source, source_manifest=source_manifest, product_claims=product_claims, design_references=design_references)
            review = (claim_reviews or {}).get(request["key"], {})
            _validate_physical_review(request, review)
            brief = _compile_image_brief(
                source, draft, product_claims=product_claims,
                category_id=category_id, claim_reviews=claim_reviews or {}, source_manifest=source_manifest,
            )
            brief["design_review"] = review
            brief["status"] = "ready"
        except ValueError as exc:
            brief = {
                "source_id": source.get("source_id", ''), "source_sha256": source.get("source_sha256", ''),
                "source_intent_revision_id": source.get("input_revision_id", ''), "role": role,
                "status": "pending", "error": str(exc), "draft": draft,
                "failure_owner": getattr(exc, 'failure_owner', 'brief'),
                "design_review": review,
                "claim_reviews": bound_reviews,
            }
        briefs.append(brief)
    result = {"family_art_direction": art_direction, "image_briefs": briefs}
    validate_compiled_visual_design_kit(result, source_manifest=source_manifest, category_id=category_id, main_policy=main_policy, product_claims=product_claims, design_references=design_references)
    return result


def validate_image_brief_draft(draft: dict[str, Any], source: dict[str, Any], art: dict[str, Any],
                              sources: list[dict[str, Any]], category_id: str, *,
                              product_claims: list[dict[str, Any]] = (),
                              design_references: list[dict[str, Any]] | None = None) -> None:
    """Local contract used before paid review and by final compilation."""
    errors = []
    role = str(draft.get('role', '')).split('_', 1)[0]
    if role in {'func', 'size'} and (source.get('observation') or {}).get('text_gaps'):
        raise VisualDesignKitCompileError('Required product text is unresolved: ' + '; '.join(source['observation']['text_gaps']), failure_owner='observation')
    if role in {'func', 'size'}:
        direction = draft.get('image_direction')
        usages = direction.get('evidence_usage', []) if isinstance(direction, dict) else []
        selected_views = {view_identity(row) for row in usages if isinstance(row, dict) and {'source_id', 'view_id'} <= set(row)} if isinstance(usages, list) else set()
        unresolved = [issue['error'] for owner in sources for issue in (owner.get('observation') or {}).get('measurement_issues') or []
                      if owner['source_id'] == source['source_id'] or (isinstance(issue['measurement'], dict)
                      and owner['source_id'] + '/' + str(issue['measurement'].get('view_id')) in selected_views)]
        if unresolved:
            raise VisualDesignKitCompileError('Required measurement evidence is unresolved: ' + '; '.join(unresolved), failure_owner='observation')
    if set(draft) - {'role', 'source_id', 'image_direction', 'display_copy'}:
        errors.append('Brief contains fields outside the current response schema')
    try:
        direction = _image_direction(draft.get('image_direction'), source, role=role, category_id=category_id, source_manifest=sources)
        available_components = {f'{group}.{part}' for group, parts in art['palette_direction'].items() for part in parts}
        if not set(direction['presentation']['components']) <= available_components:
            raise VisualDesignKitCompileError('presentation.components must select existing child palette component IDs')
        _validate_reference_approval(direction, role, design_references or [])
    except ValueError as exc:
        errors.append(str(exc))
    if role in {'func', 'size'}:
        story = draft.get('display_copy')
        if not isinstance(story, dict) or set(story) != {'title', 'labels'} or not isinstance(story.get('labels'), list):
            errors.append('display copy needs an explicit title choice and label list')
        else:
            available = _available_claims(sources, product_claims)
            for row in ([story['title']] if story['title'] is not None else []) + story['labels']:
                try:
                    bound = _copy_binding(row, available)
                    if role == 'size' and extract_measurements(bound['text']):
                        raise VisualDesignKitCompileError('Size display_copy uses headings only; numeric dimensions and capacity belong to measurement_authority')
                except ValueError as exc:
                    errors.append(str(exc))
    if errors:
        raise VisualDesignKitCompileError('; '.join(errors))


def _validate_reference_approval(direction: dict[str, Any], role: str, references: list[dict[str, Any]]) -> None:
    approved = {row['source_id']: row for row in references}
    if any(row['reference_id'] not in approved or role not in approved[row['reference_id']]['roles']
           for row in direction['design_transfer']):
        raise VisualDesignKitCompileError('Selected design reference is not approved for this role')


def claim_review_requests(raw: Any, source_manifest: list[dict[str, Any]], product_claims: list[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """Collect scoped claims for the independent reviewer before compilation."""
    sources = {source["source_id"]: source for source in source_manifest}
    requests = {}
    for brief in raw.get("image_briefs") or []:
        source = sources.get(brief.get("source_id")) if isinstance(brief, dict) else None
        if not source or str(brief.get('role', '')).split('_', 1)[0] not in {"func", "size"}:
            continue
        available = _available_claims(source_manifest, product_claims)
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
                             "proposed_text": bound["text"], "evidence": evidence,
                             "evidence_sources": [row['source_id'] for row in source_manifest
                                                  if set(evidence) & set(_available_claims([row], []))]}
    return list(requests.values())


def design_binding_request(brief: dict[str, Any], art: dict[str, Any], *, source: dict[str, Any], main_policy: str = '', source_manifest: list[dict[str, Any]] = (), product_claims: list[dict[str, Any]] = (), design_references: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    direction = brief.get("image_direction") or {}
    text = {key: direction.get(key) for key in IMAGE_DIRECTION_SCHEMA} if isinstance(direction, dict) else {}
    role = str(brief['role']).split('_', 1)[0]
    text["role"] = brief['role']
    shared = role_art_direction(art, direction, role, main_policy=main_policy)
    if role == 'main' and main_policy == 'white_background':
        text['environment_mode'] = 'graphic_canvas'
    required_facts = {
        'claims': [{key: row.get(key) for key in ('evidence_id', 'text')} for row in source.get('claims', [])],
        'measurements': [{key: row.get(key) for key in ('text', 'source_label', 'axis_hint', 'view_id', 'source_endpoints')}
                         for row in source.get('measurements', [])],
    } if role in {'func', 'size'} else {}
    required_facts['product_claims'] = list(product_claims)
    catalog = evidence_view_catalog(list(source_manifest) or [source])
    usage = text.get('evidence_usage')
    usage = [row for row in usage if isinstance(row, dict) and all(isinstance(row.get(k), str) for k in ('source_id', 'view_id'))] if isinstance(usage, list) else []
    selected = {view_identity(row) for row in usage}
    evidence = [{'source_id': owner['source_id'], 'source_sha256': owner['source_sha256'],
                 'source_revision': owner['input_revision_id'], 'view': view,
                 'required_annotation_regions': [m['source_region'] for m in owner.get('measurements', []) if m['view_id'] == view['view_id']],
                 'crops': [crop for crop in owner.get('crop_provenance', []) if crop['view_id'] == view['view_id']]}
                for key, (owner, view) in catalog.items() if key in selected]
    risks = ['coverage_transfer:' + view_identity(row) for row in usage if row.get('usage') == 'integrated']
    if text['presentation']['scope'] == 'whole_product' and not any(
            catalog[view_identity(row)][1]['extent'] == 'whole_view' for row in usage if row['usage'] == 'display'):
        risks.append('whole_product_transfer:' + brief['role'])
    shown = {view_identity(row) for row in usage if row.get('usage') != 'verification'}
    omitted_measurements = any(source['source_id'] + '/' + row['view_id'] not in shown for row in source.get('measurements', []))
    if role in {'func', 'size'} and omitted_measurements:
        risks.append('product_coverage:' + source['source_id'])
    unknown_objects = {}
    for key in sorted(selected):
        if key not in catalog:
            continue
        owner, view = catalog[key]
        objects = {row['object_id']: row for row in owner['observation'].get('objects', [])}
        disputed = [objects[item['object_id']] for item in view['evidence']
                    if objects.get(item['object_id'], {}).get('sale_membership') == 'unknown']
        if disputed:
            risks.append('sold_membership:' + key)
            for obj in disputed:
                unknown_objects[(owner['source_id'], obj['object_id'])] = {'source_id': owner['source_id'], **obj}
    if unknown_objects:
        required_facts['unknown_product_objects'] = list(unknown_objects.values())
    selected = {row.get('reference_id') for row in text.get('design_transfer') or [] if isinstance(row, dict)}
    scopes = [{**{key: row[key] for key in ('source_id', 'sha256', 'purpose', 'roles')},
               'approval_boundary': row['visual_review']['transfer_scope']}
              for row in design_references or [] if row['source_id'] in selected]
    from .status import input_revision_id
    key = input_revision_id({"policy": CLAIM_REVIEW_POLICY, "role_design": text,
        'source_revision': source['input_revision_id'], 'source_sha256': source['source_sha256'],
        'selected_evidence': evidence, 'required_facts': required_facts,
        'crop_policy': 'floor-ceil-original-png-v3-detail-evidence-bounds', 'reference_scopes': scopes, 'shared_design': shared})
    return {"kind": "design_binding", "key": key, "source_id": brief.get("source_id"), "role_design": text,
            "reference_scopes": scopes, "physical_operations": sorted(set(risks)), "selected_evidence": evidence,
            'required_facts': required_facts, 'shared_design': shared}


def review_failure_owner(record: dict[str, Any]) -> str:
    operation = str(record.get('operation', ''))
    if record.get('status') == 'contradiction' or record.get('resolution') == 'revise_plan':
        return 'observation' if operation.startswith('source_product:') else 'shared_design' if operation.startswith('shared_design:') else 'brief'
    if record.get('resolution') == 'correct_evidence' and operation.startswith('source_product:'):
        return 'observation'
    return 'review'


def _validate_physical_review(request: dict[str, Any], review: dict[str, Any]) -> None:
    findings = review.get('findings', [])
    allowed = set(request['physical_operations']) | {'source_product:' + row['source_id'] + '/' + row['view']['view_id']
                                                   for row in request['selected_evidence']}
    allowed.update('shared_design:' + key for key in shared_design_values(request['shared_design']))
    conflicts = [row for row in findings if row.get('status') == 'contradiction' and row.get('operation') in allowed]
    if conflicts:
        source_error = any(str(row.get('operation', '')).startswith('source_product:') for row in conflicts)
        shared_error = any(str(row.get('operation', '')).startswith('shared_design:') for row in conflicts)
        raise VisualDesignKitCompileError('planning evidence conflict: ' + '; '.join(str(row['reason']) for row in conflicts),
                                         failure_owner='observation' if source_error else 'shared_design' if shared_error else 'brief')
    unsupported = [row for row in findings if row.get('status') == 'inconclusive' and row.get('operation') in allowed]
    if unsupported:
        owners = {review_failure_owner(row) for row in unsupported}
        owner = next(key for key in ('observation', 'shared_design', 'brief', 'review') if key in owners)
        raise VisualDesignKitCompileError('Planning evidence unresolved: ' + '; '.join(str(row['reason']) for row in unsupported), failure_owner=owner)
    supported = {row.get('operation') for row in findings if row.get('status') == 'supported'}
    missing = set(request['physical_operations']) - supported
    if missing:
        raise VisualDesignKitCompileError('Planning operation needs bound review: ' + ', '.join(sorted(missing)), failure_owner='review')


def validate_compiled_visual_design_kit(
    data: Any,
    *,
    source_manifest: list[dict[str, Any]],
    category_id: str = "",
    main_policy: str = '',
    product_claims: list[dict[str, Any]] = (),
    design_references: list[dict[str, Any]] | None = None,
) -> None:
    if not isinstance(data, dict) or set(data) != {"family_art_direction", "image_briefs"}:
        raise VisualDesignKitCompileError("planner response fields do not match the current VisualDesignKit contract")
    _validate_art_direction(data["family_art_direction"])
    sources = {row['source_id']: row for row in source_manifest}
    for brief in data["image_briefs"]:
        if brief.get("status") == "ready":
            _validate_reference_approval(brief['image_direction'], brief['role'].split('_', 1)[0], design_references or [])
            review = brief.get("design_review")
            if not isinstance(review, dict):
                raise VisualDesignKitCompileError("Design review must be a bound record or an explicit empty record")
            request = design_binding_request(brief, data["family_art_direction"], main_policy=main_policy, source=sources[brief['source_id']], source_manifest=source_manifest, product_claims=product_claims, design_references=design_references)
            _validate_physical_review(request, review)
            if review and (review.get("key") != request["key"]
                           or review.get("policy") != CLAIM_REVIEW_POLICY
                           or not review.get("response_sha256")):
                raise VisualDesignKitCompileError("Design review no longer matches this child's design")
    _validate_briefs(
        data["image_briefs"],
        source_manifest,
        product_claims=product_claims,
        category_id=category_id,
    )


def _compile_art_direction(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _ART_DIRECTION_FIELDS:
        raise VisualDesignKitCompileError("family_art_direction needs the current child design fields")
    result = {
        field: _required_text(
            value.get(field),
            f"family_art_direction.{field}",
            _ART_DIRECTION_FIELD_MAX,
        )
        for field in _ART_DIRECTION_FIELDS - {"palette_direction", *DESIGN_FIELD_SCHEMAS}
    }
    for field, schema in DESIGN_FIELD_SCHEMAS.items():
        result[field] = _design_mapping(value.get(field), schema, field)
    graphic = result['graphic_direction']
    if graphic['icon_style'] not in {'outline', 'filled'} or graphic['line_style'] not in {'fine', 'medium'}:
        raise VisualDesignKitCompileError('Graphic treatment needs icon_style outline/filled and line_style fine/medium')
    palette = value.get("palette_direction")
    if not isinstance(palette, dict) or not palette:
        raise VisualDesignKitCompileError("palette_direction needs named groups of physical design components")
    result['palette_direction'] = {}
    for group, parts in palette.items():
        if (not isinstance(group, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', group)
                or not isinstance(parts, dict) or not parts
                or any(not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', key) for key in parts)):
            raise VisualDesignKitCompileError('Palette groups need semantic component IDs, not an undivided color string')
        if group == 'non_product_group' or (group != 'room' and 'room' in parts):
            raise VisualDesignKitCompileError('Use room.wall/floor for architecture and named component groups such as bedding; replace schema placeholders')
        result['palette_direction'][group] = _design_mapping(parts, parts, 'palette_direction.' + group)
        for part, text in result['palette_direction'][group].items():
            if len(re.findall(r'#[0-9a-fA-F]{6}(?![0-9a-fA-F])', text)) != 1:
                raise VisualDesignKitCompileError(f'palette_direction.{group}.{part} needs one component and one six-digit hex; separate combined components')
    return result


def _compile_image_brief(
    source: dict[str, Any], draft: dict[str, Any], *,
    product_claims: list[dict[str, Any]] | None = None, category_id: str = "",
    claim_reviews: dict[str, dict[str, Any]],
    source_manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    role = str(draft['role']).split('_', 1)[0]
    result = {
        "source_id": str(source["source_id"]),
        "source_intent_revision_id": str(source["input_revision_id"]),
        "source_sha256": str(source["source_sha256"]),
        "role": draft['role'],
        "image_direction": _image_direction(draft.get("image_direction"), source, role=role, category_id=category_id, source_manifest=source_manifest),
    }
    if role in {"func", "size"}:
        result["display_copy_contract"] = _compile_display_copy(source_manifest, draft.get("display_copy"), product_claims=product_claims, claim_reviews=claim_reviews)
        available = _available_claims(source_manifest, product_claims)
        used_keys = {claim_key(row["text"], {key: available[key] for key in row["evidence_ids"]})
                    for row in result["display_copy_contract"]["bindings"]}
        result["claim_reviews"] = {key: value for key, value in claim_reviews.items() if key in used_keys}
    if role == "size":
        result["measurement_authority"] = "located_source_measurements"
    return result


def _compile_display_copy(
    sources: list[dict[str, Any]], value: Any, *,
    product_claims: list[dict[str, Any]] | None = None,
    claim_reviews: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    available = _available_claims(sources, product_claims)
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
        raise VisualDesignKitCompileError("display copy binding is malformed")
    ids = value.get("evidence_ids")
    text = value.get("text")
    if (
        not isinstance(ids, list) or not ids or any(not isinstance(key, str) or key not in available for key in ids)
        or len(ids) != len(set(ids)) or not isinstance(text, str) or not text.strip()
        or len(text) > 240 or has_bad_encoding(text)
    ):
        missing = [key for key in ids if isinstance(key, str) and key not in available] if isinstance(ids, list) else []
        raise VisualDesignKitCompileError(f"display copy has invalid text or evidence scope; unknown child evidence IDs: {missing}")
    if any(key.startswith('measurement:') for key in ids) and extract_measurements(text):
        raise VisualDesignKitCompileError('measurement: IDs authorize headings only; numeric labels belong to measurement_authority')
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
        owner = review_failure_owner(review)
        raise VisualDesignKitCompileError("display claim requires independent evidence review: " + reason, failure_owner=owner)
    return bound


def _validate_art_direction(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != _ART_DIRECTION_FIELDS:
        raise VisualDesignKitCompileError("family_art_direction fields do not match the current contract")
    compiled = _compile_art_direction(value)
    if compiled != value:
        raise VisualDesignKitCompileError("art direction is not canonical")
    for field in _ART_DIRECTION_FIELDS - {"palette_direction", *DESIGN_FIELD_SCHEMAS}:
        _valid_text(
            value[field],
            f"family_art_direction.{field}",
            5,
            _ART_DIRECTION_FIELD_MAX,
        )


def _validate_briefs(
    briefs: Any,
    sources: list[dict[str, Any]],
    *,
    product_claims: list[dict[str, Any]] | None = None,
    category_id: str = "",
    source_manifest: list[dict[str, Any]] | None = None,
) -> None:
    expected = {row['role']: row['source'] or {} for row in task_specs({}, sources, include_optional=True)}
    if not isinstance(briefs, list) or len(briefs) != len(expected):
        raise VisualDesignKitCompileError(
            "image_briefs do not cover every output role exactly once"
        )
    seen: set[str] = set()
    for index, brief in enumerate(briefs):
        output_role = str(brief.get("role") or "") if isinstance(brief, dict) else ""
        if output_role not in expected or output_role in seen:
            raise VisualDesignKitCompileError(
                f"image_briefs[{index}] has a missing, duplicate, or unknown output role"
            )
        seen.add(output_role)
        source = expected[output_role]
        role = output_role.split('_', 1)[0]
        if brief.get("status") == "pending":
            if (set(brief) != _BRIEF_BINDING_FIELDS | {"status", "error", "draft", "failure_owner", "design_review", "claim_reviews"}
                    or not isinstance(brief['design_review'], dict)
                    or not isinstance(brief['claim_reviews'], dict)
                    or brief['failure_owner'] not in {'observation', 'brief', 'shared_design', 'review'} or not brief.get("error") or not isinstance(brief.get("draft"), dict)):
                raise VisualDesignKitCompileError("invalid pending source brief")
            _validate_source_binding(brief, source, index)
            continue
        if brief.get("status") != "ready":
            raise VisualDesignKitCompileError("source brief readiness is missing")
        required_fields = _BRIEF_BINDING_FIELDS | _BRIEF_ROLE_FIELDS[role] | {"status", "design_review"}
        allowed_fields = required_fields
        missing_fields = sorted(required_fields - set(brief))
        unknown_fields = sorted(set(brief) - allowed_fields)
        if missing_fields or unknown_fields:
            detail = "; ".join(
                part for part in (
                    f"missing: {', '.join(missing_fields)}" if missing_fields else "",
                    f"unknown: {', '.join(unknown_fields)}" if unknown_fields else "",
                ) if part
            )
            raise VisualDesignKitCompileError(
                f"image_briefs[{index}] fields do not match its {role} contract ({detail})"
            )
        _validate_source_binding(brief, source, index)
        _image_direction(brief["image_direction"], source, role=role, category_id=category_id, source_manifest=source_manifest or sources)
        if role in {"func", "size"}:
            _validate_display_brief(
                brief, sources, index, product_claims=product_claims,
            )
        if (
            role == "size"
            and (
                brief["measurement_authority"] != "located_source_measurements"
            )
        ):
            raise VisualDesignKitCompileError(
                f"image_briefs[{index}] changed size measurement authority"
            )


def _validate_source_binding(
    brief: dict[str, Any],
    source: dict[str, Any],
    index: int,
) -> None:
    if (
        brief['source_id'] != source.get('source_id', '')
        or brief["source_intent_revision_id"] != source.get("input_revision_id", '')
        or brief["source_sha256"] != source.get("source_sha256", '')
    ):
        raise VisualDesignKitCompileError(
            f"image_briefs[{index}] source binding changed"
        )


def _validate_display_brief(
    brief: dict[str, Any], sources: list[dict[str, Any]], index: int, *,
    product_claims: list[dict[str, Any]] | None = None,
) -> None:
    story = brief.get("display_copy_contract")
    if not isinstance(story, dict) or set(story) != {"mode", "title", "labels", "bindings"} or story.get("mode") != "source_claims":
        raise VisualDesignKitCompileError(f"image_briefs[{index}] has no canonical DisplayCopyContract")
    if not isinstance(story["labels"], list) or not isinstance(story["bindings"], list):
        raise VisualDesignKitCompileError("display copy lists are malformed")
    strings = ([story["title"]] if story["title"] else []) + story["labels"]
    if brief['role'].split('_', 1)[0] == 'size' and any(extract_measurements(text) for text in strings):
        raise VisualDesignKitCompileError('Size display_copy uses headings only; numeric dimensions and capacity belong to measurement_authority')
    if len(strings) != len(story["bindings"]) or len(strings) != len(set(strings)):
        raise VisualDesignKitCompileError("display copy bindings changed")
    available = _available_claims(sources, product_claims)
    for text, binding in zip(strings, story["bindings"]):
        if _bind_display_text(binding, available, claim_reviews=brief["claim_reviews"])["text"] != text:
            raise VisualDesignKitCompileError("func text disagrees with its reviewed binding")


def _available_claims(
    sources: list[dict[str, Any]],
    product_claims: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """The current child's catalog; an output anchor does not narrow truth scope."""
    rows = [*(row for source in sources for row in cleaned_source_claims(source)), *(product_claims or [])]
    evidence = {
        str(row.get("evidence_id") or ""): str(row.get("text") or "")
        for row in rows
        if isinstance(row, dict)
        and str(row.get("evidence_id") or "")
        and str(row.get("text") or "").strip()
    }
    for source in sources:
        source_id = source['source_id']
        for view in physical_views(source['observation']['physical_views']):
            for feature in view['evidence']:
                for index, fact in enumerate(feature['physical_facts']):
                    evidence[f"physical:{source_id}:{view['view_id']}:{feature['feature_id']}:{index}"] = fact
        for index, row in enumerate(source.get('measurements') or []):
            evidence[f'measurement:{source_id}:{index}'] = str(row.get('source_label') or row.get('text') or '')
    return evidence


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


def _image_direction(value: Any, source: dict[str, Any], *, role: str, category_id: str = "", source_manifest: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One creative contract with explicit evidence disposition, not one panel per crop."""
    if not isinstance(value, dict) or set(value) != set(IMAGE_DIRECTION_SCHEMA):
        raise VisualDesignKitCompileError("image_direction needs the current named design fields")
    if value["environment_mode"] not in {"designed_environment", "graphic_canvas", "source_setting"}:
        raise VisualDesignKitCompileError("image_direction has unknown environment_mode")
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
    _required_text(value['visual_goal'], 'visual_goal', 240)
    presentation = value['presentation']
    if (not isinstance(presentation, dict) or set(presentation) != {'scope', 'state', 'components'}
            or presentation['scope'] not in {'whole_product', 'detail_only'}
            or not isinstance(presentation['components'], list)
            or any(not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*', key)
                   for key in presentation['components'])
            or len(presentation['components']) != len(set(presentation['components']))):
        raise VisualDesignKitCompileError('presentation needs product scope, intended state and unique core component IDs')
    _required_text(presentation['state'], 'presentation.state', 300)
    if re.search(r'#[0-9a-fA-F]{6}', presentation['state']):
        raise VisualDesignKitCompileError('presentation.state references child components, not separate colors')
    if re.search(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6})\b", value['visual_goal']):
        raise VisualDesignKitCompileError("visual_goal must reference shared color roles, not redefine colors")
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
    displayed = {view_identity(row) for row in usage if row["usage"] == "display"}
    if not displayed:
        raise VisualDesignKitCompileError("An image must display observed product evidence")
    if presentation['scope'] == 'whole_product' and not any(view['extent'] == 'whole_view' for view in views.values()):
        raise VisualDesignKitCompileError('whole_product presentation needs same-child whole_view evidence, including verification; otherwise plan detail_only')
    if role == 'main' and presentation['scope'] != 'whole_product':
        raise VisualDesignKitCompileError('Main presents the complete sold product')
    if role == 'main' and not any(
            catalog[key][1]['extent'] == 'whole_view'
            and any(row['view_id'] == catalog[key][1]['view_id'] and 'appearance' in row['purposes']
                    for row in catalog[key][0]['observation']['reference_views']) for key in displayed):
        raise VisualDesignKitCompileError('Main requires selected whole-product appearance evidence')
    if role in {'func', 'size'}:
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
    return value


def _reject_renderable_copy_instruction(value: str, label: str) -> None:
    if _RENDERABLE_COPY_INSTRUCTION_RE.search(value):
        raise VisualDesignKitCompileError(
            f"{label} contains a renderable-copy instruction; readable copy belongs only to DisplayCopyContract or MeasurementContract"
        )


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
