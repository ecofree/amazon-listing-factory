from __future__ import annotations

from pathlib import Path
import math
import hashlib
import time
from typing import Any

from PIL import Image

from .io import file_sha256, write_json
from .paths import resolve_job_owned_path
from .plugin import ProductPlugin


REFERENCE_KINDS = {"edit_base", "product_evidence", "design_reference"}


def physical_views(value: Any) -> list[dict[str, Any]]:
    """Validate observation-owned view bounds, never guess a whole-page fallback."""
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError("Observation physical_views must be a bounded list")
    seen = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"view_id", "region", "extent", "evidence"}:
            raise ValueError("Physical view needs view_id, region, extent and observed evidence")
        key, box = row["view_id"], row["region"]
        if not isinstance(key, str) or not key or len(key) > 80 or key in seen:
            raise ValueError("Physical view identity is missing or duplicated")
        seen.add(key)
        if (not isinstance(box, list) or len(box) != 4
                or any(type(x) not in (int, float) or not 0 <= x <= 1 for x in box)
                or not (box[0] < box[2] and box[1] < box[3])):
            raise ValueError("Physical view needs normalized left,top,right,bottom bounds")
        if row["extent"] not in {"whole_view", "detail"} or not isinstance(row["evidence"], list) or not row["evidence"]:
            raise ValueError("Physical view needs its visible extent and feature evidence")
        features = set()
        for item in row["evidence"]:
            if (not isinstance(item, dict) or set(item) != {"feature_id", "object_id", "region", "physical_facts"}
                    or any(not isinstance(item[k], str) or not item[k].strip() for k in ("feature_id", "object_id"))
                    or not isinstance(item['physical_facts'], list) or not item['physical_facts']
                    or any(not isinstance(fact, str) or not fact.strip() for fact in item['physical_facts'])
                    or item["feature_id"] in features):
                raise ValueError("View evidence needs unique feature identity, object, visible bounds and physical facts")
            features.add(item["feature_id"])
            r = item["region"]
            if (not isinstance(r, list) or len(r) != 4 or any(type(x) not in (int, float) or not 0 <= x <= 1 for x in r)
                    or not (box[0] <= r[0] < r[2] <= box[2] and box[1] <= r[1] < r[3] <= box[3])):
                raise ValueError(f"{key}: crop truncates observed feature {item['feature_id']}; correct its bounds")
    return value


def planning_view_inputs(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"attachment_number": index + 1, "source_id": source_id, "view_id": view['view_id']}
            for index, (source_id, view) in enumerate(
                (source["source_id"], view) for source in sources
                for view in physical_views((source.get("observation") or {}).get("physical_views")))]


def _view_location(job: Path, source: dict[str, Any], view: dict[str, Any], size: tuple[int, int]) -> tuple[Path, tuple[int, int, int, int]]:
    l, t, r, b = view["region"]
    box = (math.floor(l * size[0]), math.floor(t * size[1]), math.ceil(r * size[0]), math.ceil(b * size[1]))
    key = hashlib.sha256(f"{source['source_sha256']}:{box}".encode()).hexdigest()
    return job / "images" / "evidence_views" / f"{key}.png", box


def prepare_planning_views(job: Path, sources: list[dict[str, Any]], directory: Path, *, deadline_monotonic: float | None = None) -> list[Path]:
    """Extract immutable physical views shared by planning and image editing."""
    paths = []
    provenance = []
    directory.mkdir(parents=True, exist_ok=True)
    for source in sources:
        views = physical_views((source.get("observation") or {}).get("physical_views"))
        if not views:
            raise ValueError(f"{source['source_id']}: no observed physical views; resolve source observation")
        path = resolve_job_owned_path(job, source["source_path"])
        if file_sha256(path) != source["source_sha256"]:
            raise ValueError(f"{source['source_id']}: source changed before planning")
        with Image.open(path) as image:
            image.load()
            for view in views:
                if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
                    raise TimeoutError("Child planning deadline exhausted while preparing evidence")
                output, box = _view_location(job, source, view, image.size)
                output.parent.mkdir(parents=True, exist_ok=True)
                with image.crop(box) as crop:
                    if crop.mode in {"CMYK", "YCbCr", "HSV"}:
                        with crop.convert("RGB") as rgb:
                            rgb.save(output, format="PNG")
                    else:
                        crop.save(output, format="PNG")
                paths.append(output)
                provenance.append({"attachment_number": len(paths), "source_id": source["source_id"],
                                   "view_id": view["view_id"], "original_sha256": source["source_sha256"],
                                   "original_region": view["region"], "pixel_box": box,
                                   "coordinate_frame": "original_source", "derived_path": output.relative_to(job).as_posix(),
                                   "derived_sha256": file_sha256(output)})
    write_json(directory / "manifest.json", {"attachments": provenance})
    return paths


