from __future__ import annotations

import csv
import asyncio
import httpx
import hashlib
import hmac
import mimetypes
import os
import re
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


def validate_publication_policy(policy):
    if isinstance(policy,dict) and policy.get('retention_mode')=='operator_managed':
        if set(policy)!={'retention_mode','verification_max_age_seconds','source'} or type(policy['verification_max_age_seconds']) is not int or policy['verification_max_age_seconds']<=0 or not isinstance(policy['source'],str) or not policy['source'].strip():
            raise PublishError('Operator-managed URLs require explicit responsibility and a positive verification cache window')
        return policy
    if not isinstance(policy,dict) or set(policy)!={'minimum_validity_seconds','verification_max_age_seconds','retained_until','source'}:
        raise PublishError('Explicit publication retention and verification policy required')
    for key in ('minimum_validity_seconds','verification_max_age_seconds'):
        if type(policy[key]) is not int or policy[key]<=0:raise PublishError('Publication time windows must be positive integer seconds')
    try:until=datetime.fromisoformat(policy['retained_until'])
    except (TypeError,ValueError) as exc:raise PublishError('Invalid retention expiry') from exc
    if until.tzinfo is None or not isinstance(policy['source'],str) or not policy['source'].strip():
        raise PublishError('Retention needs timezone and evidence source')
    if until.timestamp()<time.time()+policy['minimum_validity_seconds']:raise PublishError('Retention does not cover the required delivery lifetime')
    return policy


def url_record_current(row,policy, *, now=None):
    """Read-only eligibility; a dashboard view never triggers GET/PUT."""
    now=time.time() if now is None else now
    try:
        validate_publication_policy(policy)
        verified=(row.get('verified_sha256')==(row.get('upload_sha256') or row['candidate_sha256'])
            and row.get('publication_policy_sha256')==input_revision_id(policy)
            and 0<=now-float(row['verified_at'])<=policy['verification_max_age_seconds'])
        if policy.get('retention_mode')=='operator_managed':
            return verified and (not row.get('valid_until') or float(row['valid_until'])>now)
        return verified and float(row['valid_until'])>=now+policy['minimum_validity_seconds']
    except (KeyError,TypeError,ValueError,PublishError):return False


