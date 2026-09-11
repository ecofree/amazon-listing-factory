from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .visual_semantics import observe_candidate, candidate_view_targets
from .candidate_state import CandidateStateError, current_candidate
from .image_pixel_evidence import inspect_image_pixel_evidence
from .image_provider_common import ProviderQueueUnavailable
from .vision_errors import VisionRequestError
from .vision_gemini_client import vision_scope_capacity
from .image_task_inputs import task_renderable_text
from .image_prompt_compiler import prompt_for_task, read_image_prompts, require_current_image_branch
from .io import load_env
from .job import load_job
from .plugin import ProductPlugin
from .paths import resolve_job_owned_path
from .progress_trace import record_progress
from .qa_evidence import (
    QA_EVIDENCE_ARTIFACT,
    QA_EVIDENCE_SCHEMA_VERSION,
    evidence_fingerprint,
    evidence_is_current,
    qa_policy_id,
    read_qa_evidence,
    write_qa_evidence,
)
from .required_role_policy import main_image_policy
from .image_task_inputs import release_candidate_fingerprint
from .image_tasks import read_image_tasks
from .run_scope import scoped_child_set
from .status import input_revision_id, logical_task_id
from .text_evidence import extract_measurements, normalize_text, measurement_values_match, numeric_signature


def run_image_qa(
    *, job_dir: str | Path, plugin: ProductPlugin, config_path: str = "",
    workers: int = 2, limit: int = 0,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    job = Path(job_dir).resolve()
    for path in (config_path, str(load_job(job).get("config_path") or "")):
        if path:
            load_env(path, override=False)
    del limit
    require_current_image_branch(job, plugin)
    selected = scoped_child_set(job)
    prompts = read_image_prompts(job, category_id=plugin.category_id)
    tasks = read_image_tasks(job, category_id=plugin.category_id)["tasks"]
    ready_tasks = [
        task for task in tasks if task["formation_status"] == "ready" and task["child"] in selected
    ]
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    candidate_failures: list[dict[str, Any]] = []
    for task in ready_tasks:
        prompt = prompt_for_task(prompts, task)
        try:
            candidate = current_candidate(job, task)
        except CandidateStateError as exc:
            candidate_failures.append(_candidate_state_failure(task, exc))
            continue
        if isinstance(candidate, dict) and candidate and candidate.get("task_prompt_fingerprint") == prompt["prompt_sha256"]:
            pairs.append((task, candidate))
    existing: dict[tuple[str, str, str], dict[str, Any]] = {}
    qa_evidence_path = job / "reports" / QA_EVIDENCE_ARTIFACT
    if qa_evidence_path.is_file():
        try:
            existing = {(row["child"], row["role"], row["candidate_sha256"]): row for row in read_qa_evidence(job)}
        except Exception as exc:
            record_progress(
                job,
                "qa_evidence_cache_rejected",
                error=f"{type(exc).__name__}: {exc}"[:1000],
            )
    else:
        record_progress(job, "qa_evidence_cache_miss")

    def evaluate(task: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        cached = existing.get((task["child"], task["role"], candidate["candidate_sha256"]))
        if cached and evidence_is_current(cached, task, candidate, job_dir=job) and (
            cached.get("candidate_observation") or cached["automatic_decision"] == "fail"
        ):
            return cached
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            raise TimeoutError("QA execution deadline exhausted before evaluation")
        return _evaluate(job, plugin, task, candidate, deadline_monotonic=deadline_monotonic)

    rows: list[dict[str, Any]] = []
    evaluation_failures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers or 1), len(pairs) or 1, vision_scope_capacity("vision_qa")))) as pool:
        futures = {pool.submit(evaluate, task, candidate): (task, candidate) for task, candidate in pairs}
        for future in as_completed(futures):
            task, candidate = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                evaluation_failures.append({
                    "task": {
                        "logical_task_id": logical_task_id("qa", child=task["child"], role=task["role"]),
                        "input_revision_id": input_revision_id({"task": task.get("task_fingerprint"), "candidate": candidate.get("candidate_sha256"), "qa_error": type(exc).__name__}),
                        "child": task["child"], "role": task["role"],
                    },
                    "failure_owner": "qa", "task_status": "retryable", "error_code": "qa_not_executed_capacity" if isinstance(exc, ProviderQueueUnavailable) else "qa_evaluator_error",
                    "error": f"{type(exc).__name__}: {exc}",
                })
    rows.sort(key=lambda row: (row["child"], row["role"]))
    kept = {**existing, **{(row["child"], row["role"], row["candidate_sha256"]): row for row in rows}}
    write_qa_evidence(job, list(kept.values()))
    records = [
        {
            "logical_task_id": logical_task_id("qa", child=row["child"], role=row["role"]),
            "input_revision_id": input_revision_id({"evidence": row["evidence_fingerprint"], "qa_policy": row["qa_policy_id"]}),
            "child": row["child"], "role": row["role"], "status": "success",
        }
        for row in rows if row.get('observation_status') != 'unavailable'
    ]
    observation_failures = [{
        'task': {'logical_task_id': logical_task_id('qa', child=row['child'], role=row['role']),
                 'input_revision_id': input_revision_id({'evidence': row['evidence_fingerprint'], 'qa_policy': row['qa_policy_id']}),
                 'child': row['child'], 'role': row['role']},
        'failure_owner': 'qa', 'task_status': 'retryable', 'error_code': 'qa_observer_unavailable',
        'error': next((g['evidence'] for g in row['gates'] if g['gate'] == 'product_fidelity'), 'QA observer unavailable'),
    } for row in rows if row.get('observation_status') == 'unavailable']
    failures = candidate_failures + evaluation_failures + observation_failures
    records.extend({
        "logical_task_id": item["task"]["logical_task_id"],
        "input_revision_id": item["task"]["input_revision_id"],
        "child": item["task"]["child"], "role": item["task"]["role"],
        "status": item["task_status"], "error_code": item["error_code"],
    } for item in failures)
    return {"tasks": records, "failures": failures, "qa": rows}