def view_reference(source: dict[str, Any], view: dict[str, Any], *, job: Path, child: str, kind: str) -> dict[str, Any]:
    """Use the same extraction and identity as the planning attachments."""
    path = resolve_job_owned_path(job, source["source_path"])
    with Image.open(path) as image:
        crop, _ = _view_location(job, source, view, image.size)
    if not crop.is_file():
        raise ValueError(f"Missing current observed view: {view['view_id']}")
    return {"kind": kind, "child": child, "source_id": source["source_id"], "view_id": view["view_id"],
            "purpose": "Edit this intact observed view; preserve its perspective, visible extent and physical state.",
            "evidence_ids": [item["feature_id"] for item in view["evidence"]],
            "path": crop.relative_to(job).as_posix(), "sha256": file_sha256(crop),
            "original_path": source["source_path"], "original_sha256": source["source_sha256"],
            "original_region": view["region"], "extent": view["extent"], "visible_evidence": view["evidence"]}


def validate_reference_set(references: Any, *, child: str, edit_base_sha256: str) -> None:
    if not isinstance(references, list) or not references:
        raise ValueError("ImageTask needs an ordered reference set")
    if any(not isinstance(row, dict) for row in references):
        raise ValueError("Every reference must be an object")
    if references[0].get("kind") != "edit_base" or sum(row.get("kind") == "edit_base" for row in references) != 1:
        raise ValueError("The first and only edit_base must be attachment 1")
    seen = set()
    for row in references:
        if not isinstance(row, dict) or row.get("kind") not in REFERENCE_KINDS:
            raise ValueError("Unknown reference kind")
        if row.get("child") != child or not row.get("source_id") or not row.get("purpose") or not row.get("path"):
            raise ValueError("Reference ownership, source or purpose is missing")
        if len(str(row.get("sha256") or "")) != 64 or not isinstance(row.get("evidence_ids"), list):
            raise ValueError("Reference SHA or evidence scope is invalid")
        identity = (row["kind"], row["source_id"], row.get("view_id"))
        if identity in seen:
            raise ValueError("Duplicate reference")
        seen.add(identity)
        if row["kind"] == "design_reference":
            if row["evidence_ids"] or not row.get("approved_by") or not row.get("approved_at"):
                raise ValueError("Design references require explicit approval and cannot authorize facts")
        if row.get("protected_mask") and row["kind"] != "edit_base":
            raise ValueError("A mask can only apply to the edit base")
    if references[0]["sha256"] != edit_base_sha256:
        raise ValueError("Edit-base SHA disagrees with attachment 1")