def verify_publication_row(job_path,row, *, force=False):
    """One bounded, budgeted GET under the existing service receipt authority."""
    from .service_response import perform_request
    from .batch_ledger import admit_paid_request
    import json
    job_path=Path(job_path);policy=validate_publication_policy(load_job(job_path).get('publication_policy'))
    if not force and url_record_current(row,policy):return True
    url=str(row['url']);digest=str(row.get('upload_sha256') or row['candidate_sha256'])
    bucket=int(time.time()//policy['verification_max_age_seconds'])
    key=input_revision_id({'url':url,'sha256':digest})
    def send():
        admit_paid_request('storage_get');audit={}
        ok=published_url_accessible(url,timeout=8,expected_sha256=digest,audit=audit)
        safe=audit.get('http_status') in {404,410} or (audit.get('complete') is True and audit.get('received_sha256')!=digest)
        return json.dumps({'ok':ok,'at':time.time(),'replacement_safe':safe}).encode()
    receipt={}
    value=json.loads(perform_request(job_path/'reports/storage_verifications'/key,[f'publish-check:{key}'],
        {'operation':'storage_get','url_sha256':input_revision_id(url),'candidate':digest,'window':bucket},send,
        retry_received=force,receipt_observer=lambda data:receipt.update(data)))
    row.update(verification_receipt=receipt['receipt'],replacement_safe=value['replacement_safe'])
    if not value['ok']:return False
    from urllib.parse import parse_qs
    query={k.casefold():v[0] for k,v in parse_qs(urlparse(url).query).items()}
    expiries=[] if policy.get('retention_mode')=='operator_managed' else [datetime.fromisoformat(policy['retained_until']).timestamp()]
    try:
        if 'x-amz-expires' in query:
            created=datetime.strptime(query['x-amz-date'],'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            expiries.append(created.timestamp()+int(query['x-amz-expires']))
        if 'expires' in query:expiries.append(float(query['expires']))
        if 'se' in query:expiries.append(datetime.fromisoformat(query['se'].replace('Z','+00:00')).timestamp())
    except (KeyError,ValueError):return False
    row.update(verified_at=str(value['at']),verified_sha256=digest,valid_until=str(min(expiries)) if expiries else '',
        retention_source=policy['source'],publication_policy_sha256=input_revision_id(policy))
    return url_record_current(row,policy)


class StorageResponseRejected(PublishError):
    def __init__(self,status,message):
        super().__init__(message);self.status=status


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
        object_key = str(row.get("object_key") or "").strip()
        expected_key = _build_key(
            _r2_prefix(job), str(expected.get("parent") or ""), key[0], _uploaded_path(job_path, row), expected_sha,
        )
        if object_key != expected_key:
            raise PublishError(f"Published object key is stale for the current prefix: {key[0]}/{key[1]}")
        if not _public_url_matches_key(url, object_key):
            raise PublishError(f"Published URL does not match the public object key: {key[0]}/{key[1]}")
        if not verify_publication_row(job_path,row):
            raise PublishError(f"Published URL is not accessible as an image: {url}")
    _write_manifest(manifest,published,job_path=job_path)


def published_url_accessible(url: str, *, timeout: int = 20, expected_sha256: str = '', audit: dict | None = None) -> bool:
    """Bounded public image verification against the actual uploaded bytes."""
    from io import BytesIO
    from .imagegen_artifacts import IMAGE_OUTPUT_MAX_BYTES
    text = str(url or '').strip()
    if not text.startswith(('http://', 'https://')) or (expected_sha256 and not re.fullmatch('[0-9a-f]{64}', expected_sha256)):
        return False
    deadline = time.monotonic() + timeout
    try:
        response = request_public_url('GET', text, timeout=timeout,
            headers={'User-Agent': 'amazon-listing-factory/1.0'}, stream=True)
        try:
            assert_response_peer_public(response, hostname=urlparse(text).hostname or '')
            if audit is not None:audit['http_status']=response.status_code
            if response.status_code != 200 or not str(response.headers.get('Content-Type') or '').lower().startswith('image/'):
                return False
            declared = response.headers.get('Content-Length')
            if declared and (not str(declared).isdigit() or int(declared) > IMAGE_OUTPUT_MAX_BYTES):
                return False
            chunks, size = [], 0
            stream = iter(response.iter_content(chunk_size=65536))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                sock = getattr(getattr(getattr(response, 'raw', None), '_connection', None), 'sock', None)
                if sock is not None:
                    sock.settimeout(remaining)
                try:
                    chunk = next(stream)
                except StopIteration:
                    break
                if not chunk:
                    continue
                size += len(chunk)
                if size > IMAGE_OUTPUT_MAX_BYTES:
                    return False
                chunks.append(chunk)
            data = b''.join(chunks)
            if time.monotonic() >= deadline or (declared and not response.headers.get('Content-Encoding') and size != int(declared)):
                return False
            if audit is not None:audit.update(complete=True,received_sha256=hashlib.sha256(data).hexdigest())
            if expected_sha256 and hashlib.sha256(data).hexdigest() != expected_sha256:
                return False
            with Image.open(BytesIO(data)) as image:
                if image.format not in {'PNG', 'JPEG'} or image.size != (PUBLIC_IMAGE_SIZE, PUBLIC_IMAGE_SIZE):
                    return False
                image.verify()
            return True
        finally:
            response.close()
    except (requests.RequestException, OSError, ValueError):
        return False


def published_rows_current(*, job_dir: str | Path, plugin: ProductPlugin, workers: int = 4) -> bool:
    """Return true when every required role has a byte- and URL-current approved row."""
    from .release_manifest import approved_release_rows, build_release_manifest

    job_path = Path(job_dir).resolve()
    release = build_release_manifest(job_dir=job_path, plugin=plugin)
    approved = approved_release_rows(release)
    if not approved:
        return False
    rows = _reusable_publish_rows(
        job_path,
        approved,
        _load_partial_publish_rows(job_path),
        upload=True,
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
    accessible, inaccessible = _verify_public_rows(required_publish_rows, workers=max(1, int(workers or 1)), job_path=job_path)
    return len(accessible) == len(required) and not inaccessible


def publish_approved_release(
    *,
    job_dir: str | Path,
    plugin: ProductPlugin,
    config_path: str = "",
    upload: bool = False,
    workers: int = 4,
    deadline_monotonic: float | None = None,
    work_children: tuple[str, ...] = (), required_only: bool = False,
) -> dict[str, list[dict[str, str]]]:
    from .release_manifest import approved_release_rows, build_release_manifest

    job_path = Path(job_dir).resolve()
    job = load_job(job_path)
    _load_publish_env(config_path, str(job.get("config_path") or ""))
    if upload:validate_publication_policy(job.get('publication_policy'))
    release = build_release_manifest(job_dir=job_path, plugin=plugin,work_children=work_children)
    rows = approved_release_rows(release)
    retained_rows=[];work_keys=None
    if work_children or required_only:
        from .run_scope import execution_children
        from .release_manifest import required_task_keys
        selected=execution_children(job_path,work_children)
        required=required_task_keys(release,selected) if required_only else None
        active=[row for row in rows if row['child'] in selected and (required is None or (row['child'],row['role']) in required)]
        work_keys={(row['child'],row['role']) for row in release['rows'] if row['child'] in selected and (required is None or (row['child'],row['role']) in required)}
        # Retain the publisher's unselected snapshots without re-verifying or
        # re-uploading them here. Every final consumer still binds SHA/QA/URLs.
        retained_rows=[row for row in _load_publish_rows(job_path,job_path/'images/_r2_image_urls.csv') if (row['child'],row['role']) not in work_keys]
        rows=active
        release={**release,'children':{key:value for key,value in release['children'].items() if key in selected}}
    if not rows:
        raise PublishError("Publish requires at least one current approved candidate")
    valid_rows: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for row in rows:
        if str(row.get("final_decision") or "") != "approved":
            raise PublishError("Publish accepts only current release manifest approved rows")
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
    existing_rows = _load_partial_publish_rows(job_path)
    reusable_rows = _reusable_publish_rows(
        job_path,
        valid_rows,
        existing_rows,
        upload=upload,
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
            storage = publish_upload_config()
            _preflight_upload_endpoint(storage["endpoint"], timeout=min(5.0, remaining))
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
                cause=exc,retained_rows=retained_rows,work_keys=work_keys,
            )
        new_rows = _upload_rows(
            publish_rows,
            job,
            job_path=job_path,
            workers=max(1, int(workers or 1)),
            persisted_rows=existing_rows,
            failures=failures,
            storage=storage,
            deadline_monotonic=deadline_monotonic,
        )
    elif publish_rows:
        new_rows = [_local_row(row, job, job_id=job_path.name) for row in publish_rows]
    else:
        new_rows = []
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
            retained_rows=retained_rows,work_keys=work_keys,
        )
    if upload:
        accessible, inaccessible = _verify_public_rows(current_rows, workers=max(1, int(workers or 1)), job_path=job_path)
        if inaccessible:
            return _finish_publish_attempt(
                job_path=job_path,
                release=release,
                approved=rows,
                current_rows=accessible,
                failures=inaccessible,
                fatal_message=f"{len(inaccessible)} uploaded object(s) do not yet have an accessible public image URL",
                retained_rows=retained_rows,work_keys=work_keys,
            )
    _write_partial_publish_ledger(job_path,_merge_publish_rows(merged,current_rows))
    _finalize_partial_publish_manifest(job_dir=job_path, allowed_rows=[*retained_rows,*current_rows],work_keys=work_keys)
    # Remote success is already durable: a local export collision must never cause another PUT.
    _export_final_pics(current_rows,job_path=job_path,shared=upload)
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
    cause: Exception | None = None, retained_rows=(),work_keys=None,
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
    _finalize_partial_publish_manifest(job_dir=job_path, allowed_rows=[*retained_rows,*current_rows],work_keys=work_keys)
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


def _finalize_partial_publish_manifest(*, job_dir: str | Path, allowed_rows: list[dict[str, str]],work_keys=None) -> list[dict[str, str]]:
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
        raise PublishError("No partial image URL rows found to finalize")
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
    unselected=[row for row in all_rows if (row['child'],row['role']) not in work_keys] if work_keys is not None else []
    _write_partial_publish_ledger(job_path,_merge_publish_rows(unselected,rows))
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


def _uploaded_path(job_path: Path, row: dict) -> Path:
    if not row.get('upload_path'):
        if row.get('upload_sha256'):
            raise PublishError('Upload digest without a bound file')
        return _publish_local_path(job_path, row.get('local_path'))
    path = _publish_local_path(job_path, row['upload_path'])
    if not path.is_file() or file_sha256(path) != row.get('upload_sha256'):
        raise PublishError('Upload copy is missing or changed; original candidate remains intact')
    return path


def _upload_rows(
    rows: list[dict[str, str]],
    job: dict,
    *,
    job_path: Path,
    workers: int,
    persisted_rows: list[dict[str, str]] | None = None,
    failures: list[dict[str, str]] | None = None,
    storage: dict[str, str],
    deadline_monotonic: float | None = None,
) -> list[dict[str, str]]:
    prefix = _r2_prefix(job)
    uploaded: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for row in rows:
            image_path = _publish_local_path(job_path, row.get("local_path"))
            if not image_path.exists():
                raise PublishError(f"Generated image not found before upload: {image_path}")
            if job.get("upload_encoding"):
                from .image_upload import UPLOAD_ENCODING, prepare_upload_copy
                if job['upload_encoding'] != UPLOAD_ENCODING:
                    raise PublishError('Unsupported upload encoding policy')
                row = {**row, **prepare_upload_copy(job_path, image_path, row['candidate_sha256'])}
                image_path = _uploaded_path(job_path, row)
            object_key = _build_key(prefix, row["parent"], row["child"], image_path, row["candidate_sha256"])
            public_url = _public_url(storage["public_base_url"], object_key)
            future=executor.submit(_upload_bound,job_path,storage,object_key,image_path,public_url,deadline_monotonic)
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
                            "error": str(exc) if isinstance(exc, PublishError) else f"Upload failed: {type(exc).__name__}",
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
                    "local_sha256": row["candidate_sha256"],
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "storage_provider": storage["provider"],
                }
            )
            _write_partial_publish_ledger(job_path, _merge_publish_rows(persisted_rows or [], uploaded))
    return uploaded


