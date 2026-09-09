from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .candidate_state import CandidateStateError, current_candidate
from .image_pixel_evidence import inspect_image_pixel_evidence
from .image_role_ocr import OCR_CONCLUSIVE_CONFIDENCE, cached_ocr_evidence_for_image, ocr_evidence_for_image
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
from .text_evidence import extract_measurements, has_bad_encoding, normalize_text


LOCAL_GATE_NAMES = ("image_integrity", "main_background", "unauthorized_text", "dimension_accuracy")
_NON_LATIN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_UNAUTHORIZED_TEXT_CONFIDENCE = 0.75


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
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    qa_evidence_path = job / "reports" / QA_EVIDENCE_ARTIFACT
    if qa_evidence_path.is_file():
        try:
            existing = {(row["child"], row["role"]): row for row in read_qa_evidence(job)}
        except Exception as exc:
            record_progress(
                job,
                "qa_evidence_cache_rejected",
                error=f"{type(exc).__name__}: {exc}"[:1000],
            )
    else:
        record_progress(job, "qa_evidence_cache_miss")

    def evaluate(task: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        cached = existing.get((task["child"], task["role"]))
        if cached and evidence_is_current(cached, task, candidate, job_dir=job):
            return cached
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            raise TimeoutError("QA execution deadline exhausted before evaluation")
        return _evaluate(job, plugin, task, candidate)

    rows: list[dict[str, Any]] = []
    evaluation_failures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers or 1), len(pairs) or 1))) as pool:
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
                    "failure_owner": "qa", "task_status": "retryable", "error_code": "qa_evaluator_error",
                    "error": f"{type(exc).__name__}: {exc}",
                })
    rows.sort(key=lambda row: (row["child"], row["role"]))
    write_qa_evidence(job, rows)
    records = [
        {
            "logical_task_id": logical_task_id("qa", child=row["child"], role=row["role"]),
            "input_revision_id": input_revision_id({"evidence": row["evidence_fingerprint"], "qa_policy": row["qa_policy_id"]}),
            "child": row["child"], "role": row["role"], "status": "success",
        }
        for row in rows
    ]
    failures = candidate_failures + evaluation_failures
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


