from __future__ import annotations

import io
import hashlib
import mimetypes
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from PIL import Image

from .io import file_sha256, read_json, write_bytes_atomic, write_json
from .amazon_image_urls import amazon_image_identity
from .paths import resolve_job_owned_path
from .plugin import ProductPlugin
from .product_family import read_product_family
from .run_scope import read_run_scope
from .status import input_revision_id, logical_task_id
from .url_safety import URL_SAFETY_POLICY_VERSION, assert_public_http_url, assert_response_peer_public


DOWNLOAD_MANIFEST_SCHEMA_VERSION = "download-manifest-v2"
DOWNLOAD_MANIFEST_ARTIFACT = "download_manifest_v2.json"
DOWNLOAD_VALIDATION_POLICY_VERSION = f"image-validation-v3-safe-redirects+{URL_SAFETY_POLICY_VERSION}"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        assert_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_reference_images(
    *,
    job_dir: str | Path,
    plugin: ProductPlugin,
    max_images: int = 0,
    force: bool = False,
    workers: int = 0,
) -> dict[str, Any]:
    job_path = Path(job_dir).resolve()
    inventory = _expected_inventory(job_path, max_images=max_images)
    previous = {} if force else _previous_download_rows(job_path)
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in inventory:
        groups.setdefault(item["url"], []).append(item)

    def execute(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
        reusable = next(
            (
                previous.get(_inventory_key(item))
                for item in group
                if previous.get(_inventory_key(item))
                and _download_row_reusable(job_path, previous[_inventory_key(item)])
            ),
            None,
        )
        active = [
            item
            for item in group
            if not (
                previous.get(_inventory_key(item), {}).get("status") == "failed"
                and not bool(previous.get(_inventory_key(item), {}).get("retryable"))
                and previous.get(_inventory_key(item), {}).get("input_revision_id") == _download_input_revision(item["url"])
            )
        ]
        if reusable is not None:
            raw = _manifest_path(job_path, reusable.get("raw_path"))
            assert raw is not None
            return [
                _download_success_row(
                    item=item,
                    raw=raw,
                    source_sha=str(reusable["source_sha256"]),
                    previous=previous.get(_inventory_key(item)),
                    network_attempted=False,
                    job_path=job_path,
                )
                for item in group
            ]
        if not active:
            return [dict(previous[_inventory_key(item)]) for item in group]
        object_name = hashlib.sha256(group[0]["url"].encode("utf-8")).hexdigest()
        try:
            raw = _download(
                group[0]["url"],
                Path("images") / "source_objects" / object_name,
                force,
                job_path=job_path,
            )
            source_sha = file_sha256(raw)
            return [
                _download_success_row(
                    item=item,
                    raw=raw,
                    source_sha=source_sha,
                    previous=previous.get(_inventory_key(item)),
                    network_attempted=True,
                    job_path=job_path,
                )
                for item in group
            ]
        except Exception as exc:
            return [
                dict(previous[_inventory_key(item)])
                if previous.get(_inventory_key(item), {}).get("status") == "failed"
                and not bool(previous.get(_inventory_key(item), {}).get("retryable"))
                and previous.get(_inventory_key(item), {}).get("input_revision_id") == _download_input_revision(item["url"])
                else _download_failure_row(
                    item=item, exc=exc, previous=previous.get(_inventory_key(item))
                )
                for item in group
            ]

    rows: list[dict[str, Any]] = []
    grouped = list(groups.values())
    worker_count = _download_workers(workers, len(grouped))
    if worker_count > 1:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(execute, group) for group in grouped]
            for future in as_completed(futures):
                rows.extend(future.result())
    else:
        for group in grouped:
            rows.extend(execute(group))
    rows.sort(key=lambda row: (str(row["child"]), int(row["index"])))
    artifact = {
        "schema_version": DOWNLOAD_MANIFEST_SCHEMA_VERSION,
        "inventory_fingerprint": _inventory_fingerprint(inventory),
        "category_id": plugin.category_id,
        "rows": rows,
    }
    write_json(_manifest_file(job_path), artifact)
    failures = [row for row in rows if row.get("status") != "ok"]
    return {
        "schema_version": DOWNLOAD_MANIFEST_SCHEMA_VERSION,
        "tasks": rows,
        "failures": [
            {
                "task": {
                    "logical_task_id": row["logical_task_id"],
                    "input_revision_id": row["input_revision_id"],
                    "child": row["child"],
                    "source_index": str(row["index"]),
                },
                "failure_owner": "download",
                "task_status": "retryable" if row.get("retryable") else "blocked",
                "error": row.get("error") or "download failed",
            }
            for row in failures
        ],
    }


