from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .io import file_sha256, parse_json_object_response, read_json, write_json
from .status import input_revision_id
from .vision_gemini_client import gemini_stream_generate, VisionRequestError
from .text_evidence import extract_measurements, measurement_qualifiers
from .image_task_inputs import shared_design_values
from .image_reference_context import physical_views, selected_reference_views, source_box, source_point, measurement_attachment_location, view_identity, resolve_edit_references, reference_semantics


OBSERVATION_POLICY = "child-joint-observation-v26-located-specifications"
CLAIM_REVIEW_POLICY = "planning-binding-review-v23-evidence-operations"
CANDIDATE_OBSERVATION_POLICY = "blind-candidate-observation-v16-presentation-and-quantifiers"
TEXT_KINDS = {"product_label", "marketing", "measurement", "prop", "unknown"}
MEMBERSHIPS = {"product", "included_accessory", "unknown"}


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
            "semantic_valid_rows", "semantic_failed_rows", "semantic_errors",
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
                        and observed[row['source_id']]['status'] == 'success' and not observed[row['source_id']].get('measurement_issues')):
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
            "role_guess": "scene|func|size|reference_only|unknown",
            "has_dimension_lines": False,
            "has_callouts_or_panels": False,
            "visible_numbers_or_units": ["34.5 inches"],
            "evidence_gaps": ["specific unavailable product evidence, empty when unnecessary"],
            "text_gaps": ["specific unreadable necessary product claim or dimension, never prop text"],
            "reference_views": [{"view_id": "view_01", "purposes": ["appearance", "feature", "measurement"]}],
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
            "text_observations": [{"text": "verbatim necessary product information", "kind": "product_fact|product_label|marketing|measurement|unknown"}],
            "measurements": [{"measurement_id": "unique source-local annotation identity",
                "text": "34.5 inches", "object": "cabinet",
                "axis": "width",
                "region": {"left": 0.15, "top": 0.07, "right": 0.25, "bottom": 0.12},
                "endpoints": [{"x": 0.12, "y": 0.3}, {"x": 0.87, "y": 0.3}],
                "kind": "dimension", "evidence_type": "dimension_line", "view_id": "view_01"},
                {"measurement_id": "load_01", "text": "120 lbs", "object": "whole cabinet", "axis": "capacity",
                 "region": {"left": 0.15, "top": 0.07, "right": 0.25, "bottom": 0.12},
                 "endpoints": None, "kind": "capacity", "evidence_type": "text_spec", "view_id": "view_01"}],
            "objects": [{
                "object_id": "stable child-local identity across views",
                "kind": "sold product or specific disputed included part, never ordinary staging",
                "sale_membership": "product|included_accessory|unknown",
                "membership_evidence": [{"fact_id": "product.*", "quote": "exact source statement"}],
                "visibility": "visible|occluded|not_observed",
                "state": "only this object's physical count, open/closed state, visible extent and occlusion; no decorative colors, style or descriptions of other objects",
            }],
        }],
    }
    prompt = (
        "Observe the gallery returned for ONE child together; gallery ownership does not prove variant identity. "
        "Return exactly one JSON object with a top-level sources array. Do not wrap it in schema, result, data or observations. "
        "Keep every source_id registered, but describe only evidence needed to identify and depict the sold product. "
        "Locate a sufficient set of distinct product views: appearance for reliable product form/finish, "
        "feature for distinct functional evidence, measurement for real quantities and their objects. "
        "Select appearance inputs for child-wide design: prefer a reliable complete product photograph with little unrelated setting; "
        "a size-page photo can serve this purpose, but a line drawing cannot prove finish. Select one preferred whole-product appearance "
        "reference when available, adding another appearance view only for essential form or finish absent there. A background is not "
        "a reason to reject otherwise reliable evidence when no cleaner view exists. Feature and measurement views remain available "
        "for editing and factual review, not as additional room-style inputs to planning. "
        "Classify each gallery image's output purpose scene/func/size independently of whether its pixels are selected. "
        "Use reference_only solely for material with no product-image delivery purpose, not to hide uncertain identity or unreadable facts. "
        "Do not describe source room styling, ordinary props, their text, colors, counts, locations or relationships. "
        "Classify text by meaning: product_fact for mechanisms, parts, counts and functional claims "
        "(8 plywood slats, Embedded Design, No Box Spring Needed); marketing for generic praise "
        "(High-Quality); product_label for surface markings, not functional callouts. "
        "Quote complete facts with their subjects and qualifiers; leave illegible text unknown. "
        "physical_views catalogs necessary product evidence; reference_views recommends initial inputs, not the final layout. "
        "Do not inventory every inset or duplicate angle; retain distinct facts required for the output's functions and measurements. "
        "Enclose the complete visible sold object or selected detail without clipping parts. Describe which part belongs to which assembly "
        "and visible support/joint relationships, including distinct compartments, actual shelves and attached supports, not just a generic product name. "
        "A feature_id identifies the same visible structure AND state, not merely the same product; an edge joint is not slatted support. "
        "Source regions are named {left,top,right,bottom}; endpoints are named {x,y}. All coordinates are fractions of the ORIGINAL attachment width/height. "
        "Left/right measure horizontal distance from the left edge; top/bottom measure vertical distance from the top edge. Never return coordinate arrays. "
        "Use whole_view for a complete visible product view, detail for a partial close-up. "
        "Crop each photo independently, excluding separable title bands, neighboring insets and room decor. "
        "Overlapping graphics stay in the evidence crop; never erase or clip a product part or occluding bedding to remove them. "
        "Each physical view encloses its complete measured product and, for dimension_line evidence, both physical endpoints. Record each annotation once in measurements: "
        "the measured part/property (clearance is not overall height), axis, full quantity including bounds, ranges and qualifiers, and its original-page label region. "
        "A dimension label or capacity badge can lie OUTSIDE the product view; bind it to the measured view without moving its coordinates. "
        "Measurement kind is dimension, capacity or weight. evidence_type is dimension_line for an actual two-endpoint measurement, "
        "or text_spec for a written specification of any property, including length or recommended thickness; text_spec has null endpoints. "
        "Resolve OCR against pixels at the same annotation; inches and feet readings of one mark are alternatives, not two facts. "
        "Never promote unlocated OCR or a bare number into measurements; report unreadable annotations in evidence. "
        "physical_views and reference_views may be empty for an unselected source; keep its role and relevant text evidence. "
        "evidence_gaps records only specific unavailable product evidence, not incomplete room parsing. "
        "text_gaps requests OCR only for unreadable necessary product annotations; omit ordinary packaging and book text. "
        "visible_numbers_or_units is also a list of strings, not measurement objects. "
        "Alternative adjustment positions, arrows, ghosted parts and inset borders are diagram notation, not additional physical components. "
        "objects contains the sold product and necessary included parts or specific disputed accessories only. "
        "Do not name, classify, number or record ordinary non-sold bedding, furniture, decor or their relationships. "
        "Product state and physical_facts describe the sold object only. An occluded joint is unavailable product evidence, "
        "not a reason to identify the object covering it. Visible drawer contents do not prove they are included. "
        "Not observed never means confirmed absent. Product/accessory sales membership requires "
        "an exact citation to facts (fact_id is its product.* key, quote is text from that value); visual resemblance alone is insufficient. "
        "Use unknown only for a concrete sales-membership dispute, never as an inventory of unclassified room props. "
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
        if result[row['source_id']]['status'] == 'success' and (not result[row['source_id']].get('measurement_issues') or row['source_id'] in correction_rows):
            result[row['source_id']] = correction_rows.get(row['source_id'], {
                'source_id': row['source_id'], 'status': 'failed', 'error': 'Requested product observation revision is unresolved'})
    # Spend the existing two-request budget on unresolved rows, never successful attachments.
    for attempt in range(2):
        for row in requested:
            if attempts_used.get(row['source_id'], 0) >= 4 and result[row['source_id']]['status'] != 'success':
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
            elif event.get('status') == 'success' and event.get('response_text'):
                checked = _validate_observations(parse_json_object_response(event['response_text'])['sources'],
                                                [row['source_id'] for row in requested], facts)
                errors = {key: row.get('error') or row['measurement_issues'] for key, row in checked.items()
                          if row['status'] == 'failed' or row.get('measurement_issues')}
                event.update(semantic_valid_rows=len(checked) - len(errors), semantic_failed_rows=len(errors), semantic_errors=errors)

        _events, record = _attempt_trace(trace.with_name(trace.name + '.attempts.json'), observer=settle)
        request_scope = [row['source_id'] for row in requested]
        limits = list({(item.get('provider'), item.get('model'), item.get('max_output_tokens')): item
            for row in requested for failure in [result[row['source_id']].get('request_failure', {})]
            if failure.get('request_scope') == request_scope for item in failure.get('output_limits', [])}.values())
        request = prompt + "\nInput evidence, not response fields:\n" + json.dumps({
            "facts": facts,
            "attachments": [{k: row[k] for k in ('source_id', 'sha256', 'ocr')} for row in requested],
            "already_observed_read_only": [{"source_id": row['source_id'], "objects": row.get('objects', [])} for row in retained],
            "repair_findings": {row['source_id']: result[row['source_id']].get('error') or result[row['source_id']].get('measurement_issues') for row in requested},
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
            checked = _validate_observations(raw, source_ids, facts)
            result = {key: result[key] if value['status'] == 'failed' and result[key].get('measurement_issues') else value
                      for key, value in checked.items()}
            retained = [row for row in result.values() if row['status'] == 'success' and not row.get('measurement_issues')]
        except Exception as exc:
            failure = ({'kind': exc.failure_kind, 'request_scope': request_scope,
                        'output_limits': [*limits, *exc.metadata.get('output_limits', [])]}
                       if isinstance(exc, VisionRequestError) else {})
            for row in requested:
                if not result[row['source_id']].get('measurement_issues'):
                    result[row['source_id']] = {'source_id': row['source_id'], 'status': 'failed',
                        'error': f'{type(exc).__name__}: {exc}'[:1200], 'request_failure': failure}
        for source_id, correction_row in correction_rows.items():
            result[source_id] = {**correction_row, **result[source_id]}
        requested = [row for row in sources if row['source_id'] not in retained_ids and (
            result[row['source_id']]['status'] != 'success' or result[row['source_id']].get('measurement_issues'))]
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
        if key in result or row.get("role_guess") not in ("scene", "func", "size", "reference_only", "unknown"):
            raise ValueError("duplicate observation or invalid role")
        if any(type(row.get(field)) is not bool for field in ("has_dimension_lines", "has_callouts_or_panels")):
            raise ValueError("observed layout flags must be explicit booleans")
        if not isinstance(row.get("confidence"), (int, float)) or not 0 <= row["confidence"] <= 1:
            raise ValueError("observation confidence is outside zero to one")
        errors = [f'{field} must be a list of strings' for field in ('visible_numbers_or_units', 'evidence', 'evidence_gaps', 'text_gaps')
                  if not isinstance(row.get(field), list) or any(not isinstance(item, str) for item in row[field])]
        identity = row.get("variant_identity")
        if not isinstance(identity, dict) or identity.get("status") not in ("consistent", "contradiction", "unknown"):
            raise ValueError("source observation requires a variant identity assessment")
        if not isinstance(identity.get("observed_color"), str) or not isinstance(identity.get("reason"), str) or not identity["reason"].strip():
            raise ValueError("variant identity needs observed color and an evidence explanation")
        conflicts = identity.get("conflicts")
        if not isinstance(conflicts, list) or bool(conflicts) != (identity["status"] == "contradiction"):
            raise ValueError("variant identity verdict contradicts its conflict inventory")
        for conflict in conflicts:
            if not isinstance(conflict, dict) or not isinstance(conflict.get("fact_id"), str) or conflict["fact_id"] not in facts or not isinstance(conflict.get("observed"), str) or not conflict["observed"].strip():
                raise ValueError("variant conflict must identify a child fact and visible conflicting attribute")
        objects = row.get("objects")
        texts = row.get("text_observations")
        if not isinstance(objects, list) or not isinstance(texts, list):
            raise ValueError("observation needs object and text lists")
        for item in texts:
            if not isinstance(item, dict) or not isinstance(item.get('kind'), str) or item['kind'] not in (TEXT_KINDS - {'prop'}) | {'product_fact'} or not isinstance(item.get("text"), str):
                raise ValueError("invalid observed text category")
        allowed = {'source_id', 'role_guess', 'has_dimension_lines', 'has_callouts_or_panels',
                   'visible_numbers_or_units', 'evidence_gaps', 'text_gaps', 'reference_views', 'physical_views',
                   'confidence', 'evidence', 'variant_identity', 'text_observations', 'measurements', 'objects',
                   'status', 'policy_version', 'child_facts_revision_id', 'correction_revision', 'planning_correction', 'measurement_issues'}
        if set(row) - allowed:
            errors.append('Unknown product observation fields: ' + ', '.join(sorted(set(row) - allowed)))
        if row['role_guess'] == 'reference_only' and (row.get('text_gaps') or row.get('measurements')
                or row['has_dimension_lines'] or row['has_callouts_or_panels']
                or any(item.get('kind') in {'product_fact', 'measurement'} for item in texts or [] if isinstance(item, dict))):
            errors.append('Required product annotations cannot be classified as unused reference material')
        views = []
        try:
            views = physical_views(row.get('physical_views'))
            if not isinstance(row.get('measurements'), list) or not isinstance(row.get('measurement_issues', []), list):
                raise ValueError('Observation needs a measurement list and a local issue inventory')
            if any(not isinstance(issue, dict) or set(issue) != {'measurement', 'error'} for issue in row.get('measurement_issues', [])):
                raise ValueError('Invalid local measurement issue')
            measurements, measurement_issues = _validate_source_measurements(
                [*row.get('measurements', []), *(issue['measurement'] for issue in row.get('measurement_issues', []))], views)
            selected_reference_views(row)
        except ValueError as exc:
            errors.append(str(exc))
        if errors:
            raise ValueError(key + ': ' + '; '.join(errors))
        if row['has_dimension_lines'] and not row['text_gaps'] and not measurement_issues and not any(item['kind'] == 'dimension' for item in measurements):
            raise ValueError('Visible dimension lines need located measurements, not an empty inventory')
        transcribed = {m['canonical_pair'] for item in texts if item['kind'] == 'measurement' for m in extract_measurements(item['text'])}
        located = {m['canonical_pair'] for item in [*measurements, *(issue['measurement'] for issue in measurement_issues)]
                   if isinstance(item, dict) for m in extract_measurements(item.get('text', ''))}
        if not transcribed <= located:
            raise ValueError('Locate every transcribed measurement; do not omit badges or invent a second reading')
        seen_objects: set[str] = set()
        for obj in objects:
            if not isinstance(obj, dict) or set(obj) != {'object_id', 'kind', 'sale_membership', 'membership_evidence', 'visibility', 'state'} or not obj.get("object_id") or not obj.get("kind"):
                raise ValueError("observed object has no identity")
            if any(not isinstance(obj.get(field), str) for field in ("object_id", "kind", "state")) or obj["object_id"] in seen_objects:
                raise ValueError("observed object identity is duplicate or malformed")
            seen_objects.add(obj["object_id"])
            if not isinstance(obj.get('sale_membership'), str) or obj['sale_membership'] not in MEMBERSHIPS or obj.get("visibility") not in ("visible", "occluded", "not_observed"):
                raise ValueError("invalid object membership or visibility")
            refs = obj.get("membership_evidence")
            if not isinstance(refs, list):
                raise ValueError("membership evidence must be a list")
            for ref in refs:
                if (not isinstance(ref, dict) or not isinstance(ref.get('fact_id'), str) or ref['fact_id'] not in facts
                        or not isinstance(ref.get('quote'), str) or not ref['quote'].strip() or ref['quote'] not in facts[ref['fact_id']]):
                    raise ValueError(f"objects[{obj['object_id']}].membership_evidence: invalid fact_id/quote {ref!r}; use an exact facts key and its text")
            if obj["sale_membership"] in {"product", "included_accessory"} and not refs:
                raise ValueError("sales membership requires product evidence; otherwise use unknown")
        if any(item['object_id'] not in seen_objects for view in views for item in view['evidence']):
            raise ValueError("Physical view evidence refers to an unobserved object")
        result[key] = {**row, 'measurements': measurements, 'measurement_issues': measurement_issues,
                       "status": "success", "policy_version": OBSERVATION_POLICY,
                       "child_facts_revision_id": input_revision_id(facts)}
    if set(result) != set(source_ids):
        raise ValueError("joint observation omitted sources")
    return result


def _validate_source_measurements(rows: Any, views: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    if not isinstance(rows, list):
        raise ValueError('Observation needs a located measurement inventory, empty when not applicable')
    by_view = {view['view_id']: source_box(view['region']) for view in views}
    identities, locations = set(), set()
    valid, issues = [], []
    ids = [row['measurement_id'] for row in rows if isinstance(row, dict) and isinstance(row.get('measurement_id'), str) and row['measurement_id']]
    if len(ids) != len(set(ids)):
        raise ValueError('One annotation has competing readings; resolve its original pixels')
    for index, row in enumerate(rows):
        try:
            _validate_measurement(row, by_view, identities, locations)
            valid.append(row)
        except ValueError as exc:
            if 'competing readings' in str(exc):
                raise
            identity = row.get('measurement_id', index) if isinstance(row, dict) else index
            issues.append({'measurement': row, 'error': f'measurements[{identity}]: {exc}'})
    return valid, issues


def _validate_measurement(row: Any, by_view: dict, identities: set, locations: set) -> None:
    quantities = extract_measurements(row.get('text')) if isinstance(row, dict) else []
    quantity_count = len(quantities) == 1 or (len(quantities) == 2 and 'range' in measurement_qualifiers(row['text'])
                                           and len({(m['kind'], m['raw_text']) for m in quantities}) == 1)
    if (not isinstance(row, dict) or set(row) != {'measurement_id', 'text', 'object', 'axis', 'region', 'endpoints', 'kind', 'evidence_type', 'view_id'}
            or not all(isinstance(row[k], str) and row[k].strip() for k in ('measurement_id', 'text', 'object', 'axis', 'view_id'))
            or row['measurement_id'] in identities or row['view_id'] not in by_view
            or row['kind'] not in ('dimension', 'capacity', 'weight')
            or row['evidence_type'] not in ('dimension_line', 'text_spec')
            or (row['evidence_type'] == 'dimension_line' and row['kind'] != 'dimension')
            or not quantity_count or not re_has_object_name(row['object'])):
        raise ValueError('Measurement needs one located quantity or range and an actual measured object')
    box, region = by_view[row['view_id']], source_box(row['region'])
    location = (row['view_id'], tuple(region))
    if location in locations:
        raise ValueError('One annotation has competing readings; resolve its original pixels')
    locations.add(location)
    points = row['endpoints']
    if row['evidence_type'] == 'dimension_line':
        try:
            valid = isinstance(points, list) and len(points) == 2 and points[0] != points[1] and all(
                box[0] <= x <= box[2] and box[1] <= y <= box[3] for x, y in map(source_point, points))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(f"Dimension needs both physical endpoints inside its view {box}; received {points!r}")
    elif points is not None:
        raise ValueError(f"endpoints: text specifications need null, received {points!r}")
    identities.add(row['measurement_id'])


def re_has_object_name(text: str) -> bool:
    import re
    for value in extract_measurements(text):
        text = text.replace(value['raw_text'], '')
    return bool(re.search(r'[A-Za-z]{2,}', text))


def claim_key(text: str, evidence: dict[str, str]) -> str:
    return input_revision_id({"policy": CLAIM_REVIEW_POLICY, "text": text, "evidence": evidence})


def _planning_review_rows(rows: Any, requests: list[dict[str, Any]]) -> tuple[dict[str, dict], dict[str, str]]:
    if not isinstance(rows, list):
        raise ValueError('Planning review needs a top-level reviews list')
    expected = {row['key']: row for row in requests}
    result, errors, seen = {}, {}, set()
    for index, row in enumerate(rows):
        key = row.get('key') if isinstance(row, dict) else None
        if not isinstance(key, str) or key not in expected:
            errors[f'row:{index}'] = 'Unbound review identity'
            continue
        if key in seen:
            result.pop(key, None)
            errors[key] = 'Repeated review identity'
            continue
        seen.add(key)
        request = expected[key]
        try:
            if row.get('status') not in ('supported', 'contradiction', 'inconclusive') or not isinstance(row.get('reason'), str) or not row['reason'].strip():
                raise ValueError('Review needs a verdict and explanation')
            findings = row.get('findings')
            if not isinstance(findings, list) or (not findings and request.get('physical_operations')):
                raise ValueError('Review needs typed findings for required operations')
            operations, checked_findings, broken_operations = set(), {}, set()
            for finding in findings:
                if (not isinstance(finding, dict) or not {'operation', 'status', 'reason'} <= set(finding)
                        or set(finding) - {'operation', 'status', 'reason', 'resolution'}
                        or not isinstance(finding.get('operation'), str)
                        or finding.get('status') not in ('supported', 'contradiction', 'inconclusive')
                        or not isinstance(finding.get('reason'), str) or not finding['reason'].strip()
                        ):
                    errors[key] = 'Malformed typed review finding'
                    continue
                operation = finding['operation']
                if operation in operations:
                    checked_findings.pop(operation, None)
                    broken_operations.add(operation)
                    errors[key] = 'Repeated typed review finding'
                    continue
                operations.add(operation)
                if operation.startswith('source_product:') and operation.split(':', 1)[1] not in {
                        item['source_id'] + '/' + item['view']['view_id'] for item in request.get('selected_evidence', [])}:
                    errors[key] = 'Source correction must cite a selected source/view'
                    continue
                if operation.startswith('shared_design:') and operation.split(':', 1)[1] not in shared_design_values(request.get('shared_design', {})):
                    errors[key] = 'Shared correction must name an existing leaf path, not a container'
                    continue
                if request['kind'] == 'design_binding' and not operation.startswith(('source_product:', 'shared_design:')) and operation not in request['physical_operations']:
                    errors[key] = 'Unknown planning operation'
                    continue
                if operation not in broken_operations:
                    checked_findings[operation] = finding
            if request['kind'] == 'design_binding':
                missing = set(request.get('physical_operations', [])) - checked_findings.keys()
                if missing and not any(item['status'] == 'contradiction' for item in checked_findings.values()):
                    errors[key] = 'Review omitted required operations: ' + ', '.join(sorted(missing))
                statuses = {item['status'] for item in checked_findings.values()}
                status = 'contradiction' if 'contradiction' in statuses else 'inconclusive' if missing or 'inconclusive' in statuses or key in errors else 'supported'
                result[key] = {**row, 'status': status, 'findings': list(checked_findings.values())}
            else:
                if key in errors:
                    raise ValueError(errors[key])
                result[key] = row
        except ValueError as exc:
            errors[key] = str(exc)
    for key in expected.keys() - result.keys() - errors.keys():
        errors[key] = 'Review omitted this binding'
    return result, errors


def review_planning_bindings(
    claims: list[dict[str, Any]], *, trace_dir: Path,
    source_manifest: list[dict[str, Any]] = (), source_paths: list[Path] = (),
    job: Path, child: str, design_references: list[dict[str, Any]] = (),
    deadline_monotonic: float | None = None,
    attempt_observer: Any = None,
    prior_output_limits: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """One existing planning review request for facts and explicit design bindings, not aesthetics."""
    if not claims:
        return {}
    needed_sources = {key for row in claims for key in [row.get('source_id'), *row.get('evidence_sources', [])]}
    needed_views = {(item['source_id'], item['view']['view_id']) for row in claims for item in row.get('selected_evidence', [])}
    needed_views.update(tuple(key.split(':')[1:3]) for row in claims for key in row.get('evidence', {}) if key.startswith('physical:'))
    needed_sources.update(source_id for source_id, _view in needed_views)
    images: list[Path] = []
    attachment_numbers: dict[str, int] = {}
    from .paths import resolve_job_owned_path
    source_views, execution_inputs = [], []
    for request in claims:
        if request['kind'] != 'design_binding':
            continue
        direction = request['role_design']
        refs = resolve_edit_references({'role': direction['role'], 'image_direction': direction},
                                      list(source_manifest), job=job, child=child, design_references=design_references)
        inputs = []
        for index, ref in enumerate(refs, 1):
            path = resolve_job_owned_path(job, ref['path'])
            if ref['sha256'] not in attachment_numbers:
                images.append(path)
                attachment_numbers[ref['sha256']] = len(images)
            inputs.append({**reference_semantics(ref), 'generation_attachment': index,
                           'review_attachment': attachment_numbers[ref['sha256']]})
        execution_inputs.append({'key': request['key'], 'role': direction['role'], 'attachments': inputs})
    for source, path in zip(source_manifest, source_paths):
        if source['source_id'] not in needed_sources:
            continue
        if source['source_sha256'] not in attachment_numbers:
            images.append(path)
            attachment_numbers[source['source_sha256']] = len(images)
        source_views.append({'attachment_number': attachment_numbers[source['source_sha256']], 'source_id': source['source_id'],
                             'views': [{key: view[key] for key in ('view_id', 'region', 'extent')} for view in source['observation']['physical_views']
                                       if (source['source_id'], view['view_id']) in needed_views]})
    # Serialize shared facts and design once; binding keys still cover each role's consumed values.
    fact_catalog, shared_design, evidence_catalog, bindings = {}, {}, {}, []
    for request in claims:
        binding = {key: value for key, value in request.items() if key != 'shared_design'}
        if request['kind'] == 'design_binding':
            binding['selected_evidence_ids'] = []
            for item in binding.pop('selected_evidence'):
                key = item['source_id'] + '/' + item['view']['view_id']
                evidence_catalog[key] = item
                binding['selected_evidence_ids'].append(key)
            required = request['required_facts']
            fact_catalog.update({row['evidence_id']: row for row in required['product_claims']})
            binding['required_facts'] = {**{key: value for key, value in required.items() if key != 'product_claims'},
                                        'product_claim_ids': [row['evidence_id'] for row in required['product_claims']]}
            binding['shared_design_paths'] = sorted(shared_design_values(request['shared_design']))
            for key, value in request['shared_design'].items():
                if key == 'palette_direction':
                    for group, parts in value.items():
                        shared_design.setdefault(key, {}).setdefault(group, {}).update(parts)
                else:
                    shared_design[key] = value
        bindings.append(binding)
    def validate(text: str) -> bool:
        _planning_review_rows(parse_json_object_response(text).get('reviews'), claims)
        return True

    prompt = (
        "Verify the supplied planning bindings, not aesthetic quality. For product_claim entries, "
        "verify proposed text against its supplied typed evidence and corresponding source pixels. "
        "physical: IDs prove only the observed geometry, local parts or state, never material specifications, load or performance. "
        "measurement: IDs support truthful group headings without asserting new measurements. Other IDs are quoted source statements. "
        "Return JSON {reviews:[{key,status,reason,resolution,findings:[{operation,status,reason,resolution}]}]}; "
        "Status is supported, contradiction or inconclusive. The supplied operation ID owns its review category. "
        "For inconclusive results, resolution is retry_review for incomplete evaluation, correct_evidence for a cited source_product defect, "
        "or revise_plan for an unsupported proposed depiction or claim requiring a local change. Other results may omit resolution. "
        "For design entries, report each supplied operation using its exact ID. "
        "whole_product_transfer checks whether detail edits plus verification views support the proposed whole product. "
        "Detail-only output depicts selected parts, not a new whole hero; sold quantity does not require full units in a detail image. "
        "Original source_views verify provenance only: a feature visible only on an original page does not prove it is in the generation attachments. "
        "Check explicit contradictory instructions, not aesthetic quality or pixel-level color equality; uncertainty about taste is not inconclusive. "
        "Each binding's selected_evidence_ids resolves in selected_evidence; product_claim_ids resolves in child_product_facts. Its shared_design_paths names the only applicable leaf paths "
        "in the shared_design catalog; ignore all other paths, including those supplied for other bindings. "
        "Product finish and specifications are facts; palette components are non-sold target staging only. "
        "Measurements own numeric labels, display_copy owns authored text, palette owns component appearance, typography owns font treatment, "
        "and graphic_direction owns graphic colors. Report shared contradictions as shared_design:<exact leaf path>, "
        "for example shared_design:palette_direction.bedding.duvet or shared_design:graphic_direction.text_color; never name a whole container. "
        "Otherwise use the relevant supplied operation, without redesigning the palette. "
        "product_coverage checks that the role retains necessary functional facts or measured objects and endpoint associations, "
        "not the source's panel inventory. coverage_transfer checks only integrated features against displayed counterparts. "
        "sold_membership resolves only the selected, specifically disputed sold part or included accessory against product records. "
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
        "or use the designer's confidence as evidence. Adding, removing or replacing non-sold "
        "mattresses, textiles and decor is allowed, provided necessary product feature demonstrations remain truthful. "
        "New camera positions, crops, layout, furnishings and graphics are the designer's decisions, not source facts. "
        "Removing a sold drawer, changing its mechanism or duplicating the sold product is a contradiction; "
        "showing a bare frame with designed bedding is not, unless it conceals the feature this role must demonstrate. "
        "Do not judge beauty, enforce trends, require identical colors for different graphic roles, or add "
        "product requirements. Missing/ambiguous information is inconclusive, not contradiction.\n"
        + json.dumps({"bindings": bindings, "child_product_facts": list(fact_catalog.values()), 'shared_design': shared_design,
                      "selected_evidence": evidence_catalog, "source_views": source_views, "execution_inputs": execution_inputs}, ensure_ascii=False, separators=(',', ':'))
    )
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "planning_review_request.txt").write_text(prompt, encoding="utf-8")
    def observe(event: dict[str, Any]) -> None:
        if event.get('status') == 'success' and event.get('response_text'):
            valid, errors = _planning_review_rows(parse_json_object_response(event['response_text']).get('reviews'), claims)
            complete = len(valid.keys() - errors.keys())
            event.update(semantic_valid_rows=complete, semantic_failed_rows=len(claims)-complete, semantic_errors=errors)
        if attempt_observer is not None:
            attempt_observer(event)
    _events, record = _attempt_trace(trace_dir / "planning_review_attempts.json", observer=observe)
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
    checked, _errors = _planning_review_rows(parse_json_object_response(response).get('reviews'), claims)
    provenance = {'policy': CLAIM_REVIEW_POLICY, 'response_path': str((trace_dir / 'planning_review_response.txt').resolve()),
                  'response_sha256': file_sha256(trace_dir / 'planning_review_response.txt')}
    return {row['key']: {**row, **provenance, 'findings': [{**finding, **provenance} for finding in row['findings']]}
            for row in checked.values()}


def candidate_view_targets(task: dict[str, Any]) -> list[dict[str, Any]]:
    """The role's existing view dispositions are the comparison inventory."""
    return [{'view_id': row['view_id'], 'source_id': row['source_id'],
             'usage': row['usage'], 'covered_by': row['covered_by']}
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
        measurement_sources.append({**{key: row[key] for key in ('id', 'source_id', 'measured_part', 'axis', 'view_id', 'evidence_type')},
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
                                 "measurements": task.get('measurement_authority'), "required_views": required_views,
                                 "presentation": task['image_direction']['presentation']})
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
        "Compare full quantities including bounds, ranges and qualifiers, measured objects and endpoints; equivalent US-unit conversion with display rounding is not a product change. Transcribe both expressions exactly; bind each measurement id once. Use null endpoints for non-diagram callouts and unknown for unreadable geometry. "
        "Return one product_comparisons row per required target view (source_id/view_id identify that target), "
        "using attachment_index and source_region to cite any supplied same-child view that proves its structure, plus extra:unique_id rows "
        "for all additional product-bearing insets/parts in the candidate, comparing against the original source attachment. "
        "Compare each view's joints, visible faces, part count, attachment position and state, not merely its function. "
        "A stopper block serving the same purpose but showing a newly invented side/joint is not the same observed detail. "
        "Do not use a correct inset to excuse a changed main view. "
        "Locate required features in the actual candidate, without a prescribed target layout. Integrated views still need their physical feature/state visible. "
        "Inspect the entire candidate including background and unlabeled details for extra or altered products or mechanisms. "
        "product_coverage is complete only when every depicted product region is compared; an unregistered detail is not automatically correct. "
        "Use presentation.scope: detail_only authorizes selected parts, not an invented assembled product. "
        "Repeated close-ups and a representative unit in a dimension diagram are not extra sold units. "
        "A changed viewpoint or operating state is allowed when supported by any supplied same-child product evidence; "
        "unseen geometry is unknown, not an automatic contradiction. A contradiction needs an actually incompatible product part. "
        "Adjustment-position ghosts are not extra physical shelves. Non-sold rooms, bedding and props may be added, removed or replaced. "
        "Occlusion is not removal: judge depicted product regions and required functional demonstrations, not every part hidden by normal staging. "
        "When a necessary comparison is genuinely unavailable, report unknown/partial with its visible location, not absence or an empty region. "
        "Do not score aesthetics or improve the image. Every contradiction needs a specific part and two visible regions.\n"
        + "INPUT CONTEXT:\n" + json.dumps({"product_identity": task["product_facts"], "presentation": task['image_direction']['presentation'], "attachments": attachments,
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
