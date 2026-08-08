from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from .io import file_sha256, read_json, utc_now, write_json
from .schema import SchemaValidationError, validate_data


JOB_STATE_SCHEMA_VERSION = 7
VALID_RUN_STATES = {
    "pending",
    "running",
    "awaiting_review",
    "partial_success",
    "failed",
    "success",
}
VALID_TASK_STATES = {
    "pending",
    "running",
    "retryable",
    "blocked",
    "review",
    "success",
}


class JobStateError(RuntimeError):
    pass


class JobLockError(JobStateError):
    pass


def job_run_lock(job_dir: str | Path):
    return _status_file_lock(Path(job_dir) / ".production.lock")


def status_path(job_dir: str | Path) -> Path:
    return Path(job_dir) / "job_state.json"


def load_status(job_dir: str | Path) -> dict[str, Any]:
    job_path = Path(job_dir)
    path = status_path(job_path)
    if not path.exists():
        legacy = job_path / "job_status.json"
        if legacy.exists():
            raise JobStateError(
                f"Legacy job state is not compatible with the current production contract: {legacy}. "
                "Create a new job; historical jobs are evidence only and are not migrated."
            )
        raise JobStateError(f"Missing current job state: {path}")
    data = read_json(path)
    if not isinstance(data, dict) or int(data.get("schema_version") or 0) != JOB_STATE_SCHEMA_VERSION:
        raise JobStateError(
            f"Unsupported job_state schema in {path}; create a new job. "
            "Historical jobs are evidence only and are not migrated."
        )
    try:
        validate_data(data, "job_state.schema.json", label=str(path))
    except SchemaValidationError as exc:
        raise JobStateError(f"Invalid current job state in {path}; create a new job: {exc}") from exc
    return data


def mark_interrupted_running(job_dir: str | Path, *, reason: str) -> list[str]:
    now = utc_now()
    interrupted: list[str] = []
    with _status_file_lock(status_path(job_dir)):
        data = load_status(job_dir)
        for stage, row in list(data.get("stages", {}).items()):
            if isinstance(row, dict) and row.get("status") == "running":
                interrupted.append(str(stage))
                data["stages"][stage] = {
                    **row,
                    "status": "failed",
                    "failed_at": now,
                    "message": reason,
                    "interrupted": True,
                }
        for logical_id, row in list(data.get("tasks", {}).items()):
            if isinstance(row, dict) and row.get("status") == "running":
                interrupted.append(str(logical_id))
                data["tasks"][logical_id] = {
                    **row,
                    "status": "retryable",
                    "updated_at": now,
                    "error": reason,
                    "interrupted": True,
                }
        if interrupted or data.get("status") == "running":
            data["status"] = "failed"
            data["updated_at"] = now
            data.setdefault("warnings", []).append({
                "stage": "run",
                "message": reason,
                "interrupted": sorted(set(interrupted)),
                "created_at": now,
            })
            write_json(status_path(job_dir), data)
    return sorted(set(interrupted))


def logical_task_id(
    owner_stage: str,
    *,
    child: str = "",
    source_id: str = "",
    role: str = "",
) -> str:
    stage = _task_component(owner_stage)
    if not stage:
        raise JobStateError("Logical task ID requires an owner stage")
    parts = [stage]
    if child:
        parts.append(_task_component(child))
    if source_id:
        parts.append(_task_component(source_id))
    if role:
        parts.append(_task_component(role))
    return ":".join(parts) if len(parts) > 1 else f"stage:{stage}"


