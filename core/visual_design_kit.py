from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .final_source_intents import PLANNING_SOURCE_ROLES, selected_task_source_intents
from .io import (
    file_sha256,
    load_env,
    parse_json_object_response,
    read_jsonl,
    temporary_environ,
    write_jsonl,
    write_json,
)
from .job import load_job
from .plugin import ProductPlugin
from .paths import resolve_job_owned_path
from .product_family import read_product_family
from .progress_trace import record_progress
from .required_role_policy import compiled_image_policy
from .run_scope import read_run_scope
from .status import input_revision_id, logical_task_id
from .text_evidence import clean_evidence_text, has_bad_encoding, us_measurement_text
from .image_task_inputs import visual_product_color, visual_variation_values
from .palette_registry import planned_palette_diagnostics
from .vision_gemini_client import gemini_scope_identity, gemini_stream_generate
from .visual_context import planner_visual_context_instruction
from .image_reference_context import physical_views, planning_view_inputs, prepare_planning_views, source_crop_provenance
from .design_reference_library import approved_design_references, brand_design_brief, design_reference_usage
from .visual_semantics import review_planning_bindings, source_fact_records
from .visual_design_kit_compiler import (
    VisualDesignKitCompileError,
    _available_claims,
    claim_review_requests,
    design_binding_request,
    compile_visual_design_kit_response,
    validate_compiled_visual_design_kit,
    DESIGN_FIELD_SCHEMAS, IMAGE_DIRECTION_SCHEMA,
)
VISUAL_DESIGN_KIT_SCHEMA_VERSION = "visual-design-kit-v11"
VISUAL_DESIGN_KIT_POLICY_VERSION = "gemini-child-design-v56-scoped-reference-repair"
VISUAL_DESIGN_KIT_ARTIFACT = "visual_design_kits_v11.jsonl"

_ROW_FIELDS = {"schema_version", "policy_version", "category_id", "child", "source_reference", "source_sha256", "source_references", "child_facts_revision_id", "input_revision_id", "family_design_id", "visual_design_kit_id", "family_art_direction", "source_briefs", "planner", "approved_design_references"}
_SOURCE_FIELDS = {"source_id", "source_index", "role", "source_path", "source_sha256", "input_revision_id", "shopping_intent", "claims", "product_claims", "measurements", "observation", "crop_provenance"}
_PLANNER_FIELDS = {"provider", "model", "request_fingerprint", "response_fingerprint", "attempts", "configured_clients", "prompt_path", "response_path"}


class VisualDesignKitError(RuntimeError):
    pass


