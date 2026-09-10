from __future__ import annotations

import io
import os
import time
from typing import Any

from .candidate_state import CandidateStateError, commit_candidate_output
from .image_provider_common import (
    ImageGenerationError,
    PromptCompileError,
    ProviderConfigurationError,
    ProviderTransportError,
    provider_failure_class,
    provider_failure_code,
    provider_failure_status,
    provider_timeout_seconds,
    provider_concurrency_slot,
)
from .image_provider_routing import (
    generate_with_provider_retries,
    provider_runtime_circuit_key,
    record_provider_generation_event,
    record_provider_transport_attempt_event,
)
from .model_call_health import open_provider_run_circuit, provider_run_circuit_open
from .image_provider_transport import assert_imagegen_prompt_preflight
from .image_task_inputs import EXECUTION_PROFILES
from .image_reference_context import (
    generation_reference_mask_bytes,
    generation_reference_primary_path,
    generation_reference_sources,
)
from .api_registry import image_provider_supports_mask, image_provider_supports_multiple_references
from .plugin import ProductPlugin
from .paths import resolve_job_owned_path
from .provider_policy import assert_provider_allowed, load_provider_policy
from .progress_trace import record_progress
from .status import input_revision_id


def generate_one(task: dict[str, Any], *, plugin: ProductPlugin) -> dict[str, Any]:
    deadlines = [float(task[key]) for key in ("deadline_monotonic", "role_deadline_monotonic") if task.get(key) is not None]
    deadline = min([time.monotonic() + 5.0, *deadlines])
    if time.monotonic() >= deadline:
        raise ImageGenerationError("Image execution deadline exhausted before memory admission")
    with provider_concurrency_slot("host_image_memory", deadline=deadline):
        return _generate_admitted(task, plugin=plugin)


def _generate_admitted(task: dict[str, Any], *, plugin: ProductPlugin) -> dict[str, Any]:
    source_path = generation_reference_primary_path(task, plugin=plugin)
    output_path = resolve_job_owned_path(str(task.get("job_dir") or ""), str(task.get("output_path") or ""))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = str(task["prompt"])
    # Provider assignment locks a child to one ordered family lane.  The
    # reserve entries are the same lane's sequential fallbacks; omitting them
    # made a configured third provider unreachable after two content failures.
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
        commit_candidate_output(
            task["job_dir"],
            {**task, "provider": imagegen_mode},
            _finalize_candidate_bytes(source_path.read_bytes()),
        )
        return {**task, "provider": imagegen_mode, "bytes": output_path.stat().st_size}
    if not providers:
        raise ImageGenerationError(f"No allowed image providers configured for {plugin.category_id}")
    if output_path.exists():
        raise CandidateStateError(f"Immutable candidate output already exists without a current manifest: {output_path}")
    reference_sources = generation_reference_sources(task, plugin=plugin)
    image_input_paths = [str(row["path"]) for row in reference_sources]
    if len(image_input_paths) > 1:
        compatible = [name for name in providers if image_provider_supports_multiple_references(name, len(image_input_paths))]
        if not compatible:
            raise ProviderConfigurationError(providers[0], "No assigned provider supports the required reference set; no request sent")
        providers = compatible
    has_protected_mask = any(
        isinstance(row, dict) and isinstance(row.get("protected_mask"), dict)
        for row in reference_sources
    )
    protected_mask_bytes = (
        generation_reference_mask_bytes(task, plugin=plugin)
        if has_protected_mask
        else None
    )
    if protected_mask_bytes is not None:
        mask_providers = [provider for provider in providers if image_provider_supports_mask(provider)]
        if not mask_providers:
            raise ProviderConfigurationError(providers[0], "No assigned provider supports the supplied protected mask")
        providers = mask_providers
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
    # A role has one bounded production budget, not the sum of every provider's
    # maximum timeout.  The primary may use the full 420-second slow-provider
    # window, but at least two minutes remain for a configured fallback.
    default_role_budget = min(600.0, max(120.0, sum(float(provider_timeout_seconds(name)) for name in providers)))
    try:
        role_budget_seconds = max(60.0, float(os.environ.get("AMAZON_FACTORY_IMAGEGEN_ROLE_DEADLINE_SECONDS") or default_role_budget))
    except ValueError:
        role_budget_seconds = default_role_budget
    role_deadline = task.setdefault("role_deadline_monotonic", time.monotonic() + role_budget_seconds)
    if task.get("deadline_monotonic") is not None:
        role_deadline = min(role_deadline, float(task["deadline_monotonic"]))
    if time.monotonic() >= role_deadline:
        raise ImageGenerationError("Image execution deadline exhausted before provider request")
    for provider_index, provider in enumerate(providers):
        if provider_run_circuit_open(provider_runtime_circuit_key(provider)):
            circuit_skipped_providers.append(provider)
            _record_generation_progress(task, "image_provider_attempt_skipped_circuit_open", provider)
            continue
        if role_deadline - time.monotonic() <= 1:
            raise ImageGenerationError("Image execution deadline exhausted before fallback request")
        provider_started = time.monotonic()
        try:
            remaining = role_deadline - time.monotonic()
            remaining_provider_count = max(1, len(providers) - provider_index)
            fallback_reserve = 120.0 * max(0, remaining_provider_count - 1)
            provider_budget = min(
                float(provider_timeout_seconds(provider)),
                remaining,
                max(30.0, remaining - fallback_reserve),
            )
            assert_provider_allowed(provider, global_policy)
            attempted_providers.append(provider)
            _record_generation_progress(task, "image_provider_candidate_selected", provider)
            def observe_transport_attempt(
                current_provider: str, attempt: int, *, status: str,
                duration_seconds: float | None = None, error: str = "",
                failure_class: str = "",
            ) -> None:
                if status == "started":
                    counts = dict(task.get("provider_attempts") or {})
                    counts[current_provider] = min(2, int(counts.get(current_provider) or 0) + 1)
                    task["provider_attempts"] = counts
                    task["provider_attempts_exact"] = True
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
            request_audit: dict[str, Any] = {"request_id": request_id, "provider": provider}
            data = generate_with_provider_retries(
                provider_name=provider,
                image_input_paths=image_input_paths,
                prompt=prompt,
                mask_bytes=protected_mask_bytes,
                attempt_observer=observe_transport_attempt,
                total_timeout_seconds=provider_budget,
                request_id=request_id,
                request_audit=request_audit,
            )
            provider_duration = time.monotonic() - provider_started
            commit_task = {
                **task,
                "provider": provider,
                "request_audit": request_audit,
                "provider_duration_seconds": provider_duration,
                "attempted_providers": attempted_providers,
                "attempted_provider_failures": attempted_failures,
                "fallback_reason": "fallback_after_provider_failure" if attempted_failures else "",
            }
            commit_candidate_output(
                task["job_dir"], commit_task, _finalize_candidate_bytes(data),
            )
            _record_provider_event_audit_only(
                output_path=output_path,
                provider=provider,
                task=task,
                status="success",
                selected=True,
                duration_seconds=provider_duration,
                fallback_reason="fallback_after_provider_failure" if attempted_failures else "",
            )
            _record_generation_progress(task, "image_provider_attempt_success", provider)
            return {
                **task,
                "provider": provider,
                "provider_duration_seconds": provider_duration,
                "attempted_providers": attempted_providers,
                "attempted_provider_failures": attempted_failures,
                "bytes": output_path.stat().st_size,
            }
        except Exception as exc:
            last_error = exc
            if getattr(exc, "ambiguous", False):
                task["request_audit"] = request_audit
                task["request_outcome"] = "unknown"
            failure_class = provider_failure_class(exc)
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
                # Capacity is not provider health, but it is still a valid
                # reason to use this task's already-assigned backup. Holding
                # the task on the same saturated provider made independent
                # jobs wait until the batch stall budget expired even when a
                # configured reserve was idle.
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
            if getattr(exc, "ambiguous", False) or failure_class in {"contract", "candidate_commit"}:
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


