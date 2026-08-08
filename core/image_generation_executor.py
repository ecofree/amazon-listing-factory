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
    generation_reference_image_inputs,
    generation_reference_primary_path,
)
from .plugin import ProductPlugin
from .paths import resolve_job_owned_path
from .provider_policy import assert_provider_allowed, load_provider_policy
from .progress_trace import record_progress


def generate_one(task: dict[str, Any], *, plugin: ProductPlugin) -> dict[str, Any]:
    source_path = generation_reference_primary_path(task, plugin=plugin)
    output_path = resolve_job_owned_path(str(task.get("job_dir") or ""), str(task.get("output_path") or ""))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = str(task["prompt"])
    # Provider assignment selects one family primary and one sequential backup.
    # Do not append the reserve list here: different providers are intended to
    # share different image tasks, not regenerate the same image.
    providers = list(task.get("providers", []))[:2]
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
    reference_inputs = generation_reference_image_inputs(task, plugin=plugin)
    image_inputs = [row["bytes"] for row in reference_inputs]
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
    default_role_budget = min(600.0, max(120.0, sum(float(provider_timeout_seconds(name)) for name in providers[:2])))
    try:
        role_budget_seconds = max(60.0, float(os.environ.get("AMAZON_FACTORY_IMAGEGEN_ROLE_DEADLINE_SECONDS") or default_role_budget))
    except ValueError:
        role_budget_seconds = default_role_budget
    role_deadline = time.monotonic() + role_budget_seconds
    for provider_index, provider in enumerate(providers):
        if provider_run_circuit_open(provider_runtime_circuit_key(provider)):
            circuit_skipped_providers.append(provider)
            _record_generation_progress(task, "image_provider_attempt_skipped_circuit_open", provider)
            continue
        provider_started = time.monotonic()
        try:
            remaining = role_deadline - time.monotonic()
            if remaining < 30:
                raise ProviderTransportError(provider, "Image role deadline exhausted before provider attempt", status="timeout_failure")
            remaining_provider_count = max(1, len(providers) - provider_index)
            fallback_reserve = 120.0 * max(0, remaining_provider_count - 1)
            provider_budget = min(
                float(provider_timeout_seconds(provider)),
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

            data = generate_with_provider_retries(
                provider_name=provider,
                image_inputs=image_inputs,
                prompt=prompt,
                mask_bytes=None,
                attempt_observer=observe_transport_attempt,
                total_timeout_seconds=provider_budget,
                request_id=(
                    f"{task.get('logical_task_id') or ''}:"
                    f"{int(task.get('candidate_revision') or 0)}"
                ),
            )
            provider_duration = time.monotonic() - provider_started
            commit_task = {
                **task,
                "provider": provider,
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
                # A local capacity miss says nothing about provider health and
                # must return the same role to the batch scheduler. Switching
                # providers here turned a temporary slot shortage into a
                # false provider failure and unnecessarily spent the reserve.
                raise
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
            if failure_class in {"contract", "candidate_commit"}:
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
