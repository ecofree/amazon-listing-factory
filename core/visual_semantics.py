from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .io import file_sha256, parse_json_object_response, read_json, write_json
from .status import input_revision_id
from .vision_gemini_client import gemini_stream_generate, VisionRequestError
from .text_evidence import extract_measurements
from .image_reference_context import physical_views, source_box, source_point, measurement_attachment_location, view_identity


OBSERVATION_POLICY = "child-joint-observation-v19-settled-requests"
CLAIM_REVIEW_POLICY = "planning-binding-review-v15-target-consistency"
CANDIDATE_OBSERVATION_POLICY = "blind-candidate-observation-v14-product-identity"
TEXT_KINDS = {"product_label", "marketing", "measurement", "prop", "unknown"}
MEMBERSHIPS = {"product", "included_accessory", "staging", "unknown"}


def _attempt_trace(path: Path, *, observer: Any = None) -> tuple[list[dict[str, Any]], Any]:
    events: list[dict[str, Any]] = read_json(path) if path.is_file() else []
    trace_id = uuid.uuid4().hex

    def record(event: dict[str, Any]) -> None:
        if observer is not None:
            observer(event)
        if event.get('event') == 'request_budget':
            return
        summary = {key: event.get(key) for key in (
            "request_id", "provider", "model", "protocol", "attempt", "status", "elapsed_ms",
            "finish_reasons", "usage", "max_output_tokens", "output_token_cap", "response_body_sha256", "physical_request_count",
        )}
        summary["error"] = str(event.get("error") or "")[:1200]
        summary["validation_errors"] = [str(row["validation_error"])[:1200]
            for row in event.get("response_candidates") or [] if row.get("validation_error")]
        response = str(event.get("response_text") or "")
        summary["response_char_count"] = len(response)
        for kind, content in (('request', event.get('request_text')), ('response', response), ('raw_response', event.get('response_body'))):
            if content:
                target = path.with_name(f'{path.stem}.{trace_id}.{len(events) + 1}.{kind}.txt')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding='utf-8')
                summary[kind + '_path'] = target.name
        events.append(summary)
        write_json(path, events)

    return events, record


def source_fact_records(child: dict[str, Any]) -> dict[str, str]:
    """Keep complete source statements; commerce defaults do not prove claims."""
    records: dict[str, str] = {}

    def visit(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).endswith('_unit') and str(key)[:-5] in value:
                    continue
                unit = value.get(f'{key}_unit')
                visit(f'{item} {unit}' if unit and not isinstance(item, (dict, list)) and not extract_measurements(item) else item, f"{prefix}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{prefix}.{index}")
        elif value is not None and str(value).strip():
            records[prefix] = str(value).strip()

    for field in ("title", "bullets", "description", "features", "specs", "product_specific", "variation_values"):
        visit(child.get(field), f"product.{field}")
    normalized = child.get("normalized_facts") or {}
    for field in ("color", "size", "style", "variation"):
        visit(normalized.get(field), f"product.normalized_facts.{field}")
    return records


