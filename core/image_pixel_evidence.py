from __future__ import annotations

from pathlib import Path
from typing import Any


PIXEL_EVIDENCE_VERSION = "white-background-v6-external-canvas"


def inspect_image_pixel_evidence(path: Path) -> dict[str, Any]:
    from PIL import Image

    with Image.open(path) as opened:
        image = opened.convert("RGB")
        width, height = image.size
        if width < 20 or height < 20:
            raise ValueError(f"image is too small for pixel evidence: {path} ({width}x{height})")
        border = max(4, min(width, height) // 20)
        pixels = []
        for x in range(width):
            for y in range(border):
                pixels.extend((image.getpixel((x, y)), image.getpixel((x, height - 1 - y))))
        for y in range(border, height - border):
            for x in range(border):
                pixels.extend((image.getpixel((x, y)), image.getpixel((width - 1 - x, y))))
        corners = (
            image.getpixel((0, 0)),
            image.getpixel((width - 1, 0)),
            image.getpixel((0, height - 1)),
            image.getpixel((width - 1, height - 1)),
        )
        external_white_ratio = _edge_connected_white_ratio(image)
    white_border_ratio = sum(1 for pixel in pixels if min(pixel) >= 240) / len(pixels)
    white_corner_count = sum(1 for pixel in corners if min(pixel) >= 240)
    return {
        "version": PIXEL_EVIDENCE_VERSION,
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 8),
        "square_canvas": width == height,
        "white_border_ratio": round(white_border_ratio, 6),
        "white_corner_count": white_corner_count,
        "external_white_ratio": round(external_white_ratio, 6),
        "white_background": white_border_ratio >= 0.6 and white_corner_count == 4 and external_white_ratio >= 0.08,
    }


def white_main_model_support(
    observation: dict[str, Any],
    *,
    pixel_evidence: dict[str, Any] | None,
    main_image_policy: str,
) -> bool:
    if main_image_policy != "white_background" or not (pixel_evidence or {}).get("white_background"):
        return False
    environment = " ".join(
        str(item.get("name") or item.get("item") or "")
        for item in observation.get("environment_objects") or []
        if isinstance(item, dict)
    ).lower()
    if any(token in environment for token in (
        "wall", "floor", "room", "tile", "vanity", "sink", "window", "furniture", "bathroom", "bedroom"
    )):
        return False
    composition = observation.get("composition") if isinstance(observation.get("composition"), dict) else {}
    coverage = str(composition.get("product_coverage") or "").strip().lower()
    composition_text = " ".join(str(value or "") for value in composition.values()).lower()
    catalog_signal = any(token in composition_text for token in ("white", "isolated", "catalog", "plain", "studio"))
    return bool(observation.get("product_components")) and catalog_signal and coverage not in {"tiny", "minimal", "background"}


def _edge_connected_white_ratio(image: Any) -> float:
    sample = image.copy()
    sample.thumbnail((256, 256))
    width, height = sample.size
    seen: set[tuple[int, int]] = set()
    stack = [
        *((x, 0) for x in range(width)),
        *((x, height - 1) for x in range(width)),
        *((0, y) for y in range(1, height - 1)),
        *((width - 1, y) for y in range(1, height - 1)),
    ]
    while stack:
        x, y = stack.pop()
        if (x, y) in seen or min(sample.getpixel((x, y))) < 240:
            continue
        seen.add((x, y))
        if x:
            stack.append((x - 1, y))
        if x + 1 < width:
            stack.append((x + 1, y))
        if y:
            stack.append((x, y - 1))
        if y + 1 < height:
            stack.append((x, y + 1))
    return len(seen) / (width * height)
