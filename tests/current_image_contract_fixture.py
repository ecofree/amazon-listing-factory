from __future__ import annotations

from pathlib import Path
from typing import Any

from core.image_prompt_compiler import (
    IMAGE_PROMPT_SCHEMA_VERSION,
    PROMPT_CONTRACT_VERSION,
    _prompt_row,
    validate_image_prompt,
)
from core.image_tasks import (
    IMAGE_TASK_POLICY_VERSION,
    IMAGE_TASK_SCHEMA_VERSION,
    _task_fingerprint,
    _edit_contract,
    validate_image_task,
)


def supported_design_reviews(raw, sources, design_references=None, product_claims=()):
    from core.visual_design_kit_compiler import design_binding_request
    by_id = {row['source_id']: row for row in sources}
    requests = [design_binding_request(brief, raw['family_art_direction'], source=by_id[brief['source_id']],
                source_manifest=sources, product_claims=product_claims, design_references=design_references) for brief in raw['image_briefs']]
    return supported_review_results([row for row in requests if row['physical_operations']])


def supported_review_results(requests, **kwargs):
    from core.visual_semantics import CLAIM_REVIEW_POLICY
    return {row['key']: {'key': row['key'], 'policy': CLAIM_REVIEW_POLICY, 'response_sha256': 'a'*64,
            'status': 'supported', 'findings': [{'operation': op, 'status': 'supported', 'reason': 'Simulated verdict for contract testing only'}
                                               for op in row.get('physical_operations', [])]} for row in requests}


def current_physical_view(view_id: str = 'view_01', region: list[float] | None = None, *, feature: str = 'frame_support', object_id: str = 'frame') -> dict[str, Any]:
    box = dict(zip(('left', 'top', 'right', 'bottom'), region or [0.1, 0.2, 0.9, 0.8]))
    return {'view_id': view_id, 'region': box, 'extent': 'whole_view',
            'evidence': [{'feature_id': feature, 'object_id': object_id, 'region': box.copy(), 'physical_facts': ['Visible frame support and its joints']}]}


def current_art_direction() -> dict[str, Any]:
    return {
        "audience_and_market": "US homeowners seeking calm, practical bathroom storage with a residential rather than commercial impression.",
        "palette_direction": {"room": {"wall": "#F4F2EE matte mineral paint, solid", "floor": "#B9A88D oak, natural grain"}, "bath": {"towels": "#8A999E cotton, solid"}},
        "photography_direction": "Bright clear exposure, neutral white balance, soft contrast and truthful painted-wood response.",
        "environment_and_staging": "Restrained US bathroom styling with newly selected towels and ceramic containers; do not copy source props.",
        "typography_direction": {"font_family": "Inter", "title_style": "Semibold sentence case", "body_style": "Regular with readable spacing", "numeric_style": "Tabular figures with unit spacing"},
        "graphic_direction": {"text_color": "#303634", "line_color": "#637470", "icon_color": "#303634", "backing_color": "#F4F2EE", "backed_symbol_color": "#303634", "icon_style": "outline", "line_style": "fine"},
    }


def current_observed_measurement(text='17 in', object_name='Cabinet', axis='width', *, key='width', kind='dimension', evidence_type=None):
    evidence_type = evidence_type or ('dimension_line' if kind == 'dimension' else 'text_spec')
    return {'measurement_id': key, 'text': text, 'object': object_name, 'axis': axis,
            'view_id': 'view_01', 'region': {'left': .2, 'top': .25, 'right': .3, 'bottom': .3}, 'kind': kind,
            'evidence_type': evidence_type,
            'endpoints': [{'x': .2, 'y': .4}, {'x': .7, 'y': .4}] if evidence_type == 'dimension_line' else None}


def current_image_direction(*, environment: str = "designed_environment", source_id: str = 'source_00') -> dict[str, Any]:
    return {"visual_goal": "Explain the visible physical feature at a glance",
            "presentation": {"scope": "whole_product", "state": "Show the complete product with its functional parts visible",
                             "components": ['room.wall', 'room.floor', 'bath.towels'] if environment == 'designed_environment' else []},
            "evidence_usage": [{"source_id": source_id, "view_id": "view_01", "usage": "display", "covered_by": []}],
            "design_transfer": [],
            "environment_mode": environment}


