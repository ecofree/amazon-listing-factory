from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .final_source_intents import planning_source_intents, selected_task_source_intents
from .image_prompt_compiler import PROMPT_CONTRACT_VERSION
from .image_reference_context import validate_reference_set, validate_supporting_sources, view_reference, physical_views
from .image_task_inputs import (
    build_display_copy_contract,
    build_renderable_text_contract,
    execution_profile,
    product_boundary,
    task_facts,
)
from .io import read_jsonl, write_jsonl
from .plugin import ProductPlugin
from .product_family import read_product_family
from .required_role_policy import compiled_image_policy, required_role_policy
from .run_scope import read_run_scope
from .status import input_revision_id, logical_task_id
from .text_evidence import normalize_text, us_measurement_text
from .visual_design_kit import compact_product_claims, read_visual_design_kits, visual_design_kit_row_current


IMAGE_TASK_SCHEMA_VERSION = "image-task-v10"
IMAGE_TASK_POLICY_VERSION = "typed-evidence-faithful-design-v29-complete-display-copy"
IMAGE_TASK_ARTIFACT = "image_tasks_v10.jsonl"
_TASK_BASE_FIELDS = {"schema_version", "policy_version", "category_id", "child", "role", "role_family", "logical_task_id", "output_dir", "prompt_contract_version", "category_image_policy", "formation_status", "formation_reason", "source_path", "source_sha256", "task_fingerprint", "input_revision_id"}
_TASK_READY_FIELDS = _TASK_BASE_FIELDS | {"family_design_id", "family_art_direction", "source_intent_revision_id", "source_index", "generation_references", "edit_base_sha256", "reference_mode", "product_facts", "product_boundary", "measurement_authority", "display_copy_contract", "renderable_text_contract", "image_direction", "edit_contract", "execution_profile"}
_TASK_BLOCKED_FIELDS = _TASK_BASE_FIELDS | {"formation_reason_code"}


class ImageTaskError(RuntimeError):
    pass


def build_image_tasks(
    *, job_dir: str | Path, plugin: ProductPlugin, workers: int = 0,
    include_optional: bool = False,
) -> dict[str, Any]:
    del workers
    job = Path(job_dir).resolve()
    rows = _expected_rows(job, plugin, include_optional=include_optional)
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
        raise ImageTaskError(f"ImageTaskV10 is missing: {path}")
    rows = read_jsonl(path)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        validate_image_task(row)
        if category_id and row["category_id"] != category_id:
            raise ImageTaskError("ImageTaskV10 category does not match the active plugin")
        key = (str(row["child"]), str(row["role"]))
        if key in seen:
            raise ImageTaskError(f"ImageTaskV10 has a duplicate row: {key[0]}/{key[1]}")
        seen.add(key)
    return {"schema_version": IMAGE_TASK_SCHEMA_VERSION, "task_count": len(rows), "tasks": rows}


