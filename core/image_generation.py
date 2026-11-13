from __future__ import annotations

import hashlib
import json
import os
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from .api_registry import (
    image_provider_entries,
    image_provider_physical_identity,
)
from .candidate_state import (CandidateStateError,current_candidate,candidate_prompt_current,reprocess_candidate_publication,
    next_candidate_revision as _next_candidate_revision)
from .image_generation_executor import generate_one, finalize_candidate
from .image_response import recover_response, authorize_unknown_resend, unknown_result_resend_limit
from .image_provider_common import (
    CandidateCommitError,
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
    prompt_for_task,
    read_image_prompts,
    require_current_image_branch,
)
from .image_task_inputs import EXECUTION_PROFILES
from .image_provider_routing import apply_role_provider_policy, assign_provider_pool, provider_order
from .api_registry import image_provider_fallback_only
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


def generation_scope(selection) -> dict[str, Any]:
    """None means normal scope; an explicit empty/malformed permission never means all."""
    if selection is None:
        value = {'mode':'all', 'tasks':None}
    else:
        if not isinstance(selection, (list, tuple)) or not selection:
            raise ValueError('Generation task selection must be a nonempty explicit list')
        identities, seen = [], set()
        for item in selection:
            if (not isinstance(item, dict) or set(item) != {'child','role','task_fingerprint'}
                    or any(not isinstance(v,str) or not v for v in item.values())
                    or not re.fullmatch('[0-9a-f]{64}', item['task_fingerprint'])):
                raise ValueError('Generation selection only accepts child, role and current task_fingerprint')
            key = (item['child'], item['role'])
            if key in seen:
                raise ValueError('Duplicate generation task selection')
            seen.add(key); identities.append(dict(item))
        value = {'mode':'selected', 'tasks':identities}
    return {**value, 'selection_sha256':input_revision_id(value)}


def check_generation_scope(job: Path, selection, *, all_generation_tasks: bool = False) -> dict[str, Any]:
    """Read-only permission check; never reconcile receipts or restore candidates here."""
    from .status import load_status
    from .io import read_jsonl
    scope = generation_scope(selection)
    if type(all_generation_tasks) is not bool:
        raise ValueError('Full generation acknowledgement must be an explicit boolean')
    if all_generation_tasks and selection is not None:
        raise ValueError('--all-generation-tasks and a task selection are mutually exclusive')
    if selection is not None or all_generation_tasks:
        return scope
    previous = load_status(job).get('generation_execution_scope')
    if previous is None:
        # Current-job invocation evidence predates the optional state marker. It can
        # restrict expansion, never import an approval or authorize a new task.
        path = job / 'reports/progress_v1.jsonl'
        try:
            events = read_jsonl(path) if path.is_file() else []
            for event in reversed(events):
                if event.get('event') == 'run_environment_recorded' and 'generate' in event.get('environment',{}).get('stages',[]):
                    tasks = event['environment'].get('scope',{}).get('generation_tasks')
                    previous = generation_scope(None if tasks is None or tasks == [] else tasks)
                    break
        except (ValueError, OSError, TypeError, AttributeError) as exc:
            raise ValueError('Previous generation scope is unavailable; provide a task selection or --all-generation-tasks') from exc
    if previous is not None and previous != generation_scope(previous.get('tasks')):
        raise ValueError('Generation scope record is invalid; provide a task selection or --all-generation-tasks')
    if previous and previous['mode'] == 'selected':
        raise ValueError('Previous generation was limited; provide --generation-tasks again or explicitly use --all-generation-tasks')
    return scope


def select_generation_tasks(tasks: list[dict], allowed_children: set[str], selection=None) -> list[dict]:
    scope = generation_scope(selection)
    scoped = [row for row in tasks if row['child'] in allowed_children]
    if scope['mode'] == 'all':
        return scoped
    selected = []
    for item in scope['tasks']:
        matches = [row for row in scoped if all(row[k] == item[k] for k in item) and row['formation_status'] == 'ready']
        if len(matches) != 1:
            raise ValueError('Selected generation task is stale, unready or outside current RunScope')
        selected.append(matches[0])
    return selected


