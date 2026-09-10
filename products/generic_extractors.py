from __future__ import annotations

import re
from typing import Any

from core.amazon_image_urls import same_amazon_image_exists
from core.text_evidence import extract_measurements, numeric_signature


FieldLabels = dict[str, tuple[str, ...]]


def clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def detail_map(raw: dict[str, Any]) -> dict[str, Any]:
    details = raw.get("productDetails") or raw.get("product_details") or {}
    out = dict(details) if isinstance(details, dict) else {}
    for group_key in ("attributes", "manufacturerAttributes", "productOverview"):
        group = raw.get(group_key) or []
        if not isinstance(group, list):
            continue
        for item in group:
            if isinstance(item, dict) and item.get("key"):
                out[str(item["key"])] = item.get("value")
    return out


def detail_value(details: dict[str, Any], *labels: str) -> str:
    index = {norm_key(key): value for key, value in details.items()}
    for label in labels:
        value = index.get(norm_key(label))
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if item not in (None, ""))
        if value not in (None, ""):
            return clean_text(value)
    return ""


def parse_lwh(value: str) -> tuple[str, str, str] | None:
    match = re.search(
        r"([0-9.]+)\s*(?:in|inch|inches|\")?\s*[lLdD]?\s*[xX\u00d7]\s*"
        r"([0-9.]+)\s*(?:in|inch|inches|\")?\s*[wW]?\s*[xX\u00d7]\s*"
        r"([0-9.]+)\s*(?:in|inch|inches|\")?\s*[hH]?",
        str(value or ""),
        re.I,
    )
    if not match:
        return None
    quantities = extract_measurements(value)
    if len(quantities) == 3 and all(numeric_signature(row['number']) == numeric_signature(match.group(i)) for i, row in enumerate(quantities, 1)):
        return tuple(row['text'] for row in quantities)
    return match.group(1), match.group(2), match.group(3)


def parse_quantity_unit(value: str) -> tuple[str, str] | None:
    rows = extract_measurements(value)
    if len(rows) != 1:
        return None
    row = rows[0]
    unit = {'lb': 'Pounds', 'ft': 'Feet', 'in': 'Inches', 'cm': 'Centimeters',
            'mm': 'Millimeters', 'm': 'Meters', 'kg': 'Kilograms', 'g': 'Grams', 'oz': 'Ounces'}[row['unit']]
    return row['number'], unit


