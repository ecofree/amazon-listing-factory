from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .final_source_intents import planning_source_intents, selected_task_source_intents
from .image_prompt_compiler import PROMPT_CONTRACT_VERSION
from .image_task_inputs import (
    build_func_story_contract,
    build_renderable_text_contract,
    execution_profile,
    func_renderable_text_contract,
    product_boundary,
    task_facts,
)
from .io import read_jsonl, write_jsonl
from .plugin import ProductPlugin
from .product_family import read_product_family
from .required_role_policy import compiled_image_policy, required_role_policy
from .run_scope import read_run_scope
from .status import input_revision_id, logical_task_id
from .visual_design_kit import compact_product_claims, read_visual_design_kits, visual_design_kit_row_current


IMAGE_TASK_SCHEMA_VERSION = "image-task-v8"
IMAGE_TASK_POLICY_VERSION = "program-facts-gemini-art-direction-v8-complete-design-kit"
IMAGE_TASK_ARTIFACT = "image_tasks_v8.jsonl"
_TASK_BASE_FIELDS = {"schema_version", "policy_version", "category_id", "child", "role", "role_family", "logical_task_id", "output_dir", "prompt_contract_version", "category_image_policy", "formation_status", "formation_reason", "formation_retryable", "source_path", "source_sha256", "task_fingerprint", "input_revision_id"}
_TASK_READY_FIELDS = _TASK_BASE_FIELDS | {"family_design_id", "family_art_direction", "source_intent_revision_id", "source_index", "generation_references", "generation_reference_sha256", "reference_mode", "product_facts", "product_boundary", "measurement_authority", "func_story_contract", "renderable_text_contract", "role_purpose", "image_direction", "edit_contract", "execution_profile"}
_TASK_BLOCKED_FIELDS = _TASK_BASE_FIELDS | {"formation_reason_code"}


class ImageTaskError(RuntimeError):
    pass


def build_image_tasks(*, job_dir: str | Path, plugin: ProductPlugin, workers: int = 0) -> dict[str, Any]:
    del workers
    job = Path(job_dir).resolve()
    rows = _expected_rows(job, plugin)
    write_jsonl(job / "reports" / IMAGE_TASK_ARTIFACT, rows)
    failures = [
        _task_failure(row)
        for row in rows
        if row["formation_status"] == "blocked"
        and row.get("formation_reason_code") != "upstream_design_kit_missing"
    ]
    scope = read_run_scope(job)
    coverage = executable_coverage(rows, list(scope["selected_children"]), required_role_policy(plugin).counts)
    selected_sources = {
        (str(row.get("child") or ""), str(row.get("source_path") or ""))
        for row in rows
        if row.get("source_path")
    }
    not_selected = [
        {
            "child": str(source.get("child") or ""),
            "source_index": int(source.get("source_index") or 0),
            "role": str(source.get("role") or ""),
            "status": "classified_not_selected",
        }
        for source in planning_source_intents(job, plugin=plugin)
        if (str(source.get("child") or ""), str(source.get("source_path") or "")) not in selected_sources
    ]
    return {
        "schema_version": IMAGE_TASK_SCHEMA_VERSION,
        "tasks": rows,
        "failures": failures,
        "executable_coverage": coverage,
        "source_selection_audit": not_selected,
    }


def read_image_tasks(job_dir: str | Path, *, category_id: str = "") -> dict[str, Any]:
    path = Path(job_dir) / "reports" / IMAGE_TASK_ARTIFACT
    if not path.is_file():
        raise ImageTaskError(f"ImageTaskV8 is missing: {path}")
    rows = read_jsonl(path)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        validate_image_task(row)
        if category_id and row["category_id"] != category_id:
            raise ImageTaskError("ImageTaskV8 category does not match the active plugin")
        key = (str(row["child"]), str(row["role"]))
        if key in seen:
            raise ImageTaskError(f"ImageTaskV8 has a duplicate row: {key[0]}/{key[1]}")
        seen.add(key)
    return {"schema_version": IMAGE_TASK_SCHEMA_VERSION, "task_count": len(rows), "tasks": rows}


def image_tasks_current(job_dir: str | Path, plugin: ProductPlugin, limit: int = 0) -> bool:
    del limit
    try:
        actual = read_image_tasks(job_dir, category_id=plugin.category_id)["tasks"]
        expected = _expected_rows(Path(job_dir).resolve(), plugin)
        return {
            (row["child"], row["role"]): row["task_fingerprint"] for row in actual
        } == {
            (row["child"], row["role"]): row["task_fingerprint"] for row in expected
        }
    except Exception:
        return False


