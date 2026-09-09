from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import file_sha256
from .paths import resolve_job_owned_path
from .plugin import ProductPlugin


def generation_reference_sources(
    task: dict[str, Any],
    *,
    plugin: ProductPlugin,
) -> list[dict[str, Any]]:
    del plugin
    references = task.get("generation_references")
    if not isinstance(references, list) or len(references) != 1:
        raise ValueError("ImageTask must contain exactly one editable reference")
    job_dir = str(task.get("job_dir") or "").strip()
    if not job_dir:
        raise ValueError("Runtime image task has no current job_dir")
    result: list[dict[str, Any]] = []
    for row in references:
        if not isinstance(row, dict):
            continue
        path = resolve_job_owned_path(job_dir, str(row.get("path") or ""))
        expected_sha = str(row.get("sha256") or "")
        if not path.is_file() or len(expected_sha) != 64 or file_sha256(path) != expected_sha:
            raise FileNotFoundError(f"ImageTask generation reference is missing or changed: {path}")
        resolved = {"kind": str(row.get("kind") or "reference"), "path": path, "sha256": expected_sha}
        protected_mask = row.get("protected_mask")
        if isinstance(protected_mask, dict):
            resolved["protected_mask"] = {
                "path": str(protected_mask.get("path") or ""),
                "sha256": str(protected_mask.get("sha256") or ""),
            }
        result.append(resolved)
    editable = [row for row in result if row.get("kind") == "editable_reference"]
    if len(editable) != 1 or len(editable) != len(result):
        raise ValueError("ImageTask generation reference set must contain exactly one editable reference")
    return result


def generation_reference_primary_path(
    task: dict[str, Any],
    *,
    plugin: ProductPlugin,
) -> Path:
    references = generation_reference_sources(task, plugin=plugin)
    return next(row["path"] for row in references if row.get("kind") == "editable_reference")


def generation_reference_mask_bytes(
    task: dict[str, Any],
    *,
    plugin: ProductPlugin,
) -> bytes | None:
    """Read an optional native edit mask attached to the editable reference."""
    references = generation_reference_sources(task, plugin=plugin)
    reference = next(row for row in references if row.get("kind") == "editable_reference")
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