def parse_pack_count(value: str) -> str:
    text = str(value or "")
    count = r"([2-9]|[1-9]\d{1,2})"
    patterns = (
        rf"\b(?:set|pack|package|bundle)\s+of\s+{count}\b",
        rf"\b{count}\s*[- ]?(?:pack|packs|count|ct)\b",
        rf"\b{count}\s*[- ]?(?:pieces?|pcs)\b(?=\s*(?:set\b|of\b|artificial\b|faux\b|fake\b|trees?\b|plants?\b|cabinets?\b|chairs?\b|tables?\b|beds?\b|frames?\b|mirrors?\b|units?\b|$))",
        rf"\b(?:package\s+includes?|includes?)\D{{0,80}}(?<![/\d]){count}\s*x\s+(?:artificial|faux|fake)?\s*(?:trees?|plants?)\b",
        rf"(?<![/\d])\b{count}\s*x\s+(?:artificial|faux|fake)?\s*(?:trees?|plants?)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1)
    return ""


def extract_specs_by_fields(raw: dict[str, Any], field_labels: FieldLabels) -> dict[str, Any]:
    details = detail_map(raw)
    specs: dict[str, Any] = {}
    for key, labels in field_labels.items():
        value = detail_value(details, *labels)
        if value:
            specs[key] = value
    title = raw.get("title") or raw.get("productTitle") or ""
    if title:
        specs["source_title"] = clean_text(title)
    bullets = raw.get("bulletPoints") or raw.get("features") or raw.get("bullet_points") or []
    if isinstance(bullets, str):
        bullets = [bullets]
    if isinstance(bullets, list):
        specs["source_bullets"] = [clean_text(item) for item in bullets if clean_text(item)][:5]
    dimensions = specs.get("dimensions", "")
    parsed = parse_lwh(dimensions)
    if parsed:
        length, width, height = parsed
        specs.setdefault("length", length)
        specs.setdefault("width", width)
        specs.setdefault("height", height)
    source_text = searchable_text(raw)
    if "height" in field_labels and not specs.get("height"):
        parsed_height = parse_height_from_text(source_text)
        if parsed_height:
            specs["height"], specs["height_unit"] = parsed_height
    if "dimensions" in field_labels and not specs.get("dimensions"):
        parsed_dimensions = parse_lwh(source_text)
        if parsed_dimensions:
            length, width, height = parsed_dimensions
            specs.setdefault("length", length)
            specs.setdefault("width", width)
            specs.setdefault("height", height)
    for key, unit_key in (
        ("height", "height_unit"),
        ("item_weight", "item_weight_unit"),
        ("weight_capacity", "weight_capacity_unit"),
        ("load_capacity", "load_capacity_unit"),
    ):
        parsed_unit = parse_quantity_unit(specs.get(key, ""))
        if parsed_unit:
            specs[key], specs[unit_key] = parsed_unit
    return {key: value for key, value in specs.items() if value not in (None, "", [])}


def searchable_text(raw: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "productTitle", "description", "productDescription"):
        value = raw.get(key)
        if value not in (None, ""):
            parts.append(clean_text(value))
    bullets = raw.get("bulletPoints") or raw.get("features") or raw.get("bullet_points") or []
    if isinstance(bullets, str):
        parts.append(clean_text(bullets))
    elif isinstance(bullets, list):
        parts.extend(clean_text(item) for item in bullets if clean_text(item))
    return " ".join(parts)


def explicit_item_count(raw: dict[str, Any]) -> int | None:
    details = detail_map(raw)
    number_of_items = _explicit_count_value(detail_value(details, "Number of Items"), label="Number of Items", strict=True)
    if number_of_items is not None:
        return number_of_items
    title_pack = parse_pack_count(str(raw.get("title") or raw.get("productTitle") or ""))
    if title_pack:
        return int(title_pack)
    includes_count = parse_pack_count(searchable_text(raw))
    if includes_count:
        return int(includes_count)
    return _explicit_count_value(detail_value(details, "Unit Count"), label="Unit Count", strict=False)


def _explicit_count_value(value: str, *, label: str, strict: bool) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"([1-9]\d*)(?:\.0+)?(?:\s*(?:count|items?|pieces?))?", value, flags=re.I)
    if not match:
        if strict:
            raise ValueError(f"invalid explicit {label}: {value!r}")
        return None
    return int(match.group(1))


def explicit_package_quantity(raw: dict[str, Any]) -> int | None:
    value = detail_value(detail_map(raw), "Package Quantity", "Item Package Quantity")
    if not value:
        return None
    match = re.fullmatch(r"([1-9]\d*)(?:\.0+)?(?:\s*(?:count|packages?))?", value, flags=re.I)
    if not match:
        raise ValueError(f"invalid explicit Package Quantity: {value!r}")
    return int(match.group(1))


def parse_height_from_text(value: str) -> tuple[str, str] | None:
    text = str(value or "")
    patterns = (
        r"\b(?:height|tall|stands?)\D{0,24}([0-9.]+)\s*(feet|foot|ft|inches|inch|in)\b",
        r"\b([0-9.]+)\s*(feet|foot|ft)\s+(?:tall|high|height|artificial|faux|tree|plant)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        unit = match.group(2).lower()
        if unit in {"feet", "foot", "ft"}:
            return match.group(1), "Feet"
        return match.group(1), "Inches"
    return None


def image_urls(raw: dict[str, Any]) -> list[str]:
    images = raw.get("highResolutionImages") or raw.get("images") or raw.get("imageUrls") or []
    out: list[str] = []
    if isinstance(images, list):
        for item in images:
            url = item.get("url") if isinstance(item, dict) else item
            if isinstance(url, str) and url.startswith("http") and url not in out:
                out.append(url)
    main = raw.get("mainImage") or raw.get("main_image") or raw.get("thumbnailImage")
    if isinstance(main, str) and main.startswith("http") and main not in out and not same_amazon_image_exists(out, main):
        out.insert(0, main)
    return out


def variant_value(item: dict[str, Any], *keys: str) -> str:
    candidates = dict(item)
    dims = item.get("dimensions")
    if isinstance(dims, dict):
        candidates.update(dims)
    attrs = item.get("attributes")
    if isinstance(attrs, list):
        for attr in attrs:
            if isinstance(attr, dict) and attr.get("key"):
                candidates[str(attr["key"])] = attr.get("value")
    index = {norm_key(key): value for key, value in candidates.items()}
    for key in keys:
        value = index.get(norm_key(key))
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if item not in (None, ""))
        if value not in (None, ""):
            return clean_text(value)
    return ""