def _upload_bound(job_path,storage,object_key,image_path,public_url,deadline):
    from .service_response import perform_request
    import json
    digest=file_sha256(image_path);key=input_revision_id(object_key)
    root=job_path/'reports/storage_requests'/key
    recovery=''
    # Reconcile a prior PUT with GET of the desired bytes, never another unknown PUT.
    if root.is_dir() and any(root.glob('*.json')):
        row={'url':public_url,'candidate_sha256':digest}
        if verify_publication_row(job_path,row,force=True):
            with Image.open(image_path) as image:width,height=image.size
            return {'width':width,'height':height,'bytes':image_path.stat().st_size}
        if not row.get('replacement_safe'):raise PublishError('Remote object state is uncertain; retain original PUT, do not repurchase')
        recovery=file_sha256(Path(row['verification_receipt']))
    def send():
        try:
            if storage['provider']=='oci_par':
                result=_upload_one_oci(storage['endpoint'],object_key,image_path,deadline_monotonic=deadline)
            else:
                result=_upload_one_s3(storage['endpoint'],storage['access_key_id'],storage['secret_access_key'],
                    storage['bucket'],object_key,image_path,storage['region'],deadline_monotonic=deadline)
        except StorageResponseRejected as exc:result={'error':str(exc),'status':exc.status}
        return json.dumps(result).encode()
    result=json.loads(perform_request(root,[f'publish-put:{key}'],
        {'operation':'storage_put','object':object_key,'sha256':digest,'storage_revision':input_revision_id(storage),'verified_recovery':recovery},send))
    if result.get('error'):raise PublishError(result['error'])
    return result