def preflight_generation_tasks(job: Path, plugin: ProductPlugin, selection=None, *, work_children=(), required_only=False,work_roles=()):
    """Read the same contracts at invocation admission and immediately before execution."""
    generation_scope(selection)
    allowed = scoped_child_set(job)
    tasks = [row for row in read_image_tasks(job, category_id=plugin.category_id)['tasks'] if row['child'] in allowed]
    from .run_scope import execution_children
    active=execution_children(job,work_children) if work_children else allowed
    selected = select_generation_tasks(tasks, active, selection)
    if work_roles:selected=[row for row in selected if row['role'] in work_roles]
    if required_only:
        from .release_manifest import build_release_manifest,required_task_keys
        required=required_task_keys(build_release_manifest(job_dir=job,plugin=plugin,work_children=work_children),work_children)
        selected=[row for row in selected if (row['child'],row['role']) in required]
    from .image_prompt_compiler import ImagePromptError
    try:
        require_current_image_branch(job, plugin, task_keys={(row['child'],row['role']) for row in selected})
    except ImagePromptError:
        if selection is not None:raise
        issues={}
        for row in selected:
            key=(row['child'],row['role'])
            try:require_current_image_branch(job,plugin,task_keys={key})
            except ImagePromptError as exc:issues[key]=str(exc)
        selected=[{**row,'formation_status':'blocked','formation_reason':issues[(row['child'],row['role'])],
                   'formation_reason_code':'current_input_changed'} if (row['child'],row['role']) in issues else row for row in selected]
    prompts = read_image_prompts(job, category_id=plugin.category_id,task_keys={(r['child'],r['role']) for r in selected if r['formation_status']=='ready'})
    if selection is not None:
        for task in selected:
            prompt_for_task(prompts, task)
    return tasks, selected, prompts


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
    task_selection: tuple[dict, ...] | None = None,
    all_generation_tasks: bool = False,
    work_children: tuple[str, ...] = (), required_only: bool = False, work_roles: tuple[str, ...] = (),
) -> dict[str, Any]:
    if production and task_selection is not None:
        raise ValueError('Production cannot use a debug task selection')
    job_path = Path(job_dir).resolve()
    _load_generation_env(config_path, str(load_job(job_path).get("config_path") or ""))
    scope = check_generation_scope(job_path, task_selection, all_generation_tasks=all_generation_tasks)
    task_selection = None if scope['tasks'] is None else tuple(scope['tasks'])
    del limit
    tasks, selected_tasks, prompt_artifact = preflight_generation_tasks(job_path, plugin, task_selection,work_children=work_children,required_only=required_only,work_roles=work_roles)
    selected_ids = {(row['child'],row['role']) for row in selected_tasks}
    not_run = [{'child':row['child'],'role':row['role'],'task_fingerprint':row['task_fingerprint'],
                'status':'not_run'} for row in tasks if (row['child'],row['role']) not in selected_ids]
    from .status import record_generation_scope
    record_generation_scope(job_path, scope, allow_expansion=all_generation_tasks)
    providers = provider_order(plugin)
    execution_revision = _generation_execution_revision(providers)

    runtime: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    blocked_by: list[dict[str, str]] = []
    for task in selected_tasks:
        if task["formation_status"] == "blocked":
            if task.get('formation_reason_code')=='current_input_changed':
                failures.append(_failure(task,owner='generation_preflight',status='blocked',error=task['formation_reason']))
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
        except (CandidateStateError, CandidateCommitError) as exc:
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
        if candidate and not candidate_prompt_current(task=task, candidate=candidate, prompt=prompt_row):
            failures.append(_failure({**task, "execution_revision": execution_revision}, owner="candidate_state",
                error="Candidate has no verified binding to the current task prompt; no automatic regeneration", status="blocked"))
            continue
        if candidate:
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
            saved = recover_response(runtime_task, check_pending=False)
            if saved:
                runtime_task.update(provider=saved['provider'], request_audit=saved['request_audit'], raw_response_path=saved['receipt_path'])
                runtime.append(runtime_task)
                continue
            if authorize_unknown_resend(runtime_task):
                runtime_task['request_outcome'] = 'unknown'
            recover_response(runtime_task)  # unresolved receipts still prohibit remote dispatch
            if state.get('status') == 'blocked' and state.get('execution_revision') == execution_revision:
                failures.append(_failure({**task, **state}, owner='generation',
                    error=str(state.get('error') or 'Generation contract is blocked'), status='blocked'))
                continue
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
                status=_generation_failure_status(exc), cause=exc,
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
        'not_run': not_run,
        'execution': {**scope, 'attempt_id':attempt_id,
            'requested_count':len(selected_tasks), 'completed_count':len(outcomes),
            'failed_count':len(failures), 'blocked_count':len(blocked_by), 'not_run_count':len(not_run),
            'status':'success' if len(outcomes)==len(selected_tasks) and not failures and not blocked_by
                     else 'partial_success' if outcomes else 'failed'},
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
    revision_mode: str = "targeted_edit", candidate_sha256: str = "", upscale_artifact_confirmed: bool = False,
) -> dict[str, Any]:
    if type(upscale_artifact_confirmed) is not bool:
        raise ValueError('Upscale artifact confirmation must be a boolean')
    if revision_mode == 'publication_reprocess' and not upscale_artifact_confirmed:
        raise ValueError('Publication reprocess requires --upscale-artifact-confirmed for the selected candidate')
    if upscale_artifact_confirmed and revision_mode != 'publication_reprocess':
        raise ValueError('Upscale artifact confirmation is only valid for publication_reprocess')
    if revision_mode not in {"targeted_edit", "full_redraw", "publication_reprocess"}:
        raise ValueError("Unknown image revision mode")
    if revision_mode=='publication_reprocess' and not re.fullmatch('[0-9a-f]{64}',str(candidate_sha256)):
        raise ValueError('Publication reprocess requires an explicit candidate SHA')
    if not str(reason or "").strip():
        raise RuntimeError("Revision requires a human-readable reason")
    job_path = Path(job_dir).resolve()
    _load_generation_env(config_path, str(load_job(job_path).get("config_path") or ""))
    require_current_image_branch(job_path, plugin, task_keys={(child,role)})
    prompt_artifact = read_image_prompts(job_path, category_id=plugin.category_id, task_keys={(child,role)})
    task = next(
        (
            row for row in read_image_tasks(job_path, category_id=plugin.category_id)["tasks"]
            if str(row.get("child")) == str(child) and str(row.get("role")) == str(role)
        ),
        None,
    )
    if not task or task.get("formation_status") != "ready":
        raise RuntimeError(f"Ready image task not found for {child}/{role}")
    if revision_mode=='publication_reprocess':
        candidate=reprocess_candidate_publication(job_path,task,candidate_sha256=candidate_sha256,reason=reason,
            task_prompt_fingerprint=prompt_for_task(prompt_artifact,task)['prompt_sha256'],
            upscale_artifact_confirmed=upscale_artifact_confirmed)
        from .image_upscale import UPSCALE_BACKEND,PUBLIC_IMAGE_SIZE
        revision=input_revision_id({'operation':'publication_reprocess','backend':UPSCALE_BACKEND,'size':PUBLIC_IMAGE_SIZE})
        return {'schema_version':'imagegen-revision-v1','tasks':[_candidate_task_result(task,candidate,execution_revision=revision)],
            'failures':[],'revision_mode':revision_mode,'revision_reason':str(reason).strip(),'requests_sent':0,
            'qa_required_for_candidate_sha256':candidate['candidate_sha256']}
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
    request_heading = {"targeted_edit": "TARGETED CANDIDATE EDIT", "full_redraw": "SOURCE EDIT REPLACEMENT REQUEST",
                       "initial": "EXPLICIT MISSING CANDIDATE REQUEST"}[mode]
    request_intro = {
        "targeted_edit": "Edit attachment 1 only for the listed issue. Preserve other correct product pixels, approved copy, composition and staging.",
        "full_redraw": "Re-execute the current edit contract from attachment 1 to produce a new candidate; keep the selected source product instances unchanged. Change design direction through the existing brand brief and brief stage, never by overriding that design here.",
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
    saved = recover_response(runtime_task, check_pending=False)
    if saved:
        runtime_task.update(provider=saved['provider'], request_audit=saved['request_audit'], raw_response_path=saved['receipt_path'])
        assigned = [runtime_task]
    else:
        if authorize_unknown_resend(runtime_task):
            runtime_task['request_outcome'] = 'unknown'
        recover_response(runtime_task)
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
        if mode == "targeted_edit" and previous_provider in ordered and not image_provider_fallback_only(previous_provider) and runtime_task.get('request_outcome') != 'unknown':
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
            if not candidate_prompt_current(task=task, candidate=candidate, prompt=prompt_row):
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
        f"Instruction: {' '.join(str(request_intro or '').split())} Address this reason within the task facts and family art direction: "
    )
    available = int(target_chars) - len(base_prompt) - len(prefix)
    if available < 1:
        raise RuntimeError("Revision reason cannot fit without discarding the immutable base prompt")
    if len(cleaned_reason) > available:
        raise RuntimeError(
            f"Revision reason is {len(cleaned_reason)} characters; maximum executable length is {available}"
        )
    return base_prompt + prefix + cleaned_reason


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
    recovery_attempts: set[str] = set()
    last_batch_progress_at = time.monotonic()
    capacity_errors: dict[str, ProviderQueueUnavailable] = {}
    remote_cap = _generation_worker_limit(tasks, workers)
    with ThreadPoolExecutor(max_workers=max(1, remote_cap)) as pool, ThreadPoolExecutor(max_workers=1) as local_pool:
        futures: dict[Any, dict[str, Any]] = {}
        local_futures: set[Any] = set()
        local_ready: set[int] = {id(task) for task in pending if task.get('raw_response_path')}
        while pending or futures:
            # A saved response waiting for local capacity must never re-enter remote dispatch.
            waiting_local = [task for task in pending if id(task) in local_ready]
            pending = [task for task in pending if id(task) not in local_ready]
            if waiting_local and not local_futures:
                task = waiting_local.pop(0)
                local_future = local_pool.submit(finalize_candidate, task, plugin=plugin)
                futures[local_future] = task
                local_futures.add(local_future)
                local_ready.discard(id(task))
            deferred = [task for task in pending if getattr(capacity_errors.get(
                str(task.get("logical_task_id") or f"{task.get('child')}/{task.get('role')}")), 'retry_at', 0) > time.time()]
            pending = [task for task in pending if not any(task is item for item in deferred)]
            current, pending = _dispatch_generation_batch(pending, workers,
                active=[task for future, task in futures.items() if future not in local_futures],
                occupied={(task.get('logical_task_id') or (task.get('child'), task.get('role')), task.get('candidate_revision', 0))
                          for task in futures.values()})
            room = max(0, remote_cap + 1 - len(futures) - len(waiting_local))
            pending = current[room:] + pending
            current = current[:room]
            pending.extend(waiting_local)
            pending.extend(deferred)
            futures.update({pool.submit(generate_one, task, plugin=plugin): task for task in current})
            done, _ = wait(futures, timeout=.25, return_when=FIRST_COMPLETED)
            round_made_progress = False
            for future in done:
                task = futures.pop(future)
                is_local = future in local_futures
                local_futures.discard(future)
                try:
                    completed_task = future.result()
                except Exception as exc:
                    task_id = str(task.get("logical_task_id") or f"{task.get('child')}/{task.get('role')}")
                    if provider_failure_class(exc) == 'candidate_commit' and task_id not in recovery_attempts:
                        try:
                            saved = recover_response(task)
                        except Exception:
                            saved = {}
                        if saved:
                            recovery_attempts.add(task_id)
                            recovered = {**task, 'provider': saved['provider'], 'request_audit': saved['request_audit'],
                                         'raw_response_path': saved['receipt_path']}
                            pending.append(recovered)
                            local_ready.add(id(recovered))
                            record_progress(task['job_dir'], 'image_saved_response_local_retry', child=task.get('child'), role=task.get('role'))
                            continue
                    if isinstance(exc, ProviderQueueUnavailable):
                        capacity_requeues[task_id] = capacity_requeues.get(task_id, 0) + 1
                        capacity_errors[task_id] = exc
                        pending.append(task)
                        if is_local:
                            local_ready.add(id(task))
                        if task.get("job_dir") and (
                            capacity_requeues[task_id] == 1
                            or capacity_requeues[task_id] % 20 == 0
                        ):
                            record_progress(
                                str(task["job_dir"]), "image_task_capacity_requeued",
                                logical_task_id=task_id, child=task.get("child"), role=task.get("role"),
                                capacity_round=capacity_requeues[task_id],
                                phase='local_finalize' if is_local else 'remote_admission',
                                reason=f'{type(exc).__name__}[{exc.provider_name}]: {exc}'[:500],
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
                    failure = _failure(failed_task, owner="generation_finalize" if is_local else "generation", error=f"{type(exc).__name__}: {exc}", status=status, cause=exc)
                    if status == "blocked":
                        failure["task_status"] = failure_task_status(failure)
                    failures.append(failure)
                    if on_failure is not None:
                        on_failure(failure)
                else:
                    if not is_local:
                        pending.append(completed_task)
                        local_ready.add(id(completed_task))
                        round_made_progress = True
                        continue
                    if on_success is not None:
                        on_success(completed_task)
                    completed.append(completed_task)
                    round_made_progress = True
            if round_made_progress:
                last_batch_progress_at = time.monotonic()
                capacity_errors.clear()
            retry_wait = max((getattr(exc, 'retry_at', 0) - time.time() for exc in capacity_errors.values()), default=0)
            # Known gateway cooldown is not unexplained lack of progress. Bound
            # the wait by the existing 600s ceiling and each task's real deadline.
            deadlines = [float(task[k]) for task in pending for k in ('deadline_monotonic', 'role_deadline_monotonic') if task.get(k) is not None]
            deadline_expired = bool(deadlines and time.monotonic() >= min(deadlines))
            can_wait = (retry_wait > 0 and time.monotonic() - last_batch_progress_at < 600
                        and not deadline_expired)
            if pending and not futures and not round_made_progress and not can_wait and (not current or all(
                str(task.get("logical_task_id") or f"{task.get('child')}/{task.get('role')}") in capacity_errors
                for task in pending
            )) and (deadline_expired or time.monotonic() - last_batch_progress_at >= _capacity_stall_budget_seconds()):
                stalled = [task for task in pending if not deadline_expired or any(
                    task.get(k) is not None and time.monotonic() >= float(task[k])
                    for k in ('deadline_monotonic', 'role_deadline_monotonic'))]
                pending = [task for task in pending if not any(task is item for item in stalled)]
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
                        owner="generation_local_capacity" if id(task) in local_ready else "generation_provider_capacity",
                        error=(
                            f"ProviderQueueUnavailable: capacity unavailable after {time.monotonic() - last_batch_progress_at:g} seconds or execution deadline reached; "
                            f"{(exc.provider_name + ': ' + str(exc)) if exc else 'no dispatch capacity'}"
                        ),
                        status="retryable",
                    )
                    failures.append(failure)
                    if on_failure is not None:
                        on_failure(failure)
                continue
            if pending and not round_made_progress:
                time.sleep(0.25)
    completed.sort(key=lambda row: (row["child"], row["role"]))
    return completed, failures


