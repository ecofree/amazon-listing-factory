from __future__ import annotations

from pathlib import Path
from typing import Any

from .final_source_intents import planning_source_intents, selected_task_source_intents
from .image_prompt_compiler import PROMPT_CONTRACT_VERSION, compile_task_prompt
from .image_reference_context import validate_reference_set, resolve_edit_references, evidence_view_catalog, view_identity, reference_semantics
from .image_task_inputs import (
    build_display_copy_contract,
    build_renderable_text_contract,
    execution_profile,
    task_specs,
    task_facts,
)
from .io import read_jsonl, write_jsonl
from .plugin import ProductPlugin
from .product_family import read_product_family
from .required_role_policy import compiled_image_policy, required_role_policy
from .run_scope import read_run_scope
from .status import input_revision_id, logical_task_id
from .text_evidence import us_measurement_text
from .visual_design_kit import read_visual_design_kits, visual_design_kit_row_current


IMAGE_TASK_SCHEMA_VERSION = "image-task-v12"
IMAGE_TASK_POLICY_VERSION = "output-evidence-child-direction-v42-recoverable-facts"
IMAGE_TASK_ARTIFACT = "image_tasks_v12.jsonl"
_TASK_BASE_FIELDS = {"schema_version", "policy_version", "category_id", "child", "role", "role_family", "logical_task_id", "output_dir", "prompt_contract_version", "category_image_policy", "formation_status", "formation_reason", "source_path", "source_sha256", "task_fingerprint", "input_revision_id"}
_TASK_READY_FIELDS = _TASK_BASE_FIELDS | {"family_design_id", "family_art_direction", "source_intent_revision_id", "source_index", "generation_references", "edit_base_sha256", "reference_mode", "product_facts", "measurement_authority", "display_copy_contract", "renderable_text_contract", "image_direction", "edit_contract", "execution_profile"}
_TASK_BLOCKED_FIELDS = _TASK_BASE_FIELDS | {"formation_reason_code", "formation_failure_owner"}


class ImageTaskError(RuntimeError):
    pass


def build_image_tasks(
    *, job_dir: str | Path, plugin: ProductPlugin, workers: int = 0,
    include_optional: bool = False,
) -> dict[str, Any]:
    del workers
    job = Path(job_dir).resolve()
    rows = _expected_rows(job, plugin, include_optional=include_optional)
    for row in rows:
        validate_image_task(row)
    write_jsonl(job / "reports" / IMAGE_TASK_ARTIFACT, rows)
    failures = [_task_failure(row) for row in rows if row["formation_status"] == "blocked"]
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
        raise ImageTaskError(f"ImageTask is missing: {path}")
    rows = read_jsonl(path)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        validate_image_task(row)
        if category_id and row["category_id"] != category_id:
            raise ImageTaskError("ImageTask category does not match the active plugin")
        key = (str(row["child"]), str(row["role"]))
        if key in seen:
            raise ImageTaskError(f"ImageTask has a duplicate row: {key[0]}/{key[1]}")
        seen.add(key)
    return {"schema_version": IMAGE_TASK_SCHEMA_VERSION, "task_count": len(rows), "tasks": rows,
            "failures": [_task_failure(row) for row in rows if row['formation_status'] == 'blocked']}