def image_tasks_current(
    job_dir: str | Path, plugin: ProductPlugin, limit: int = 0,
    *, include_optional: bool = False,
) -> bool:
    del limit
    try:
        actual = read_image_tasks(job_dir, category_id=plugin.category_id)["tasks"]
        expected = _expected_rows(Path(job_dir).resolve(), plugin, include_optional=include_optional)
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
            raise ImageTaskError(f"Invalid ImageTaskV10 inventory row: {key}")
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
        raise ImageTaskError("Invalid ImageTaskV10")
    expected = _TASK_READY_FIELDS if row.get("formation_status") == "ready" else _TASK_BLOCKED_FIELDS
    if set(row) != expected:
        raise ImageTaskError(f"ImageTaskV10 has unknown or missing fields: {sorted(set(row) ^ expected)}")
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
            f"ImageTaskV10 is incomplete: missing={missing};{mismatch} "
            "regenerate the current ImageTask artifact from the active brief contract"
        )
    if row["formation_status"] not in {"ready", "blocked"}:
        raise ImageTaskError("ImageTaskV10 formation status is invalid")
    if row["formation_status"] == "ready":
        needed = (
            "family_design_id", "family_art_direction", "source_path", "source_sha256",
            "source_intent_revision_id", "generation_references", "product_boundary",
            "measurement_authority", "display_copy_contract", "renderable_text_contract",
            "edit_contract", "execution_profile",
        )
        if row.get("role_family") in {"main", "scene"}:
            needed += ("image_direction",)
        absent = [key for key in needed if row.get(key) in (None, "", [], {})]
        if absent:
            raise ImageTaskError(f"Ready ImageTaskV10 is incomplete: {absent}")
        references = row["generation_references"]
        try:
            validate_reference_set(references, child=row["child"], edit_base_sha256=row["edit_base_sha256"])
        except ValueError as exc:
            raise ImageTaskError(str(exc)) from exc
        if (references[0].get("original_sha256") != row["source_sha256"]
                or references[0].get("original_path") != row["source_path"]):
            raise ImageTaskError("Edit view provenance disagrees with its original role source")
        boundary = row["product_boundary"]
        if set(boundary) != {"sold_product_parts", "replaceable_staging", "must_not_change", "product_color_material", "observed_product_colors", "forbidden_additions", "observed_objects"}:
            raise ImageTaskError("ImageTaskV10 product boundary is not canonical")
        expected = build_renderable_text_contract(row["role_family"], row["measurement_authority"], display_copy=row['display_copy_contract'])
        if row["renderable_text_contract"] != expected:
                raise ImageTaskError("ImageTaskV10 renderable text changed after formation")
        edit = row.get("edit_contract")
        if not isinstance(edit, dict) or set(edit) != {"create", "reference_authority", "preserve", "replace", "forbid", "reference_completeness"}:
            raise ImageTaskError("ImageTaskV10 edit contract is not canonical")
    if row.get("task_fingerprint") != _task_fingerprint(row):
        raise ImageTaskError("ImageTaskV10 content changed")


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
        specs = _task_specs(
            children[asin], sources_by_child.get(asin, []), include_optional=include_optional,
        )
        for spec in specs:
            rows.append(_form_task(
                job=job, plugin=plugin, child=children[asin], spec=spec,
                design_kit=design_kit, image_policy=image_policy,
                product_type=product_type,
            ))
    return sorted(rows, key=lambda row: (row["child"], _role_sort_key(row["role"])))


