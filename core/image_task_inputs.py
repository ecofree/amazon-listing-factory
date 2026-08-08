from __future__ import annotations

import re
from typing import Any

from .status import input_revision_id
from .text_evidence import clean_evidence_text, extract_measurements, has_bad_encoding

_GENERIC_FUNC_TITLE_WORDS = {
    "bed", "cabinet", "classic", "crafted", "design", "details", "feature", "features",
    "first", "frame", "functional", "hardware", "key", "mount", "mounted", "premium",
    "product", "safe", "secure", "safety", "smart", "storage", "sturdy",
}
_FORBIDDEN_FUNC_TITLE_FILLER = {"classic", "crafted", "details", "feature", "features", "functional", "key", "premium", "smart"}
_NON_STORY_FUNC_TITLES = {
    "secure wall mounting",
    "durable painted finish",
    "user friendly details",
    "selected solid pine wood",
    "durable silk foliage",
    "reliable safety and support",
}


def build_renderable_text_contract(
    family: str, measurement: dict[str, Any], *, func_story: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the only strings an image provider may render as pixels."""
    if family in {"main", "scene"}:
        return {"mode": "none", "strings": []}
    if family == "size":
        if measurement.get("mode") == "source_image":
            return {"mode": "preserve_source_measurements", "strings": []}
        raise ValueError("size renderable text requires a source measurement image")
    del func_story
    raise ValueError("func renderable text must be copied from the immutable source content contract")


def build_func_story_contract(
    source: dict[str, Any],
    source_brief: dict[str, Any],
    *,
    product_claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify and copy the one immutable FuncStoryContract chosen upstream."""
    claims = {
        str(row.get("evidence_id") or ""): row
        for row in [*(source.get("claims") or []), *(product_claims or [])]
        if isinstance(row, dict) and str(row.get("evidence_id") or "")
    }
    selected = source_brief.get("func_story_contract")
    if (
        not isinstance(selected, dict)
        or set(selected) != {"mode", "title", "labels", "bindings"}
        or selected.get("mode") != "source_claims"
        or not isinstance(selected.get("labels"), list)
        or not isinstance(selected.get("bindings"), list)
    ):
        raise ValueError("immutable FuncStoryContract is missing")
    title = str(selected.get("title") or "")
    labels = [str(value or "") for value in selected.get("labels") or []]
    strings = [title, *labels]
    bindings = selected["bindings"]
    if (
        not title
        or len(labels) > 6
        or len(strings) != len(bindings)
        or len(strings) != len(set(value.casefold() for value in strings))
        or any(
            not isinstance(row, dict)
            or set(row) != {"evidence_ids", "text"}
            or not isinstance(row.get("evidence_ids"), list)
            or not row.get("evidence_ids")
            or any(str(value or "") not in claims for value in row.get("evidence_ids") or [])
            or str(row.get("text") or "") != strings[index]
            for index, row in enumerate(bindings)
        )
    ):
        raise ValueError("immutable FuncStoryContract or its evidence binding changed")
    return {
        "mode": "source_claims", "title": title, "labels": labels,
        "bindings": [
            {"evidence_ids": [str(value) for value in row["evidence_ids"]], "text": str(row["text"])}
            for row in bindings
        ],
    }


def func_story_title_is_specific(title: Any) -> bool:
    words = [word.casefold() for word in re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", str(title or ""))]
    if not 2 <= len(words) <= 6:
        return False
    normalized_title = " ".join(" ".join(words).replace("-", " ").split())
    if normalized_title in _NON_STORY_FUNC_TITLES:
        return False
    title_concepts = set(words) - _GENERIC_FUNC_TITLE_WORDS - _FORBIDDEN_FUNC_TITLE_FILLER
    return bool(title_concepts)


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
    color = visual_product_color(child)
    if color:
        for key in list(values):
            if str(key).casefold() in {"color", "colour", "color_name"}:
                values[key] = color
    return values


def func_renderable_text_contract(story: dict[str, Any]) -> dict[str, Any]:
    """Project buyer-facing strings from one immutable FuncStoryContract."""
    if not isinstance(story, dict) or story.get("mode") != "source_claims":
        raise ValueError("func story contract is not ready")
    title = str(story.get("title") or "").strip()
    labels = [str(value or "").strip() for value in story.get("labels") or [] if str(value or "").strip()]
    if not title:
        raise ValueError("FuncStoryContract must provide one source-supported title")
    strings = [title, *labels]
    if len(strings) != len(set(value.casefold() for value in strings)):
        raise ValueError("FuncStoryContract contains duplicate renderable strings")
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
            _append_measurement_record(evidence, str(field), str(value or ""), "apify_spec", 1)
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
        canonical = {str(row.get("canonical_value") or "") for row in rows}
        if len(canonical) != 1:
            conflicts.append({"measured_part": part, "axis": axis, "kind": kind, "values": [row["text"] for row in rows]})
            continue
        text = _preferred_measurement_text(rows)
        if re.search(r"\b0(?:\.0+)?\s*(?:lb|lbs|pound|pounds)\b", text, re.I):
            conflicts.append({"measured_part": part, "axis": axis, "kind": kind, "values": [text], "reason": "impossible_zero_weight"})
            continue
        groups_out.append({
            "id": f"{part}:{axis}:{kind}", "measured_part": part, "axis": axis,
            "kind": kind, "canonical_value": next(iter(canonical)), "render_text": text,
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

def product_boundary(
    image_policy: dict[str, Any],
    child: dict[str, Any],
    *,
    product_type: str,
) -> dict[str, Any]:
    """Build the sold-product boundary from program facts and the editable reference."""
    structure = _unique_text(image_policy.get("structure_invariants") or [])
    normalized = child.get("normalized_facts") if isinstance(child.get("normalized_facts"), dict) else {}
    specs = child.get("specs") if isinstance(child.get("specs"), dict) else {}
    color = visual_product_color(child)
    materials = [
        str(value).strip()
        for key, value in specs.items()
        if any(token in str(key).casefold() for token in ("material", "finish"))
        and str(value or "").strip()
    ]
    color_material = "; ".join(
        value for value in [f"color: {color}" if color else "", *materials[:4]]
        if value
    )
    return {
        "sold_product_parts": [
            f"the complete {product_type.lower().replace('_', ' ')} visible in the editable reference",
            "all structural parts, attached supports, and product surfaces visible in that reference",
        ],
        "replaceable_staging": _unique_text(image_policy.get("replaceable_staging") or []),
        "must_not_change": [
            "the product type, source-visible structure, proportions, quantity, color, finish, and attached parts",
            "the source-visible open, closed, installed, assembled, or demonstrated product state",
        ],
        "product_color_material": color_material or "preserve the source-visible product color, finish, and material",
        "observed_product_colors": [{"name": color, "source": "ProductFamilyV3"}] if color else [],
        "conditional_structure_lock": [
            f"Preserve {value} exactly when visible in the editable reference; do not add it when absent"
            for value in structure
        ],
        "forbidden_additions": _forbidden_addition_rules(image_policy.get("forbidden_additions") or []),
    }


def task_facts(child: dict[str, Any], *, product_type: str) -> dict[str, Any]:
    normalized = child.get("normalized_facts") if isinstance(child.get("normalized_facts"), dict) else {}
    return {
        "asin": str(child.get("asin") or ""),
        "product_type": str(product_type or ""),
        "color": visual_product_color(child),
        "size": str(normalized.get("size") or "")[:120],
        "variation": visual_variation_values(child),
        "sold_unit_count": normalized.get("sold_unit_count") or child.get("sold_unit_count"),
    }


EXECUTION_PROFILES = frozenset({
    "reference_edit_soft_lock",
    "source_size_visual_restyle",
    "reference_infographic_design",
})


def execution_profile(family: str, measurement: dict[str, Any]) -> str:
    if family == "size":
        if measurement.get("mode") != "source_image":
            raise ValueError("size execution requires a classified source measurement image")
        return "source_size_visual_restyle"
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
    return _measurement_render_text((imperial or rows)[0].get("text"))


def _measurement_render_text(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    parsed = extract_measurements(text)
    return "" if not parsed or has_bad_encoding(text) else str(parsed[0].get("text") or text).strip()


def _unique_text(values: Any) -> list[str]:
    return list(dict.fromkeys(" ".join(str(value or "").split()) for value in values if str(value or "").strip()))


def _forbidden_addition_rules(values: Any) -> list[str]:
    result: list[str] = []
    for value in values if isinstance(values, list) else []:
        if isinstance(value, dict):
            part = " ".join(str(value.get("part") or "").split())
            if not part: continue
            text = f"Do not add {part}" + (" unless it is visible in the editable reference" if value.get("unless_source_visible") else "")
        else:
            text = " ".join(str(value or "").split())
        if text and text not in result: result.append(text)
    return result
