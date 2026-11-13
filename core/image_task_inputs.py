from __future__ import annotations

import re
from typing import Any

from .status import input_revision_id
from .product_family import effective_product_facts, fact_resolutions
from .text_evidence import clean_evidence_text, extract_measurements, has_bad_encoding, us_measurement_text, measurement_values_match


def role_art_direction(art: dict[str, Any], direction: dict[str, Any], role: str, *, main_policy: str = '', image_policy=None) -> dict[str, Any]:
    """Project shared design within the role's existing environment contract."""
    result = {key: art[key] for key in ('audience_and_market', 'photography_direction')}
    white_main = role.split('_', 1)[0] == 'main' and main_policy == 'white_background'
    if white_main or direction['environment_mode'] == 'graphic_canvas':
        result['photography_direction'] = {'lighting': 'source', 'exposure': 'source'}
    environment = direction['environment_mode'] == 'designed_environment' and not white_main
    selected = set(direction['presentation']['components'])
    if image_policy is not None:
        from .required_role_policy import authorized_staging_targets
        allowed=authorized_staging_targets(image_policy, role=role, environment_mode=direction['environment_mode'])
        if selected - allowed.keys():
            raise ValueError('Palette contains targets outside this role/environment policy: ' + ', '.join(sorted(selected-allowed.keys())))
        if any(f'{group}.{part}' not in authorized_staging_targets(image_policy)
               or not isinstance(color,str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',color)
               for group,parts in art['palette_direction'].items() for part,color in parts.items()):
            raise ValueError('Palette must contain only authorized non-sold target IDs and strict #RRGGBB colors')
    result['palette_direction'] = {
        group: chosen for group, parts in art['palette_direction'].items()
        if (chosen := {part: value for part, value in parts.items()
                       if environment and f'{group}.{part}' in selected})}
    if role.split('_', 1)[0] in {'func', 'size'}:
        result.update({key: art[key] for key in ('typography_direction', 'graphic_direction')})
    return result

def display_quantity_issues(direction: dict[str, Any], selected_count: int, product_type: str, *, product_title: str = '') -> dict[str, str]:
    """Check explicit primary-count claims, not actions, aesthetics or free-text meaning."""
    presentation = direction.get('presentation') or {}
    if presentation.get('scope') != 'whole_product' or not selected_count or not product_type:
        return {}
    from products.generic_extractors import product_pack_counts
    issues = {}
    for path, value in (('visual_goal', direction.get('visual_goal')), ('presentation/state', presentation.get('state'))):
        counts = product_pack_counts(value, title=product_title or product_type.replace('_', ' '), display=True)
        if counts - {selected_count}:
            issues[path] = f'Explicit primary product count {sorted(counts)} contradicts {selected_count} selected instances; correct this field in the same plan'
    return issues


def build_renderable_text_contract(family: str, measurement: dict[str, Any], *, display_copy: dict[str, Any]) -> dict[str, Any]:
    """Return the only strings an image provider may render as pixels."""
    if family in {"main", "scene"}:
        return {"mode": "none", "strings": []}
    from .measurement_sources import MEASUREMENT_MODES
    if family == 'size' and measurement.get('mode') not in MEASUREMENT_MODES:
        raise ValueError('size renderable text requires an explicit measurement source')
    if family in {'func','size'}:
        contract=authored_text_contract(display_copy)
        if measurement.get('mode')=='product_statement':
            contract['strings']=[*contract['strings'],*measurement['render_text']]
            if len({s.casefold() for s in contract['strings']})!=len(contract['strings']):raise ValueError('Duplicate declared measurement text')
        return contract
    raise ValueError("Unknown image role")


def build_display_copy_contract(
    sources: list[dict[str, Any]],
    image_brief: dict[str, Any],
    *,
    product_claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify and copy the one immutable DisplayCopyContract chosen upstream."""
    from .visual_design_kit_compiler import _available_claims, _copy_binding
    claims = _available_claims(sources, product_claims)
    selected = image_brief.get("display_copy_contract")
    if (
        not isinstance(selected, dict)
        or set(selected) != {"mode", "title", "labels", "bindings"}
        or selected.get("mode") != "source_claims"
        or not isinstance(selected.get("labels"), list)
        or not isinstance(selected.get("bindings"), list)
    ):
        raise ValueError("immutable DisplayCopyContract is missing")
    title = str(selected.get("title") or "")
    labels = [str(value or "") for value in selected.get("labels") or []]
    strings = ([title] if title else []) + labels
    bindings = selected["bindings"]
    if (
        any(not value.strip() for value in strings)
        or sum(len(value) for value in strings) > 1200
        or len(strings) != len(bindings)
        or len(strings) != len(set(value.casefold() for value in strings))
        or any(_copy_binding(row, claims)['text'] != strings[index] for index, row in enumerate(bindings))
    ):
        raise ValueError("immutable DisplayCopyContract or its evidence binding changed")
    return {
        "mode": "source_claims", "title": title, "labels": labels,
        "bindings": [
            _copy_binding(row, claims)
            for row in bindings
        ],
    }


def visual_product_color(child: dict[str, Any]) -> str:
    """Return a visual-only color without mutating commerce variation facts.

    Apify variation labels often combine color with size or configuration (for
    example, ``Grey Full Over Full with Trundle``).  Templates and Copy must
    keep that original variation value; image planning only needs the clean
    color from structured specs, with the normalized color used only when it
    is already a standalone value.
    """
    normalized = child.get("normalized_facts") if isinstance(child.get("normalized_facts"), dict) else {}
    specs = child.get("specs") if isinstance(child.get("specs"), dict) else {}
    spec_color = next(
        (str(value).strip() for key, value in specs.items()
         if str(key).casefold() in {"color", "colour", "color_name"} and str(value or "").strip()),
        "",
    )
    # This projection is intentionally limited to structured product facts.
    # Image planning must never infer the product colour from bedding, props,
    # walls, or other staging visible in a reference image.
    candidates = [spec_color, str(normalized.get("color") or "").strip(), str(child.get("color") or "").strip()]
    if 'color' in fact_resolutions(child):
        candidates = [str(effective_product_facts(child).get('color') or '')]
    polluted = re.compile(
        r"\b(?:with|without|over|under|full|twin|queen|king|trundle|bed|frame|cabinet|drawer|door|pack|set|count|size)\b",
        re.IGNORECASE,
    )
    for value in candidates:
        if value and not polluted.search(value):
            return value[:100]
    return ""


def visual_variation_values(child: dict[str, Any]) -> dict[str, Any]:
    """Project variation values for image prompts without changing source facts."""
    normalized = child.get("normalized_facts") if isinstance(child.get("normalized_facts"), dict) else {}
    raw = normalized.get("variation") if isinstance(normalized.get("variation"), dict) else child.get("variation_values")
    values = dict(raw) if isinstance(raw, dict) else {}
    resolutions = fact_resolutions(child)
    from .product_family import fact_key
    for key in list(values):
        decision = resolutions.get(fact_key(key))
        if decision:
            values.pop(key)
            if decision['status'] == 'confirmed':
                values[key] = decision.get('value')
    color = visual_product_color(child)
    if color:
        for key in list(values):
            if str(key).casefold() in {"color", "colour", "color_name"}:
                values[key] = color
    return values


def authored_text_contract(story: dict[str, Any]) -> dict[str, Any]:
    """Project buyer-facing strings from one immutable DisplayCopyContract."""
    if not isinstance(story, dict) or story.get("mode") != "source_claims":
        raise ValueError("display copy contract is not ready")
    title = str(story.get("title") or "").strip()
    labels = [str(value or "").strip() for value in story.get("labels") or [] if str(value or "").strip()]
    strings = ([title] if title else []) + labels
    if len(strings) != len(set(value.casefold() for value in strings)):
        raise ValueError("DisplayCopyContract contains duplicate renderable strings")
    bindings = story.get('bindings')
    if (not isinstance(bindings, list) or len(bindings) != len(strings)
            or any(not isinstance(row, dict) or set(row) != {'text', 'evidence_ids', 'target'}
                   or row['text'] != text or not isinstance(row['evidence_ids'], list) or not row['evidence_ids']
                   or (row['target'] is not None and (not isinstance(row['target'], dict)
                       or set(row['target']) != {'source_id', 'feature_id'}
                       or any(not isinstance(v, str) or not v for v in row['target'].values())))
                   for text, row in zip(strings, bindings))):
        raise ValueError('DisplayCopyContract must retain its exact copy-to-feature bindings')
    return {
        "mode": "exact",
        "strings": strings,
    }


def task_renderable_text(task: dict[str, Any]) -> list[str]:
    contract = task.get("renderable_text_contract") if isinstance(task.get("renderable_text_contract"), dict) else {}
    return list(contract.get("strings") or [])


def measurement_contract(child: dict[str, Any]) -> dict[str, Any]:
    """Resolve specs by measured part, axis, unit-equivalent value, and source."""
    normalized = child.get("normalized_facts") if isinstance(child.get("normalized_facts"), dict) else {}
    evidence: list[dict[str, Any]] = []
    records = normalized.get("spec_measurement_records") if isinstance(normalized.get("spec_measurement_records"), list) else []
    for record in records:
        if isinstance(record, dict):
            _append_measurement_record(evidence, str(record.get("field") or "overall_dimensions"), str(record.get("text") or ""), "normalized_spec", 0)
    if not records and str(normalized.get("physical_dimensions") or "").strip():
        _append_measurement_record(evidence, "overall_dimensions", str(normalized["physical_dimensions"]), "physical_dimensions", 0)
    # Raw Apify specs remain authoritative even when normalized records are
    # only partially populated. One dimension record must not hide a separate
    # load-capacity or weight field.
    for field, value in (child.get("specs") if isinstance(child.get("specs"), dict) else {}).items():
        key = str(field).casefold()
        if any(token in key for token in ("package", "shipping", "carton")):
            continue
        if any(token in key for token in ("dimension", "height", "width", "depth", "length", "weight", "capacity", "load")):
            unit = (child.get('specs') or {}).get(f'{field}_unit')
            text = f'{value} {unit}' if unit and not extract_measurements(value) else str(value or '')
            _append_measurement_record(evidence, str(field), text, "apify_spec", 1)
    unique_evidence: list[dict[str, Any]] = []
    seen_evidence: set[tuple[str, str, str, str]] = set()
    for row in evidence:
        key = (
            str(row.get("measured_part") or ""), str(row.get("axis") or ""),
            str(row.get("kind") or ""), str(row.get("canonical_value") or ""),
        )
        if key not in seen_evidence:
            seen_evidence.add(key)
            unique_evidence.append(row)
    evidence = unique_evidence
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in evidence:
        groups.setdefault((str(row["measured_part"]), str(row.get("axis") or "unspecified"), str(row["kind"])), []).append(row)
    render: list[str] = []
    conflicts: list[dict[str, Any]] = []
    groups_out: list[dict[str, Any]] = []
    for (part, axis, kind), rows in groups.items():
        if not all(measurement_values_match(rows[0]['text'], row['text']) or measurement_values_match(row['text'], rows[0]['text']) for row in rows):
            conflicts.append({"measured_part": part, "axis": axis, "kind": kind, "values": [row["text"] for row in rows]})
            continue
        text = _preferred_measurement_text(rows)
        if re.search(r"\b0(?:\.0+)?\s*(?:lb|lbs|pound|pounds)\b", text, re.I):
            conflicts.append({"measured_part": part, "axis": axis, "kind": kind, "values": [text], "reason": "impossible_zero_weight"})
            continue
        groups_out.append({
            "id": f"{part}:{axis}:{kind}", "measured_part": part, "axis": axis,
            "kind": kind, "canonical_value": rows[0]['canonical_value'], "render_text": text,
        })
        if text and text not in render:
            render.append(text)
    return {
        "status": "confirmed" if render else "conflicted" if conflicts else "unconfirmed",
        "render_text": render,
        "measurement_groups": groups_out,
        "conflicts": conflicts,
        "evidence": evidence,
    }

def _appearance_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    appearances = []
    for source in sources:
        observation = source.get('observation', source.get('visual_evidence')) or {}
        if observation.get('product_extent') == 'whole_view' and 'appearance' in observation.get('reference_purposes', []):
            appearances.append(source)
    return sorted(appearances, key=lambda row: (row.get('role') != 'main', int(row.get('source_index') or 0)))


def _role_sources(sources: list[dict[str, Any]], family: str) -> list[dict[str, Any]]:
    if family == 'main':
        return _appearance_sources(sources)
    if family == 'size':
        return sorted((row for row in sources if row.get('measurements')),
                      key=lambda row: row.get('role') != 'size')
    matches = [row for row in sources if row.get('role') == family]
    return matches or (_appearance_sources(sources)[:1] if family == 'scene' else [])


def initial_output_inventory(sources: list[dict[str, Any]], *, previous: dict[str, Any] | None = None, statement_sources=None) -> list[dict[str, str]]:
    """Keep allocated identities, restoring outputs for current source purposes."""
    ordered = sorted(({**row, 'source_id': row.get('source_id') or f"source_{int(row['source_index']):02d}"} for row in sources),
                     key=lambda row: int(row.get('source_index') or 0))
    def bind_statements(inventory):
        from .image_reference_context import has_visible_product_evidence
        catalog={s['source_id']:s for s in ordered}
        for slot in inventory:
            selected=(statement_sources or {}).get(slot['role'])
            if not slot['source_id'] and selected:
                source=catalog.get(selected)
                if not source or not has_visible_product_evidence(source.get('observation',source.get('visual_evidence')) or {}):
                    raise ValueError('Statement coverage lacks a usable child source')
                slot['source_id']=selected
        return inventory
    if previous is not None:
        # Preserve allocated identities; empty anchors can acquire verified evidence.
        from .image_reference_context import has_visible_product_evidence
        inventory = [dict(row) for row in previous['output_inventory']]
        for slot in inventory:
            if slot['source_id']:
                continue
            family = slot['role'].split('_', 1)[0]
            used = {s['source_id'] for s in inventory if s['role'].split('_', 1)[0] == family}
            source = next((s for s in _role_sources(ordered, family)
                if s['source_id'] not in used and has_visible_product_evidence(s.get('observation', s.get('visual_evidence')) or {})), None)
            if source:
                slot['source_id'] = source['source_id']
        return bind_statements(inventory)
    appearances = _appearance_sources(ordered)
    main = appearances[0] if appearances else None
    specs = [{'role': 'main', 'source': main, 'reason': '' if main else 'No selected whole-product appearance evidence'}]
    for family in ('scene', 'func', 'size'):
        matches = _role_sources(ordered, family)
        if family == 'size':
            matches = matches[:1]  # Other measurement sources remain evidence, not competing outputs.
        if matches:
            specs.extend({'role': family if i == 1 else f'{family}_{i:02d}', 'source': row, 'reason': ''}
                         for i, row in enumerate(matches, 1))
        else:
            specs.append({'role': family, 'source': None, 'reason': f'No final source intent is classified as {family}'})
    return bind_statements([{'role':spec['role'],'source_id':spec['source']['source_id'] if spec['source'] else ''} for spec in specs])


def task_specs(child: dict[str, Any], sources: list[dict[str, Any]], *, inventory: list[dict[str, str]],
               include_optional: bool = False) -> list[dict[str, Any]]:
    """Resolve frozen output slots against current evidence, never renumber them."""
    if (not isinstance(inventory, list) or not inventory
            or any(not isinstance(row, dict) or set(row) != {'role', 'source_id'}
                   or not isinstance(row['source_id'], str)
                   or not re.fullmatch(r'(main|scene|func|size)(?:_\d{2,})?', str(row['role'])) for row in inventory)
            or len({row['role'] for row in inventory}) != len(inventory)
            or not {'main', 'scene', 'func', 'size'} <= {row['role'] for row in inventory}):
        raise ValueError('Current child needs its frozen output inventory')
    catalog = {row.get('source_id') or f"source_{int(row['source_index']):02d}": row for row in sources
               if not child.get('asin') or row.get('child') in (None, child['asin'])}
    specs = []
    for slot in inventory:
        role = slot['role']
        if not include_optional and role not in {'main', 'scene', 'func', 'size'}:
            continue
        source = catalog.get(slot['source_id'])
        specs.append({'role': role, 'source': source, 'reason': '' if source else 'Output evidence anchor is unresolved'})
    for spec in specs:
        family = spec['role'].split('_', 1)[0]
        peers = [row for row in specs if row['role'].split('_', 1)[0] == family]
        spec.update(instance_index=peers.index(spec) + 1, instance_count=len(peers), evidence_pending=spec['source'] is None)
    return specs


def task_facts(child: dict[str, Any], *, product_type: str) -> dict[str, Any]:
    facts = effective_product_facts(child)
    return {
        "asin": str(child.get("asin") or ""),
        "product_type": str(product_type or ""),
        "color": visual_product_color(child),
        "size": str(facts.get("size") or "")[:120],
        "physical_dimensions": {key: facts[key] for key in ('length', 'width', 'height', 'item_depth',
            'length_unit', 'width_unit', 'height_unit', 'item_depth_unit') if key in facts},
        "variation": visual_variation_values(child),
        "sold_unit_count": fact_resolutions(child).get("sold_unit_count", {}).get("value"),
    }


EXECUTION_PROFILES = frozenset({
    "reference_edit_soft_lock",
    "source_size_visual_restyle",
    "statement_size_visual_restyle",
    "reference_infographic_design",
})


def execution_profile(family: str, measurement: dict[str, Any]) -> str:
    if family == "size":
        if measurement.get('mode')=='product_statement':return 'statement_size_visual_restyle'
        if measurement.get('mode')!='source_image':raise ValueError('size execution requires an explicit measurement source')
        return 'source_size_visual_restyle'
    return "reference_infographic_design" if family == "func" else "reference_edit_soft_lock"


def release_candidate_fingerprint(task: dict[str, Any], candidate: dict[str, Any]) -> str:
    return input_revision_id({
        "schema": task.get("schema_version"), "task_fingerprint": task.get("task_fingerprint"),
        "candidate_sha256": candidate.get("candidate_sha256"), "candidate_path": str(candidate.get("candidate_path") or ""),
        "provider_physical": str(candidate.get("provider_physical") or ""),
        "request_prompt_fingerprint": str(candidate.get("request_prompt_fingerprint") or ""),
    })


def _append_measurement_record(result: list[dict[str, Any]], field: str, text: str, source: str, priority: int) -> None:
    parsed = extract_measurements(clean_evidence_text(text))
    base = _measurement_field(field)
    if not base:
        return
    for index, row in enumerate(parsed):
        kind = str(row.get("kind") or "")
        if (base == "maximum_load") != (kind == "weight_g"):
            continue
        part = _axis_dimension_field(str(row.get("axis_hint") or "")) or _indexed_dimension_field(base, index, len(parsed))
        result.append({
            **row, "measured_part": part, "axis": _measurement_axis(part),
            "equivalence_group": f"{part}:{_measurement_axis(part)}:{row.get('kind')}",
            "source": source, "source_priority": priority,
        })


def _measurement_field(value: str) -> str:
    field = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    if any(token in field for token in ("shipping", "package", "carton", "item_weight", "product_weight", "net_weight")):
        return ""
    if "load" in field or ("capacity" in field and "weight" in field) or ("maximum" in field and "weight" in field):
        return "maximum_load"
    if any(token in field for token in ("height", "vertical")): return "overall_height"
    if any(token in field for token in ("width", "horizontal")): return "overall_width"
    if "length" in field: return "overall_length"
    if any(token in field for token in ("depth", "thickness")): return "overall_depth"
    if "dimension" in field or field in {"size", "item_size", "product_size"}: return "overall_dimensions"
    return ""


def _indexed_dimension_field(field: str, index: int, count: int) -> str:
    if field != "overall_dimensions" or count < 2: return field
    return ("overall_length", "overall_width", "overall_height")[min(index, 2)]


def _axis_dimension_field(value: str) -> str:
    return {
        "l": "overall_length", "length": "overall_length",
        "w": "overall_width", "width": "overall_width",
        "h": "overall_height", "height": "overall_height",
        "d": "overall_depth", "depth": "overall_depth",
    }.get(value.casefold(), "")


def _measurement_axis(part: str) -> str:
    return {
        "overall_length": "longitudinal", "overall_width": "horizontal",
        "overall_height": "vertical", "overall_depth": "depth", "maximum_load": "load",
    }.get(str(part), "unspecified")


def _preferred_measurement_text(rows: list[dict[str, Any]]) -> str:
    imperial = [row for row in rows if str(row.get("unit") or "") in {"in", "ft", "lb", "oz"}]
    return us_measurement_text(_measurement_render_text((imperial or rows)[0].get("text")))


def _measurement_render_text(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    parsed = extract_measurements(text)
    return "" if not parsed or has_bad_encoding(text) else str(parsed[0].get("text") or text).strip()