def role_prefix(role: Any) -> str:
    value = str(role or "").split("_", 1)[0]
    return value if value in {"main", "scene", "func", "size"} else ""


def validate_task_inventory(tasks: list[dict[str, Any]], expected_children: list[str], required: dict[str, int]) -> None:
    expected = set(map(str, expected_children))
    seen: set[tuple[str, str]] = set()
    for task in tasks:
        key = (str(task.get("child") or ""), str(task.get("role") or ""))
        if key in seen or key[0] not in expected or role_prefix(key[1]) not in required:
            raise ImageTaskError(f"Invalid ImageTaskV8 inventory row: {key}")
        seen.add(key)


def executable_coverage(
    tasks: list[dict[str, Any]], expected_children: list[str], required: dict[str, int],
) -> dict[str, Any]:
    children: dict[str, dict[str, Any]] = {}
    for child in map(str, expected_children):
        ready_counts = {
            family: sum(
                1 for task in tasks
                if task.get("child") == child
                and role_prefix(task.get("role")) == family
                and task.get("formation_status") == "ready"
            )
            for family in required
        }
        missing = [family for family, count in required.items() if ready_counts[family] < int(count)]
        children[child] = {
            "status": "ready" if not missing else "partial",
            "ready_counts": ready_counts,
            "missing_required_roles": missing,
        }
    return {
        "status": "ready" if children and all(row["status"] == "ready" for row in children.values()) else "partial",
        "children": children,
    }


def validate_image_task(row: Any) -> None:
    if not isinstance(row, dict) or row.get("schema_version") != IMAGE_TASK_SCHEMA_VERSION:
        raise ImageTaskError("Invalid ImageTaskV8")
    expected = _TASK_READY_FIELDS if row.get("formation_status") == "ready" else _TASK_BLOCKED_FIELDS
    if set(row) != expected:
        raise ImageTaskError(f"ImageTaskV8 has unknown or missing fields: {sorted(set(row) ^ expected)}")
    required = (
        "policy_version", "category_id", "child", "role", "role_family",
        "formation_status", "logical_task_id", "input_revision_id", "task_fingerprint",
        "output_dir", "prompt_contract_version",
    )
    missing = [key for key in required if row.get(key) in (None, "", [], {})]
    if missing or row.get("policy_version") != IMAGE_TASK_POLICY_VERSION:
        raise ImageTaskError(f"ImageTaskV8 is incomplete: {missing}")
    if row["formation_status"] not in {"ready", "blocked"}:
        raise ImageTaskError("ImageTaskV8 formation status is invalid")
    if row["formation_status"] == "ready":
        needed = (
            "family_design_id", "family_art_direction", "source_path", "source_sha256",
            "source_intent_revision_id", "generation_references", "product_boundary",
            "measurement_authority", "func_story_contract", "renderable_text_contract",
            "role_purpose", "edit_contract", "execution_profile",
        )
        if row.get("role_family") in {"main", "scene"}:
            needed += ("image_direction",)
        absent = [key for key in needed if row.get(key) in (None, "", [], {})]
        if absent:
            raise ImageTaskError(f"Ready ImageTaskV8 is incomplete: {absent}")
        if len(row["generation_references"]) != 1:
            raise ImageTaskError("Ready ImageTaskV8 must have exactly one editable reference")
        reference = row["generation_references"][0]
        if reference.get("kind") != "editable_reference" or reference.get("sha256") != row["source_sha256"]:
            raise ImageTaskError("ImageTaskV8 editable reference is inconsistent")
        boundary = row["product_boundary"]
        if set(boundary) != {"sold_product_parts", "replaceable_staging", "must_not_change", "product_color_material", "observed_product_colors", "conditional_structure_lock", "forbidden_additions"}:
            raise ImageTaskError("ImageTaskV8 product boundary is not canonical")
        if row["role_family"] == "func":
            expected = func_renderable_text_contract(row.get("func_story_contract") or {})
        else:
            expected = build_renderable_text_contract(row["role_family"], row["measurement_authority"])
        if row["renderable_text_contract"] != expected:
                raise ImageTaskError("ImageTaskV8 renderable text changed after formation")
        edit = row.get("edit_contract")
        if not isinstance(edit, dict) or set(edit) != {"create", "reference_authority", "preserve", "replace", "forbid", "reference_completeness"}:
            raise ImageTaskError("ImageTaskV8 edit contract is not canonical")
    if row.get("task_fingerprint") != _task_fingerprint(row):
            raise ImageTaskError("ImageTaskV8 content changed")


