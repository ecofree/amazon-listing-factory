from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .candidate_state import CandidateStateError, commit_candidate_output
from .image_provider_common import (
    ImageGenerationError,
    CandidateCommitError, ImageOutputRejected,
    PromptCompileError,
    ProviderConfigurationError,
    ProviderTransportError,
    ProviderQueueUnavailable,
    provider_failure_class,
    provider_failure_code,
    provider_failure_status,
    provider_timeout_seconds,
    provider_concurrency_slot,
)
from .image_provider_routing import (
    generate_with_provider_retries,
    provider_runtime_circuit_key,
    record_provider_transport_attempt_event,
)
from .model_call_health import open_provider_run_circuit, provider_run_circuit_open
from .image_provider_transport import assert_imagegen_prompt_preflight
from .image_task_inputs import EXECUTION_PROFILES
from .image_reference_context import (
    generation_attachment_count,
    generation_reference_region_map_bytes,
    generation_reference_primary_path,
    generation_reference_sources,
)
from .api_registry import image_provider_supports_multiple_references, image_provider_fallback_only
from .plugin import ProductPlugin
from .paths import resolve_job_owned_path
from .provider_policy import assert_provider_allowed, load_provider_policy
from .progress_trace import record_progress
from .status import input_revision_id
from .image_response import recover_response, response_binding, response_directory, finish_response, materialize_response, authorize_unknown_resend, unknown_result_resend_limit
from .image_resources import reserve_image, release_image


def generate_one(task: dict[str, Any], *, plugin: ProductPlugin) -> dict[str, Any]:
    if authorize_unknown_resend(task):
        task['request_outcome'] = 'unknown'
    saved = recover_response(task)
    if saved:
        return {**task, 'provider': saved['provider'], 'request_audit': saved['request_audit'],
                'raw_response_path': saved['receipt_path'], 'provider_attempts': saved['request_audit'].get('provider_attempts', {})}
    deadlines = [float(task[key]) for key in ("deadline_monotonic", "role_deadline_monotonic") if task.get(key) is not None]
    if deadlines and time.monotonic() >= min(deadlines):
        raise ImageGenerationError("Image execution deadline exhausted before memory admission")
    lease = reserve_image(task)
    try:
        result = _generate_admitted(task, plugin=plugin)
    except Exception:
        release_image(task, lease)
        raise
    release_image(task, lease, buffered=True)
    return result