def current_image_task(
    role: str = "main",
    *,
    blocked_reason: str = "",
    source_sha256: str = "a" * 64,
    category_id: str = "bathroom_cabinet",
    reason_code: str = "",
    retryable: bool = False,
) -> dict[str, Any]:
    family = role.split("_", 1)[0]
    base: dict[str, Any] = {
        "schema_version": IMAGE_TASK_SCHEMA_VERSION,
        "policy_version": IMAGE_TASK_POLICY_VERSION,
        "category_id": category_id,
        "child": "B1",
        "role": role,
        "role_family": family,
        "logical_task_id": f"generate:B1:{role}",
        "output_dir": f"images/generated/B1/{role}",
        "prompt_contract_version": PROMPT_CONTRACT_VERSION,
        "category_image_policy": {},
        "formation_status": "blocked" if blocked_reason else "ready",
        "formation_reason": blocked_reason,
        "source_path": "" if blocked_reason else "images/source.png",
        "source_sha256": "" if blocked_reason else source_sha256,
    }
    if blocked_reason:
        base["formation_reason_code"] = reason_code or "deterministic_block"
        base['formation_failure_owner'] = 'review' if retryable else 'brief'
    else:
        story = (
            {
                "mode": "source_claims",
                "title": "Flexible Shelf Storage",
                "labels": ["Adjustable Shelf", "Open Storage Access"],
                "bindings": [
                    {"evidence_ids": ["title"], "text": "Flexible Shelf Storage"},
                    {"evidence_ids": ["label-1"], "text": "Adjustable Shelf"},
                    {"evidence_ids": ["label-2"], "text": "Open Storage Access"},
                ],
            }
            if family == "func"
            else {"mode": "source_claims" if family == "size" else "none", "title": "", "labels": [], "bindings": []}
        )
        strings = [story["title"], *story["labels"]] if family == "func" else []
        measurement = (
            {
                "mode": "source_image",
                "source_sha256": source_sha256,
                "source_intent_revision_id": "source-intent-revision",
                "render_text": [],
                "measurement_groups": [],
                "ocr_role": "definite_error_warning_only",
                "relationship_policy": "Preserve every source-visible measurement relationship exactly.",
            }
            if family == "size"
            else {"mode": "none", "render_text": [], "measurement_groups": []}
        )
        references = [
            {
                "kind": "edit_base", "child": "B1", "source_id": "source_00",
                "purpose": "Edit this product view", "evidence_ids": [],
                "path": "images/func-source.png" if family == "func" else "images/source.png",
                "sha256": source_sha256,
                "original_path": base["source_path"], "original_sha256": source_sha256,
                "view_id": "view_01", "extent": "whole_view",
                "visible_evidence": current_physical_view()['evidence'],
            }
        ]
        base.update({
            "family_design_id": "family-design",
            "family_art_direction": current_art_direction(),
            "source_intent_revision_id": "source-intent-revision",
            "source_index": 0,
            "generation_references": references,
            "edit_base_sha256": source_sha256,
            "reference_mode": f"{family}_source_edit",
            "product_facts": {
                "asin": "B1",
                "product_type": "BATHROOM_CABINET",
                "color": "soft white",
                "size": "",
                "variation": {},
                "sold_unit_count": 1,
            },
            "measurement_authority": measurement,
            "display_copy_contract": story,
            "renderable_text_contract": {
                "mode": (
                    "exact"
                    if family in {"func", "size"}
                    else "none"
                ),
                "strings": strings,
            },
            "image_direction": current_image_direction(),
            "edit_contract": _edit_contract(family, measurement, base["category_image_policy"]),
            "execution_profile": (
                "reference_infographic_design"
                if family == "func"
                else "source_size_visual_restyle"
                if family == "size"
                else "reference_edit_soft_lock"
            ),
        })
        if family == 'size':
            base['image_direction'] = current_image_direction(environment='graphic_canvas')
    base["task_fingerprint"] = _task_fingerprint(base)
    base["input_revision_id"] = base["task_fingerprint"]
    validate_image_task(base)
    return base


def current_prompt_artifact(
    job: str | Path,
    task: dict[str, Any],
) -> dict[str, Any]:
    row = _prompt_row(Path(job), task)
    validate_image_prompt(row)
    return {"schema_version": IMAGE_PROMPT_SCHEMA_VERSION, "prompts": [row]}
