from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .api_registry import image_provider_identity_key, image_provider_physical_identity
from .imagegen_artifacts import (
    assert_image_output,
    imagegen_output_marker,
    provider_model,
    publish_staged_imagegen_output,
    replace_output,
    staged_imagegen_output,
)
from .image_upscale import (
    PUBLIC_IMAGE_SIZE,
    REALESRGAN_MODEL,
    UPSCALE_BACKEND,
    upscale_for_publication_with_backend,
)
from .image_provider_common import CandidateCommitError
from .io import file_sha256, read_json, write_json
from .paths import resolve_job_owned_path
from .image_reference_context import validate_reference_set


class CandidateStateError(CandidateCommitError):
    pass


CANDIDATE_MANIFEST_SCHEMA_VERSION = "candidate-manifest-v7-typed-edit-provenance"
_CANDIDATE_MANIFEST_FIELDS = {
    "schema_version", "child", "role", "logical_task_id", "input_revision_id",
    "task_fingerprint", "candidate_revision", "candidate_sha256", "candidate_path",
    "output_path", "staging_path", "output_width", "output_height", "provider_name",
    "provider_model", "provider_identity", "provider_physical", "provider_duration_seconds",
    "attempted_providers", "attempted_provider_failures", "fallback_reason", "upscale_backend",
    "task_prompt_fingerprint", "request_prompt_fingerprint", "prompt_path", "source_path",
    "source_sha256", "transport_attempt", "provider_attempts", "status",
    "generation_references", "edit_base_sha256", "edit_parent_candidate_sha256", "revision_mode", "request_audit",
}


def current_candidate(job_dir: str | Path, task: dict[str, Any], *, required: bool = False) -> dict[str, Any]:
    job_path = Path(job_dir).resolve()
    candidate = _recover_candidate_from_manifest(job_path, task)
    if candidate:
        return candidate
    if required:
        raise CandidateStateError(f"Current CandidateManifest is missing or stale: {task['child']}/{task['role']}")
    return {}


def candidate_current(job_dir: str | Path, task: dict[str, Any]) -> bool:
    return bool(current_candidate(job_dir, task))


def candidate_by_sha(job_dir: str | Path, task: dict[str, Any], candidate_sha256: str) -> dict[str, Any]:
    """Resolve an explicit choice within this task; never silently fall back."""
    job = Path(job_dir).resolve()
    directory = _manifest_path(job, task, 0).parent
    for path in sorted(directory.glob("candidate*.json")):
        match = re.fullmatch(r"candidate(0|[1-9]\d*)\.json", path.name)
        if not match:
            continue
        try:
            row = read_json(path)
        except (ValueError, OSError):
            continue
        if not isinstance(row, dict):
            continue
        if row.get("candidate_sha256") == candidate_sha256:
            if row.get("candidate_revision") != int(match[1]):
                raise CandidateStateError("Explicit candidate manifest revision disagrees with its filename")
            return _recover_bound_manifest(job, row, task)
    raise CandidateStateError("Explicit candidate SHA is not in the current task")