def _generate_admitted(task: dict[str, Any], *, plugin: ProductPlugin) -> dict[str, Any]:
    source_path = generation_reference_primary_path(task, plugin=plugin)
    output_path = resolve_job_owned_path(str(task.get("job_dir") or ""), str(task.get("output_path") or ""))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = str(task["prompt"])
    # Role-compatible routes remain ordered; local processing never re-enters this loop.
    providers = list(dict.fromkeys([
        *(str(name) for name in task.get("providers", []) if str(name).strip()),
        *(str(name) for name in task.get("child_provider_reserve", []) if str(name).strip()),
    ]))
    imagegen_mode = os.environ.get("AMAZON_FACTORY_IMAGEGEN_MODE", "").strip().lower()
    if imagegen_mode in {"copy", "mock"}:
        if _production_imagegen_task(task):
            raise ImageGenerationError("AMAZON_FACTORY_IMAGEGEN_MODE=copy/mock is disabled for production image generation")
        if output_path.exists():
            raise CandidateStateError(f"Immutable candidate output already exists without a current manifest: {output_path}")
        return {**task, 'provider': imagegen_mode, 'local_source_path': str(source_path)}
    if not providers:
        raise ImageGenerationError(f"No allowed image providers configured for {plugin.category_id}")
    if output_path.exists():
        raise CandidateStateError(f"Immutable candidate output already exists without a current manifest: {output_path}")
    reference_sources = generation_reference_sources(task, plugin=plugin)
    image_input_paths = [str(row["path"]) for row in reference_sources]
    attachment_count = generation_attachment_count(reference_sources)
    if attachment_count > 1:
        compatible = [name for name in providers if image_provider_supports_multiple_references(name, attachment_count)]
        if not compatible:
            raise ProviderConfigurationError(providers[0], "No assigned provider supports the required reference set; no request sent")
        providers = compatible
    region_map_bytes = (generation_reference_region_map_bytes(task, plugin=plugin)
                        if attachment_count > len(reference_sources) else None)
    execution_profile = str(task.get("execution_profile") or "")
    if execution_profile not in EXECUTION_PROFILES:
        raise ImageGenerationError(f"Unsupported generated-image execution profile: {execution_profile}")
    # A malformed task prompt is a task-contract failure, not a reason to
    # consume every image provider.  Provider-specific transport is handled
    # below; only those failures may move to another provider.
    try:
        assert_imagegen_prompt_preflight(prompt, providers)
    except ProviderConfigurationError:
        # Provider capability/configuration can change between queueing and
        # execution. It remains recoverable and must not become a task contract.
        raise
    except PromptCompileError:
        raise
    except Exception as exc:
        raise PromptCompileError(f"ImageTask prompt preflight failed: {exc}") from exc
    last_error: Exception | None = None
    attempted_failures: list[dict[str, Any]] = []
    global_policy = load_provider_policy()
    attempted_providers: list[str] = []
    circuit_skipped_providers: list[str] = []
    # Budget follows the bounded resend policy, never the size of the model pool.
    default_role_budget = min(1800.0, max(float(provider_timeout_seconds(name)) for name in providers) * (1 + unknown_result_resend_limit()) + 120.0)
    try:
        role_budget_seconds = max(60.0, float(os.environ.get("AMAZON_FACTORY_IMAGEGEN_ROLE_DEADLINE_SECONDS") or default_role_budget))
    except ValueError:
        role_budget_seconds = default_role_budget
    role_deadline = task.get("role_deadline_monotonic", time.monotonic() + role_budget_seconds)
    if task.get("deadline_monotonic") is not None:
        role_deadline = min(role_deadline, float(task["deadline_monotonic"]))
    if time.monotonic() >= role_deadline:
        raise ImageGenerationError("Image execution deadline exhausted before provider request")
    backups = [name for name in providers if image_provider_fallback_only(name)]
    normal = [name for name in providers if name not in backups]
    if task.get('request_outcome') == 'unknown' and not backups:
        raise ProviderConfigurationError(providers[0], 'Authorized resend requires an eligible fallback model')
    providers = normal + backups
    for provider in providers:
        if backups and (attempted_failures or task.get('request_outcome') == 'unknown') and provider not in backups:
            continue
        if provider in backups and normal and not attempted_failures and task.get('request_outcome') != 'unknown':
            continue
        if provider_run_circuit_open(provider_runtime_circuit_key(provider)):
            circuit_skipped_providers.append(provider)
            _record_generation_progress(task, "image_provider_attempt_skipped_circuit_open", provider)
            continue
        if role_deadline - time.monotonic() <= 1:
            raise ImageGenerationError("Image execution deadline exhausted before fallback request")
        provider_started = time.monotonic()
        try:
            remaining = role_deadline - time.monotonic()
            provider_budget = min(float(provider_timeout_seconds(provider)), remaining)
            assert_provider_allowed(provider, global_policy)
            attempted_providers.append(provider)
            _record_generation_progress(task, "image_provider_candidate_selected", provider)
            def observe_transport_attempt(
                current_provider: str, attempt: int, *, status: str,
                duration_seconds: float | None = None, error: str = "",
                failure_class: str = "",
            ) -> None:
                if status == "started":
                    task.setdefault("role_deadline_monotonic", time.monotonic() + role_budget_seconds)
                    counts = dict(task.get("provider_attempts") or {})
                    counts[current_provider] = int(counts.get(current_provider) or 0) + 1
                    task["provider_attempts"] = counts
                    task["provider_attempts_exact"] = True
                    request_audit['provider_attempts'] = counts
                try:
                    record_provider_transport_attempt_event(
                        output_path=output_path,
                        provider=current_provider,
                        task=task,
                        attempt=attempt,
                        status=status,
                        duration_seconds=duration_seconds,
                        error=error,
                        failure_class=failure_class,
                    )
                except Exception as ledger_exc:
                    _record_generation_progress(
                        task,
                        "image_provider_transport_ledger_write_failed",
                        current_provider,
                        status="audit_failure",
                        error=f"{type(ledger_exc).__name__}: {ledger_exc}",
                    )
                _record_generation_progress(
                    task,
                    f"image_provider_transport_attempt_{status}",
                    current_provider,
                    status=status,
                    error=error,
                )

            request_id = input_revision_id({"job": task["job_dir"], "task": task["task_fingerprint"],
                "revision": task.get("candidate_revision", 0), "prompt": prompt, "references": task["generation_references"]})
            request_audit: dict[str, Any] = {
                "request_id": request_id, "provider": provider,
                'response_binding': response_binding(task),
                'logical_task_id': task['logical_task_id'],
                "revision_mode": task.get("revision_mode") or "initial",
                "reference_count": attachment_count,
                "coordinate_frame": "candidate_in_place" if task.get("revision_mode") == "targeted_edit" else "original_source",
                "design_transfer": (task.get("image_direction") or {}).get("design_transfer", []),
                "reference_effect": "not_visually_evaluated",
                "references": [{"attachment_number": index, **{key: row[key] for key in
                    ("kind", "source_id", "sha256", "purpose", "evidence_ids")}}
                    for index, row in enumerate(reference_sources, 1)],
            }
            if region_map_bytes is not None:
                import hashlib
                request_audit['references'].append({
                    'attachment_number': attachment_count, 'kind': 'region_map',
                    'source_id': reference_sources[0]['source_id'],
                    'sha256': hashlib.sha256(region_map_bytes).hexdigest(),
                    'source_mask_sha256': reference_sources[0]['protected_mask']['sha256'],
                    'purpose': 'White preserves product; black permits only contracted edits.', 'evidence_ids': [],
                })
            receipt = generate_with_provider_retries(
                provider_name=provider,
                image_input_paths=image_input_paths,
                prompt=prompt,
                region_map_bytes=region_map_bytes,
                attempt_observer=observe_transport_attempt,
                total_timeout_seconds=provider_budget,
                request_id=request_id,
                request_audit=request_audit,
                response_directory=response_directory(task),
            )
            task['request_audit'] = request_audit
            from .imagegen_artifacts import assert_native_image, IMAGE_OUTPUT_MAX_BYTES
            try:
                if receipt.with_suffix('.bin').stat().st_size > IMAGE_OUTPUT_MAX_BYTES:
                    raise ImageOutputRejected('Native response exceeds output byte limit')
                assert_native_image(receipt.with_suffix('.bin').read_bytes())
            except ImageOutputRejected as exc:
                from .image_response import reject_response_output
                reject_response_output(receipt, str(exc))
                raise
            except Exception as exc:
                raise CandidateCommitError(f'Paid response saved; local native validation failed: {exc}') from exc
            provider_duration = time.monotonic() - provider_started
            task.pop('request_outcome', None)
            commit_task = {
                **task,
                "provider": provider,
                "request_audit": request_audit,
                "provider_duration_seconds": provider_duration,
                "attempted_providers": attempted_providers,
                "attempted_provider_failures": attempted_failures,
                "fallback_reason": "fallback_after_provider_failure" if attempted_failures else "",
                'raw_response_path': str(receipt),
            }
            _record_provider_event_audit_only(
                output_path=output_path,
                provider=provider,
                task=task,
                status="success",
                selected=True,
                duration_seconds=provider_duration,
                fallback_reason="fallback_after_provider_failure" if attempted_failures else "",
            )
            _record_generation_progress(task, 'image_response_saved', provider, provider_seconds=round(provider_duration, 3))
            return commit_task
        except Exception as exc:
            last_error = exc
            if getattr(exc, "ambiguous", False):
                task["request_audit"] = request_audit
                task["request_outcome"] = "unknown"
            failure_class = provider_failure_class(exc)
            if failure_class in {'candidate_commit','budget'}:
                raise
            if failure_class == "queue":
                if attempted_providers and attempted_providers[-1] == provider:
                    attempted_providers.pop()
                _record_generation_progress(
                    task,
                    "image_provider_capacity_unavailable",
                    provider,
                    status="queue_unavailable",
                    error=f"{type(exc).__name__}: {exc}",
                )
                # Capacity waits may use another normal route; failure-only
                # backups remain reserved for an actual failure or authorized unknown resend.
                continue
            attempted_failures.append({
                "provider": provider,
                "failure_class": failure_class,
                "failure_code": provider_failure_code(exc),
                "status": provider_failure_status(exc),
                "duration_seconds": round(time.monotonic() - provider_started, 3),
                "error": f"{type(exc).__name__}: {exc}",
            })
            _record_provider_event_audit_only(
                output_path=output_path,
                provider=provider,
                task=task,
                status=provider_failure_status(exc),
                error=f"{type(exc).__name__}: {exc}",
                failure_class=failure_class,
                duration_seconds=time.monotonic() - provider_started,
            )
            _record_generation_progress(
                task,
                "image_provider_attempt_failure",
                provider,
                status=provider_failure_status(exc),
                error=f"{type(exc).__name__}: {exc}",
            )
            if failure_class == "configuration":
                open_provider_run_circuit(provider_runtime_circuit_key(provider), task_id=str(task.get("logical_task_id") or ""))
            if getattr(exc, "ambiguous", False):
                available_backups = [name for name in backups if not provider_run_circuit_open(provider_runtime_circuit_key(name))]
                if available_backups and role_deadline - time.monotonic() > 1 and authorize_unknown_resend(task):
                    replacement = min(available_backups, key=lambda name: (attempted_providers.count(name), name == provider))
                    providers.append(replacement)
                    continue
                break
            if failure_class == "contract" or (provider in backups and failure_class != "configuration"):
                # Neither an immutable task-contract failure nor a local
                # artifact-commit failure can be repaired by spending a backup
                # provider call.
                break
    if last_error is not None:
        try:
            setattr(last_error, "attempted_providers", list(attempted_providers))
            setattr(last_error, "attempted_provider_failures", list(attempted_failures))
        except Exception:
            pass
        raise last_error
    if circuit_skipped_providers:
        raise ProviderConfigurationError(
            str(circuit_skipped_providers[0]),
            "All eligible providers are already circuit-open for this run: " + ", ".join(circuit_skipped_providers),
        )
    raise ImageGenerationError(f"All providers failed for {task['child']}/{task['role']}")