def observe_child_sources(
    job: Path, child: dict[str, Any], sources: list[dict[str, Any]],
    *, deadline_monotonic: float | None = None, corrections: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Replace individual visual recovery with one child-scoped observation."""
    deadline = min(deadline_monotonic or float('inf'), time.monotonic() + 100)
    facts = source_fact_records(child)
    text_ids = {text: f'fact_{index}' for index, text in enumerate(dict.fromkeys(facts.values()), 1)}
    source_ids = [str(row["source_id"]) for row in sources]
    inputs = [{key: row[key] for key in ("source_id", "sha256", "ocr")} for row in sources]
    revision = input_revision_id({"policy": OBSERVATION_POLICY, "child": child.get("asin"), "facts": facts, "inputs": inputs})
    cache = job / "reports" / "source_observations" / f"{revision}.json"
    retained = []
    attempts_used: dict[str, int] = {}
    corrections = corrections or {}
    if cache.is_file():
        value = read_json(cache)
        if value.get("input_revision_id") == revision:
            attempts_used = value.get('attempts_used', {})
            observed = _validate_observations(value["sources"], source_ids, facts)
            for row in value['sources']:
                correction = corrections.get(row['source_id'])
                revision_matches = not correction or row.get('correction_revision', '') == correction['revision']
                applied = (bool(row.get('planning_correction')) and revision_matches
                           and (not correction or row['planning_correction'] == correction.get('planning_correction')))
                if (revision_matches and (not correction or not correction.get('planning_correction') or applied)
                        and observed[row['source_id']]['status'] == 'success'):
                    retained.append(row)
            if len(retained) == len(sources):
                return observed
    retained_ids = {row["source_id"] for row in retained}
    requested = [row for row in sources if row["source_id"] not in retained_ids]
    # Persist consumption before the bounded correction request, including interruption.
    correction_rows = {row['source_id']: {'source_id': row['source_id'], 'status': 'failed',
        'error': 'Planning observation correction is unresolved', 'correction_revision': corrections[row['source_id']]['revision'],
        'planning_correction': corrections[row['source_id']]['planning_correction']}
        for row in requested if corrections.get(row['source_id'], {}).get('planning_correction')}
    schema = {
        "sources": [{
            "source_id": "attachment source_id",
            "role_guess": "scene|func|size|unknown",
            "has_dimension_lines": False,
            "has_callouts_or_panels": False,
            "visible_numbers_or_units": ["34.5 inches"],
            "layout_summary": "classification evidence only, not a design prescription",
            "view_coverage": "complete",
            "physical_views": [{"view_id": "view_01", "region": {"left": 0.12, "top": 0.23, "right": 0.87, "bottom": 0.94},
                "extent": "whole_view|detail", "evidence": [{"feature_id": "stable physical feature/state identity shared ONLY if visibly present in both views",
                    "object_id": "one observed object_id", "region": {"left": 0.12, "top": 0.23, "right": 0.87, "bottom": 0.94},
                    "physical_facts": ["one directly visible part, geometry, mechanism, finish, local count or state; confirmed absence only with visible evidence"]}]}],
            "confidence": 0.0,
            "evidence": ["One product view with a visible height annotation"],
            "variant_identity": {
                "status": "consistent|contradiction|unknown",
                "observed_color": "visible sold-product finish, not bedding or lighting; empty if unclear",
                "reason": "pixel evidence compared to this child's recorded variant, not gallery ownership",
                "conflicts": [{"fact_id": "product.*", "observed": "visible conflicting attribute"}],
            },
            "text_observations": [{"text": "verbatim", "kind": "product_label|marketing|measurement|prop|unknown"}],
            "measurements": [{"measurement_id": "unique source-local annotation identity",
                "text": "34.5 inches", "object": "cabinet",
                "axis": "width",
                "region": {"left": 0.15, "top": 0.07, "right": 0.25, "bottom": 0.12},
                "endpoints": [{"x": 0.12, "y": 0.3}, {"x": 0.87, "y": 0.3}],
                "kind": "dimension", "view_id": "view_01"},
                {"measurement_id": "load_01", "text": "120 lbs", "object": "whole cabinet", "axis": "capacity",
                 "region": {"left": 0.15, "top": 0.07, "right": 0.25, "bottom": 0.12},
                 "endpoints": None, "kind": "capacity", "view_id": "view_01"}],
            "objects": [{
                "object_id": "stable child-local identity across views",
                "kind": "sold object, included part or uncertain product-like object; no decorative color/style",
                "sale_membership": "product|included_accessory|staging|unknown",
                "membership_evidence": [{"fact_id": "product.*", "quote": "exact source statement"}],
                "visibility": "visible|occluded|not_observed",
                "state": "only this object's physical count, open/closed state, visible extent and occlusion; no decorative colors, style or descriptions of other objects",
                "relations": [{"predicate": "part_of|contained_in|occludes", "target_id": "object_id"}],
            }],
        }],
    }
    prompt = (
        "Observe the gallery returned for ONE child together; gallery ownership does not prove variant identity. "
        "Return exactly one JSON object with a top-level sources array. Do not wrap it in schema, result, data or observations. "
        "Keep each source_id aligned with its attachment. Report physical evidence separately from source graphics: "
        "layout_summary holds source styling and drawn annotations; physical_facts hold atomic real-part facts only. "
        "Separate authored marketing/dimensions, product surface labels and loose prop text. "
        "Ordinary books do not make a scene a function infographic. Quote complete visible claims, "
        "including counts, measured objects and qualifiers; leave illegible text unknown. "
        "Inventory every distinct product photo, inset and placement diagram, including small corner details; "
        "locate its visible physical features first (evidence object_id, feature_id, region, physical_facts), "
        "then enclose ALL of that view's visible product, attached parts and occluding accessories in physical_views.region. "
        "A feature_id identifies the same visible structure AND state, not merely the same product; an edge joint is not slatted support. "
        "Source regions are named {left,top,right,bottom}; endpoints are named {x,y}. All coordinates are fractions of the ORIGINAL attachment width/height. "
        "Left/right measure horizontal distance from the left edge; top/bottom measure vertical distance from the top edge. Never return coordinate arrays. "
        "Use whole_view for a complete visible product view, detail for a partial close-up. "
        "Crop each photo independently, excluding separable title bands, neighboring insets and room decor. "
        "Overlapping graphics stay in the evidence crop; never erase or clip a product part or occluding bedding to remove them. "
        "Each physical view encloses its complete measured product and both physical endpoints. Record each annotation once in measurements: "
        "the specific measured part/property (underbed clearance is not overall bed height), axis, one quantity/unit and its original-page label region. "
        "A dimension label or capacity badge can lie OUTSIDE the product view; bind it to the measured view without moving its coordinates. "
        "Measurement kind is dimension, capacity or weight; capacity/weight badges have null endpoints, not an empty array. "
        "Resolve OCR against pixels at the same annotation; inches and feet readings of one mark are alternatives, not two facts. "
        "Never promote unlocated OCR or a bare number into measurements; report unreadable annotations in evidence. "
        "physical_views=[] only if no product view can be identified. "
        "view_coverage is exactly complete or partial; put explanations in evidence, a list of strings. "
        "visible_numbers_or_units is also a list of strings, not measurement objects. "
        "Mark partial if any product-bearing region cannot be fully located; never silently drop a small inset. "
        "Alternative adjustment positions, arrows, ghosted parts and inset borders are diagram notation, not additional physical components. "
        "Inventory the sold product, included accessories and uncertain product-like objects. Ordinary non-sold decor is optional context, "
        "not a completeness requirement. Record occlusion only to explain which product evidence is unavailable. "
        "Product state describes the sold object only. Bed textiles use a separate staging object linked by occludes; "
        "source decorative colors/patterns belong neither in product state nor physical_facts. "
        "An object inside a drawer is contained_in, not automatically part_of. "
        "Not observed never means confirmed absent. Product/accessory sales membership requires "
        "an exact citation to supplied product records (facts maps source IDs to fact_texts); visual resemblance alone is insufficient. "
        "Uncertain ownership stays unknown; it is not proof that ordinary staging is sold or must remain in the target. "
        "Compare each visible sold product's finish, variant and structure to the child records and other views. "
        "Record a clear mismatch as variant_identity contradiction with the conflicting fact_id and observed attribute, "
        "even if that attachment came from this child's gallery. Never relabel its visible finish to match the listing. "
        "Cropped, occluded, uncolored diagrams or ambiguous lighting are unknown, not contradictions. "
        "Do not infer material specifications, performance or dimensions from appearance.\n"
        + "\nRequired response shape (replace example values):\n" + json.dumps(schema, ensure_ascii=False)
    )

    def validate(text: str) -> bool:
        value = parse_json_object_response(text)
        if not isinstance(value.get("sources"), list):
            raise ValueError("joint observation requires one top-level sources array containing every attachment")
        requested_ids = {row["source_id"] for row in requested}
        if any(not isinstance(row, dict) or row.get("source_id") not in requested_ids for row in value["sources"]):
            raise ValueError("Observation response changed the requested attachment scope")
        _validate_observations([*retained, *value["sources"]], source_ids, facts)
        return True

    trace = cache.with_name(cache.stem + '.' + uuid.uuid4().hex)
    cache.parent.mkdir(parents=True, exist_ok=True)
    result = observed if cache.is_file() and value.get('input_revision_id') == revision else _validate_observations(retained, source_ids, facts)
    for row in requested:
        if result[row['source_id']]['status'] == 'success':
            result[row['source_id']] = correction_rows.get(row['source_id'], {
                'source_id': row['source_id'], 'status': 'failed', 'error': 'Requested product observation revision is unresolved'})
    # Spend the existing two-request budget on unresolved rows, never successful attachments.
    for attempt in range(2):
        for row in requested:
            if attempts_used.get(row['source_id'], 0) >= 4:
                result[row['source_id']]['error'] = 'Source observation request budget exhausted for this input revision; no request sent'
        requested = [row for row in requested if attempts_used.get(row['source_id'], 0) < 4]
        if not requested or time.monotonic() >= deadline:
            break
        initial_counts = dict(attempts_used)
        unresolved = [correction_rows.get(row['source_id'], result[row['source_id']]) for row in sources
                      if row['source_id'] not in {r['source_id'] for r in retained}]

        def settle(event: dict[str, Any]) -> None:
            if event.get('event') == 'request_budget':
                for row in requested:
                    attempts_used[row['source_id']] = initial_counts.get(row['source_id'], 0) + event['physical_request_count']
                write_json(cache, {'input_revision_id': revision, 'policy': OBSERVATION_POLICY,
                    'attempts_used': attempts_used, 'sources': [*retained, *unresolved]})

        _events, record = _attempt_trace(trace.with_name(trace.name + '.attempts.json'), observer=settle)
        request_scope = [row['source_id'] for row in requested]
        limits = list({(item.get('provider'), item.get('model'), item.get('max_output_tokens')): item
            for row in requested for failure in [result[row['source_id']].get('request_failure', {})]
            if failure.get('request_scope') == request_scope for item in failure.get('output_limits', [])}.values())
        request = prompt + "\nInput evidence, not response fields:\n" + json.dumps({
            "facts": {key: text_ids[text] for key, text in facts.items()}, 'fact_texts': {key: text for text, key in text_ids.items()},
            "attachments": [{k: row[k] for k in ('source_id', 'sha256', 'ocr')} for row in requested],
            "already_observed_read_only": [{"source_id": row['source_id'], "objects": row.get('objects', [])} for row in retained],
            "repair_findings": {row['source_id']: result[row['source_id']].get('error') for row in requested} if attempt else {},
            'correction_requests': {row['source_id']: corrections[row['source_id']]['reason'] for row in requested if row['source_id'] in corrections},
        }, ensure_ascii=False)
        trace.with_name(trace.name + f".{attempt + 1}.request.txt").write_text(request, encoding="utf-8")
        try:
            response = gemini_stream_generate(
                request, [Path(row["path"]) for row in requested], client_scope="visual_planning",
                attempts=1, timeout_seconds=60, total_timeout_seconds=100,
                max_physical_requests=1, deadline_monotonic=deadline,
                max_output_tokens=min(32768, max(8192, 2400 * len(requested),
                    max((int(row.get('max_output_tokens') or 0) * 2 for row in limits), default=0))),
                prior_output_limits=limits,
                response_validator=validate, request_id=f"source-observation:{revision}:{attempt + 1}", attempt_observer=record,
            )
            validate(response)
            raw = [*retained, *({**{key: value for key, value in row.items() if key not in {'correction_revision', 'planning_correction'}},
                                'correction_revision': corrections.get(row['source_id'], {}).get('revision', ''),
                                **({'planning_correction': corrections[row['source_id']]['planning_correction']}
                                   if corrections.get(row['source_id'], {}).get('planning_correction') else {})}
                               for row in parse_json_object_response(response)['sources'])]
            result = _validate_observations(raw, source_ids, facts)
            retained = [row for row in raw if result[row['source_id']]['status'] == 'success' or row['source_id'] in retained_ids]
        except Exception as exc:
            failure = ({'kind': exc.failure_kind, 'request_scope': request_scope,
                        'output_limits': [*limits, *exc.metadata.get('output_limits', [])]}
                       if isinstance(exc, VisionRequestError) else {})
            for row in requested:
                result[row['source_id']] = {'source_id': row['source_id'], 'status': 'failed',
                    'error': f'{type(exc).__name__}: {exc}'[:1200], 'request_failure': failure}
        for source_id, correction_row in correction_rows.items():
            result[source_id] = {**correction_row, **result[source_id]}
        requested = [row for row in sources if row['source_id'] not in retained_ids and result[row['source_id']]['status'] != 'success']
        write_json(cache, {"input_revision_id": revision, "policy": OBSERVATION_POLICY, "attempts_used": attempts_used, "sources": [
            *retained, *(result[row['source_id']] for row in requested)]})
    for source_id, correction in corrections.items():
        result[source_id]['correction_revision'] = correction['revision']
    return result


def _validate_observations(
    rows: Any, source_ids: list[str], facts: dict[str, str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) or row.get("source_id") not in source_ids for row in rows):
        raise ValueError("Observation attachment inventory is invalid")
    ids = [row["source_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Observation attachment identity is duplicated")
    result = {key: {"source_id": key, "status": "failed", "error": "Joint observation omitted this source"} for key in source_ids}
    for row in rows:
        key = row["source_id"]
        if row.get('status') == 'failed' and isinstance(row.get('error'), str) and row['error']:
            result[key] = {k: row[k] for k in ('source_id', 'status', 'error', 'correction_revision', 'planning_correction', 'request_failure') if k in row}
            continue
        try:
            result.update(_validate_observation_rows([row], [key], facts))
        except ValueError as exc:
            result[key] = {"source_id": key, "status": "failed", "error": str(exc)}
    memberships: dict[str, set[str]] = {}
    for row in result.values():
        for obj in row.get("objects", []):
            memberships.setdefault(obj["object_id"], set()).add(obj["sale_membership"])
    conflicts = {key for key, values in memberships.items() if "staging" in values and values & {"product", "included_accessory"}}
    for key, row in list(result.items()):
        row["object_identity_conflicts"] = sorted({obj["object_id"] for obj in row.get("objects", [])} & conflicts)
        if any(rel["target_id"] not in memberships for obj in row.get("objects", [])
               if obj['sale_membership'] in {'product', 'included_accessory'} for rel in obj["relations"] if rel['predicate'] == 'part_of'):
            result[key] = {"source_id": key, "status": "failed", "error": "Object relation refers to an unresolved identity"}
    return result


def _validate_observation_rows(
    rows: Any, source_ids: list[str], facts: dict[str, str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError("child observations must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("source_id") not in source_ids:
            raise ValueError("observation has an unknown source_id")
        key = row["source_id"]
        if key in result or row.get("role_guess") not in {"scene", "func", "size", "unknown"}:
            raise ValueError("duplicate observation or invalid role")
        if any(type(row.get(field)) is not bool for field in ("has_dimension_lines", "has_callouts_or_panels")):
            raise ValueError("observed layout flags must be explicit booleans")
        if not isinstance(row.get("confidence"), (int, float)) or not 0 <= row["confidence"] <= 1:
            raise ValueError("observation confidence is outside zero to one")
        errors = [f'{field} must be a list of strings' for field in ('visible_numbers_or_units', 'evidence')
                  if not isinstance(row.get(field), list) or any(not isinstance(item, str) for item in row[field])]
        identity = row.get("variant_identity")
        if not isinstance(identity, dict) or identity.get("status") not in {"consistent", "contradiction", "unknown"}:
            raise ValueError("source observation requires a variant identity assessment")
        if not isinstance(identity.get("observed_color"), str) or not isinstance(identity.get("reason"), str) or not identity["reason"].strip():
            raise ValueError("variant identity needs observed color and an evidence explanation")
        conflicts = identity.get("conflicts")
        if not isinstance(conflicts, list) or bool(conflicts) != (identity["status"] == "contradiction"):
            raise ValueError("variant identity verdict contradicts its conflict inventory")
        for conflict in conflicts:
            if not isinstance(conflict, dict) or conflict.get("fact_id") not in facts or not isinstance(conflict.get("observed"), str) or not conflict["observed"].strip():
                raise ValueError("variant conflict must identify a child fact and visible conflicting attribute")
        objects = row.get("objects")
        texts = row.get("text_observations")
        if row.get('view_coverage') != 'complete':
            errors.append(f"view_coverage: expected complete, received {row.get('view_coverage')!r}; locate missing views if partial")
        views = []
        try:
            views = physical_views(row.get('physical_views'))
            _validate_source_measurements(row.get('measurements'), views)
        except ValueError as exc:
            errors.append(str(exc))
        if errors:
            raise ValueError(key + ': ' + '; '.join(errors))
        if row['has_dimension_lines'] and not any(item['kind'] == 'dimension' for item in row['measurements']):
            raise ValueError('Visible dimension lines need located measurements, not an empty inventory')
        if not views and row["role_guess"] != "unknown":
            raise ValueError("Recognized source needs observed physical views")
        if not isinstance(objects, list) or not isinstance(texts, list):
            raise ValueError("observation needs object and text lists")
        for item in texts:
            if not isinstance(item, dict) or item.get("kind") not in TEXT_KINDS or not isinstance(item.get("text"), str):
                raise ValueError("invalid observed text category")
        transcribed = {m['canonical_pair'] for item in texts if item['kind'] == 'measurement' for m in extract_measurements(item['text'])}
        located = {m['canonical_pair'] for item in row['measurements'] for m in extract_measurements(item['text'])}
        if not transcribed <= located:
            raise ValueError('Locate every transcribed measurement; do not omit badges or invent a second reading')
        seen_objects: set[str] = set()
        for obj in objects:
            if not isinstance(obj, dict) or not obj.get("object_id") or not obj.get("kind"):
                raise ValueError("observed object has no identity")
            if any(not isinstance(obj.get(field), str) for field in ("object_id", "kind", "state")) or obj["object_id"] in seen_objects:
                raise ValueError("observed object identity is duplicate or malformed")
            seen_objects.add(obj["object_id"])
            if obj.get("sale_membership") not in MEMBERSHIPS or obj.get("visibility") not in {"visible", "occluded", "not_observed"}:
                raise ValueError("invalid object membership or visibility")
            refs = obj.get("membership_evidence") or []
            if not isinstance(refs, list):
                raise ValueError("membership evidence must be a list")
            for ref in refs:
                if not isinstance(ref, dict) or ref.get("fact_id") not in facts or not ref.get("quote") or ref["quote"] not in facts[ref["fact_id"]]:
                    raise ValueError("object membership citation is not source-bound")
            if obj["sale_membership"] in {"product", "included_accessory"} and not refs:
                raise ValueError("sales membership requires product evidence; otherwise use unknown")
            if not isinstance(obj.get("relations"), list):
                raise ValueError("object relations must be a list")
            for relation in obj["relations"]:
                if not isinstance(relation, dict) or relation.get("predicate") not in {"part_of", "contained_in", "occludes"} or not relation.get("target_id"):
                    raise ValueError("invalid object relation")
        if any(item['object_id'] not in seen_objects for view in views for item in view['evidence']):
            raise ValueError("Physical view evidence refers to an unobserved object")
        result[key] = {**row, "status": "success", "policy_version": OBSERVATION_POLICY,
                       "child_facts_revision_id": input_revision_id(facts)}
    if set(result) != set(source_ids):
        raise ValueError("joint observation omitted sources")
    return result


def _validate_source_measurements(rows: Any, views: list[dict[str, Any]]) -> None:
    if not isinstance(rows, list):
        raise ValueError('Observation needs a located measurement inventory, empty when not applicable')
    by_view = {view['view_id']: source_box(view['region']) for view in views}
    identities, locations = set(), set()
    errors = []
    for index, row in enumerate(rows):
        try:
            _validate_measurement(row, by_view, identities, locations)
        except ValueError as exc:
            errors.append(f'measurements[{index}]: {exc}')
    if errors:
        raise ValueError('; '.join(errors))


def _validate_measurement(row: Any, by_view: dict, identities: set, locations: set) -> None:
    if (not isinstance(row, dict) or set(row) != {'measurement_id', 'text', 'object', 'axis', 'region', 'endpoints', 'kind', 'view_id'}
            or not all(isinstance(row[k], str) and row[k].strip() for k in ('measurement_id', 'text', 'object', 'axis', 'view_id'))
            or row['measurement_id'] in identities or row['view_id'] not in by_view
            or row['kind'] not in {'dimension', 'capacity', 'weight'}
            or len(extract_measurements(row['text'])) != 1 or not re_has_object_name(row['object'])):
        raise ValueError('Measurement needs one located quantity and an actual measured object')
    box, region = by_view[row['view_id']], source_box(row['region'])
    location = (row['view_id'], tuple(region))
    if location in locations:
        raise ValueError('One annotation has competing readings; resolve its original pixels')
    identities.add(row['measurement_id'])
    locations.add(location)
    points = row['endpoints']
    if row['kind'] == 'dimension':
        try:
            valid = isinstance(points, list) and len(points) == 2 and points[0] != points[1] and all(
                box[0] <= x <= box[2] and box[1] <= y <= box[3] for x, y in map(source_point, points))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(f"Dimension needs both physical endpoints inside its view {box}; received {points!r}")
    elif points is not None:
        raise ValueError(f"endpoints: capacity/weight needs null, received {points!r}")


def re_has_object_name(text: str) -> bool:
    import re
    for value in extract_measurements(text):
        text = text.replace(value['raw_text'], '')
    return bool(re.search(r'[A-Za-z]{2,}', text))


def claim_key(text: str, evidence: dict[str, str]) -> str:
    return input_revision_id({"policy": CLAIM_REVIEW_POLICY, "text": text, "evidence": evidence})


def review_planning_bindings(
    claims: list[dict[str, Any]], *, trace_dir: Path,
    shared_design: dict[str, Any],
    source_manifest: list[dict[str, Any]] = (), source_paths: list[Path] = (),
    view_paths: list[Path] = (),
    deadline_monotonic: float | None = None,
    attempt_observer: Any = None,
    prior_output_limits: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """One existing planning review request for facts and explicit design bindings, not aesthetics."""
    if not claims:
        return {}
    expected = {row["key"] for row in claims}
    pixel_claims = [row for row in claims if row.get('kind') == 'product_claim'
                   or any(not op.startswith('target_consistency:') for op in row.get('physical_operations', []))]
    needed_sources = {row.get('source_id') for row in pixel_claims}
    needed_views = {(item['source_id'], item['view']['view_id']) for row in pixel_claims for item in row.get('selected_evidence', [])}
    needed_sources.update(source_id for source_id, _view in needed_views)
    images: list[Path] = []
    attachment_numbers: dict[Path, int] = {}
    source_views, crop_views = [], []
    for source, path in zip(source_manifest, source_paths):
        if source['source_id'] not in needed_sources:
            continue
        if path not in attachment_numbers:
            images.append(path)
            attachment_numbers[path] = len(images)
        source_views.append({'attachment_number': attachment_numbers[path], 'source_id': source['source_id'],
                             'views': source['observation']['physical_views']})
    for (source, view), path in zip(((source, view) for source in source_manifest
            for view in source['observation']['physical_views']), view_paths):
        if (source['source_id'], view['view_id']) not in needed_views:
            continue
        if path not in attachment_numbers:
            images.append(path)
            attachment_numbers[path] = len(images)
        crop_views.append({'attachment_number': attachment_numbers[path], 'source_id': source['source_id'], 'view_id': view['view_id']})

    def validate(text: str) -> bool:
        rows = parse_json_object_response(text).get("reviews")
        if not isinstance(rows, list) or len(rows) != len(expected):
            raise ValueError("claim review inventory changed")
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or row.get("key") not in expected or row["key"] in seen:
                raise ValueError("unknown or repeated claim review")
            if row.get("status") not in {"supported", "contradiction", "inconclusive"} or not str(row.get("reason") or "").strip():
                raise ValueError("claim review requires a verdict and evidence explanation")
            findings = row.get('findings')
            if not isinstance(findings, list):
                raise ValueError('Review findings must be a list')
            request = next(item for item in claims if item['key'] == row['key'])
            if not findings and request.get('physical_operations'):
                raise ValueError('Design review needs findings for required product operations')
            for finding in findings:
                if (not isinstance(finding, dict) or set(finding) != {'operation', 'status', 'reason'}
                    or finding.get('status') not in {'supported', 'contradiction', 'inconclusive'}
                    or not str(finding.get('reason') or '').strip() or not isinstance(finding.get('operation'), str)):
                    raise ValueError('Malformed typed review finding')
                if finding['operation'].startswith('source_product:') and finding['operation'].split(':', 1)[1] not in {
                    item['source_id'] + '/' + item['view']['view_id'] for item in request.get('selected_evidence', [])}:
                    raise ValueError('Source product correction must cite a selected source/view')
            seen.add(row["key"])
        return True

    prompt = (
        "Verify the supplied planning bindings, not aesthetic quality. For product_claim entries, "
        "verify proposed text against its supplied typed evidence and corresponding source pixels. "
        "physical: IDs prove only the observed geometry, local parts or state, never material specifications, load or performance. "
        "measurement: IDs support truthful group headings without asserting new measurements. Other IDs are quoted source statements. "
        "Return JSON {reviews:[{key,status,reason,findings:[{operation,status,reason}]}]}; "
        "Status is supported, contradiction or inconclusive. The supplied operation ID owns its review category. "
        "For design entries, report each supplied operation using its exact ID. "
        "product_coverage checks that the role retains necessary functional facts or measured objects and endpoint associations, "
        "not the source's panel inventory. coverage_transfer checks only integrated features against displayed counterparts. "
        "Verification-only views are evidence, not required output panels. Source and target feature IDs need not match if pixels support the same fact. "
        "For an actual observation defect that misidentifies, clips or invents the SOLD PRODUCT, use source_product:<source_id/view_id>, "
        "cite that selected view's original and crop and the specific product part. Crop context added by measurement labels is not an error. "
        "Missing ordinary props, different framing, room style, open/closed presentation supported elsewhere in the child, or replaced bedding "
        "are not observation defects. Unknown geometry is inconclusive only when the proposed product depiction depends on it. "
        "Compare subject, action, property, quantity, unit, conditions, negation and scope. A modifier stays with its source subject: "
        "drawers placeable on either bed side do not imply wheels mountable on either side. IDs and matching "
        "numbers alone do not imply support. Two doors do not support two drawers. Pine wood does "
        "not imply waterproof. Preserve per-shelf versus whole-product and static-load qualifiers. "
        "A plausible but unsupported benefit is inconclusive, not supported. Do not rewrite claims "
        "or use the designer's confidence as evidence. target_consistency compares each role's target "
        "composition and selected components against shared_design, not the source's props or view inventory. "
        "reference_transfer checks that entry's reference_scopes. "
        "Selected reference purposes bound what may be inherited; a designer summary cannot broaden that scope. Detect explicit "
        "conflicting TARGET assignments of the SAME object's color/material or SAME graphic/font role. "
        "scene_objects selects target group.component definitions independently of source props. Adding, removing or replacing non-sold "
        "mattresses, textiles and decor is allowed, provided necessary product feature demonstrations remain truthful. "
        "Compare target prose against target palette, never source staging color against target color. Quote both conflicting target fields. "
        "A product-only white-background main does not use the room palette; a graphic_canvas does not require "
        "room objects. Only components selected for the target need palette definitions. "
        "Named palette and graphic values define the shared assignment. Check shared staging/photography/cohesion "
        "prose against those assignments too; use operation shared_prose:<exact.field.path> for the shared field "
        "that conflicts, citing both fields. Include component_style if it overrides role text_placement backgrounds. "
        "Use shared_prose:palette_direction.<group>.<component> for a faulty or missing target component definition, "
        "citing the requested component and conflict, not its aesthetic desirability. "
        "New camera positions, crops, layout, furnishings and graphics are the designer's decisions, not source facts. "
        "Removing a sold drawer, changing its mechanism or duplicating the sold product is a contradiction; "
        "showing a bare frame with designed bedding is not, unless it conceals the feature this role must demonstrate. "
        "Source graphic styling is not product evidence; new graphics follow shared graphic roles. "
        "text_color owns flat text ink, typography owns hierarchy, text_placement owns local backing; "
        "component_style owns strokes/icons, not a second label treatment. "
        "Do not judge beauty, enforce trends, require identical colors for different graphic roles, or add "
        "product requirements. Missing/ambiguous information is inconclusive, not contradiction.\n"
        + json.dumps({"shared_design": shared_design, "bindings": claims,
                      "source_views": source_views, "actual_crop_attachments": crop_views}, ensure_ascii=False)
    )
    trace_dir.mkdir(parents=True, exist_ok=True)
    from .palette_registry import planned_palette_diagnostics
    try:
        diagnostics = planned_palette_diagnostics(shared_design)
        surfaces = {'palette_direction.' + key for claim in claims for key in
                    (claim.get('role_design', {}).get('scene_objects') or []) if isinstance(key, str)}
        feedback = {"unresolved": diagnostics['unresolved'], "intended_surface_pairs": [row for row in diagnostics['pairs']
                    if row['second'] == 'graphic_direction.backing_color' or any(
                        row['second'] == key or row['second'].startswith(key + '.') for key in surfaces)]}
        prompt += "\nPalette calculation feedback (diagnostic, not an aesthetic veto; check actual intended pairings): " + json.dumps(feedback)
    except Exception:
        prompt += "\nPalette calculation unavailable; retain model design authority."
    (trace_dir / "planning_review_request.txt").write_text(prompt, encoding="utf-8")
    _events, record = _attempt_trace(trace_dir / "planning_review_attempts.json", observer=attempt_observer)
    response = gemini_stream_generate(
        prompt, images, client_scope="visual_planning", attempts=1,
        max_physical_requests=1,
        max_output_tokens=min(32768, max([min(24576, max(8192, 600 * len(claims))),
            *(2 * int(row.get('max_output_tokens') or 0) for row in prior_output_limits or [])])),
        prior_output_limits=prior_output_limits,
        deadline_monotonic=deadline_monotonic, response_validator=validate,
        request_id=f"claim-review:{input_revision_id(claims)}", attempt_observer=record,
    )
    (trace_dir / "planning_review_response.txt").write_text(response, encoding="utf-8")
    validate(response)
    return {row["key"]: {**row, "policy": CLAIM_REVIEW_POLICY, "response_path": str((trace_dir / "planning_review_response.txt").resolve()),
                         "response_sha256": file_sha256(trace_dir / "planning_review_response.txt")} for row in parse_json_object_response(response)["reviews"]}


def candidate_view_targets(task: dict[str, Any]) -> list[dict[str, Any]]:
    """The role's existing view dispositions are the comparison inventory."""
    positions = {view_identity(row): row['target_region'] for row in task['image_direction']['layout']}
    return [{'view_id': row['view_id'], 'source_id': row['source_id'],
             'usage': row['usage'], 'covered_by': row['covered_by'],
             'candidate_search_regions': [positions[key] for key in (row['covered_by'] or [view_identity(row)]) if key in positions]}
            for row in task['image_direction']['evidence_usage'] if row['usage'] != 'verification']


def observe_candidate(job: Path, task: dict[str, Any], candidate: dict[str, Any], *, deadline_monotonic: float | None = None) -> dict[str, Any]:
    from .paths import resolve_job_owned_path
    from .vision_gemini_client import gemini_scope_execution_revision

    product_refs = [row for row in task["generation_references"] if row["kind"] != "design_reference"]
    originals = {}
    for row in product_refs:
        if row.get('original_path'):
            path = resolve_job_owned_path(job, row['original_path'])
            if file_sha256(path) != row['original_sha256']:
                raise ValueError('Original physical evidence changed before QA')
            originals[row['source_id']] = {"source_id": row['source_id'], "path": row['original_path'],
                "sha256": row['original_sha256'], "purpose": "Original source for measured endpoints and complete visible product comparison"}
    product_refs = [*product_refs, *originals.values()]
    images = [resolve_job_owned_path(job, candidate["candidate_path"])] + [resolve_job_owned_path(job, row["path"]) for row in product_refs]
    attachments = [{"attachment_index": index, "source_id": ref.get('source_id') or f"source_{int(task.get('source_index') or 0):02d}",
                    "view_id": ref.get('view_id'), "purpose": ref.get('purpose'), "sha256": ref['sha256']} for index, ref in enumerate(product_refs, 2)]
    required_views = candidate_view_targets(task)
    for view in required_views:
        view['attachment_index'] = next(a['attachment_index'] for a in attachments
                                       if (a['source_id'], a['view_id']) == (view['source_id'], view['view_id']))
    measurement_sources = []
    for row in (task.get('measurement_authority') or {}).get('measurement_groups', []):
        location = measurement_attachment_location(row, product_refs)
        measurement_sources.append({**{key: row[key] for key in ('id', 'source_id', 'measured_part', 'axis', 'view_id')},
            'attachment_index': location['attachment'] + 1, 'coordinate_frame': 'specified_attachment',
            'source_region': location['label'], 'source_endpoints': location['endpoints']})
    edit_scope = {}
    if candidate.get('revision_mode') == 'targeted_edit':
        from .candidate_state import candidate_by_sha
        parent = candidate_by_sha(job, task, candidate['edit_parent_candidate_sha256'])
        parent_path = resolve_job_owned_path(job, parent['candidate_path'])
        if file_sha256(parent_path) != candidate['edit_parent_candidate_sha256']:
            raise ValueError('Edit parent candidate bytes changed')
        prompt_path = resolve_job_owned_path(job, candidate['prompt_path'])
        if file_sha256(prompt_path) != candidate['request_prompt_fingerprint']:
            raise ValueError('Edit request bytes changed')
        request = prompt_path.read_text(encoding='utf-8').split('# Revision request\n', 1)
        if len(request) != 2:
            raise ValueError('Targeted edit has no bound revision request')
        images.append(parent_path)
        edit_scope = {'parent_attachment_index': len(images), 'parent_sha256': candidate['edit_parent_candidate_sha256'], 'request': request[1]}
    revision = input_revision_id({"policy": CANDIDATE_OBSERVATION_POLICY, "candidate": candidate["candidate_sha256"],
                                 "observer_execution": gemini_scope_execution_revision("vision_qa"),
                                 "references": product_refs, "product": task["product_facts"], "edit_scope": edit_scope,
                                 "measurements": task.get('measurement_authority'), "required_views": required_views})
    path = job / "reports" / "candidate_observations" / f"{revision}.json"
    if path.is_file():
        cached = read_json(path)
        _validate_candidate_bindings(cached, attachments, required_views, measurement_sources, edit_scope)
        return cached
    schema = {
        "text_coverage": "complete|partial|unreadable",
        "texts": [{"text": "verbatim observed text", "kind": "marketing|measurement|product_label|prop|brand|unknown",
                   "confidence": 0.0, "region": dict(left=0.0, top=0.0, right=1.0, bottom=1.0)}],
        "measurements": [{"measurement_id": "source measurement id, or null for unlisted evidence", "object": "measured part and axis", "source_id": "source_id from attachments", "attachment_index": 2,
                          "source_text": "observed in attachment 2+",
                          "candidate_text": "observed in attachment 1", "relationship": "same|different|unknown",
                          "source_endpoints": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}], "candidate_endpoints": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}],
                          "confidence": 0.0, "source_region": dict(left=0.0, top=0.0, right=1.0, bottom=1.0), "candidate_region": dict(left=0.0, top=0.0, right=1.0, bottom=1.0)}],
        "measurement_coverage": "complete|partial|not_applicable",
        "product_coverage": "complete|partial",
        "product_comparisons": [{"view_id": "required view_id or extra:unique_id for an additional depicted detail", "source_id": "its source_id", "attachment_index": 2,
                               "status": "consistent|contradiction|unknown", "part": "specific sold part",
                               "evidence": "source/candidate geometry, count, finish and state comparison, not aesthetics",
                               "confidence": 0.0, "source_region": dict(left=0.0, top=0.0, right=1.0, bottom=1.0), "candidate_region": dict(left=0.0, top=0.0, right=1.0, bottom=1.0)}],
    }
    if edit_scope:
        schema['edit_comparison'] = {'status': 'consistent|contradiction|unknown', 'part': 'specific unexpected change',
                                     'evidence': 'Compare parent and candidate outside the requested change; no aesthetic rating',
                                     'confidence': 0.0, 'source_region': dict(left=0.0, top=0.0, right=1.0, bottom=1.0), 'candidate_region': dict(left=0.0, top=0.0, right=1.0, bottom=1.0)}
    prompt = (
        "Attachment 1 is the generated candidate; subsequent attachments are the same child's product evidence. "
        "Observe the actual pixels independently; no expected display copy is supplied. Return the completed observation object, not its schema or input context. "
        "Transcribe candidate text verbatim. Regions use named {left,top,right,bottom}; endpoints use {x,y}, normalized to the specified attachment, not another crop or output. Distinguish marketing/dimensions from "
        "product surface labels and loose props; do not guess illegible words or brand identity. "
        "Compare physical quantities, measured objects and both endpoints; equivalent US-unit conversion with display rounding is not a product change. Transcribe both numbers exactly; bind each listed measurement id once. Use null endpoints for non-diagram callouts and unknown for unreadable geometry. "
        "Return one product_comparisons row per required target view (source_id/view_id identify that target), "
        "using attachment_index and source_region to cite any supplied same-child view that proves its structure, plus extra:unique_id rows "
        "for all additional product-bearing insets/parts in the candidate, comparing against the original source attachment. "
        "Compare each view's joints, visible faces, part count, attachment position and state, not merely its function. "
        "A stopper block serving the same purpose but showing a newly invented side/joint is not the same observed detail. "
        "Do not use a correct inset to excuse a changed main view. "
        "Search regions are placement hints, not proof of presence. Integrated views still need their physical feature/state visible. "
        "Inspect the entire candidate including background and unlabeled details for extra or altered products or mechanisms. "
        "product_coverage is complete only when every depicted product region is compared; an unregistered detail is not automatically correct. "
        "A repeated close-up of the same part is allowed; an extra assembled product staged behind the demonstrated product is a count contradiction. "
        "A changed viewpoint or operating state is allowed when supported by any supplied same-child product evidence; "
        "unseen geometry is unknown, not an automatic contradiction. A contradiction needs an actually incompatible product part. "
        "Adjustment-position ghosts are not extra physical shelves. Non-sold rooms, bedding and props may be added, removed or replaced. "
        "Occlusion is not removal: judge depicted product regions and required functional demonstrations, not every part hidden by normal staging. "
        "When a necessary comparison is genuinely unavailable, report unknown/partial with its visible location, not absence or an empty region. "
        "Do not score aesthetics or improve the image. Every contradiction needs a specific part and two visible regions.\n"
        + "INPUT CONTEXT:\n" + json.dumps({"product_identity": task["product_facts"], "attachments": attachments,
                      "required_views": required_views, "measurement_sources": measurement_sources, "edit_scope": edit_scope}, ensure_ascii=False)
        + "\nOUTPUT OBJECT (these fields are top-level):\n" + json.dumps(schema, ensure_ascii=False)
    )
    def validate(text: str) -> bool:
        observed = parse_json_object_response(text)
        _validate_candidate_bindings(observed, attachments, required_views, measurement_sources, edit_scope)
        return True
    events, record = _attempt_trace(path.with_suffix(".attempts.json"))
    raw = gemini_stream_generate(prompt, images, client_scope="vision_qa", attempts=1,
        max_physical_requests=1,
                                deadline_monotonic=deadline_monotonic, response_validator=validate,
                                request_id=f"candidate-observation:{revision}", attempt_observer=record)
    result = parse_json_object_response(raw)
    _validate_candidate_bindings(result, attachments, required_views, measurement_sources, edit_scope)
    success = next((event for event in reversed(events) if event.get("status") == "success"), {})
    result["provider"] = {key: success.get(key) or "unavailable" for key in ("provider", "model", "protocol")}
    write_json(path, result)
    return result


