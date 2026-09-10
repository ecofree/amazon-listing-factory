from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .io import file_sha256, parse_json_object_response, read_json, write_json
from .status import input_revision_id
from .vision_gemini_client import gemini_stream_generate
from .text_evidence import extract_measurements
from .image_reference_context import physical_views


OBSERVATION_POLICY = "child-joint-observation-v6-independent-views"
CLAIM_REVIEW_POLICY = "independent-claim-entailment-v1"
CANDIDATE_OBSERVATION_POLICY = "blind-candidate-observation-v4-view-boundaries"
TEXT_KINDS = {"product_label", "marketing", "measurement", "prop", "unknown"}
MEMBERSHIPS = {"product", "included_accessory", "staging", "unknown"}


def _attempt_trace(path: Path) -> tuple[list[dict[str, Any]], Any]:
    events: list[dict[str, Any]] = []
    trace_id = uuid.uuid4().hex

    def record(event: dict[str, Any]) -> None:
        summary = {key: event.get(key) for key in (
            "request_id", "provider", "model", "protocol", "attempt", "status", "elapsed_ms",
            "finish_reasons",
        )}
        summary["error"] = str(event.get("error") or "")[:1200]
        summary["validation_errors"] = [str(row["validation_error"])[:1200]
            for row in event.get("response_candidates") or [] if row.get("validation_error")]
        response = str(event.get("response_text") or "")
        summary["response_char_count"] = len(response)
        if response:
            response_path = path.with_name(f"{path.stem}.{trace_id}.{len(events) + 1}.response.txt")
            response_path.parent.mkdir(parents=True, exist_ok=True)
            response_path.write_text(response, encoding="utf-8")
            summary["response_path"] = response_path.name
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
    *, deadline_monotonic: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Replace individual visual recovery with one child-scoped observation."""
    facts = source_fact_records(child)
    source_ids = [str(row["source_id"]) for row in sources]
    inputs = [{key: row[key] for key in ("source_id", "sha256", "ocr")} for row in sources]
    revision = input_revision_id({"policy": OBSERVATION_POLICY, "child": child.get("asin"), "facts": facts, "inputs": inputs})
    cache = job / "reports" / "source_observations" / f"{revision}.json"
    if cache.is_file():
        value = read_json(cache)
        if value.get("input_revision_id") == revision:
            return _validate_observations(value["sources"], source_ids, facts)
    schema = {
        "sources": [{
            "source_id": "attachment source_id",
            "role_guess": "scene|func|size|unknown",
            "has_dimension_lines": False,
            "has_callouts_or_panels": False,
            "visible_numbers_or_units": [],
            "layout_summary": "classification evidence only, not a design prescription",
            "physical_views": [{"view_id": "view_01", "region": [0.0, 0.0, 1.0, 1.0]}],
            "confidence": 0.0,
            "evidence": [],
            "variant_identity": {
                "status": "consistent|contradiction|unknown",
                "observed_color": "visible sold-product finish, not bedding or lighting; empty if unclear",
                "reason": "pixel evidence compared to this child's recorded variant, not gallery ownership",
                "conflicts": [{"fact_id": "product.*", "observed": "visible conflicting attribute"}],
            },
            "text_observations": [{"text": "verbatim", "kind": "product_label|marketing|measurement|prop|unknown"}],
            "objects": [{
                "object_id": "stable child-local identity across views",
                "kind": "bed frame, drawer, bedding, bottle, etc.",
                "sale_membership": "product|included_accessory|staging|unknown",
                "membership_evidence": [{"fact_id": "product.*", "quote": "exact source statement"}],
                "visibility": "visible|occluded|not_observed",
                "state": "physical count actually visible, open/closed state, crop boundary and occlusion; distinguish diagram ghosts from real parts; unknown where unclear",
                "relations": [{"predicate": "part_of|contained_in|occludes", "target_id": "object_id"}],
            }],
        }],
    }
    prompt = (
        "Observe the gallery returned for ONE child together; gallery ownership does not prove variant identity. Return JSON only matching the schema. "
        "Keep each source_id aligned with its attachment. Report pixels, not a proposed design. "
        "Separate authored marketing/dimensions, product surface labels and loose prop text. "
        "Ordinary books do not make a scene a function infographic. Quote complete visible claims, "
        "including counts, measured objects and qualifiers; leave illegible text unknown. "
        "Describe product-relevant parts and physical_views: one tight rectangle per distinct product view or detail inset, "
        "not per component within a view. Include its entire visible product, attached parts and occluding bedding/accessories; "
        "never crop through a visible part to exclude text. Exclude surrounding title bands, cards and room decor where separable. "
        "Bounds are normalized left,top,right,bottom on the original attachment, not proposed canvas positions. "
        "Keep detail crops partial. For size include the complete measured view and both physical endpoints; "
        "measurement labels remain in text_observations even outside the crop. Give every visible product view a local view_id; "
        "physical_views=[] only if no product view can be identified. "
        "Alternative adjustment positions, arrows, ghosted parts and inset borders are diagram notation, not additional physical components. "
        "Record staging only where it affects editing or occlusion, not its decorative style. "
        "An object inside a drawer is contained_in, not automatically part_of. "
        "Not observed never means confirmed absent. Product/accessory sales membership requires "
        "an exact citation to supplied product records; visual resemblance alone is insufficient. "
        "Uncertain ownership stays unknown and should retain its observed coverage. "
        "Compare each visible sold product's finish, variant and structure to the child records and other views. "
        "Record a clear mismatch as variant_identity contradiction with the conflicting fact_id and observed attribute, "
        "even if that attachment came from this child's gallery. Never relabel its visible finish to match the listing. "
        "Cropped, occluded, uncolored diagrams or ambiguous lighting are unknown, not contradictions. "
        "Do not infer material specifications, performance or dimensions from appearance.\n"
        + json.dumps({"schema": schema, "facts": facts, "attachments": inputs}, ensure_ascii=False)
    )

    def validate(text: str) -> bool:
        value = parse_json_object_response(text)
        if not isinstance(value.get("sources"), list):
            raise ValueError("joint observation requires one top-level sources array containing every attachment")
        _validate_observations(value["sources"], source_ids, facts)
        return True

    _events, record = _attempt_trace(cache.with_suffix(".attempts.json"))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.with_suffix(".request.txt").write_text(prompt, encoding="utf-8")
    response = gemini_stream_generate(
        prompt, [Path(row["path"]) for row in sources], client_scope="visual_planning",
        attempts=1, timeout_seconds=60, total_timeout_seconds=100,
        max_physical_requests=2, deadline_monotonic=deadline_monotonic,
        response_validator=validate, request_id=f"source-observation:{revision}", attempt_observer=record,
    )
    raw = parse_json_object_response(response)["sources"]
    result = _validate_observations(raw, source_ids, facts)
    write_json(cache, {"input_revision_id": revision, "policy": OBSERVATION_POLICY, "sources": raw})
    return result


def _validate_observations(
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
        if any(not isinstance(row.get(field), list) or any(not isinstance(item, str) for item in row[field]) for field in ("visible_numbers_or_units", "evidence")):
            raise ValueError("observed measurements and evidence must be text lists")
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
        views = physical_views(row.get("physical_views"))
        if not views and row["role_guess"] != "unknown":
            raise ValueError("Recognized source needs observed physical views")
        if not isinstance(objects, list) or not isinstance(texts, list):
            raise ValueError("observation needs object and text lists")
        for item in texts:
            if not isinstance(item, dict) or item.get("kind") not in TEXT_KINDS or not isinstance(item.get("text"), str):
                raise ValueError("invalid observed text category")
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
        result[key] = {**row, "status": "success", "policy_version": OBSERVATION_POLICY,
                       "child_facts_revision_id": input_revision_id(facts)}
    if set(result) != set(source_ids):
        raise ValueError("joint observation omitted sources")
    object_ids = {obj["object_id"] for row in result.values() for obj in row["objects"]}
    memberships: dict[str, set[str]] = {}
    for row in result.values():
        for obj in row['objects']:
            memberships.setdefault(obj['object_id'], set()).add(obj['sale_membership'])
    conflicts = {key for key, values in memberships.items()
                 if 'staging' in values and values & {'product', 'included_accessory'}}
    for row in result.values():
        row['object_identity_conflicts'] = sorted({obj['object_id'] for obj in row['objects']} & conflicts)
        for obj in row["objects"]:
            if any(rel["target_id"] not in object_ids for rel in obj["relations"]):
                raise ValueError("object relation refers to an unobserved identity")
    return result


def claim_key(text: str, evidence: dict[str, str]) -> str:
    return input_revision_id({"policy": CLAIM_REVIEW_POLICY, "text": text, "evidence": evidence})


def review_claims(
    claims: list[dict[str, Any]], *, trace_dir: Path,
    deadline_monotonic: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Independent text-only entailment check; never repair or rewrite a claim."""
    if not claims:
        return {}
    expected = {row["key"] for row in claims}

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
            seen.add(row["key"])
        return True

    prompt = (
        "Independently verify each proposed product claim ONLY against its supplied source statements. "
        "Return JSON {reviews:[{key,status,reason}]}; status is supported, contradiction or inconclusive. "
        "Compare object, property, quantity, unit, conditions, negation and scope. IDs and matching "
        "numbers alone do not imply support. Two doors do not support two drawers. Pine wood does "
        "not imply waterproof. Preserve per-shelf versus whole-product and static-load qualifiers. "
        "A plausible but unsupported benefit is inconclusive, not supported. Do not rewrite claims "
        "or use the designer's confidence as evidence. Give a short source-specific reason.\n"
        + json.dumps(claims, ensure_ascii=False)
    )
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "claim_review_request.txt").write_text(prompt, encoding="utf-8")
    _events, record = _attempt_trace(trace_dir / "claim_review_attempts.json")
    response = gemini_stream_generate(
        prompt, [], client_scope="visual_planning", attempts=1,
        timeout_seconds=35, total_timeout_seconds=35, max_physical_requests=1,
        deadline_monotonic=deadline_monotonic, response_validator=validate,
        request_id=f"claim-review:{input_revision_id(claims)}", attempt_observer=record,
    )
    (trace_dir / "claim_review_response.txt").write_text(response, encoding="utf-8")
    validate(response)
    return {row["key"]: {**row, "policy": CLAIM_REVIEW_POLICY, "response_path": str((trace_dir / "claim_review_response.txt").resolve()),
                         "response_sha256": file_sha256(trace_dir / "claim_review_response.txt")} for row in parse_json_object_response(response)["reviews"]}