def read_download_manifest(job_dir: str | Path) -> dict[str, Any]:
    job_path = Path(job_dir).resolve()
    path = _manifest_file(job_path)
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema_version") != DOWNLOAD_MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"Unsupported download manifest; create a new job: {path}")
    if not isinstance(data.get("rows"), list):
        raise ValueError(f"Download manifest rows are invalid: {path}")
    for index, row in enumerate(data["rows"]):
        if not isinstance(row, dict):
            raise ValueError(f"Download manifest row {index} is invalid: {path}")
        status = str(row.get("status") or "")
        raw_path = str(row.get("raw_path") or "").strip()
        if status == "ok":
            if _manifest_path(job_path, raw_path) is None:
                raise ValueError(f"Download manifest row {index} has an unsafe raw_path: {raw_path!r}")
        elif status == "failed":
            if raw_path:
                raise ValueError(f"Failed download manifest row {index} must not retain raw_path")
        else:
            raise ValueError(f"Download manifest row {index} has invalid status: {status!r}")
    return data


def download_artifacts_current(job_dir: str | Path, *, max_issues: int = 20) -> tuple[bool, list[str]]:
    job_path = Path(job_dir).resolve()
    try:
        artifact = read_download_manifest(job_path)
        expected = _expected_inventory(job_path)
    except Exception as exc:
        return False, [f"invalid download authority: {type(exc).__name__}: {exc}"]
    issues: list[str] = []
    rows = artifact["rows"]
    if artifact.get("inventory_fingerprint") != _inventory_fingerprint(expected):
        issues.append("download inventory fingerprint does not match current image URLs")
    actual_keys = [_inventory_key(row) for row in rows]
    expected_keys = [_inventory_key(row) for row in expected]
    if len(actual_keys) != len(set(actual_keys)):
        issues.append("download manifest contains duplicate inventory rows")
    if set(actual_keys) != set(expected_keys):
        issues.append("download inventory does not match ProductFamilyV3 image URLs")
    for row in rows:
        label = f"{row.get('child', '?')}/source_{row.get('index', '?')}"
        if row.get("input_revision_id") != _download_input_revision(str(row.get("url") or "")):
            issues.append(f"{label}: download validation policy changed")
        if row.get("status") == "ok":
            if not _download_row_reusable(job_path, row):
                issues.append(f"{label}: successful row has a missing, invalid, or changed image")
        elif row.get("status") != "failed":
            issues.append(f"{label}: invalid status {row.get('status')!r}")
        elif bool(row.get("retryable")):
            issues.append(f"{label}: retryable download is still pending")
        elif not str(row.get("error") or "").strip():
            issues.append(f"{label}: terminal failure has no recorded error")
        if len(issues) >= max_issues:
            break
    return not issues, issues


def _expected_inventory(job_path: Path, *, max_images: int = 0) -> list[dict[str, Any]]:
    family = read_product_family(job_path)
    children = family.get("family", {}).get("children")
    if not isinstance(children, list) or not children:
        raise ValueError("ProductFamilyV3 has no children")
    selected = set(str(child) for child in read_run_scope(job_path)["selected_children"])
    rows: list[dict[str, Any]] = []
    for child in children:
        asin = str(child.get("asin") or "").strip()
        if asin not in selected:
            continue
        urls = _dedupe_urls(_image_url(item) for item in child.get("reference_images") or [])
        if max_images > 0:
            urls = urls[:max_images]
        rows.extend({"child": asin, "index": index, "url": url} for index, url in enumerate(urls))
    return rows


def _inventory_key(row: dict[str, Any]) -> tuple[str, int, str]:
    return str(row.get("child") or ""), int(row.get("index") or 0), str(row.get("url") or "")


def _inventory_fingerprint(rows: Iterable[dict[str, Any]]) -> str:
    return input_revision_id(
        [{"child": child, "index": index, "url": url} for child, index, url in map(_inventory_key, rows)]
    )


def _download_task_id(child: str, url: str) -> str:
    return logical_task_id("download", child=child, source_id=input_revision_id({"url": url})[:24])


