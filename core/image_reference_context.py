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
        raise ValueError("ImageTask must contain exactly one editable generation reference")
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
        result.append({"kind": str(row.get("kind") or "reference"), "path": path, "sha256": expected_sha})
    if len(result) != 1:
        raise ValueError("ImageTask editable generation reference is invalid")
    return result


def generation_reference_primary_path(
    task: dict[str, Any],
    *,
    plugin: ProductPlugin,
) -> Path:
    return generation_reference_sources(task, plugin=plugin)[0]["path"]


def generation_reference_image_inputs(
    task: dict[str, Any],
    *,
    plugin: ProductPlugin,
) -> list[dict[str, Any]]:
    return [
        {**row, "bytes": row["path"].read_bytes()}
        for row in generation_reference_sources(task, plugin=plugin)
    ]