def observe_candidate(job: Path, task: dict[str, Any], candidate: dict[str, Any], *, deadline_monotonic: float | None = None) -> dict[str, Any]:
    from .paths import resolve_job_owned_path
    from .vision_gemini_client import gemini_scope_execution_revision

    product_refs = [row for row in task["generation_references"] if row["kind"] != "design_reference"]
    images = [resolve_job_owned_path(job, candidate["candidate_path"])] + [resolve_job_owned_path(job, row["path"]) for row in product_refs]
    attachments = [{"attachment_index": index, "source_id": ref.get('source_id') or f"source_{int(task.get('source_index') or 0):02d}",
                    "purpose": ref.get('purpose'), "sha256": ref['sha256']} for index, ref in enumerate(product_refs, 2)]
    measurement_sources = [{key: row.get(key) for key in ('id', 'source_id', 'source_text', 'measured_part', 'axis')}
                           for row in (task.get('measurement_authority') or {}).get('measurement_groups', [])]
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
                                 "measurements": task.get('measurement_authority')})
    path = job / "reports" / "candidate_observations" / f"{revision}.json"
    if path.is_file():
        cached = read_json(path)
        _validate_candidate_observation(cached)
        return cached
    schema = {
        "text_coverage": "complete|partial|unreadable",
        "texts": [{"text": "verbatim observed text", "kind": "marketing|measurement|product_label|prop|brand|unknown",
                   "confidence": 0.0, "region": [0.0, 0.0, 1.0, 1.0]}],
        "measurements": [{"measurement_id": "source measurement id, or null for unlisted evidence", "object": "measured part and axis", "source_id": "source_id from attachments", "attachment_index": 2,
                          "source_text": "observed in attachment 2+",
                          "candidate_text": "observed in attachment 1", "relationship": "same|different|unknown",
                          "source_endpoints": [[0.0, 0.0], [1.0, 1.0]], "candidate_endpoints": [[0.0, 0.0], [1.0, 1.0]],
                          "confidence": 0.0, "source_region": [0.0, 0.0, 1.0, 1.0], "candidate_region": [0.0, 0.0, 1.0, 1.0]}],
        "measurement_coverage": "complete|partial|not_applicable",
        "product_comparison": {"status": "consistent|contradiction|unknown", "part": "specific sold part",
                               "evidence": "source/candidate geometry, count, finish and state comparison, not aesthetics",
                               "confidence": 0.0, "source_region": [0.0, 0.0, 1.0, 1.0], "candidate_region": [0.0, 0.0, 1.0, 1.0]},
    }
    if edit_scope:
        schema['edit_comparison'] = {'status': 'consistent|contradiction|unknown', 'part': 'specific unexpected change',
                                     'evidence': 'Compare parent and candidate outside the requested change; no aesthetic rating',
                                     'confidence': 0.0, 'source_region': [0.0, 0.0, 1.0, 1.0], 'candidate_region': [0.0, 0.0, 1.0, 1.0]}
    prompt = (
        "Attachment 1 is the generated candidate; subsequent attachments are the same child's product evidence. "
        "Observe the actual pixels independently; no expected display copy is supplied. Return the completed observation object, not its schema or input context. "
        "Transcribe candidate text verbatim. Regions are normalized [left, top, right, bottom]; endpoints are [x, y]. Distinguish marketing/dimensions from "
        "product surface labels and loose props; do not guess illegible words or brand identity. "
        "Compare physical quantities, measured objects and both endpoints; equivalent US-unit conversion with display rounding is not a product change. Transcribe both numbers exactly; bind each listed measurement id once. Use null endpoints for non-diagram callouts and unknown for unreadable geometry. "
        "Compare sold-product geometry, count, finish and demonstrated state in each corresponding source view. "
        "Expanding a partial product view into unseen structure is a product contradiction, even if the total product count is plausible. "
        "Adjustment-position ghosts are not extra physical shelves. Moving/resizing intact evidence views on the canvas and restyling graphics or room/bedding/props are not product defects. "
        "Occlusion or unseen parts mean unknown, not absence. Report partial coverage honestly. "
        "Do not score aesthetics or improve the image. Every contradiction needs a specific part and two visible regions.\n"
        + "INPUT CONTEXT:\n" + json.dumps({"product_identity": task["product_facts"], "attachments": attachments,
                      "measurement_sources": measurement_sources, "edit_scope": edit_scope}, ensure_ascii=False)
        + "\nOUTPUT OBJECT (these fields are top-level):\n" + json.dumps(schema, ensure_ascii=False)
    )
    def validate(text: str) -> bool:
        observed = parse_json_object_response(text)
        _validate_candidate_observation(observed)
        for row in observed['measurements']:
            if not any(row['attachment_index'] == a['attachment_index'] and row['source_id'] == a['source_id'] for a in attachments):
                raise ValueError('Measurement refers to a different source attachment')
        if edit_scope and 'edit_comparison' not in observed:
            raise ValueError('Targeted edit comparison is missing')
        return True
    events, record = _attempt_trace(path.with_suffix(".attempts.json"))
    raw = gemini_stream_generate(prompt, images, client_scope="vision_qa", attempts=1,
                                timeout_seconds=50, total_timeout_seconds=50, max_physical_requests=1,
                                deadline_monotonic=deadline_monotonic, response_validator=validate,
                                request_id=f"candidate-observation:{revision}", attempt_observer=record)
    result = parse_json_object_response(raw)
    validate(raw)
    success = next((event for event in reversed(events) if event.get("status") == "success"), {})
    result["provider"] = {key: success.get(key) or "unavailable" for key in ("provider", "model", "protocol")}
    write_json(path, result)
    return result


