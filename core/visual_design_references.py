from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import resolve_job_owned_path


def planning_reference_paths(
    job: Path, child: str, sources: list[dict[str, Any]], *, output_dir: Path,
) -> list[Path]:
    """Return the identity image followed by visibly labelled evidence images.

    The main image remains the sole color/material authority. Each other source
    keeps useful reading resolution and receives an in-pixel source_id label so
    Gemini can bind content to the correct immutable source contract.
    """
    main = next(row for row in sources if str(row.get("role") or "") == "main")
    main_path = _job_path(job, main.get("source_path"))
    output_root = _job_path(job, output_dir)
    if not output_root.is_dir():
        raise ValueError(f"VisualDesignKit reference root is missing: {output_root}")
    target_dir = resolve_job_owned_path(job, output_root / child)
    target_dir.mkdir(parents=True, exist_ok=True)
    result = [main_path]
    for row in sources:
        if row is main:
            continue
        source_id = f"source_{int(row.get('source_index') or 0):02d}"
        target = target_dir / f"{source_id}.{row.get('role') or 'evidence'}.png"
        _write_labelled_reference(_job_path(job, row.get("source_path")), target, source_id, str(row.get("role") or ""))
        result.append(target)
    return result


def _write_labelled_reference(source: Path, output: Path, source_id: str, role: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    with Image.open(source) as opened:
        image = opened.convert("RGB")
        image.thumbnail((1280, 1280))
    bar = max(56, image.height // 20)
    canvas = Image.new("RGB", (image.width, image.height + bar), "white")
    canvas.paste(image, (0, bar))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default(size=max(20, bar // 2))
    except TypeError:
        font = ImageFont.load_default()
    draw.rectangle((0, 0, image.width, bar), fill=(245, 245, 245))
    draw.text((16, max(8, bar // 4)), f"{source_id} | {role} | CONTENT EVIDENCE ONLY", fill=(20, 20, 20), font=font)
    temporary = output.with_suffix(output.suffix + ".tmp")
    canvas.save(temporary, format="PNG", optimize=True)
    temporary.replace(output)


def _job_path(job: Path, value: Any) -> Path:
    if not str(value or "").strip():
        raise ValueError("VisualDesignKit reference path is empty")
    return resolve_job_owned_path(job, str(value))
