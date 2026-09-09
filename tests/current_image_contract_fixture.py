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


def current_art_direction() -> dict[str, Any]:
    return {
        "audience_and_market": "US homeowners seeking calm, practical bathroom storage with a residential rather than commercial impression.",
        "palette_direction": "Use warm mineral neutrals around the soft-white cabinet, charcoal text, and one muted blue-gray accent so the product remains distinct.",
        "photography_direction": "Broad natural side light, soft contact shadows, truthful painted-wood response, and realistic residential depth.",
        "environment_and_staging": "Restrained US bathroom styling with newly selected towels and ceramic containers; do not copy source props.",
        "typography_direction": "Confident contemporary sans-serif hierarchy with highly legible short headlines and labels.",
        "graphic_direction": "Restrained technical lines and sparse icons integrated into the image without dashboard cards or sticker modules.",
        "cohesion_rule": "Repeat the same light behavior, typographic hierarchy, restrained line character, and negative-space rhythm across the family.",
        "negative_visuals": [
            "No dark solid advertising field behind the light cabinet.",
            "No floating UI cards, copied toiletries, unrelated saturated accents, or invented cabinet parts.",
        ],
    }


def current_image_task(
    role: str = "main",
    *,
    blocked_reason: str = "",
    source_sha256: str = "source-sha",
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
            else {"mode": "none", "title": "", "labels": [], "bindings": []}
        )
        strings = [story["title"], *story["labels"]] if family == "func" else []
        measurement = (
            {
                "mode": "source_image",
                "source_sha256": source_sha256,
                "source_intent_revision_id": "source-intent-revision",
                "preserve_entire_diagram": True,
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
                "kind": "editable_reference",
                "path": "images/func-source.png" if family == "func" else "images/source.png",
                "sha256": source_sha256,
            }
        ]
        base.update({
            "family_design_id": "family-design",
            "family_art_direction": current_art_direction(),
            "source_intent_revision_id": "source-intent-revision",
            "source_index": 0,
            "generation_references": references,
            "generation_reference_sha256": source_sha256,
            "reference_mode": f"{family}_source_edit",
            "product_facts": {
                "asin": "B1",
                "product_type": "BATHROOM_CABINET",
                "color": "soft white",
                "size": "",
                "variation": {},
                "sold_unit_count": 1,
            },
            "product_boundary": {
                "sold_product_parts": [
                    "the complete bathroom cabinet visible in the editable reference",
                    "all source-visible structural parts and attached hardware",
                ],
                "replaceable_staging": ["loose toiletries, towels, flowers, and wall decor"],
                "must_not_change": [
                    "product type, source-visible structure, proportions, quantity, color, finish, and attached parts",
                    "source-visible open or closed product state",
                ],
                "product_color_material": "color: soft white; painted engineered wood",
                "observed_product_colors": [
                    {"name": "soft white", "source": "ProductFamilyV3"}
                ],
                "conditional_structure_lock": [],
                "forbidden_additions": [],
            },
            "measurement_authority": measurement,
            "func_story_contract": story,
            "renderable_text_contract": {
                "mode": (
                    "exact"
                    if family == "func"
                    else "preserve_source_measurements"
                    if family == "size"
                    else "none"
                ),
                "strings": strings,
            },
            "role_purpose": (
                "Explain how the interior storage adapts to different items."
                if family == "func"
                else "Identify the sold product immediately."
            ),
            "image_direction": (
                "Keep the exact product as the dominant visual subject under the shared family direction."
                if family in {"main", "scene"}
                else "Use an editorial asymmetric feature composition with restrained callouts and generous product space under the shared child system."
                if family == "func"
                else "Use a spacious technical hierarchy with aligned measurements and the shared child typography, line, and badge system."
            ),
            "edit_contract": _edit_contract(family, measurement, base["category_image_policy"], {}, product_type=category_id),
            "execution_profile": (
                "reference_infographic_design"
                if family == "func"
                else "source_size_visual_restyle"
                if family == "size"
                else "reference_edit_soft_lock"
            ),
        })
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
