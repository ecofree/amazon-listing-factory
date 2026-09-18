from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

from .final_source_intents import PLANNING_SOURCE_ROLES, selected_task_source_intents
from .io import (
    file_sha256,
    load_env,
    parse_json_object_response,
    read_json,
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
from .text_evidence import has_bad_encoding, us_measurement_text
from .image_task_inputs import visual_product_color, visual_variation_values, task_specs, initial_output_inventory, shared_design_values
from .palette_registry import planned_palette_diagnostics
from .vision_gemini_client import gemini_scope_identity, gemini_stream_generate, VisionRequestError
from .visual_context import planner_visual_context_instruction
from .image_reference_context import product_features, planning_reference_inputs, prepare_planning_references
from .design_reference_library import approved_design_references, brand_design_brief, design_reference_usage, design_reference_semantics
from .visual_semantics import CLAIM_REVIEW_POLICY, _attempt_trace, review_planning_bindings, source_fact_records
from .visual_design_kit_compiler import (
    VisualDesignKitCompileError,
    _available_claims,
    claim_review_requests,
    design_binding_request,
    review_failure_owner,
    compile_visual_design_kit_response,
    validate_compiled_visual_design_kit,
    validate_image_brief_draft,
    required_observation_issues,
    DESIGN_FIELD_SCHEMAS, IMAGE_DIRECTION_SCHEMA,
)
VISUAL_DESIGN_KIT_SCHEMA_VERSION = "visual-design-kit-v16"
VISUAL_DESIGN_KIT_POLICY_VERSION = "gemini-output-design-v74-original-evidence"
VISUAL_DESIGN_KIT_ARTIFACT = "visual_design_kits_v16.jsonl"

_ROW_FIELDS = {"schema_version", "policy_version", "category_id", "main_image_policy", "child", "source_reference", "source_sha256", "source_references", "product_claims", "child_facts_revision_id", "input_revision_id", "family_design_id", "visual_design_kit_id", "family_art_direction", "image_briefs", "output_inventory", "planner", "approved_design_references"}
_SOURCE_FIELDS = {"source_id", "source_index", "role", "source_path", "source_sha256", "input_revision_id", "shopping_intent", "claims", "measurements", "observation"}
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
    committed = {key: row for key, row in previous.items() if key in selected and _planner_trace_current(job, row)}
    commit_lock = Lock()
    write_jsonl(job / 'reports' / VISUAL_DESIGN_KIT_ARTIFACT, [committed[key] for key in sorted(committed)])
    result: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []

    def build_one(child: dict[str, Any]) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
        child_deadline = min(deadline_monotonic or float("inf"), time.monotonic() + 180)
        asin = str(child.get("asin") or "")
        sources = _ordered_sources(intents_by_child.get(asin, []))
        if not sources:
            return asin, None, [_failure(
                asin,
                "No current product evidence is available for this child",
            )]
        cached = previous.get(asin)
        inventory = initial_output_inventory(sources, previous=cached)
        anchor = task_specs(child, sources, inventory=inventory, include_optional=True)[0]['source'] or sources[0]
        source_manifest = _source_manifest(sources, job=job)
        product_claims = compact_product_claims(child)
        design_refs = approved_design_references(job, asin)
        prompt = visual_design_kit_prompt(plugin, compact_product_facts(child), policy, source_manifest, design_refs, brand_design_brief(job), product_claims=product_claims, output_inventory=inventory)
        revision, child_facts_revision = _kit_input_revision(child=child, policy=policy, sources=sources, planner_prompt=prompt)
        cached_current = bool(cached and visual_design_kit_row_current(
            job, plugin, asin, cached, child_row=child, sources=sources, policy=policy,
        ))
        if cached_current and all(row["status"] == "ready" for row in cached["image_briefs"]):
            record_progress(job, "visual_design_kit_cache_hit", child=asin, input_revision=revision)
            return asin, cached, []
        scoped_repair = bool(cached and not cached_current and _local_evidence_repair(
            job, cached, source_manifest, child_facts_revision=child_facts_revision,
            prompt=prompt, plugin=plugin, facts=compact_product_facts(child), policy=policy,
            design_refs=design_refs,
            observation_revisions={f"source_{row['source_index']:02d}": (row.get('visual_evidence') or {}).get('planning_correction', {})
                                   for row in sources},
        ))

        trace_dir = (
            job / "reports" / "visual_design_kit_traces" / asin / revision
            / uuid.uuid4().hex
        )
        trace_dir.mkdir(parents=True, exist_ok=True)
        request_path = trace_dir / "request.txt"
        attempts_path = trace_dir / "attempts.json"
        budget_path = trace_dir.parent / 'attempt_budget.json'
        budget = read_json(budget_path) if budget_path.is_file() else {}
        plan_start = budget.get('plan', 0)
        plan_request_id = f'{VISUAL_DESIGN_KIT_SCHEMA_VERSION}:{asin}:{revision}'
        plan_limits = budget.get('output_limits', {}).get(plan_request_id, [])
        request_path.write_text(prompt, encoding="utf-8")

        def validate_response(text: str) -> bool:
            compiled = compile_visual_design_kit_response(
                _parse_response(text),
                output_inventory=inventory,
                source_manifest=source_manifest,
                product_claims=product_claims,
                category_id=plugin.category_id,
                main_policy=policy['main_image_policy'],
                design_references=design_refs,
            )
            validate_visual_design_kit(
                compiled,
                source_manifest=source_manifest,
                product_claims=product_claims,
                category_id=plugin.category_id,
                main_policy=policy['main_image_policy'],
                design_references=design_refs,
            )
            return True

        def observe(event: dict[str, Any]) -> None:
            if event.get('event') == 'request_budget':
                budget['plan'] = plan_start + event['physical_request_count']
                write_json(budget_path, budget)
                return
            if event.get('status') == 'output_limit':
                budget.setdefault('output_limits', {}).setdefault(event['request_id'], []).append(
                    {key: event.get(key) for key in ('provider', 'model', 'max_output_tokens', 'output_token_cap')})
                write_json(budget_path, budget)
            record_progress(
                job,
                "visual_design_kit_provider_attempt",
                child=asin,
                provider=event.get('provider', ''), model=event.get('model', ''), status=event.get('status', ''),
                elapsed_ms=event.get('elapsed_ms'), error=str(event.get('error') or '')[:500],
                attempt_id=attempt_id,
            )

        attempts, record = _attempt_trace(attempts_path, observer=observe)
        last_payload = None

        def persist(planned: dict[str, Any]) -> None:
            nonlocal last_payload
            snapshot = deepcopy(planned)
            for brief in snapshot['image_briefs']:
                bound = [*brief.get('claim_reviews', {}).values(), brief.get('design_review', {})]
                bound += [finding for review in bound for finding in review.get('findings', [])]
                for review in bound:
                    if review.get('response_path'):
                        review['response_path'] = resolve_job_owned_path(job, review['response_path']).relative_to(job).as_posix()
            response_fingerprint = input_revision_id(snapshot)
            if last_payload and last_payload['planner']['response_fingerprint'] == response_fingerprint:
                return
            response_path = trace_dir / f'response-{response_fingerprint}.json'
            write_json(response_path, snapshot)
            selected_attempt = next((row for row in reversed(attempts) if row['status'] == 'success'),
                                    attempts[-1] if attempts else (cached['planner'] if cached_current or scoped_repair else {}))
            family_design_id = input_revision_id(snapshot['family_art_direction'])
            payload = {
                'schema_version': VISUAL_DESIGN_KIT_SCHEMA_VERSION, 'policy_version': VISUAL_DESIGN_KIT_POLICY_VERSION,
                'category_id': plugin.category_id, 'main_image_policy': policy['main_image_policy'], 'child': asin,
                'source_reference': str(anchor.get('source_path') or ''), 'source_sha256': str(anchor.get('source_sha256') or ''),
                'source_references': source_manifest, 'product_claims': product_claims, 'approved_design_references': design_refs,
                'child_facts_revision_id': child_facts_revision, 'input_revision_id': revision,
                'family_design_id': family_design_id,
                'visual_design_kit_id': input_revision_id({
                    'family_design_id': family_design_id, 'main_image_policy': policy['main_image_policy'],
                    'source_references': source_manifest, 'product_claims': product_claims, 'approved_design_references': design_refs,
                    'image_briefs': snapshot['image_briefs'], 'output_inventory': inventory}),
                **snapshot,
                'planner': {
                    'provider': selected_attempt.get('provider') or '', 'model': selected_attempt.get('model') or '',
                    'request_fingerprint': file_sha256(request_path), 'response_fingerprint': response_fingerprint,
                    'attempts': deepcopy(attempts), 'configured_clients': gemini_scope_identity('visual_planning'),
                    'prompt_path': request_path.relative_to(job).as_posix(), 'response_path': response_path.relative_to(job).as_posix(),
                },
            }
            validate_visual_design_kit_row(payload, plugin.category_id)
            # Merge under one writer lock; a child checkpoint must not replace its siblings.
            with commit_lock:
                merged = {**committed, asin: payload}
                write_jsonl(job / 'reports' / VISUAL_DESIGN_KIT_ARTIFACT, [merged[key] for key in sorted(merged)])
                committed[asin] = payload
            last_payload = payload
            record_progress(job, 'visual_design_kit_persisted', child=asin, input_revision=revision,
                provider=payload['planner']['provider'], ready_briefs=sum(row['status'] == 'ready' for row in snapshot['image_briefs']),
                total_briefs=len(snapshot['image_briefs']))

        try:
            source_paths = prepare_planning_references(job, source_manifest, trace_dir / "references", deadline_monotonic=child_deadline)
            source_paths += [resolve_job_owned_path(job, row["path"]) for row in design_refs]
            record_progress(job, "visual_design_kit_started", child=asin, input_revision=revision)
            plan_requests = min(2, 4 - budget.get('plan', 0))
            if not (cached_current or scoped_repair):
                if plan_requests <= 0:
                    return asin, None, [_failure(asin, 'Child planning attempt budget exhausted for this input revision; no request sent',
                                                 revision=revision, terminal=True)]
            response_text = json.dumps({
                "family_art_direction": cached["family_art_direction"],
                "image_briefs": [(row["draft"] or {"source_id": row["source_id"], 'role': row['role']}) if row["status"] == "pending" else _brief_draft(row) for row in cached["image_briefs"]],
            }) if cached_current or scoped_repair else gemini_stream_generate(
                prompt,
                source_paths,
                client_scope="visual_planning",
                timeout_seconds=60,
                attempts=1,
                total_timeout_seconds=90,
                deadline_monotonic=child_deadline,
                # One response and one bounded repair, within the shared resume budget.
                max_physical_requests=plan_requests,
                max_output_tokens=min(32768, max([min(24576, max(8192, 1200 * len(source_manifest))),
                    *(2 * int(row.get('max_output_tokens') or 0) for row in plan_limits)])),
                prior_output_limits=plan_limits,
                response_validator=validate_response,
                attempt_observer=record,
                request_id=plan_request_id,
            )
            raw_response_path = trace_dir / "provider_response.txt"
            raw_response_path.write_text(response_text, encoding="utf-8")
            planned = _finish_image_briefs(
                _parse_response(response_text), source_manifest=source_manifest,
                output_inventory=inventory,
                job=job, child=asin,
                product_claims=product_claims,
                category_id=plugin.category_id, main_policy=policy['main_image_policy'], source_paths=source_paths,
                source_originals=[resolve_job_owned_path(job, row['source_path']) for row in source_manifest],
                trace_dir=trace_dir, deadline_monotonic=child_deadline,
                cached=cached if cached_current or scoped_repair else None,
                design_references=design_refs,
                attempt_budget_path=budget_path,
                checkpoint=persist,
            )
            validate_visual_design_kit(
                planned,
                source_manifest=source_manifest,
                product_claims=product_claims,
                category_id=plugin.category_id,
                main_policy=policy['main_image_policy'],
                design_references=design_refs,
            )
            persist(planned)
            write_json(trace_dir / "reference_usage.json", design_reference_usage(job, design_refs, planned["image_briefs"]))
            try:
                write_json(trace_dir / "palette_diagnostics.json", planned_palette_diagnostics(planned["family_art_direction"]))
            except Exception as exc:
                record_progress(job, "palette_diagnostics_unavailable", child=asin, error=f"{type(exc).__name__}: {exc}"[:300])
            return asin, last_payload, []
        except Exception as exc:
            record_progress(job, "visual_design_kit_failed", child=asin, input_revision=revision, error=f"{type(exc).__name__}: {exc}"[:1000])
            return asin, last_payload, [_failure(asin, f"{type(exc).__name__}: {exc}", revision=revision,
                                         terminal=not (cached_current or scoped_repair) and budget.get('plan', 0) >= 4)]

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
                result[asin] = payload
            failures.extend(child_failures)

    return {
        "schema_version": VISUAL_DESIGN_KIT_SCHEMA_VERSION,
        "children": result,
        "tasks": list(result.values()),
        "failures": failures,
    }

def observation_corrections(design_kits: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Route local dependency gaps and bound model findings to the same observer."""
    corrections = {}
    for child, kit in design_kits.get('children', {}).items():
        sources = {row['source_id']: row for row in kit.get('source_references', [])}
        for brief in kit.get('image_briefs', []):
            if brief.get('status') != 'pending':
                continue
            if brief['source_id'] not in sources:
                continue
            for source_id, issues in required_observation_issues(
                    brief['draft'], sources[brief['source_id']], list(sources.values())).items():
                source = sources[source_id]
                correction = corrections.setdefault(child, {}).setdefault(source_id, {
                    'source_sha256': source['source_sha256'], 'source_revision': source['input_revision_id'], 'findings': []})
                for issue in issues:
                    finding = {'operation': 'source_text:' + source_id, 'status': 'inconclusive',
                               'resolution': 'correct_evidence', **issue}
                    if finding not in correction['findings']:
                        correction['findings'].append(finding)
            if not brief.get('design_review'):
                continue
            request = design_binding_request(brief['draft'], kit['family_art_direction'], source=sources[brief['source_id']],
                main_policy=kit['main_image_policy'], source_manifest=list(sources.values()), product_claims=kit['product_claims'], design_references=kit.get('approved_design_references', []))
            review = brief.get('design_review', {})
            if review.get('key') != request['key'] or review.get('policy') != CLAIM_REVIEW_POLICY or not review.get('response_sha256'):
                continue
            for finding in review.get('findings', []):
                operation = str(finding.get('operation', ''))
                if (finding.get('status') not in {'contradiction', 'inconclusive'} or review_failure_owner(finding) != 'observation' or not operation.startswith('source_product:')
                        or operation.split(':', 1)[1] not in {item['source_id'] for item in request['selected_evidence']}):
                    continue
                source_id = operation.split(':', 1)[1]
                source = sources[source_id]
                row = corrections.setdefault(child, {}).setdefault(source_id, {
                    'source_sha256': source['source_sha256'], 'source_revision': source['input_revision_id'], 'findings': []})
                bound = {**finding, 'review_key': review['key']}
                if bound not in row['findings']:
                    row['findings'].append(bound)
    return corrections


def _local_evidence_repair(job: Path, cached: dict[str, Any], sources: list[dict[str, Any]], *,
                           child_facts_revision: str, prompt: str, plugin: ProductPlugin,
                           facts: dict[str, Any], policy: dict[str, Any], design_refs: list[dict[str, Any]],
                           observation_revisions: dict[str, dict[str, Any]] | None = None) -> bool:
    """Rebind the current design after source-bound evidence corrections.

    Surviving pixels and child design inputs must remain unchanged. Unavailable
    sources stay blocked; recovered sources extend evidence without redesign.
    """
    if cached['child_facts_revision_id'] != child_facts_revision or not _planner_trace_current(job, cached):
        return False
    old = {row['source_id']: row for row in cached['source_references']}
    local_fields = {'input_revision_id', 'role', 'shopping_intent', 'claims', 'measurements'}
    for row in sources:
        if row['source_id'] not in old:
            continue
        before = old[row['source_id']]
        correction = (observation_revisions or {}).get(row['source_id'], {})
        fields = local_fields | ({'observation'} if correction.get('source_revision') == before['input_revision_id']
            and correction.get('source_sha256') == before['source_sha256'] and correction.get('findings') else set())
        if {k: v for k, v in row.items() if k not in fields} != {k: v for k, v in before.items() if k not in fields}:
            return False
    previous_prompt = visual_design_kit_prompt(plugin, facts, policy, cached['source_references'], design_refs, brand_design_brief(job), product_claims=cached['product_claims'], output_inventory=cached['output_inventory'])
    original = resolve_job_owned_path(job, cached['planner']['prompt_path']).read_text(encoding='utf-8')
    return previous_prompt == original and prompt != original


def _brief_draft(brief: dict[str, Any]) -> dict[str, Any]:
    draft = {key: brief[key] for key in ("role", "source_id", "image_direction")}
    if brief["role"].split('_', 1)[0] in {"func", "size"}:
        bindings = brief["display_copy_contract"]["bindings"]
        has_title = bool(brief["display_copy_contract"]["title"])
        draft["display_copy"] = {"title": bindings[0] if has_title else None, "labels": bindings[1:] if has_title else bindings}
    return draft


def _finish_image_briefs(
    raw: dict[str, Any], *, source_manifest: list[dict[str, Any]], category_id: str,
    output_inventory: list[dict[str, str]],
    main_policy: str = '',
    job: Path, child: str,
    product_claims: list[dict[str, Any]] = (),
    source_paths: list[Path], trace_dir: Path, deadline_monotonic: float,
    source_originals: list[Path],
    cached: dict[str, Any] | None,
    design_references: list[dict[str, Any]] | None = None,
    attempt_budget_path: Path | None = None,
    checkpoint: Any = None,
) -> dict[str, Any]:
    budget_path = attempt_budget_path or trace_dir / 'attempt_budget.json'
    budget = read_json(budget_path) if budget_path.is_file() else {}

    def settlement(kind: str) -> Any:
        initial = budget.get(kind, 0)
        def observe(event: dict[str, Any]) -> None:
            if event.get('event') == 'request_budget':
                budget[kind] = initial + event['physical_request_count']
                write_json(budget_path, budget)
            elif event.get('status') == 'output_limit':
                budget.setdefault('output_limits', {}).setdefault(event['request_id'], []).append(
                    {key: event.get(key) for key in ('provider', 'model', 'max_output_tokens', 'output_token_cap')})
                write_json(budget_path, budget)
        return observe

    reviews = {key: value for brief in (cached or {}).get("image_briefs", [])
               for key, value in brief.get("claim_reviews", {}).items()}
    reviews.update({brief["design_review"]["key"]: brief["design_review"]
                    for brief in (cached or {}).get("image_briefs", []) if brief.get("design_review")})
    sources = {source["source_id"]: source for source in source_manifest}

    def compile_reviewed(draft: dict[str, Any], attempt: str) -> dict[str, Any]:
        def settled() -> dict[str, Any]:
            compiled = compile_visual_design_kit_response(draft, source_manifest=source_manifest, output_inventory=output_inventory,
                category_id=category_id, main_policy=main_policy, product_claims=product_claims, claim_reviews=reviews,
                design_references=design_references)
            if checkpoint is not None:
                checkpoint(compiled)
            return compiled

        settled()
        valid = []
        inventory = {spec['role']: spec['source'] for spec in task_specs({}, source_manifest, inventory=output_inventory, include_optional=True)}
        for brief in draft['image_briefs']:
            if (not isinstance(brief, dict) or not isinstance(brief.get('role'), str)
                    or sum(isinstance(row, dict) and row.get('role') == brief.get('role')
                                                  for row in draft['image_briefs']) != 1):
                continue
            try:
                source = inventory.get(brief.get('role'))
                if not source or brief.get('source_id') != source['source_id']:
                    continue
                validate_image_brief_draft(brief, sources[brief['source_id']], draft['family_art_direction'], source_manifest, category_id, product_claims=product_claims, design_references=design_references)
                valid.append(brief)
            except ValueError:
                pass  # The same compiler retains these findings for the bounded local repair.
        all_requests = [*claim_review_requests({**draft, 'image_briefs': valid}, source_manifest, product_claims),
                        *(design_binding_request(brief, draft["family_art_direction"], main_policy=main_policy, source=sources[brief["source_id"]], source_manifest=source_manifest, product_claims=product_claims, design_references=design_references) for brief in valid)]
        for review_attempt in range(2):
            requests = {}
            for row in all_requests:
                previous = reviews.get(row['key'], {})
                if row['kind'] == 'design_binding':
                    findings = {finding['operation']: finding for finding in previous.get('findings', [])}
                    if any(finding['status'] != 'supported' and review_failure_owner(finding) != 'review' for finding in findings.values()):
                        continue
                    missing = [op for op in row['physical_operations'] if op not in findings or (
                        findings[op]['status'] == 'inconclusive' and review_failure_owner(findings[op]) == 'review')]
                    if missing:
                        requests[row['key']] = {**row, 'physical_operations': missing}
                elif not previous or (previous.get('status') == 'inconclusive' and review_failure_owner(previous) == 'review'):
                    requests[row['key']] = row
            requests = list(requests.values())
            if not requests or time.monotonic() >= deadline_monotonic:
                break
            if budget.get('review', 0) >= 4:
                break
            try:
                received = review_planning_bindings(requests,
                    source_manifest=source_manifest, source_paths=source_originals,
                    job=job, child=child, design_references=design_references or [],
                    trace_dir=trace_dir / (attempt if review_attempt == 0 else attempt + '_unresolved'), deadline_monotonic=deadline_monotonic,
                    attempt_observer=settlement('review'),
                    prior_output_limits=budget.get('output_limits', {}).get(f'claim-review:{input_revision_id(requests)}', []))
                for key, value in received.items():
                    findings = {finding['operation']: finding for finding in reviews.get(key, {}).get('findings', [])}
                    findings.update({finding['operation']: finding for finding in value.get('findings', [])})
                    reviews[key] = {**value, 'findings': list(findings.values())}
                settled()
            except (VisionRequestError, TimeoutError, ConnectionError) as exc:
                (trace_dir / 'planning_review_error.txt').write_text(f'Planning review unavailable: {type(exc).__name__}: {exc}', encoding='utf-8')
                transient = not isinstance(exc, VisionRequestError) or exc.failure_kind in {
                    'timeout_failure', 'transport_failure', 'server_failure', 'queue_unavailable',
                    'rate_limit_failure', 'output_limit', 'json_syntax'}
                if not transient or review_attempt == 1 or time.monotonic() >= deadline_monotonic:
                    break
                time.sleep(min(.25, max(0, deadline_monotonic - time.monotonic())))
        return settled()

    planned = compile_reviewed(raw, "initial")
    pending = [row for row in planned["image_briefs"] if row["status"] == "pending" and row['failure_owner'] in {'brief', 'shared_design'}]
    if not pending or time.monotonic() >= deadline_monotonic:
        return planned
    if budget.get('repair', 0) >= 2:
        return planned
    shared_values = shared_design_values(planned['family_art_direction'])
    shared_paths = sorted({finding['operation'].split(':', 1)[1] for row in pending
                            for finding in row['design_review'].get('findings', [])
                            if finding.get('status') in {'contradiction', 'inconclusive'} and review_failure_owner(finding) == 'shared_design'
                            and str(finding.get('operation', '')).startswith('shared_design:')
                            and finding['operation'].split(':', 1)[1] in shared_values})
    pending_drafts = [{**row['draft'], 'role': row['role'], 'source_id': row['source_id']} for row in pending]
    # Scope edits to pending roles, not evidence to the references that caused the failure.
    repair_evidence, repair_claims = _planner_evidence(source_manifest, product_claims)
    prompt = (
        "Repair the listed output image briefs. Return JSON {image_briefs:[...]}, one replacement for each listed role. "
        "Keep source_id evidence anchors unchanged. Choose any verified same-child product_sources and measurement_ids needed for this output. "
        + ("Also return shared_design_repairs as {exact_leaf_path:replacement_text} for exactly the listed paths; "
           "null removes an incorrectly defined palette component and its ID from repaired presentation.components. All other shared values remain unchanged. "
           if shared_paths else "Keep shared design unchanged. ")
        +
        "Use the original brief schema; preserve complete claim objects, counts and qualifiers. "
        "Preserve the child design and necessary specific product features and claim qualifiers; the image model owns composition. "
        "Do not redesign unaffected parts of the child or change other output briefs.\n"
        + json.dumps({"shared_design": planned["family_art_direction"], "pending": [
                          {**{key: row[key] for key in ('role', 'source_id', 'error')}, 'draft': draft}
                          for row, draft in zip(pending, pending_drafts)],
                      "shared_paths_to_repair": {path: shared_values[path] for path in shared_paths},
                      "claim_review_findings": [{"source_id": row['source_id'], "proposed_text": row['proposed_text'],
                                                 "review": reviews.get(row["key"], {})}
                          for row in claim_review_requests({"image_briefs": pending_drafts}, source_manifest, product_claims)],
                      "design_review_findings": [{"source_id": row['source_id'], 'role': row['role'], 'review': row['design_review']}
                          for row in pending if row['design_review']],
                      "source_evidence": repair_evidence,
                      "evidence_attachments": planning_reference_inputs(source_manifest),
                      "design_references": _planner_design_refs(design_references or [], len(planning_reference_inputs(source_manifest))),
                      "claim_texts": repair_claims,
                      "schemas": [_brief_schema_for_output(row) for row in pending]}, ensure_ascii=False)
    )
    (trace_dir / "brief_repair_request.txt").write_text(prompt, encoding="utf-8")

    def validate_repair(text: str) -> bool:
        value = _parse_response(text)
        if set(value) != ({'image_briefs', 'shared_design_repairs'} if shared_paths else {'image_briefs'}):
            raise VisualDesignKitError('local repair returned fields outside the current repair contract')
        if shared_paths:
            edits = value['shared_design_repairs']
            if not isinstance(edits, dict) or set(edits) != set(shared_paths):
                raise VisualDesignKitError('local repair changed unreported shared paths')
            if any(not (isinstance(text, str) and text.strip()) and not (text is None and path.startswith('palette_direction.'))
                   for path, text in edits.items()):
                raise VisualDesignKitError('Shared repair must replace leaf text or remove a palette component')
        if not isinstance(value.get("image_briefs"), list):
            raise VisualDesignKitError("local brief repair requires an image_briefs list")
        return True

    try:
        _, record_repair = _attempt_trace(trace_dir / 'brief_repair_attempts.json', observer=settlement('repair'))
        repair_id = f'brief-local-repair:{input_revision_id(pending)}'
        repair_limits = budget.get('output_limits', {}).get(repair_id, [])
        response = gemini_stream_generate(
            prompt, source_paths, client_scope="visual_planning", attempts=1,
            max_physical_requests=1,
            deadline_monotonic=deadline_monotonic, response_validator=validate_repair,
            attempt_observer=record_repair,
            request_id=repair_id, prior_output_limits=repair_limits,
            max_output_tokens=min(32768, max([8192, *(2 * int(row.get('max_output_tokens') or 0) for row in repair_limits)])),
        )
        (trace_dir / "brief_repair_response.txt").write_text(response, encoding="utf-8")
        validate_repair(response)
        payload = _parse_response(response)
        art = deepcopy(planned['family_art_direction'])
        for path, text in payload.get('shared_design_repairs', {}).items():
            parts = path.split('.')
            target = art
            for part in parts[:-1]:
                target = target[int(part)] if isinstance(target, list) else target[part]
            if text is None:
                del target[parts[-1]]
                if not target:
                    del art['palette_direction'][parts[1]]
            else:
                target[int(parts[-1]) if isinstance(target, list) else parts[-1]] = text
        pending_roles = {row['role'] for row in pending}
        # Compile the latest rows even when invalid: failed repairs must not revive older drafts/errors.
        replacements = [row for row in payload['image_briefs'] if isinstance(row, dict)
                        and isinstance(row.get('role'), str) and row['role'] in pending_roles]
        replacement = {"family_art_direction": art, "image_briefs": [
            *[row for row in raw["image_briefs"] if not isinstance(row, dict) or not isinstance(row.get('role'), str)
              or row['role'] not in pending_roles], *replacements,
        ]}
        return compile_reviewed(replacement, "repaired")
    except Exception as exc:
        (trace_dir / "brief_repair_error.txt").write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
        return planned


def read_visual_design_kits(job_dir: str | Path, *, plugin: ProductPlugin | None = None) -> dict[str, Any]:
    path = Path(job_dir) / "reports" / VISUAL_DESIGN_KIT_ARTIFACT
    if not path.is_file():
        raise VisualDesignKitError(f"VisualDesignKitV15 is missing: {path}")
    rows = read_jsonl(path)
    category_id = plugin.category_id if plugin is not None else ""
    for row in rows:
        validate_visual_design_kit_row(row, category_id)
        if not _planner_trace_current(Path(job_dir).resolve(), row):
            raise VisualDesignKitError(f"VisualDesignKitV15 planner trace is missing or changed: {row.get('child')}")
    children = {str(row["child"]): row for row in rows}
    if len(children) != len(rows):
            raise VisualDesignKitError("VisualDesignKitV15 has duplicate child rows")
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
            and all(brief.get("status") == "ready" for brief in artifact["children"][asin]["image_briefs"])
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
        if not sources:
            return False
        policy = policy or compiled_image_policy(plugin)
        source_manifest = _source_manifest(sources, job=job)
        product_claims = compact_product_claims(child_row)
        prompt = visual_design_kit_prompt(
            plugin, compact_product_facts(child_row), policy, source_manifest, approved_design_references(job, child), brand_design_brief(job),
            product_claims=product_claims,
            output_inventory=row['output_inventory'],
        )
        expected_revision, expected_child_facts = _kit_input_revision(
            child=child_row, policy=policy, sources=sources, planner_prompt=prompt,
        )
        if ([design_reference_semantics(ref) for ref in row['approved_design_references']]
                != [design_reference_semantics(ref) for ref in approved_design_references(job, child)]):
            return False
        if row.get("source_references") != source_manifest or row['product_claims'] != product_claims:
            return False
        if row.get("child_facts_revision_id") != expected_child_facts or row['main_image_policy'] != policy['main_image_policy']:
            return False
        return row.get("input_revision_id") == expected_revision
    except Exception:
        return False

def resolve_visual_design_kit(artifact: dict[str, Any], child: str) -> dict[str, Any]:
    row = (artifact.get("children") or {}).get(str(child))
    if not isinstance(row, dict):
        raise VisualDesignKitError(f"VisualDesignKitV15 child is missing: {child}")
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
        if has_bad_encoding(text) or key in seen:
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


def visual_design_kit_prompt(plugin: ProductPlugin, facts: dict[str, Any], policy: dict[str, Any], source_manifest: list[dict[str, Any]], design_references: list[dict[str, Any]] | None = None, brand_brief: dict[str, Any] | None = None, *, output_inventory: list[dict[str, str]], product_claims: list[dict[str, Any]] = ()) -> str:
    # One response grammar, not a duplicate schema for every gallery image.
    outputs = [{'role': spec['role'], 'source_id': (spec['source'] or {}).get('source_id', ''), 'evidence_gap': spec['reason']}
               for spec in task_specs({}, source_manifest, inventory=output_inventory, include_optional=True)]
    expected_briefs = [_brief_schema_for_output({"source_id": "anchor from output inventory", "role": "func"})]
    response_schema = {
        "family_art_direction": {
            "audience_and_market": "evidence-supported US buyer, use and emotional goal; no styling, price or age assumptions",
            "palette_direction": {"room": {"wall": "one #RRGGBB, material, pattern or solid"},
                                  "bedding": {"duvet": "one #RRGGBB, material, pattern or solid"}},
            "photography_direction": "bright clear exposure retaining product edges, balanced white balance, contrast and material clarity; no room, window or prop instructions",
            "environment_and_staging": "believable US room type, spatial needs and atmosphere; no component colors or prop inventory",
            **DESIGN_FIELD_SCHEMAS,
        },
        "image_briefs": expected_briefs,
    }
    evidence, claim_texts = _planner_evidence(source_manifest, product_claims)
    attachments = planning_reference_inputs(source_manifest)
    # Keep planner context useful but bounded; the same context is projected
    # again into role prompts, so repeating the full policy here adds noise.
    visual_context_guardrail = planner_visual_context_instruction(policy, max_chars=420)
    return (
        "Return JSON for one Amazon child. The program supplies verified facts and process; you plan the child-wide visual direction. "
        "The GPT image model designs each composition, room arrangement, lighting placement and information layout within that direction.\n\n"
        "Appearance attachments identify the product's form, color and material, not its decorative styling. Plan from this product, "
        "its evidenced users, use and US market. Ordinary source bedding, rooms and graphics are not a design brief. "
        "Other observed views remain in the fact catalog for function and measurement bindings; their original pixels go to editing and factual review. "
        "Preserve the sold product's geometry, finish, parts and quantity; use evidenced mechanisms and states, not invented hidden structure.\n\n"
        + (visual_context_guardrail + "\n\n" if visual_context_guardrail else "")
        + "OUTPUT IMAGE BRIEFS\n"
        "Return one brief per output role, retaining role and source_id from the inventory. Multiple roles may share a source; "
        "retain every output slot. visual_goal states the buyer question, not a second appearance specification or preset layout. "
        "Main follows category policy and uses reliable complete product evidence. presentation states the intended product use/demonstration, "
        "including real physical support or installation, not source staging. whole_product needs a same-child complete product reference; "
        "detail_only stays close-up without inventing a full hero. Scene goals serve the evidenced audience; "
        "func goals communicate specific proven features rather than generic benefits.\n"
        "product_sources lists the original same-child images to attach: first choose a clean/simple edit photograph when available; "
        "add other sources only for necessary product evidence absent there. Their facts are authoritative, not their layouts, graphics or decor. "
        "measurement_ids selects exact source_id:measurement_id facts this output communicates, independent of the edit photograph. "
        "Size requires real measurements; func may use [] when its feature needs no numeric annotation. Selected measurement originals are attached automatically. "
        "Do not reproduce optional source numbers merely because they exist; never invent or discard the qualifiers of a selected fact.\n"
        "design_transfer selects role-approved references within their transfer_principles: inherit only permitted features and explain adaptations. A reference approval is scoped, not permission to copy its whole style. Use [] without suitable references: autonomous, not reference-calibrated.\n"
        "Each instruction has one owner: product facts own product finish; measurements own numeric labels; display_copy owns exact authored text; "
        "palette_direction owns core non-product appearance; typography owns font language; graphic_direction owns graphic colors. "
        "Other fields reference these choices without repeating them.\n"
        "Replace the palette example with applicable groups: room for architecture and functional groups such as bedding or bath. "
        "Each leaf defines exactly one component with one hex, material and pattern. Include major cover and sleeping pillowcases when applicable. "
        "presentation.components selects only core component IDs used in this image; [] suits exposed measurement details. "
        "Select bedding for normal bed use, not exposed measurements or hidden mechanism demonstrations. The image model designs secondary decor. "
        "designed_environment uses the room direction; graphic_canvas is technical without room staging; source_setting preserves necessary installation relationships only. "
        "Keep graphic inks and the user backing boundary coherent; the image model designs sizing, line breaks and symbols.\n"
        "For func/size, display_copy owns exact titles and captions: title may be null, labels may be empty. Bind each string to evidence IDs from this child's catalog, including other sources; the output anchor does not restrict fact scope. physical: proves visible structure only, not material/performance; measurement: supports measured-object headings. Numeric annotations belong to measurement authority, not duplicate copy. Cover distinctive proven mechanisms across the gallery, with their counts and qualifiers; omit repeated generic praise.\n\n"
        "Source-colored outlines, adjustment ghosts and highlights are diagram notation, not finish or extra physical parts. Size preserves quantities and measurement associations; program-approved US-unit labels replace metric labels.\n\n"
        f"Category: {plugin.category_id}\n"
        f"Product type: {plugin.display_name}\n"
        f"Product identity: {json.dumps(_planner_product_identity(facts), ensure_ascii=False, separators=(',', ':'))}\n"
        f"User brand design brief (not product facts): {json.dumps(brand_brief or {}, ensure_ascii=False)}\n"
        f"Fact text catalog (each text once; all source evidence IDs retained): {json.dumps(claim_texts, ensure_ascii=False, separators=(',', ':'))}\n"
        f"Final source intents: {json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))}\n"
        f"Output inventory: {json.dumps(outputs, separators=(',', ':'))}\n"
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
    main_policy: str = '',
    product_claims: list[dict[str, Any]] = (),
    design_references: list[dict[str, Any]] | None = None,
) -> None:
    try:
        validate_compiled_visual_design_kit(
            data, source_manifest=source_manifest, category_id=category_id, main_policy=main_policy, product_claims=product_claims, design_references=design_references,
        )
    except VisualDesignKitCompileError as exc:
        raise VisualDesignKitError(str(exc)) from exc

def validate_visual_design_kit_row(row: Any, category_id: str = "") -> None:
    if not isinstance(row, dict) or row.get("schema_version") != VISUAL_DESIGN_KIT_SCHEMA_VERSION:
        raise VisualDesignKitError("Invalid VisualDesignKitV15 row")
    if row.get("policy_version") != VISUAL_DESIGN_KIT_POLICY_VERSION:
        raise VisualDesignKitError("VisualDesignKitV15 policy mismatch")
    if set(row) != _ROW_FIELDS:
        raise VisualDesignKitError("VisualDesignKitV15 row fields do not match the current contract")
    for key in ("category_id", "child", "source_reference", "source_sha256", "child_facts_revision_id", "input_revision_id", "family_design_id", "visual_design_kit_id"):
        _validate_text(row[key], key, maximum=500)
    if category_id and row["category_id"] != category_id:
        raise VisualDesignKitError("VisualDesignKitV15 category mismatch")
    if row['main_image_policy'] not in {'white_background', 'product_first_lifestyle'}:
        raise VisualDesignKitError('VisualDesignKit main policy snapshot is invalid')
    sources = row["source_references"]
    _validate_source_manifest(sources)
    claims = row['product_claims']
    if (not isinstance(claims, list) or any(not isinstance(claim, dict)
            or set(claim) != {'evidence_id', 'field_path', 'text', 'type'}
            or not all(isinstance(claim[key], str) and claim[key].strip() for key in claim) for claim in claims)
            or len({claim['evidence_id'] for claim in claims}) != len(claims)):
        raise VisualDesignKitError('Child product facts must have unique, complete source bindings')
    validate_visual_design_kit(
        {
            "family_art_direction": row["family_art_direction"],
            "image_briefs": row["image_briefs"],
            "output_inventory": row['output_inventory'],
        },
        source_manifest=sources,
        product_claims=claims,
        category_id=category_id or str(row.get("category_id") or ""),
        main_policy=row['main_image_policy'],
        design_references=row["approved_design_references"],
    )
    anchor = task_specs({}, sources, inventory=row['output_inventory'], include_optional=True)[0]['source'] or sources[0]
    if row["source_reference"] != anchor["source_path"] or row["source_sha256"] != anchor["source_sha256"]:
        raise VisualDesignKitError("VisualDesignKit evidence reference binding is inconsistent")
    expected_family = input_revision_id(row["family_art_direction"])
    if row["family_design_id"] != expected_family:
        raise VisualDesignKitError("VisualDesignKitV15 family art direction changed")
    expected_kit = input_revision_id({
        "family_design_id": expected_family,
        "main_image_policy": row['main_image_policy'],
        "source_references": sources,
        "product_claims": claims,
        "approved_design_references": row["approved_design_references"],
        "image_briefs": row["image_briefs"],
        "output_inventory": row['output_inventory'],
    })
    if row["visual_design_kit_id"] != expected_kit:
        raise VisualDesignKitError("VisualDesignKitV15 source briefs changed")
    planner = row["planner"]
    if not isinstance(planner, dict) or set(planner) != _PLANNER_FIELDS or not str(planner.get("provider") or "").strip() or not str(planner.get("model") or "").strip():
        raise VisualDesignKitError("VisualDesignKitV15 planner provenance is incomplete")
    expected_response = input_revision_id({
        "family_art_direction": row["family_art_direction"],
        "image_briefs": row["image_briefs"],
        "output_inventory": row['output_inventory'],
    })
    if planner["response_fingerprint"] != expected_response:
        raise VisualDesignKitError("VisualDesignKitV15 planner response fingerprint changed")

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
        "product_claims": compact_product_claims(child),
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


def _source_manifest(rows: list[dict[str, Any]], *, job: Path) -> list[dict[str, Any]]:
    manifest = []
    for row in rows:
        manifest.append({
            "source_id": f"source_{int(row.get('source_index') or 0):02d}",
            "source_index": int(row.get("source_index") or 0),
            "role": str(row.get("role") or ""),
            "source_path": str(row.get("source_path") or ""),
            "source_sha256": str(row.get("source_sha256") or ""),
            "input_revision_id": str(row.get("input_revision_id") or ""),
            "shopping_intent": row.get("shopping_intent") or "",
            "claims": row.get("claims") or [],
            "measurements": row.get("measurements") or [],
            "observation": {key: (row.get("visual_evidence") or {}).get(key) for key in ("status", "objects", "product_features", "product_extent", "reference_purposes", "evidence_gaps", "text_gaps", "measurement_issues")},
        })
    _validate_source_manifest(manifest)
    return manifest


def _validate_source_manifest(rows: Any) -> None:
    if not isinstance(rows, list) or not rows:
        raise VisualDesignKitError("source_references must be a non-empty list")
    ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != _SOURCE_FIELDS:
            raise VisualDesignKitError(f"source_references[{index}] is malformed")
        if row["source_id"] in ids:
            raise VisualDesignKitError("source_references contain duplicate source IDs")
        ids.add(row["source_id"])
        product_features(row.get("observation") or {})
        if row["role"] not in PLANNING_SOURCE_ROLES:
            raise VisualDesignKitError(f"source_references[{index}] has unsupported role")
        for key in ("source_id", "source_path", "source_sha256", "input_revision_id"):
            _validate_text(row[key], f"source_references[{index}].{key}", maximum=1000)
        if not isinstance(row["source_index"], int) or row["source_index"] < 0:
            raise VisualDesignKitError(f"source_references[{index}].source_index is invalid")
        if (
            not isinstance(row["claims"], list)
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
def _planner_evidence(sources: list[dict[str, Any]], product_claims: list[dict[str, Any]] = ()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence = [_planner_source_view(row) for row in sources]
    texts: dict[str, list[str]] = {}
    for row in product_claims:
        texts.setdefault(row['text'], []).append(row['evidence_id'])
    for source, view in zip(sources, evidence):
        local = view.pop('source_supported_claims', [])
        view['source_supported_claim_ids'] = [row['evidence_id'] for row in local]
        for row in local:
            ids = texts.setdefault(row['text'], [])
            if row['evidence_id'] not in ids:
                ids.append(row['evidence_id'])
    return evidence, [{'evidence_ids': ids, 'text': text} for text, ids in texts.items()]


def _planner_source_view(row: dict[str, Any]) -> dict[str, Any]:
    source_id = row['source_id']
    observation = row['observation']
    features = product_features(observation)
    facts = _available_claims([row], [])
    objects = {feature['object_id'] for feature in features}
    view = {
        "source_id": source_id,
        "role": row["role"],
        "objects": [{key: obj[key] for key in ('object_id', 'kind', 'sale_membership', 'visibility', 'state')}
                    for obj in observation['objects'] if obj['object_id'] in objects],
        "product_extent": observation['product_extent'],
        "reference_purposes": observation['reference_purposes'],
        'evidence_gaps': observation['evidence_gaps'],
        'text_gaps': observation['text_gaps'],
        "source_supported_claims": [{'evidence_id': key, 'text': value} for key, value in facts.items()],
    }
    if row.get("measurements"):
        view["measurements"] = [{'evidence_id': f'measurement:{source_id}:{i}',
                                 'measurement_id': source_id + ':' + item['source_occurrence'],
                                 **{key: item.get(key) for key in ("text", "source_label", "axis_hint")}}
                                for i, item in enumerate(row["measurements"])]
    return view


def _brief_schema_for_output(source: dict[str, Any]) -> dict[str, Any]:
    role = source["role"].split('_', 1)[0]
    common: dict[str, Any] = {
        "source_id": source["source_id"],
        'role': source['role'],
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
    def response_record(evidence: dict[str, Any], key: str) -> dict[str, Any]:
        if Path(str(evidence.get('response_path') or '')).is_absolute():
            raise ValueError('Review trace must be job-relative')
        path = resolve_job_owned_path(job, str(evidence.get('response_path') or ''))
        if not path.is_file() or file_sha256(path) != evidence.get('response_sha256'):
            raise ValueError('Review trace is missing or changed')
        records = [item for item in _parse_response(path.read_text(encoding='utf-8')).get('reviews', [])
                   if isinstance(item, dict) and item.get('key') == key]
        if len(records) != 1:
            raise ValueError('Review trace identity is ambiguous')
        return records[0]
    try:
        request = resolve_job_owned_path(job, str(planner.get("prompt_path") or ""))
        response = resolve_job_owned_path(job, str(planner.get("response_path") or ""))
        if not request.is_file() or not response.is_file():
            return False
        if file_sha256(request) != str(planner.get("request_fingerprint") or ""):
            return False
        for brief in row.get("image_briefs", []):
            checks = [*brief.get("claim_reviews", {}).values()]
            if brief.get("design_review"):
                checks.append(brief["design_review"])
            for review in checks:
                original = response_record(review, review['key'])
                fields = ('reason',) if review is brief.get('design_review') else ('reason', 'status', 'resolution')
                if any(original.get(key) != review.get(key) for key in fields):
                    return False
                for finding in review.get('findings', []):
                    original = response_record(finding, review['key'])
                    matches = [item for item in original.get('findings', []) if isinstance(item, dict)
                               and item.get('operation') == finding.get('operation')]
                    if len(matches) != 1 or any(matches[0].get(key) != finding.get(key) for key in ('status', 'reason', 'resolution', 'fact_ids')):
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