def _candidate_state_failure(task: dict[str, Any], exc: CandidateStateError) -> dict[str, Any]:
    return {
        "task": {
            "logical_task_id": logical_task_id("qa", child=task["child"], role=task["role"]),
            "input_revision_id": input_revision_id({
                "task": task.get("task_fingerprint"),
                "reason": "candidate_manifest_invalid_before_qa",
                "candidate_error": str(exc),
            }),
            "child": task["child"], "role": task["role"],
        },
        "failure_owner": "generation",
        "task_status": "blocked",
        "error_code": "candidate_manifest_invalid_before_qa",
        "error": f"CandidateStateError: {exc}",
    }


def _evaluate(job: Path, plugin: ProductPlugin, task: dict[str, Any], candidate: dict[str, Any], *, deadline_monotonic: float | None = None) -> dict[str, Any]:
    output = resolve_job_owned_path(job, str(candidate["candidate_path"]))
    gates = _local_gates(job, plugin, task, output)
    observation = {}
    if not any(row["status"] == "fail" for row in gates):
        try:
            observation = observe_candidate(job, task, candidate, deadline_monotonic=deadline_monotonic)
            semantic = _semantic_gates(task, observation)
            gates = [row for row in gates if row["gate"] not in {"unauthorized_text", "dimension_accuracy"}] + semantic
        except Exception as exc:
            if isinstance(exc, ProviderQueueUnavailable) or (isinstance(exc, VisionRequestError) and exc.failure_kind == "queue_unavailable" and exc.metadata.get("physical_request_count") == 0):
                raise ProviderQueueUnavailable("vision_qa", "QA not executed: vision capacity unavailable; candidate retained") from exc
            gates.append(_gate("product_fidelity", "inconclusive", f"Independent observation unavailable: {type(exc).__name__}: {exc}"))
    statuses = {row["status"] for row in gates}
    decision = "fail" if "fail" in statuses else "inconclusive" if "inconclusive" in statuses else "pass"
    evidence = {
        "schema_version": QA_EVIDENCE_SCHEMA_VERSION,
        "child": task["child"], "role": task["role"],
        "candidate_path": candidate["candidate_path"], "candidate_sha256": candidate["candidate_sha256"],
        "release_candidate_fingerprint": release_candidate_fingerprint(task, candidate),
        "qa_policy_id": qa_policy_id(task), "automatic_decision": decision,
        "decision_scope": "observed_hard_facts_only",
        "candidate_observation": observation,
        "observation_status": "completed" if observation else "not_needed" if decision == "fail" else "unavailable",
        "quality_authority": "human_review_and_provider_ledger",
        "automatic_pass": decision == "pass", "failure_owner": "qa" if decision == "fail" else "",
        "provider": observation.get("provider") or {"provider": "unavailable", "model": "unavailable", "protocol": "unavailable"},
        "gates": gates,
        "human_review_checklist": _human_checklist(task),
    }
    evidence["evidence_fingerprint"] = evidence_fingerprint(evidence)
    return evidence