def _download_input_revision(url: str) -> str:
    return input_revision_id({"url": url, "validation_policy": DOWNLOAD_VALIDATION_POLICY_VERSION})


def _download_failure_row(
    *, item: dict[str, Any], exc: Exception, previous: dict[str, Any] | None
) -> dict[str, Any]:
    revision = _download_input_revision(item["url"])
    attempts = int((previous or {}).get("attempts") or 0) + 1 if (previous or {}).get("input_revision_id") == revision else 1
    retryable = _download_error_retryable(exc)
    return {
        **item,
        "raw_path": "",
        "source_sha256": "",
        "logical_task_id": _download_task_id(item["child"], item["url"]),
        "input_revision_id": revision,
        "status": "failed",
        "attempts": attempts,
        "retryable": retryable,
        "error": f"{type(exc).__name__}: {exc}",
    }


def _download_success_row(
    *,
    item: dict[str, Any],
    raw: Path,
    source_sha: str,
    previous: dict[str, Any] | None,
    network_attempted: bool,
    job_path: Path,
) -> dict[str, Any]:
    revision = _download_input_revision(item["url"])
    attempts = int((previous or {}).get("attempts") or 0) if (previous or {}).get("input_revision_id") == revision else 0
    return {
        **item,
        "raw_path": _job_relative(job_path, raw),
        "source_sha256": source_sha,
        "logical_task_id": _download_task_id(item["child"], item["url"]),
        "input_revision_id": revision,
        "status": "ok",
        "attempts": attempts + (1 if network_attempted else 0),
        "retryable": False,
        "error": "",
    }


def _previous_download_rows(job_path: Path) -> dict[tuple[str, int, str], dict[str, Any]]:
    try:
        rows = read_download_manifest(job_path)["rows"]
    except Exception:
        return {}
    return {_inventory_key(row): row for row in rows if isinstance(row, dict)}


def _download_row_reusable(job_path: Path, row: dict[str, Any]) -> bool:
    if row.get("status") != "ok":
        return False
    raw = _manifest_path(job_path, row.get("raw_path"))
    expected_sha = str(row.get("source_sha256") or "")
    if raw is None or not raw.is_file() or not expected_sha or file_sha256(raw) != expected_sha:
        return False
    if not _download_url_matches(raw, str(row.get("url") or "")):
        return False
    try:
        _validate_image_bytes(raw.read_bytes(), str(row.get("url") or raw))
    except Exception:
        return False
    return True


def _manifest_file(job_path: Path) -> Path:
    return resolve_job_owned_path(
        job_path,
        Path(job_path) / "images" / DOWNLOAD_MANIFEST_ARTIFACT,
    )


