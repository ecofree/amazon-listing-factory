from __future__ import annotations

import threading
import time
import urllib.error
import os
import calendar
from pathlib import Path
from .io import read_json, write_json
from .process_lock import process_file_lock


MODEL_CALL_HEALTH_SCHEMA_VERSION = 1
_LOCK = threading.RLock()
_RUN_CIRCUIT_LOCK = threading.RLock()
_RUN_OPEN_CIRCUITS: set[str] = set()
_RUN_CIRCUIT_TASKS: dict[str, str] = {}
_RUN_TRANSIENT_FAILURES: dict[str, int] = {}
_RUN_RETRY_AT: dict[str, float] = {}
_RUN_PROBE_USED: set[str] = set()


def reset_provider_run_circuits() -> None:
    with _RUN_CIRCUIT_LOCK:
        _RUN_OPEN_CIRCUITS.clear()
        _RUN_CIRCUIT_TASKS.clear()
        _RUN_TRANSIENT_FAILURES.clear()
        _RUN_RETRY_AT.clear()
        _RUN_PROBE_USED.clear()


def provider_run_circuit_open(provider: str, *, task_id: str = "") -> bool:
    del task_id
    key = str(provider or "").strip()
    with _RUN_CIRCUIT_LOCK:
        return key in _RUN_OPEN_CIRCUITS and (
            key not in _RUN_RETRY_AT or key in _RUN_PROBE_USED or time.monotonic() < _RUN_RETRY_AT[key])


def admit_provider_probe(provider: str) -> bool:
    """Reserve at most one post-cooldown request inside the existing health authority."""
    with _RUN_CIRCUIT_LOCK:
        if provider_run_circuit_open(provider):
            return False
        if provider in _RUN_OPEN_CIRCUITS:
            _RUN_PROBE_USED.add(provider)
        return True


def release_unused_provider_probe(provider: str) -> None:
    with _RUN_CIRCUIT_LOCK:
        if provider in _RUN_RETRY_AT:
            _RUN_PROBE_USED.discard(provider)


def open_provider_run_circuit(provider: str, *, task_id: str = "") -> None:
    key = str(provider or "").strip()
    if key:
        with _RUN_CIRCUIT_LOCK:
            _RUN_OPEN_CIRCUITS.add(key)
            _RUN_RETRY_AT.pop(key, None)
            _RUN_CIRCUIT_TASKS[key] = str(task_id or "").strip()


def record_provider_run_result(provider: str, status: str, *, threshold: int = 2) -> bool:
    key = str(provider or "").strip()
    if not key:
        return False
    normalized = str(status or "").strip()
    with _RUN_CIRCUIT_LOCK:
        if normalized == "success":
            _RUN_TRANSIENT_FAILURES.pop(key, None)
            if key in _RUN_RETRY_AT:
                _RUN_OPEN_CIRCUITS.discard(key)
                _RUN_RETRY_AT.pop(key, None)
            return key in _RUN_OPEN_CIRCUITS
        if normalized not in {"timeout_failure", "transport_failure"}:
            return key in _RUN_OPEN_CIRCUITS
        failures = int(_RUN_TRANSIENT_FAILURES.get(key) or 0) + 1
        _RUN_TRANSIENT_FAILURES[key] = failures
        if failures >= max(1, int(threshold)):
            _RUN_OPEN_CIRCUITS.add(key)
            _RUN_RETRY_AT.setdefault(key, time.monotonic() + 180.0)
        return key in _RUN_OPEN_CIRCUITS


