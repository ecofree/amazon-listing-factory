from __future__ import annotations

from pathlib import Path
import math
from typing import Any

from PIL import Image

from .io import file_sha256, read_json
from .paths import resolve_job_owned_path
from .plugin import ProductPlugin


REFERENCE_KINDS = {"edit_base", "product_evidence", "design_reference"}


def physical_views(value: Any) -> list[dict[str, Any]]:
    """Validate observation-owned view bounds, never guess a whole-page fallback."""
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError("Observation physical_views must be a bounded list")
    seen = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"view_id", "region"}:
            raise ValueError("Physical view needs view_id and region")
        key, box = row["view_id"], row["region"]
        if not isinstance(key, str) or not key or len(key) > 80 or key in seen:
            raise ValueError("Physical view identity is missing or duplicated")
        seen.add(key)
        if (not isinstance(box, list) or len(box) != 4
                or any(type(x) not in (int, float) or not 0 <= x <= 1 for x in box)
                or not (box[0] < box[2] and box[1] < box[3])):
            raise ValueError("Physical view needs normalized left,top,right,bottom bounds")
    return value


def planning_view_inputs(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"attachment_number": index + 1, "source_id": source_id, "view_id": view_id}
            for index, (source_id, view_id) in enumerate(
                (source["source_id"], view["view_id"]) for source in sources
                for view in physical_views((source.get("observation") or {}).get("physical_views")))]


def prepare_planning_views(job: Path, sources: list[dict[str, Any]], directory: Path) -> list[Path]:
    """Independent, lossless evidence crops; originals remain the edit authority."""
    paths = []
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
                l, t, r, b = view["region"]
                box = (math.floor(l * image.width), math.floor(t * image.height),
                       math.ceil(r * image.width), math.ceil(b * image.height))
                output = directory / f"view_{len(paths) + 1:03d}.png"
                with image.crop(box) as crop:
                    if crop.mode in {"CMYK", "YCbCr", "HSV"}:
                        with crop.convert("RGB") as rgb:
                            rgb.save(output, format="PNG")
                    else:
                        crop.save(output, format="PNG")
                paths.append(output)
    return paths


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
        identity = (row["kind"], row["source_id"])
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


def approved_design_references(job: Path, child: str) -> list[dict[str, Any]]:
    """Use only explicit current-job inputs; never discover previous outputs."""
    metadata = read_json(job / "job.json") if (job / "job.json").is_file() else {}
    rows = metadata.get("approved_design_references", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Approved design references must be an explicit list")
    selected = [row for row in rows if row.get("child") == child]
    for row in selected:
        if row.get("kind") != "design_reference" or row.get("evidence_ids") != [] or not row.get("approved_by") or not row.get("approved_at") or not row.get("source_id") or not row.get("purpose"):
            raise ValueError("Design reference approval or scope is incomplete")
        path = resolve_job_owned_path(job, str(row.get("path") or ""))
        if not path.is_file() or file_sha256(path) != row.get("sha256"):
            raise ValueError("Approved design reference is missing or changed")
        if path.relative_to(job).parts[0] != "inputs":
            raise ValueError("Import an approved design reference under current-job inputs before planning")
    if len({row["source_id"] for row in selected}) != len(selected):
        raise ValueError("Duplicate approved design reference")
    return selected


def reference_prompt(references: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"Attachment {index}: {row['kind']} ({row['source_id']}). {row['purpose']}"
        + (" Structure evidence only; do not copy its setting or graphics." if row["kind"] == "product_evidence" else
           " Approved style only; never use it for product facts, claims or dimensions." if row["kind"] == "design_reference" else
           " Edit its physical product evidence, not its page design; source graphics and decorative setting have no style authority.")
        for index, row in enumerate(references, 1)
    )


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