def image_tasks_current(
    job_dir: str | Path, plugin: ProductPlugin, limit: int = 0,
    *, include_optional: bool = False,
) -> bool:
    del limit
    try:
        actual = read_image_tasks(job_dir, category_id=plugin.category_id)["tasks"]
        expected = _expected_rows(Path(job_dir).resolve(), plugin, include_optional=include_optional)
        # Candidate reuse is semantic; artifact currentness also refreshes paths and approvals.
        return {
            (row["child"], row["role"]): row for row in actual
        } == {
            (row["child"], row["role"]): row for row in expected
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
            raise ImageTaskError(f"Invalid ImageTask inventory row: {key}")
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
        raise ImageTaskError("Invalid ImageTask")
    expected = _TASK_READY_FIELDS if row.get("formation_status") == "ready" else _TASK_BLOCKED_FIELDS
    if set(row) != expected:
        raise ImageTaskError(f"ImageTask has unknown or missing fields: {sorted(set(row) ^ expected)}")
    required = (
        "policy_version", "category_id", "child", "role", "role_family",
        "formation_status", "logical_task_id", "input_revision_id", "task_fingerprint",
        "output_dir", "prompt_contract_version",
    )
    missing = [key for key in required if row.get(key) in (None, "", [], {})]
    if missing or row.get("policy_version") != IMAGE_TASK_POLICY_VERSION:
        mismatch = ""
        if row.get("policy_version") != IMAGE_TASK_POLICY_VERSION:
            mismatch = (
                f" policy_version found={row.get('policy_version')!r} "
                f"expected={IMAGE_TASK_POLICY_VERSION!r}; task_fingerprint={row.get('task_fingerprint')!r}"
            )
        raise ImageTaskError(
            f"ImageTask is incomplete: missing={missing};{mismatch} "
            "regenerate the current ImageTask artifact from the active brief contract"
        )
    if row["formation_status"] not in {"ready", "blocked"}:
        raise ImageTaskError("ImageTask formation status is invalid")
    if row['formation_status'] == 'blocked' and (
            row['formation_failure_owner'] not in {'brief', 'observation', 'shared_design', 'review'}
            or not row['formation_reason'] or not row['formation_reason_code']):
        raise ImageTaskError('Blocked ImageTask has no valid failure responsibility')
    if row["formation_status"] == "ready":
        needed = (
            "family_design_id", "family_art_direction", "source_path", "source_sha256",
            "source_intent_revision_id", "generation_references",
            "measurement_authority", "display_copy_contract", "renderable_text_contract",
            "edit_contract", "execution_profile",
        )
        if row.get("role_family") in {"main", "scene"}:
            needed += ("image_direction",)
        absent = [key for key in needed if row.get(key) in (None, "", [], {})]
        if absent:
            raise ImageTaskError(f"Ready ImageTask is incomplete: {absent}")
        references = row["generation_references"]
        try:
            validate_reference_set(references, child=row["child"], edit_base_sha256=row["edit_base_sha256"])
        except ValueError as exc:
            raise ImageTaskError(str(exc)) from exc
        expected = build_renderable_text_contract(row["role_family"], row["measurement_authority"], display_copy=row['display_copy_contract'])
        if row["renderable_text_contract"] != expected:
                raise ImageTaskError("ImageTask renderable text changed after formation")
        edit = row.get("edit_contract")
        if not isinstance(edit, dict) or set(edit) != {"create", "reference_authority", "preserve", "replace", "forbid", "reference_completeness"}:
            raise ImageTaskError("ImageTask edit contract is not canonical")
    if row.get("task_fingerprint") != _task_fingerprint(row):
        raise ImageTaskError("ImageTask content changed")


def _expected_rows(job: Path, plugin: ProductPlugin, *, include_optional: bool = False) -> list[dict[str, Any]]:
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
        design_kit = kits.get(asin)
        if not isinstance(design_kit, dict):
            # The brief/design-kit task is the single authority for this
            # failure.  Do not fan one upstream failure out into a blocked
            # ImageTask for every expected role.
            continue
        specs = task_specs(
            children[asin], sources_by_child.get(asin, []), include_optional=include_optional,
        )
        for spec in specs:
            rows.append(_form_task(
                job=job, plugin=plugin, child=children[asin], spec=spec,
                design_kit=design_kit, image_policy=image_policy,
                product_type=product_type,
            ))
    return sorted(rows, key=lambda row: (row["child"], _role_sort_key(row["role"])))


def _form_task(
    *, job: Path, plugin: ProductPlugin, child: dict[str, Any], spec: dict[str, Any],
    design_kit: dict[str, Any], image_policy: dict[str, Any],
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
            reason_code="source_evidence_missing" if spec.get("evidence_pending") else "",
        )
    image_brief = _image_brief(design_kit, source, role)
    if image_brief.get("status") != "ready":
        return _blocked(base, str(image_brief.get("error") or "source brief is pending"),
                        reason_code='source_observation_unresolved' if image_brief.get('failure_owner') == 'observation' else '',
                        failure_owner=image_brief.get('failure_owner', 'brief'))
    try:
        image_direction = image_brief["image_direction"]
        catalog = evidence_view_catalog(design_kit['source_references'])
        selected = [catalog[view_identity(row)] for row in image_direction['evidence_usage'] if row['usage'] != 'verification']
        measurement = _measurement_authority(family, source, selected)
        story = (
            build_display_copy_contract(
                design_kit['source_references'],
                image_brief or {},
                product_claims=design_kit['product_claims'],
            )
            if family in {"func", "size"} else {
                "mode": "none", "title": "", "labels": [], "bindings": [],
            }
        )
        renderable = build_renderable_text_contract(family, measurement, display_copy=story)
        references = resolve_edit_references(
            image_brief, design_kit['source_references'], job=job, child=str(child["asin"]),
            design_references=design_kit['approved_design_references'],
        )
        reference = references[0]
        fields = {
            **base,
            "family_design_id": str(design_kit.get("family_design_id") or design_kit.get("input_revision_id") or ""),
            "family_art_direction": art_direction,
            "source_intent_revision_id": str(source.get("input_revision_id") or ""),
            "source_index": int(source.get("source_index") or 0),
            "source_path": source["source_path"],
            "source_sha256": source["source_sha256"],
            "generation_references": references,
            "edit_base_sha256": reference["sha256"],
            "reference_mode": f"{family}_source_edit",
            "product_facts": task_facts(child, product_type=product_type),
            "measurement_authority": measurement,
            "display_copy_contract": story,
            "renderable_text_contract": renderable,
            "image_direction": image_direction,
            "edit_contract": _edit_contract(
                family, measurement, image_policy,
                reference_completeness=str((source.get("signals") or {}).get("reference_completeness") or ""),
            ),
            "execution_profile": execution_profile(family, measurement),
            "formation_status": "ready",
            "formation_reason": "",
        }
        fields["task_fingerprint"] = _task_fingerprint(fields)
        fields["input_revision_id"] = fields["task_fingerprint"]
    except Exception as exc:
        return _blocked(base, f"{type(exc).__name__}: {exc}")
    return fields


def _image_brief(
    design_kit: dict[str, Any], source: dict[str, Any], role: str,
) -> dict[str, Any]:
    revision = str(source.get("input_revision_id") or "")
    sha = str(source.get("source_sha256") or "")
    matches = [
        row for row in design_kit.get("image_briefs") or []
        if isinstance(row, dict)
        and str(row.get("role") or "") == role
        and str(row.get("source_intent_revision_id") or "") == revision
        and str(row.get("source_sha256") or "") == sha
    ]
    if len(matches) == 1:
        return matches[0]
    raise ImageTaskError("source brief is missing or duplicated")


def _measurement_authority(family: str, source: dict[str, Any], selected: list[tuple[dict, dict]]) -> dict[str, Any]:
    inputs = [(owner, row) for owner, view in selected for row in owner.get('measurements', []) if row['view_id'] == view['view_id']]
    has_func_measurement = family == "func" and bool(inputs or (source.get("visual_evidence") or {}).get("has_dimension_lines"))
    if family != "size" and not has_func_measurement:
        return {"mode": "none", "render_text": [], "measurement_groups": []}
    if source.get("role") == "size" or has_func_measurement:
        if source.get('measurements') and not inputs:
            raise ImageTaskError('The selected views omit the required measured product; repair the size/function brief')
        measurements = [
            {
                "id": owner['source_id'] + ':' + row['source_occurrence'],
                "source_id": owner['source_id'],
                "source_text": str(row.get("text") or "").strip(),
                "measured_part": row['source_label'],
                "axis": row['axis_hint'],
                **{key: row[key] for key in ('view_id', 'source_region', 'source_endpoints', 'evidence_type')},
                "kind": "measurement",
                "canonical_value": str(row.get("canonical_pair") or ""),
                "render_text": us_measurement_text(row.get("text"), upper_bound="capacity" in str(row.get("source_label") or "").lower()),
                "confidence": str(row.get("confidence") or "source_visible"),
                "measurement_role": 'load_capacity' if row['measurement_kind'] == 'capacity' else row['measurement_kind'],
            }
            for owner, row in inputs
            if isinstance(row, dict) and str(row.get("text") or "").strip()
        ]
        return {
            "mode": "source_image", "source_sha256": str(source.get("source_sha256") or ""),
            "source_intent_revision_id": str(source.get("input_revision_id") or ""),
            "render_text": list(dict.fromkeys(row["render_text"] for row in measurements)),
            "measurement_groups": measurements,
            "ocr_role": "definite_error_warning_only",
            "relationship_policy": "Preserve physical quantities, measured parts, endpoints and product-instance associations; display the authorized US-unit labels.",
        }
    raise ImageTaskError("Size task requires one source image classified as size")


def _edit_contract(
    family: str, measurement: dict[str, Any], policy: dict[str, Any],
    *, reference_completeness: str = "",
) -> dict[str, Any]:
    create = {
        "main": "Create one square Amazon US main image.",
        "scene": "Create one square Amazon US lifestyle image.",
        "func": "Create one square Amazon US function image.",
        "size": "Create one square Amazon US size image.",
    }[family]
    reference = "Each product view binds its own physical evidence; the first is only the transport edit base."
    preserve = [
        "Sold-product geometry, proportions, finish and parts, using this child's evidenced structures and operating states",
    ]
    replace: list[str] = []
    if family == "func":
        preserve.append(
            "The image's necessary functional evidence and qualifiers, not the source's inset inventory"
        )
    staging = "; ".join(str(value) for value in policy.get("replaceable_staging") or []) or "non-sold room surfaces and loose props"
    if family == "main":
        if policy.get("main_image_policy") == "white_background":
            replace.append("Replace external environment and source graphics with a uniform pure-white canvas; keep the complete sold product unmistakable")
        else:
            replace.append(
                "Redesign non-sold surroundings and staging: " + staging
            )
    elif family == "scene":
        replace.append(
            "Redesign non-sold surroundings and staging: " + staging
        )
    elif family == "func":
        replace.append(
            "Edit the referenced product into the target feature composition; redesign source panels, titles, icons and highlights using the child design"
        )
    elif family == "size":
        replace.append(
            "Redesign the measurement composition, labels, lines and typography; retain the correct measured objects, quantities and physical endpoint associations"
        )
    replace.append("Use the planned target components, not the source prop inventory; remove people and reflected people")
    allowed_props = [str(value) for value in policy.get("allowed_internal_props") or [] if str(value).strip()]
    if allowed_props and family != "size":
        replace.append(
            "Where the selected child evidence supports the shown compartment, "
            "non-sold staging may use: " + "; ".join(allowed_props)
        )
    role_rules = [
        str(value) for value in (policy.get("role_specific_rules") or {}).get(family) or []
        if str(value).strip()
    ]
    forbid = role_rules
    return {
        "create": create,
        "reference_authority": reference,
        "preserve": list(dict.fromkeys(str(value).strip() for value in preserve if str(value).strip())),
        "replace": list(dict.fromkeys(str(value).strip() for value in replace if str(value).strip())),
        "forbid": list(dict.fromkeys(str(value).strip() for value in forbid if str(value).strip())),
        "reference_completeness": (
            "located_measurement_views"
            if family == "size" and measurement.get("mode") == "source_image"
            else reference_completeness or "partial_feature_view"
        ),
    }


def _blocked(base: dict[str, Any], reason: str, *, reason_code: str = "", failure_owner: str = 'brief') -> dict[str, Any]:
    row = {
        **base, "formation_status": "blocked", "formation_reason": reason,
        "formation_reason_code": reason_code or "deterministic_block",
        "formation_failure_owner": failure_owner,
    }
    row["task_fingerprint"] = _task_fingerprint(row)
    row["input_revision_id"] = row["task_fingerprint"]
    return row


def _task_fingerprint(row: dict[str, Any]) -> str:
    """Bind the actual compiled brief, reference pixels and factual execution inputs."""
    projection = {key: row.get(key) for key in ('category_id', 'child', 'role', 'role_family',
        'formation_status', 'policy_version', 'prompt_contract_version', 'execution_profile')}
    if row.get('formation_status') == 'ready':
        projection['compiled_brief'] = compile_task_prompt(task=row)
        projection['product_facts'] = row['product_facts']
        projection['generation_references'] = [reference_semantics(ref) for ref in row['generation_references']]
        projection['measurements'] = [{key: value for key, value in measurement.items() if key != 'confidence'}
                                      for measurement in row['measurement_authority'].get('measurement_groups', [])]
    else:
        projection.update({key: row.get(key) for key in ('formation_reason', 'formation_reason_code', 'formation_failure_owner', 'source_sha256')})
    return input_revision_id(projection)


def _task_failure(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": {
            "logical_task_id": logical_task_id("brief", child=row["child"], role=row["role"]),
            "input_revision_id": row["input_revision_id"], "child": row["child"], "role": row["role"],
        },
        "failure_owner": "classify" if row.get('formation_reason_code') in {'source_evidence_missing', 'source_observation_unresolved'} else row['formation_failure_owner'],
        "task_status": "retryable" if row['formation_failure_owner'] == 'review' else "blocked",
        "error": row.get("formation_reason") or "image task blocked",
    }


def _role_sort_key(role: str) -> tuple[int, str]:
    return ({"main": 0, "scene": 1, "func": 2, "size": 3}.get(role_prefix(role), 9), role)
