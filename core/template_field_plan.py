from __future__ import annotations

import re
import math
from typing import Any

from .copy_writer import (
    ITEM_HIGHLIGHT_MAX_COUNT,
    ITEM_HIGHLIGHT_MIN_COUNT,
    ITEM_HIGHLIGHT_SEPARATOR,
    ITEM_HIGHLIGHT_TOTAL_LIMIT_CHARS,
)

from .text_evidence import extract_measurements, us_measurement_text


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
    text = str(value or "").strip()
    rows = extract_measurements(us_measurement_text(text if extract_measurements(text) else f'{text} {unit}', upper_bound=True))
    if len(rows) == 1 and rows[0]['kind'] == 'weight_g':
        return rows[0]['number'], _weight_unit(rows[0]['unit'])
    return '', _weight_unit(unit)


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
                    # The offer-price cell accepts numbers. Its non-enforcing list only offers a delete command.
                    if (field.endswith('.our_price#1.schedule#1.value_with_tax') and not validation.showErrorMessage
                            and all(str(v).casefold().startswith('delete offer') for v in values)):
                        continue
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
    pending_fields: dict[str, str] | None = None,
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
        pending_fields=pending_fields,
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
        "item_highlight": ("Required", "Child"),
        "brand": ("Required", ""),
        "manufacturer": ("Required", ""),
        "item_type_keyword": ("Required", ""),
        "country": ("Required", ""),
        "product_id_type": ("Required", "Child"),
        # The factory adds no universal price requirement; the actual template
        # may require it. Missing evidence must not downgrade that requirement.
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
        use_factory = strength.get(factory_required.casefold(), 0) > strength.get(existing_required.casefold(), 0)
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
    pending_fields: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    requirement_by_field = {
        str(item.get("field") or ""): item
        for item in requirements
        if isinstance(item, dict) and str(item.get("field") or "") in fields
    }
    decisions: list[dict[str, Any]] = []
    from .template_conditions import row_applicability
    row_context = {**row_context, 'workbook_applies': row_applicability(row_context.get('workbook_conditions'), values)}
    candidates = set(values) | set(invalid_candidates) | set(requirement_by_field)
    for field in sorted(candidates, key=lambda name: fields.get(name, 10_000)):
        meta = requirement_by_field.get(field, {})
        requirement = str(meta.get("required") or "Optional").strip()
        required_kind = requirement.casefold().replace(" ", "_")
        row_scope = str(meta.get("row_scope") or "").strip().casefold()
        scope_active = not row_scope or row_scope == str(row_context.get("row_type") or "").strip().casefold()
        marketplace=re.search(r'marketplace_id=([^\]]+)',field)
        if marketplace and marketplace[1]!=row_context.get('marketplace_id','ATVPDKIKX0DER'):
            if str(values.get(field) or '').strip():raise ValueError('Foreign marketplace value in the US-only listing contract')
            scope_active=False;row_scope='other_marketplace'
        battery_conflict = (scope_active and field in aliases.get('batteries_required', ())
                            and row_context.get('battery_requirement_conflict'))
        if not scope_active:
            active, activation_reason = False, f"{row_scope}_rows_only"
        elif battery_conflict:
            active, activation_reason = None, 'seller_and_product_battery_requirement_conflict'
        elif required_kind == "required":
            active, activation_reason = True, "template_required"
        elif required_kind == "conditionally_required":
            active, activation_reason = _conditional_activation(
                field, values=values, fields=fields, labels=labels, aliases=aliases, row_context=row_context
            )
        else:
            active = field in values or field in invalid_candidates
            activation_reason = "value_supplied" if active else "optional"
        disposition = (row_context.get('conditional_dispositions') or {}).get(field)
        if disposition and scope_active and not battery_conflict and required_kind == 'conditionally_required':
            if active is not None and active is not disposition['applicable']:
                raise ValueError(f'Conditional disposition contradicts current facts: {field}')
            active, activation_reason = disposition['applicable'], f"operational:{disposition['source']}: {disposition['reason']}"
        value = str(values.get(field) or "")
        attempted = str(invalid_candidates.get(field) or "")
        unknown_conditional = required_kind == "conditionally_required" and active is None
        inactive_conditional = required_kind == "conditionally_required" and active is False
        dependency = (pending_fields or {}).get(field, '')
        if dependency and scope_active and not value and not attempted:
            validation = 'awaiting_upstream'
            activation_reason = 'pending:' + dependency
        elif scope_active and field in row_context.get('source_field_conflicts', ()) and (
                battery_conflict or active is not False and required_kind in {'required','conditionally_required'}):
            validation, activation_reason = 'conditional_risk', 'conflicting_child_source_values'
        elif battery_conflict or unknown_conditional:
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
        elif value and field_expects_number(field) and not looks_numeric(value, field=field):
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
                "active": active,
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
    if alias in {'variation_theme','required_product_compliance_certificate','condition','color_map',
                 'material','recommended_uses','included_component'} or alias in fields:
        return select_allowed_value(value, allowed)
    return select_allowed_value(value, allowed, hints=[*_value_hints(value), *(hints or [])])