def write_candidate_manifest(
    job_dir: str | Path, task: dict[str, Any], *, candidate_bytes_path: Path | None = None,
    upscale_backend: str = UPSCALE_BACKEND,
) -> dict[str, Any]:
    job_path = Path(job_dir).resolve()
    output = _job_owned_path(job_path, str(task.get("candidate_path") or task.get("output_path") or ""))
    candidate_bytes = _job_owned_path(job_path, str(candidate_bytes_path or output))
    source = _job_owned_path(job_path, str(task.get("source_path") or ""))
    sha = file_sha256(candidate_bytes)
    output_width, output_height = _image_dimensions(candidate_bytes)
    revision = int(task.get("candidate_revision") or _candidate_revision_from_name(output.name, f"{task.get('task_fingerprint')}.candidate"))
    provider_name = str(task.get("provider") or "")
    provider_identity = image_provider_physical_identity(provider_name)
    source_sha = str(task.get("source_sha256") or "")
    references = [{**row, "path": _job_owned_path(job_path, row["path"]).relative_to(job_path).as_posix()}
                  for row in task.get("generation_references", [])]
    manifest = {
        "schema_version": CANDIDATE_MANIFEST_SCHEMA_VERSION,
        "child": str(task.get("child") or ""),
        "role": str(task.get("role") or ""),
        "logical_task_id": str(task.get("logical_task_id") or ""),
        "input_revision_id": str(task.get("input_revision_id") or ""),
        "task_fingerprint": str(task.get("task_fingerprint") or ""),
        "candidate_revision": revision,
        "candidate_sha256": sha,
        "candidate_path": output.relative_to(job_path).as_posix(),
        "output_path": output.relative_to(job_path).as_posix(),
        "staging_path": candidate_bytes.relative_to(job_path).as_posix() if candidate_bytes != output else "",
        "output_width": output_width,
        "output_height": output_height,
        "provider_name": provider_name,
        "provider_model": provider_model(provider_name),
        "provider_identity": provider_identity,
        "provider_physical": image_provider_identity_key(provider_identity),
        "provider_duration_seconds": _rounded_optional_float(task.get("provider_duration_seconds")),
        "attempted_providers": [str(value) for value in task.get("attempted_providers") or [] if str(value or "").strip()],
        "attempted_provider_failures": [
            dict(value) for value in task.get("attempted_provider_failures") or [] if isinstance(value, dict)
        ],
        "fallback_reason": str(task.get("fallback_reason") or ""),
        "upscale_backend": str(upscale_backend or UPSCALE_BACKEND),
        "task_prompt_fingerprint": str(task.get("task_prompt_fingerprint") or ""),
        "request_prompt_fingerprint": str(task.get("request_prompt_fingerprint") or ""),
        "prompt_path": str(task.get("prompt_path") or ""),
        "source_path": source.relative_to(job_path).as_posix(),
        "source_sha256": source_sha,
        "generation_references": references,
        "edit_base_sha256": str(task.get("edit_base_sha256") or ""),
        "edit_parent_candidate_sha256": str(task.get("edit_parent_candidate_sha256") or ""),
        "revision_mode": str(task.get("revision_mode") or "initial"),
        "request_audit": dict(task.get("request_audit") or {}),
        "transport_attempt": int(task.get("transport_attempt") or 0),
        "provider_attempts": dict(task.get("provider_attempts") or {}),
        "status": "candidate_ready",
    }
    _validate_manifest_binding(job_path, manifest, task)
    write_json(_manifest_path(job_path, task, revision), manifest)
    return manifest


def commit_candidate_output(job_dir: str | Path, task: dict[str, Any], data: bytes) -> dict[str, Any]:
    """Commit bytes through CandidateManifest before atomically publishing the final path."""
    job_path = Path(job_dir).resolve()
    output = _job_owned_path(job_path, str(task.get("candidate_path") or task.get("output_path") or ""))
    _job_owned_path(job_path, str(task.get("source_path") or ""))
    staging = staged_imagegen_output(output)
    _job_owned_path(job_path, str(staging))
    if output.exists():
        raise CandidateStateError(f"Immutable candidate already exists: {output}")
    if staging.exists():
        staging.unlink()
    # Providers commonly return 1024x1024.  Size the bytes before the
    # CandidateManifest is written so candidate, QA, publish and template all
    # refer to the exact same 1600x1600 publication artifact.
    upscale_started = time.monotonic()
    final_data, upscale_backend = upscale_for_publication_with_backend(data)
    if isinstance(task.get("request_audit"), dict):
        task["request_audit"]["upscale_seconds"] = round(time.monotonic() - upscale_started, 3)
    replace_output(staging, final_data)
    assert_image_output(staging)
    manifest = write_candidate_manifest(
        job_path, task, candidate_bytes_path=staging, upscale_backend=upscale_backend,
    )
    publish_staged_imagegen_output(staging, output)
    if file_sha256(output) != manifest["candidate_sha256"]:
        raise CandidateStateError("Candidate commit changed output bytes")
    write_json(imagegen_output_marker(output), _marker_from_manifest(manifest))
    return manifest