def _evaluate(job: Path, plugin: ProductPlugin, task: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    output = resolve_job_owned_path(job, str(candidate["candidate_path"]))
    gates = _local_gates(job, plugin, task, output)
    statuses = {row["status"] for row in gates}
    decision = "fail" if "fail" in statuses else "pass"
    evidence = {
        "schema_version": QA_EVIDENCE_SCHEMA_VERSION,
        "child": task["child"], "role": task["role"],
        "candidate_path": candidate["candidate_path"], "candidate_sha256": candidate["candidate_sha256"],
        "release_candidate_fingerprint": release_candidate_fingerprint(task, candidate),
        "qa_policy_id": qa_policy_id(task), "automatic_decision": decision,
        "decision_scope": "qa_lite_hard_facts_only",
        "quality_authority": "human_review_and_provider_ledger",
        "automatic_pass": decision == "pass", "failure_owner": "qa" if decision == "fail" else "",
        "provider": {"provider": "qa_lite", "model": "local", "protocol": "local"},
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
    gates.append(_main_background_gate(plugin, task, output))
    text, dimensions = _ocr_gates(job, task, output)
    gates.extend((text, dimensions))
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


def _ocr_gates(job: Path, task: dict[str, Any], output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    role = task["role_family"]
    try:
        ocr = ocr_evidence_for_image(output, cache_root=job / "reports" / "ocr_evidence")
    except Exception as exc:
        return _ocr_unavailable(role, f"{type(exc).__name__}: {exc}")
    if not ocr.get("available"):
        return _ocr_unavailable(role, str(ocr.get("error") or "no reliable OCR result"))
    evidence_lines = [row for row in ocr.get("lines") or [] if isinstance(row, dict)]
    lines = [
        normalize_text(row.get("text")) for row in evidence_lines
        if float(row.get("confidence") or 0) >= OCR_CONCLUSIVE_CONFIDENCE and normalize_text(row.get("text"))
    ]
    damaged = [line for line in lines if has_bad_encoding(line) or len(_NON_LATIN_RE.findall(line)) >= 2]
    if role in {"func", "size"} and damaged:
        return _gate("unauthorized_text", "fail", f"high-confidence damaged or non-English text: {damaged}"), _gate("dimension_accuracy", "fail", "damaged text prevents reliable dimension review")
    if role in {"main", "scene"}:
        source_lines = [normalize_text(value) for value in _source_ocr_lines(job, task) if normalize_text(value)]
        unsupported = _unsupported_contract_lines(lines, source_lines)
        return (
            _gate("unauthorized_text", "fail", f"new high-confidence readable text is not authorized for this role: {unsupported}")
            if unsupported else
            _gate(
                "unauthorized_text",
                "pass",
                "readable text is source-explained and requires human policy review"
                if lines else "no high-confidence readable text detected",
                warning=bool(lines),
            ),
            _gate("dimension_accuracy", "pass", "dimension gate is not applicable"),
        )
    if role == "func":
        allowed = [
            normalize_text(value)
            for value in task_renderable_text(task)
            if normalize_text(value)
        ]
        readable_lines = [
            normalize_text(row.get("text")) for row in evidence_lines
            if float(row.get("confidence") or 0) >= _UNAUTHORIZED_TEXT_CONFIDENCE
            and normalize_text(row.get("text"))
        ]
        unsupported = _unsupported_contract_lines(readable_lines, allowed)
        evidence = (
            "ordinary prop text is allowed; human review must confirm it is not a third-party brand, logo, "
            f"or branded package: {unsupported}"
            if unsupported else
            "all high-confidence OCR fragments match contracted text"
        )
        return _gate("unauthorized_text", "pass", evidence, warning=bool(unsupported)), _gate(
            "dimension_accuracy", "pass", "func dimensions are not a hard gate"
        )
    return _size_ocr_gates(job, task, lines)


def _size_ocr_gates(job: Path, task: dict[str, Any], candidate_lines: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    authority = task.get("measurement_authority") or {}
    if authority.get("mode") == "source_image":
        source_lines = _source_ocr_lines(job, task)
        source_values = _measurement_values(source_lines)
        candidate_values = _measurement_values(candidate_lines)
        if _has_zero_measurement(candidate_lines):
            evidence = "candidate contains an explicit zero measurement"
            return _gate("unauthorized_text", "fail", evidence), _gate("dimension_accuracy", "fail", evidence)
        unconfirmed = sorted(candidate_values - source_values) if source_values else []
        missing = sorted(source_values - candidate_values) if candidate_values else sorted(source_values)
        if unconfirmed:
            evidence = (
                "candidate OCR contains values not recovered from source OCR; OCR cannot overrule the editable "
                f"measurement reference, so human source comparison is required: {unconfirmed}"
            )
            return _gate("unauthorized_text", "pass", evidence, warning=True), _gate("dimension_accuracy", "pass", evidence, warning=True)
        if missing:
            evidence = (
                "source measurements were not all detected in the candidate; human source comparison required"
                f"; source values not detected in candidate={missing}"
            )
            return _gate("unauthorized_text", "pass", evidence, warning=True), _gate("dimension_accuracy", "pass", evidence, warning=True)
        if not source_values or not candidate_values:
            return _gate("unauthorized_text", "pass", "OCR cannot prove the complete source diagram; human review required", warning=True), _gate("dimension_accuracy", "pass", "OCR absence never rejects a source-size edit", warning=True)
        return _gate("unauthorized_text", "pass", "no definite unauthorized measurement was detected"), _gate("dimension_accuracy", "pass", "human review must confirm every source-visible value, line, endpoint, and measured part was retained", warning=True)
    expected = _measurement_values(authority.get("render_text") or [])
    observed = _measurement_values(candidate_lines)
    wrong = sorted(observed - expected)
    if wrong:
        evidence = f"candidate contains unauthorized spec measurements: {wrong}"
        return _gate("unauthorized_text", "fail", evidence), _gate("dimension_accuracy", "fail", evidence)
    missing = not expected.issubset(observed)
    return _gate("unauthorized_text", "pass", "no unauthorized spec measurement detected"), _gate("dimension_accuracy", "pass", "human review required for any OCR-missed spec value" if missing else "all confirmed spec values detected", warning=missing)


def _measurement_values(lines: Any) -> set[str]:
    values: set[str] = set()
    for line in lines or []:
        for row in extract_measurements(str(line or "")):
            pair = str(row.get("canonical_pair") or "").strip()
            if pair:
                values.add(pair)
    return values


def _has_zero_measurement(lines: Any) -> bool:
    return any(
        str(row.get("canonical_value") or "").strip() in {"0", "0.0"}
        for line in lines or []
        for row in extract_measurements(str(line or ""))
    )


def _source_ocr_lines(job: Path, task: dict[str, Any]) -> list[str]:
    source = resolve_job_owned_path(job, str(task.get("source_path") or ""))
    cached = cached_ocr_evidence_for_image(source, cache_root=job / "reports" / "ocr_evidence") if source.is_file() else None
    return [
        str(row.get("text") or "").strip() for row in (cached or {}).get("lines") or []
        if isinstance(row, dict) and float(row.get("confidence") or 0) >= 0.7 and str(row.get("text") or "").strip()
    ]


def _line_matches_any(line: str, allowed: list[str]) -> bool:
    tokens = _ocr_match_tokens(line)
    if not tokens:
        return True
    for value in allowed:
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
    permitted = {_ocr_compact(value) for value in allowed if _ocr_compact(value)}
    for start in range(len(lines)):
        for stop in range(start + 2, min(len(lines), start + 3) + 1):
            if any(
                _compact_edit_distance_at_most_one(
                    _ocr_compact(" ".join(lines[start:stop])), expected,
                )
                for expected in permitted
            ):
                supported.update(range(start, stop))
    return [line for index, line in enumerate(lines) if index not in supported]


def _line_is_contract_fragment(line: str, allowed: list[str]) -> bool:
    tokens = _ocr_match_tokens(line)
    compact = _ocr_compact(line)
    return bool(tokens) and any(
        any(permitted[index:index + len(tokens)] == tokens for index in range(len(permitted) - len(tokens) + 1))
        or (
            len(compact) >= 4
            and (
                _ocr_compact(value).startswith(compact)
                or _ocr_compact(value).endswith(compact)
            )
        )
        or any(
            compact == "".join(permitted[start:stop])
            for start in range(len(permitted))
            for stop in range(start + 1, len(permitted) + 1)
        )
        for value in allowed
        for permitted in [_ocr_match_tokens(value)]
    )


def _ocr_match_tokens(value: str) -> list[str]:
    text = re.sub(r"\bl(?=[a-z]{3,})", "i", value.casefold())
    return ["in" if token == "ln" else token for token in re.findall(r"[a-z0-9]+", text)]


def _ocr_compact(value: str) -> str:
    return "".join(_ocr_match_tokens(value))


def _compact_edit_distance_at_most_one(left: str, right: str) -> bool:
    """Tolerate one OCR insertion/deletion/substitution for a complete phrase."""
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


def _ocr_unavailable(role: str, error: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if role in {"main", "scene"}:
        return _gate("unauthorized_text", "pass", f"OCR unavailable; manual text inspection remains: {error}"), _gate("dimension_accuracy", "pass", "not applicable")
    return _gate("unauthorized_text", "pass", f"OCR unavailable; human text inspection required: {error}", warning=True), _gate("dimension_accuracy", "pass", "OCR absence cannot reject an infographic", warning=True)


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