def _validate_candidate_bindings(observed, attachments, required_views, measurement_sources, edit_scope):
    _validate_candidate_observation(observed)
    expected = {(row['source_id'], row['id']): row for row in measurement_sources}
    seen = set()
    for row in observed['measurements']:
        if not any(row['attachment_index'] == a['attachment_index'] and row['source_id'] == a['source_id'] for a in attachments):
            raise ValueError('Measurement refers to a different source attachment')
        if row.get('measurement_id') is None:
            continue
        key = (row['source_id'], row['measurement_id'])
        binding = expected.get(key)
        if binding is None or key in seen or row['attachment_index'] != binding['attachment_index']:
            raise ValueError('Measurement ID refers to a different view attachment or is repeated')
        seen.add(key)
    if seen != set(expected):
        observed['measurement_coverage'] = 'partial'
    required = {(row['source_id'], row['view_id']) for row in required_views}
    for row in observed['product_comparisons']:
        extra = row['view_id'].startswith('extra:')
        if ((not extra and (row['source_id'], row['view_id']) not in required)
                or not any(row['attachment_index'] == a['attachment_index'] for a in attachments)):
            raise ValueError('Product comparison needs a planned target and supplied same-child evidence attachment')
    if edit_scope and 'edit_comparison' not in observed:
        raise ValueError('Targeted edit comparison is missing')


