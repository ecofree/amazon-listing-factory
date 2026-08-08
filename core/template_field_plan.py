from __future__ import annotations

import re
from typing import Any

from .copy_writer import (
    ITEM_HIGHLIGHT_MAX_COUNT,
    ITEM_HIGHLIGHT_MIN_COUNT,
    ITEM_HIGHLIGHT_SEPARATOR,
    ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS,
)

_WEIGHT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(pounds?|lbs?|lb|kilograms?|kg|grams?|g|ounces?|oz)?\s*$", re.I)


def item_highlights_text(copy: dict[str, Any]) -> str:
    # The real XLSM exposes one Item Highlight cell. CopyV1 owns multiple
    # independently generated phrases; the field plan only joins them.
    raw = copy.get("item_highlights")
    if not isinstance(raw, list):
        return ""
    values = [str(value or "").strip() for value in raw if str(value or "").strip()]
    if not ITEM_HIGHLIGHT_MIN_COUNT <= len(values) <= ITEM_HIGHLIGHT_MAX_COUNT:
        return ""
    text = ITEM_HIGHLIGHT_SEPARATOR.join(values)
    return text if len(text) < ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS else ""


def split_weight_recommendation(value: Any, unit: Any = "") -> tuple[str, str]:
    raw_unit = _weight_unit(unit)
    text = str(value or "").strip()
    match = _WEIGHT_RE.match(text)
    if match:
        parsed_unit = _weight_unit(match.group(2))
        return _clean_number(match.group(1)), raw_unit or parsed_unit
    number = _first_number(text)
    return (number, raw_unit) if number and raw_unit else ("", raw_unit)


def country_of_origin_value(value: Any) -> str:
    text = str(value or "").strip()
    normalized = text.casefold()
    if normalized in {"cn", "chn", "china", "people's republic of china", "prc"}:
        return "China"
    return text


def template_allowed_values(
    workbook: Any,
    worksheet: Any,
    fields: dict[str, int],
    data_start_row: int,
    template_product_type: str,
) -> dict[str, list[str]]:
    validations = getattr(getattr(worksheet, "data_validations", None), "dataValidation", None)
    if not validations:
        return {}
    allowed: dict[str, list[str]] = {}
    field_by_col = {col: field for field, col in fields.items()}
    for validation in validations:
        if str(getattr(validation, "type", "") or "").casefold() != "list":
            continue
        values = _validation_values(workbook, getattr(validation, "formula1", ""), template_product_type)
        if not values:
            continue
        for cell_range in getattr(getattr(validation, "cells", None), "ranges", []) or []:
            try:
                min_col, min_row, max_col, max_row = cell_range.bounds
            except Exception:
                continue
            if max_row < data_start_row:
                continue
            for col in range(int(min_col), int(max_col) + 1):
                field = field_by_col.get(col)
                if field:
                    allowed[field] = list(dict.fromkeys([*(allowed.get(field) or []), *values]))
    return allowed