def _expected_rows(job: Path, plugin: ProductPlugin) -> list[dict[str, Any]]:
    family = read_product_family(job)
    product_type = str(family["family"].get("product_type") or plugin.product_type)
    children = {str(row["asin"]): row for row in family["family"]["children"]}
    selected = [asin for asin in read_run_scope(job)["selected_children"] if asin in children]
    sources_by_child: dict[str, list[dict[str, Any]]] = {}
    for row in selected_task_source_intents(job, plugin=plugin):
        sources_by_child.setdefault(str(row["child"]), []).append(row)
    all_kits = read_visual_design_kits(job, plugin=plugin).get("children") or {}
    image_policy = compiled_image_policy(plugin)
    kits = {
        asin: row for asin, row in all_kits.items()
        if asin in children and visual_design_kit_row_current(
            job, plugin, asin, row, child_row=children[asin],
            sources=sources_by_child.get(asin, []), policy=image_policy,
        )
    }
    rows: list[dict[str, Any]] = []
    for asin in selected:
        specs = _task_specs(children[asin], sources_by_child.get(asin, []))
        for spec in specs:
            rows.append(_form_task(
                plugin=plugin, child=children[asin], spec=spec,
                design_kit=kits.get(asin), image_policy=image_policy,
                product_type=product_type,
            ))
    return sorted(rows, key=lambda row: (row["child"], _role_sort_key(row["role"])))


