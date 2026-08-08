from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import queue
import re
import threading
import time
import calendar
from pathlib import Path
from typing import Any

from . import model_router
from .api_registry import (
    dedupe_image_provider_names,
    image_provider_entries,
    image_provider_physical_identity,
)
from .image_provider_common import (
    ProviderConfigurationError,
    ProviderContentError,
    ProviderQueueUnavailable,
    ProviderTransportError,
    assert_imagegen_prompt_contract,
    is_transient_imagegen_error,
    normalize_provider_error,
    provider_attempts,
    provider_concurrency_slot,
    provider_failure_class,
    provider_failure_code,
    provider_failure_status,
    provider_retry_delay_seconds,
    provider_timeout_seconds,
)
from .image_provider_transport import generate_with_registry_image_provider, has_registry_image_provider
from .image_role_utils import role_key
from .io import read_json, write_json
from .model_call_health import (
    model_provider_cooldown_active,
    open_provider_run_circuit,
    provider_run_circuit_open,
    record_model_call_event,
    record_provider_run_result,
)
from .paths import resolve_job_owned_path
from .plugin import ProductPlugin
from .process_lock import process_file_lock
from .provider_policy import filter_not_forbidden_providers, load_provider_policy


PROVIDER_SUCCESS_LEDGER_SCHEMA_VERSION = 5
_LEDGER_LOCK = threading.RLock()
_CURRENT_IMAGE_PROVIDERS = (
    "aicost_gpt_image_2",
    "qc_yc_fixed",
    "cxk_fixed",
    # The primary pool is tried across different tasks. APImart and Krill
    # remain sequential reserves after the primary pool is exhausted.
)
_ROLE_PREFERENCE = {
    "scene": _CURRENT_IMAGE_PROVIDERS,
    "func": _CURRENT_IMAGE_PROVIDERS,
    "size": _CURRENT_IMAGE_PROVIDERS,
}


def provider_order(plugin: ProductPlugin) -> list[str]:
    available = model_router.provider_names_for_scope("image_generation")
    allowed = filter_not_forbidden_providers(available, plugin.merged_config(), global_policy=load_provider_policy())
    return dedupe_image_provider_names(allowed)


def apply_role_provider_policy(task: dict[str, Any], plugin: ProductPlugin) -> dict[str, Any]:
    role = role_key(str(task.get("role_family") or task.get("role") or ""))
    available = provider_order(plugin)
    if role == "main":
        preference = _CURRENT_IMAGE_PROVIDERS
    else:
        preference = _ROLE_PREFERENCE.get(role, ())
    preferred = [name for name in preference if name in available]
    ordered = [*preferred, *(name for name in available if name not in preferred)]
    unhealthy = _persistently_unhealthy_providers(task) | {
        name for name in ordered if _global_provider_cooldown_active(name)
    }
    healthy = [name for name in ordered if name not in unhealthy and not provider_run_circuit_open(provider_runtime_circuit_key(name))]
    task["category_id"] = plugin.category_id
    task["providers"] = healthy
    return task


def _global_provider_cooldown_active(provider: str) -> bool:
    identity = image_provider_physical_identity(provider)
    return model_provider_cooldown_active(
        scope="image_generation",
        provider=provider,
        model=str(identity.get("model") or provider),
    )


def _persistently_unhealthy_providers(task: dict[str, Any]) -> set[str]:
    job_value = str(task.get("job_dir") or "")
    if not job_value:
        return set()
    ledger = _read_ledger(project_provider_success_ledger_path(Path(job_value)))
    try:
        cooldown = max(60.0, float(os.environ.get("AMAZON_FACTORY_PROVIDER_CONFIG_COOLDOWN_SECONDS") or "3600"))
    except ValueError:
        cooldown = 3600.0
    now = time.time()
    blocked: set[str] = set()
    for entry in ledger.get("entries", {}).values():
        provider = str(entry.get("provider") or "") if isinstance(entry, dict) else ""
        if (
            not provider
            or entry.get("configuration_revision") != _provider_configuration_revision(provider)
            or _terminal_status(entry) != "configuration_failure"
        ):
            continue
        stamp = str(entry.get("updated_at") or "")
        try:
            age = now - calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
        except (TypeError, ValueError, OverflowError):
            age = 0.0
        if age < cooldown:
            blocked.add(provider)
    return {name for name in blocked if name}