def validate_supporting_sources(value: Any, sources: list[dict[str, Any]], primary_id: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("supporting_sources must be a list")
    known = {row["source_id"]: row for row in sources}
    seen = {primary_id}
    for row in value:
        if not isinstance(row, dict) or set(row) != {"source_id", "purpose", "evidence_ids"}:
            raise ValueError("Supporting source needs source_id, purpose and evidence_ids")
        key = row["source_id"]
        if key not in known or key in seen or not isinstance(row["purpose"], str) or not 1 <= len(row["purpose"].strip()) <= 240:
            raise ValueError("Supporting source is unknown, repeated or lacks a bounded purpose")
        seen.add(key)
        available = {str(item["evidence_id"]) for item in known[key].get("claims", [])}
        available.update("object:" + str(item["object_id"]) for item in ((known[key].get("observation") or {}).get("objects") or []))
        ids = row["evidence_ids"]
        if not isinstance(ids, list) or any(not isinstance(item, str) or item not in available for item in ids) or len(ids) != len(set(ids)):
            raise ValueError("Supporting source evidence is not bound to that source")
    return value




def reference_prompt(references: list[dict[str, Any]], *, design_transfer: list[dict[str, Any]], targeted_edit: bool = False) -> str:
    decisions = {row["reference_id"]: row for row in design_transfer}
    actual = {row["source_id"] for row in references if row["kind"] == "design_reference"}
    if actual != set(decisions):
        raise ValueError("Selected design references do not match generation attachments")
    lines = []
    for index, row in enumerate(references, 1):
        if row["kind"] == "design_reference":
            decision = decisions[row["source_id"]]
            scope = row['visual_review']['transfer_scope']
            purpose = f"Reviewed use: {row['purpose']} Approval boundary: {scope} " + (
                "Style verification only; retain the candidate's established design except for the requested correction."
                if targeted_edit else f"Inherit within that scope: {decision['inherit']} Adapt: {decision['adapt']}")
            purpose += " No reference product, branding, copy or dimension transfer."
        elif row["kind"] == "product_evidence" and row['source_id'] != references[0]['source_id']:
            purpose = "Supporting physical evidence only; verify existing structure, never transfer another view's state or replace the edit base."
        elif row["kind"] == "product_evidence" or not targeted_edit:
            purpose = "Own physical view; follow its assigned evidence use, not source styling."
        else:
            purpose = "Selected candidate: retain its design and physical state except for the requested correction."
        identity = row['source_id'] + (f"/{row['view_id']}" if row.get('view_id') else '')
        lines.append(f"Attachment {index}: {row['kind']} ({identity}). {purpose}")
    return "\n".join(lines)


def generation_reference_sources(
    task: dict[str, Any],
    *,
    plugin: ProductPlugin,
) -> list[dict[str, Any]]:
    del plugin
    references = task.get("generation_references")
    validate_reference_set(references, child=str(task.get("child") or ""), edit_base_sha256=str(task.get("edit_base_sha256") or ""))
    job_dir = str(task.get("job_dir") or "").strip()
    if not job_dir:
        raise ValueError("Runtime image task has no current job_dir")
    result: list[dict[str, Any]] = []
    for row in references:
        path = resolve_job_owned_path(job_dir, str(row.get("path") or ""))
        expected_sha = str(row.get("sha256") or "")
        if not path.is_file() or len(expected_sha) != 64 or file_sha256(path) != expected_sha:
            raise FileNotFoundError(f"ImageTask generation reference is missing or changed: {path}")
        resolved = {**row, "path": path}
        protected_mask = row.get("protected_mask")
        if isinstance(protected_mask, dict):
            resolved["protected_mask"] = {
                "path": str(protected_mask.get("path") or ""),
                "sha256": str(protected_mask.get("sha256") or ""),
            }
        result.append(resolved)
    return result


def generation_reference_primary_path(
    task: dict[str, Any],
    *,
    plugin: ProductPlugin,
) -> Path:
    references = generation_reference_sources(task, plugin=plugin)
    return references[0]["path"]


def generation_reference_mask_bytes(
    task: dict[str, Any],
    *,
    plugin: ProductPlugin,
) -> bytes | None:
    """Read an optional native edit mask attached to the editable reference."""
    references = generation_reference_sources(task, plugin=plugin)
    reference = references[0]
    mask = reference.get("protected_mask")
    if not isinstance(mask, dict):
        return None
    job_dir = str(task.get("job_dir") or "").strip()
    path = resolve_job_owned_path(job_dir, str(mask.get("path") or ""))
    expected_sha = str(mask.get("sha256") or "")
    if not path.is_file() or len(expected_sha) != 64 or file_sha256(path) != expected_sha:
        raise FileNotFoundError(f"ImageTask protected mask is missing or changed: {path}")
    data = path.read_bytes()
    try:
        from io import BytesIO
        from PIL import Image

        with Image.open(BytesIO(data)) as mask_image:
            if mask_image.mode != "RGBA":
                raise ValueError(f"protected mask must be RGBA, got {mask_image.mode}")
            with Image.open(reference["path"]) as source_image:
                if mask_image.size != source_image.size:
                    raise ValueError(
                        f"protected mask size differs from editable reference: "
                        f"{mask_image.size} != {source_image.size}"
                    )
    except Exception as exc:
        raise ValueError(f"Invalid ImageTask protected mask: {exc}") from exc
    return data