def _task_specs(
    child: dict[str, Any], sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted(sources, key=lambda row: int(row.get("source_index") or 0))
    by_role = {role: [row for row in ordered if row.get("role") == role] for role in ("main", "scene", "func", "size")}
    specs: list[dict[str, Any]] = []
    mains = by_role["main"]
    main = mains[0] if len(mains) == 1 else None
    specs.append({
        "role": "main", "source": main, "main": main,
        "reason": "" if main else "FinalSourceIntent must contain exactly one main authority",
        "evidence_pending": main is None,
    })
    for family in ("scene", "func"):
        matches = by_role[family]
        if matches:
            for index, source in enumerate(matches, 1):
                specs.append({"role": _numbered(family, index), "source": source, "main": main, "reason": "", "evidence_pending": False})
        else:
            specs.append({"role": family, "source": None, "main": main, "reason": f"no final source intent is classified as {family}", "evidence_pending": True})
    sizes = by_role["size"]
    if len(sizes) == 1:
        specs.append({"role": "size", "source": sizes[0], "main": main, "reason": "", "evidence_pending": False})
    elif len(sizes) > 1:
        specs.append({"role": "size", "source": None, "main": main, "reason": "FinalSourceIntent contains multiple size authorities", "evidence_pending": True})
    else:
        specs.append({"role": "size", "source": None, "main": main, "reason": "no final source intent is classified as size", "evidence_pending": True})
    counts = {family: sum(role_prefix(row["role"]) == family for row in specs) for family in ("main", "scene", "func", "size")}
    seen: dict[str, int] = {}
    for spec in specs:
        family = role_prefix(spec["role"])
        seen[family] = seen.get(family, 0) + 1
        spec["instance_index"] = seen[family]
        spec["instance_count"] = counts[family]
    return specs


def _form_task(
    *, plugin: ProductPlugin, child: dict[str, Any], spec: dict[str, Any],
    design_kit: dict[str, Any] | None, image_policy: dict[str, Any],
    product_type: str,
) -> dict[str, Any]:
    role = str(spec["role"])
    family = role_prefix(role)
    source = spec.get("source")
    source_path = str((source or {}).get("source_path") or "")
    source_sha256 = str((source or {}).get("source_sha256") or "")
    base = {
        "schema_version": IMAGE_TASK_SCHEMA_VERSION,
        "policy_version": IMAGE_TASK_POLICY_VERSION,
        "category_id": plugin.category_id,
        "child": str(child["asin"]),
        "role": role,
        "role_family": family,
        "logical_task_id": logical_task_id("generate", child=str(child["asin"]), role=role),
        "output_dir": f"images/generated/{child['asin']}/{role}",
        "prompt_contract_version": PROMPT_CONTRACT_VERSION,
        "category_image_policy": image_policy,
        "source_path": source_path,
        "source_sha256": source_sha256,
    }
    if not isinstance(design_kit, dict):
        return _blocked(
            base,
            "visual design kit is missing",
            retryable=True,
            reason_code="upstream_design_kit_missing",
        )
    art_direction = design_kit.get("family_art_direction")
    if not isinstance(art_direction, dict):
        return _blocked(base, "visual design kit has no family_art_direction")
    if not source:
        return _blocked(
            base,
            str(spec.get("reason") or "role evidence is missing"),
            # A missing role source is deterministic for the current source
            # inventory.  Mark only this role blocked; it must not be retried
            # indefinitely or invalidate ready roles in the same child/family.
            retryable=False,
            reason_code="source_evidence_missing" if spec.get("evidence_pending") else "",
        )
    source_brief = _source_brief(design_kit, source, family, allow_missing=family == "main")
    if source_brief is None and family != "main":
        return _blocked(base, "visual design kit has no matching source brief")
    try:
        measurement = _measurement_authority(family, child, source)
        source_reference = _source_reference(design_kit, source)
        editable_source = _editable_source_for_task(
            source, spec.get("main"), family=family, product_type=product_type,
        )
        story = (
            build_func_story_contract(
                source,
                source_brief or {},
                product_claims=_shared_product_claims(design_kit, child),
            )
            if family == "func" else {
                "mode": "none", "title": "", "labels": [], "bindings": [],
            }
        )
        renderable = (
            func_renderable_text_contract(story)
            if family == "func" else build_renderable_text_contract(family, measurement)
        )
        boundary = product_boundary(
            image_policy,
            child,
            product_type=product_type,
        )
        reference = _reference(editable_source)
        reference_mode = _reference_mode(family, source, editable_source)
        purpose = _role_purpose(family, source_brief, measurement)
        fields = {
            **base,
            "family_design_id": str(design_kit.get("family_design_id") or design_kit.get("input_revision_id") or ""),
            "family_art_direction": art_direction,
            "source_intent_revision_id": str(source.get("input_revision_id") or ""),
            "source_index": int(source.get("source_index") or 0),
            "source_path": reference["path"],
            "source_sha256": reference["sha256"],
            "generation_references": [reference],
            "generation_reference_sha256": reference["sha256"],
            "reference_mode": reference_mode,
            "product_facts": task_facts(child, product_type=product_type),
            "product_boundary": boundary,
            "measurement_authority": measurement,
            "func_story_contract": story,
            "renderable_text_contract": renderable,
            "role_purpose": purpose,
            "image_direction": (
                _main_image_direction(image_policy)
                if family == "main"
                else str((source_brief or {}).get("image_direction") or "").strip()
                if family == "scene"
                else ""
            ),
            "edit_contract": _edit_contract(
                family, measurement, image_policy, source_brief or {},
                reference_completeness=str((editable_source.get("signals") or {}).get("reference_completeness") or ""),
                reference_role=("main" if editable_source is not source else family),
            ),
            "execution_profile": execution_profile(family, measurement),
            "formation_status": "ready",
            "formation_reason": "",
            "formation_retryable": False,
        }
    except Exception as exc:
        return _blocked(base, f"{type(exc).__name__}: {exc}")
    fields["task_fingerprint"] = _task_fingerprint(fields)
    fields["input_revision_id"] = fields["task_fingerprint"]
    return fields


def _editable_source_for_task(
    source: dict[str, Any], main: dict[str, Any] | None, *,
    family: str, product_type: str,
) -> dict[str, Any]:
    """Choose one editable image without letting a partial tree detail invent identity."""
    completeness = str((source.get("signals") or {}).get("reference_completeness") or "").strip()
    if (
        family == "func"
        and str(product_type or "").strip().casefold() == "artificial_tree"
        and completeness in {"partial_feature_view", "scene_context_only"}
        and isinstance(main, dict)
        and str(main.get("source_path") or "").strip()
        and str(main.get("source_sha256") or "").strip()
    ):
        return main
    return source


def _reference_mode(
    family: str, source: dict[str, Any], editable_source: dict[str, Any],
) -> str:
    if family == "func" and editable_source is not source:
        return "func_main_identity_edit"
    return f"{family}_source_edit"


def _main_image_direction(image_policy: dict[str, Any]) -> str:
    if image_policy.get("main_image_policy") == "white_background":
        return (
            "Make the exact sold product immediately legible on a uniform white canvas, "
            "using source-faithful lighting and only permitted functional staging."
        )
    return (
        "Present the exact sold product as the unmistakable hero in a credible US-home "
        "setting that differs clearly from the supporting lifestyle images."
    )


def _source_brief(
    design_kit: dict[str, Any], source: dict[str, Any], family: str, *, allow_missing: bool,
) -> dict[str, Any] | None:
    revision = str(source.get("input_revision_id") or "")
    sha = str(source.get("source_sha256") or "")
    matches = [
        row for row in design_kit.get("source_briefs") or []
        if isinstance(row, dict)
        and str(row.get("role") or "") == family
        and str(row.get("source_intent_revision_id") or "") == revision
        and str(row.get("source_sha256") or "") == sha
    ]
    if len(matches) == 1:
        return matches[0]
    if allow_missing and not matches:
        return None
    raise ImageTaskError("source brief is missing or duplicated")


def _source_reference(
    design_kit: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    revision = str(source.get("input_revision_id") or "")
    sha = str(source.get("source_sha256") or "")
    matches = [
        row
        for row in design_kit.get("source_references") or []
        if isinstance(row, dict)
        and str(row.get("input_revision_id") or "") == revision
        and str(row.get("source_sha256") or "") == sha
    ]
    if len(matches) != 1:
        raise ImageTaskError("visual design kit source reference is missing or duplicated")
    return matches[0]


def _shared_product_claims(
    design_kit: dict[str, Any],
    child: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve child-level product facts once, independent of source role."""
    unique: dict[str, dict[str, Any]] = {}
    for source in design_kit.get("source_references") or []:
        for claim in source.get("product_claims") or []:
            if isinstance(claim, dict) and str(claim.get("evidence_id") or ""):
                unique.setdefault(str(claim["evidence_id"]), claim)
    return list(unique.values()) or compact_product_claims(child)


def _reference(source: dict[str, Any]) -> dict[str, str]:
    path = str(source.get("source_path") or "")
    sha = str(source.get("source_sha256") or "")
    if not path or not sha:
        raise ImageTaskError("editable reference path or SHA is missing")
    return {"kind": "editable_reference", "path": path, "sha256": sha}


def _measurement_authority(family: str, child: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    del child
    if family != "size":
        return {"mode": "none", "render_text": [], "measurement_groups": []}
    if source.get("role") == "size":
        measurements = [
            {
                "id": f"source:{index}",
                "measured_part": "source_visible",
                "axis": "source_diagram",
                "kind": "measurement",
                "canonical_value": str(row.get("canonical_pair") or ""),
                "render_text": str(row.get("text") or "").strip(),
                "confidence": str(row.get("confidence") or "source_visible"),
                # A load-capacity callout is factual evidence even when it is
                # drawn inside an icon/badge rather than on a dimension line.
                "measurement_role": _measurement_role(str(row.get("text") or "")),
                "presentation": "source_visible_capacity_callout"
                if _measurement_role(str(row.get("text") or "")) == "load_capacity"
                else "source_visible_measurement",
            }
            for index, row in enumerate(source.get("measurements") or [], 1)
            if isinstance(row, dict) and str(row.get("text") or "").strip()
        ]
        return {
            "mode": "source_image", "source_sha256": str(source.get("source_sha256") or ""),
            "source_intent_revision_id": str(source.get("input_revision_id") or ""),
            "preserve_entire_diagram": True,
            "render_text": list(dict.fromkeys(row["render_text"] for row in measurements)),
            "measurement_groups": measurements,
            "ocr_role": "definite_error_warning_only",
            "relationship_policy": "Preserve each label, line, endpoint, measured part, and product-instance association exactly as shown.",
        }
    raise ImageTaskError("Size task requires one source image classified as size")


def _measurement_role(text: str) -> str:
    """Classify source-visible numeric evidence without changing its value."""
    normalized = " ".join(text.casefold().replace("–", "-").split())
    if re.search(r"\b(?:lb|lbs|pounds?)\b", normalized):
        return "load_capacity"
    return "dimension"


def _role_purpose(family: str, brief: dict[str, Any] | None, measurement: dict[str, Any]) -> str:
    if brief:
        purpose = str(brief.get("shopping_purpose") or "").strip()
        if purpose:
            return purpose
    return {
        "main": "Help shoppers identify the exact sold product immediately.",
        "scene": "Show the exact sold product in a realistic US home setting that explains scale and use without changing the product.",
        "size": "Show the complete source measurement system without omission.",
    }.get(family, "")


def _edit_contract(
    family: str, measurement: dict[str, Any], policy: dict[str, Any],
    brief: dict[str, Any], *, reference_completeness: str = "",
    reference_role: str = "",
) -> dict[str, Any]:
    del brief
    create = {
        "main": "Create one square Amazon US main image.",
        "scene": "Create one square Amazon US lifestyle image.",
        "func": "Create one square Amazon US function image.",
        "size": "Create one square Amazon US size image.",
    }[family]
    reference = {
        "main": "The editable main reference is the sole sold-product identity and visible-state authority.",
        "scene": "The editable scene reference is the sole sold-product identity and visible-state authority.",
        "func": "The editable function reference is the sole sold-product identity, demonstrated state, and part-relationship authority.",
        "size": "The editable size reference is the sole sold-product identity and complete measurement-diagram authority.",
    }.get(reference_role or family, "The editable reference is the sole sold-product identity and visible-state authority.")
    reference += (
        " Preserve the product itself from that reference. Do not change the product type, color, visible structure, "
        "proportions, key parts, or source-visible open/closed state."
    )
    preserve = [
        "The complete sold product and every source-visible structural relationship",
    ]
    replace: list[str] = []
    if family == "size" and measurement.get("mode") == "source_image":
        preserve.extend([
            "Every visible number, unit, line direction, endpoint, measured part, and label-to-line relationship",
            "The association between each measurement line and the exact single product instance or part it measures",
        ])
    if family == "main" and policy.get("main_image_policy") == "white_background":
        replace.append("External canvas with uniform pure white")
    elif family == "scene":
        replace.append(
            "Restyle the surrounding room; preserve state-bearing staging presence, coverage, placement, and relationship, while loose decor may be restyled or substituted"
        )
    elif family == "func":
        replace.append(
            "Restyle only the non-product presentation around the visible feature; preserve staging that establishes product use or scale, while loose decor may be restyled or substituted"
        )
    elif family == "size":
        replace.append(
            "Restyle only background, banner, typography, and line treatment; preserve the complete visible product state and measurement diagram"
        )
    allowed_props = [str(value) for value in policy.get("allowed_internal_props") or [] if str(value).strip()]
    if allowed_props:
        replace.append(
            "Only where that surface or compartment is already visible/open in the editable reference, "
            "non-sold staging may use: " + "; ".join(allowed_props)
        )
    role_rules = [
        str(value) for value in (policy.get("role_specific_rules") or {}).get(family) or []
        if str(value).strip()
    ]
    forbid = [
        "Do not invent product parts, functions, dimensions, quantities, logos, watermarks, or readable text",
        *role_rules,
    ]
    return {
        "create": create,
        "reference_authority": reference,
        "preserve": list(dict.fromkeys(str(value).strip() for value in preserve if str(value).strip())),
        "replace": list(dict.fromkeys(str(value).strip() for value in replace if str(value).strip())),
        "forbid": list(dict.fromkeys(str(value).strip() for value in forbid if str(value).strip())),
        "reference_completeness": reference_completeness or "partial_feature_view",
    }


def _blocked(base: dict[str, Any], reason: str, *, retryable: bool = False, reason_code: str = "") -> dict[str, Any]:
    row = {
        **base, "formation_status": "blocked", "formation_reason": reason,
        "formation_retryable": bool(retryable),
        "formation_reason_code": reason_code or ("retryable" if retryable else "deterministic_block"),
    }
    row["task_fingerprint"] = _task_fingerprint(row)
    row["input_revision_id"] = row["task_fingerprint"]
    return row


def _task_fingerprint(row: dict[str, Any]) -> str:
    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items() if key not in {"task_fingerprint", "input_revision_id"}}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value
    return input_revision_id(strip(row))


def _task_failure(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": {
            "logical_task_id": logical_task_id("brief", child=row["child"], role=row["role"]),
            "input_revision_id": row["input_revision_id"], "child": row["child"], "role": row["role"],
        },
        "failure_owner": "brief",
        "task_status": "retryable" if row.get("formation_retryable") else "blocked",
        "error": row.get("formation_reason") or "image task blocked",
    }


def _numbered(role: str, index: int) -> str:
    return role if index == 1 else f"{role}_{index:02d}"


def _role_sort_key(role: str) -> tuple[int, str]:
    return ({"main": 0, "scene": 1, "func": 2, "size": 3}.get(role_prefix(role), 9), role)