def build_visual_design_kits(
    *,
    job_dir: str | Path,
    plugin: ProductPlugin,
    config_path: str = "",
    workers: int = 4,
    attempt_id: str = "",
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    """Build one immutable visual-design row per selected child."""
    job = Path(job_dir).resolve()
    family = read_product_family(job)
    scope = read_run_scope(job)
    selected = set(scope["selected_children"])
    children = [
        row for row in family["family"]["children"]
        if str(row.get("asin") or "") in selected
    ]
    policy = compiled_image_policy(plugin)
    intents_by_child = _intents_by_child(job, plugin)
    previous = _read_previous(job, plugin.category_id)
    env = _planning_env(job, config_path)
    result: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []

    def build_one(child: dict[str, Any]) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
        child_deadline = min(deadline_monotonic or float("inf"), time.monotonic() + 180)
        asin = str(child.get("asin") or "")
        sources = _ordered_sources(intents_by_child.get(asin, []))
        main = next((row for row in sources if row.get("role") == "main"), None)
        if main is None:
            return asin, None, [_failure(
                asin,
                "final main source intent is unresolved; inspect this child's final_source_intents "
                "and source_observations, resolve the recorded classification failure, then resume classify,brief",
            )]
        source_manifest = _source_manifest(sources, child, job=job)
        design_refs = approved_design_references(job, asin)
        prompt = visual_design_kit_prompt(plugin, compact_product_facts(child), policy, source_manifest, design_refs, brand_design_brief(job))
        revision, child_facts_revision = _kit_input_revision(child=child, policy=policy, sources=sources, planner_prompt=prompt)
        cached = previous.get(asin)
        cached_current = bool(cached and visual_design_kit_row_current(
            job, plugin, asin, cached, child_row=child, sources=sources, policy=policy,
        ))
        if cached_current and all(row["status"] == "ready" for row in cached["source_briefs"]):
            record_progress(job, "visual_design_kit_cache_hit", child=asin, input_revision=revision)
            return asin, cached, []

        trace_dir = (
            job / "reports" / "visual_design_kit_traces" / asin / revision
            / uuid.uuid4().hex
        )
        trace_dir.mkdir(parents=True, exist_ok=True)
        request_path = trace_dir / "request.txt"
        response_path = trace_dir / "response.txt"
        attempts_path = trace_dir / "attempts.json"
        request_path.write_text(prompt, encoding="utf-8")
        attempts: list[dict[str, Any]] = []

        def validate_response(text: str) -> bool:
            compiled = compile_visual_design_kit_response(
                _parse_response(text),
                source_manifest=source_manifest,
                category_id=plugin.category_id,
                design_references=design_refs,
            )
            validate_visual_design_kit(
                compiled,
                source_manifest=source_manifest,
                category_id=plugin.category_id,
            )
            return True

        def observe(event: dict[str, Any]) -> None:
            attempt = {
                "provider": str(event.get("provider") or ""),
                "model": str(event.get("model") or ""),
                "attempt": int(event.get("attempt") or 0),
                "status": str(event.get("status") or ""),
                "elapsed_ms": event.get("elapsed_ms"),
                "error": str(event.get("error") or "")[:500],
            }
            attempts.append(attempt)
            attempts_path.write_text(json.dumps(attempts, indent=2, ensure_ascii=False), encoding="utf-8")
            if event.get("response_text"):
                response_index = len(attempts)
                (trace_dir / f"attempt{response_index}.response.txt").write_text(
                    str(event["response_text"]), encoding="utf-8",
                )
            record_progress(
                job,
                "visual_design_kit_provider_attempt",
                child=asin,
                provider=attempt["provider"],
                model=attempt["model"],
                status=attempt["status"],
                elapsed_ms=attempt["elapsed_ms"],
                error=attempt["error"],
                attempt_id=attempt_id,
            )
            if event.get("status") == "validation_failure" and event.get("response_text"):
                index = sum(row["status"] == "validation_failure" for row in attempts)
                (trace_dir / f"attempt{index}.invalid.txt").write_text(
                    str(event["response_text"]),
                    encoding="utf-8",
                )

        try:
            source_paths = prepare_planning_views(job, source_manifest, trace_dir / "evidence_views", deadline_monotonic=child_deadline)
            source_paths += [resolve_job_owned_path(job, row["path"]) for row in design_refs]
            record_progress(job, "visual_design_kit_started", child=asin, input_revision=revision)
            response_text = json.dumps({
                "family_art_direction": cached["family_art_direction"],
                "source_briefs": [(row["draft"] or {"source_id": row["source_id"]}) if row["status"] == "pending" else _brief_draft(row) for row in cached["source_briefs"]],
            }) if cached_current else gemini_stream_generate(
                prompt,
                source_paths,
                client_scope="visual_planning",
                timeout_seconds=60,
                attempts=1,
                # A slow planner must yield to the configured reserves in a
                # bounded interval; a successful ZIVV response in the live
                # canary completed well below this ceiling.
                total_timeout_seconds=90,
                deadline_monotonic=child_deadline,
                # Allow each configured provider one request plus one schema repair
                # on the provider that returns a structurally invalid response.
                max_physical_requests=2,
                response_validator=validate_response,
                attempt_observer=observe,
                request_id=f"visual-design-kit-v11:{asin}:{revision}",
            )
            raw_response_path = trace_dir / "provider_response.txt"
            raw_response_path.write_text(response_text, encoding="utf-8")
            planned = _finish_source_briefs(
                _parse_response(response_text), source_manifest=source_manifest,
                category_id=plugin.category_id, source_paths=source_paths,
                source_originals=[resolve_job_owned_path(job, row['source_path']) for row in source_manifest],
                trace_dir=trace_dir, deadline_monotonic=child_deadline,
                cached=cached if cached_current else None,
                design_references=design_refs,
            )
            validate_visual_design_kit(
                planned,
                source_manifest=source_manifest,
                category_id=plugin.category_id,
                design_references=design_refs,
            )
            response_path.write_text(
                json.dumps(planned, indent=2, ensure_ascii=False), encoding="utf-8",
            )
            write_json(trace_dir / "reference_usage.json", design_reference_usage(job, design_refs, planned["source_briefs"]))
            try:
                write_json(trace_dir / "palette_diagnostics.json", planned_palette_diagnostics(planned["family_art_direction"]))
            except Exception as exc:
                record_progress(job, "palette_diagnostics_unavailable", child=asin, error=f"{type(exc).__name__}: {exc}"[:300])
            selected_attempt = next(
                (row for row in reversed(attempts) if row["status"] == "success"),
                attempts[-1] if attempts else (cached["planner"] if cached_current else {}),
            )
            family_design_id = input_revision_id(planned["family_art_direction"])
            visual_design_kit_id = input_revision_id({
                "family_design_id": family_design_id,
                "source_references": source_manifest,
                "approved_design_references": design_refs,
                "source_briefs": planned["source_briefs"],
            })
            payload = {
                "schema_version": VISUAL_DESIGN_KIT_SCHEMA_VERSION,
                "policy_version": VISUAL_DESIGN_KIT_POLICY_VERSION,
                "category_id": plugin.category_id,
                "child": asin,
                "source_reference": str(main.get("source_path") or ""),
                "source_sha256": str(main.get("source_sha256") or ""),
                "source_references": source_manifest,
                "approved_design_references": design_refs,
                "child_facts_revision_id": child_facts_revision,
                "input_revision_id": revision,
                "family_design_id": family_design_id,
                "visual_design_kit_id": visual_design_kit_id,
                "family_art_direction": planned["family_art_direction"],
                "source_briefs": planned["source_briefs"],
                "planner": {
                    "provider": selected_attempt.get("provider") or "",
                    "model": selected_attempt.get("model") or "",
                    "request_fingerprint": file_sha256(request_path),
                    "response_fingerprint": input_revision_id(planned),
                    "attempts": attempts,
                    "configured_clients": gemini_scope_identity("visual_planning"),
                    "prompt_path": request_path.relative_to(job).as_posix(),
                    "response_path": response_path.relative_to(job).as_posix(),
                },
            }
            validate_visual_design_kit_row(payload, plugin.category_id)
            record_progress(job, "visual_design_kit_succeeded", child=asin, input_revision=revision, provider=payload["planner"]["provider"])
            return asin, payload, []
        except Exception as exc:
            record_progress(job, "visual_design_kit_failed", child=asin, input_revision=revision, error=f"{type(exc).__name__}: {exc}"[:1000])
            return asin, None, [_failure(asin, f"{type(exc).__name__}: {exc}", revision=revision)]

    configured_workers = str(os.environ.get("AMAZON_FACTORY_VISUAL_PLANNER_WORKERS") or "2").strip().casefold()
    if configured_workers in {"", "auto", "default"}:
        planner_workers = 2
    else:
        try:
            planner_workers = max(1, min(4, int(configured_workers)))
        except ValueError:
            planner_workers = 2
    max_workers = max(1, min(int(workers or planner_workers), planner_workers, len(children) or 1))
    with temporary_environ(env), ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(build_one, child): str(child.get("asin") or "")
            for child in children
        }
        for future in as_completed(futures):
            asin = futures[future]
            try:
                asin, payload, child_failures = future.result()
            except Exception as exc:
                payload = None
                child_failures = [_failure(asin, f"{type(exc).__name__}: {exc}")]
                record_progress(
                    job, "visual_design_kit_failed", child=asin,
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                )
            if payload is not None:
                # Keep the family artifact untouched until every selected child
                # has reached a terminal result.  Writing after each future
                # used to replace a complete family with a partial file when
                # the process was interrupted between children.
                result[asin] = payload
            failures.extend(child_failures)

    # A single atomic commit is the only point at which a rebuilt family
    # becomes visible.  Successful siblings remain usable when another child
    # fails, while an interrupted run cannot destroy the previous artifact.
    write_jsonl(job / "reports" / VISUAL_DESIGN_KIT_ARTIFACT, [result[key] for key in sorted(result)])
    return {
        "schema_version": VISUAL_DESIGN_KIT_SCHEMA_VERSION,
        "children": result,
        "tasks": list(result.values()),
        "failures": failures,
    }