def _validate_candidate_observation(value: Any) -> None:
    if not isinstance(value, dict) or value.get("text_coverage") not in {"complete", "partial", "unreadable"}:
        raise ValueError("Candidate observation has no honest text coverage")
    if value.get("measurement_coverage") not in {"complete", "partial", "not_applicable"}:
        raise ValueError("Candidate measurement coverage is invalid")
    if not isinstance(value.get("texts"), list) or not isinstance(value.get("measurements"), list):
        raise ValueError("Candidate observation lists are missing")
    for row in value["texts"]:
        if not isinstance(row, dict) or row.get("kind") not in TEXT_KINDS | {"brand"} or not isinstance(row.get("text"), str):
            raise ValueError("Candidate text observation is malformed")
        _observation_location(row, ("region",))
    for row in value["measurements"]:
        if not isinstance(row, dict) or row.get("relationship") not in {"same", "different", "unknown"} or not row.get("object"):
            raise ValueError("Candidate measured-object relationship is missing")
        if not isinstance(row.get("source_text"), str) or not isinstance(row.get("candidate_text"), str):
            raise ValueError("Observed source and candidate measurement text is required")
        _observation_location(row, ("source_region", "candidate_region"))
        if not row.get('source_id') or type(row.get('attachment_index')) is not int or row['attachment_index'] < 2:
            raise ValueError('Measurement source attachment is missing')
        for field in ('source_endpoints', 'candidate_endpoints'):
            points = row.get(field)
            if points is not None and (not isinstance(points, list) or len(points) != 2 or any(
                not isinstance(p, list) or len(p) != 2 or any(type(n) not in (int, float) or not 0 <= n <= 1 for n in p) for p in points)):
                raise ValueError('Measurement endpoints must be two normalized points, or null for a non-diagram callout')
    comparison = value.get("product_comparison")
    if not isinstance(comparison, dict) or comparison.get("status") not in {"consistent", "contradiction", "unknown"} or not comparison.get("evidence") or not comparison.get("part"):
        raise ValueError("Candidate product comparison is missing")
    _observation_location(comparison, ("source_region", "candidate_region"))
    if 'edit_comparison' in value:
        edit = value['edit_comparison']
        if not isinstance(edit, dict) or edit.get('status') not in {'consistent', 'contradiction', 'unknown'} or not edit.get('evidence'):
            raise ValueError('Edit comparison is invalid')
        _observation_location(edit, ('source_region', 'candidate_region'))


def _observation_location(row: dict[str, Any], regions: tuple[str, ...]) -> None:
    confidence = row.get("confidence")
    if not isinstance(confidence, (float, int)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("Invalid observation confidence")
    for field in regions:
        box = row.get(field)
        if not isinstance(box, list) or len(box) != 4 or any(not isinstance(x, (int, float)) or not 0 <= x <= 1 for x in box) or box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError("Observation needs a nonempty normalized region")