def input_revision_id(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def begin_run(job_dir: str | Path) -> None:
    with _status_file_lock(status_path(job_dir)):
        data = load_status(job_dir)
        now = utc_now()
        data["status"] = "running"
        data.pop("status_reason", None)
        data["updated_at"] = now
        write_json(status_path(job_dir), data)


def finish_run_state(
    job_dir: str | Path,
    requested: str,
    *,
    reason: str = "",
) -> str:
    if requested not in VALID_RUN_STATES - {"running"}:
        raise JobStateError(f"Invalid terminal run state: {requested}")
    with _status_file_lock(status_path(job_dir)):
        data = load_status(job_dir)
        running = [name for name, row in data.get("stages", {}).items() if row.get("status") == "running"]
        if running:
            raise JobStateError(f"Cannot finish a job while stages are running: {', '.join(sorted(running))}")
        # The caller has already aggregated task/stage outcomes.  Do not let an
        # unrelated historical error rewrite a terminal result here: that made
        # a successful publish or awaiting-review run report partial_success and
        # made the CLI exit code disagree with the artifact it just wrote.
        # Superseded errors remain available in the status file for audit, but
        # they are not a second run-state authority.
        actual = requested
        data["status"] = actual
        data["updated_at"] = utc_now()
        if reason:
            data["status_reason"] = reason
        else:
            data.pop("status_reason", None)
        write_json(status_path(job_dir), data)
        return actual


def start_stage(job_dir: str | Path, stage: str, *, attempt_id: str, input_revision: str) -> None:
    if not attempt_id:
        raise JobStateError("Starting a stage requires an attempt ID")
    if len(str(input_revision or "")) != 64:
        raise JobStateError("Starting a stage requires its current input revision")
    now = utc_now()
    with _status_file_lock(status_path(job_dir)):
        data = load_status(job_dir)
        data.setdefault("stages", {})[stage] = {
            "status": "running",
            "attempt_id": attempt_id,
            "started_at": now,
        }
        data["stage"] = stage
        data["status"] = "running"
        data["updated_at"] = now
        write_json(status_path(job_dir), data)


def mark_stage(
    job_dir: str | Path,
    stage: str,
    *,
    artifact: tuple[str, str | Path] | None = None,
    attempt_id: str = "",
    input_revision: str,
    has_failures: bool = False,
) -> None:
    now = utc_now()
    with _status_file_lock(status_path(job_dir)):
        data = load_status(job_dir)
        task_rows = [
            row for row in (data.get("tasks") or {}).values()
            if isinstance(row, dict) and row.get("owner_stage") == stage and (not attempt_id or row.get("attempt_id") == attempt_id)
        ]
        has_failures = has_failures or any(row.get("status") in {"blocked", "retryable", "review"} for row in task_rows)
        record: dict[str, Any] = {
            "status": "partial_success" if has_failures else "success",
            "completed_at": now,
            "input_revision_id": input_revision,
        }
        if attempt_id:
            record["attempt_id"] = attempt_id
        if artifact:
            artifact_path = Path(artifact[1])
            artifact_record = {
                "kind": artifact[0],
                "path": str(artifact_path),
                "sha256": file_sha256(artifact_path),
            }
            record["artifact"] = artifact_record
            data.setdefault("artifacts", {})[artifact[0]] = artifact_record
        data.setdefault("stages", {})[stage] = record
        data["stage"] = stage
        data["updated_at"] = now
        write_json(status_path(job_dir), data)


def record_task_successes(
    job_dir: str | Path,
    *,
    owner_stage: str,
    attempt_id: str,
    tasks: Iterable[dict[str, Any]],
) -> None:
    rows = list(tasks)
    if not rows:
        return
    now = utc_now()
    with _status_file_lock(status_path(job_dir)):
        data = load_status(job_dir)
        for row in rows:
            logical_id, revision_id = _required_task_identity(row)
            _write_task(
                data,
                logical_id=logical_id,
                owner_stage=owner_stage,
                revision_id=revision_id,
                status="success",
                attempt_id=attempt_id,
                now=now,
                metadata=_task_runtime_metadata(row),
            )
            _resolve_task_errors(data, logical_id=logical_id, successful_revision_id=revision_id, now=now)
        data["updated_at"] = now
        write_json(status_path(job_dir), data)


def record_task_failures(
    job_dir: str | Path,
    *,
    owner_stage: str,
    attempt_id: str,
    failures: Iterable[dict[str, Any]],
) -> None:
    rows = [row for row in failures if isinstance(row, dict)]
    if not rows:
        return
    now = utc_now()
    with _status_file_lock(status_path(job_dir)):
        data = load_status(job_dir)
        for failure in rows:
            task = failure.get("task") if isinstance(failure.get("task"), dict) else {}
            logical_id, revision_id = _required_task_identity(task)
            message = str(failure.get("error") or "task failed")
            task_status = failure_task_status(failure)
            _write_task(
                data,
                logical_id=logical_id,
                owner_stage=owner_stage,
                revision_id=revision_id,
                status=task_status,
                attempt_id=attempt_id,
                now=now,
                error=message,
                failure_owner=str(failure.get("failure_owner") or owner_stage),
                metadata=_task_runtime_metadata(task),
            )
            _append_active_error(
                data,
                stage=owner_stage,
                logical_id=logical_id,
                revision_id=revision_id,
                message=message,
                attempt_id=attempt_id,
                details={},
                now=now,
            )
        data["updated_at"] = now
        write_json(status_path(job_dir), data)


def add_error(
    job_dir: str | Path,
    stage: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    attempt_id: str = "",
    input_revision: str = "",
    task_status: str = "blocked",
) -> None:
    now = utc_now()
    payload = dict(details or {})
    failures = [row for row in payload.pop("failures", []) if isinstance(row, dict)]
    successes = [row for row in payload.pop("successful_tasks", []) if isinstance(row, dict)]
    with _status_file_lock(status_path(job_dir)):
        data = load_status(job_dir)
        for row in successes:
            logical_id, revision_id = _required_task_identity(row)
            _write_task(
                data,
                logical_id=logical_id,
                owner_stage=stage,
                revision_id=revision_id,
                status="success",
                attempt_id=attempt_id,
                now=now,
                metadata=_task_runtime_metadata(row),
            )
            _resolve_task_errors(data, logical_id=logical_id, successful_revision_id=revision_id, now=now)
        if failures:
            for failure in failures:
                task = failure.get("task") if isinstance(failure.get("task"), dict) else {}
                logical_id, revision_id = _required_task_identity(task)
                error = str(failure.get("error") or failure.get("status") or message)
                task_status = failure_task_status(failure)
                _write_task(
                    data,
                    logical_id=logical_id,
                    owner_stage=stage,
                    revision_id=revision_id,
                    status=task_status,
                    attempt_id=attempt_id,
                    now=now,
                    error=error,
                    failure_owner=str(failure.get("failure_owner") or stage),
                    metadata=_task_runtime_metadata(task),
                )
                _append_active_error(
                    data,
                    stage=stage,
                    logical_id=logical_id,
                    revision_id=revision_id,
                    message=error,
                    attempt_id=attempt_id,
                    details=payload,
                    now=now,
                )
        else:
            logical_id = logical_task_id(stage)
            revision_id = input_revision or input_revision_id({"stage": stage, "message": message})
            _write_task(
                data,
                logical_id=logical_id,
                owner_stage=stage,
                revision_id=revision_id,
                status=task_status,
                attempt_id=attempt_id,
                now=now,
                error=message,
            )
            _append_active_error(
                data,
                stage=stage,
                logical_id=logical_id,
                revision_id=revision_id,
                message=message,
                attempt_id=attempt_id,
                details=payload,
                now=now,
            )
        data.setdefault("stages", {})[stage] = {
            "status": "failed",
            "task_status": task_status,
            "attempt_id": attempt_id,
            "message": message,
            "failed_at": now,
        }
        data["stage"] = stage
        data["status"] = "failed"
        data["updated_at"] = now
        write_json(status_path(job_dir), data)


def add_warning(job_dir: str | Path, stage: str, message: str) -> None:
    with _status_file_lock(status_path(job_dir)):
        data = load_status(job_dir)
        data.setdefault("warnings", []).append({"stage": stage, "message": message, "at": utc_now()})
        data["updated_at"] = utc_now()
        write_json(status_path(job_dir), data)


def _required_task_identity(row: dict[str, Any]) -> tuple[str, str]:
    logical_id = str(row.get("logical_task_id") or "").strip()
    revision_id = str(row.get("input_revision_id") or "").strip()
    if not logical_id or not revision_id:
        raise JobStateError("Task result requires logical_task_id and input_revision_id")
    return logical_id, revision_id


def task_record(job_dir: str | Path, logical_id: str) -> dict[str, Any]:
    row = load_status(job_dir).get("tasks", {}).get(logical_id)
    return dict(row) if isinstance(row, dict) else {}


def task_record_current(job_dir: str | Path, logical_id: str, revision_id: str) -> dict[str, Any]:
    row = task_record(job_dir, logical_id)
    return row if row.get("input_revision_id") == revision_id else {}


def _task_runtime_metadata(row: dict[str, Any]) -> dict[str, Any]:
    # Paths, prompt traces, provider identity, and attempt diagnostics belong
    # to CandidateManifestV5. Job state only tracks task recovery semantics.
    allowed = {
        "transport_attempt", "provider_attempts", "candidate_revision",
        "candidate_sha256", "execution_revision",
    }
    return {key: row[key] for key in allowed if key in row}


def failure_task_status(failure: dict[str, Any]) -> str:
    explicit = str(failure.get("task_status") or "").strip()
    if explicit in {"retryable", "blocked", "review"}:
        return explicit
    owner = str(failure.get("failure_owner") or "").strip()
    if owner in {"brief", "classification", "generation_preflight", "qa"}:
        return "blocked"
    error = str(failure.get("error") or "").lower()
    transient = (
        "timeout", "timed out", "429", "rate limit", "connection", "network",
        "temporarily unavailable", "not accessible", "502", "503", "504", "server error",
    )
    return "retryable" if any(token in error for token in transient) else "blocked"


def _write_task(
    data: dict[str, Any],
    *,
    logical_id: str,
    owner_stage: str,
    revision_id: str,
    status: str,
    attempt_id: str,
    now: str,
    error: str = "",
    failure_owner: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    if status not in VALID_TASK_STATES:
        raise JobStateError(f"Invalid task state: {status}")
    tasks = data.setdefault("tasks", {})
    previous = tasks.get(logical_id) if isinstance(tasks.get(logical_id), dict) else {}
    if previous and str(previous.get("input_revision_id") or "") != revision_id:
        data.setdefault("task_history", []).append(
            {**previous, "invalidated_at": now}
        )
        previous = {}
    attempts = int(previous.get("attempts") or 0)
    if attempt_id and previous.get("attempt_id") != attempt_id:
        attempts += 1
    row = {
        "logical_task_id": logical_id,
        "owner_stage": owner_stage,
        "status": status,
        "input_revision_id": revision_id,
        "attempts": attempts,
        "updated_at": now,
    }
    if attempt_id:
        row["attempt_id"] = attempt_id
    if error:
        row["error"] = error
    if failure_owner:
        row["failure_owner"] = failure_owner
    runtime = _task_runtime_metadata(previous)
    runtime.update(metadata or {})
    for key, value in runtime.items():
        if key not in row and value not in (None, "", [], {}):
            row[key] = value
    tasks[logical_id] = row


def _append_active_error(
    data: dict[str, Any],
    *,
    stage: str,
    logical_id: str,
    revision_id: str,
    message: str,
    attempt_id: str,
    details: dict[str, Any],
    now: str,
) -> None:
    data.setdefault("errors", [])
    remaining = []
    for row in data["errors"]:
        if not isinstance(row, dict) or row.get("logical_task_id") != logical_id:
            remaining.append(row)
        elif row.get("input_revision_id") != revision_id:
            data.setdefault("invalidated_errors", []).append(
                {**row, "invalidated_at": now, "invalidated_by_input_revision_id": revision_id}
            )
    data["errors"] = remaining
    error_id = input_revision_id(
        {"logical_task_id": logical_id, "input_revision_id": revision_id, "message": message}
    )
    data["errors"].append(
        {
            **details,
            "error_id": error_id,
            "stage": stage,
            "logical_task_id": logical_id,
            "input_revision_id": revision_id,
            "message": message,
            "attempt_id": attempt_id,
            "at": now,
        }
    )


def _resolve_task_errors(
    data: dict[str, Any],
    *,
    logical_id: str,
    successful_revision_id: str,
    now: str,
) -> None:
    remaining: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    for row in data.get("errors", []):
        if isinstance(row, dict) and row.get("logical_task_id") == logical_id:
            resolved.append(
                {
                    **row,
                    "resolved_at": now,
                    "resolved_by_input_revision_id": successful_revision_id,
                }
            )
        elif isinstance(row, dict):
            remaining.append(row)
    data["errors"] = remaining
    if resolved:
        data.setdefault("resolved_errors", []).extend(resolved)


def _task_component(value: str) -> str:
    return str(value or "").strip().replace("/", "_").replace(":", "_")


@contextmanager
def _status_file_lock(path: str | Path):
    status_file = Path(path)
    lock_path = status_file.with_suffix(status_file.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise JobLockError(f"Job state is locked by another process: {status_file}") from exc
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise JobLockError(f"Job state is locked by another process: {status_file}") from exc
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