def _brief_draft(brief: dict[str, Any]) -> dict[str, Any]:
    draft = {key: brief[key] for key in ("source_id", "image_direction")}
    draft["supporting_sources"] = brief["supporting_sources"]
    if brief["role"] in {"func", "size"}:
        bindings = brief["display_copy_contract"]["bindings"]
        has_title = bool(brief["display_copy_contract"]["title"])
        draft["display_copy"] = {"title": bindings[0] if has_title else None, "labels": bindings[1:] if has_title else bindings}
    return draft


def _finish_source_briefs(
    raw: dict[str, Any], *, source_manifest: list[dict[str, Any]], category_id: str,
    source_paths: list[Path], trace_dir: Path, deadline_monotonic: float,
    source_originals: list[Path],
    cached: dict[str, Any] | None,
    design_references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reviews = {key: value for brief in (cached or {}).get("source_briefs", [])
               for key, value in brief.get("claim_reviews", {}).items()}
    reviews.update({brief["design_review"]["key"]: brief["design_review"]
                    for brief in (cached or {}).get("source_briefs", []) if brief.get("design_review")})
    review_available = True
    sources = {source["source_id"]: source for source in source_manifest}

    def compile_reviewed(draft: dict[str, Any], attempt: str) -> dict[str, Any]:
        nonlocal review_available
        all_requests = [*claim_review_requests(draft, source_manifest),
                        *(design_binding_request(brief, draft["family_art_direction"], source=sources[brief["source_id"]], source_manifest=source_manifest, design_references=design_references) for brief in draft["source_briefs"])]
        requests = list({row["key"]: row for row in all_requests if row["key"] not in reviews}.values())
        try:
            reviews.update(review_planning_bindings(requests, shared_design=draft["family_art_direction"],
                source_manifest=source_manifest, source_paths=source_originals,
                view_paths=source_paths[:len(planning_view_inputs(source_manifest))],
                trace_dir=trace_dir / attempt, deadline_monotonic=deadline_monotonic))
        except Exception as exc:
            review_available = False
            reason = f"Planning review unavailable: {type(exc).__name__}: {exc}"
            (trace_dir / "planning_review_error.txt").write_text(reason, encoding="utf-8")
            reviews.update({row['key']: {'status': 'inconclusive', 'reason': reason}
                            for row in requests if row['kind'] == 'product_claim'})
        return compile_visual_design_kit_response(draft, source_manifest=source_manifest, category_id=category_id, claim_reviews=reviews, design_references=design_references)

    planned = compile_reviewed(raw, "initial")
    pending = [row for row in planned["source_briefs"] if row["status"] == "pending" and row['failure_owner'] == 'brief']
    if not pending or not review_available or time.monotonic() >= deadline_monotonic:
        return planned
    pending_ids = {row["source_id"] for row in pending}
    evidence_ids = pending_ids | {row['source_id'] for brief in raw['source_briefs'] if brief['source_id'] in pending_ids
                                 for row in brief.get('supporting_sources', [])}
    repair_sources = [row for row in source_manifest if row['source_id'] in evidence_ids]
    attachment_map = planning_view_inputs(source_manifest)
    repair_paths = [path for item, path in zip(attachment_map, source_paths) if item['source_id'] in evidence_ids]
    repair_paths.extend(source_paths[len(attachment_map):])
    prompt = (
        "Repair the listed source briefs under the unchanged named child design assignments. "
        "Return JSON {source_briefs:[...],shared_prose:{}}, one replacement for every listed source_id. "
        "shared_prose may correct only conflicting environment_and_staging, photography_direction or cohesion_rule "
        "descriptions by reusing named assignments; omit unchanged fields. Palette, typography and graphic values stay unchanged. "
        "Use the original brief schema; preserve complete claim objects, counts and qualifiers. "
        "Resolve all listed findings together: preserve supported specific features; remove only unsupported qualifiers. "
        "Resolve role color/material/font conflicts by referencing unchanged shared object/graphic names, not new values. "
        "Do not redesign the child or change other source briefs.\n"
        + json.dumps({"shared_design": planned["family_art_direction"], "pending": [
                          {key: row[key] for key in ('source_id', 'error', 'draft')} for row in pending],
                      "claim_review_findings": [{"source_id": row['source_id'], "proposed_text": row['proposed_text'],
                                                 "review": reviews.get(row["key"], {})}
                          for row in claim_review_requests({"source_briefs": [brief for brief in raw["source_briefs"]
                              if brief["source_id"] in pending_ids]}, source_manifest)],
                      "design_review_findings": [{"source_id": brief['source_id'], "review": reviews.get(request["key"], {})}
                          for brief in raw["source_briefs"] if brief["source_id"] in pending_ids
                          for request in [design_binding_request(brief, planned["family_art_direction"], source=sources[brief["source_id"]], source_manifest=source_manifest, design_references=design_references)]],
                      "source_evidence": [_planner_source_view(row) for row in repair_sources],
                      "evidence_attachments": planning_view_inputs(repair_sources),
                      "design_references": _planner_design_refs(design_references or [], len(planning_view_inputs(repair_sources))),
                      "product_claims": {claim['evidence_id']: claim['text'] for row in source_manifest for claim in row.get("product_claims") or []},
                      "schemas": [_brief_schema_for_source(row) for row in repair_sources if row['source_id'] in pending_ids]}, ensure_ascii=False)
    )
    (trace_dir / "brief_repair_request.txt").write_text(prompt, encoding="utf-8")

    def validate_repair(text: str) -> bool:
        value = _parse_response(text)
        rows = value.get("source_briefs")
        if not isinstance(rows, list) or len(rows) != len(pending_ids) or any(not isinstance(row, dict) for row in rows) or {row.get("source_id") for row in rows} != pending_ids:
            raise VisualDesignKitError("local brief repair changed its source inventory")
        prose = value.get("shared_prose", {})
        if (not isinstance(prose, dict) or set(prose) - {"environment_and_staging", "photography_direction", "cohesion_rule"}
                or any(not isinstance(text, str) or not text.strip() for text in prose.values())):
            raise VisualDesignKitError("local repair attempted to change shared design assignments")
        return True

    try:
        response = gemini_stream_generate(
            prompt, repair_paths, client_scope="visual_planning", attempts=1,
            max_physical_requests=1,
            deadline_monotonic=deadline_monotonic, response_validator=validate_repair,
            request_id=f"brief-local-repair:{input_revision_id(pending)}",
        )
        (trace_dir / "brief_repair_response.txt").write_text(response, encoding="utf-8")
        validate_repair(response)
        payload = _parse_response(response)
        repaired = payload["source_briefs"]
        replacement = {"family_art_direction": {**planned["family_art_direction"], **payload.get("shared_prose", {})}, "source_briefs": [
            *[row for row in raw["source_briefs"] if row["source_id"] not in pending_ids], *repaired,
        ]}
        return compile_reviewed(replacement, "repaired")
    except Exception as exc:
        (trace_dir / "brief_repair_error.txt").write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
        return planned


def read_visual_design_kits(job_dir: str | Path, *, plugin: ProductPlugin | None = None) -> dict[str, Any]:
    path = Path(job_dir) / "reports" / VISUAL_DESIGN_KIT_ARTIFACT
    if not path.is_file():
        raise VisualDesignKitError(f"VisualDesignKitV11 is missing: {path}")
    rows = read_jsonl(path)
    category_id = plugin.category_id if plugin is not None else ""
    for row in rows:
        validate_visual_design_kit_row(row, category_id)
        if not _planner_trace_current(Path(job_dir).resolve(), row):
            raise VisualDesignKitError(f"VisualDesignKitV11 planner trace is missing or changed: {row.get('child')}")
    children = {str(row["child"]): row for row in rows}
    if len(children) != len(rows):
            raise VisualDesignKitError("VisualDesignKitV11 has duplicate child rows")
    return {
        "schema_version": VISUAL_DESIGN_KIT_SCHEMA_VERSION,
        "children": children,
        "tasks": rows,
    }

def visual_design_kits_current(job_dir: str | Path, plugin: ProductPlugin, *, config_path: str = "") -> bool:
    del config_path
    try:
        job = Path(job_dir)
        artifact = read_visual_design_kits(job, plugin=plugin)
        family = read_product_family(job)
        selected = set(read_run_scope(job)["selected_children"])
        children = {
            str(row.get("asin") or ""): row
            for row in family["family"]["children"]
            if str(row.get("asin") or "") in selected
        }
        if set(artifact["children"]) != set(children):
            return False
        return all(
            visual_design_kit_row_current(job, plugin, asin, artifact["children"][asin])
            and all(brief.get("status") == "ready" for brief in artifact["children"][asin]["source_briefs"])
            for asin in children
        )
    except Exception:
        return False


def visual_design_kit_row_current(
    job_dir: str | Path, plugin: ProductPlugin, child: str, row: dict[str, Any], *,
    child_row: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> bool:
    """Validate one child kit without requiring every sibling to have a kit."""
    try:
        job = Path(job_dir).resolve()
        validate_visual_design_kit_row(row, plugin.category_id)
        if str(row.get("child") or "") != str(child) or not _planner_trace_current(job, row):
            return False
        if child_row is None:
            family = read_product_family(job)
            child_row = next(
                item for item in family["family"]["children"]
                if str(item.get("asin") or "") == str(child)
            )
        if sources is None:
            sources = _intents_by_child(job, plugin).get(str(child), [])
        sources = _ordered_sources(sources)
        if not any(source.get("role") == "main" for source in sources):
            return False
        policy = policy or compiled_image_policy(plugin)
        source_manifest = _source_manifest(sources, child_row, job=job)
        prompt = visual_design_kit_prompt(
            plugin, compact_product_facts(child_row), policy, source_manifest, approved_design_references(job, child), brand_design_brief(job),
        )
        expected_revision, expected_child_facts = _kit_input_revision(
            child=child_row, policy=policy, sources=sources, planner_prompt=prompt,
        )
        if row.get("approved_design_references") != approved_design_references(job, child):
            return False
        if row.get("source_references") != source_manifest:
            return False
        if row.get("child_facts_revision_id") != expected_child_facts:
            return False
        return row.get("input_revision_id") == expected_revision
    except Exception:
        return False

def resolve_visual_design_kit(artifact: dict[str, Any], child: str) -> dict[str, Any]:
    row = (artifact.get("children") or {}).get(str(child))
    if not isinstance(row, dict):
        raise VisualDesignKitError(f"VisualDesignKitV11 child is missing: {child}")
    validate_visual_design_kit_row(row)
    return row

def compact_product_facts(child: dict[str, Any]) -> dict[str, Any]:
    """Select whole source records without cutting qualifiers or measured objects."""
    normalized = child.get("normalized_facts") if isinstance(child.get("normalized_facts"), dict) else {}
    specs = child.get("specs") if isinstance(child.get("specs"), dict) else {}
    relevant = {key: value for key, value in specs.items()
                if any(term in str(key).casefold() for term in ("material", "finish", "color", "style", "room", "mount"))}
    return {
        "title": str(child.get("title") or ""),
        "variation": visual_variation_values(child),
        "color": visual_product_color(child),
        "size": normalized.get("size") or child.get("size") or "",
        "package": normalized.get("package") or child.get("package") or "",
        "style": normalized.get("style") or child.get("style") or "",
        "material_and_context_specs": relevant,
        "market_context": {"site": "US", "language": "English", "price_position": "unconfirmed",
                           "user_preferences": "bright clear presentation; avoid people and reflections; audience-appropriate staging; coherent child-wide palette and graphics"},
    }


def compact_product_claims(child: dict[str, Any]) -> list[dict[str, str]]:
    """Expose complete source statements, excluding seller defaults."""
    rows = []
    seen = set()
    for origin, text in source_fact_records(child).items():
        key = (origin, text.casefold())
        if origin == "product.title" or has_bad_encoding(text) or key in seen:
            continue
        seen.add(key)
        rows.append({"evidence_id": input_revision_id({"origin": origin, "text": text})[:20],
                     "field_path": origin,
                     "text": us_measurement_text(f"{origin.split('.')[-1].replace('_', ' ')}: {text}" if origin.startswith(('product.specs.', 'product.product_specific.')) else text),
                     "type": "source_product_statement"})
    return rows


def _planner_product_identity(facts: dict[str, Any]) -> dict[str, Any]:
    """Keep one compact identity view; feature prose is carried by evidence claims."""
    identity = {
        key: value
        for key, value in facts.items()
        if key != "features" and value not in (None, "", [], {})
    }
    variation = identity.get("variation")
    if isinstance(variation, dict):
        variation = {
            key: value
            for key, value in variation.items()
            if str(key).casefold() not in {"color", "colour", "color_name"}
            and not (
                str(key).casefold() in {"size", "package", "style"}
                and str(value or "").strip().casefold()
                == str(identity.get(str(key).casefold()) or "").strip().casefold()
            )
        }
        if variation:
            identity["variation"] = variation
        else:
            identity.pop("variation", None)
    return identity



def _planner_design_refs(rows: list[dict[str, Any]], offset: int) -> list[dict[str, Any]]:
    return [{"attachment_number": offset + index, "reference_id": row["source_id"],
             "roles": row["roles"], "transfer_principles": row["purpose"], "approval_boundary": row['visual_review']['transfer_scope']}
            for index, row in enumerate(rows, 1)]


def visual_design_kit_prompt(plugin: ProductPlugin, facts: dict[str, Any], policy: dict[str, Any], source_manifest: list[dict[str, Any]], design_references: list[dict[str, Any]] | None = None, brand_brief: dict[str, Any] | None = None) -> str:
    # One response grammar, not a duplicate schema for every gallery image.
    expected_briefs = [_brief_schema_for_source({"source_id": "one source_id from the evidence list", "role": "func"})]
    response_schema = {
        "family_art_direction": {
            "audience_and_market": "US buyer, room context, price position, and emotional goal",
            "palette_direction": {"non-product object name": "one chosen hex and material per object; include relevant wall/floor/textile/accent objects, no alternatives or graphics"},
            "photography_direction": "light, exposure, white balance, material response; no layout",
            "environment_and_staging": "US setting and prop placement; reuse palette objects, no new colors",
            **DESIGN_FIELD_SCHEMAS,
            "cohesion_rule": "name the core reference direction (or autonomous), why it fits this child, and how roles cohere; do not repeat styling values",
            "negative_visuals": ["2-6 concise child-wide design risks"],
        },
        "source_briefs": expected_briefs,
    }
    evidence = [_planner_source_view(row) for row in source_manifest]
    attachments = planning_view_inputs(source_manifest)
    product_claims = {
        str(claim["evidence_id"]): claim["text"]
        for source in source_manifest
        for claim in source.get("product_claims") or []
        if isinstance(claim, dict) and claim.get("evidence_id") and claim.get("text")
    }
    # Keep planner context useful but bounded; the same context is projected
    # again into role prompts, so repeating the full policy here adds noise.
    visual_context_guardrail = planner_visual_context_instruction(policy, max_chars=420)
    return (
        "Return JSON for one Amazon child. The program owns facts and process. You are the sole visual designer.\n\n"
        "Evidence attachments are intact observed views. Their feature map describes only visible pixels; residual graphics have no design authority.\n"
        "Preserve geometry, finish, physical count, state, perspective and visible extent WITHIN each product view, including visible mattresses in bed main/scene. Redesign canvas positions, view scale, panels, room decor and typography. Use bright, people-free settings.\n\n"
        + (visual_context_guardrail + "\n\n" if visual_context_guardrail else "")
        + "SOURCE BRIEFS\n"
        "supporting_sources=[{source_id,view_id,purpose,evidence_ids}]; select exact observed views and their feature IDs, source claims or object:object_id. Supporting views verify structure, not hidden parts.\n"
        "Return one brief per source_id; display_copy for func and size only. visual_goal identifies the buyer question, not a depicted state. creative_brief arranges the existing physical views, not a reconstructed illustration of the benefit.\n"
        "Main follows category policy; scenes share the object palette. Func hierarchy serves proven features; icons are optional. Partial views stay partial; measurement endpoints stay bound to physical points.\n"
        "Each evidence_usage is {view_id,usage,covered_by}. Non-displayed views may link only to displayed views actually showing the same observed feature_ids and state. Unique joints, slat recesses and measured endpoints remain visible; detail views cannot become whole products. Choose fresh canvas placement, not a mandatory panel per crop. Layout/text_placement may be []; bounds are normalized [left,top,right,bottom]. Text references: title, label:N or measurements; photos use [].\n"
        "design_transfer selects role-approved references within their transfer_principles: inherit only permitted features and explain adaptations. A reference approval is scoped, not permission to copy its whole style. Use [] without suitable references: autonomous, not reference-calibrated.\n"
        "Shared art direction fixes this child's adapted styling. creative_brief owns composition; design_transfer owns reference use. Both reuse shared names, not new colors or copy. The image model integrates layout, text and detail within this direction and product facts.\n"
        "Choose one color/material per non-product object in the shared palette. scene_objects maps each observed staging object_id to its palette key, "
        "or null for removable decor omitted from this composition; occluding bedding must be restyled, not removed. Introduced objects use new:descriptive_name keys. "
        "Include contents in graphic_canvas/source_setting; product-only white mains use an empty map and bare views remain bare. "
        "creative_brief positions these objects without redefining their appearance. One treatment per graphic role; local backing only for readability, no default capsule.\n"
        "For func/size, display_copy owns all exact titles, group labels and inset captions: title may be null, labels may be empty. Bind each independent string to its local evidence IDs, not a paragraph later split into captions. physical: evidence proves visible structure only, never performance/material specifications; measurement: evidence supports measured-object headings, not new values. Size numeric labels already come from measurement authority: do not repeat them as copy. Prefer specific mechanisms with their counts and qualifiers.\n\n"
        "Source-colored outlines, adjustment ghosts and highlights are diagram notation, not finish or extra physical parts. Size preserves quantities and measurement associations; program-approved US-unit labels replace metric labels.\n\n"
        f"Category: {plugin.category_id}\n"
        f"Product type: {plugin.display_name}\n"
        f"Product identity: {json.dumps(_planner_product_identity(facts), ensure_ascii=False, separators=(',', ':'))}\n"
        f"User brand design brief (not product facts): {json.dumps(brand_brief or {}, ensure_ascii=False)}\n"
        f"Trusted product fact evidence: {json.dumps(product_claims, ensure_ascii=False, separators=(',', ':'))}\n"
        f"Final source intents: {json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}\n"
        f"Evidence attachment map: {json.dumps(attachments, separators=(',', ':'))}\n"
        f"Approved style-only attachments (never fact evidence): {json.dumps(_planner_design_refs(design_references or [], len(attachments)), ensure_ascii=False)}\n"
        f"Reference design systems: {json.dumps(list(dict.fromkeys(row['design_system'] for row in design_references or [])), ensure_ascii=False)}\n"
        f"Program-owned product-boundary policy: {json.dumps(_planner_policy_view(policy), ensure_ascii=False)}\n"
        f"Required response schema: {json.dumps(response_schema, ensure_ascii=False, separators=(',', ':'))}"
    )


def validate_visual_design_kit(
    data: dict[str, Any],
    *,
    source_manifest: list[dict[str, Any]],
    category_id: str = "",
    design_references: list[dict[str, Any]] | None = None,
) -> None:
    try:
        validate_compiled_visual_design_kit(
            data, source_manifest=source_manifest, category_id=category_id, design_references=design_references,
        )
    except VisualDesignKitCompileError as exc:
        raise VisualDesignKitError(str(exc)) from exc

def validate_visual_design_kit_row(row: Any, category_id: str = "") -> None:
    if not isinstance(row, dict) or row.get("schema_version") != VISUAL_DESIGN_KIT_SCHEMA_VERSION:
        raise VisualDesignKitError("Invalid VisualDesignKitV11 row")
    if row.get("policy_version") != VISUAL_DESIGN_KIT_POLICY_VERSION:
        raise VisualDesignKitError("VisualDesignKitV11 policy mismatch")
    if set(row) != _ROW_FIELDS:
        raise VisualDesignKitError("VisualDesignKitV11 row fields do not match the current contract")
    for key in ("category_id", "child", "source_reference", "source_sha256", "child_facts_revision_id", "input_revision_id", "family_design_id", "visual_design_kit_id"):
        _validate_text(row[key], key, maximum=500)
    if category_id and row["category_id"] != category_id:
        raise VisualDesignKitError("VisualDesignKitV11 category mismatch")
    sources = row["source_references"]
    _validate_source_manifest(sources)
    validate_visual_design_kit(
        {
            "family_art_direction": row["family_art_direction"],
            "source_briefs": row["source_briefs"],
        },
        source_manifest=sources,
        category_id=category_id or str(row.get("category_id") or ""),
        design_references=row["approved_design_references"],
    )
    main = next((source for source in sources if source["role"] == "main"), None)
    if main is None or row["source_reference"] != main["source_path"] or row["source_sha256"] != main["source_sha256"]:
        raise VisualDesignKitError("VisualDesignKitV11 main reference binding is inconsistent")
    expected_family = input_revision_id(row["family_art_direction"])
    if row["family_design_id"] != expected_family:
        raise VisualDesignKitError("VisualDesignKitV11 family art direction changed")
    expected_kit = input_revision_id({
        "family_design_id": expected_family,
        "source_references": sources,
        "approved_design_references": row["approved_design_references"],
        "source_briefs": row["source_briefs"],
    })
    if row["visual_design_kit_id"] != expected_kit:
        raise VisualDesignKitError("VisualDesignKitV11 source briefs changed")
    planner = row["planner"]
    if not isinstance(planner, dict) or set(planner) != _PLANNER_FIELDS or not str(planner.get("provider") or "").strip() or not str(planner.get("model") or "").strip():
        raise VisualDesignKitError("VisualDesignKitV11 planner provenance is incomplete")
    expected_response = input_revision_id({
        "family_art_direction": row["family_art_direction"],
        "source_briefs": row["source_briefs"],
    })
    if planner["response_fingerprint"] != expected_response:
        raise VisualDesignKitError("VisualDesignKitV11 planner response fingerprint changed")

def _intents_by_child(job: Path, plugin: ProductPlugin) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in selected_task_source_intents(job, plugin=plugin):
        grouped.setdefault(str(row.get("child") or ""), []).append(row)
    return grouped

def _kit_input_revision(*, child: dict[str, Any], policy: dict[str, Any], sources: list[dict[str, Any]], planner_prompt: str) -> tuple[str, str]:
    # Bind only facts actually exposed to the visual director.  Price,
    # inventory, copy mode, and unrelated listing metadata must not invalidate
    # a successful family design.
    child_facts_revision = input_revision_id({
        "compact_product_facts": compact_product_facts(child),
        "material_facts": _material_facts(child),
    })
    policy_id = str(policy.get("policy_id") or "")
    if not policy_id:
        raise VisualDesignKitError("compiled image policy has no policy_id")
    # The actual planner input is part of the visual authority.  If its
    # wording changes, reusing the previous kit would make production ignore
    # the new design direction while appearing current.
    planner_prompt_sha256 = hashlib.sha256(planner_prompt.encode("utf-8")).hexdigest()
    revision = input_revision_id({
        "child_facts_revision_id": child_facts_revision,
        "child_material": _material_facts(child),
        "complete_image_policy_id": policy_id,
        "planner_prompt_sha256": planner_prompt_sha256,
        "ordered_final_source_intent_revisions": [str(row.get("input_revision_id") or "") for row in sources],
    })
    return revision, child_facts_revision

def _material_facts(child: dict[str, Any]) -> dict[str, Any]:
    normalized = child.get("normalized_facts") if isinstance(child.get("normalized_facts"), dict) else {}
    specs = child.get("specs") if isinstance(child.get("specs"), dict) else {}
    return {
        "color": visual_product_color(child),
        "style": normalized.get("style") or child.get("style"),
        "variation": visual_variation_values(child),
        "material_specs": {str(key): value for key, value in specs.items() if any(token in str(key).casefold() for token in ("material", "finish", "color"))},
    }

def _ordered_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (0 if row.get("role") == "main" else 1, int(row.get("source_index") or 0), str(row.get("source_sha256") or "")))


def _source_manifest(rows: list[dict[str, Any]], child: dict[str, Any], *, job: Path) -> list[dict[str, Any]]:
    manifest = []
    product_claims = compact_product_claims(child)
    product_claims_emitted = False
    for row in rows:
        source_product_claims = []
        if row.get("role") == "func" and not product_claims_emitted:
            # Keep the complete shared set in one place.  Per-source
            # contradiction filtering happens when a func brief is bound,
            # so an early source cannot hide a fact needed by a later one.
            source_product_claims = list(product_claims)
            product_claims_emitted = True
        manifest.append({
            "source_id": f"source_{int(row.get('source_index') or 0):02d}",
            "source_index": int(row.get("source_index") or 0),
            "role": str(row.get("role") or ""),
            "source_path": str(row.get("source_path") or ""),
            "source_sha256": str(row.get("source_sha256") or ""),
            "input_revision_id": str(row.get("input_revision_id") or ""),
            "shopping_intent": row.get("shopping_intent") or "",
            "claims": row.get("claims") or [],
            # Product facts are child-level evidence, not source-level copy.
            # Emit them once; compiler/task code resolves the shared set for
            # every func source while source claims remain source-bound.
            "product_claims": source_product_claims,
            "measurements": row.get("measurements") or [],
            "observation": {key: (row.get("visual_evidence") or {}).get(key) for key in ("status", "objects", "physical_views")},
        })
    for source in manifest:
        source['crop_provenance'] = source_crop_provenance(job, source)
    _validate_source_manifest(manifest)
    return manifest


def _validate_source_manifest(rows: Any) -> None:
    if not isinstance(rows, list) or not rows:
        raise VisualDesignKitError("source_references must be a non-empty list")
    ids: set[str] = set()
    product_claim_ids: set[str] = set()
    main_count = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != _SOURCE_FIELDS:
            raise VisualDesignKitError(f"source_references[{index}] is malformed")
        if row["source_id"] in ids:
            raise VisualDesignKitError("source_references contain duplicate source IDs")
        ids.add(row["source_id"])
        if not physical_views((row.get("observation") or {}).get("physical_views")):
            raise VisualDesignKitError(f"{row['source_id']}: source observation has no physical views")
        if row["role"] not in PLANNING_SOURCE_ROLES:
            raise VisualDesignKitError(f"source_references[{index}] has unsupported role")
        main_count += row["role"] == "main"
        for key in ("source_id", "source_path", "source_sha256", "input_revision_id"):
            _validate_text(row[key], f"source_references[{index}].{key}", maximum=1000)
        if not isinstance(row["source_index"], int) or row["source_index"] < 0:
            raise VisualDesignKitError(f"source_references[{index}].source_index is invalid")
        if (
            not isinstance(row["claims"], list)
            or not isinstance(row["product_claims"], list)
            or not isinstance(row["measurements"], list)
        ):
            raise VisualDesignKitError(f"source_references[{index}] evidence must be lists")
        if row["role"] == "func":
            claim_ids: set[str] = set()
            for claim in row["claims"]:
                if not isinstance(claim, dict) or set(claim) != {"evidence_id", "source_sha256", "text", "type", "confidence"}:
                    raise VisualDesignKitError(f"source_references[{index}] has malformed func evidence")
                if claim["source_sha256"] != row["source_sha256"] or not str(claim["evidence_id"]):
                    raise VisualDesignKitError(f"source_references[{index}] has unbound func evidence")
                claim_ids.add(str(claim["evidence_id"]))
            if len(claim_ids) != len(row["claims"]):
                raise VisualDesignKitError(f"source_references[{index}] has duplicate func evidence IDs")
            for claim in row["product_claims"]:
                if (
                    not isinstance(claim, dict)
                    or set(claim) != {"evidence_id", "field_path", "text", "type"}
                    or not str(claim.get("evidence_id") or "")
                    or not str(claim.get("text") or "").strip()
                ):
                    raise VisualDesignKitError(
                        f"source_references[{index}] has malformed product fact evidence"
                    )
                claim_id = str(claim["evidence_id"])
                if claim_id in product_claim_ids:
                    raise VisualDesignKitError(
                        "source_references repeat shared product fact evidence"
                    )
                product_claim_ids.add(claim_id)
            if len({str(claim["evidence_id"]) for claim in row["product_claims"]}) != len(row["product_claims"]):
                raise VisualDesignKitError(
                    f"source_references[{index}] has duplicate product fact evidence"
                )
    if main_count != 1:
        raise VisualDesignKitError("source_references must contain exactly one main")


def _planner_source_view(row: dict[str, Any]) -> dict[str, Any]:
    source_id = row['source_id']
    views = physical_views((row.get("observation") or {}).get("physical_views"))
    view = {
        "source_id": source_id,
        "role": row["role"],
        "objects": [{key: obj[key] for key in ('object_id', 'kind', 'sale_membership', 'visibility', 'state', 'relations')}
                    for obj in row.get('observation', {}).get('objects') or []],
        "physical_evidence": {"views": [{**v, 'evidence': [{**f, 'copy_evidence_ids': [
            f"physical:{source_id}:{v['view_id']}:{f['feature_id']}:{i}" for i in range(len(f['physical_facts']))]}
            for f in v['evidence']]} for v in views]},
    }
    if row.get("measurements"):
        view["measurements"] = [{'evidence_id': f'measurement:{source_id}:{i}',
                                 **{key: item.get(key) for key in ("text", "source_label", "axis_hint")}}
                                for i, item in enumerate(row["measurements"])]
    if row["role"] in {"func", "size"}:
        view["source_supported_claims"] = [{"evidence_id": key, "text": value}
                                           for key, value in _available_claims(row, []).items()
                                           if not key.startswith(('physical:', 'measurement:'))]
    return view


def _brief_schema_for_source(source: dict[str, Any]) -> dict[str, Any]:
    role = source["role"]
    common: dict[str, Any] = {
        "source_id": source["source_id"],
        "supporting_sources": [],
    }
    common["image_direction"] = IMAGE_DIRECTION_SCHEMA
    if role in {"func", "size"}:
        common.update({
            "display_copy": {
                "title": {"evidence_ids": ["listed evidence_id"], "text": "factual title or measurement-group heading; null to omit"},
                "labels": [{"evidence_ids": ["listed evidence_id"], "text": "one complete displayed caption, not combined caption choices"}],
            },
        })
    return common


def _planner_policy_view(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        key: policy.get(key)
        for key in (
            "main_image_policy", "allowed_internal_props",
            "replaceable_staging",
            "role_visual_direction",
        )
        if policy.get(key) not in (None, "", [], {})
    }


def _validate_text(value: Any, label: str, *, minimum: int = 1, maximum: int) -> None:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or not value.strip():
        raise VisualDesignKitError(f"{label} is missing or outside its length budget")
    if value != value.strip():
        raise VisualDesignKitError(f"{label} contains leading or trailing whitespace")
    if has_bad_encoding(value) or "\ufffd" in value or re.search(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", value):
        raise VisualDesignKitError(f"{label} contains malformed text")
    if re.search(r"[\u0400-\u04ff\u4e00-\u9fff]", value):
        raise VisualDesignKitError(f"{label} must use English text")


def _parse_response(text: str) -> dict[str, Any]:
    try:
        return parse_json_object_response(text, label="VisualDesignKit planner response")
    except ValueError as exc:
        raise VisualDesignKitError(str(exc)) from exc


def _read_previous(job: Path, category_id: str) -> dict[str, dict[str, Any]]:
    path = job / "reports" / VISUAL_DESIGN_KIT_ARTIFACT
    if not path.is_file():
        return {}
    result: dict[str, dict[str, Any]] = {}
    try:
        rows = read_jsonl(path)
    except Exception:
        return {}
    for row in rows:
        try:
            validate_visual_design_kit_row(row, category_id)
            result[str(row["child"])] = row
        except Exception:
            # A policy or source change invalidates the complete row.  It must
            # never become input to a new planner run.
            continue
    return result


def _planner_trace_current(job: Path, row: dict[str, Any]) -> bool:
    planner = row.get("planner") if isinstance(row.get("planner"), dict) else {}
    try:
        request = resolve_job_owned_path(job, str(planner.get("prompt_path") or ""))
        response = resolve_job_owned_path(job, str(planner.get("response_path") or ""))
        if not request.is_file() or not response.is_file():
            return False
        if file_sha256(request) != str(planner.get("request_fingerprint") or ""):
            return False
        for brief in row.get("source_briefs", []):
            checks = [*brief.get("claim_reviews", {}).values()]
            if brief.get("design_review"):
                checks.append(brief["design_review"])
            for review in checks:
                path = resolve_job_owned_path(job, str(review.get("response_path") or ""))
                if not path.is_file() or file_sha256(path) != review.get("response_sha256"):
                    return False
                records = _parse_response(path.read_text(encoding="utf-8")).get("reviews", [])
                if not any(all(item.get(key) == review.get(key) for key in ("key", "status", "reason", "findings")) for item in records):
                    return False
        return input_revision_id(_parse_response(response.read_text(encoding="utf-8"))) == str(
            planner.get("response_fingerprint") or ""
        )
    except Exception:
        return False


def _failure(
    child: str,
    error: str,
    *,
    revision: str = "",
    terminal: bool = False,
) -> dict[str, Any]:
    return {
        "task": {
            "logical_task_id": logical_task_id("brief", child=child, role="design_kit"),
            "input_revision_id": revision or input_revision_id({
                "policy": VISUAL_DESIGN_KIT_POLICY_VERSION,
                "child": child,
                "error": error,
            }),
            "child": child,
            "role": "design_kit",
        },
        "failure_owner": "brief",
        "task_status": "blocked" if terminal else "retryable",
        "error": error,
    }


def _planning_env(job: Path, config_path: str) -> dict[str, str]:
    values: dict[str, str] = dict(os.environ)
    job_config = str(load_job(job).get("config_path") or "") if (job / "job.json").is_file() else ""
    for path in (config_path, job_config):
        if str(path or "").strip():
            values = {**load_env(path, override=False), **values}
    return values
