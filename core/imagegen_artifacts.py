from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .api_registry import image_provider_physical_identity
from .image_provider_common import ImageGenerationError


IMAGEGEN_OUTPUT_CACHE_VERSION = "imagegen-output-v11-1600-publication"


class ImageArtifactContractError(RuntimeError):
    pass


def imagegen_output_marker(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".source.json")


def staged_imagegen_output(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".pending")


def publish_staged_imagegen_output(staging_path: Path, output_path: Path) -> None:
    if output_path.exists():
        raise ImageArtifactContractError(f"Immutable image artifact already exists: {output_path}")
    if not staging_path.is_file():
        raise ImageArtifactContractError(f"Staged image artifact is missing: {staging_path}")
    os.replace(staging_path, output_path)


def provider_model(provider: str) -> str:
    identity = image_provider_physical_identity(provider)
    return str(identity.get("model") or identity.get("builtin") or "")


def replace_output(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ImageArtifactContractError(f"Immutable image artifact already exists: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=f".tmp{path.suffix}", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def assert_image_output(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ImageGenerationError(f"Generated image is empty: {path}")
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            extrema = image.convert("L").getextrema()
        if min(width, height) < 1000:
            raise ImageGenerationError(f"Generated image is too small: {path}: {width}x{height}")
        if width != height:
            raise ImageGenerationError(f"Generated image must be square: {path}: {width}x{height}")
        if extrema in {(0, 0), (255, 255)}:
            raise ImageGenerationError(f"Generated image is solid color: {path}")
    except ImageGenerationError:
        raise
    except Exception as exc:
        raise ImageGenerationError(f"Generated image is unreadable: {path}: {exc}") from exc
