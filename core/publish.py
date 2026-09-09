from __future__ import annotations

import csv
import hashlib
import hmac
import mimetypes
import os
import random
import re
import shutil
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import requests
from PIL import Image

from .image_upscale import PUBLIC_IMAGE_SIZE
from .io import file_sha256, load_env, write_csv, write_json
from .job import load_job
from .paths import FACTORY_ROOT, resolve_job_owned_path
from .plugin import ProductPlugin
from .status import input_revision_id, logical_task_id
from .url_safety import request_public_url, assert_response_peer_public


class PublishError(RuntimeError):
    pass


class PublishBatchError(PublishError):
    def __init__(self, message: str, failures: list[dict[str, str]], successes: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.failures = [
            {"task": {**row, **_publish_task_identity(row)}, "error": str(row.get("error") or "publish failed")}
            for row in failures
        ]
        self.successes = [{**row, **_publish_task_identity(row)} for row in successes]


def assert_published_release_complete(*, job_dir: str | Path, plugin: ProductPlugin) -> None:
    from .release_manifest import approved_release_rows, build_release_manifest, release_submit_ready

    job_path = Path(job_dir).resolve()
    release = build_release_manifest(job_dir=job_path, plugin=plugin)
    if not release_submit_ready(release):
        completion = release.get("production_task_completion") or {}
        raise PublishError(
            "Final publish requires every configured role minimum to be approved; "
            f"required_completion={completion.get('status')}"
        )
    job = load_job(job_path)
    approved = approved_release_rows(release)
    manifest = job_path / "images" / "_r2_image_urls.csv"
    if not manifest.exists():
        raise PublishError(f"Final publish manifest is missing: {manifest}")
    with manifest.open(newline="", encoding="utf-8-sig") as handle:
        published = [dict(row) for row in csv.DictReader(handle)]
    by_key = {(str(row.get("child") or ""), str(row.get("role") or "")): row for row in published}
    rows, missing = _required_rows_from_published(release, approved, set(by_key))
    if missing:
        raise PublishError("Required published role coverage is incomplete: " + ", ".join(missing))
    for expected in rows:
        key = (str(expected.get("child") or ""), str(expected.get("role") or ""))
        row = by_key.get(key)
        if row is None:
            raise PublishError(f"Approved image was not published: {key[0]}/{key[1]}")
        expected_sha = str(expected.get("candidate_sha256") or "").strip()
        published_sha = str(row.get("candidate_sha256") or "").strip()
        if not expected_sha or published_sha != expected_sha:
            raise PublishError(f"Published image does not match the approved candidate: {key[0]}/{key[1]}")
        local_path = _publish_local_path(job_path, row.get("local_path"))
        if (
            str(row.get("local_sha256") or "") != expected_sha
            or not local_path.is_file()
            or file_sha256(local_path) != expected_sha
        ):
            raise PublishError(f"Published local pixels differ from the approved candidate: {key[0]}/{key[1]}")
        url = str(row.get("url") or "").strip()
        if not url:
            raise PublishError(f"Published image has no public URL: {key[0]}/{key[1]}")
        public_base_url = str(os.environ.get("R2_PUBLIC_BASE_URL") or "").strip()
        object_key = str(row.get("object_key") or "").strip()
        expected_key = _build_key(
            _r2_prefix(job), str(expected.get("parent") or ""), key[0], local_path, expected_sha,
        )
        if object_key != expected_key:
            raise PublishError(f"Published object key is stale for the current R2 prefix: {key[0]}/{key[1]}")
        if public_base_url and (not object_key or url != _public_url(public_base_url, object_key)):
            raise PublishError(f"Published URL is stale for the current public base: {key[0]}/{key[1]}")
        if not published_url_accessible(url):
            raise PublishError(f"Published URL is not accessible as an image: {url}")


def published_url_accessible(url: str, *, timeout: int = 20) -> bool:
    text = str(url or "").strip()
    if not text.startswith(("http://", "https://")):
        return False
    headers = {"User-Agent": "amazon-listing-factory/1.0"}
    for method in ("HEAD", "GET"):
        try:
            current_headers = dict(headers)
            if method == "GET":
                current_headers["Range"] = "bytes=0-0"
            response = request_public_url(
                method,
                text,
                timeout=timeout,
                headers=current_headers,
                stream=method == "GET",
            )
            try:
                assert_response_peer_public(response, hostname=urlparse(text).hostname or "")
                content_type = str(response.headers.get("Content-Type") or "").lower()
                if response.status_code < 400 and content_type.startswith("image/"):
                    return True
            finally:
                response.close()
        except requests.RequestException:
            continue
    return False


def published_rows_current(*, job_dir: str | Path, plugin: ProductPlugin, workers: int = 4) -> bool:
    """Return true when every required role has a byte- and URL-current approved row."""
    from .release_manifest import approved_release_rows, build_release_manifest

    job_path = Path(job_dir).resolve()
    release = build_release_manifest(job_dir=job_path, plugin=plugin)
    approved = approved_release_rows(release)
    if not approved:
        return False
    public_base = str(os.environ.get("R2_PUBLIC_BASE_URL") or "").strip()
    rows = _reusable_publish_rows(
        job_path,
        approved,
        _load_partial_publish_rows(job_path),
        upload=True,
        public_base_url=public_base,
    )
    required, missing = _required_rows_from_published(
        release,
        approved,
        {(str(row.get("child") or ""), str(row.get("role") or "")) for row in rows},
    )
    if missing:
        return False
    required_keys = {(str(row.get("child") or ""), str(row.get("role") or "")) for row in required}
    required_publish_rows = [
        row for row in rows
        if (str(row.get("child") or ""), str(row.get("role") or "")) in required_keys
    ]
    accessible, inaccessible = _verify_public_rows(required_publish_rows, workers=max(1, int(workers or 1)))
    return len(accessible) == len(required) and not inaccessible


def publish_approved_release(
    *,
    job_dir: str | Path,
    plugin: ProductPlugin,
    config_path: str = "",
    upload: bool = False,
    workers: int = 4,
    deadline_monotonic: float | None = None,
) -> dict[str, list[dict[str, str]]]:
    from .release_manifest import approved_release_rows, build_release_manifest

    job_path = Path(job_dir).resolve()
    job = load_job(job_path)
    _load_publish_env(config_path, str(job.get("config_path") or ""))
    release = build_release_manifest(job_dir=job_path, plugin=plugin)
    rows = approved_release_rows(release)
    if not rows:
        raise PublishError("Publish requires at least one current approved candidate")
    valid_rows: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for row in rows:
        if str(row.get("final_decision") or "") != "approved":
            raise PublishError("Publish accepts only ReleaseManifestV5 approved rows")
        local_path = _publish_local_path(job_path, row.get("local_path"))
        expected_sha = str(row.get("candidate_sha256") or "")
        if not local_path.exists() or not expected_sha or file_sha256(local_path) != expected_sha:
            failures.append({
                "parent": str(row.get("parent") or ""),
                "child": str(row.get("child") or ""),
                "role": str(row.get("role") or ""),
                "local_path": str(local_path),
                "candidate_sha256": expected_sha,
                "error": f"Approved candidate changed or is missing: {local_path}",
            })
            continue
        valid_rows.append(row)
    public_base_url = _env_any("R2_PUBLIC_BASE_URL", required=True) if upload else ""
    existing_rows = _load_partial_publish_rows(job_path)
    reusable_rows = _reusable_publish_rows(
        job_path,
        valid_rows,
        existing_rows,
        upload=upload,
        public_base_url=public_base_url,
    )
    reusable_keys = {(row["child"], row["role"]) for row in reusable_rows}
    tasks = [
        (
            str(row.get("parent") or ""),
            str(row.get("child") or ""),
            str(row.get("role") or ""),
            _publish_local_path(job_path, row.get("local_path")),
            str(row.get("candidate_sha256") or ""),
        )
        for row in valid_rows
        if (str(row.get("child") or ""), str(row.get("role") or "")) not in reusable_keys
    ]
    publish_rows: list[dict[str, str]] = []
    for task in tasks:
        parent, child, role, image_path, candidate_sha = task
        try:
            publish_rows.append(_publish_candidate_row(task))
        except Exception as exc:
            failures.append({
                "parent": parent,
                "child": child,
                "role": role,
                "local_path": str(image_path),
                "candidate_sha256": candidate_sha,
                "error": f"{type(exc).__name__}: {exc}",
            })
    if upload and publish_rows:
        try:
            remaining = deadline_monotonic - time.monotonic() if deadline_monotonic is not None else 5.0
            if remaining <= 0:
                raise PublishError("Publish execution deadline exhausted before upload")
            _preflight_upload_endpoint(_env_any("R2_ENDPOINT", "R2_S3_ENDPOINT", required=True), timeout=min(5.0, remaining))
        except PublishError as exc:
            _write_partial_publish_ledger(job_path, _merge_publish_rows(existing_rows, reusable_rows))
            preflight_failures = [
                {
                    "parent": str(row.get("parent") or ""),
                    "child": str(row.get("child") or ""),
                    "role": str(row.get("role") or ""),
                    "local_path": str(row.get("local_path") or ""),
                    "candidate_sha256": str(row.get("candidate_sha256") or ""),
                    "error": str(exc),
                }
                for row in publish_rows
            ]
            return _finish_publish_attempt(
                job_path=job_path,
                release=release,
                approved=rows,
                current_rows=reusable_rows,
                failures=[*failures, *preflight_failures],
                fatal_message=str(exc),
                cause=exc,
            )
        new_rows = _upload_rows(
            publish_rows,
            job,
            job_path=job_path,
            workers=max(1, int(workers or 1)),
            persisted_rows=existing_rows,
            failures=failures,
            public_base_url=public_base_url,
            deadline_monotonic=deadline_monotonic,
        )
    elif publish_rows:
        new_rows = [_local_row(row, job, job_id=job_path.name) for row in publish_rows]
    else:
        new_rows = []
    if new_rows:
        _export_final_pics(new_rows, job_path=job_path, shared=upload)
    merged = _merge_publish_rows(existing_rows, [*reusable_rows, *new_rows])
    _write_partial_publish_ledger(job_path, merged)
    current_rows = [*reusable_rows, *new_rows]
    if failures or len(new_rows) != len(tasks):
        return _finish_publish_attempt(
            job_path=job_path,
            release=release,
            approved=rows,
            current_rows=current_rows,
            failures=failures,
            fatal_message=f"Publish completed only {len(new_rows)}/{len(tasks)} new approved rows",
        )
    if upload:
        accessible, inaccessible = _verify_public_rows(current_rows, workers=max(1, int(workers or 1)))
        if inaccessible:
            return _finish_publish_attempt(
                job_path=job_path,
                release=release,
                approved=rows,
                current_rows=accessible,
                failures=inaccessible,
                fatal_message=f"{len(inaccessible)} uploaded object(s) do not yet have an accessible public image URL",
            )
    _finalize_partial_publish_manifest(job_dir=job_path, allowed_rows=current_rows)
    _write_optional_publish_failures(job_path, [])
    return {
        "tasks": [{**row, **_publish_task_identity(row)} for row in current_rows],
        "failures": [],
        "warnings": [],
    }


def _finish_publish_attempt(
    *,
    job_path: Path,
    release: dict[str, Any],
    approved: list[dict[str, str]],
    current_rows: list[dict[str, str]],
    failures: list[dict[str, str]],
    fatal_message: str,
    cause: Exception | None = None,
) -> dict[str, list[dict[str, str]]]:
    _, missing = _required_rows_from_published(
        release,
        approved,
        {(str(row.get("child") or ""), str(row.get("role") or "")) for row in current_rows},
    )
    if missing:
        error = PublishBatchError(
            f"{fatal_message}; missing required role coverage: {', '.join(missing)}",
            failures,
            current_rows,
        )
        if cause is not None:
            raise error from cause
        raise error
    _finalize_partial_publish_manifest(job_dir=job_path, allowed_rows=current_rows)
    _write_optional_publish_failures(job_path, failures)
    return {
        "tasks": [{**row, **_publish_task_identity(row)} for row in current_rows],
        "failures": [],
        "warnings": [
            {
                "child": str(row.get("child") or ""),
                "role": str(row.get("role") or ""),
                "error": str(row.get("error") or fatal_message),
            }
            for row in failures
        ],
    }


def _required_rows_from_published(
    release: dict[str, Any],
    approved: list[dict[str, str]],
    published_keys: set[tuple[str, str]],
) -> tuple[list[dict[str, str]], list[str]]:
    counts = {
        str(role): max(0, int(count))
        for role, count in (release.get("required_role_counts") or {}).items()
    }
    selected: list[dict[str, str]] = []
    missing: list[str] = []
    children = [str(child) for child in (release.get("children") or {})]
    for child in children:
        for role_family, required_count in counts.items():
            candidates = sorted(
                [
                    row for row in approved
                    if str(row.get("child") or "") == child
                    and str(row.get("role_prefix") or "") == role_family
                    and (child, str(row.get("role") or "")) in published_keys
                ],
                key=lambda row: str(row.get("role") or ""),
            )
            selected.extend(candidates[:required_count])
            if len(candidates) < required_count:
                missing.append(f"{child}/{role_family}:{len(candidates)}/{required_count}")
    return selected, missing


def _write_optional_publish_failures(job_path: Path, failures: list[dict[str, str]]) -> None:
    write_json(job_path / "reports" / "publish_optional_failures.json", {
        "failures": [
            {
                "child": str(row.get("child") or ""),
                "role": str(row.get("role") or ""),
                "candidate_sha256": str(row.get("candidate_sha256") or ""),
                "error": str(row.get("error") or ""),
            }
            for row in failures
        ],
    })


def _publish_task_identity(row: dict[str, str]) -> dict[str, str]:
    child = str(row.get("child") or "")
    role = str(row.get("role") or "")
    return {
        "logical_task_id": logical_task_id("publish", child=child, role=role),
        "input_revision_id": input_revision_id(
            {
                "child": child,
                "role": role,
                "candidate_sha256": str(row.get("candidate_sha256") or ""),
                "object_key": str(row.get("object_key") or ""),
            }
        ),
    }


def _finalize_partial_publish_manifest(*, job_dir: str | Path, allowed_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    job_path = Path(job_dir)
    all_rows = _load_partial_publish_rows(job_path)
    allowed = {
        (
            str(row.get("parent") or "").strip(),
            str(row.get("child") or "").strip(),
            str(row.get("role") or "").strip(),
            str(row.get("candidate_sha256") or "").strip(),
            str(row.get("local_path") or "").strip(),
        )
        for row in allowed_rows
    }
    rows = [
        row
        for row in all_rows
        if (
            str(row.get("parent") or "").strip(),
            str(row.get("child") or "").strip(),
            str(row.get("role") or "").strip(),
            str(row.get("candidate_sha256") or "").strip(),
            str(row.get("local_path") or "").strip(),
        )
        in allowed
    ]
    if not rows:
        raise PublishError("No partial R2 image URL rows found to finalize")
    kept_keys = {str(row.get("object_key") or "") for row in rows}
    superseded = [
        {
            "child": str(row.get("child") or ""),
            "role": str(row.get("role") or ""),
            "candidate_sha256": str(row.get("candidate_sha256") or ""),
            "object_key": str(row.get("object_key") or ""),
            "remote_cleanup_required": bool(str(row.get("url") or "")),
        }
        for row in all_rows
        if str(row.get("object_key") or "") not in kept_keys
    ]
    write_json(job_path / "reports" / "publish_retention_audit.json", {
        "active_object_keys": sorted(key for key in kept_keys if key),
        "superseded_objects": superseded,
        "automatic_remote_delete": False,
    })
    manifest = job_path / "images" / "_r2_image_urls.csv"
    _write_manifest(manifest, rows, job_path=job_path)
    _write_partial_publish_ledger(job_path, rows)
    return rows


def _publish_candidate_row(task: tuple[str, str, str, Path, str]) -> dict[str, str]:
    parent, child, role, input_path, candidate_sha256 = task
    if file_sha256(input_path) != candidate_sha256:
        raise PublishError(f"Approved candidate SHA changed before publish: {child}/{role}")
    with Image.open(input_path) as image:
        width, height = image.size
        if (width, height) != (PUBLIC_IMAGE_SIZE, PUBLIC_IMAGE_SIZE):
            raise PublishError(
                f"Approved candidate must be exactly {PUBLIC_IMAGE_SIZE}x{PUBLIC_IMAGE_SIZE}: "
                f"{child}/{role} {width}x{height}"
            )
    row = {
        "parent": parent,
        "child": child,
        "role": role,
        "candidate_sha256": candidate_sha256,
        "local_path": str(input_path),
        "width": str(width),
        "height": str(height),
        "bytes": str(input_path.stat().st_size),
        "local_sha256": candidate_sha256,
    }
    return row


def _upload_rows(
    rows: list[dict[str, str]],
    job: dict,
    *,
    job_path: Path,
    workers: int,
    persisted_rows: list[dict[str, str]] | None = None,
    failures: list[dict[str, str]] | None = None,
    public_base_url: str,
    deadline_monotonic: float | None = None,
) -> list[dict[str, str]]:
    endpoint = _env_any("R2_ENDPOINT", "R2_S3_ENDPOINT", required=True)
    access_key_id = _env_any("R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID", required=True)
    secret_access_key = _env_any("R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY", required=True)
    bucket = _env_any("R2_BUCKET", required=True)
    region = _env_any("R2_REGION", "AWS_REGION", default="auto")
    prefix = _r2_prefix(job)
    uploaded: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for row in rows:
            image_path = _publish_local_path(job_path, row.get("local_path"))
            if not image_path.exists():
                raise PublishError(f"Generated image not found before upload: {image_path}")
            object_key = _build_key(prefix, row["parent"], row["child"], image_path, row["candidate_sha256"])
            public_url = _public_url(public_base_url, object_key)
            future = executor.submit(_upload_one_s3, endpoint, access_key_id, secret_access_key, bucket, object_key, image_path, region, deadline_monotonic=deadline_monotonic)
            futures[future] = (row, image_path, object_key, public_url)
        for future in as_completed(futures):
            row, image_path, object_key, public_url = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                if failures is not None:
                    failures.append(
                        {
                            **row,
                            "object_key": object_key,
                            "url": public_url,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                _write_partial_publish_ledger(job_path, _merge_publish_rows(persisted_rows or [], uploaded))
                continue
            uploaded.append(
                {
                    **row,
                    "object_key": object_key,
                    "url": public_url,
                    "job_id": job_path.name,
                    "width": str(result["width"]),
                    "height": str(result["height"]),
                    "bytes": str(result["bytes"]),
                    "local_sha256": file_sha256(image_path),
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            _write_partial_publish_ledger(job_path, _merge_publish_rows(persisted_rows or [], uploaded))
    return uploaded


def _preflight_upload_endpoint(endpoint: str, *, timeout: float = 5.0) -> None:
    parsed = urlparse(str(endpoint or "").strip())
    host = parsed.hostname
    if not host:
        raise PublishError("R2 endpoint is invalid; set R2_ENDPOINT to a reachable http(s) endpoint")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except OSError as exc:
        if _is_socket_permission_error(exc):
            raise PublishError(f"R2 endpoint socket access is blocked in this environment: {host}:{port}: {exc}") from exc
        raise PublishError(f"R2 endpoint is unreachable before upload: {host}:{port}: {exc}") from exc


def _local_row(row: dict[str, str], job: dict, *, job_id: str = "") -> dict[str, str]:
    prefix = _r2_prefix(job)
    image_path = Path(row["local_path"])
    object_key = _build_key(prefix, row["parent"], row["child"], image_path, row["candidate_sha256"])
    return {**row, "object_key": object_key, "url": "", "job_id": job_id, "uploaded_at": ""}


def _write_partial_publish_ledger(job_path: Path, rows: list[dict[str, str]]) -> None:
    partial_csv = job_path / "images" / "_r2_image_urls.partial.csv"
    partial_json = job_path / "reports" / "publish_partial_summary.json"
    enriched = [_publish_row_with_local_hash(job_path, row) for row in rows]
    _write_manifest(partial_csv, enriched, job_path=job_path)
    write_json(partial_json, {"images": len(enriched), "rows": enriched})


def _load_publish_rows(job_path: Path, manifest: Path) -> list[dict[str, str]]:
    if not manifest.exists():
        return []
    try:
        with manifest.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required = {"parent", "child", "role", "candidate_sha256", "local_path", "object_key", "url", "local_sha256"}
            if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                raise PublishError(f"Publish ledger schema is invalid: {manifest}")
            rows = [{str(key): str(value or "") for key, value in row.items() if key is not None} for row in reader]
    except (OSError, csv.Error, UnicodeError) as exc:
        raise PublishError(f"Publish ledger is unreadable: {manifest}: {exc}") from exc
    keys = [str(row.get("object_key") or "") for row in rows]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise PublishError(f"Publish ledger contains missing or duplicate object keys: {manifest}")
    logical_keys = [
        (
            str(row.get("child") or ""),
            str(row.get("role") or ""),
            str(row.get("candidate_sha256") or ""),
        )
        for row in rows
    ]
    if any(not all(key) for key in logical_keys) or len(logical_keys) != len(set(logical_keys)):
        raise PublishError(f"Publish ledger contains missing or duplicate candidate task keys: {manifest}")
    for row in rows:
        row["local_path"] = str(_publish_local_path(job_path, row.get("local_path")))
    return rows


def _load_partial_publish_rows(job_path: Path) -> list[dict[str, str]]:
    return _load_publish_rows(job_path, job_path / "images" / "_r2_image_urls.partial.csv")


def current_published_release_rows(job_dir: str | Path, release_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return only ledger rows belonging to the current approved candidates.

    The partial ledger is read after the finalized ledger so a newly published
    current candidate replaces a stale finalized row. Candidate SHA and local
    pixels, not CSV existence, establish currentness.
    """
    job_path = Path(job_dir).resolve()
    job = load_job(job_path)
    expected = {
        (str(row.get("child") or ""), str(row.get("role") or ""), str(row.get("candidate_sha256") or "")): row
        for row in release_rows
    }
    current: dict[tuple[str, str, str], dict[str, str]] = {}
    for manifest in (
        job_path / "images" / "_r2_image_urls.csv",
        job_path / "images" / "_r2_image_urls.partial.csv",
    ):
        for row in _load_publish_rows(job_path, manifest):
            key = (str(row.get("child") or ""), str(row.get("role") or ""), str(row.get("candidate_sha256") or ""))
            release = expected.get(key)
            if release is None or str(row.get("job_id") or "") != job_path.name or not str(row.get("url") or ""):
                continue
            local_path = _publish_local_path(job_path, row.get("local_path"))
            release_path = _publish_local_path(job_path, release.get("local_path"))
            if local_path != release_path or row.get("local_sha256") != key[2] or not local_path.is_file() or file_sha256(local_path) != key[2]:
                continue
            expected_key = _build_key(
                _r2_prefix(job), str(release.get("parent") or ""), key[0], release_path, key[2],
            )
            if str(row.get("object_key") or "").strip("/") != expected_key:
                continue
            current[key] = row
    return sorted(current.values(), key=lambda row: (row["child"], row["role"]))


def _reusable_publish_rows(
    job_path: Path,
    release_rows: list[dict[str, str]],
    existing_rows: list[dict[str, str]],
    *,
    upload: bool,
    public_base_url: str = "",
) -> list[dict[str, str]]:
    job = load_job(job_path)
    by_key = {
        (
            str(row.get("child") or ""),
            str(row.get("role") or ""),
            str(row.get("candidate_sha256") or ""),
        ): row
        for row in existing_rows
    }
    reusable: list[dict[str, str]] = []
    for release in release_rows:
        row = by_key.get((
            str(release.get("child") or ""),
            str(release.get("role") or ""),
            str(release.get("candidate_sha256") or ""),
        ))
        if not row:
            continue
        local_path = _publish_local_path(job_path, row.get("local_path"))
        release_path = _publish_local_path(job_path, release.get("local_path"))
        local_sha = str(row.get("local_sha256") or "")
        if local_path != release_path or local_sha != str(release.get("candidate_sha256") or "") or not local_path.is_file() or file_sha256(local_path) != local_sha:
            continue
        if upload and not str(row.get("url") or "").startswith(("http://", "https://")):
            continue
        expected_key_fragment = str(release.get("candidate_sha256") or "")[:20]
        object_key = str(row.get("object_key") or "").strip().strip("/")
        expected_object_key = _build_key(
            _r2_prefix(job), str(release.get("parent") or ""), str(release.get("child") or ""),
            release_path, str(release.get("candidate_sha256") or ""),
        )
        if expected_key_fragment not in object_key or object_key != expected_object_key:
            continue
        if upload:
            url_path = unquote(urlparse(str(row.get("url") or "")).path).rstrip("/")
            if not url_path.endswith("/" + object_key):
                continue
            if public_base_url:
                row = {**row, "url": _public_url(public_base_url, object_key)}
            # Do not trust a stale CSV/object key as proof that the remote
            # object still exists.  Reuse only after the current public URL
            # passes the same image-content check used by final publish.
            if not published_url_accessible(str(row.get("url") or ""), timeout=8):
                continue
        reusable.append(row)
    return reusable


def _verify_public_rows(
    rows: list[dict[str, str]], *, workers: int
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    accessible: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(published_url_accessible, str(row.get("url") or ""), timeout=8): row
            for row in rows
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                current = future.result()
            except Exception:
                current = False
            if current:
                accessible.append(row)
            else:
                failures.append({**row, "error": "public URL is not accessible as an image"})
    return accessible, failures


def _merge_publish_rows(existing: list[dict[str, str]], new_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for row in [*existing, *new_rows]:
        object_key = str(row.get("object_key") or "").strip()
        if not object_key:
            image_path = Path(str(row.get("local_path") or ""))
            object_key = "|".join([str(row.get("parent") or ""), str(row.get("child") or ""), str(row.get("role") or ""), str(image_path)])
        merged[object_key] = {str(key): str(value or "") for key, value in row.items()}
    return list(merged.values())


def _publish_row_with_local_hash(job_path: Path, row: dict[str, str]) -> dict[str, str]:
    enriched = dict(row)
    local_path = _publish_local_path(job_path, enriched.get("local_path"))
    if local_path.exists() and local_path.is_file():
        enriched["local_sha256"] = file_sha256(local_path)
    return enriched


def _export_final_pics(
    rows: list[dict[str, str]],
    *,
    job_path: Path,
    shared: bool,
) -> list[str]:
    exported: list[str] = []
    local_root = job_path / "Final_pics"
    local_root.mkdir(parents=True, exist_ok=True)
    shared_root = FACTORY_ROOT / "Final_pics"
    if shared:
        shared_root.mkdir(parents=True, exist_ok=True)
    for row in rows:
        parent = str(row.get("parent") or "")
        child = str(row.get("child") or "")
        role = str(row.get("role") or "")
        source = _publish_local_path(job_path, row.get("local_path"))
        if not parent or not child or not role or not source.exists():
            continue
        filename = f"{_safe_component(role)}_{_safe_component(job_path.name)}.png"
        local_dir = local_root / _safe_component(parent) / _safe_component(child)
        local_dir.mkdir(parents=True, exist_ok=True)
        local_target = local_dir / filename
        shutil.copy2(source, local_target)
        target = local_target
        if shared:
            child_dir = shared_root / _safe_component(parent) / _safe_component(child)
            child_dir.mkdir(parents=True, exist_ok=True)
            target = _atomic_copy(local_target, child_dir / filename)
        row["final_export_path"] = str(target)
        exported.append(str(target))
    return exported


def _atomic_copy(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{target.name}.{os.getpid()}.tmp"
    try:
        shutil.copy2(source, tmp)
        os.replace(tmp, target)
        return target
    except PermissionError:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        fallback = target.with_name(f"{target.stem}_{timestamp}{target.suffix}")
        tmp = fallback.parent / f".{fallback.name}.{os.getpid()}.tmp"
        shutil.copy2(source, tmp)
        os.replace(tmp, fallback)
        return fallback
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _upload_one_s3(endpoint: str, access_key_id: str, secret_access_key: str, bucket: str, object_key: str, image_path: Path, region: str, *, deadline_monotonic: float | None = None) -> dict[str, int | str]:
    content_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    payload_hash = _sha256_file(image_path)
    size = image_path.stat().st_size
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    parsed = urlparse(endpoint)
    host = parsed.netloc
    canonical_uri = "/" + "/".join(quote(part, safe="") for part in [bucket, *object_key.split("/")])
    url = endpoint.rstrip("/") + canonical_uri
    canonical_headers = f"content-type:{content_type}\nhost:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
    signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(["PUT", canonical_uri, "", canonical_headers, signed_headers, payload_hash])
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, credential_scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()])
    signature = hmac.new(_aws_signing_key(secret_access_key, date_stamp, region, "s3"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "Authorization": f"AWS4-HMAC-SHA256 Credential={access_key_id}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}",
        "Content-Type": content_type,
        "Host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    response = _put_file_with_retries(url, headers=headers, image_path=image_path, deadline_monotonic=deadline_monotonic)
    if not response.ok:
        hint = ""
        if _is_retryable_signature_error(response.status_code, response.text):
            hint = " HINT: R2 rejected the request signature; check local clock sync and retry."
        raise PublishError(f"R2 upload failed status={response.status_code}: {response.text[:500]}{hint}")
    with Image.open(image_path) as image:
        width, height = image.size
    return {"width": width, "height": height, "bytes": size, "content_type": content_type}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _put_file_with_retries(url: str, *, headers: dict[str, str], image_path: Path, deadline_monotonic: float | None = None) -> requests.Response:
    attempts = 3
    last: requests.Response | None = None
    for attempt in range(1, attempts + 1):
        timeout = min(120.0, deadline_monotonic - time.monotonic()) if deadline_monotonic is not None else 120.0
        if timeout <= 0:
            raise PublishError("Publish execution deadline exhausted before request")
        try:
            with image_path.open("rb") as f:
                response = requests.put(url, headers=headers, data=f, timeout=timeout)
        except requests.RequestException as exc:
            if _is_socket_permission_error(exc):
                raise PublishError(f"R2 upload blocked by local socket permissions: {exc}") from exc
            if attempt >= attempts:
                raise PublishError(f"R2 upload failed after {attempts} attempts: {exc}") from exc
            delay = _retry_delay(attempt)
            if deadline_monotonic is not None and time.monotonic() + delay >= deadline_monotonic:
                raise PublishError("Publish execution deadline exhausted before retry") from exc
            time.sleep(delay)
            continue
        last = response
        if response.ok or not _retryable_status(response.status_code, response.text) or attempt >= attempts:
            return response
        delay = _retry_delay(attempt)
        if deadline_monotonic is not None and time.monotonic() + delay >= deadline_monotonic:
            raise PublishError("Publish execution deadline exhausted before retry")
        time.sleep(delay)
    return last if last is not None else requests.Response()


def _retryable_status(status: int, body: str = "") -> bool:
    del body
    return status == 429 or 500 <= status <= 599


def _is_retryable_signature_error(status: int, body: str) -> bool:
    if status != 403:
        return False
    lowered = body.lower()
    return "signaturedoesnotmatch" in lowered or "requesttimetoo" in lowered or "request time too skewed" in lowered


def _retry_delay(attempt: int) -> float:
    return min(30.0, (2 ** (attempt - 1)) + random.uniform(0, 0.5))


def _is_socket_permission_error(exc: BaseException) -> bool:
    errno = getattr(exc, "errno", None)
    winerror = getattr(exc, "winerror", None)
    if errno == 10013 or winerror == 10013:
        return True
    reason = getattr(exc, "reason", None)
    if reason is not None and _is_socket_permission_error(reason):
        return True
    cause = getattr(exc, "__cause__", None)
    if cause is not None and _is_socket_permission_error(cause):
        return True
    text = str(exc)
    return "WinError 10013" in text or "10013" in text and "socket" in text.lower()


def _aws_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    key_date = hmac.new(("AWS4" + secret_key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
    key_region = hmac.new(key_date, region.encode("utf-8"), hashlib.sha256).digest()
    key_service = hmac.new(key_region, service.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()


def _write_manifest(path: Path, rows: list[dict[str, str]], *, job_path: Path) -> None:
    fields = ["job_id", "parent", "child", "role", "candidate_sha256", "local_path", "final_export_path", "object_key", "url", "width", "height", "bytes", "local_sha256", "uploaded_at"]
    ordered = sorted((_manifest_row_with_current_local_metadata(job_path, row, fields) for row in rows), key=lambda item: (item["parent"], item["child"], item["role"]))
    write_csv(path, ordered, fields)


def _manifest_row_with_current_local_metadata(job_path: Path, row: dict[str, str], fields: list[str]) -> dict[str, str]:
    enriched = {field: row.get(field, "") for field in fields}
    local_path = _publish_local_path(job_path, enriched.get("local_path"))
    if local_path.exists() and local_path.is_file():
        enriched["bytes"] = str(local_path.stat().st_size)
        enriched["local_sha256"] = file_sha256(local_path)
    return enriched


def _publish_local_path(job_path: Path, value: object) -> Path:
    if not str(value or "").strip():
        raise PublishError("Publish row local_path is empty")
    try:
        return resolve_job_owned_path(job_path, str(value))
    except ValueError as exc:
        raise PublishError("Publish row local_path escapes the current job") from exc


def _build_key(prefix: str, parent: str, child: str, image_path: Path, candidate_sha256: str) -> str:
    digest = str(candidate_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise PublishError("R2 object key requires the approved candidate SHA-256")
    return "/".join(part.strip("/") for part in (prefix, parent, child, digest[:20], image_path.name) if part)


def _r2_prefix(job: dict[str, Any]) -> str:
    return str(job.get("r2_prefix") or f"amazon-listing/generated/original/{job.get('category_id', 'product')}").strip("/")


def _safe_component(value: str, fallback: str = "unknown") -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return text[:80] or fallback


def _public_url(base_url: str, object_key: str) -> str:
    return base_url.rstrip("/") + "/" + "/".join(quote(part) for part in object_key.split("/"))


def _load_publish_env(*paths: str) -> None:
    for path in paths:
        if path:
            load_env(path)


def _r2_config_present() -> bool:
    required = ("R2_BUCKET", "R2_PUBLIC_BASE_URL")
    key_groups = (
        ("R2_ENDPOINT", "R2_S3_ENDPOINT"),
        ("R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"),
        ("R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"),
    )
    if any(not os.environ.get(name) for name in required):
        return False
    return all(any(os.environ.get(name) for name in group) for group in key_groups)


def _env_any(*names: str, required: bool = False, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    if required:
        raise PublishError(f"Missing environment variable; expected one of: {', '.join(names)}")
    return default