def compile_field_plan(
    *,
    fields: dict[str, int],
    labels: dict[str, str],
    aliases: dict[str, list[str]],
    allowed_values: dict[str, list[str]] | None = None,
    semantic_hints: dict[str, list[str]] | None = None,
    semantic_values: dict[str, Any],
    images: dict[str, Any],
    image_fields: dict[str, str],
    requirements: list[dict[str, Any]] | None = None,
    row_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    invalid_candidates: dict[str, str] = {}
    allowed_values = allowed_values or {}
    semantic_hints = semantic_hints or {}
    for alias, value in semantic_values.items():
        legal = _legal_template_value(
            fields,
            labels,
            aliases,
            allowed_values,
            str(alias),
            value,
            hints=semantic_hints.get(str(alias)),
        )
        _record_invalid_candidate(
            invalid_candidates, fields, labels, aliases, allowed_values, str(alias), value, legal
        )
        _put_alias(
            values,
            sources,
            fields,
            labels,
            aliases,
            str(alias),
            legal,
            f"semantic:{alias}",
            overwrite=True,
        )
    main = str(images.get("main") or "")
    other = images.get("other") if isinstance(images.get("other"), list) else []
    used: set[str] = set()
    if main.startswith("http"):
        field = image_fields.get("main")
        if field and field in fields:
            values[field] = main
            sources[field] = "release:image:main"
            used.add(main)
    # Alternate/source references never become a main image merely because
    # the current release has no approved main. Keep their template slots and
    # their semantic role independent.
    alternate_urls = [str(item) for item in other if str(item).startswith("http") and str(item) not in used]
    for index, url in enumerate(dict.fromkeys(alternate_urls), 1):
        if index > 8:
            break
        field = image_fields.get(f"other{index}")
        if field and field in fields:
            values[field] = url
            sources[field] = f"release:image:other{index}"
    decisions = compile_field_decisions(
        fields=fields,
        labels=labels,
        aliases=aliases,
        allowed_values=allowed_values,
        values=values,
        sources=sources,
        requirements=requirements or [],
        row_context=row_context or {},
        invalid_candidates=invalid_candidates,
    )
    return {"field_values": values, "field_sources": sources, "field_decisions": decisions}


def compile_field_requirements(
    *,
    fields: dict[str, int],
    labels: dict[str, str],
    aliases: dict[str, list[str]],
    template_requirements: list[dict[str, Any]],
    template_mode: str = "draft",
) -> list[dict[str, Any]]:
    """Merge template metadata and factory upload requirements once."""
    by_field = {
        str(row.get("field") or ""): dict(row)
        for row in template_requirements
        if isinstance(row, dict) and str(row.get("field") or "") in fields
    }
    submit_ready = str(template_mode or "").strip().casefold() == "submit_ready"
    factory_requirements = {
        "item_highlight": ("Required", ""),
        "brand": ("Required", ""),
        "manufacturer": ("Required", ""),
        "item_type_keyword": ("Required", ""),
        "country": ("Required", ""),
        "product_id_type": ("Required", "Child"),
        # Price is optional when Apify has no source offer; a blank cell is
        # preferable to inventing a value.  Existing source prices remain
        # populated and are checked by template_submit_ready.
        "list_price": ("Optional", "Child"),
        "main_image_url": ("Required" if submit_ready else "Optional", "Child"),
        "quantity": ("Required", "Child"),
        "fulfillment": ("Required", "Child"),
        "dg": ("Required", "Child"),
        "color": ("Conditionally Required", "Child"),
        "size": ("Conditionally Required", "Child"),
    }
    strength = {"optional": 0, "conditionally required": 1, "required": 2}
    for alias, (factory_required, row_scope) in factory_requirements.items():
        field = resolve_field(fields, labels, aliases, alias)
        if not field:
            continue
        existing = by_field.get(field, {})
        existing_required = str(existing.get("required") or "Optional").strip()
        # A missing Apify price is an allowed blank by product policy.  The
        # template's raw Required label must not turn an absent fact into a
        # fabricated-value blocker; sourced prices are still checked for drift
        # by template_submit_ready.
        price_optional = alias == "list_price"
        use_factory = price_optional or strength.get(factory_required.casefold(), 0) > strength.get(existing_required.casefold(), 0)
        by_field[field] = {
            **existing,
            "field": field,
            "label": existing.get("label") or labels.get(field, ""),
            "required": factory_required if use_factory else existing_required,
            "row_scope": row_scope or existing.get("row_scope") or "",
            "requirement_source": "factory" if use_factory else existing.get("requirement_source") or "template",
        }
    return list(by_field.values())


def compile_field_coverage(
    *,
    fields: dict[str, int],
    labels: dict[str, str],
    rows: list[dict[str, Any]],
    reference: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate TemplateFieldPlan decisions without re-deciding field validity."""
    filled_fields: set[str] = set()
    for row in rows:
        values = row.get("field_values") if isinstance(row.get("field_values"), dict) else {}
        filled_fields.update(field for field, value in values.items() if str(value or "").strip())
    reference_fields = set((reference.get("fields") if isinstance(reference.get("fields"), dict) else {}).keys())
    reference_map = reference.get("fields") if isinstance(reference.get("fields"), dict) else {}
    decisions = [
        {"sku": str(row.get("sku") or ""), **decision}
        for row in rows
        for decision in row.get("field_decisions") or []
        if isinstance(decision, dict)
    ]
    missing_required = [row for row in decisions if row.get("validation_status") == "missing_required"]
    business_required = [row for row in missing_required if row.get("requirement_source") == "factory"]
    invalid_values = [
        row for row in decisions
        if row.get("validation_status") in {"invalid_allowed_value", "invalid_numeric"}
    ]
    optional_invalid_values = [
        row for row in decisions
        if row.get("validation_status") == "optional_invalid_allowed_value"
    ]
    conditional_risks = [row for row in decisions if row.get("validation_status") == "conditional_risk"]
    required_fields = {
        str(row.get("field") or "") for row in decisions
        if row.get("active") and str(row.get("requirement") or "").casefold() == "required"
    }
    unfilled_reference = sorted(reference_fields - filled_fields, key=lambda field: fields.get(field, 10_000))
    unmapped = sorted(set(fields) - filled_fields, key=lambda field: fields.get(field, 10_000))
    return {
        "total_fields": len(fields),
        "filled_field_count": len(filled_fields),
        "unmapped_field_count": len(unmapped),
        "required_field_count": len(required_fields),
        "unfilled_required_field_count": len(missing_required),
        "unfilled_required_fields": missing_required,
        "business_required_missing_count": len(business_required),
        "business_required_missing": business_required,
        "invalid_value_count": len(invalid_values),
        "invalid_values": invalid_values,
        "optional_invalid_value_count": len(optional_invalid_values),
        "optional_invalid_values": optional_invalid_values,
        "conditional_risk_count": len(conditional_risks),
        "conditional_risks": conditional_risks,
        "unfilled_reference_field_count": len(unfilled_reference),
        "unfilled_reference_fields": [
            {
                **_coverage_item(fields, labels, field),
                "policy": str(reference_map.get(field, {}).get("policy") or ""),
                "examples": list(reference_map.get(field, {}).get("examples") or [])[:2],
            }
            for field in unfilled_reference[:80]
        ],
        "unmapped_field_samples": [_coverage_item(fields, labels, field) for field in unmapped[:80]],
    }


def _coverage_item(fields: dict[str, int], labels: dict[str, str], field: str) -> dict[str, Any]:
    return {"field": field, "label": labels.get(field, ""), "column": fields.get(field)}


def compile_field_decisions(
    *,
    fields: dict[str, int],
    labels: dict[str, str],
    aliases: dict[str, list[str]],
    allowed_values: dict[str, list[str]],
    values: dict[str, str],
    sources: dict[str, str],
    requirements: list[dict[str, Any]],
    row_context: dict[str, Any],
    invalid_candidates: dict[str, str],
) -> list[dict[str, Any]]:
    requirement_by_field = {
        str(item.get("field") or ""): item
        for item in requirements
        if isinstance(item, dict) and str(item.get("field") or "") in fields
    }
    decisions: list[dict[str, Any]] = []
    candidates = set(values) | set(invalid_candidates) | set(requirement_by_field)
    for field in sorted(candidates, key=lambda name: fields.get(name, 10_000)):
        meta = requirement_by_field.get(field, {})
        requirement = str(meta.get("required") or "Optional").strip()
        required_kind = requirement.casefold().replace(" ", "_")
        row_scope = str(meta.get("row_scope") or "").strip().casefold()
        scope_active = not row_scope or row_scope == str(row_context.get("row_type") or "").strip().casefold()
        if not scope_active:
            active, activation_reason = False, f"{row_scope}_rows_only"
        elif required_kind == "required":
            active, activation_reason = True, "template_required"
        elif required_kind == "conditionally_required":
            active, activation_reason = _conditional_activation(
                field, values=values, fields=fields, labels=labels, aliases=aliases, row_context=row_context
            )
        else:
            active = field in values or field in invalid_candidates
            activation_reason = "value_supplied" if active else "optional"
        value = str(values.get(field) or "")
        attempted = str(invalid_candidates.get(field) or "")
        unknown_conditional = required_kind == "conditionally_required" and active is None
        inactive_conditional = required_kind == "conditionally_required" and active is False
        if unknown_conditional:
            validation = "conditional_risk"
        elif inactive_conditional:
            validation = "pass"
        elif attempted and not value:
            validation = (
                "optional_invalid_allowed_value"
                if required_kind == "optional"
                else "invalid_allowed_value"
            )
        elif active and required_kind in {"required", "conditionally_required"} and not value:
            validation = "missing_required"
        elif value and allowed_values.get(field) and not _value_allowed(value, allowed_values[field]):
            validation = (
                "optional_invalid_allowed_value"
                if required_kind == "optional"
                else "invalid_allowed_value"
            )
        elif value and field_expects_number(field) and not looks_numeric(value):
            validation = "invalid_numeric"
        else:
            validation = "pass"
        decisions.append(
            {
                "field": field,
                "label": str(meta.get("label") or labels.get(field) or ""),
                "value": value,
                "source": str(sources.get(field) or ""),
                "requirement": requirement,
                "requirement_source": str(meta.get("requirement_source") or "template"),
                "active": bool(active),
                "activation_reason": activation_reason,
                "validation_status": validation,
                **({"attempted_value": attempted} if attempted else {}),
            }
        )
    return decisions


def resolve_field(fields: dict[str, int], labels: dict[str, str], aliases: dict[str, list[str]], alias: str) -> str | None:
    if alias in fields:
        return alias
    for candidate in aliases.get(alias, []):
        if candidate in fields:
            return candidate
    wanted = {_norm(alias), *(_norm(item) for item in aliases.get(alias, []))}
    matches = [
        field for field in fields
        if _norm(field) in wanted or _norm(labels.get(field, "")) in wanted
    ]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous template field alias {alias!r}: {matches}")
    return matches[0] if matches else None


def fields_for_alias(fields: dict[str, int], labels: dict[str, str], aliases: dict[str, list[str]], alias: str) -> list[str]:
    matches: list[str] = []
    if alias in fields:
        matches.append(alias)
    for candidate in aliases.get(alias, []):
        if candidate in fields and candidate not in matches:
            matches.append(candidate)
    if matches:
        return matches
    resolved = resolve_field(fields, labels, aliases, alias)
    return [resolved] if resolved else []


def allowed_values_for_alias(
    allowed_values: dict[str, list[str]],
    fields: dict[str, int],
    labels: dict[str, str],
    aliases: dict[str, list[str]],
    alias: str,
) -> list[str]:
    values: list[str] = []
    for field in fields_for_alias(fields, labels, aliases, alias):
        values.extend(str(item) for item in allowed_values.get(field, []) if str(item or "").strip())
    return list(dict.fromkeys(values))


def select_allowed_value(preferred: Any, allowed_values: list[str], *, hints: list[str] | None = None) -> str:
    preferred_text = str(preferred or "").strip()
    allowed = [str(item or "").strip() for item in allowed_values if str(item or "").strip()]
    if not allowed:
        return preferred_text
    for item in allowed:
        if item.casefold() == preferred_text.casefold():
            return item
    for hint in hints or []:
        hint_tokens = _allowed_match_tokens(hint)
        if len(hint_tokens) < 2:
            continue
        for item in allowed:
            item_tokens = _allowed_match_tokens(item)
            if hint_tokens.issubset(item_tokens) or item_tokens.issubset(hint_tokens):
                return item
    return ""


def primary_material_label(value: Any) -> str:
    text = str(value or "").strip()
    lowered = text.casefold()
    if not lowered:
        return ""
    if re.search(r"\b(?:pine|wood|mdf|plywood|engineered wood|rubber wood|particleboard)\b", lowered):
        return "Wood"
    if re.search(r"\b(?:steel|metal|iron|aluminum|aluminium)\b", lowered):
        return "Metal"
    if re.search(r"\b(?:plastic|polyethylene|polypropylene|pe|pp)\b", lowered):
        return "Plastic"
    return text


def _legal_template_value(
    fields: dict[str, int],
    labels: dict[str, str],
    aliases: dict[str, list[str]],
    allowed_values: dict[str, list[str]],
    alias: str,
    value: Any,
    *,
    hints: list[str] | None = None,
) -> Any:
    allowed = allowed_values_for_alias(allowed_values, fields, labels, aliases, alias)
    if not allowed:
        return value
    equivalent = _known_enum_value(alias, value, allowed)
    if equivalent:
        return equivalent
    return select_allowed_value(value, allowed, hints=[*_value_hints(value), *(hints or [])])


def _known_enum_value(alias: str, value: Any, allowed: list[str]) -> str:
    token = _norm(value)
    groups = {
        "inventory_available": (
            {"enabled", "yes", "true", "available", "1"},
            {"disabled", "no", "false", "unavailable", "0"},
        ),
        "country": (
            {"china", "cn", "chn", "peoplesrepublicofchina", "prc"},
        ),
    }.get(alias, ())
    for group in groups:
        if token in group:
            for candidate in allowed:
                if _norm(candidate) in group:
                    return candidate
    return ""


def _record_invalid_candidate(
    invalid: dict[str, str],
    fields: dict[str, int],
    labels: dict[str, str],
    aliases: dict[str, list[str]],
    allowed_values: dict[str, list[str]],
    alias: str,
    candidate: Any,
    selected: Any,
) -> None:
    text = _string_value(candidate).strip() if candidate not in (None, "", []) else ""
    if not text or selected not in (None, "", []):
        return
    for field in fields_for_alias(fields, labels, aliases, alias):
        if allowed_values.get(field):
            invalid[field] = text


def _conditional_activation(
    field: str,
    *,
    values: dict[str, str],
    fields: dict[str, int],
    labels: dict[str, str],
    aliases: dict[str, list[str]],
    row_context: dict[str, Any],
) -> tuple[bool | None, str]:
    name = str(field or "").casefold()
    row_type = str(row_context.get("row_type") or "")
    theme = str(row_context.get("variation_theme") or "").upper()
    if "parent_sku_relationship" in name:
        return row_type == "Child", "child_relationship" if row_type == "Child" else "parent_row"
    variation_fields = set(fields_for_alias(fields, labels, aliases, "variation_theme"))
    if field in variation_fields:
        return bool(theme), "variation_family" if theme else "no_variation_theme"
    product_id_fields = set(fields_for_alias(fields, labels, aliases, "product_id"))
    if field in product_id_fields:
        active = not bool(row_context.get("gtin_exempt", True)) and row_type == "Child"
        return active, "non_exempt_child" if active else "gtin_exempt_or_parent"
    if name.endswith(".unit"):
        value_field = field[:-5] + ".value"
        active = bool(str(values.get(value_field) or "").strip())
        return active, "paired_value_present" if active else "paired_value_missing"
    if "package_contains_sku" in name:
        active = bool(row_context.get("package_level"))
        return active, "package_level_present" if active else "not_a_package_hierarchy"
    if any(token in name for token in ("battery[", "num_batteries", "lithium_battery", "lithium_ion", "lithium_metal")):
        active = bool(row_context.get("contains_battery"))
        return active, "battery_present" if active else "battery_not_present"
    if any(token in name for token in ("hazmat", "ghs[", "safety_data_sheet", "dangerous_goods")):
        dangerous = str(row_context.get("dangerous_goods") or "").strip().casefold()
        active = bool(dangerous and dangerous not in {"not applicable", "not_applicable", "none", "no"})
        return active, "dangerous_goods_present" if active else "dangerous_goods_not_applicable"
    value = str(values.get(field) or "").strip()
    if value:
        return True, "value_supplied"
    color_fields = {
        *fields_for_alias(fields, labels, aliases, "color"),
        *fields_for_alias(fields, labels, aliases, "color_map"),
        *fields_for_alias(fields, labels, aliases, "hardware_color"),
    }
    size_fields = set(fields_for_alias(fields, labels, aliases, "size"))
    if row_type == "Parent" and field in color_fields | size_fields:
        return False, "parent_row"
    if "COLOR" in theme and row_type == "Child" and field in color_fields:
        return True, "color_variation"
    if "SIZE" in theme and row_type == "Child" and field in size_fields:
        return True, "size_variation"
    return None, "activation_unknown"


def field_expects_number(field: str) -> bool:
    name = str(field or "").casefold()
    if any(token in name for token in ("language_tag", ".unit", ".type")):
        return False
    return any(
        token in name
        for token in (
            "number_of_items",
            "item_package_quantity",
            "unit_count",
            "list_price",
            "fulfillment_availability#1.quantity",
            ".length.value",
            ".width.value",
            ".height.value",
            ".depth.value",
            ".weight.value",
            "normalized_value.value",
        )
    )


def looks_numeric(value: Any) -> bool:
    if value in (None, ""):
        return True
    try:
        float(str(value).strip())
        return True
    except (TypeError, ValueError):
        return False


def _value_allowed(value: Any, allowed: list[str]) -> bool:
    needle = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    return not needle or any(re.sub(r"\s+", " ", str(item or "")).strip().casefold() == needle for item in allowed)


def _value_hints(value: Any) -> list[str]:
    if isinstance(value, dict):
        values = value.values()
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]
    hints: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        hints.append(text)
        hints.extend(part for part in re.split(r"[^A-Za-z0-9]+", text) if len(part) > 2)
    return list(dict.fromkeys(hints))


def fit_template_image_slots(others: list[dict[str, str]], *, limit: int = 8) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    kept = list(others)
    omitted: list[dict[str, str]] = []
    for prefix in ("scene", "func", "size"):
        while len(kept) > limit:
            index = next(
                (idx for idx in range(len(kept) - 1, -1, -1) if str(kept[idx].get("role") or "").startswith(prefix)),
                -1,
            )
            if index < 0:
                break
            omitted.insert(0, kept.pop(index))
    while len(kept) > limit:
        omitted.insert(0, kept.pop())
    return kept, omitted


def role_sort(role: str) -> tuple[int, str]:
    prefix = next((name for name in ("main", "scene", "func", "size") if role == name or role.startswith(f"{name}_")), "")
    return ({"main": 0, "scene": 1, "func": 2, "size": 3}.get(prefix, 4), role)


def _put_alias(
    values: dict[str, str],
    sources: dict[str, str],
    fields: dict[str, int],
    labels: dict[str, str],
    aliases: dict[str, list[str]],
    alias: str,
    value: Any,
    source: str,
    *,
    overwrite: bool,
) -> None:
    if value in (None, "", []):
        return
    rendered = _string_value(value)
    for field in fields_for_alias(fields, labels, aliases, alias):
        if not overwrite and values.get(field) not in (None, ""):
            continue
        values[field] = rendered
        sources[field] = source


def _string_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value if item not in (None, ""))
    return str(value)


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _allowed_match_tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if len(token) > 1
    }


def _validation_values(workbook: Any, formula: Any, product_type: str) -> list[str]:
    text = str(formula or "").strip().lstrip("=")
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return [item.strip() for item in text[1:-1].split(",") if item.strip()]
    name = text
    if text.upper().startswith("INDIRECT("):
        suffixes = re.findall(r'&\s*"([^"]+)"', text)
        if not suffixes or not product_type:
            return []
        prefix = str(product_type).replace("-", "_").replace(" ", "")
        if prefix[:1].isdigit():
            prefix = "_" + prefix
        name = prefix + suffixes[-1]
    return _defined_name_values(workbook, name)


def _defined_name_values(workbook: Any, name: str) -> list[str]:
    try:
        defined = workbook.defined_names.get(name)
    except Exception:
        defined = None
    if defined is None:
        return []
    try:
        destinations = list(defined.destinations)
    except Exception:
        return []
    values: list[str] = []
    for sheet_name, coord in destinations:
        try:
            cells = workbook[sheet_name][coord]
        except Exception:
            continue
        for cell in _iter_cells(cells):
            value = getattr(cell, "value", None)
            if value not in (None, ""):
                text = str(value).strip()
                if text and text not in values:
                    values.append(text)
    return values


def _iter_cells(value: Any):
    if hasattr(value, "value"):
        yield value
        return
    try:
        for item in value:
            yield from _iter_cells(item)
    except TypeError:
        return


def _weight_unit(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text in {"pound", "pounds", "lb", "lbs"}:
        return "Pounds"
    if text in {"kilogram", "kilograms", "kg"}:
        return "Kilograms"
    if text in {"gram", "grams", "g"}:
        return "Grams"
    if text in {"ounce", "ounces", "oz"}:
        return "Ounces"
    return str(value or "").strip()


def _first_number(value: str) -> str:
    match = re.search(r"\d+(?:\.\d+)?", value)
    return _clean_number(match.group(0)) if match else ""


def _clean_number(value: Any) -> str:
    text = str(value or "").strip()
    return text[:-2] if text.endswith(".0") else text