def _task_specs(
    child: dict[str, Any], sources: list[dict[str, Any]], *, include_optional: bool = False,
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
        if not include_optional:
            matches = matches[:1]
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
    source_brief = _source_brief(
        design_kit, source, family,
        allow_missing=False,
    )
    if source_brief is None:
        return _blocked(base, "visual design kit has no matching source brief")
    if source_brief.get("status") != "ready":
        return _blocked(base, str(source_brief.get("error") or "source brief is pending"))
    try:
        measurement = _measurement_authority(family, child, source)
        image_direction = source_brief["image_direction"]
        story = (
            build_display_copy_contract(
                source,
                source_brief or {},
                product_claims=_shared_product_claims(design_kit, child),
            )
            if family in {"func", "size"} else {
                "mode": "none", "title": "", "labels": [], "bindings": [],
            }
        )
        renderable = build_renderable_text_contract(family, measurement, display_copy=story)
        boundary = product_boundary(
            image_policy,
            child,
            product_type=product_type,
            observations=[source.get("visual_evidence") or {}],
        )
        references = _generation_references_for_task(
            source, source_brief, design_kit, job=job, child=str(child["asin"]),
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
            "product_boundary": boundary,
            "measurement_authority": measurement,
            "display_copy_contract": story,
            "renderable_text_contract": renderable,
            "image_direction": image_direction,
            "edit_contract": _edit_contract(
                family, measurement, image_policy, source_brief or {},
                product_type=product_type,
                reference_completeness=str((source.get("signals") or {}).get("reference_completeness") or ""),
            ),
            "execution_profile": execution_profile(family, measurement),
            "formation_status": "ready",
            "formation_reason": "",
        }
    except Exception as exc:
        return _blocked(base, f"{type(exc).__name__}: {exc}")
    fields["task_fingerprint"] = _task_fingerprint(fields)
    fields["input_revision_id"] = fields["task_fingerprint"]
    return fields


def _generation_references_for_task(
    source: dict[str, Any], brief: dict[str, Any], kit: dict[str, Any], *, job: Path, child: str,
) -> list[dict[str, Any]]:
    manifest = kit["source_references"]
    primary = _source_reference(kit, source)
    views = physical_views(primary['observation']['physical_views'])
    displayed = {row['view_id'] for row in brief['image_direction']['evidence_usage'] if row['usage'] == 'display'}
    ordered = sorted(views, key=lambda view: view['view_id'] not in displayed)
    refs = [view_reference(primary, view, job=job, child=child, kind='edit_base' if i == 0 else 'product_evidence')
            for i, view in enumerate(ordered)]
    selected = validate_supporting_sources(brief["supporting_sources"], manifest, primary["source_id"])
    by_id = {row["source_id"]: row for row in manifest}
    for selection in selected:
        support = by_id[selection['source_id']]
        refs.extend({**view_reference(support, view, job=job, child=child, kind='product_evidence'),
                     'purpose': selection['purpose']} for view in physical_views(support['observation']['physical_views']))
    available = {row["source_id"]: row for row in kit.get("approved_design_references", [])}
    for transfer in brief["image_direction"]["design_transfer"]:
        key = transfer["reference_id"]
        if key not in available or brief["role"] not in available[key]["roles"]:
            raise ImageTaskError("Selected design reference is not approved for this role")
        refs.append(available[key])
    return refs


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


def _measurement_authority(family: str, child: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    del child
    has_func_measurement = family == "func" and bool(source.get("measurements") or (source.get("visual_evidence") or {}).get("has_dimension_lines"))
    if family != "size" and not has_func_measurement:
        return {"mode": "none", "render_text": [], "measurement_groups": []}
    if source.get("role") == "size" or has_func_measurement:
        measurements = [
            {
                "id": f"source:{index}",
                "source_id": f"source_{int(source.get('source_index') or 0):02d}",
                "source_text": str(row.get("text") or "").strip(),
                "measured_part": _canonical_source_callout(row.get("source_label")) or "source_visible",
                "axis": str(row.get("axis_hint") or "source_diagram"),
                "kind": "measurement",
                "canonical_value": str(row.get("canonical_pair") or ""),
                "render_text": us_measurement_text(row.get("text"), upper_bound="capacity" in str(row.get("source_label") or "").lower()),
                "confidence": str(row.get("confidence") or "source_visible"),
                # A load-capacity callout is factual evidence even when it is
                # drawn inside an icon/badge rather than on a dimension line.
                "measurement_role": _measurement_role(str(row.get("source_label") or row.get("text") or "")),
                "presentation": "source_visible_capacity_callout"
                if _measurement_role(str(row.get("source_label") or row.get("text") or "")) == "load_capacity"
                else "source_visible_measurement",
            }
            for index, row in enumerate(source.get("measurements") or [], 1)
            if isinstance(row, dict) and str(row.get("text") or "").strip()
        ]
        source_visible_text_artifacts, source_visible_callouts = _source_visible_factual_text(source, measurements)
        return {
            "mode": "source_image", "source_sha256": str(source.get("source_sha256") or ""),
            "source_intent_revision_id": str(source.get("input_revision_id") or ""),
            "preserve_entire_diagram": True,
            "render_text": list(dict.fromkeys(row["render_text"] for row in measurements)),
            "measurement_groups": measurements,
            "source_visible_text_artifacts": source_visible_text_artifacts,
            "source_visible_callouts": source_visible_callouts,
            "ocr_role": "definite_error_warning_only",
            "relationship_policy": "Preserve physical quantities, measured parts, endpoints and product-instance associations; display the authorized US-unit labels.",
        }
    raise ImageTaskError("Size task requires one source image classified as size")


def _source_visible_factual_text(
    source: dict[str, Any], measurements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Project only source-visible numeric facts into the existing authority.

    OCR is evidence, not a second fact store.  Missing or malformed OCR is
    intentionally represented by empty lists so a size task keeps the normal
    generation path and remains available for human comparison.
    """
    evidence = source.get("ocr_evidence") if isinstance(source.get("ocr_evidence"), dict) else {}
    lines = evidence.get("lines") if isinstance(evidence.get("lines"), list) else []
    measurement_texts = {
        " ".join(str(row.get(key) or "").casefold().split())
        for row in measurements
        for key in ("render_text", "raw_text")
        if str(row.get(key) or "").strip()
    }
    artifacts: list[dict[str, Any]] = []
    callouts = list(dict.fromkeys(
        _canonical_source_callout(row.get("text"))
        for row in (source.get("visual_evidence") or {}).get("text_observations") or []
        if row.get("kind") == "measurement"
    ))
    for line in lines:
        if not isinstance(line, dict) or float(line.get("confidence") or 0) < 0.68:
            continue
        text = " ".join(str(line.get("text") or "").split()).strip()
        box = line.get("box")
        if not text or not isinstance(box, list) or len(box) < 4:
            continue
        normalized = _canonical_source_callout(text).casefold()
        is_numeric_fact = (
            normalized in measurement_texts
            or bool(re.search(r"\d", normalized) and re.search(r"(?:\"|\b(?:in|inch|inches|lb|lbs|pounds?)\b)", normalized))
            or bool(re.fullmatch(r"\d+(?:\.\d+)?", normalized))
        )
        is_callout = bool(
            re.search(r"\b(?:capacity|thickness|weight|load)\b", normalized)
            and re.search(r"\d", normalized)
        ) or bool(re.search(r":", normalized) and re.search(r"\d", normalized))
        if not (is_numeric_fact or is_callout):
            continue
        artifact = {
            # Keep OCR exactly as evidence, but expose canonical display copy
            # to the existing size prompt contract so malformed source spacing
            # cannot become the text-rendering instruction.
            "text": text,
            "display_text": _canonical_source_callout(text),
            "confidence": line.get("confidence"),
            "box": box,
            "kind": "callout" if is_callout else "measurement",
        }
        artifacts.append(artifact)
        display_text = str(artifact["display_text"] or "").strip()
        if is_callout and display_text and display_text not in callouts:
            callouts.append(display_text)
    return artifacts, callouts


def _canonical_source_callout(value: Any) -> str:
    """Normalize buyer-facing spacing without changing the factual value."""
    text = normalize_text(value)
    if not text:
        return ""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = re.sub(r"Ibs", "lbs", text, flags=re.I)
    text = re.sub(r"\s*:\s*", ": ", text)
    text = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", text)
    text = re.sub(r"(?<=[\"'])\s*(?=\()", " ", text)
    return us_measurement_text(re.sub(r"\s+", " ", text).strip())


def _measurement_role(text: str) -> str:
    """Classify source-visible numeric evidence without changing its value."""
    normalized = " ".join(text.casefold().replace("–", "-").split())
    if re.search(r"\b(?:capacity|load|supports?|holds?)\b", normalized):
        return "load_capacity"
    if re.search(r"\b(?:lb|lbs|pounds?|kg|kilograms?)\b", normalized):
        return "weight" if re.search(r"\b(?:item|product|net|shipping|package)\s+weight\b", normalized) else "mass_callout"
    return "dimension"


def _edit_contract(
    family: str, measurement: dict[str, Any], policy: dict[str, Any],
    brief: dict[str, Any], *, reference_completeness: str = "",
    product_type: str = "",
) -> dict[str, Any]:
    del brief
    create = {
        "main": "Create one square Amazon US main image.",
        "scene": "Create one square Amazon US lifestyle image.",
        "func": "Create one square Amazon US function image.",
        "size": "Create one square Amazon US size image.",
    }[family]
    reference = "Each product view binds its own physical evidence; the first is only the transport edit base."
    preserve = [
        "Preserve product geometry, proportions, finish, physical part count, attached parts, demonstrated state and the perspective within each view; retain occlusion and partial-view boundaries without reconstructing unseen surfaces",
    ]
    replace: list[str] = []
    if measurement.get("mode") == "source_image":
        preserve.extend([
            "Every physical quantity, measured object and both endpoints on that object; use authorized US-unit labels. Repositioning the intact diagram preserves these associations, not absolute canvas coordinates",
        ])
    if family == "func":
        preserve.append(
            "Keep every source-supported feature, demonstrated moving-part state, required detail view, and factual relationship; preserve the evidence, not the source graphic framing"
        )
    staging = "; ".join(str(value) for value in policy.get("replaceable_staging") or []) or "non-sold room surfaces and loose props"
    bed = product_type.casefold() == "bed_frame"
    if family == "main":
        if policy.get("main_image_policy") == "white_background":
            replace.append("Remove non-sold environment, props, inset scenes and graphics; place the complete sold product on a uniform pure-white canvas")
        else:
            replace.append(
                "Restyle only non-product room surfaces and staging: " + staging
            )
    elif family == "scene":
        replace.append(
            "Restyle only non-product room surfaces and staging: " + staging
        )
    elif family == "func":
        replace.append(
            "Design a new canvas hierarchy around intact source product/detail views: reposition and scale them without changing their internal perspective or visible extent. Replace source panel shapes, title bands, badges and drawn highlights using the child design; source graphics are not a layout template"
        )
        replace.append(
            "Remove source people and reflected people as non-product staging; preserve all sold product surfaces and parts"
        )
    elif family == "size":
        replace.append(
            "Redesign the graphic canvas, typography and measurement styling with the child system; move or scale the intact diagram as a unit, keeping each endpoint attached to the same physical point"
        )
    if bed and family in {"main", "scene"} and policy.get("main_image_policy") != "white_background":
        preserve.append("Retain the complete source-visible mattress and bed-in-use state while restyling bedding")
    allowed_props = [str(value) for value in policy.get("allowed_internal_props") or [] if str(value).strip()]
    if allowed_props and family != "size":
        replace.append(
            "Only where that surface or compartment is already visible/open in the editable reference, "
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
            "complete_measurement_diagram"
            if family == "size" and measurement.get("mode") == "source_image"
            else reference_completeness or "partial_feature_view"
        ),
    }


def _blocked(base: dict[str, Any], reason: str, *, reason_code: str = "") -> dict[str, Any]:
    row = {
        **base, "formation_status": "blocked", "formation_reason": reason,
        "formation_reason_code": reason_code or "deterministic_block",
    }
    row["task_fingerprint"] = _task_fingerprint(row)
    row["input_revision_id"] = row["task_fingerprint"]
    return row


_TASK_SEMANTIC_FIELDS = frozenset({
    "category_id", "child", "role", "role_family", "category_image_policy",
    "family_design_id", "family_art_direction", "source_intent_revision_id",
    "source_index", "source_path", "source_sha256", "generation_references",
    "edit_base_sha256", "reference_mode", "product_facts",
    "product_boundary", "measurement_authority", "display_copy_contract",
    "renderable_text_contract", "image_direction",
    "edit_contract", "execution_profile", "prompt_contract_version",
})


def _task_fingerprint(row: dict[str, Any]) -> str:
    """Hash only facts that change the requested image.

    The prompt contract is part of the image semantics: changing the
    compiler contract must not silently reuse an old candidate.  Runtime
    state, output paths and schema labels remain non-semantic.
    """
    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items() if key not in {"task_fingerprint", "input_revision_id"}}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value
    projection = {
        key: strip(row[key])
        for key in sorted(_TASK_SEMANTIC_FIELDS)
        if key in row
    }
    return input_revision_id(projection)


def _task_failure(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": {
            "logical_task_id": logical_task_id("brief", child=row["child"], role=row["role"]),
            "input_revision_id": row["input_revision_id"], "child": row["child"], "role": row["role"],
        },
        "failure_owner": "brief",
        "task_status": "blocked",
        "error": row.get("formation_reason") or "image task blocked",
    }


def _numbered(role: str, index: int) -> str:
    return role if index == 1 else f"{role}_{index:02d}"


def _role_sort_key(role: str) -> tuple[int, str]:
    return ({"main": 0, "scene": 1, "func": 2, "size": 3}.get(role_prefix(role), 9), role)