def extract_variations(raw: dict[str, Any], seed_asin: str, dimensions_default: list[str]) -> dict[str, Any]:
    parent_asin = raw.get("parentAsin") or raw.get("parent_asin") or raw.get("parentASIN") or seed_asin
    dimensions = raw.get("dimensions") if isinstance(raw.get("dimensions"), list) else []
    rows: list[dict[str, str]] = []
    display = raw.get("dimensionValuesDisplayData")
    if isinstance(display, dict):
        for asin, values in display.items():
            row = {"asin": str(asin)}
            if isinstance(values, list):
                for dim, value in zip(dimensions or dimensions_default, values):
                    row[str(dim)] = clean_text(value)
            rows.append(row)
    variants = raw.get("variantDetails") or raw.get("variants") or []
    if not rows and isinstance(variants, list):
        for item in variants:
            if not isinstance(item, dict):
                continue
            asin = variant_value(item, "asin", "ASIN", "variantAsin", "variant_asin")
            if not asin:
                continue
            row = {"asin": asin}
            for key in dimensions_default:
                value = variant_value(item, key, f"{key}_name", f"{key}Name", key.title())
                if value:
                    row[key] = value
            if not any(key in row for key in dimensions_default) and item.get("name"):
                row[dimensions_default[0]] = clean_text(item["name"])
            rows.append(row)
    variant_asins = raw.get("variantAsins") or raw.get("variant_asins") or raw.get("variationAsins") or []
    if not rows and isinstance(variant_asins, list):
        seen_asins: set[str] = set()
        for item in variant_asins:
            asin = item.get("asin") if isinstance(item, dict) else item
            asin_text = str(asin or "").strip()
            if not asin_text or asin_text in seen_asins:
                continue
            seen_asins.add(asin_text)
            rows.append({"asin": asin_text})
    if not rows:
        rows = [{"asin": seed_asin}]
    observed = set().union(*(set(row) for row in rows)) if rows else set()
    if not dimensions:
        dimensions = [key for key in dimensions_default if key in observed] or dimensions_default[:1]
    rows = sorted(rows, key=lambda row: tuple(row.get(key, "") for key in dimensions_default) + (row["asin"],))
    return {
        "parent_asin": str(parent_asin),
        "dimensions": dimensions,
        "variation_theme": theme_from_dimensions(dimensions),
        "variants": rows,
    }


def theme_from_dimensions(dimensions: list[str]) -> str:
    parts: list[str] = []
    for dim in dimensions:
        normalized = norm_key(dim)
        if "color" in normalized or "colour" in normalized:
            parts.append("COLOR")
        elif "size" in normalized:
            parts.append("SIZE")
        elif "style" in normalized:
            parts.append("STYLE_NAME")
        elif "height" in normalized:
            parts.append("SIZE")
    return "/".join(dict.fromkeys(parts)) if parts else "COLOR"


def contains(raw: dict[str, Any], needle: str) -> bool:
    text = " ".join(
        str(part)
        for part in [
            raw.get("title"),
            raw.get("productTitle"),
            raw.get("bulletPoints"),
            raw.get("features"),
            raw.get("productDetails"),
        ]
        if part not in (None, "")
    ).lower()
    return needle.lower() in text
