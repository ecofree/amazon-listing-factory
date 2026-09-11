from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from .api_registry import (
    image_provider_entries,
    image_provider_physical_identity,
)
from .candidate_state import CandidateStateError, current_candidate
from .image_generation_executor import generate_one
from .image_provider_common import (
    _system_memory_bytes,
    ProviderQueueUnavailable,
    provider_attempts,
    provider_concurrency_limit,
    provider_failure_class,
    provider_timeout_seconds,
)
from .image_prompt_compiler import (
    IMAGE_PROMPT_POLICY_VERSION,
    IMAGE_PROMPT_SCHEMA_VERSION,
    PROMPT_CONTRACT_VERSION,
    PROMPT_HARD_LIMIT_CHARS,
    PROMPT_REVISION_RESERVE_CHARS,
    prompt_for_task,
    read_image_prompts,
    require_current_image_branch,
)
from .image_task_inputs import EXECUTION_PROFILES
from .image_provider_routing import apply_role_provider_policy, assign_provider_pool, provider_order
from .image_provider_transport import eligible_imagegen_providers
from .image_tasks import IMAGE_TASK_SCHEMA_VERSION, read_image_tasks
from .imagegen_artifacts import IMAGEGEN_OUTPUT_CACHE_VERSION
from .io import file_sha256, load_env, write_bytes_atomic, write_json
from .job import load_job
from .plugin import ProductPlugin
from .paths import resolve_job_owned_path
from .provider_policy import load_provider_policy
from .progress_trace import record_progress
from .run_scope import scoped_child_set
from .status import (
    failure_task_status,
    input_revision_id,
    record_task_failures,
    record_task_successes,
    task_record_current,
)
from .url_safety import URL_SAFETY_POLICY_VERSION