def record_model_call_event(
    *,
    scope: str,
    provider: str,
    model: str,
    status: str,
    protocol: str = "",
    error: str = "",
) -> None:
    """Record model endpoint health in one project-level 30-day ledger."""

    scope = str(scope or "unknown").strip() or "unknown"
    provider = str(provider or "unknown").strip() or "unknown"
    model = str(model or "unknown").strip() or "unknown"
    status = str(status or "unknown").strip() or "unknown"
    path = model_call_health_ledger_path()
    key = f"{scope}|{provider}|{model}"
    now_ts = time.time()
    with _LOCK, process_file_lock(path.with_suffix(".lock")):
        try:
            ledger = read_json(path) if path.exists() else {}
        except Exception:
            ledger = {}
        entries = ledger.setdefault("entries", {})
        entry = entries.setdefault(
            key,
            {
                "scope": scope,
                "provider": provider,
                "model": model,
                "protocol": protocol,
                "attempts": 0,
                "successes": 0,
                "failures": 0,
            },
        )
        if status in _attempt_statuses():
            entry["attempts"] = int(entry.get("attempts") or 0) + 1
        if status == "success":
            entry["successes"] = int(entry.get("successes") or 0) + 1
        if status in _failure_statuses():
            entry["failures"] = int(entry.get("failures") or 0) + 1
            entry[f"{statuses_key(status)}"] = int(entry.get(statuses_key(status)) or 0) + 1
        if error:
            entry["last_error"] = str(error)[:500]
        events = entry.get("recent_events")
        if not isinstance(events, list):
            events = []
        events.append({"ts": now_ts, "status": status})
        cutoff = now_ts - 30 * 24 * 60 * 60
        recent = [item for item in events if isinstance(item, dict) and float(item.get("ts") or 0.0) >= cutoff][-300:]
        entry["recent_events"] = recent
        entry["recent_attempts"] = sum(1 for item in recent if str(item.get("status") or "") in _attempt_statuses())
        entry["recent_successes"] = sum(1 for item in recent if str(item.get("status") or "") == "success")
        entry["recent_failures"] = sum(1 for item in recent if str(item.get("status") or "") in _failure_statuses())
        entry["last_status"] = status
        entry["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))
        ledger["schema_version"] = MODEL_CALL_HEALTH_SCHEMA_VERSION
        ledger["decay_window_days"] = 30
        ledger["updated_at"] = entry["last_updated"]
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, ledger)


def model_call_health_ledger_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "runtime" / "model_call_health_ledger.json"


def model_provider_cooldown_active(*, scope: str, provider: str, model: str, now: float | None = None) -> bool:
    """Temporarily demote a recently failing endpoint without disabling future recovery."""
    path = model_call_health_ledger_path()
    try:
        ledger = read_json(path) if path.is_file() else {}
    except Exception:
        return False
    entry = (ledger.get("entries") or {}).get(f"{scope}|{provider}|{model}")
    if not isinstance(entry, dict):
        return False
    status = str(entry.get("last_status") or "")
    if status == "success":
        return False
    if status in {"auth_failure", "configuration_failure", "model_not_found", "request_failure"}:
        default, env_key = 3600.0, "AMAZON_FACTORY_PROVIDER_CONFIG_COOLDOWN_SECONDS"
    elif status in {"timeout_failure", "transport_failure", "rate_limit_failure"}:
        recent = entry.get("recent_events") if isinstance(entry.get("recent_events"), list) else []
        consecutive_transient = 0
        for event in reversed(recent):
            event_status = str(event.get("status") or "") if isinstance(event, dict) else ""
            if event_status not in {"timeout_failure", "transport_failure", "rate_limit_failure"}:
                break
            consecutive_transient += 1
        if consecutive_transient < 2:
            return False
        default, env_key = 180.0, "AMAZON_FACTORY_PROVIDER_TRANSIENT_COOLDOWN_SECONDS"
    else:
        return False
    try:
        cooldown = max(30.0, float(os.environ.get(env_key) or default))
        updated = calendar.timegm(time.strptime(str(entry.get("last_updated") or ""), "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError, OverflowError):
        return False
    return float(now if now is not None else time.time()) - updated < cooldown


def model_status_from_exception(exc: Exception, detail: str = "") -> str:
    text = f"{type(exc).__name__}: {exc} {detail}".lower()
    code = exc.code if isinstance(exc, urllib.error.HTTPError) else 0
    if code == 404 or "model_not_found" in text or "model not found" in text:
        return "model_not_found"
    if "401" in text or "403" in text or "unauthorized" in text or "forbidden" in text:
        return "auth_failure"
    if code == 400:
        return "request_failure"
    if code == 429 or "rate limit" in text or "too many requests" in text:
        return "rate_limit_failure"
    if "timeout" in text or "timed out" in text:
        return "timeout_failure"
    if isinstance(exc, (urllib.error.URLError, ConnectionError)) or "500" in text or "502" in text or "503" in text or "504" in text or "connection" in text:
        return "transport_failure"
    return "content_failure"


def statuses_key(status: str) -> str:
    return f"{str(status or 'failure').strip()}s"


def _attempt_statuses() -> set[str]:
    return {"success", *_failure_statuses()}


def _failure_statuses() -> set[str]:
    return {
        "auth_failure", "configuration_failure", "model_not_found", "request_failure",
        "rate_limit_failure", "timeout_failure", "transport_failure", "content_failure",
        "validation_failure",
    }