def _known_enum_value(alias: str, value: Any, allowed: list[str]) -> str:
    token = _norm(_string_value(value))
    if alias in {'batteries_required','batteries_included','contains_battery','is_fragile'}:
        groups=({'yes','true','1'},{'no','false','0'})
    else:
        groups = {
        "inventory_available": (
            {"enabled", "yes", "true", "available", "1"},
            {"disabled", "no", "false", "unavailable", "0"},
        ),
        "country": (
            {"china", "cn", "chn", "peoplesrepublicofchina", "prc"},
        ),
        'fulfillment': ({'fbm','default','merchantfulfilled','sellerfulfilled','fulfillmentbymerchantdefault'},),
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
        if row_type == 'Parent': return False, 'parent_row'
        exempt = row_context.get('gtin_exempt')
        if type(exempt) is not bool: return None, 'gtin_exemption_unknown'
        return not exempt, 'gtin_exempt' if exempt else 'non_exempt_child'
    if name.endswith(".unit"):
        value_field = field[:-5] + ".value"
        active = bool(str(values.get(value_field) or "").strip())
        return active, "paired_value_present" if active else "paired_value_missing"
    if (row_context.get('use_default_shipping') and field in aliases.get('shipping_template', ())
            and 'marketplace_id=ATVPDKIKX0DER' in field
            and 'create' in str(values.get('::record_action', '')).casefold()):
        return False, 'new_sku_uses_account_shipping_default'
    if field in row_context.get('workbook_applies', {}):
        return row_context['workbook_applies'][field], 'template_row_condition'
    if "package_contains_sku" in name:
        level = str(row_context.get('package_level') or '').strip().casefold()
        if not level or level in {'unknown','not specified'}: return None, 'package_hierarchy_unknown'
        active = level not in {'unit','false','no','none','not applicable'}
        return active, 'package_level_present' if active else 'not_a_package_hierarchy'
    if row_type=='Parent' and name.startswith('number_of_items['):return False,'parent_not_sellable'
    if any(token in name for token in ("battery[", "num_batteries", "lithium_battery", "lithium_ion", "lithium_metal",
        'battery_contains_','battery_installation_','is_battery_non_spillable','has_less_than_30_percent_state_of_charge',
        'has_multiple_battery_powered_components','contains_battery_or_cell')):
        # Required-but-not-included batteries do not prove shipped battery contents.
        flags = {str(row_context.get(key)).strip().casefold() for key in ("contains_battery", "batteries_included")}
        if flags & {'true','yes','1'} and flags & {'false','no','0'}:return None,'battery_evidence_conflict'
        if flags & {"true", "yes", "1"}:
            return True, "battery_present"
        if flags & {"false", "no", "0"}:
            return False, "battery_not_present"
        return None, "battery_presence_unknown"
    if any(token in name for token in ("hazmat", "ghs[", "safety_data_sheet", "dangerous_goods")):
        dangerous = str(row_context.get("dangerous_goods") or "").strip().casefold()
        if not dangerous or dangerous in {"unknown", "not specified"}:
            return None, "dangerous_goods_unknown"
        active = dangerous not in {"not applicable", "not_applicable", "none", "no"}
        return active, "dangerous_goods_present" if active else "dangerous_goods_not_applicable"
    value = str(values.get(field) or "").strip()
    inventory_fields=set(fields_for_alias(fields,labels,aliases,'inventory_available'))
    if field in inventory_fields and not value and any(values.get(q) not in (None,'') for q in fields_for_alias(fields,labels,aliases,'quantity')):
        return False,'finite_quantity_instead_of_always_available'
    if value:
        return True, "value_supplied"
    hardware_color_fields = set(fields_for_alias(fields, labels, aliases, "hardware_color"))
    color_fields = {
        *fields_for_alias(fields, labels, aliases, "color"),
        *fields_for_alias(fields, labels, aliases, "color_map"),
    }
    size_fields = set(fields_for_alias(fields, labels, aliases, "size"))
    if row_type == "Parent" and field in color_fields | hardware_color_fields | size_fields:
        return False, "parent_row"
    if "COLOR" in theme and row_type == "Child" and field in color_fields:
        return True, "color_variation"
    if "SIZE" in theme and row_type == "Child" and field in size_fields:
        return True, "size_variation"
    return None, "activation_unknown"


def bound_conditional_dispositions(records, *, template_sha256, sku, product_type, facts_revision, fields):
    """Consume explicit evidence in the existing template field authority, bound to this SKU/revision."""
    if records is None: return {}
    if not isinstance(records, list): raise ValueError('conditional_dispositions must be a list')
    bound = {}
    keys = {'template_sha256','sku','product_type','facts_revision','field','applicable','reason','source'}
    for record in records:
        if (not isinstance(record,dict) or set(record) != keys or type(record['applicable']) is not bool
                or any(not isinstance(record[k],str) or not record[k].strip() for k in keys-{'applicable'})):
            raise ValueError('Conditional disposition requires a concrete field, applicability, reason and source')
        if record['sku'] != sku: continue
        if (record['template_sha256'] != template_sha256 or record['product_type'] != product_type
                or record['facts_revision'] != facts_revision or record['field'] not in fields):
            raise ValueError(f"Conditional disposition is stale or not applicable to this template/SKU: {record['field']}")
        if record['field'] in bound: raise ValueError(f"Duplicate conditional disposition: {record['field']}")
        bound[record['field']] = record
    return bound


def group_field_blockers(rows):
    """Read-only grouping of the existing decisions, never another applicability gate."""
    groups={}
    for row in rows:
        for decision in row.get('field_decisions',[]):
            status=decision['validation_status']
            if status in {'pass','awaiting_upstream'} or status.startswith('optional_'):continue
            reason=decision.get('activation_reason','')
            field=decision['field'];root=re.split(r'[\[#]',field,1)[0]
            owner='template_rule' if reason=='activation_unknown' else 'business_or_product_evidence'
            key=(status,reason,root if reason=='activation_unknown' or status!='conditional_risk' else reason)
            group=groups.setdefault(key,{'status':status,'reason_code':reason,'owner':owner,'subject':key[2],
                'action':'provide_scoped_rule_evidence' if owner=='template_rule' else 'provide_or_correct_bound_facts','affected':[]})
            group['affected'].append({'sku':row.get('sku',''),'row_type':row.get('row_type',''),'field':field,'label':decision.get('label','')})
    return list(groups.values())


def field_expects_number(field: str) -> bool:
    name = re.sub(r'\[[^]]*\]|#\d+', '', str(field or '').casefold())
    if set(name.split('.')) & {'unit', 'type', 'language_tag'}:
        return False
    return any(
        token in name
        for token in (
            "number_of_items",
            "number_of_doors",
            "number_of_drawers",
            "number_of_shelves",
            "item_weight",
            "item_package_weight",
            "weight_capacity",
            "maximum_weight_recommendation",
            "item_package_quantity",
            "unit_count",
            "list_price",
            ".our_price.schedule.value_with_tax",
            "fulfillment_availability.quantity",
            ".length.value",
            ".width.value",
            ".height.value",
            ".depth.value",
            ".weight.value",
            "normalized_value.value",
        )
    )


def looks_numeric(value: Any, *, field: str = "") -> bool:
    if value in (None, ""):
        return True
    try:
        number = float(str(value).strip())
        if not math.isfinite(number):
            return False
        name = re.sub(r'\[[^]]*\]|#\d+', '', field.casefold())
        if any(token in name for token in ('number_of_', 'item_package_quantity', 'fulfillment_availability.quantity')):
            minimum = 1 if any(token in name for token in ('number_of_items', 'item_package_quantity')) else 0
            return number >= minimum and number.is_integer()
        if '.our_price.schedule.value_with_tax' in name:
            return number > 0
        return not field or number >= 0
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


def fit_template_image_slots(others: list[dict[str, str]], *, required_counts: dict[str, int], limit: int = 8) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    minima = {role: count for role, count in required_counts.items() if role != 'main'}
    if sum(minima.values()) > limit:
        raise ValueError('Template image capacity is smaller than required role coverage')
    kept = list(others)
    omitted: list[dict[str, str]] = []
    for prefix in ('scene', 'func', 'size', ''):
        for index in range(len(kept) - 1, -1, -1):
            if len(kept) <= limit:
                break
            role = str(kept[index].get('role') or '').split('_', 1)[0]
            count = sum(str(row.get('role') or '').split('_', 1)[0] == role for row in kept)
            if (not prefix or role == prefix) and count > minima.get(role, 0):
                omitted.insert(0, kept.pop(index))
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