def run_image_generation(
    *,
    job_dir: str | Path,
    plugin: ProductPlugin,
    config_path: str = "",
    workers: int = 0,
    limit: int = 0,
    production: bool = False,
    attempt_id: str = "",
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    job_path = Path(job_dir).resolve()
    _load_generation_env(config_path, str(load_job(job_path).get("config_path") or ""))
    require_current_image_branch(job_path, plugin)
    del limit
    allowed_children = scoped_child_set(job_path)
    prompt_artifact = read_image_prompts(job_path, category_id=plugin.category_id)
    tasks = read_image_tasks(job_path, category_id=plugin.category_id)["tasks"]
    providers = provider_order(plugin)
    execution_revision = _generation_execution_revision(providers)

    runtime: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    blocked_by: list[dict[str, str]] = []
    for task in tasks:
        if task["child"] not in allowed_children:
            continue
        if task["formation_status"] == "blocked":
            upstream = (
                f"brief:{task['child']}:design_kit"
                if task.get("formation_reason_code") == "upstream_design_kit_missing"
                else str(task["logical_task_id"]).replace("generate:", "brief:", 1)
            )
            blocked_by.append({"logical_task_id": str(task["logical_task_id"]), "blocked_by": upstream})
            record_progress(
                job_path,
                "generate_task_blocked_by_brief",
                logical_task_id=task["logical_task_id"],
                child=task.get("child"),
                role=task.get("role"),
                blocked_by=upstream,
            )
            continue
        try:
            prompt_row = prompt_for_task(prompt_artifact, task)
            prompt = str(prompt_row["prompt"])
            task_prompt_fingerprint = str(prompt_row["prompt_sha256"])
        except OSError as exc:
            failures.append(_failure(
                {**task, "execution_revision": execution_revision},
                owner="generation_preflight",
                error=f"{type(exc).__name__}: {exc}",
                status="retryable",
            ))
            continue
        except Exception as exc:
            failures.append(_failure(
                {**task, "execution_revision": execution_revision},
                owner="generation_preflight",
                error=f"{type(exc).__name__}: {exc}",
                status="blocked",
            ))
            continue
        try:
            candidate = current_candidate(job_path, task)
        except CandidateStateError as exc:
            failures.append(_failure(
                {**task, "execution_revision": execution_revision},
                owner="candidate_state", error=str(exc), status="blocked",
            ))
            continue
        except OSError as exc:
            failures.append(_failure(
                {**task, "execution_revision": execution_revision},
                owner="candidate_state",
                error=f"{type(exc).__name__}: {exc}",
                status="retryable",
            ))
            continue
        if candidate and candidate.get("task_prompt_fingerprint") == task_prompt_fingerprint:
            recovered = _candidate_task_result(task, candidate, execution_revision=execution_revision)
            outcomes.append(recovered)
            record_progress(
                job_path,
                "generate_candidate_reused",
                logical_task_id=task["logical_task_id"],
                child=task["child"],
                role=task["role"],
                candidate_sha256=recovered.get("candidate_sha256"),
                candidate_revision=recovered.get("candidate_revision"),
            )
            if attempt_id:
                record_task_successes(job_path, owner_stage="generate", attempt_id=attempt_id, tasks=[recovered])
            continue
        state = task_record_current(job_path, task["logical_task_id"], task["input_revision_id"])
        if state.get("request_outcome") == "unknown":
            failures.append(_failure({**task, **state}, owner="generation", error="Remote request outcome is unknown; reconcile the recorded request before explicitly revising this image.", status="review"))
            continue
        if (
            state.get("status") == "blocked"
            and state.get("execution_revision") == execution_revision
        ):
            failures.append(_failure(
                {**task, **state}, owner="generation",
                error=str(state.get("error") or "Generation is terminal for the current execution configuration"),
                status="blocked",
            ))
            continue
        try:
            candidate_revision = _next_candidate_revision(
                job_path,
                task,
                int(candidate.get("candidate_revision") or 0) + 1 if candidate else 0,
            )
            relative_output = _candidate_output_path(task, candidate_revision)
            runtime_task = {
                **task,
                "source_path": str(resolve_job_owned_path(job_path, str(task["source_path"]))),
                "generation_references": _runtime_generation_references(job_path, task),
                "output_path": str(resolve_job_owned_path(job_path, relative_output)),
                "candidate_path": relative_output,
                "prompt": prompt,
                "job_dir": str(job_path),
                "prompt_path": str(prompt_row["prompt_path"]),
                "task_prompt_fingerprint": task_prompt_fingerprint,
                "request_prompt_fingerprint": task_prompt_fingerprint,
                "providers": list(providers),
                "production_imagegen": bool(production),
                "candidate_revision": candidate_revision,
                "child_provider_lane_key": f"{plugin.category_id}:{job_path.name}:{task['child']}",
                "transport_attempt": int(state.get("transport_attempt") or 0) + 1,
                "provider_attempts": dict(state.get("provider_attempts") or {}),
                "execution_revision": execution_revision,
            }
            apply_role_provider_policy(runtime_task, plugin)
            if not runtime_task.get("providers"):
                failures.append(_failure(
                    {**task, "execution_revision": execution_revision},
                    owner="generation_provider_availability",
                    error=f"No currently available physical provider for {task['child']}/{task['role']}; retry after provider health/configuration changes",
                    status="retryable",
                ))
                continue
            runtime_task["providers"] = eligible_imagegen_providers(prompt, list(runtime_task["providers"]))
            if not runtime_task["providers"]:
                failures.append(_failure(
                    {**task, "execution_revision": execution_revision},
                    owner="generation_provider_availability",
                    error=f"No currently eligible provider accepts the compiled prompt for {task['child']}/{task['role']}; retry after provider capability/configuration changes",
                    status="retryable",
                ))
                continue
            runtime.append(runtime_task)
            record_progress(
                job_path,
                "generate_candidate_queued",
                logical_task_id=task["logical_task_id"],
                child=task["child"],
                role=task["role"],
                candidate_revision=candidate_revision,
                providers=list(runtime_task.get("providers") or []),
            )
        except OSError as exc:
            failures.append(_failure(
                {**task, "execution_revision": execution_revision},
                owner="generation_preflight",
                error=f"{type(exc).__name__}: {exc}",
                status="retryable",
            ))
        except Exception as exc:
            failures.append(_failure(
                {**task, "execution_revision": execution_revision},
                owner="generation_preflight",
                error=f"{type(exc).__name__}: {exc}",
                status="blocked",
            ))

    persisted_results: dict[str, dict[str, Any]] = {}

    def _persist_success(task: dict[str, Any]) -> dict[str, Any]:
        result = _completed_task_result(task, execution_revision=execution_revision)
        persisted_results[str(result["logical_task_id"])] = result
        record_progress(
            job_path,
            "generate_candidate_committed",
            logical_task_id=result["logical_task_id"],
            child=result["child"],
            role=result["role"],
            candidate_sha256=result.get("candidate_sha256"),
            candidate_revision=result.get("candidate_revision"),
            provider_name=result.get("provider_name"),
        )
        if attempt_id:
            record_task_successes(job_path, owner_stage="generate", attempt_id=attempt_id, tasks=[result])
        return result

    def _persist_failure(failure: dict[str, Any]) -> None:
        task = failure.get("task") if isinstance(failure.get("task"), dict) else {}
        record_progress(
            job_path,
            "generate_candidate_failure",
            logical_task_id=task.get("logical_task_id"),
            child=task.get("child"),
            role=task.get("role"),
            status=failure.get("task_status"),
            error=failure.get("error"),
        )
        if attempt_id:
            record_task_failures(job_path, owner_stage="generate", attempt_id=attempt_id, failures=[failure])

    for task in runtime:
        task["deadline_monotonic"] = deadline_monotonic
    completed, execution_failures = _execute(
        assign_provider_pool(runtime),
        plugin=plugin,
        workers=workers,
        on_success=_persist_success if attempt_id else None,
        on_failure=_persist_failure if attempt_id else None,
    )
    failures.extend(execution_failures)
    for task in completed:
        outcomes.append(persisted_results.get(str(task["logical_task_id"])) or _completed_task_result(task, execution_revision=execution_revision))
    provider_usage = {
        child: sorted({
            str(row.get("provider_name") or "") for row in outcomes
            if str(row.get("child") or "") == child and str(row.get("provider_name") or "")
        })
        for child in sorted({str(row.get("child") or "") for row in outcomes})
    }
    result = {
        "schema_version": "imagegen-results-v3",
        "tasks": outcomes,
        "outcomes": outcomes,
        "failures": failures,
        "blocked_by": blocked_by,
        "child_provider_usage": {
            child: {"providers": names, "mixed_provider_warning": len(names) > 1}
            for child, names in provider_usage.items()
        },
        "task_status_recorded": bool(attempt_id),
        "policy_versions": image_generation_policy_versions(plugin),
    }
    write_json(job_path / "reports" / "imagegen_results_v3.json", result)
    return result


def run_image_revision(
    *,
    job_dir: str | Path,
    plugin: ProductPlugin,
    child: str,
    role: str,
    reason: str,
    config_path: str = "",
    production: bool = False,
    revision_mode: str = "targeted_edit", candidate_sha256: str = "",
) -> dict[str, Any]:
    if revision_mode not in {"targeted_edit", "full_redraw"}:
        raise ValueError("Revision mode must be targeted_edit or full_redraw")
    if not str(reason or "").strip():
        raise RuntimeError("Revision requires a human-readable reason")
    job_path = Path(job_dir).resolve()
    _load_generation_env(config_path, str(load_job(job_path).get("config_path") or ""))
    require_current_image_branch(job_path, plugin)
    prompt_artifact = read_image_prompts(job_path, category_id=plugin.category_id)
    task = next(
        (
            row for row in read_image_tasks(job_path, category_id=plugin.category_id)["tasks"]
            if str(row.get("child")) == str(child) and str(row.get("role")) == str(role)
        ),
        None,
    )
    if not task or task.get("formation_status") != "ready":
        raise RuntimeError(f"Ready image task not found for {child}/{role}")
    candidate_state_corrupt = False
    try:
        from .candidate_state import candidate_by_sha
        current = candidate_by_sha(job_path, task, candidate_sha256) if candidate_sha256 else current_candidate(job_path, task, required=False) or {}
    except CandidateStateError:
        if candidate_sha256 or revision_mode != "full_redraw":
            raise
        current = {}
        candidate_state_corrupt = True
    providers = provider_order(plugin)
    execution_revision = _generation_execution_revision(providers)
    prompt_row = prompt_for_task(prompt_artifact, task)
    base_prompt = str(prompt_row["prompt"])
    task_prompt_fingerprint = str(prompt_row["prompt_sha256"])
    current_revision = current.get("candidate_revision") if current else None
    revision = _next_candidate_revision(
        job_path, task,
        (int(current_revision) if current_revision is not None else -1) + 1,
        skip_existing=candidate_state_corrupt or bool(candidate_sha256),
    )
    mode = revision_mode if current or candidate_state_corrupt else "initial"
    references = _runtime_generation_references(job_path, task)
    parent_sha = ""
    if mode == "targeted_edit":
        parent_sha = current["candidate_sha256"]
        source_evidence = {**references[0], "kind": "product_evidence", "purpose": "Original product structure and state evidence"}
        source_evidence.pop("protected_mask", None)
        references = [{**source_evidence, "kind": "edit_base", "source_id": f"candidate_{current['candidate_revision']}",
                       "path": str(resolve_job_owned_path(job_path, current["candidate_path"])), "sha256": parent_sha,
                       "purpose": "Edit this selected candidate only within the requested changes", "evidence_ids": []},
                      source_evidence, *references[1:]]
        from .image_prompt_compiler import compile_task_prompt
        base_prompt = compile_task_prompt(task={**task, "generation_references": references}, targeted_edit=True)
    request_heading = {"targeted_edit": "TARGETED CANDIDATE EDIT", "full_redraw": "EXPLICIT FULL-REDRAW REQUEST",
                       "initial": "EXPLICIT MISSING CANDIDATE REQUEST"}[mode]
    request_intro = {
        "targeted_edit": "Edit attachment 1 only for the listed issue. Preserve other correct product pixels, approved copy, composition and staging.",
        "full_redraw": "Generate a complete new candidate because a human reviewer requested a full-image redraw; this is not a localized text repair.",
        "initial": "Generate the first candidate for this ready role because no current candidate exists.",
    }[mode]
    prompt = _compose_revision_prompt(
        base_prompt=base_prompt,
        request_heading=request_heading,
        request_intro=request_intro,
        reason=reason,
    )
    request_prompt_fingerprint = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    revision_prompt_path = Path("reports") / "image_prompts" / str(task["child"]) / str(task["role"]) / f"{task['task_fingerprint']}.candidate{revision}.{request_prompt_fingerprint}.revision.prompt.txt"
    revision_trace = job_path / revision_prompt_path
    if revision_trace.is_file() and file_sha256(revision_trace) != request_prompt_fingerprint:
        raise RuntimeError("Immutable revision prompt trace changed")
    if not revision_trace.is_file():
        write_bytes_atomic(revision_trace, prompt.encode("utf-8"))
    relative_output = _candidate_output_path(task, revision)
    runtime_task = {
        **task,
        "source_path": str(resolve_job_owned_path(job_path, str(task["source_path"]))),
        "generation_references": references,
        "edit_base_sha256": references[0]["sha256"],
        "edit_parent_candidate_sha256": parent_sha, "revision_mode": mode,
        "output_path": str(resolve_job_owned_path(job_path, relative_output)),
        "candidate_path": relative_output,
        "prompt": prompt,
        "job_dir": str(job_path),
        "prompt_path": revision_prompt_path.as_posix(),
        "task_prompt_fingerprint": task_prompt_fingerprint,
        "request_prompt_fingerprint": request_prompt_fingerprint,
        "providers": list(providers),
        "production_imagegen": bool(production),
        "candidate_revision": revision,
        "child_provider_lane_key": f"{plugin.category_id}:{job_path.name}:{task['child']}",
        "transport_attempt": 1,
        "provider_attempts": {},
        "execution_revision": execution_revision,
    }
    apply_role_provider_policy(runtime_task, plugin)
    if not runtime_task.get("providers"):
        return {
            "schema_version": "imagegen-revision-v1",
            "tasks": [],
            "failures": [_failure(
                runtime_task,
                owner="generation_provider_availability",
                error=f"No configured physical provider is available for {task['child']}/{task['role']}; retry after provider health/configuration changes",
                status="retryable",
            )],
        }
    runtime_task["providers"] = eligible_imagegen_providers(prompt, list(runtime_task["providers"]))
    if not runtime_task["providers"]:
        return {
            "schema_version": "imagegen-revision-v1",
            "tasks": [],
            "failures": [_failure(
                runtime_task,
                owner="generation_provider_availability",
                error=f"No currently eligible provider accepts the compiled prompt for {task['child']}/{task['role']}; retry after provider capability/configuration changes",
                status="retryable",
            )],
        }
    assigned = assign_provider_pool([runtime_task])
    previous_provider = str(current.get("provider_name") or "")
    if previous_provider and assigned:
        assigned_task = assigned[0]
        ordered = list(dict.fromkeys([
            *(str(name) for name in assigned_task.get("providers") or [] if str(name)),
            *(str(name) for name in assigned_task.get("child_provider_reserve") or [] if str(name)),
        ]))
        if mode == "targeted_edit" and previous_provider in ordered:
            preferred = [previous_provider, *[name for name in ordered if name != previous_provider]]
            assigned_task["providers"] = preferred[:2]
            assigned_task["child_provider_reserve"] = preferred[2:]
    completed, failures = _execute(assigned, plugin=plugin, workers=1)
    if failures:
        return {"schema_version": "imagegen-revision-v1", "tasks": [], "failures": failures}
    output_task = completed[0]
    result = _completed_task_result(output_task, execution_revision=execution_revision)
    return {
        "schema_version": "imagegen-revision-v1",
        "tasks": [result],
        "failures": [],
        "revision_mode": mode,
        "revision_reason": str(reason).strip(),
    }


def generation_artifacts_current(job_dir: str | Path, plugin: ProductPlugin) -> bool:
    try:
        job_path = Path(job_dir).resolve()
        require_current_image_branch(job_path, plugin)
        prompt_artifact = read_image_prompts(job_path, category_id=plugin.category_id)
        allowed_children = scoped_child_set(job_path)
        tasks = read_image_tasks(job_path, category_id=plugin.category_id)["tasks"]
        for task in tasks:
            if task["child"] not in allowed_children:
                continue
            if task["formation_status"] == "blocked":
                # A current blocked formation is a terminal task artifact, not
                # a reason to invalidate successful siblings or to replay the
                # generate stage on every resume.
                continue
            candidate = current_candidate(job_path, task)
            if not candidate:
                return False
            prompt_row = prompt_for_task(prompt_artifact, task)
            if candidate.get("task_prompt_fingerprint") != prompt_row["prompt_sha256"]:
                return False
        return True
    except Exception:
        return False


def _candidate_output_path(task: dict[str, Any], revision: int) -> str:
    return f"{str(task['output_dir']).rstrip('/')}/{task['task_fingerprint']}.candidate{revision}.png"


def _compose_revision_prompt(
    *,
    base_prompt: str,
    request_heading: str,
    request_intro: str,
    reason: Any,
    target_chars: int = PROMPT_HARD_LIMIT_CHARS,
) -> str:
    cleaned_reason = " ".join(str(reason or "").strip().split())
    if not cleaned_reason:
        cleaned_reason = "review requested a new candidate"
    prefix = (
        "\n\n# Revision request\n"
        f"Request type: {request_heading}.\n"
        f"Instruction: {' '.join(str(request_intro or '').split())} "
        "Address only this reason while preserving the task facts and family art direction: "
    )
    suffix = "\nDo not add new facts, new dimensions, new claims, or a different product configuration."
    if len(base_prompt) > int(target_chars) - PROMPT_REVISION_RESERVE_CHARS:
        raise RuntimeError("Base ImagePromptV2 did not reserve space for an explicit revision request")
    available = int(target_chars) - len(base_prompt) - len(prefix) - len(suffix)
    if available < 64:
        raise RuntimeError("Revision reason cannot fit without discarding the immutable base prompt")
    if len(cleaned_reason) > available:
        raise RuntimeError(
            f"Revision reason is {len(cleaned_reason)} characters; maximum executable length is {available}"
        )
    return base_prompt + prefix + cleaned_reason + suffix


def _next_candidate_revision(
    job_path: Path,
    task: dict[str, Any],
    start: int,
    *,
    skip_existing: bool = False,
) -> int:
    revision = max(0, int(start))
    while True:
        output = resolve_job_owned_path(job_path, _candidate_output_path(task, revision))
        manifest = resolve_job_owned_path(
            job_path,
            str(
                Path("reports") / "candidate_manifests" / str(task.get("child") or "")
                / str(task.get("role") or "") / str(task.get("task_fingerprint") or "")
                / f"candidate{revision}.json"
            ),
        )
        if not output.exists() and not manifest.exists():
            return revision
        if not skip_existing:
            raise CandidateStateError(
                f"Unowned candidate output blocks immutable revision {revision}: {task.get('child')}/{task.get('role')}"
            )
        revision += 1


def _execute(
    tasks: list[dict[str, Any]], *, plugin: ProductPlugin, workers: int,
    on_success: Any | None = None,
    on_failure: Any | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    completed: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if not tasks:
        return completed, failures
    pending = list(tasks)
    capacity_requeues: dict[str, int] = {}
    last_batch_progress_at = time.monotonic()
    capacity_errors: dict[str, ProviderQueueUnavailable] = {}
    with ThreadPoolExecutor(max_workers=_effective_generation_workers(tasks, workers)) as pool:
        futures: dict[Any, dict[str, Any]] = {}
        while pending or futures:
            current, pending = _dispatch_generation_batch(pending, workers, active=list(futures.values()))
            futures.update({pool.submit(generate_one, task, plugin=plugin): task for task in current})
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            round_made_progress = False
            for future in done:
                task = futures.pop(future)
                try:
                    completed_task = future.result()
                except Exception as exc:
                    task_id = str(task.get("logical_task_id") or f"{task.get('child')}/{task.get('role')}")
                    if isinstance(exc, ProviderQueueUnavailable):
                        capacity_requeues[task_id] = capacity_requeues.get(task_id, 0) + 1
                        capacity_errors[task_id] = exc
                        pending.append(task)
                        if task.get("job_dir") and (
                            capacity_requeues[task_id] == 1
                            or capacity_requeues[task_id] % 20 == 0
                        ):
                            record_progress(
                                str(task["job_dir"]), "image_task_capacity_requeued",
                                logical_task_id=task_id, child=task.get("child"), role=task.get("role"),
                                capacity_round=capacity_requeues[task_id],
                            )
                        continue
                    status = _generation_failure_status(exc)
                    round_made_progress = True
                    failed_task = {
                        **task,
                        "provider_attempts": _provider_attempt_counts(
                            task, selected="", attempted=getattr(exc, "attempted_providers", []),
                        ),
                    }
                    failure = _failure(failed_task, owner="generation", error=f"{type(exc).__name__}: {exc}", status=status)
                    if status == "blocked":
                        failure["task_status"] = failure_task_status(failure)
                    failures.append(failure)
                    if on_failure is not None:
                        on_failure(failure)
                else:
                    if on_success is not None:
                        on_success(completed_task)
                    completed.append(completed_task)
                    round_made_progress = True
            if round_made_progress:
                last_batch_progress_at = time.monotonic()
                capacity_errors.clear()
            if pending and not futures and all(
                str(task.get("logical_task_id") or f"{task.get('child')}/{task.get('role')}") in capacity_errors
                for task in pending
            ) and time.monotonic() - last_batch_progress_at >= _capacity_stall_budget_seconds():
                stalled, pending = pending, []
                for task in stalled:
                    task_id = str(task.get("logical_task_id") or f"{task.get('child')}/{task.get('role')}")
                    exc = capacity_errors.get(task_id)
                    failed_task = {
                        **task,
                        "provider_attempts": _provider_attempt_counts(
                            task, selected="", attempted=getattr(exc, "attempted_providers", []),
                        ),
                    }
                    failure = _failure(
                        failed_task,
                        owner="generation_provider_capacity",
                        error=(
                            "ProviderQueueUnavailable: no image task completed or failed while local provider "
                            f"capacity remained unavailable for {_capacity_stall_budget_seconds():g} seconds"
                        ),
                        status="retryable",
                    )
                    failures.append(failure)
                    if on_failure is not None:
                        on_failure(failure)
                continue
            if pending and capacity_errors and not round_made_progress:
                time.sleep(0.25)
    completed.sort(key=lambda row: (row["child"], row["role"]))
    return completed, failures


def _dispatch_generation_batch(
    pending: list[dict[str, Any]], requested_workers: int,
    *, active: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fill free worker lanes; provider file leases remain cross-process authority."""
    if not pending:
        return [], []
    active = active or []
    cap = max(0, _effective_generation_workers(pending + active, requested_workers) - len(active))
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    used: dict[str, int] = {}
    used_lanes: set[str] = {
        str(task.get("child_provider_lane") or task.get("child_provider_lane_key") or task.get("child") or "default")
        for task in active
    }
    for task in active:
        primary = _task_primary_provider(task)
        used[primary] = used.get(primary, 0) + 1
    for task in pending:
        primary = _task_primary_provider(task)
        lane = str(task.get("child_provider_lane") or task.get("child_provider_lane_key") or task.get("child") or "default")
        if lane in used_lanes:
            deferred.append(task)
            continue
        limit = provider_concurrency_limit(primary) if primary else 0
        if primary and limit > 0 and used.get(primary, 0) >= limit:
            deferred.append(task)
            continue
        if len(selected) >= cap:
            deferred.append(task)
            continue
        selected.append(task)
        used_lanes.add(lane)
        if primary:
            used[primary] = used.get(primary, 0) + 1
    return selected, deferred


def _task_primary_provider(task: dict[str, Any]) -> str:
    return str(
        task.get("child_provider_primary")
        or ((task.get("providers") or [""])[0] if isinstance(task.get("providers"), list) else "")
        or ""
    ).strip()


def _effective_generation_workers(
    tasks: list[dict[str, Any]], requested_workers: int,
) -> int:
    task_count = max(1, len(tasks))
    requested = int(requested_workers or 0)
    requested_cap = requested if requested > 0 else task_count
    policy_cap = _policy_parallel_cap()
    provider_cap = 0
    from .api_registry import image_provider_resource_group
    groups = set()
    for provider in {_task_primary_provider(task) for task in tasks} - {""}:
        group = image_provider_resource_group(provider)
        if group in groups:
            continue
        groups.add(group)
        limit = provider_concurrency_limit(provider)
        provider_cap += limit if limit > 0 else task_count
    provider_cap = provider_cap or 1
    return max(1, min(
        task_count,
        requested_cap,
        policy_cap,
        provider_cap,
        _memory_worker_cap(tasks),
        _cpu_worker_cap(),
    ))


def _policy_parallel_cap() -> int:
    try:
        policy = load_provider_policy().get("image_generation") or {}
        value = int(policy.get("max_parallel_provider_jobs") or 0)
        return max(1, min(32, value)) if value > 0 else 1
    except (OSError, TypeError, ValueError):
        return 1


def _cpu_worker_cap() -> int:
    logical = int(os.cpu_count() or 1)
    return max(1, min(8, logical // 4 or 1))


def _memory_worker_cap(tasks: list[dict[str, Any]] | None = None) -> int:
    total, available = _system_memory_bytes()
    if total <= 0 or available <= 0:
        return 1
    reserve = max(4 * 1024**3, int(total * 0.20))
    # Multi-reference edits hold the complete input set, not only its largest file.
    largest_reference = 0
    for task in tasks or []:
        task_bytes = 0
        for row in task.get("generation_references") or []:
            path = row.get("path") if isinstance(row, dict) else row
            try:
                task_bytes += Path(str(path)).stat().st_size
            except (OSError, TypeError, ValueError):
                continue
        largest_reference = max(largest_reference, task_bytes)
    estimated_task_peak = max(768 * 1024**2, min(1536 * 1024**2, int(total * 0.04)))
    estimated_task_peak = max(
        estimated_task_peak,
        min(1536 * 1024**2, largest_reference * 8 + 512 * 1024**2),
    )
    usable = max(0, available - reserve)
    return max(1, min(8, usable // estimated_task_peak or 1))


def _capacity_stall_budget_seconds() -> float:
    raw = str(os.environ.get("AMAZON_FACTORY_IMAGEGEN_QUEUE_STALL_SECONDS") or "120").strip()
    try:
        return max(0.0, min(float(raw), 600.0))
    except ValueError:
        return 120.0


def _generation_failure_status(exc: Exception) -> str:
    if getattr(exc, "ambiguous", False):
        return "review"
    # Only a locally compiled immutable prompt/contract may deterministically
    # block the task.  Provider transport, configuration, response decoding,
    # and invalid returned pixels are provider-owned and must remain recoverable.
    return "blocked" if provider_failure_class(exc) == "contract" else "retryable"


def _completed_task_result(task: dict[str, Any], *, execution_revision: str) -> dict[str, Any]:
    candidate = current_candidate(task["job_dir"], task, required=True)
    return _candidate_task_result(task, candidate, execution_revision=execution_revision)


def _failure(task: dict[str, Any], *, owner: str, error: str, status: str) -> dict[str, Any]:
    runtime = {
        key: task[key]
        for key in (
            "transport_attempt", "provider_attempts", "execution_revision", "request_outcome", "request_audit",
        ) if key in task
    }
    return {
        "task": {
            "child": str(task.get("child") or ""),
            "role": str(task.get("role") or ""),
            "logical_task_id": str(task.get("logical_task_id") or ""),
            "input_revision_id": str(task.get("input_revision_id") or ""),
            **runtime,
        },
        "failure_owner": owner,
        "task_status": status,
        "error": error,
    }


def _candidate_task_result(task: dict[str, Any], candidate: dict[str, Any], *, execution_revision: str) -> dict[str, Any]:
    return {
        "logical_task_id": task["logical_task_id"],
        "input_revision_id": task["input_revision_id"],
        "child": task["child"],
        "role": task["role"],
        **{key: candidate[key] for key in (
            "candidate_sha256", "candidate_path", "candidate_revision", "provider_physical",
            "provider_name", "task_prompt_fingerprint", "request_prompt_fingerprint", "transport_attempt", "provider_attempts",
        ) if key in candidate},
        "execution_revision": execution_revision,
    }


def _provider_attempt_counts(task: dict[str, Any], *, selected: str, attempted: Any = None) -> dict[str, int]:
    counts = dict(task.get("provider_attempts") or {})
    if task.get("provider_attempts_exact") is True:
        return {str(name): min(2, max(0, int(value))) for name, value in counts.items()}
    attempted_names = [str(value) for value in attempted or [] if str(value or "").strip()]
    if selected and selected not in attempted_names:
        attempted_names.append(selected)
    for provider in attempted_names:
        counts[provider] = min(2, int(counts.get(provider) or 0) + 1)
    return counts


def _generation_execution_revision(providers: list[str]) -> str:
    registry = {entry.name: entry for entry in image_provider_entries()}
    material: dict[str, Any] = {
        "prompt_contract": PROMPT_CONTRACT_VERSION,
        # Reference cardinality is part of the executable generation contract.
        # A task that was blocked under the old single-reference runtime must
        # be eligible for recovery after the current func dual-reference fix.
        "generation_reference_contract": "typed-reference-edit-base-v2",
        "routing_contract": "role-model-pool-v1-bounded-fallback",
        "execution_profiles": sorted(EXECUTION_PROFILES),
        "url_safety_policy": URL_SAFETY_POLICY_VERSION,
        "providers": [],
    }
    for name in providers:
        entry = registry.get(name)
        raw = getattr(entry, "raw", {}) or {}
        material["providers"].append({
            "name": name,
            "identity": image_provider_physical_identity(name),
            "credential_revision": hashlib.sha256(str(getattr(entry, "api_key", "")).encode("utf-8")).hexdigest(),
            "prompt_max_chars": int(raw.get("prompt_max_chars") or 0),
            "allowed_roles": raw.get("allowed_roles") or [],
            # The resolved protocol profile is part of currentness: endpoint,
            # request dimensions, quality/background and output contract all
            # affect provider behaviour even when the prompt is unchanged.
            "protocol_profile": raw.get("protocol_profile") or {},
            "timeout_seconds": provider_timeout_seconds(name),
            "attempts": provider_attempts(name),
            "retry_delay_seconds": str(os.environ.get("AMAZON_FACTORY_IMAGEGEN_RETRY_DELAY_SECONDS", "10")),
        })
    return input_revision_id(material)


def image_generation_policy_versions(plugin: ProductPlugin) -> dict[str, str]:
    providers = [image_provider_physical_identity(name) for name in provider_order(plugin)]
    return {
        "image_tasks": IMAGE_TASK_SCHEMA_VERSION,
        "image_prompts": f"{IMAGE_PROMPT_SCHEMA_VERSION}:{IMAGE_PROMPT_POLICY_VERSION}",
        "prompt_contract": PROMPT_CONTRACT_VERSION,
        "execution_profiles": hashlib.sha256(",".join(sorted(EXECUTION_PROFILES)).encode("utf-8")).hexdigest(),
        "imagegen_output": IMAGEGEN_OUTPUT_CACHE_VERSION,
        "provider_route": hashlib.sha256(json.dumps(providers, sort_keys=True, default=str).encode("utf-8")).hexdigest(),
    }


def _load_generation_env(*paths: str) -> None:
    for path in paths:
        if path:
            load_env(path, override=False)


def _runtime_generation_references(job_path: Path, task: dict[str, Any]) -> list[dict[str, Any]]:
    from .image_reference_context import generation_reference_sources

    return [{**row, "path": str(row["path"])} for row in generation_reference_sources(
        {**task, "job_dir": str(job_path)}, plugin=None,
    )]
