from __future__ import annotations

import re
from typing import Any

from .text_evidence import normalize_text


_DIMENSION_NUMBER = r"\d+(?:\.\d+)?"
_LABELED_DIMENSION_RE = re.compile(rf"\b({_DIMENSION_NUMBER})\s*(?:\"|in(?:ches?)?)?\s*([LWHDT])\b", re.I)
_DIMENSION_CHAIN_RE = re.compile(rf"\b({_DIMENSION_NUMBER}(?:\s*(?:x|\*)\s*{_DIMENSION_NUMBER}){{2,4}})\b", re.I)


def template_dimensions_from_facts(facts: dict[str, Any], *, category_id: str = "") -> dict[str, str]:
    dimensions: dict[str, str] = {}
    keys_by_alias = {
        "length": ("length", "item_length"),
        "width": ("width", "item_width"),
        "height": ("height", "item_height"),
        "item_depth": ("item_depth", "depth"),
        "item_weight": ("item_weight", "weight"),
    }
    if category_id in {"bathroom_cabinet", "medicine_cabinet"}:
        keys_by_alias.pop("length")
        keys_by_alias["item_depth"] = ("item_depth", "depth", "length", "item_length")
    for alias, keys in keys_by_alias.items():
        value = _first(facts, *keys)
        if value:
            dimensions[alias] = _first_number(value) or str(value)
    text = _first(facts, "dimensions", "product_dimensions", "item_dimensions", "overall_dimensions")
    if text:
        dimensions.update({key: value for key, value in _parse_template_dimensions(text, category_id=category_id).items() if key not in dimensions})
    dimension_unit = _infer_dimension_unit(text)
    for alias in ("length", "width", "height", "item_depth"):
        if dimensions.get(alias) and dimension_unit:
            dimensions.setdefault(f"{alias}_unit", dimension_unit)
    if dimensions.get("item_weight"):
        weight_unit = _infer_weight_unit(_first(facts, "item_weight", "weight"))
        if weight_unit:
            if weight_unit == "Kilograms":
                try:
                    pounds = float(str(dimensions["item_weight"]).strip()) * 2.2046226218
                    dimensions["item_weight"] = f"{pounds:.2f}".rstrip("0").rstrip(".")
                    dimensions["item_weight_unit"] = "Pounds"
                except (TypeError, ValueError):
                    dimensions.setdefault("item_weight_unit", weight_unit)
            else:
                dimensions.setdefault("item_weight_unit", weight_unit)
    # Amazon listing templates use Inches for item dimensions.  Apify specs
    # often provide a confirmed single-axis value such as ``height=5`` with
    # ``height_unit=Feet``; preserve the fact by converting that value instead
    # of emitting the unsupported ``Feet`` allowed value.
    for alias in ("length", "width", "height", "item_depth"):
        value = dimensions.get(alias)
        unit = _first(facts, f"{alias}_unit") or dimensions.get(f"{alias}_unit")
        if not value or str(unit or "").strip().casefold() not in {"ft", "foot", "feet"}:
            continue
        try:
            inches = float(str(value).strip()) * 12.0
        except (TypeError, ValueError):
            continue
        dimensions[alias] = f"{inches:.2f}".rstrip("0").rstrip(".")
        dimensions[f"{alias}_unit"] = "Inches"
    return dimensions


def color_map_value(color: Any, *, category_id: str = "") -> str:
    text = normalize_text(color).casefold()
    if not text:
        return ""
    for token, value in (
        ("black", "Black"),
        ("white", "White"),
        ("gray", "Gray"),
        ("grey", "Gray"),
        ("brown", "Brown"),
        ("caramel", "Brown"),
        ("green", "Green"),
        ("blue", "Blue"),
        ("red", "Red"),
        ("pink", "Pink"),
        ("beige", "Beige"),
        ("natural", "Natural"),
        ("gold", "Gold"),
        ("silver", "Silver"),
        ("clear", "Clear"),
    ):
        if token in text:
            return value
    if any(mark in text for mark in ("/", "&", " and ")):
        return "Multicolor"
    # Artificial-plant variation labels often name the species (Begonia,
    # Cedar, Cypress) instead of a standard Amazon color.  Preserve that
    # label in the free-text color field, while using the truthful standard
    # map for the foliage-plus-trunk/flower product.
    return "Multicolor" if category_id == "artificial_tree" else ""


def light_color_value(category_id: str, attributes: dict[str, Any]) -> str:
    for key in ("light_color", "lighting_color", "light_colour"):
        value = attributes.get(key)
        if value:
            return str(value)
    return "Not Applicable" if category_id == "artificial_tree" else ""


def _parse_template_dimensions(value: Any, *, category_id: str = "") -> dict[str, str]:
    text = normalize_text(value)
    parsed: dict[str, str] = {}
    label_map = {"l": "length", "w": "width", "h": "height", "d": "item_depth", "t": "item_depth"}
    for number, label in _LABELED_DIMENSION_RE.findall(text):
        parsed.setdefault(label_map[label.casefold()], _clean_dimension_number(number))
    if parsed:
        return parsed
    match = _DIMENSION_CHAIN_RE.search(text)
    if not match:
        return parsed
    numbers = [_clean_dimension_number(item) for item in re.findall(_DIMENSION_NUMBER, match.group(1))]
    if len(numbers) < 3:
        return parsed
    if category_id == "artificial_tree":
        height = max(numbers, key=lambda item: float(item))
        remaining = list(numbers)
        remaining.remove(height)
        parsed.update({"height": height, "width": remaining[0], "item_depth": remaining[1] if len(remaining) > 1 else remaining[0]})
        return {key: value for key, value in parsed.items() if value}
    order = _unlabeled_dimension_order(category_id)
    for alias, number in zip(order, numbers[:3]):
        parsed[alias] = number
    return {key: value for key, value in parsed.items() if value}


def _unlabeled_dimension_order(category_id: str) -> tuple[str, str, str]:
    category = str(category_id or "").strip()
    if category == "bed_frame":
        return ("length", "width", "height")
    if category == "artificial_tree":
        return ("height", "width", "item_depth")
    if category in {"bathroom_cabinet", "medicine_cabinet"}:
        return ("item_depth", "width", "height")
    return ("width", "item_depth", "height")


def _first(values: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = values.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    return ""


def _first_number(value: Any) -> str:
    match = re.search(_DIMENSION_NUMBER, normalize_text(value))
    return _clean_dimension_number(match.group(0)) if match else ""


def _clean_dimension_number(value: Any) -> str:
    text = str(value or "").strip()
    return text[:-2] if text.endswith(".0") else text


def _infer_dimension_unit(value: Any) -> str:
    text = normalize_text(value).casefold()
    if re.search(r'\b(?:in|inch|inches)\b|["″”＂]', text):
        return "Inches"
    if re.search(r"\b(?:cm|centimeter|centimeters)\b", text):
        return "Centimeters"
    if re.search(r"\b(?:mm|millimeter|millimeters)\b", text):
        return "Millimeters"
    if re.search(r"\b(?:ft|feet|foot)\b", text):
        return "Feet"
    return ""


def _infer_weight_unit(value: Any) -> str:
    text = normalize_text(value).casefold()
    if re.search(r"\b(?:lb|lbs|pound|pounds)\b", text):
        return "Pounds"
    if re.search(r"\b(?:oz|ounce|ounces)\b", text):
        return "Ounces"
    if re.search(r"\b(?:kg|kilogram|kilograms)\b", text):
        return "Kilograms"
    if re.search(r"\b(?:g|gram|grams)\b", text):
        return "Grams"
    return ""
