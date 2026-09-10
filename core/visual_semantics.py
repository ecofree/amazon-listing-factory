from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import file_sha256, parse_json_object_response, read_json, write_json
from .status import input_revision_id
from .vision_gemini_client import gemini_stream_generate


OBSERVATION_POLICY = "child-joint-observation-v2-variant-identity"
CLAIM_REVIEW_POLICY = "independent-claim-entailment-v1"
CANDIDATE_OBSERVATION_POLICY = "blind-candidate-observation-v1"
TEXT_KINDS = {"product_label", "marketing", "measurement", "prop", "unknown"}
MEMBERSHIPS = {"product", "included_accessory", "staging", "unknown"}


def _attempt_trace(path: Path) -> tuple[list[dict[str, Any]], Any]:
    events: list[dict[str, Any]] = []

    def record(event: dict[str, Any]) -> None:
        events.append({key: event.get(key) for key in (
            "request_id", "provider", "model", "protocol", "attempt", "status", "elapsed_ms",
        )})
        write_json(path, events)

    return events, record


def source_fact_records(child: dict[str, Any]) -> dict[str, str]:
    """Keep complete source statements; commerce defaults do not prove claims."""
    records: dict[str, str] = {}

    def visit(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, f"{prefix}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{prefix}.{index}")
        elif value is not None and str(value).strip():
            records[prefix] = str(value).strip()

    for field in ("title", "bullets", "features", "specs", "product_specific", "variation_values"):
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
            "layout_summary": "visible view and product state",
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
                "state": "observed state; unknown where not visible",
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
        "Describe only product-relevant parts and staging that affects editing or occlusion. "
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
        _validate_observations(parse_json_object_response(text)["sources"], source_ids, facts)
        return True

    _events, record = _attempt_trace(cache.with_suffix(".attempts.json"))
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
    for row in result.values():
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

    product_refs = [row for row in task["generation_references"] if row["kind"] != "design_reference"]
    images = [resolve_job_owned_path(job, candidate["candidate_path"])] + [resolve_job_owned_path(job, row["path"]) for row in product_refs]
    revision = input_revision_id({"policy": CANDIDATE_OBSERVATION_POLICY, "candidate": candidate["candidate_sha256"],
                                 "references": product_refs, "product": task["product_facts"]})
    path = job / "reports" / "candidate_observations" / f"{revision}.json"
    if path.is_file():
        cached = read_json(path)
        _validate_candidate_observation(cached)
        return cached
    schema = {
        "text_coverage": "complete|partial|unreadable",
        "texts": [{"text": "verbatim observed text", "kind": "marketing|measurement|product_label|prop|brand|unknown",
                   "confidence": 0.0, "region": [0.0, 0.0, 1.0, 1.0]}],
        "measurements": [{"object": "measured part and axis", "source_text": "observed in attachment 2+",
                          "candidate_text": "observed in attachment 1", "relationship": "same|different|unknown",
                          "confidence": 0.0, "source_region": [0.0, 0.0, 1.0, 1.0], "candidate_region": [0.0, 0.0, 1.0, 1.0]}],
        "measurement_coverage": "complete|partial|not_applicable",
        "product_comparison": {"status": "consistent|contradiction|unknown", "part": "specific sold part",
                               "evidence": "source/candidate geometry, count, finish and state comparison, not aesthetics",
                               "confidence": 0.0, "source_region": [0.0, 0.0, 1.0, 1.0], "candidate_region": [0.0, 0.0, 1.0, 1.0]},
    }
    prompt = (
        "Attachment 1 is the generated candidate; subsequent attachments are the same child's product evidence. "
        "Observe the actual pixels independently; no expected display copy is supplied. Return only the JSON schema. "
        "Transcribe candidate text verbatim with normalized bounding boxes. Distinguish marketing/dimensions from "
        "product surface labels and loose props; do not guess illegible words or brand identity. "
        "Compare measurement values AND their measured object and both arrow endpoints using the source diagram. "
        "Compare sold-product geometry, count, finish and demonstrated state. Restyled room/bedding/props are not product defects. "
        "Occlusion or unseen parts mean unknown, not absence. Report partial coverage honestly. "
        "Do not score aesthetics or improve the image. Every contradiction needs a specific part and two visible regions.\n"
        + json.dumps({"schema": schema, "product_identity": task["product_facts"]}, ensure_ascii=False)
    )
    def validate(text: str) -> bool:
        _validate_candidate_observation(parse_json_object_response(text))
        return True
    events, record = _attempt_trace(path.with_suffix(".attempts.json"))
    raw = gemini_stream_generate(prompt, images, client_scope="vision_qa", attempts=1,
                                timeout_seconds=50, total_timeout_seconds=50, max_physical_requests=1,
                                deadline_monotonic=deadline_monotonic, response_validator=validate,
                                request_id=f"candidate-observation:{revision}", attempt_observer=record)
    result = parse_json_object_response(raw)
    _validate_candidate_observation(result)
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
    comparison = value.get("product_comparison")
    if not isinstance(comparison, dict) or comparison.get("status") not in {"consistent", "contradiction", "unknown"} or not comparison.get("evidence") or not comparison.get("part"):
        raise ValueError("Candidate product comparison is missing")
    _observation_location(comparison, ("source_region", "candidate_region"))


def _observation_location(row: dict[str, Any], regions: tuple[str, ...]) -> None:
    confidence = row.get("confidence")
    if not isinstance(confidence, (float, int)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("Invalid observation confidence")
    for field in regions:
        box = row.get(field)
        if not isinstance(box, list) or len(box) != 4 or any(not isinstance(x, (int, float)) or not 0 <= x <= 1 for x in box) or box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError("Observation needs a nonempty normalized region")