def _image_dimensions(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return int(image.width), int(image.height)


def _recover_candidate_from_manifest(job_path: Path, task: dict[str, Any]) -> dict[str, Any]:
    manifest_dir = _job_owned_path(
        job_path,
        str(
            Path("reports") / "candidate_manifests" / str(task.get("child") or "")
            / str(task.get("role") or "") / str(task.get("task_fingerprint") or "")
        ),
    )
    if not manifest_dir.is_dir():
        return {}
    candidates = list(manifest_dir.glob("candidate*.json"))
    invalid = [path for path in candidates if not re.fullmatch(r"candidate(?:0|[1-9]\d*)\.json", path.name)]
    if invalid:
        raise CandidateStateError(f"CandidateManifest filename is invalid: {invalid[0]}")
    manifests = sorted(
        candidates,
        key=lambda path: _candidate_revision_from_name(path.name, "candidate"),
        reverse=True,
    )
    if not manifests:
        return {}
    # The highest revision is the only current candidate authority. A corrupt
    # or incomplete newer revision must not silently resurrect an older image.
    highest = manifests[0]
    expected_revision = _candidate_revision_from_name(highest.name, "candidate")
    try:
        manifest = read_json(highest)
        if int(manifest.get("candidate_revision") or 0) != expected_revision:
            raise CandidateStateError("CandidateManifest filename revision disagrees with its content")
        return _recover_bound_manifest(job_path, manifest, task)
    except CandidateStateError:
        raise
    except Exception as exc:
        raise CandidateStateError(f"Current CandidateManifest is corrupt: {highest}") from exc


def _recover_bound_manifest(job_path: Path, manifest: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    _validate_manifest_binding(job_path, manifest, task)
    output = _job_owned_path(job_path, str(manifest.get("candidate_path") or manifest.get("output_path") or ""))
    staging = _job_owned_path(job_path, str(manifest.get("staging_path") or "")) if manifest.get("staging_path") else None
    candidate_bytes = output if output.is_file() else staging
    if candidate_bytes is None or not candidate_bytes.is_file():
        raise CandidateStateError("CandidateManifest bytes are missing")
    assert_image_output(candidate_bytes)
    sha = file_sha256(candidate_bytes)
    if sha != manifest.get("candidate_sha256"):
        raise CandidateStateError("CandidateManifest bytes changed")
    dimensions = _image_dimensions(candidate_bytes)
    if (int(manifest.get("output_width") or 0), int(manifest.get("output_height") or 0)) != dimensions:
        raise CandidateStateError("CandidateManifest image dimensions changed")
    upscale_backend = str(manifest.get("upscale_backend") or "")
    if dimensions != (PUBLIC_IMAGE_SIZE, PUBLIC_IMAGE_SIZE) or not (
        upscale_backend in {UPSCALE_BACKEND, REALESRGAN_MODEL}
        or upscale_backend.startswith(f"{UPSCALE_BACKEND}:fallback_from_realesrgan:")
    ):
        raise CandidateStateError(
            f"CandidateManifest image is not the current {PUBLIC_IMAGE_SIZE}x{PUBLIC_IMAGE_SIZE} publication artifact"
        )
    if not output.is_file():
        publish_staged_imagegen_output(candidate_bytes, output)
    if file_sha256(output) != sha:
        raise CandidateStateError("Published candidate bytes changed")
    # The sidecar is a reconstructable transaction receipt only. CandidateManifest
    # is the sole currentness/provenance authority and a stale receipt can never
    # veto a valid committed candidate.
    receipt = _marker_from_manifest(manifest)
    marker_path = imagegen_output_marker(output)
    try:
        current_receipt = read_json(marker_path) if marker_path.is_file() else {}
    except Exception:
        current_receipt = {}
    if current_receipt != receipt:
        write_json(marker_path, receipt)
    return {
        "candidate_sha256": sha,
        "candidate_path": str(manifest.get("candidate_path") or output.relative_to(job_path)),
        "candidate_revision": int(manifest.get("candidate_revision") or 0),
        "provider_physical": str(manifest.get("provider_physical") or ""),
        "provider_name": str(manifest.get("provider_name") or ""),
        "task_prompt_fingerprint": str(manifest.get("task_prompt_fingerprint") or ""),
        "request_prompt_fingerprint": str(manifest.get("request_prompt_fingerprint") or ""),
        "prompt_path": str(manifest.get("prompt_path") or ""),
        "transport_attempt": int(manifest.get("transport_attempt") or 0),
        "provider_attempts": dict(manifest.get("provider_attempts") or {}),
        "state": "manifest_recovered",
        "output_path": output,
    }


def _validate_manifest_binding(job_path: Path, manifest: dict[str, Any], task: dict[str, Any]) -> None:
    if task.get("revision_mode") == "targeted_edit":
        from .image_tasks import read_image_tasks

        bound = [row for row in read_image_tasks(job_path)["tasks"]
                 if row["task_fingerprint"] == task["task_fingerprint"] and row["logical_task_id"] == task["logical_task_id"]]
        if len(bound) != 1:
            raise CandidateStateError("Targeted edit has no unique canonical ImageTask")
        task = bound[0]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != CANDIDATE_MANIFEST_SCHEMA_VERSION:
        raise CandidateStateError("CandidateManifest schema is stale")
    if set(manifest) != _CANDIDATE_MANIFEST_FIELDS:
        raise CandidateStateError("CandidateManifest fields do not match the current contract")
    expected = {
        "child": str(task.get("child") or ""),
        "role": str(task.get("role") or ""),
        "logical_task_id": str(task.get("logical_task_id") or ""),
        "input_revision_id": str(task.get("input_revision_id") or ""),
        "task_fingerprint": str(task.get("task_fingerprint") or ""),
        "source_sha256": str(task.get("source_sha256") or ""),
    }
    if any(str(manifest.get(key) or "") != value for key, value in expected.items()):
        raise CandidateStateError("CandidateManifest does not match ImageTaskV10")
    sha = str(manifest.get("candidate_sha256") or "")
    if len(sha) != 64 or not str(manifest.get("candidate_path") or ""):
        raise CandidateStateError("CandidateManifest has no committed candidate identity")
    if manifest.get("status") != "candidate_ready":
        raise CandidateStateError("CandidateManifest status is not current")
    candidate = _job_owned_path(job_path, str(manifest["candidate_path"]))
    output = _job_owned_path(job_path, str(manifest.get("output_path") or ""))
    if candidate != output:
        raise CandidateStateError("CandidateManifest output paths disagree")
    revision = int(manifest.get("candidate_revision") or 0)
    expected_name = f"{task.get('task_fingerprint')}.candidate{revision}.png"
    if candidate.name != expected_name:
        raise CandidateStateError("CandidateManifest revision does not match its output filename")
    if manifest.get("staging_path"):
        _job_owned_path(job_path, str(manifest["staging_path"]))
    manifest_source = _job_owned_path(job_path, str(manifest.get("source_path") or ""))
    task_source = _job_owned_path(job_path, str(task.get("source_path") or ""))
    if manifest_source != task_source:
        raise CandidateStateError("CandidateManifest source path changed")
    references = manifest["generation_references"]
    try:
        validate_reference_set(references, child=manifest["child"], edit_base_sha256=manifest["edit_base_sha256"])
    except ValueError as exc:
        raise CandidateStateError(str(exc)) from exc
    for ref in references:
        path = _job_owned_path(job_path, ref["path"])
        if not path.is_file() or file_sha256(path) != ref["sha256"]:
            raise CandidateStateError("Candidate input reference is missing or changed")
    mode = manifest["revision_mode"]
    if mode not in {"initial", "targeted_edit", "full_redraw"}:
        raise CandidateStateError("Candidate revision mode is invalid")
    parent = manifest["edit_parent_candidate_sha256"]
    if mode == "targeted_edit":
        if len(parent) != 64 or parent != manifest["edit_base_sha256"]:
            raise CandidateStateError("Targeted edit is not bound to its parent candidate")
    elif parent or manifest["edit_base_sha256"] != task["edit_base_sha256"]:
        raise CandidateStateError("Initial/full-redraw base must be the task's observed edit view")
    expected_refs = [{**ref, "path": _job_owned_path(job_path, ref["path"]).relative_to(job_path).as_posix()}
                     for ref in task["generation_references"]]
    if mode == "targeted_edit":
        original = {**expected_refs[0], "kind": "product_evidence", "purpose": "Original product structure and state evidence"}
        original.pop("protected_mask", None)
        if references[1:] != [original, *expected_refs[1:]]:
            raise CandidateStateError("Targeted edit auxiliary evidence differs from the task")
        match = re.fullmatch(r"candidate_(\d+)", references[0]["source_id"])
        if not match or int(match[1]) >= revision:
            raise CandidateStateError("Targeted edit parent is not an earlier candidate")
        parent_manifest = read_json(_manifest_path(job_path, task, int(match[1])))
        if parent_manifest.get("candidate_sha256") != parent or _job_owned_path(job_path, str(parent_manifest.get("candidate_path") or "")) != _job_owned_path(job_path, references[0]["path"]):
            raise CandidateStateError("Targeted edit parent manifest does not match its pixels")
    elif references != expected_refs:
        raise CandidateStateError("Candidate references differ from the task reference contract")
    audit = manifest["request_audit"]
    if not isinstance(audit, dict):
        raise CandidateStateError("Candidate request audit is malformed")
    sent = audit.get("inputs", [])
    if manifest.get("provider_name") not in {"copy", "mock"}:
        if audit.get("provider") != manifest["provider_name"] or audit.get("model") != manifest["provider_model"] or not audit.get("request_id"):
            raise CandidateStateError("Candidate request identity is inconsistent")
        if not isinstance(sent, list) or any(not isinstance(row, dict) for row in sent):
            raise CandidateStateError("Candidate actual-input evidence is malformed")
        if [row.get("original_sha256") for row in sent] != [row["sha256"] for row in references] or any(not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sent_sha256") or "")) for row in sent):
            raise CandidateStateError("Candidate has no matching actual-input transport evidence")
    identity = manifest.get("provider_identity") if isinstance(manifest.get("provider_identity"), dict) else {}
    if not identity or image_provider_identity_key(identity) != str(manifest.get("provider_physical") or ""):
        raise CandidateStateError("CandidateManifest provider identity is invalid")
    identity_model = str(identity.get("model") or identity.get("builtin") or "")
    if not str(manifest.get("provider_name") or "") or str(manifest.get("provider_model") or "") != identity_model:
        raise CandidateStateError("CandidateManifest provider provenance is inconsistent")
    if not _prompt_trace_current(job_path, manifest):
        raise CandidateStateError("CandidateManifest prompt trace is missing or changed")


def _marker_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    from .imagegen_artifacts import IMAGEGEN_OUTPUT_CACHE_VERSION

    return {
        "version": IMAGEGEN_OUTPUT_CACHE_VERSION,
        "output_sha256": str(manifest["candidate_sha256"]),
        "source_path": str(manifest.get("source_path") or ""),
        "source_sha256": str(manifest.get("source_sha256") or ""),
        "task_prompt_sha256": str(manifest.get("task_prompt_fingerprint") or ""),
        "request_prompt_sha256": str(manifest.get("request_prompt_fingerprint") or ""),
        "prompt_path": str(manifest.get("prompt_path") or ""),
        "provider": str(manifest.get("provider_name") or ""),
        "provider_model": str(manifest.get("provider_model") or ""),
        "provider_identity": dict(manifest.get("provider_identity") or {}),
        "task_fingerprint": str(manifest.get("task_fingerprint") or ""),
        "input_revision_id": str(manifest.get("input_revision_id") or ""),
        "upscale_backend": str(manifest.get("upscale_backend") or "legacy"),
    }


def _prompt_trace_current(job_path: Path, marker: dict[str, Any]) -> bool:
    raw = str(marker.get("prompt_path") or "").strip()
    expected = str(
        marker.get("request_prompt_sha256")
        or marker.get("request_prompt_fingerprint")
        or ""
    ).strip()
    if not raw or not expected:
        return False
    try:
        path = resolve_job_owned_path(job_path, raw)
    except ValueError:
        return False
    return path.is_file() and file_sha256(path) == expected


def _job_owned_path(job_path: Path, value: str) -> Path:
    if not str(value or "").strip():
        raise CandidateStateError("CandidateManifest path is empty")
    try:
        return resolve_job_owned_path(job_path, value)
    except ValueError as exc:
        raise CandidateStateError("CandidateManifest path escapes the job directory") from exc


def _manifest_path(job_path: Path, task: dict[str, Any], revision: int) -> Path:
    path = (
        job_path
        / "reports"
        / "candidate_manifests"
        / str(task.get("child") or "")
        / str(task.get("role") or "")
        / str(task.get("task_fingerprint") or "")
        / f"candidate{int(revision)}.json"
    )
    return _job_owned_path(job_path, str(path))




def _candidate_revision_from_name(name: str, prefix: str) -> int:
    tail = name.removeprefix(prefix)
    for suffix in (".png", ".json"):
        tail = tail.removesuffix(suffix)
    try:
        return max(0, int(tail))
    except ValueError:
        return 0


def _rounded_optional_float(value: Any) -> float | None:
    try:
        return round(max(0.0, float(value)), 3)
    except (TypeError, ValueError):
        return None