def _dispatch_generation_batch(
    pending: list[dict[str, Any]], requested_workers: int,
    *, active: list[dict[str, Any]] | None = None,
    occupied: set[tuple[Any, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fill free worker lanes; provider file leases remain cross-process authority."""
    if not pending:
        return [], []
    active = active or []
    cap = max(0, _effective_generation_workers(pending + active, requested_workers) - len(active))
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    used: dict[str, int] = {}
    from .api_registry import image_provider_resource_group, image_provider_supports_multiple_references
    from .image_reference_context import generation_attachment_count
    identities = {(task.get('logical_task_id') or (task.get('child'), task.get('role')), task.get('candidate_revision', 0)) for task in active}
    identities.update(occupied or set())
    for task in active:
        primary = _task_primary_provider(task)
        group = image_provider_resource_group(primary)
        used[group] = used.get(group, 0) + 1
    for task in pending:
        identity = (task.get('logical_task_id') or (task.get('child'), task.get('role')), task.get('candidate_revision', 0))
        if identity in identities:
            deferred.append(task)
            continue
        routes = list(dict.fromkeys([_task_primary_provider(task), *task.get('providers', []), *task.get('child_provider_reserve', [])]))
        references = task.get('generation_references', [])
        count = generation_attachment_count(references)
        routes = [name for name in routes if name and
                  (count <= 1 or image_provider_supports_multiple_references(name, count))]
        normal = [name for name in routes if not image_provider_fallback_only(name)]
        routes = ([name for name in routes if image_provider_fallback_only(name)]
                  if task.get('request_outcome') == 'unknown' else normal or routes)
        primary = next((name for name in routes if provider_concurrency_limit(name) <= 0 or
                        used.get(image_provider_resource_group(name), 0) < provider_concurrency_limit(name)), '')
        if routes and not primary:
            deferred.append(task)
            continue
        if len(selected) >= cap:
            deferred.append(task)
            continue
        if primary and primary != _task_primary_provider(task):
            task = {**task, 'providers': [primary, *[name for name in task.get('providers', []) if name != primary]],
                    'child_provider_primary': primary, 'capacity_reassigned': True}
        selected.append(task)
        identities.add(identity)
        if primary:
            group = image_provider_resource_group(primary)
            used[group] = used.get(group, 0) + 1
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
    return min(_generation_worker_limit(tasks, requested_workers), _memory_worker_cap(tasks))


def _generation_worker_limit(tasks: list[dict[str, Any]], requested_workers: int) -> int:
    """Stable executor ceiling; dispatch and leases own live resource admission."""
    task_count = max(1, len(tasks))
    requested = int(requested_workers or 0)
    requested_cap = requested if requested > 0 else task_count
    policy_cap = _policy_parallel_cap()
    provider_cap = 0
    from .api_registry import image_provider_resource_group
    groups = set()
    for provider in {name for task in tasks for name in
                     [_task_primary_provider(task), *task.get('providers', []), *task.get('child_provider_reserve', [])]} - {""}:
        group = image_provider_resource_group(provider)
        if group in groups:
            continue
        groups.add(group)
        limit = provider_concurrency_limit(provider)
        provider_cap += limit if limit > 0 else task_count
    provider_cap = provider_cap or 1
    return max(0, min(
        task_count,
        requested_cap,
        policy_cap,
        provider_cap,
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
    from .image_resources import image_memory_capacity
    return image_memory_capacity(tasks or [])


def _capacity_stall_budget_seconds() -> float:
    raw = str(os.environ.get("AMAZON_FACTORY_IMAGEGEN_QUEUE_STALL_SECONDS") or "120").strip()
    try:
        return max(0.0, min(float(raw), 600.0))
    except ValueError:
        return 120.0


def _generation_failure_status(exc: Exception) -> str:
    from .batch_ledger import AdmissionDenied
    if isinstance(exc,AdmissionDenied):return 'retryable'  # Capacity/authorization may recover; the ledger still decides every send.
    from .image_provider_common import ReceiptDispositionRequired
    if isinstance(exc, ReceiptDispositionRequired) or getattr(exc, "ambiguous", False):
        return "review"
    # Only a locally compiled immutable prompt/contract may deterministically
    # block the task.  Provider transport, configuration, response decoding,
    # and invalid returned pixels are provider-owned and must remain recoverable.
    return 'blocked' if provider_failure_class(exc) == 'contract' else 'retryable'


def _completed_task_result(task: dict[str, Any], *, execution_revision: str) -> dict[str, Any]:
    candidate = current_candidate(task["job_dir"], task, required=True)
    return _candidate_task_result(task, candidate, execution_revision=execution_revision)


def _failure(task: dict[str, Any], *, owner: str, error: str, status: str, cause: Exception | None = None) -> dict[str, Any]:
    runtime = {
        key: task[key]
        for key in (
            "transport_attempt", "provider_attempts", "execution_revision", "request_outcome", "request_audit",
        ) if key in task
    }
    from .image_provider_common import CandidateCommitError
    if status == 'review':
        runtime.update(reason_code='remote_result_unknown' if getattr(cause,'ambiguous',False) or task.get('request_outcome')=='unknown' else 'receipt_disposition_required',next_action='resolve_receipt',
                       resume_condition='explicit_receipt_disposition',remote_request_allowed=False)
    elif isinstance(cause, CandidateCommitError) or owner in {'generation_finalize','generation_local_capacity'}:
        runtime.update(reason_code='local_commit_pending',next_action='finalize_saved_response',
                       resume_condition='local_resource_or_io_recovered',remote_request_allowed=False)
    else:
        runtime.update(reason_code=getattr(cause,'reason_code',owner), next_action='repair_input' if status=='blocked' else 'retry_when_available',
                       resume_condition='validated_input_change' if status=='blocked' else 'capacity_health_and_budget_available')
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
            "provider_name", "task_prompt_fingerprint", "request_prompt_fingerprint", "transport_attempt", "provider_attempts", "reuse_evidence",
        ) if key in candidate},
        "execution_revision": execution_revision,
    }


def _provider_attempt_counts(task: dict[str, Any], *, selected: str, attempted: Any = None) -> dict[str, int]:
    counts = dict(task.get("provider_attempts") or {})
    if task.get("provider_attempts_exact") is True:
        return {str(name): max(0, int(value)) for name, value in counts.items()}
    attempted_names = [str(value) for value in attempted or [] if str(value or "").strip()]
    if selected and selected not in attempted_names:
        attempted_names.append(selected)
    for provider in attempted_names:
        counts[provider] = int(counts.get(provider) or 0) + 1
    return counts


def _generation_execution_revision(providers: list[str]) -> str:
    registry = {entry.name: entry for entry in image_provider_entries()}
    material: dict[str, Any] = {
        "prompt_contract": PROMPT_CONTRACT_VERSION,
        # Reference cardinality is part of the executable generation contract.
        # A task that was blocked under the old single-reference runtime must
        # be eligible for recovery after the current func dual-reference fix.
        "generation_reference_contract": "typed-reference-edit-base-v2",
        "routing_contract": "role-model-pool-v3-primary-fallback",
        'admission_contract':'work-unit-closing-capacity-v1',
        "unknown_result_policy": load_provider_policy().get('image_generation', {}).get('unknown_result_policy', {}),
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
            "fallback_only": raw.get("fallback_only") is True,
            "resource_group": raw.get("resource_group") or name,
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