def _validate_candidate_observation(value: Any) -> None:
    if not isinstance(value, dict) or value.get("text_coverage") not in {"complete", "partial", "unreadable"}:
        raise ValueError("Candidate observation has no honest text coverage")
    if value.get("measurement_coverage") not in {"complete", "partial", "not_applicable"}:
        raise ValueError("Candidate measurement coverage is invalid")
    if value.get('product_coverage') not in {'complete', 'partial'}:
        raise ValueError('Candidate must report whole-image product coverage')
    if not isinstance(value.get("texts"), list) or not isinstance(value.get("measurements"), list):
        raise ValueError("Candidate observation lists are missing")
    for row in value["texts"]:
        if not isinstance(row, dict) or row.get("kind") not in TEXT_KINDS | {"brand"} or not isinstance(row.get("text"), str):
            raise ValueError("Candidate text observation is malformed")
        _located_finding(row, ('region',), 'kind', 'unknown')
    for row in value["measurements"]:
        if not isinstance(row, dict) or row.get("relationship") not in {"same", "different", "unknown"} or not row.get("object"):
            raise ValueError("Candidate measured-object relationship is missing")
        if not isinstance(row.get("source_text"), str) or not isinstance(row.get("candidate_text"), str):
            raise ValueError("Observed source and candidate measurement text is required")
        if not _located_finding(row, ('source_region', 'candidate_region'), 'relationship', 'unknown'):
            value['measurement_coverage'] = 'partial'
        if not row.get('source_id') or type(row.get('attachment_index')) is not int or row['attachment_index'] < 2:
            raise ValueError('Measurement source attachment is missing')
        for field in ('source_endpoints', 'candidate_endpoints'):
            points = row.get(field)
            try:
                if points is not None:
                    if not isinstance(points, list) or len(points) != 2 or points[0] == points[1]:
                        raise ValueError('Invalid measurement endpoints')
                    for point in points:
                        source_point(point)
            except ValueError:
                row.update(relationship='unknown', confidence=0.0, location_error='Invalid measurement endpoints')
                row[field] = None
                value['measurement_coverage'] = 'partial'
    comparisons = value.get("product_comparisons")
    if not isinstance(comparisons, list):
        raise ValueError("Candidate per-view product comparisons are missing")
    seen = set()
    for comparison in comparisons:
        if (not isinstance(comparison, dict) or comparison.get('status') not in {'consistent', 'contradiction', 'unknown'}
                or not all(comparison.get(key) for key in ('source_id', 'view_id', 'evidence', 'part'))
                or type(comparison.get('attachment_index')) is not int or comparison['attachment_index'] < 2):
            raise ValueError('Candidate product comparison needs a bound view and located evidence')
        key = (comparison['source_id'], comparison['view_id'])
        if key in seen:
            raise ValueError('Candidate product comparison repeats a view')
        seen.add(key)
        if not _located_finding(comparison, ('source_region', 'candidate_region'), 'status', 'unknown'):
            value['product_coverage'] = 'partial'
    if 'edit_comparison' in value:
        edit = value['edit_comparison']
        if not isinstance(edit, dict) or edit.get('status') not in {'consistent', 'contradiction', 'unknown'} or not edit.get('evidence'):
            raise ValueError('Edit comparison is invalid')
        _located_finding(edit, ('source_region', 'candidate_region'), 'status', 'unknown')


def _located_finding(row: dict[str, Any], regions: tuple[str, ...], field: str, unknown: str) -> bool:
    try:
        _observation_location(row, regions)
        return True
    except ValueError as exc:
        row.update({field: unknown, 'confidence': 0.0, 'location_error': str(exc)})
        for region in regions:
            row[region] = None
        return False


def _observation_location(row: dict[str, Any], regions: tuple[str, ...]) -> None:
    confidence = row.get("confidence")
    if not isinstance(confidence, (float, int)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("Invalid observation confidence")
    for field in regions:
        source_box(row.get(field))