def assign_provider_pool(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one healthy family provider, with one sequential reserve.

    Provider quality is a family-level visual concern.  One primary and one
    sequential reserve are retained for each child; a reserve is used only
    after the locked provider reaches a terminal failure.
    """
    child_rows: dict[str, list[tuple[int, dict[str, Any], list[str]]]] = {}
    for index, task in enumerate(tasks):
        candidates = [str(name) for name in (task.get("providers") or []) if str(name).strip()]
        ordered = _order_by_health(task, candidates)
        child_lane = str(task.get("child_provider_lane_key") or task.get("child") or "default")
        child_rows.setdefault(child_lane, []).append((index, task, ordered))
    result: list[dict[str, Any] | None] = [None] * len(tasks)
    for child_lane, rows in child_rows.items():
        # First select from the candidates common to the complete child.  In
        # normal production all roles share the same filtered registry list;
        # the union fallback only handles a role-specific capability gap.
        common = set(rows[0][2]) if rows else set()
        for _index, _task, ordered in rows[1:]:
            common.intersection_update(ordered)
        candidates = list(common) if common else list(dict.fromkeys(
            name for _index, _task, ordered in rows for name in ordered
        ))
        score_totals: dict[str, float] = {name: 0.0 for name in candidates}
        first_position: dict[str, int] = {}
        for _index, task, ordered in rows:
            scores = _provider_scores(task, ordered)
            for name in candidates:
                if name in scores:
                    score_totals[name] += float(scores[name])
                first_position.setdefault(name, ordered.index(name) if name in ordered else len(ordered))
        family_primary = max(
            candidates,
            key=lambda name: (score_totals.get(name, 0.0), -first_position.get(name, 999)),
            default="",
        )
        selected_primaries = [
            family_primary if family_primary in ordered else (ordered[0] if ordered else "")
            for _index, _task, ordered in rows
        ]
        family_provider_locked = bool(family_primary) and len(set(selected_primaries)) <= 1
        for index, task, ordered in rows:
            primary = family_primary if family_primary in ordered else (ordered[0] if ordered else "")
            backup = next((name for name in ordered if name != primary), "")
            eligible = [name for name in (primary, backup) if name]
            reserves = [name for name in ordered if name not in eligible]
            result[index] = {
                **task,
                "providers": eligible,
                "child_provider_reserve": reserves,
                "child_provider_primary": primary,
                "child_provider_backup": backup,
                "child_provider_lane": child_lane,
                "child_provider_lock": family_provider_locked,
            }
    return [row for row in result if row is not None]


def generate_with_provider_retries(
    *, provider_name: str, image_inputs: list[bytes], prompt: str,
    mask_bytes: bytes | None = None, attempt_observer: Any | None = None,
    total_timeout_seconds: float | None = None, request_id: str = "",
) -> bytes:
    """Run one physical provider with bounded attempts and a role deadline."""
    circuit = provider_runtime_circuit_key(provider_name)
    if provider_run_circuit_open(circuit):
        raise ProviderConfigurationError(provider_name, "Provider circuit is open for this run")
    try:
        total = float(total_timeout_seconds or os.environ.get("AMAZON_FACTORY_IMAGEGEN_ROLE_DEADLINE_SECONDS") or "480")
    except ValueError:
        total = 480.0
    run_deadline = time.monotonic() + max(30.0, total)
    last: Exception | None = None
    for attempt in range(1, provider_attempts(provider_name) + 1):
        attempt_started_at: float | None = None
        try:
            remaining = run_deadline - time.monotonic()
            if remaining <= 1:
                raise ProviderTransportError(provider_name, "Role provider deadline exhausted", status="timeout_failure")
            # A short acquisition attempt keeps worker threads responsive. A
            # pure capacity miss is propagated unchanged so the batch scheduler
            # requeues this task on the same assigned provider; it is not
            # permission to spend a backup provider call.
            queue_budget = max(1.0, min(5.0, remaining - 30.0))
            queue_deadline = time.monotonic() + queue_budget
            with provider_concurrency_slot(provider_name, deadline=queue_deadline):
                if provider_run_circuit_open(circuit):
                    raise ProviderConfigurationError(
                        provider_name,
                        "Provider circuit opened while this task waited for a concurrency slot",
                    )
                if attempt_observer:
                    attempt_started_at = time.monotonic()
                    attempt_observer(provider_name, attempt, status="started")
                request_remaining = run_deadline - time.monotonic()
                if request_remaining <= 1:
                    raise ProviderTransportError(provider_name, "Role request budget exhausted after queue wait", status="timeout_failure")
                attempt_timeout = min(float(provider_timeout_seconds(provider_name)), request_remaining)
                # The slot covers the real transport, not only queue
                # acquisition.  Releasing it before the request allowed more
                # processes than the configured provider capacity to submit
                # concurrently and caused avoidable 429/EOF failures.
                data = _generate_with_provider_deadline(
                    provider_name=provider_name,
                    image_inputs=image_inputs,
                    prompt=prompt,
                    mask_bytes=mask_bytes,
                    timeout_seconds=attempt_timeout,
                    request_id=request_id,
                )
            if attempt_observer:
                assert attempt_started_at is not None
                attempt_observer(
                    provider_name,
                    attempt,
                    status="success",
                    duration_seconds=max(0.0, time.monotonic() - attempt_started_at),
                )
            record_provider_run_result(circuit, "success")
            return data
        except Exception as exc:
            error = normalize_provider_error(provider_name, exc)
            last = error
            if attempt_observer and attempt_started_at is not None:
                attempt_observer(
                    provider_name,
                    attempt,
                    status=provider_failure_status(error),
                    duration_seconds=max(0.0, time.monotonic() - attempt_started_at),
                    error=f"{type(error).__name__}: {error}",
                    failure_class=provider_failure_class(error),
                )
            if isinstance(error, ProviderQueueUnavailable):
                # A full local semaphore says nothing about provider health.
                # Persist it at the logical task layer as retryable without
                # poisoning the physical-provider circuit.
                raise error from exc if error is not exc else error
            status = provider_failure_status(error)
            # An EOF after submission/polling is ambiguous: the remote task
            # may already exist. Do not poison the provider circuit while the
            # caller is still allowed to reconcile/retry the same request.
            circuit_opened = False if getattr(error, "ambiguous", False) else record_provider_run_result(
                circuit, status, threshold=2,
            )
            if isinstance(error, ProviderConfigurationError):
                open_provider_run_circuit(circuit)
            if circuit_opened or attempt >= provider_attempts(provider_name) or not is_transient_imagegen_error(error):
                raise error from exc if error is not exc else error
            delay = provider_retry_delay_seconds(provider_name, attempt)
            if time.monotonic() + delay >= run_deadline:
                break
            time.sleep(delay)
    assert last is not None
    raise last


def _generate_with_provider_deadline(
    *, provider_name: str, image_inputs: list[bytes], prompt: str,
    mask_bytes: bytes | None = None, timeout_seconds: float | None = None,
    request_id: str = "",
) -> bytes:
    assert_imagegen_prompt_contract(prompt, provider_name)
    if not has_registry_image_provider(provider_name):
        raise ProviderConfigurationError(provider_name, f"Unsupported registry image provider: {provider_name}")
    timeout = max(1.0, float(timeout_seconds or provider_timeout_seconds(provider_name)))
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_provider_worker,
        args=(provider_name, image_inputs, prompt, mask_bytes, request_id, result_queue),
        daemon=True,
    )
    deadline = time.monotonic() + timeout
    process.start()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderTransportError(provider_name, f"Provider exceeded its {timeout:.0f}-second attempt deadline", status="timeout_failure")
            try:
                result = result_queue.get(timeout=min(0.25, remaining))
                break
            except queue.Empty:
                if process.is_alive():
                    continue
                try:
                    result = result_queue.get_nowait()
                    break
                except queue.Empty as exc:
                    raise ProviderTransportError(provider_name, f"Provider subprocess exited without a result (exit_code={process.exitcode})") from exc
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(timeout=1)
        result_queue.cancel_join_thread()
        result_queue.close()
    if result.get("ok") is True:
        return bytes(result["data"])
    code = str(result.get("failure_code") or "")
    message = str(result.get("message") or "Provider subprocess failed")
    if code == "local_contract_mismatch":
        raise ProviderConfigurationError(provider_name, message)
    if code == "provider_transport_failure":
        raise ProviderTransportError(
            provider_name,
            message,
            status=str(result.get("status") or "transport_failure"),
            ambiguous=bool(result.get("ambiguous")),
        )
    raise ProviderContentError(provider_name, message)


def _provider_worker(
    provider: str, images: list[bytes], prompt: str, mask: bytes | None,
    request_id: str, output: Any,
) -> None:
    try:
        output.put({"ok": True, "data": generate_with_registry_image_provider(
            provider_name=provider, image_inputs=images, prompt=prompt, mask_bytes=mask,
            request_id=request_id,
        )})
    except Exception as exc:
        output.put({
            "ok": False,
            "failure_code": provider_failure_code(exc),
            "status": provider_failure_status(exc),
            "message": f"{type(exc).__name__}: {exc}",
            "ambiguous": bool(getattr(exc, "ambiguous", False)),
        })


def project_provider_success_ledger_path(job_path: Path) -> Path:
    resolved = Path(job_path)
    root = resolved.parent.parent if resolved.parent.name.lower() == "jobs" else resolved.parent
    return root / "runtime" / "provider_success_ledger.json"


def record_provider_generation_event(
    *, output_path: Path, provider: str, task: dict[str, Any], status: str,
    selected: bool = False, score: float | None = None, duration_seconds: float | None = None,
    error: str = "", fallback_reason: str = "", failure_class: str = "",
) -> None:
    job = _provider_event_job(task, output_path)
    category = str(task.get("category_id") or "")
    if not category:
        return
    path = project_provider_success_ledger_path(job)
    with _LEDGER_LOCK, process_file_lock(path.with_suffix(".lock")):
        ledger = _read_ledger(path)
        entry = _current_entry(ledger, provider, category, role_key(str(task.get("role") or "")))
        if status != "started":
            entry["attempts"] += 1
        if status == "success":
            entry["successes"] += 1
        elif status != "started":
            entry["failures"] += 1
        if selected:
            entry["selected"] += 1
        if duration_seconds is not None:
            entry["last_duration_seconds"] = round(float(duration_seconds), 3)
            durations = list(entry.get("recent_duration_seconds") or [])
            durations.append(round(float(duration_seconds), 3))
            entry["recent_duration_seconds"] = durations[-12:]
        if error:
            entry["last_error"] = str(error)[:500]
        if status == "started":
            entry["active_started_at"] = _utc_now()
        else:
            entry.pop("active_started_at", None)
            entry["last_status"] = status
            entry["last_terminal_status"] = status
            entry["last_failure_class"] = failure_class
        entry["last_fallback_reason"] = fallback_reason
        if score is not None:
            entry["last_score"] = float(score)
        entry["updated_at"] = _utc_now()
        ledger["updated_at"] = entry["updated_at"]
        _write_ledger(path, ledger)
    record_model_call_event(
        scope="image_generation",
        provider=provider,
        model=str(image_provider_physical_identity(provider).get("model") or provider),
        status=status if status in {"started", "success", "timeout_failure", "transport_failure", "content_failure", "configuration_failure"} else "content_failure",
        protocol="image_generation", error=error,
    )


def record_provider_transport_attempt_event(
    *, output_path: Path, provider: str, task: dict[str, Any], attempt: int,
    status: str, duration_seconds: float | None = None, error: str = "",
    failure_class: str = "",
) -> None:
    """Persist one request attempt without conflating it with provider selection."""
    job = _provider_event_job(task, output_path)
    category = str(task.get("category_id") or "")
    if not category:
        return
    role = role_key(str(task.get("role") or ""))
    path = project_provider_success_ledger_path(job)
    attempt_key = "|".join((
        str(task.get("logical_task_id") or f"{task.get('child')}/{task.get('role')}"),
        str(task.get("candidate_revision") or 0),
        str(max(1, int(attempt))),
    ))
    now = _utc_now()
    with _LEDGER_LOCK, process_file_lock(path.with_suffix(".lock")):
        ledger = _read_ledger(path)
        entry = _current_entry(ledger, provider, category, role)
        active = entry.setdefault("active_transport_attempts", {})
        if status == "started":
            active[attempt_key] = {"attempt": int(attempt), "started_at": now}
        else:
            active.pop(attempt_key, None)
            entry["transport_attempts"] = int(entry.get("transport_attempts") or 0) + 1
            terminal_key = "transport_successes" if status == "success" else "transport_failures"
            entry[terminal_key] = int(entry.get(terminal_key) or 0) + 1
            entry["last_transport_terminal_status"] = status
            entry["last_transport_failure_class"] = failure_class
            if duration_seconds is not None:
                entry["last_transport_duration_seconds"] = round(float(duration_seconds), 3)
            if error:
                entry["last_transport_error"] = str(error)[:500]
            recent = list(entry.get("recent_transport_attempts") or [])
            recent.append({
                "logical_task_id": str(task.get("logical_task_id") or ""),
                "candidate_revision": int(task.get("candidate_revision") or 0),
                "attempt": int(attempt),
                "status": status,
                "failure_class": failure_class,
                "duration_seconds": round(float(duration_seconds or 0.0), 3),
                "finished_at": now,
            })
            entry["recent_transport_attempts"] = recent[-40:]
        entry["updated_at"] = now
        ledger["updated_at"] = now
        _write_ledger(path, ledger)


def record_provider_quality_score(
    job_path: str | Path, *, category_id: str, child: str, role: str,
    candidate_path: str, score: int | float, reason_tags: list[str] | None = None,
) -> None:
    from .candidate_state import current_candidate
    from .image_tasks import read_image_tasks
    job = Path(job_path).resolve()
    task = next((
        row for row in read_image_tasks(job, category_id=category_id)["tasks"]
        if str(row.get("child") or "") == str(child)
        and str(row.get("role") or "") == str(role)
    ), None)
    if not isinstance(task, dict):
        raise ValueError(f"No current ImageTaskV8 for provider quality score: {child}/{role}")
    candidate = current_candidate(job, task, required=True)
    try:
        output = resolve_job_owned_path(job, str(candidate.get("output_path") or candidate.get("candidate_path") or ""))
        requested = resolve_job_owned_path(job, str(candidate_path or ""))
    except ValueError as exc:
        raise ValueError("Provider quality score candidate path escapes the job") from exc
    if output != requested:
        raise ValueError("Provider quality score candidate does not match CandidateManifest")
    provider = str(candidate.get("provider_name") or "")
    if not provider or not category_id:
        raise ValueError("CandidateManifest has no provider provenance for quality scoring")
    path = project_provider_success_ledger_path(job)
    with _LEDGER_LOCK, process_file_lock(path.with_suffix(".lock")):
        ledger = _read_ledger(path)
        entry = _current_entry(ledger, provider, category_id, role_key(role))
        entry["human_quality_count"] = int(entry.get("human_quality_count") or 0) + 1
        entry["human_quality_score_total"] = round(float(entry.get("human_quality_score_total") or 0) + max(1, min(5, float(score))), 3)
        entry["last_child"] = child
        entry["last_role_name"] = role
        tags = entry.setdefault("quality_tags", {})
        for tag in reason_tags or []:
            clean = re.sub(r"[^a-z0-9_.-]+", "_", tag.casefold()).strip("_")
            if clean:
                tags[clean] = int(tags.get(clean) or 0) + 1
        entry["updated_at"] = _utc_now()
        ledger["updated_at"] = entry["updated_at"]
        _write_ledger(path, ledger)


def _order_by_health(task: dict[str, Any], providers: list[str]) -> list[str]:
    scores = _provider_scores(task, providers)
    order = {name: index for index, name in enumerate(providers)}
    ranked = sorted(providers, key=lambda name: (-scores[name], order[name]))
    current = [name for name in ranked if name in _CURRENT_IMAGE_PROVIDERS]
    reserve = [name for name in ranked if name not in _CURRENT_IMAGE_PROVIDERS]
    return [*current, *reserve] if current else reserve


def _provider_scores(task: dict[str, Any], providers: list[str]) -> dict[str, float]:
    if not str(task.get("job_dir") or "").strip():
        raise ValueError("Provider routing requires the current job_dir; routing without its health ledger is forbidden")
    job = Path(str(task["job_dir"]))
    ledger = _read_ledger(project_provider_success_ledger_path(job))
    category = str(task.get("category_id") or "")
    role = role_key(str(task.get("role") or ""))
    return {
        name: (
        _health_score(_ledger_entry_for_current_revision(ledger, name, category, role))
        + _recent_transport_health(ledger, name, category)
        )
        for name in providers
    }


def _recent_transport_health(ledger: dict[str, Any], provider: str, category: str) -> float:
    """Apply endpoint health across roles while leaving role quality separate."""
    rows = [
        row for row in (ledger.get("entries") or {}).values()
        if isinstance(row, dict)
        and str(row.get("provider") or "") == provider
        and str(row.get("category_id") or "") == category
        and row.get("configuration_revision") == _provider_configuration_revision(provider)
    ]
    if not rows:
        return 0.0
    latest = max(rows, key=lambda row: str(row.get("updated_at") or ""))
    if _terminal_status(latest) == "configuration_failure":
        return -5.0
    if latest.get("last_failure_class") == "transient":
        return -3.0
    return 0.0


def _health_score(entry: Any) -> float:
    if not isinstance(entry, dict):
        return 0.0
    attempts = int(entry.get("attempts") or 0)
    score = 0.0
    if 0 < attempts < 3 and _terminal_status(entry) != "configuration_failure":
        # One completed timeout is enough to stop leading the next task, but
        # it remains an eligible fallback and can recover after a success.
        score = -1.0 if entry.get("last_failure_class") == "transient" else 0.0
    elif attempts:
        score = (int(entry.get("successes") or 0) - int(entry.get("failures") or 0)) / attempts
    count = int(entry.get("human_quality_count") or 0)
    if count:
        score += ((float(entry.get("human_quality_score_total") or 0) / count) - 3.0) * 0.5
    if _terminal_status(entry) == "configuration_failure":
        score -= 5
    durations = sorted(float(value) for value in entry.get("recent_duration_seconds") or [] if float(value) > 0)
    duration = durations[min(len(durations) - 1, int(len(durations) * 0.9))] if durations else float(entry.get("last_duration_seconds") or 0)
    if duration > 240:
        score -= min(2.0, (duration - 240.0) / 240.0)
    if entry.get("last_failure_class") == "transient":
        score -= 1.0
    return score


def _read_ledger(path: Path) -> dict[str, Any]:
    try:
        data = read_json(path) if path.exists() else {}
    except Exception:
        data = {}
    return data if data.get("schema_version") == PROVIDER_SUCCESS_LEDGER_SCHEMA_VERSION else {"schema_version": PROVIDER_SUCCESS_LEDGER_SCHEMA_VERSION, "entries": {}}


def _write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger["schema_version"] = PROVIDER_SUCCESS_LEDGER_SCHEMA_VERSION
    write_json(path, ledger)


def _new_entry(provider: str, category: str, role: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "category_id": category,
        "role": role,
        "configuration_revision": _provider_configuration_revision(provider),
        "attempts": 0,
        "successes": 0,
        "failures": 0,
        "selected": 0,
    }


def _current_entry(ledger: dict[str, Any], provider: str, category: str, role: str) -> dict[str, Any]:
    entries = ledger.setdefault("entries", {})
    key = _ledger_key(provider, category, role)
    current_revision = _provider_configuration_revision(provider)
    entry = entries.get(key)
    if not isinstance(entry, dict) or entry.get("configuration_revision") != current_revision:
        entry = _new_entry(provider, category, role)
        entries[key] = entry
    return entry


def _ledger_entry_for_current_revision(
    ledger: dict[str, Any], provider: str, category: str, role: str,
) -> dict[str, Any] | None:
    entry = (ledger.get("entries") or {}).get(_ledger_key(provider, category, role))
    if not isinstance(entry, dict):
        return None
    return entry if entry.get("configuration_revision") == _provider_configuration_revision(provider) else None


def _provider_configuration_revision(provider: str) -> str:
    entry = next((row for row in image_provider_entries() if row.name == provider), None)
    credential_material = ""
    if entry is not None:
        credential_material = "\0".join((str(entry.api_key or ""), str(entry.bearer_token or "")))
    material = {
        "physical_identity": image_provider_physical_identity(provider),
        "credential_revision": hashlib.sha256(credential_material.encode("utf-8")).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def provider_runtime_circuit_key(provider: str) -> str:
    """Bind one run circuit to physical transport plus credential revision."""
    return f"image_generation:{_provider_configuration_revision(provider)}"


def _terminal_status(entry: dict[str, Any]) -> str:
    return str(entry.get("last_terminal_status") or entry.get("last_status") or "")


def _ledger_key(provider: str, category: str, role: str) -> str:
    return "|".join((provider, category, role))


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _provider_event_job(task: dict[str, Any], output_path: Path) -> Path:
    raw_job = str(task.get("job_dir") or "").strip()
    if not raw_job:
        raise ValueError("Provider event requires the current job_dir")
    job = Path(raw_job).resolve()
    expected = resolve_job_owned_path(job, str(task.get("output_path") or ""))
    actual = resolve_job_owned_path(job, output_path)
    if actual != expected:
        raise ValueError("Provider event output does not match the current generation task")
    return job