def _manifest_path(job_path: Path, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        return None
    try:
        return resolve_job_owned_path(job_path, Path(job_path) / path)
    except ValueError:
        return None


def _job_relative(job_path: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(job_path.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"Downloaded image is outside the current job: {path}") from exc


def _image_url(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("url") or "")
    return ""


def _dedupe_urls(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        url = str(value or "").strip()
        identity = amazon_image_identity(url) if "amazon." in url.casefold() else ""
        key = f"amazon:{identity}" if identity else f"url:{url}"
        if url and key not in seen:
            seen.add(key)
            result.append(url)
    return result


def _download(url: str, out_no_ext: Path, force: bool, *, job_path: Path) -> Path:
    out_no_ext = resolve_job_owned_path(job_path, out_no_ext)
    if not force:
        for existing in _existing_download_candidates(out_no_ext):
            if _download_url_matches(existing, url):
                try:
                    _validate_image_bytes(existing.read_bytes(), url)
                    return existing
                except RuntimeError:
                    existing.unlink(missing_ok=True)
                    _download_url_marker(existing).unlink(missing_ok=True)
    attempts = _download_retry_attempts()
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _download_once(url, out_no_ext)
        except Exception as exc:
            last_error = exc
            if attempt >= attempts or not _download_error_retryable(exc):
                raise
            time.sleep(_download_retry_delay(attempt))
    raise last_error or RuntimeError(f"Download failed: {url}")


def _download_once(url: str, out_no_ext: Path) -> Path:
    assert_public_http_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        },
    )
    with urllib.request.build_opener(_PublicRedirectHandler()).open(request, timeout=90) as response:
        # Re-check the connected peer to close the DNS-rebinding gap between
        # assert_public_http_url() and urllib's actual socket connection.
        assert_response_peer_public(response, hostname=urlparse(url).hostname or "")
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        maximum = _maximum_download_bytes()
        declared = int(response.headers.get("Content-Length") or 0)
        if declared > maximum:
            raise RuntimeError(f"Reference image exceeds download limit: {url} bytes={declared}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(min(1024 * 1024, maximum - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise RuntimeError(f"Reference image exceeds download limit: {url} maximum={maximum}")
            chunks.append(chunk)
        data = b"".join(chunks)
    if content_type and (content_type.startswith("text/") or "html" in content_type.lower()):
        raise RuntimeError(f"Downloaded file is not a valid image: {url} content-type={content_type}")
    _validate_image_bytes(data, url)
    # out_no_ext was resolved once by _download. The suffix comes from the
    # fixed IMAGE_EXTS allowlist, so resolving the same derived path again can
    # only introduce a race with Windows path metadata; it adds no safety.
    out = out_no_ext.with_suffix(_extension_for(url, content_type))
    out.parent.mkdir(parents=True, exist_ok=True)
    for existing in _existing_download_candidates(out_no_ext):
        if existing != out:
            existing.unlink(missing_ok=True)
            _download_url_marker(existing).unlink(missing_ok=True)
    write_bytes_atomic(out, data)
    write_bytes_atomic(
        _download_url_marker(out),
        url.encode("utf-8"),
    )
    return out


def _extension_for(url: str, content_type: str | None) -> str:
    guessed = mimetypes.guess_extension(content_type or "")
    if guessed in IMAGE_EXTS:
        return ".jpg" if guessed == ".jpeg" else guessed
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in IMAGE_EXTS else ".jpg"


def _download_error_retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in {408, 429, 500, 502, 503, 504}
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(token in text for token in (
        "timeout", "timed out", "connection", "temporar", "content-type=text/",
        "content-type=application/xhtml", " 429", " 500", " 502", " 503", " 504",
    ))


def _download_workers(requested: int, task_count: int) -> int:
    if task_count <= 1:
        return 1
    raw = os.environ.get("AMAZON_FACTORY_DOWNLOAD_WORKERS", "").strip()
    if raw:
        try:
            return max(1, min(8, int(raw), task_count))
        except ValueError:
            pass
    return max(1, min(8, requested or 4, task_count))


def _download_retry_attempts() -> int:
    try:
        return max(1, min(6, int(float(os.environ.get("AMAZON_FACTORY_IMAGE_DOWNLOAD_RETRY_ATTEMPTS", "3")))))
    except (TypeError, ValueError):
        return 3


def _maximum_download_bytes() -> int:
    try:
        return max(1024 * 1024, min(100 * 1024 * 1024, int(os.environ.get("AMAZON_FACTORY_MAX_REFERENCE_IMAGE_BYTES", str(25 * 1024 * 1024)))))
    except (TypeError, ValueError):
        return 25 * 1024 * 1024


def _download_retry_delay(attempt: int) -> float:
    try:
        base = max(0.0, float(os.environ.get("AMAZON_FACTORY_IMAGE_DOWNLOAD_RETRY_BASE_SECONDS", "0.5")))
    except (TypeError, ValueError):
        base = 0.5
    return min(10.0, base * (2 ** max(0, attempt - 1)))


def _existing_download_candidates(out_no_ext: Path) -> list[Path]:
    if not out_no_ext.parent.exists():
        return []
    return sorted(
        path for path in out_no_ext.parent.glob(f"{out_no_ext.name}.*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS
    )


def _download_url_matches(path: Path, url: str) -> bool:
    try:
        return _download_url_marker(path).read_text(encoding="utf-8").strip() == url
    except OSError:
        return False


def _download_url_marker(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".url.txt")


def _validate_image_bytes(data: bytes, url: str) -> None:
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image.verify()
    except Exception as exc:
        raise RuntimeError(f"Downloaded file is not a valid image: {url} bytes={len(data)}") from exc
    minimum_side, minimum_pixels = 320, 250_000
    if min(width, height) < minimum_side or width * height < minimum_pixels:
        raise RuntimeError(
            f"Downloaded image is below usable reference resolution: {url} size={width}x{height} "
            f"minimum_side={minimum_side}px minimum_pixels={minimum_pixels}"
        )