def finalize_candidate(task: dict[str, Any], *, plugin: ProductPlugin) -> dict[str, Any]:
    """A stalled decoder, stream or native subprocess cannot outlive local finalization."""
    import multiprocessing
    import queue
    import psutil
    from .process_lock import stop_process
    deadline = min(time.monotonic() + 120, float(task.get('deadline_monotonic') or float('inf')))
    if time.monotonic() >= deadline:
        raise CandidateCommitError('Local finalization deadline exhausted; receipt retained')
    context = multiprocessing.get_context('spawn')
    output = context.Queue(maxsize=1)
    process = context.Process(target=_finalize_worker, args=({**task, 'deadline_monotonic': deadline}, output))
    created = None
    try:
        process.start()
        created = psutil.Process(process.pid).create_time()
        while time.monotonic() < deadline:
            try:
                result = output.get(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
                if result['ok']:
                    return result['task']
                if result.get('waiting'):
                    raise ProviderQueueUnavailable('host_image_finalize', result['error'])
                raise CandidateCommitError(result['error'])
            except queue.Empty:
                if not process.is_alive():
                    break
        raise CandidateCommitError('Local finalization stopped or exceeded deadline; reconcile saved receipt, no resend')
    finally:
        if created is not None:
            stop_process(process.pid, created)
        if process.pid:
            process.join(timeout=1)
        output.cancel_join_thread()
        output.close()


def _finalize_worker(task, output):
    try:
        output.put({'ok': True, 'task': _finalize_local(task, plugin=None)})
    except Exception as exc:
        output.put({'ok': False, 'waiting': isinstance(exc, ProviderQueueUnavailable),
                    'error': f'{type(exc).__name__}: {exc}'})


def _finalize_local(task: dict[str, Any], *, plugin: ProductPlugin) -> dict[str, Any]:
    del plugin
    started = time.monotonic()
    waiting = False
    lease = ''
    try:
        from .candidate_state import current_candidate
        if not current_candidate(task['job_dir'], task, revision=int(task.get('candidate_revision') or 0)):
            receipt = Path(task['raw_response_path']) if task.get('raw_response_path') else None
            if receipt:
                saved = recover_response(task)
                if not saved or saved['receipt_path'] != str(receipt):
                    raise CandidateCommitError('Raw response no longer matches the current request')
            deadline = min(time.monotonic() + 120, float(task.get('deadline_monotonic') or float('inf')))
            with provider_concurrency_slot('host_image_finalize', deadline=deadline):
                lease = reserve_image(task, local=True)
                path = materialize_response(receipt, deadline=deadline) if receipt else Path(task['local_source_path'])
                from .imagegen_artifacts import IMAGE_OUTPUT_MAX_BYTES
                if path.stat().st_size > IMAGE_OUTPUT_MAX_BYTES:
                    raise ImageOutputRejected('Saved native response exceeds byte limit; no automatic resend')
                commit_candidate_output(task['job_dir'], {**task, 'deadline_monotonic': deadline}, path.read_bytes())
        if task.get('raw_response_path'):
            finish_response(Path(task['raw_response_path']), 'finalized')
        _record_generation_progress(task, 'image_candidate_committed', str(task.get('provider') or ''),
            local_finalize_seconds=round(time.monotonic() - started, 3))
        return {**task, 'bytes': Path(task['output_path']).stat().st_size}
    except Exception as exc:
        if isinstance(exc, ImageOutputRejected) and task.get('raw_response_path'):
            from .image_response import reject_response_output
            reject_response_output(Path(task['raw_response_path']), str(exc))
        waiting = isinstance(exc, ProviderQueueUnavailable)
        if isinstance(exc, (CandidateCommitError, ProviderQueueUnavailable)):
            raise
        raise CandidateCommitError(f'Local finalization failed; saved response retained: {type(exc).__name__}: {exc}') from exc
    finally:
        if lease:
            release_image(task, lease, buffered=waiting)


def _record_provider_event_audit_only(**event: Any) -> None:
    """Generation selection/finalization are progress, not a second health ledger."""
    task=event.get('task') if isinstance(event.get('task'),dict) else {}
    _record_generation_progress(task,'image_provider_execution',str(event.get('provider') or ''),
        status=str(event.get('status') or ''),error=str(event.get('error') or ''),
        selected=bool(event.get('selected')),duration_seconds=event.get('duration_seconds'),
        failure_class=str(event.get('failure_class') or ''))


def _record_generation_progress(
    task: dict[str, Any],
    event: str,
    provider: str,
    *,
    status: str = "",
    error: str = "",
    **metrics: Any,
) -> None:
    job_dir = str(task.get("job_dir") or "")
    if not job_dir:
        return
    record_progress(
        job_dir,
        event,
        logical_task_id=task.get("logical_task_id"),
        child=task.get("child"),
        role=task.get("role"),
        candidate_revision=task.get("candidate_revision"),
        provider_name=provider,
        status=status,
        error=error,
        **metrics,
    )


def _production_imagegen_task(task: dict[str, Any]) -> bool:
    if task.get("production_imagegen") is True:
        return True
    raw = os.environ.get("AMAZON_FACTORY_PRODUCTION_IMAGEGEN", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}