def _local_gates(job: Path, plugin: ProductPlugin, task: dict[str, Any], output: Path) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    try:
        from .imagegen_artifacts import assert_image_output
        assert_image_output(output)
        gates.append(_gate("image_integrity", "pass", "candidate decodes and has a non-solid production canvas"))
    except Exception as exc:
        gates.append(_gate("image_integrity", "fail", f"{type(exc).__name__}: {exc}"))
        return gates
    gates.append(_main_background_gate(plugin, task, output))
    if gates[-1]["status"] == "fail":
        return gates
    return gates


def _main_background_gate(plugin: ProductPlugin, task: dict[str, Any], output: Path) -> dict[str, Any]:
    if task["role_family"] != "main":
        return _gate("main_background", "pass", "not a main-image task")
    pixel = inspect_image_pixel_evidence(output)
    white = bool(pixel.get("white_background"))
    if main_image_policy(plugin) == "product_first_lifestyle":
        return _gate(
            "main_background",
            "pass",
            "edge-connected pixels look white; lifestyle context needs human review"
            if white else "non-white lifestyle canvas detected",
            warning=white,
        )
    if white:
        return _gate("main_background", "pass", "edge-connected white external canvas detected; sparse functional props remain a human review item")
    return _gate("main_background", "fail", "required white external canvas is absent")