def _record_provider_event_audit_only(**event: Any) -> None:
    """Provider quality telemetry must never change candidate authority."""
    try:
        record_provider_generation_event(**event)
    except Exception as exc:
        task = event.get("task") if isinstance(event.get("task"), dict) else {}
        _record_generation_progress(
            task,
            "image_provider_quality_ledger_write_failed",
            str(event.get("provider") or ""),
            status="audit_failure",
            error=f"{type(exc).__name__}: {exc}",
        )


def _record_generation_progress(
    task: dict[str, Any],
    event: str,
    provider: str,
    *,
    status: str = "",
    error: str = "",
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
    )


def _production_imagegen_task(task: dict[str, Any]) -> bool:
    if task.get("production_imagegen") is True:
        return True
    raw = os.environ.get("AMAZON_FACTORY_PRODUCTION_IMAGEGEN", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _finalize_candidate_bytes(data: bytes) -> bytes:
    """Normalize provider bytes without inventing resolution through interpolation."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as opened:
            # Candidate commit owns the single publication-size conversion.
            # Keep an already normalized PNG compressed bytestring intact so a
            # large provider response is not decoded and re-encoded twice.
            if opened.format == "PNG" and opened.mode == "RGB":
                width, height = opened.size
                if min(width, height) <= 0 or width != height:
                    raise ImageGenerationError("Generated image has an invalid canvas")
                return bytes(data)
            if opened.mode in {"RGBA", "LA"} or (opened.mode == "P" and "transparency" in opened.info):
                rgba = opened.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                background.alpha_composite(rgba)
                image = background.convert("RGB")
            else:
                image = opened.convert("RGB")
            if min(image.size) <= 0:
                raise ImageGenerationError("Generated image has an invalid canvas")
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue()
    except ImageGenerationError:
        raise
    except Exception as exc:
        raise ImageGenerationError(f"Final candidate conversion failed: {type(exc).__name__}: {exc}") from exc
