from __future__ import annotations

from copy import deepcopy
from typing import Any

from .template_field_plan import item_highlights_text


SCHEMA_VERSION = "1.0"


def row(
    *,
    row_type: str,
    sku: str,
    asin: str,
    parent_sku: str = "",
    variation: dict[str, Any] | None = None,
    copy: dict[str, Any] | None = None,
    images: dict[str, Any] | None = None,
    attributes: dict[str, Any] | None = None,
    offer: dict[str, Any] | None = None,
    compliance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "row_type": str(row_type or ""),
        "sku": str(sku or ""),
        "asin": str(asin or ""),
        "parent_sku": str(parent_sku or ""),
        "variation": deepcopy(variation or {}),
        "copy": _copy_payload(copy or {}),
        "images": _images_payload(images or {}),
        "attributes": deepcopy(attributes or {}),
        "offer": deepcopy(offer or {}),
        "compliance": deepcopy(compliance or {}),
    }


def package(
    *,
    job_id: str,
    parent_asin: str,
    category_id: str,
    product_type: str,
    variation_theme: str,
    parent: dict[str, Any],
    source_children: list[dict[str, Any]],
    uploadable_child_skus: set[str],
    require_main_image: bool = True,
) -> dict[str, Any]:
    uploadable = [deepcopy(item) for item in source_children if item.get("sku") in uploadable_child_skus]
    omitted = [
        {
            **_public_omitted_child(item),
            "reason": "no_publishable_main_image_or_template_gate",
        }
        for item in source_children
        if item.get("sku") not in uploadable_child_skus
    ]
    data = {
        "schema_version": SCHEMA_VERSION,
        "job_id": str(job_id or ""),
        "parent_asin": str(parent_asin or ""),
        "category_id": str(category_id or ""),
        "product_type": str(product_type or ""),
        "variation_theme": str(variation_theme or ""),
        "source_child_count": len(source_children),
        "uploadable_child_count": len(uploadable),
        "parent": deepcopy(parent),
        "children": uploadable,
        "omitted_children": omitted,
        "audit": [],
    }
    data["audit"] = validate(data, require_main_image=require_main_image)
    return data


def sync_images(row_data: dict[str, Any], *, main: str = "", other: list[str] | None = None) -> dict[str, Any]:
    updated = deepcopy(row_data)
    updated["images"] = _images_payload({"main": main, "other": other or []})
    return updated


def validate(data: dict[str, Any], *, require_main_image: bool = True) -> list[dict[str, str]]:
    audit: list[dict[str, str]] = []
    parent = data.get("parent")
    if not isinstance(parent, dict) or not parent.get("sku"):
        audit.append({"severity": "error", "sku": "*", "field": "parent", "message": "Listing data package has no parent row"})
    children = data.get("children") if isinstance(data.get("children"), list) else []
    source_child_count = int(data.get("source_child_count") or 0)
    if source_child_count > 0 and not children:
        audit.append({"severity": "error", "sku": "*", "field": "children", "message": "Listing data package has no uploadable child rows"})
    seen_asins: set[str] = set()
    for child in children:
        if not isinstance(child, dict):
            continue
        sku = str(child.get("sku") or "")
        asin = str(child.get("asin") or "")
        if not sku.strip():
            audit.append({"severity": "error", "sku": "*", "field": "sku", "message": "Child listing data has blank SKU"})
        if not asin.strip():
            audit.append({"severity": "error", "sku": sku or "*", "field": "asin", "message": "Child listing data has blank ASIN"})
        if asin and asin in seen_asins:
            audit.append({"severity": "error", "sku": sku, "field": "asin", "message": f"Duplicate child ASIN in listing data package: {asin}"})
        if asin:
            seen_asins.add(asin)
        copy = child.get("copy") if isinstance(child.get("copy"), dict) else {}
        if not str(copy.get("title") or "").strip():
            audit.append({"severity": "error", "sku": sku, "field": "title", "message": "Child listing copy has no title"})
        bullets = copy.get("bullets") if isinstance(copy.get("bullets"), list) else []
        if len([item for item in bullets if str(item or "").strip()]) < 5:
            audit.append({"severity": "error", "sku": sku, "field": "bullets", "message": "Child listing copy has fewer than five bullets"})
        if any(len(str(item)) > 120 for item in bullets):
            audit.append({"severity": "warning", "sku": sku, "field": "bullets", "message": "One or more bullets exceed the 120-character quality target"})
        description = str(copy.get("description") or "").strip()
        if not description:
            audit.append({"severity": "error", "sku": sku, "field": "description", "message": "Child listing copy has no description"})
        elif not 700 <= len(description) <= 1200:
            audit.append({"severity": "warning", "sku": sku, "field": "description", "message": "Description is outside the 700-1200 character quality target"})
        if not item_highlights_text(copy):
            audit.append({"severity": "error", "sku": sku, "field": "item_highlights", "message": "Child listing copy has no valid Item Highlights"})
        images = child.get("images") if isinstance(child.get("images"), dict) else {}
        if require_main_image and not str(images.get("main") or "").strip():
            audit.append({"severity": "error", "sku": sku, "field": "main_image", "message": "Child listing data has no publishable main image"})
    return audit


def _copy_payload(copy: dict[str, Any]) -> dict[str, Any]:
    bullets = copy.get("bullets") if isinstance(copy.get("bullets"), list) else []
    out = {
        "title": str(copy.get("title") or ""),
        "item_highlights": [str(item) for item in copy.get("item_highlights", []) if str(item or "").strip()] if isinstance(copy.get("item_highlights"), list) else [],
        "bullets": [str(item) for item in bullets if str(item or "").strip()],
        "description": str(copy.get("description") or ""),
    }
    if copy.get("review_summary"):
        out["review_summary"] = str(copy.get("review_summary"))
    if copy.get("provider"):
        out["provider"] = str(copy.get("provider"))
    return out


def _images_payload(images: dict[str, Any]) -> dict[str, Any]:
    main = str(images.get("main") or "")
    other_raw = images.get("other") if isinstance(images.get("other"), list) else []
    other = [str(item) for item in other_raw if str(item or "").strip()]
    all_urls = []
    for url in [main, *other]:
        if url and url not in all_urls:
            all_urls.append(url)
    return {"main": main, "other": other, "all": all_urls}


def _public_omitted_child(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "asin": str(item.get("asin") or ""),
        "sku": str(item.get("sku") or ""),
        "variation": deepcopy(item.get("variation") or {}),
    }