def _preflight_upload_endpoint(endpoint: str, *, timeout: float = 5.0) -> None:
    parsed = urlparse(str(endpoint or "").strip())
    host = parsed.hostname
    if not host:
        raise PublishError("Storage endpoint is invalid; configure a reachable http(s) endpoint")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except OSError as exc:
        if _is_socket_permission_error(exc):
            raise PublishError(f"Storage endpoint socket access is blocked in this environment: {host}:{port}") from None
        raise PublishError(f"Storage endpoint is unreachable before upload: {host}:{port}") from None


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
                _r2_prefix(job), str(release.get("parent") or ""), key[0], _uploaded_path(job_path, row), key[2],
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
            _uploaded_path(job_path, row), str(release.get("candidate_sha256") or ""),
        )
        if expected_key_fragment not in object_key or object_key != expected_object_key:
            continue
        if upload:
            if not _public_url_matches_key(str(row.get("url") or ""), object_key):
                continue
            # Do not trust a stale CSV/object key as proof that the remote
            # object still exists.  Reuse only after the current public URL
            # passes the same image-content check used by final publish.
            if not verify_publication_row(job_path,row):
                continue
        reusable.append(row)
    return reusable


def _verify_public_rows(
    rows: list[dict[str, str]], *, workers: int, job_path: Path
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    accessible: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(verify_publication_row, job_path, row,force=not bool(row.get('verified_at'))): row
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


def _export_final_pics(rows: list[dict[str,str]], *, job_path: Path, shared: bool) -> list[str]:
    """One-way exports, never a source of approval or parent/child identity."""
    from .product_family import read_product_family
    from .paths import resolve_job_owned_path
    from .template_runtime import parent_sku, child_sku
    import json
    family=read_product_family(job_path)['family'];parent=family['parent_asin']
    if not rows:
        return []
    metadata = load_job(job_path) if not parent else {}
    folder=parent or parent_sku(metadata,'',[child_sku(metadata,c,i) for i,c in enumerate(family['children'],1)])
    children={c['asin'] for c in family['children']};seen=set();prepared=[]
    roots=[job_path/'Fianl_pics']+([FACTORY_ROOT/'Fianl_pics'] if shared else [])
    policy=load_job(job_path).get('publication_policy') if shared else None
    for row in rows:
        child,role=str(row.get('child') or ''),str(row.get('role') or '')
        if row.get('parent')!=parent or child not in children or not re.fullmatch(r'(?:main|scene|func|size)(?:_[0-9]+)?',role) or (child,role) in seen:
            raise ValueError('Delivery needs unique roles under the verified family mapping')
        seen.add((child,role));source=_publish_local_path(job_path,row.get('local_path'))
        digest=str(row.get('candidate_sha256') or '')
        if file_sha256(source)!=digest:raise ValueError('Delivery candidate bytes changed')
        if shared and (not str(row.get('url') or '').startswith('https://') or not url_record_current(row,policy)):
            raise ValueError('Shared delivery requires current verified publication URLs')
        targets=[resolve_job_owned_path(root,Path(folder)/child/(role+source.suffix.lower())) for root in roots]
        prepared.append((row,source,digest,targets))
    exported=[];manifests={}
    for row,source,digest,targets in prepared:
        data=source.read_bytes()
        for target in targets:_commit_export(data,target,digest,owner=job_path)
        row['final_export_path']=str(targets[-1]);exported.append(str(targets[-1]))
        manifests.setdefault(row['child'],[]).append({key:row.get(key,'') for key in
            ('role','candidate_sha256','upload_sha256','upload_encoding','url','verified_sha256','valid_until','retention_source','publication_policy_sha256')})
    for child,images in manifests.items():
        payload={'schema':'child-image-url-snapshot-v1','parent':parent,'child':child,
            'kind':'verified_publication' if shared else 'local_export_only',
            'images':sorted(images,key=lambda r:r['role']),
            'eligibility':'Immutable URL snapshot; current eligibility remains with the publisher.'}
        data=(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf-8');digest=hashlib.sha256(data).hexdigest()
        for root in roots:
            target=resolve_job_owned_path(root,Path(folder)/child/('image_urls.'+digest+'.json'))
            _commit_export(data,target,digest)
    return exported


def export_final_template(job_path: Path,plan: dict) -> str:
    from .product_family import read_product_family
    from .paths import resolve_job_owned_path
    from .template_runtime import parent_sku, child_sku
    family=read_product_family(job_path)['family'];parent=family['parent_asin']
    metadata = load_job(job_path) if not parent else {}
    folder=parent or parent_sku(metadata,'',[child_sku(metadata,c,i) for i,c in enumerate(family['children'],1)])
    if plan.get('artifact_state')!='submit_ready' or plan.get('template_mode')!='submit_ready' or plan.get('parent_asin')!=parent:
        raise ValueError('Only the canonical submit-ready family workbook may be exported')
    source=resolve_job_owned_path(job_path,plan['output_path'])
    target=resolve_job_owned_path(FACTORY_ROOT/'Final_templates',Path(folder)/source.name)
    return str(_commit_export(source.read_bytes(),target,plan['workbook_sha256'],owner=job_path))


def _commit_export(data: bytes,target: Path,expected_sha256: str, *, owner: Path | None = None) -> Path:
    """Fenced publisher CAS. Only this job's recorded output may change versions."""
    import tempfile
    from .io import read_json, write_bytes_atomic
    from .process_lock import process_file_lock
    if hashlib.sha256(data).hexdigest()!=expected_sha256:raise ValueError('Export source changed before commit')
    target=Path(target).absolute();target.parent.mkdir(parents=True,exist_ok=True)
    binding={'target':str(target),'owner':str(Path(owner).resolve())} if owner is not None else None
    journal=Path(owner)/'reports/delivery_exports'/input_revision_id(binding)/'current.json' if binding else None
    with process_file_lock(target.parent/'.delivery.lock'):
        if target.is_symlink() or target.exists() and not target.is_file():raise ValueError('Export destination is not a regular managed file')
        current=file_sha256(target) if target.exists() else None
        prior=read_json(journal) if journal and journal.is_file() else {}
        if prior and (prior.get('schema')!='managed-export-v1' or prior.get('binding')!=binding):
            raise ValueError('Export ownership record differs')
        if prior.get('status')=='prepared':
            swap=Path(prior['swap_path']) if prior.get('swap_path') else None
            if current is None and swap and swap.is_file() and file_sha256(swap)==prior['previous_sha256']:
                try:os.link(swap,target)
                except FileExistsError:pass
                current=file_sha256(target)
            if current==prior['sha256']:
                prior={**prior,'status':'committed'};write_json(journal,prior)
            elif current==prior['previous_sha256']:
                # Before-image unchanged: abandon only this uncommitted preparation.
                write_json(journal.parent/(prior['sha256']+'.cancelled.json'),{**prior,'status':'cancelled'})
                prior={**prior,'status':'committed','sha256':current}
            else:raise ValueError('Prepared export has unrelated later writes')
        if current==expected_sha256:
            return target  # Identical foreign bytes do not transfer ownership.
        if current is not None and (not prior or prior.get('status')!='committed' or prior.get('sha256')!=current):
            raise ValueError('Different delivery content is not owned by this order: '+str(target))
        if journal:
            if current is not None:
                before=target.read_bytes()
                if hashlib.sha256(before).hexdigest()!=current:raise ValueError('Export before-image changed')
                write_bytes_atomic(journal.parent/(current+'.before'),before)
            swap=target.with_name('.'+target.name+'.'+input_revision_id({'binding':binding,'before':current,'after':expected_sha256})+'.previous')
            pending={'schema':'managed-export-v1','binding':binding,'previous_sha256':current,
                     'sha256':expected_sha256,'status':'prepared','swap_path':str(swap)}
            write_json(journal,pending)
        fd,name=tempfile.mkstemp(prefix='.'+target.name+'.',suffix='.tmp',dir=target.parent);tmp=Path(name)
        try:
            with os.fdopen(fd,'wb') as handle:handle.write(data);handle.flush();os.fsync(handle.fileno())
            if current is None:
                try:os.link(tmp,target)
                except FileExistsError:
                    if not target.is_file() or file_sha256(target)!=expected_sha256:raise ValueError('Delivery destination changed during commit')
            else:
                if not target.is_file() or file_sha256(target)!=current:raise ValueError('Export CAS before-image changed')
                if swap.exists():
                    if not swap.is_file() or file_sha256(swap)!=current:raise ValueError('Export swap contains unrelated bytes')
                    swap.unlink()
                os.rename(target,swap)
                if file_sha256(swap)!=current:
                    try:os.link(swap,target)
                    except FileExistsError:pass
                    raise ValueError('Concurrent external writer preserved; export CAS refused')
                try:os.link(tmp,target)
                except FileExistsError:
                    if not target.is_file() or file_sha256(target)!=expected_sha256:
                        raise ValueError('Concurrent export destination preserved; original remains in the recorded backup')
            if file_sha256(target)!=expected_sha256:raise ValueError('Export bytes changed during commit')
            if journal:
                committed={**pending,'status':'committed'}
                write_json(journal.parent/(expected_sha256+'.committed.json'),committed);write_json(journal,committed)
                if swap.is_file() and file_sha256(swap)==current:swap.unlink()
            return target
        finally:tmp.unlink(missing_ok=True)


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
    response = _put_file_once(url, headers=headers, image_path=image_path, deadline_monotonic=deadline_monotonic)
    if not 200 <= response.status_code < 300:
        hint = ""
        if response.status_code==403:
            hint = " Check credentials, clock and permissions; resolve the original receipt before retry."
        response.close()
        raise StorageResponseRejected(response.status_code,f"R2 upload failed status={response.status_code}.{hint}")
    response.close()
    with Image.open(image_path) as image:
        width, height = image.size
    return {"width": width, "height": height, "bytes": size, "content_type": content_type}


def _upload_one_oci(upload_base: str, object_key: str, image_path: Path, *, deadline_monotonic: float | None = None) -> dict[str, int | str]:
    content_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    response = _put_file_once(
        _public_url(upload_base, object_key), headers={"Content-Type": content_type, "Content-Length": str(image_path.stat().st_size)},
        image_path=image_path, deadline_monotonic=deadline_monotonic,
    )
    try:
        if not 200 <= response.status_code < 300:
            # PAR credentials can be echoed by servers; never persist bodies or URLs.
            raise StorageResponseRejected(response.status_code,f"OCI upload failed status={response.status_code}; check PAR permissions, expiry and bucket capacity")
        with Image.open(image_path) as image:
            width, height = image.size
        return {"width": width, "height": height, "bytes": image_path.stat().st_size, "content_type": content_type}
    finally:
        response.close()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _put_file_once(url: str, *, headers: dict[str,str], image_path: Path, deadline_monotonic=None):
    from .batch_ledger import admit_paid_request
    from .service_response import prepare_request,start_submission
    end=min(time.monotonic()+120,deadline_monotonic if deadline_monotonic is not None else float('inf'))
    if end<=time.monotonic():raise PublishError('Publish execution deadline exhausted before request')
    admit_paid_request('storage_put')
    async def send():
        async def chunks():
            with image_path.open('rb') as handle:
                while chunk:=handle.read(65536):yield chunk
        async with asyncio.timeout(max(0,end-time.monotonic())),httpx.AsyncClient(timeout=None,follow_redirects=False,trust_env=True) as client:
            start_submission()
            async with client.stream('PUT',url,headers=headers,content=chunks()) as response:
                # Subsequent full public-image GET proves publish success, not this header.
                result=requests.Response();result.status_code=response.status_code;result._content=b'';result._content_consumed=True
                return result
    try:
        with prepare_request():return asyncio.run(send())
    except (httpx.HTTPError,OSError,TimeoutError) as exc:
        raise PublishError(f'Storage PUT outcome unavailable ({type(exc).__name__}); original receipt retained') from None


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
    fields = ["upload_path", "upload_sha256", "upload_encoding", "upload_encoder", "upload_bytes", "upload_mime", "job_id", "parent", "child", "role", "candidate_sha256", "local_path", "final_export_path", "object_key", "url", "width", "height", "bytes", "local_sha256", "uploaded_at", "storage_provider", "verified_at", "verified_sha256", "valid_until", "retention_source", "publication_policy_sha256"]
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
        raise PublishError("Storage object key requires the approved candidate SHA-256")
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


def publish_upload_config(env: dict[str, str] | None = None) -> dict[str, str]:
    """Resolve the one selected destination; credentials never enter manifests."""
    values = os.environ if env is None else env
    provider = str(values.get("IMAGE_PUBLISH_STORAGE") or "r2").strip().lower()
    if provider not in {"r2", "oci_par"}:
        raise PublishError("IMAGE_PUBLISH_STORAGE must be r2 or oci_par")
    names = ("OCI_PAR_UPLOAD_URL", "OCI_PUBLIC_BASE_URL") if provider == "oci_par" else ("R2_ENDPOINT", "R2_PUBLIC_BASE_URL")
    endpoint = _env_any(names[0], *(("R2_S3_ENDPOINT",) if provider == "r2" else ()), required=True, env=values)
    public_base = _env_any(names[1], required=True, env=values)
    try:
        parsed, public = urlparse(endpoint), urlparse(public_base)
        for url in (parsed, public):
            if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError()
            _ = url.port
        if re.match(r"^/p/[^/]+/n/", public.path):
            raise ValueError()
        if provider == "oci_par":
            match = re.fullmatch(r"/p/[^/]+(/n/[^/]+/b/[^/]+/o/)(.*)", parsed.path)
            if (parsed.scheme != "https" or public.scheme != "https" or not match
                    or not parsed.hostname.endswith((".oraclecloud.com", ".customer-oci.com"))
                    or public.path.rstrip("/") != (match[1] + match[2]).rstrip("/")):
                raise ValueError()
    except ValueError:
        raise PublishError("Storage URL configuration is invalid; OCI requires an HTTPS PAR upload URL and matching public object base without credentials") from None
    config = {"provider": provider, "endpoint": endpoint, "public_base_url": public_base}
    if provider == "r2":
        config.update(
            access_key_id=_env_any("R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID", required=True, env=values),
            secret_access_key=_env_any("R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY", required=True, env=values),
            bucket=_env_any("R2_BUCKET", required=True, env=values),
            region=_env_any("R2_REGION", "AWS_REGION", default="auto", env=values),
        )
    return config


def _public_url_matches_key(url: str, object_key: str) -> bool:
    try:
        parsed = urlparse(url)
        return bool(
            parsed.scheme in {"https", "http"} and parsed.hostname
            and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
            and not re.match(r"^/p/[^/]+/n/", parsed.path)
            and unquote(parsed.path).rstrip("/").endswith("/" + object_key)
        )
    except ValueError:
        return False


def _env_any(*names: str, required: bool = False, default: str = "", env: dict[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    for name in names:
        value = str(values.get(name) or "").strip()
        if value:
            return value
    if required:
        raise PublishError(f"Missing environment variable; expected one of: {', '.join(names)}")
    return default