def _semantic_gates(task: dict[str, Any], observation: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = task_renderable_text(task)
    texts = observation["texts"]
    authored = [row["text"] for row in texts if row["kind"] in {"marketing", "measurement"} and row["confidence"] >= 0.9]
    unknown = [row["text"] for row in texts if row["kind"] in {"unknown", "brand", "product_label"} or row["confidence"] < 0.9]
    marketing = [row["text"] for row in texts if row["kind"] == "marketing" and row["confidence"] >= 0.9]
    has_diagram = (task.get("measurement_authority") or {}).get("mode") == "source_image"
    factual_copy = (task.get("measurement_authority") or {}) if has_diagram else {}
    permitted = allowed + list(factual_copy.get("render_text") or []) + list(factual_copy.get("source_visible_callouts") or [])
    unexpected = _unsupported_contract_lines(marketing if has_diagram else authored, permitted)
    observed_phrases = authored + [" ".join(authored[start:stop])
                                  for start in range(len(authored))
                                  for stop in range(start + 2, min(len(authored), start + 3) + 1)]
    missing = _unsupported_contract_lines(allowed, observed_phrases)
    if unexpected:
        text_gate = _gate("unauthorized_text", "fail", f"Located unapproved authored copy: {unexpected}")
    elif unknown or observation["text_coverage"] != "complete" or missing:
        text_gate = _gate("unauthorized_text", "inconclusive", f"Unverified text/brand ownership: {unknown}; approved strings not fully observed: {missing}")
    else:
        text_gate = _gate("unauthorized_text", "pass", "Located approved copy matches; ordinary prop text is not an authored product claim")

    dimensions = observation["measurements"]
    groups = {r['id']: r for r in (task.get('measurement_authority') or {}).get('measurement_groups', [])}
    expected_ids = set(groups)
    observed_ids = [r.get('measurement_id') for r in dimensions if r.get('measurement_id')]
    unbound = bool(set(observed_ids) != expected_ids or len(observed_ids) != len(set(observed_ids)))
    if expected_ids and any(not extract_measurements(row['candidate_text']) for row in dimensions):
        unbound = True
    wrong = [row for row in dimensions if row["confidence"] >= 0.9 and (
        row["relationship"] == "different" or (
            _measurement_values([row["source_text"]]) and _measurement_values([row["candidate_text"]])
            and not measurement_values_match(groups.get(row.get('measurement_id'), {}).get('render_text') or row["source_text"], row["candidate_text"])))]
    if wrong:
        dimension_gate = _gate("dimension_accuracy", "fail", f"Located measured-object/value/endpoint contradictions: {wrong}")
    elif unbound or (has_diagram and (not dimensions or observation["measurement_coverage"] != "complete")) or observation["measurement_coverage"] == "partial" or any(row["confidence"] < 0.9 or row["relationship"] == "unknown" for row in dimensions):
        dimension_gate = _gate("dimension_accuracy", "inconclusive", "Incomplete measured-object, value or endpoint observation")
    else:
        dimension_gate = _gate("dimension_accuracy", "pass", "Observed measurement relationships match" if dimensions else "No measurement diagram; func numeric claims remain checked as exact authored copy")

    product = observation["product_comparisons"]
    expected = {(row['source_id'], row['view_id']) for row in candidate_view_targets(task)}
    observed = [(row['source_id'], row['view_id']) for row in product]
    complete = (bool(expected) and expected.issubset(observed) and len(observed) == len(set(observed))
                and all(pair in expected or pair[1].startswith('extra:') for pair in observed)
                and observation.get('product_coverage') == 'complete')
    status = ('fail' if any(row['status'] == 'contradiction' and row['confidence'] >= .9 for row in product)
              else 'pass' if complete and all(row['status'] == 'consistent' and row['confidence'] >= .9 for row in product)
              else 'inconclusive')
    gates = [text_gate, dimension_gate, _gate("product_fidelity", status, str(product))]
    edit = observation.get('edit_comparison')
    if edit:
        edit_status = {'consistent': 'pass', 'contradiction': 'fail', 'unknown': 'inconclusive'}[edit['status']]
        gates.append(_gate('edit_scope', edit_status if edit['confidence'] >= .9 else 'inconclusive', str(edit)))
    return gates


def _measurement_values(lines: Any) -> set[str]:
    values: set[str] = set()
    for line in lines or []:
        for row in extract_measurements(str(line or "")):
            pair = str(row.get("canonical_pair") or "").strip()
            if pair:
                values.add(pair)
    return values


def _line_matches_any(line: str, allowed: list[str]) -> bool:
    tokens = _ocr_match_tokens(line)
    if not tokens:
        return True
    for value in allowed:
        if numeric_signature(line) != numeric_signature(value):
            continue
        permitted = _ocr_match_tokens(value)
        if tokens == permitted or _compact_edit_distance_at_most_one(
            _ocr_compact(line), _ocr_compact(value)
        ):
            return True
    return False


def _unsupported_contract_lines(lines: list[str], allowed: list[str]) -> list[str]:
    """Return OCR lines not explained by one exact contract string.

    OCR may split one permitted heading across adjacent lines and may glue
    hyphenated words. Only exact whole-string equality after removing separators
    is accepted; arbitrary substring matching remains forbidden.
    """
    supported: set[int] = {
        index for index, line in enumerate(lines)
        if _line_matches_any(line, allowed)
    }
    for start in range(len(lines)):
        for stop in range(start + 2, min(len(lines), start + 3) + 1):
            if _line_matches_any(" ".join(lines[start:stop]), allowed):
                supported.update(range(start, stop))
    return [line for index, line in enumerate(lines) if index not in supported]


def _ocr_match_tokens(value: str) -> list[str]:
    text = re.sub(r"\bl(?=[a-z]{3,})", "i", value.casefold())
    return ["in" if token == "ln" else token for token in re.findall(r"[a-z0-9]+", text)]


def _ocr_compact(value: str) -> str:
    return "".join(_ocr_match_tokens(value))


def _compact_edit_distance_at_most_one(left: str, right: str) -> bool:
    """Tolerate one OCR insertion/deletion/substitution for a complete phrase."""
    if re.findall(r"\d+(?:\.\d+)?", left) != re.findall(r"\d+(?:\.\d+)?", right):
        return False
    if not left or not right or abs(len(left) - len(right)) > 1:
        return False
    if left == right:
        return True
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    short, long = (left, right) if len(left) < len(right) else (right, left)
    index = 0
    skipped = False
    for char in long:
        if index < len(short) and char == short[index]:
            index += 1
        elif skipped:
            return False
        else:
            skipped = True
    return index == len(short)


def _human_checklist(task: dict[str, Any]) -> list[str]:
    checks = [
        "exact product type, color, structure, count, moving-part state, and key parts",
        "composition, props, US-market context, and family art-direction consistency",
        "provider preserved the sold product from the one editable role reference and did not reconstruct hidden parts",
    ]
    if task["role_family"] == "size":
        checks.append("every source-visible measurement, line direction, endpoint, measured part, badge, and label relationship")
    if task["role_family"] == "func":
        checks.append("specific shopping story, readable labels, and source-supported feature relationship")
    return checks


def _gate(name: str, status: str, evidence: str, *, warning: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {"gate": name, "status": status, "evidence": evidence, "confidence": 1.0}
    if warning:
        row["warning"] = True
        row["reason_code"] = "human_visual_review_required"
    return row
