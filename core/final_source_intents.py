from __future__ import annotations
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from .asset_manager import download_artifacts_current, read_download_manifest
from .image_role_ocr import ocr_evidence_for_image
from .image_pixel_evidence import inspect_image_pixel_evidence
from .io import file_sha256, read_jsonl, write_json, write_jsonl
from .model_router import ModelRouterError, clients_for_scope
from .plugin import ProductPlugin
from .paths import resolve_job_owned_path
from .product_family import read_product_family
from .run_scope import ensure_run_scope, row_in_scope
from .status import input_revision_id, logical_task_id
from .text_evidence import clean_evidence_text, extract_measurements, has_bad_encoding, normalize_text
from .vision_gemini_client import gemini_stream_generate
FINAL_SOURCE_INTENT_SCHEMA_VERSION = "final-source-intent-v1"
FINAL_SOURCE_INTENT_ARTIFACT = "final_source_intents_v1.jsonl"
FINAL_SOURCE_INTENT_POLICY_VERSION = "final-source-intent-policy-v12-bound-phrases-and-measurements"
SOURCE_INTENT_REVIEW_SCHEMA_VERSION = "source-intent-review-v1"
SOURCE_INTENT_REVIEW_ARTIFACT = "source_intent_reviews_v1.jsonl"
SOURCE_INTENT_REVIEW_ROLES = frozenset({"scene", "func", "size"})
_VISUAL_RECOVERY_POLICY_VERSION = "final-source-intent-visual-recovery-v4-authored-evidence"
PLANNING_SOURCE_ROLES = frozenset({"main", "scene", "func", "size"})
_DIMENSION_WORD = re.compile(r"\b(size|dimensions?|width|height|depth|length|overall|tall|wide|inch(?:es)?|cm|mm|ft|feet)\b", re.I)
_DIRECTION_WORD = re.compile(r"\b(width|height|depth|length|overall|tall|wide)\b", re.I)
_MULTI_AXIS = re.compile(r"\b\d+(?:\.\d+)?\s*(?:[xX*]\s*\d+(?:\.\d+)?\s*){1,3}", re.I)
_AUTHORED_FUNC_WORD = re.compile(r"\b(material|wood|metal|fabric|steel|aluminum|finish|secure|safe|safety|stable|reinforced|durable|support|storage|drawer|shelf|door|hinge|handle|mirror|adjustable|removable|foldable|expandable|convertible|guardrails?|slats?|ladder|slide|wheels?|casters?|mount(?:ed|ing)?|pot|base|stakes?|spikes?|waterproof|weather[- ]?resistant|fade[- ]?resistant|anti[- ]?tip|magnetic|close[- ]?up|detail|feature|function)\b", re.I)
_SCENE_WORD = re.compile(r"\b(living room|office|bedroom|bathroom|kitchen|laundry|hallway|entryway|nursery|home|room|decor)\b", re.I)
_NOISE_TEXT = re.compile(r"^[^A-Za-z0-9]*$|^[A-Za-z]{1,2}$|^\d{1,3}$")
class FinalSourceIntentError(RuntimeError):
    pass
def build_final_source_intents(*, job_dir: str | Path, plugin: ProductPlugin, workers: int = 0, limit: int = 0,
                               deadline_monotonic: float | None = None) -> dict[str, Any]:
    """Build one immutable, final role decision for every scoped downloaded source."""
    job = Path(job_dir).resolve()
    ensure_run_scope(job_dir=job, limit=limit)
    downloads_current, download_issues = download_artifacts_current(job)
    if not downloads_current:
        raise FinalSourceIntentError(
            "DownloadManifestV2 is not current for classification: "
            + "; ".join(download_issues[:5])
        )
    downloads = [
        row
        for row in read_download_manifest(job)["rows"]
        if row.get("status") == "ok" and row_in_scope(job, row)
    ]
    source_reviews = _current_source_intent_reviews(job, downloads)
    family = read_product_family(job)
    children = {str(row["asin"]): row for row in family["family"]["children"]}
    evidence_by_sha = _collect_evidence_by_sha(job, downloads, workers=_classification_workers(workers, len(downloads)), deadline_monotonic=deadline_monotonic)
    prepared_by_child: dict[str, list[dict[str, Any]]] = {}
    for download in downloads:
        try:
            prepared = _prepare_source(
                job,
                plugin,
                download,
                evidence_by_sha[str(download.get("source_sha256") or "")],
                children.get(str(download.get("child") or ""), {}),
            )
            prepared["source_review"] = source_reviews.get(
                (
                    str(download.get("child") or ""),
                    int(download.get("index", download.get("source_index", 0)) or 0),
                    str(download.get("source_sha256") or ""),
                )
            )
            prepared_by_child.setdefault(str(download.get("child") or ""), []).append(prepared)
        except Exception as exc:
            row = _failure_row(plugin, download, exc)
            prepared_by_child.setdefault(str(download.get("child") or ""), []).append({"final_row": row})
    rows: list[dict[str, Any]] = []
    for child in sorted(prepared_by_child):
        rows.extend(_finalize_child(prepared_by_child[child]))
    rows.sort(key=lambda row: (str(row.get("child") or ""), int(row.get("source_index") or 0)))
    artifact = resolve_job_owned_path(job, job / "reports" / FINAL_SOURCE_INTENT_ARTIFACT)
    write_jsonl(artifact, rows)
    persisted = read_jsonl(artifact)
    if len(persisted) != len(rows):
        raise FinalSourceIntentError("FinalSourceIntentV1 write verification changed the source inventory")
    for row in persisted:
        _validate_row(row)
    return {
        "schema_version": FINAL_SOURCE_INTENT_SCHEMA_VERSION,
        "tasks": rows,
        "failures": [
            _stage_failure(row)
            for row in rows
            if row.get("status") == "failed" or row.get("role") == "review_required"
        ],
    }
def read_final_source_intents(job_dir: str | Path, *, plugin: ProductPlugin | None = None,
                              require_current: bool = True) -> list[dict[str, Any]]:
    job = Path(job_dir).resolve()
    artifact = resolve_job_owned_path(job, job / "reports" / FINAL_SOURCE_INTENT_ARTIFACT)
    if not artifact.is_file():
        raise FinalSourceIntentError(f"Current FinalSourceIntentV1 artifact is missing: {artifact}")
    rows = read_jsonl(artifact)
    downloads = {
        (str(row.get("child") or ""), _source_index(row)): row
        for row in read_download_manifest(job)["rows"]
        if row.get("status") == "ok" and row_in_scope(job, row)
    }
    actual: set[tuple[str, int]] = set()
    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        _validate_row(row)
        if plugin is not None and row.get("category_id") != plugin.category_id:
            raise FinalSourceIntentError("FinalSourceIntentV1 category does not match active plugin")
        key = (str(row["child"]), int(row["source_index"]))
        if key in actual:
            raise FinalSourceIntentError(f"Duplicate FinalSourceIntentV1 row: {key[0]}/{key[1]}")
        actual.add(key)
        by_key[key] = row
        if not require_current:
            continue
        download = downloads.get(key)
        source = _job_path(job, row.get("source_path"))
        if download is None or source is None or not source.is_file():
            raise FinalSourceIntentError(f"FinalSourceIntentV1 has no current download: {key[0]}/{key[1]}")
        expected_sha = str(download.get("source_sha256") or "")
        if row.get("source_sha256") != expected_sha or file_sha256(source) != expected_sha:
            raise FinalSourceIntentError(f"Source image SHA changed: {key[0]}/{key[1]}")
        if row.get("input_revision_id") != _semantic_revision(row):
            raise FinalSourceIntentError(f"FinalSourceIntentV1 semantic revision changed: {key[0]}/{key[1]}")
    if require_current and actual != set(downloads):
        missing = sorted(set(downloads) - actual)[:5]
        extra = sorted(actual - set(downloads))[:5]
        raise FinalSourceIntentError(f"FinalSourceIntentV1 inventory mismatch: missing={missing}, extra={extra}")
    if require_current:
        reviews = _current_source_intent_reviews(job, list(downloads.values()))
        for (child, source_index, _sha), review in reviews.items():
            row = by_key.get((child, source_index), {})
            if (
                row.get("role") != review.get("role")
                or str(review.get("review_fingerprint") or "") not in str(row.get("classification_reason") or "")
            ):
                raise FinalSourceIntentError(
                    f"FinalSourceIntentV1 has not applied current source review: {child}/{source_index}"
                )
        reviewed_keys = {(child, source_index) for child, source_index, _sha in reviews}
        stale_embedded = [
            key for key, row in by_key.items()
            if str(row.get("classification_reason") or "").startswith("human_source_role_review=")
            and key not in reviewed_keys
        ]
        if stale_embedded:
            raise FinalSourceIntentError(
                f"FinalSourceIntentV1 contains stale source review: {stale_embedded[0][0]}/{stale_embedded[0][1]}"
            )
    return rows


def record_source_intent_review(
    job_dir: str | Path, *, child: str, source_index: int, role: str, reason: str,
) -> dict[str, Any]:
    """Record SHA-bound human evidence consumed by FinalSourceIntentV1."""
    job = Path(job_dir).resolve()
    role = str(role or "").strip().lower()
    reason = " ".join(str(reason or "").split())
    if role not in SOURCE_INTENT_REVIEW_ROLES:
        raise FinalSourceIntentError(
            f"Source review role must be one of {sorted(SOURCE_INTENT_REVIEW_ROLES)}"
        )
    if not reason:
        raise FinalSourceIntentError("Source review requires a reason")
    ensure_run_scope(job_dir=job)
    download = next(
        (
            row for row in read_download_manifest(job)["rows"]
            if row.get("status") == "ok"
            and row_in_scope(job, row)
            and str(row.get("child") or "") == str(child)
            and _source_index(row) == int(source_index)
        ),
        None,
    )
    if not isinstance(download, dict):
        raise FinalSourceIntentError(f"Current downloaded source not found: {child}/{source_index}")
    if int(source_index) == 0:
        raise FinalSourceIntentError("source_00 is the immutable main source and cannot be reassigned")
    # A manual decision is still part of the same child-level role contract:
    # one size authority, no duplicate source key, and no stale decision from
    # a different downloaded SHA may remain active.
    existing_reviews = _current_source_intent_reviews(job, read_download_manifest(job)["rows"])
    proposed_key = (str(child), int(source_index), str(download.get("source_sha256") or ""))
    for key, current_row in existing_reviews.items():
        if key == proposed_key:
            continue
        if key[0] == str(child) and current_row.get("role") == role and role == "size":
            raise FinalSourceIntentError(f"Child already has a current size review: {child}/{key[1]}")
    source_sha = str(download.get("source_sha256") or "")
    row = {
        "schema_version": SOURCE_INTENT_REVIEW_SCHEMA_VERSION,
        "child": str(child),
        "source_index": int(source_index),
        "source_sha256": source_sha,
        "role": role,
        "reason": reason[:300],
    }
    row["review_fingerprint"] = input_revision_id(row)
    path = resolve_job_owned_path(job, job / "reports" / SOURCE_INTENT_REVIEW_ARTIFACT)
    existing = read_jsonl(path) if path.is_file() else []
    current = [
        item for item in existing
        if isinstance(item, dict)
        and not (
            str(item.get("child") or "") == str(child)
            and int(item.get("source_index") or 0) == int(source_index)
        )
    ]
    write_jsonl(path, [*current, row])
    return row


def planning_source_intents(
    job_dir: str | Path, *, plugin: ProductPlugin, child: str = "",
) -> list[dict[str, Any]]:
    """Return the one authoritative source set used by planning and task formation."""
    rows = read_final_source_intents(job_dir, plugin=plugin, require_current=True)
    return [
        row for row in rows
        if row.get("status") == "success"
        and row.get("role") in PLANNING_SOURCE_ROLES
        and (not child or str(row.get("child") or "") == str(child))
    ]


def selected_task_source_intents(
    job_dir: str | Path, *, plugin: ProductPlugin, child: str = "",
) -> list[dict[str, Any]]:
    """Return the single source inventory consumed by planning and task formation."""
    return planning_source_intents(job_dir, plugin=plugin, child=child)


def _current_source_intent_reviews(
    job: Path, downloads: list[dict[str, Any]],
) -> dict[tuple[str, int, str], dict[str, Any]]:
    path = resolve_job_owned_path(job, job / "reports" / SOURCE_INTENT_REVIEW_ARTIFACT)
    if not path.is_file():
        return {}
    current_downloads = {
        (
            str(row.get("child") or ""),
            _source_index(row),
            str(row.get("source_sha256") or ""),
        )
        for row in downloads
    }
    decisions: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in read_jsonl(path):
        if not isinstance(row, dict) or set(row) != {
            "schema_version", "child", "source_index", "source_sha256",
            "role", "reason", "review_fingerprint",
        }:
            raise FinalSourceIntentError("Invalid source intent review row")
        fingerprint = str(row.get("review_fingerprint") or "")
        payload = {key: value for key, value in row.items() if key != "review_fingerprint"}
        if (
            row.get("schema_version") != SOURCE_INTENT_REVIEW_SCHEMA_VERSION
            or row.get("role") not in SOURCE_INTENT_REVIEW_ROLES
            or not str(row.get("reason") or "").strip()
            or fingerprint != input_revision_id(payload)
        ):
            raise FinalSourceIntentError("Invalid source intent review contract")
        key = (
            str(row.get("child") or ""),
            int(row.get("source_index") or 0),
            str(row.get("source_sha256") or ""),
        )
        if key not in current_downloads:
            continue
        if key in decisions:
            raise FinalSourceIntentError(
                f"Duplicate current source intent review: {key[0]}/{key[1]}"
            )
        decisions[key] = row
    return decisions


def final_source_intents_current(job_dir: str | Path, plugin: ProductPlugin,
                                 limit: int = 0) -> tuple[bool, list[str]]:
    del limit
    try:
        rows = read_final_source_intents(job_dir, plugin=plugin, require_current=True)
        if not rows:
            return False, ["FinalSourceIntentV1 has no scoped source rows"]
        # Evidence incompleteness belongs to the source/role task that uses it.
        # It is not artifact staleness: making one OCR or visual-recovery miss
        # invalidate the whole family suppressed ready siblings and forced a
        # full image-branch retry without changing the input.  Structural
        # currentness is still enforced by read_final_source_intents above;
        # task formation records the remaining source-specific review/block.
        return True, []
    except Exception as exc:
        return False, [f"{type(exc).__name__}: {exc}"]
def _collect_evidence_by_sha(job: Path, downloads: list[dict[str, Any]], *,
                             workers: int, deadline_monotonic: float | None = None) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in downloads:
        sha = str(row.get("source_sha256") or "")
        grouped.setdefault(sha, []).append(row)
    evidence: dict[str, dict[str, Any]] = {}
    max_workers = max(1, min(int(workers or 1), len(grouped) or 1, 3))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_evidence_for_sha, job, sha, rows, deadline_monotonic=deadline_monotonic): sha for sha, rows in grouped.items()}
        for future in as_completed(futures):
            sha = futures[future]
            try:
                evidence[sha] = future.result()
            except Exception as exc:
                evidence[sha] = _empty_evidence(f"{type(exc).__name__}: {exc}")
    return evidence


def _classification_workers(requested: int, source_count: int) -> int:
    """Honor explicit serial execution; automatic observation concurrency is two."""
    if source_count <= 1:
        return 1
    try:
        requested_count = int(requested or 2)
    except (TypeError, ValueError):
        requested_count = 1
    return max(1, min(requested_count, source_count, 3))
def _evidence_for_sha(job: Path, sha: str, downloads: list[dict[str, Any]], *, deadline_monotonic: float | None = None) -> dict[str, Any]:
    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
        raise FinalSourceIntentError("Classification execution deadline exhausted")
    source = _job_path(job, downloads[0].get("raw_path"))
    if source is None or not source.is_file() or file_sha256(source) != sha:
        raise FinalSourceIntentError(f"Downloaded source changed before classification: {downloads[0].get('raw_path')}")
    needs_ocr = any(_source_index(row) != 0 for row in downloads)
    ocr = (
        ocr_evidence_for_image(source, cache_root=resolve_job_owned_path(job, job / "reports" / "ocr_evidence"))
        if needs_ocr
        else {
            "available": False,
            "error": "ocr_skipped_source_00_main",
            "raw_text": "",
            "lines": [],
            "retryable": False,
        }
    )
    trusted = _trusted_text_lines(ocr)
    raw_measurements = [
        {**value, "source_label": line, "source_occurrence": f"{line_index}:{index}"}
        for line_index, line in enumerate(trusted)
        for index, value in enumerate(extract_measurements(line))
    ]
    measurements = _independent_measurements(raw_measurements)
    claims = _authored_claims(trusted)
    pixels = _pixel_evidence(source)
    base = {
        "ocr_evidence": ocr,
        "trusted_text": trusted,
        "measurements": measurements,
        "claims": claims,
        "text": " ".join(trusted),
        "pixel_evidence": pixels,
    }
    visual = _visual_recovery(job, source, sha, downloads, base, deadline_monotonic=deadline_monotonic)
    return {**base, "visual_evidence": visual, "claims": _authored_claims(trusted, visual=visual)}
def _visual_recovery(job: Path, source: Path, sha: str, downloads: list[dict[str, Any]],
                     evidence: dict[str, Any], *, deadline_monotonic: float | None = None) -> dict[str, Any]:
    if not _needs_visual_recovery(downloads, evidence):
        return {"status": "not_needed", "reason": "deterministic evidence is sufficient"}
    cache = resolve_job_owned_path(job, job / "reports" / "final_source_intent_visual_evidence" / f"{sha}_{_VISUAL_RECOVERY_POLICY_VERSION}.json")
    if cache.is_file():
        try:
            value = json.loads(cache.read_text(encoding="utf-8"))
            if (
                value.get("status") == "success"
                and value.get("source_sha256") == sha
                and value.get("policy_version") == _VISUAL_RECOVERY_POLICY_VERSION
            ):
                return value
        except Exception:
            pass
    clients = _observation_clients()
    if not clients:
        return {"status": "unavailable", "reason": "source-observation provider is not configured"}
    last_error: Exception | None = None
    for client in clients:
        provider = str(client.get("name") or "")
        try:
            response = gemini_stream_generate(
                _visual_recovery_prompt(),
                [source],
                client_scope="visual_planning",
                preferred_client_name=provider,
                timeout_seconds=25,
                total_timeout_seconds=35,
                deadline_monotonic=deadline_monotonic,
                response_validator=_visual_response_valid,
            )
            value = _normalize_visual_evidence(_parse_json_object(response))
            value.update(
                {
                    "status": "success",
                    "policy_version": _VISUAL_RECOVERY_POLICY_VERSION,
                    "source_sha256": sha,
                    "provider_name": provider,
                }
            )
            write_json(cache, value)
            return value
        except Exception as exc:
            last_error = exc
    return {
        "status": "failed",
        "error": f"{type(last_error).__name__}: {last_error}" if last_error else "no usable source-observation provider",
    }
def _needs_visual_recovery(downloads: list[dict[str, Any]], evidence: dict[str, Any]) -> bool:
    if not any(_source_index(row) != 0 for row in downloads):
        return False
    ocr = evidence["ocr_evidence"]
    if ocr.get("retryable") or (ocr.get("error") and evidence.get("trusted_text") == []):
        return True
    # OCR engines may return a raw aggregate string without line-level
    # confidence or geometry.  It is useful as a hint that authored content
    # may exist, but it is never trusted evidence and must force the visual
    # recovery/review path instead of selecting a role by itself.
    if _has_untrusted_raw_text(ocr, evidence.get("trusted_text") or []):
        return True
    pixels = evidence.get("pixel_evidence") or {}
    if _deterministic_size_evidence(evidence):
        return False
    if evidence.get("claims"):
        return False
    if pixels.get("scene_pixels") and not pixels.get("product_view_pixels"):
        return False
    return bool(evidence.get("trusted_text") or pixels.get("product_view_pixels") or pixels.get("error"))
def _prepare_source(job: Path, plugin: ProductPlugin, download: dict[str, Any],
                    evidence: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    source_index = _source_index(download)
    source_path = _relative_source_path(job, download.get("raw_path"))
    source = resolve_job_owned_path(job, job / source_path)
    source_sha = str(download.get("source_sha256") or "")
    if not source.is_file() or file_sha256(source) != source_sha:
        raise FinalSourceIntentError(f"Source path is invalid or changed: {source_path}")
    measurements = _measurement_rows(evidence.get("measurements") or [], child)
    trusted_text = list(evidence.get("trusted_text") or [])
    visual = dict(evidence.get("visual_evidence") or {})
    # A matching child fact can corroborate OCR without a second observation
    # request; a layout signal alone never authorizes arbitrary prop text.
    claims = _authored_claims(trusted_text, visual=visual, product_text=_plain_text({
        key: child.get(key) for key in ("title", "bullets", "specs", "product_specific")
    }))
    signals = _signals(source_index, {**evidence, "claims": claims}, measurements)
    return {
        "plugin": plugin,
        "download": download,
        "source_index": source_index,
        "source_path": source_path,
        "source_sha256": source_sha,
        "trusted_text": trusted_text,
        "claims": claims,
        "measurements": measurements,
        "ocr_evidence": dict(evidence.get("ocr_evidence") or {}),
        "pixel_evidence": dict(evidence.get("pixel_evidence") or {}),
        "visual_evidence": visual,
        "signals": signals,
        "size_candidate": source_index != 0 and bool(signals["has_rich_dimension_layout"]),
    }
def _finalize_child(prepared_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reviewed_sizes = [
        row for row in prepared_rows
        if not row.get("final_row")
        and isinstance(row.get("source_review"), dict)
        and row["source_review"].get("role") == "size"
    ]
    if len(reviewed_sizes) > 1:
        child = str(reviewed_sizes[0].get("download", {}).get("child") or "")
        raise FinalSourceIntentError(f"Source review assigns more than one size image for {child}")
    candidates = [
        row for row in prepared_rows
        if row.get("size_candidate")
        and not row.get("final_row")
        and not isinstance(row.get("source_review"), dict)
    ]
    size_winner = reviewed_sizes[0] if reviewed_sizes else (
        max(candidates, key=_size_strength) if candidates else None
    )
    final: list[dict[str, Any]] = []
    for prepared in sorted(prepared_rows, key=lambda row: int(row.get("source_index") or 0)):
        if prepared.get("final_row"):
            final.append(prepared["final_row"])
            continue
        review = prepared.get("source_review") if isinstance(prepared.get("source_review"), dict) else None
        role = "main" if prepared["source_index"] == 0 else (
            str(review["role"]) if review else (
                "size" if prepared is size_winner else _non_size_role(prepared)
            )
        )
        final.append(_build_final_row(
            prepared,
            role,
            additional_size=bool(
                not review and prepared.get("size_candidate") and prepared is not size_winner
            ),
            source_review=review,
        ))
    return final
def _non_size_role(prepared: dict[str, Any]) -> str:
    signals = prepared["signals"]
    visual = prepared["visual_evidence"]
    visual_role = str(visual.get("role_guess") or "unknown")
    visual_confidence = float(visual.get("confidence") or 0.0)
    # Authored evidence is determinative for function imagery.  Claims are
    # downstream renderable evidence and may legitimately be empty when OCR
    # or the visual provider did not return text; role classification must not
    # turn an annotated/detail image into review_required in that case.
    if (
        signals["has_authored_information"]
        or signals["has_authored_function_text"]
        or signals["has_callout_layout"]
        or int(signals.get("trusted_text_count") or 0) > 0
    ):
        return "func"
    if visual_role == "scene" and visual_confidence >= 0.55 and not signals["has_authored_information"]:
        return "scene"
    if (
        str(visual.get("status") or "") in {"failed", "unavailable"}
        and signals["has_alternate_product_view"]
        and not signals["has_authored_information"]
    ):
        return "review_required"
    if not signals["has_authored_information"] and (
        signals["has_scene_pixels"] or signals["has_alternate_product_view"]
    ):
        return "scene"
    if signals["has_product_pixels"] and not signals["has_authored_information"]:
        return "scene"
    return "review_required"


def _build_final_row(
    prepared: dict[str, Any], role: str, *, additional_size: bool,
    source_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signals = dict(prepared["signals"])
    signals["reference_completeness"] = _reference_completeness(role, signals)
    flags = _evidence_flags(signals)
    claims = _bound_claims(prepared) if role in {"func", "review_required"} else []
    measurements = list(prepared["measurements"])
    warnings = _warnings(prepared, role, additional_size=additional_size)
    row = {
        "schema_version": FINAL_SOURCE_INTENT_SCHEMA_VERSION,
        "policy_version": FINAL_SOURCE_INTENT_POLICY_VERSION,
        "category_id": prepared["plugin"].category_id,
        "child": str(prepared["download"].get("child") or ""),
        "source_index": int(prepared["source_index"]),
        "source_path": str(prepared["source_path"]),
        "source_sha256": prepared["source_sha256"],
        "status": "success",
        "role": role,
        "classification_reason": (
            f"human_source_role_review={source_review['review_fingerprint']}; {source_review['reason']}"
            if source_review else _classification_reason(role, signals, additional_size=additional_size)
        ),
        "evidence_flags": flags,
        "signals": signals,
        "ocr_evidence": prepared["ocr_evidence"],
        "pixel_evidence": prepared["pixel_evidence"],
        "visual_evidence": prepared["visual_evidence"],
        "trusted_text": prepared["trusted_text"],
        "claims": claims,
        "measurements": measurements,
        "shopping_intent": _shopping_intent(role, claims, measurements),
        "warnings": warnings,
        "logical_task_id": logical_task_id(
            "classify", child=str(prepared["download"].get("child") or ""), source_id=str(prepared["source_index"])
        ),
    }
    row["input_revision_id"] = _semantic_revision(row)
    return row


def _reference_completeness(role: str, signals: dict[str, Any]) -> str:
    """Describe what the selected image can prove without blocking generation.

    This is deliberately an evidence label, not a readiness gate.  A function
    or size image may be a partial view; the image model must then preserve
    only visible structure instead of reconstructing hidden product regions.
    """
    if role == "main":
        return "complete_product_view"
    if role == "scene":
        return "scene_context_only"
    if role == "func":
        if signals.get("has_alternate_product_view") and not signals.get("has_callout_layout"):
            return "complete_product_view"
        return "partial_feature_view"
    if role == "size":
        return "partial_feature_view"
    return "partial_feature_view"


def _bound_claims(prepared: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_sha = str(prepared.get("source_sha256") or "")
    values = list(prepared.get("claims") or [])
    for value in values:
        if not isinstance(value, dict):
            continue
        text = normalize_text(value.get("text"))
        if not text or has_bad_encoding(text):
            continue
        rows.append({
            "evidence_id": input_revision_id({
                "source_sha256": source_sha,
                "text": normalize_text(text),
                "type": str(value.get("type") or "source_visible"),
            })[:20],
            "source_sha256": source_sha,
            "text": text,
            "type": str(value.get("type") or "source_visible"),
            "confidence": str(value.get("confidence") or "source_visible"),
        })
    return rows
def _signals(source_index: int, evidence: dict[str, Any], measurements: list[dict[str, Any]]) -> dict[str, Any]:
    trusted = list(evidence.get("trusted_text") or [])
    text = " ".join(trusted)
    visual = evidence.get("visual_evidence") or {}
    pixels = evidence.get("pixel_evidence") or {}
    distinct_measurements = len(_independent_measurements(measurements))
    measurement_lines = sum(1 for line in trusted if extract_measurements(line))
    direction_count = len({word.lower() for word in _DIRECTION_WORD.findall(text)})
    textual_dimension_layout = distinct_measurements >= 2 and (
        measurement_lines >= 2 or direction_count >= 2 or bool(_MULTI_AXIS.search(text)) or distinct_measurements >= 3
    )
    visual_dimension_layout = (
        str(visual.get("role_guess") or "") == "size"
        and bool(visual.get("has_dimension_lines"))
        and int(visual.get("visible_number_count") or len(visual.get("visible_numbers_or_units") or [])) >= 2
        and float(visual.get("confidence") or 0.0) >= 0.55
    )
    callouts = bool(visual.get("has_callouts_or_panels")) and float(visual.get("confidence") or 0.0) >= 0.5
    authored_function = bool(evidence.get("claims"))
    authored_info = bool(authored_function or callouts or textual_dimension_layout or visual_dimension_layout)
    untrusted_ocr_text = _has_untrusted_raw_text(
        evidence.get("ocr_evidence") or {}, trusted,
    )
    return {
        "is_source_00": source_index == 0,
        "ocr_available": bool((evidence.get("ocr_evidence") or {}).get("available") is not False),
        "trusted_text_count": len(trusted),
        "measurement_count": distinct_measurements,
        "measurement_line_count": measurement_lines,
        "direction_word_count": direction_count,
        "has_dimension_words": bool(_DIMENSION_WORD.search(text)),
        "has_textual_dimension_layout": textual_dimension_layout,
        "has_visual_dimension_layout": visual_dimension_layout,
        "has_rich_dimension_layout": textual_dimension_layout or visual_dimension_layout,
        "has_callout_layout": callouts,
        "has_authored_function_text": authored_function,
        "has_authored_information": authored_info,
        "has_untrusted_ocr_text": untrusted_ocr_text,
        "has_scene_words": bool(_SCENE_WORD.search(text)),
        "has_scene_pixels": bool(pixels.get("scene_pixels")),
        "has_alternate_product_view": bool(pixels.get("product_view_pixels")),
        "has_product_pixels": bool(pixels.get("scene_pixels") or pixels.get("product_view_pixels")),
        "visual_role_guess": str(visual.get("role_guess") or "unknown"),
        "visual_confidence": float(visual.get("confidence") or 0.0),
    }
def _deterministic_size_evidence(evidence: dict[str, Any]) -> bool:
    measurements = _independent_measurements(evidence.get("measurements") or [])
    if len(measurements) < 2:
        return False
    text = " ".join(evidence.get("trusted_text") or [])
    line_count = sum(1 for line in evidence.get("trusted_text") or [] if extract_measurements(line))
    directions = {word.lower() for word in _DIRECTION_WORD.findall(text)}
    return line_count >= 2 or len(directions) >= 2 or bool(_MULTI_AXIS.search(text)) or len(measurements) >= 3
def _size_strength(row: dict[str, Any]) -> tuple[int, int, int, int]:
    signals = row["signals"]
    return (
        int(signals["has_visual_dimension_layout"]),
        int(signals["measurement_count"]),
        int(signals["measurement_line_count"]),
        -int(row["source_index"]),
    )
def _measurement_rows(values: list[dict[str, Any]], child: dict[str, Any]) -> list[dict[str, Any]]:
    spec_pairs = _spec_measurement_pairs(child)
    rows: list[dict[str, Any]] = []
    for value in _independent_measurements(values):
        pair = str(value.get("canonical_pair") or "")
        rows.append(
            {
                "text": str(value.get("text") or value.get("raw_text") or ""),
                "raw_text": str(value.get("raw_text") or value.get("text") or ""),
                "canonical_pair": pair,
                "source_label": str(value.get("source_label") or value.get("raw_text") or ""),
                "source_occurrence": str(value.get("source_occurrence") or ""),
                "axis_hint": str(value.get("axis_hint") or ""),
                "confidence": "confirmed" if pair and pair in spec_pairs else "source_visible",
            }
        )
    return rows
def _independent_measurements(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        pair = str(value.get("canonical_pair") or "").strip().lower()
        label = normalize_text(value.get("source_label") or value.get("raw_text") or value.get("text") or "").lower()
        key = (pair, label, str(value.get("axis_hint") or ""), str(value.get("source_occurrence") or ""))
        if (pair or label) and key not in seen:
            rows.append(dict(value))
            seen.add(key)
    return rows
def _authored_claims(lines: list[str], *, visual: dict[str, Any] | None = None, product_text: str = "") -> list[dict[str, Any]]:
    visual = visual or {}
    authored = (
        visual.get("role_guess") == "func" and visual.get("has_callouts_or_panels")
        and float(visual.get("confidence") or 0) >= 0.8
    )
    observed = {normalize_text(value).casefold() for value in visual.get("evidence") or [] if isinstance(value, str)} if authored else set()
    candidates = list(lines)
    ocr_text = " ".join(normalize_text(line).casefold() for line in lines)
    for phrase in visual.get("evidence") or [] if authored else []:
        if isinstance(phrase, str) and normalize_text(phrase).casefold() in ocr_text:
            candidates.append(phrase)
    rows: list[dict[str, Any]] = []
    product_words = " " + " ".join(re.findall(r"[a-z0-9]+", product_text.casefold())) + " "
    for line in candidates:
        text = _claim_concept(line)
        words = re.findall(r"[a-z0-9]+", text.casefold())
        corroborated = len(words) >= 2 and (" " + " ".join(words) + " ") in product_words
        if not text or not (_AUTHORED_FUNC_WORD.search(text) or normalize_text(line).casefold() in observed or corroborated):
            continue
        if text.casefold() not in {row["text"].casefold() for row in rows}:
            rows.append({"text": text, "type": "visible_function_concept", "confidence": "source_visible"})
    return rows


def _claim_concept(value: Any) -> str:
    text = re.sub(
        r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)",
        " ",
        normalize_text(value),
    )
    if not text or has_bad_encoding(text):
        return ""
    # This is source evidence, not buyer-facing render copy. Long, trustworthy
    # authored sentences stay bound to the source; the later FuncStory contract
    # alone owns the 2-6 word renderable rewrite.
    return text.rstrip(" ,;:")


def _spec_measurement_pairs(child: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    for key in ("specs", "product_specific"):
        source = child.get(key) if isinstance(child.get(key), dict) else {}
        values.extend(source.values())
    pairs: set[str] = set()
    for value in values:
        for item in extract_measurements(_plain_text(value)):
            pair = str(item.get("canonical_pair") or "")
            if pair:
                pairs.add(pair)
    return pairs
def _evidence_flags(signals: dict[str, Any]) -> dict[str, bool]:
    return {
        "rich_dimension_layout": bool(signals.get("has_rich_dimension_layout")),
        "visual_dimension_layout": bool(signals.get("has_visual_dimension_layout")),
        "callout_layout": bool(signals.get("has_callout_layout")),
        "authored_function_text": bool(signals.get("has_authored_function_text")),
        "scene_background": bool(signals.get("has_scene_pixels")),
        "alternate_product_view": bool(signals.get("has_alternate_product_view")),
        "readable_text": bool(signals.get("trusted_text_count")),
        "ocr_available": bool(signals.get("ocr_available")),
    }
def _classification_reason(role: str, signals: dict[str, Any], *, additional_size: bool) -> str:
    if role == "main":
        return "source_00 is main by fixed policy"
    reasons: list[str] = []
    if role == "size":
        reasons.append("won the child-level size authority ranking")
    if signals.get("has_textual_dimension_layout"):
        reasons.append("multiple independent measurements with authored dimension layout")
    if signals.get("has_visual_dimension_layout"):
        reasons.append("visual recovery found measurement lines and multiple numbers")
    if signals.get("has_callout_layout"):
        reasons.append("callout or panel layout indicates authored functional information")
    if signals.get("has_authored_function_text"):
        reasons.append("source-visible functional text indicates func usage")
    elif signals.get("has_authored_information"):
        reasons.append("source-visible text or annotated detail indicates func usage")
    if signals.get("has_scene_pixels") and not signals.get("has_authored_information"):
        reasons.append("environmental image without authored information indicates scene usage")
    if signals.get("has_alternate_product_view") and not signals.get("has_authored_information"):
        reasons.append("non-primary product view is preserved as scene usage")
    if additional_size:
        reasons.append("not the strongest size source; fully reclassified from its non-size evidence")
    if role == "review_required":
        reasons.append("available evidence cannot determine scene versus func without guessing")
    return f"final={role}; " + "; ".join(reasons or ["deterministic source-purpose rule"])
def _shopping_intent(role: str, claims: list[dict[str, Any]], measurements: list[dict[str, Any]]) -> str:
    if role == "main":
        return "quickly identify the exact product"
    if role == "scene":
        return "show the product in a realistic use context or alternate product state"
    if role == "size":
        return "verify source-visible product dimensions and measured fit"
    if role == "func":
        visible = "; ".join(str(row.get("text") or "") for row in claims[:3])
        return f"understand source-visible product functions: {visible}" if visible else "understand the visible product function"
    if measurements:
        return "review an unresolved source containing measurement evidence"
    return "review unresolved source purpose"
def _warnings(prepared: dict[str, Any], role: str, *, additional_size: bool) -> list[str]:
    warnings: list[str] = []
    ocr = prepared["ocr_evidence"]
    visual = prepared["visual_evidence"]
    if ocr.get("retryable"):
        warnings.append("ocr_retryable")
    if ocr.get("error") and prepared["source_index"] != 0:
        warnings.append("ocr_unavailable")
    if str(visual.get("status") or "") in {"failed", "unavailable"}:
        warnings.append("visual_recovery_retryable")
    if role == "review_required":
        warnings.append("source_review_required")
    if additional_size:
        warnings.append("additional_dimension_infographic_reclassified")
    return warnings
def _semantic_revision(row: dict[str, Any]) -> str:
    keys = ("category_id", "child", "source_index", "source_path", "source_sha256", "status", "role",
            "classification_reason", "evidence_flags", "signals", "trusted_text", "claims", "measurements",
            "shopping_intent", "error")
    payload = {key: row.get(key) for key in keys}
    payload.update(schema=FINAL_SOURCE_INTENT_SCHEMA_VERSION, policy=FINAL_SOURCE_INTENT_POLICY_VERSION,
                   visual_evidence=_visual_semantics(row.get("visual_evidence")))
    return input_revision_id(payload)
def _visual_semantics(value: Any) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    keys = ("status", "role_guess", "has_dimension_lines", "has_callouts_or_panels",
            "visible_numbers_or_units", "layout_summary", "confidence", "evidence", "error", "reason")
    return {key: row.get(key) for key in keys if key in row}
def _failure_row(plugin: ProductPlugin, download: dict[str, Any], exc: Exception) -> dict[str, Any]:
    source_index = _source_index(download)
    row = {
        "schema_version": FINAL_SOURCE_INTENT_SCHEMA_VERSION,
        "policy_version": FINAL_SOURCE_INTENT_POLICY_VERSION,
        "category_id": plugin.category_id,
        "child": str(download.get("child") or ""),
        "source_index": source_index,
        "source_path": str(download.get("raw_path") or ""),
        "source_sha256": str(download.get("source_sha256") or ""),
        "status": "failed",
        "role": "failed",
        "classification_reason": "classification failed before a final source intent could be formed",
        "evidence_flags": {},
        "signals": {},
        "ocr_evidence": {},
        "pixel_evidence": {},
        "visual_evidence": {},
        "trusted_text": [],
        "claims": [],
        "measurements": [],
        "shopping_intent": "",
        "warnings": [],
        "logical_task_id": logical_task_id(
            "classify", child=str(download.get("child") or ""), source_id=str(source_index)
        ),
        "error": f"{type(exc).__name__}: {exc}",
    }
    row["input_revision_id"] = _semantic_revision(row)
    return row
def _stage_failure(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": {"logical_task_id": row["logical_task_id"], "input_revision_id": row["input_revision_id"],
                 "child": row["child"], "source_index": str(row.get("source_index") or "")},
        "failure_owner": "classify",
        "task_status": "blocked",
        "error": row.get("error") or row.get("classification_reason") or "final source intent failed",
    }
def _validate_row(row: Any) -> None:
    if not isinstance(row, dict) or row.get("schema_version") != FINAL_SOURCE_INTENT_SCHEMA_VERSION:
        raise FinalSourceIntentError("Invalid FinalSourceIntentV1 row")
    expected = {"schema_version", "policy_version", "category_id", "child", "source_index", "source_path", "source_sha256", "status", "role", "classification_reason", "evidence_flags", "signals", "ocr_evidence", "pixel_evidence", "visual_evidence", "trusted_text", "claims", "measurements", "shopping_intent", "warnings", "logical_task_id", "input_revision_id"}
    if row.get("status") == "failed":
        expected.add("error")
    if set(row) != expected:
        raise FinalSourceIntentError(f"FinalSourceIntentV1 has unknown or missing fields: {sorted(set(row) ^ expected)}")
    required = (
        "child",
        "source_index",
        "source_path",
        "source_sha256",
        "status",
        "role",
        "logical_task_id",
        "input_revision_id",
    )
    missing = [
        key
        for key in required
        if row.get(key) is None or (not isinstance(row.get(key), int) and not str(row.get(key) or "").strip())
    ]
    if missing:
        raise FinalSourceIntentError(f"Invalid FinalSourceIntentV1 row: missing={missing}")
    if row.get("status") not in {"success", "failed"}:
        raise FinalSourceIntentError("Invalid FinalSourceIntentV1 status")
    roles = {"main", "scene", "func", "size", "review_required"} if row.get("status") == "success" else {"failed"}
    if row.get("role") not in roles:
        raise FinalSourceIntentError("Invalid FinalSourceIntentV1 role")
    for key in ("evidence_flags", "signals", "ocr_evidence", "pixel_evidence", "visual_evidence"):
        if not isinstance(row.get(key), dict):
            raise FinalSourceIntentError(f"Invalid FinalSourceIntentV1 {key}")
    for key in ("trusted_text", "claims", "measurements", "warnings"):
        if not isinstance(row.get(key), list):
            raise FinalSourceIntentError(f"Invalid FinalSourceIntentV1 {key}")
    if row.get("role") == "func":
        source_key = f"{row.get('child')}/{row.get('source_index')}"
        ids: set[str] = set()
        for claim in row["claims"]:
            if not isinstance(claim, dict) or set(claim) != {"evidence_id", "source_sha256", "text", "type", "confidence"}:
                raise FinalSourceIntentError(f"Invalid FinalSourceIntentV1 func evidence: {source_key}")
            if claim["source_sha256"] != row["source_sha256"] or not claim["evidence_id"]:
                raise FinalSourceIntentError(f"FinalSourceIntentV1 func evidence is not source-bound: {source_key}")
            ids.add(str(claim["evidence_id"]))
        if row["claims"] and len(ids) != len(row["claims"]):
            raise FinalSourceIntentError(f"FinalSourceIntentV1 func evidence IDs are missing or duplicated: {source_key}")
def _trusted_text_lines(ocr: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    lines = ocr.get("lines") or []
    for line in lines:
        if not isinstance(line, dict) or float(line.get("confidence") or 0) < 0.68:
            continue
        text = _clean_line(line.get("text"))
        if text and not _NOISE_TEXT.match(text) and text not in rows:
            rows.append(text)
    return rows


def _has_untrusted_raw_text(ocr: dict[str, Any], trusted_text: list[str]) -> bool:
    raw_text = _clean_line(ocr.get("raw_text"))
    lines = ocr.get("lines") or []
    for line in lines:
        if not isinstance(line, dict):
            continue
        text = _clean_line(line.get("text"))
        if text and float(line.get("confidence") or 0) < 0.68:
            return True
    if not raw_text:
        return False
    if not trusted_text:
        return True
    raw_tokens = set(re.findall(r"[a-z0-9]+", normalize_text(raw_text).casefold()))
    trusted_tokens = set(re.findall(r"[a-z0-9]+", normalize_text(" ".join(trusted_text)).casefold()))
    return bool(raw_tokens - trusted_tokens)
def _pixel_evidence(path: Path) -> dict[str, Any]:
    try:
        evidence = inspect_image_pixel_evidence(path)
        product_view = bool(evidence["white_background"])
        return {
            "scene_pixels": not product_view,
            "product_view_pixels": product_view,
            "image_width": evidence["width"],
            "image_height": evidence["height"],
            "image_aspect_ratio": evidence["aspect_ratio"],
            "white_border_ratio": evidence["white_border_ratio"],
        }
    except Exception as exc:
        return {"scene_pixels": False, "product_view_pixels": False, "error": f"{type(exc).__name__}: {exc}"}
def _empty_evidence(error: str) -> dict[str, Any]:
    return {
        "ocr_evidence": {"available": False, "error": error, "raw_text": "", "lines": [], "retryable": True},
        "trusted_text": [],
        "measurements": [],
        "claims": [],
        "text": "",
        "pixel_evidence": {"scene_pixels": False, "product_view_pixels": False, "error": error},
        "visual_evidence": {"status": "failed", "error": error},
    }
def _observation_clients() -> list[dict[str, str]]:
    try:
        clients = clients_for_scope("visual_planning")
    except ModelRouterError:
        return []
    capable: list[dict[str, str]] = []
    for client in clients:
        try:
            capabilities = {str(value) for value in json.loads(client.get("capabilities") or "[]")}
        except (TypeError, json.JSONDecodeError):
            capabilities = set()
        if "source_observation" in capabilities:
            capable.append(client)
    return capable
def _visual_recovery_prompt() -> str:
    return (
        "Return JSON only. Decide image purpose from visible pixels, not listing text or outside facts. "
        "Schema: {\"role_guess\":\"scene|func|size|unknown\",\"has_dimension_lines\":false,"
        "\"has_callouts_or_panels\":false,\"visible_numbers_or_units\":[\"\"],\"layout_summary\":\"\","
        "\"confidence\":0.0,\"evidence\":[\"\"]}. Size requires multiple visible measurements plus lines, arrows, "
        "endpoints, or a clear measurement layout. Func uses authored callouts, panels, detail crops, or functional text. "
        "Scene is an environment or alternate product view without authored information. For func, evidence must quote complete "
        "authored product callouts verbatim, excluding text printed on loose props. Do not infer product facts or claims."
    )
def _visual_response_valid(text: str) -> bool:
    value = _parse_json_object(text)
    return str(value.get("role_guess") or "") in {"scene", "func", "size", "unknown"} and isinstance(value.get("evidence"), list)
def _parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(raw[start : end + 1])
    if not isinstance(value, dict):
        raise FinalSourceIntentError("Visual recovery response is not a JSON object")
    return value
def _normalize_visual_evidence(value: dict[str, Any]) -> dict[str, Any]:
    role = str(value.get("role_guess") or "unknown").strip().lower()
    if role not in {"scene", "func", "size", "unknown"}:
        role = "unknown"
    numbers = _unique_text(value.get("visible_numbers_or_units"), limit=20)
    try:
        confidence = max(0.0, min(1.0, float(value.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "role_guess": role,
        "has_dimension_lines": bool(value.get("has_dimension_lines")),
        "has_callouts_or_panels": bool(value.get("has_callouts_or_panels")),
        "visible_numbers_or_units": numbers,
        "visible_number_count": len(numbers),
        "layout_summary": _compact_text(value.get("layout_summary"), 300),
        "confidence": round(confidence, 3),
        "evidence": _unique_text(value.get("evidence"), limit=8),
    }
def _unique_text(value: Any, *, limit: int) -> list[str]:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, (list, tuple)):
        return []
    rows: list[str] = []
    for item in values:
        text = _compact_text(item, 300)
        if text and text not in rows:
            rows.append(text)
    return rows[:limit]
def _relative_source_path(job: Path, value: Any) -> Path:
    if not str(value or "").strip():
        raise FinalSourceIntentError("Downloaded source path is empty")
    source = _job_path(job, value)
    assert source is not None
    return source.relative_to(job.resolve())
def _job_path(job: Path, value: Any) -> Path | None:
    if not str(value or "").strip():
        return None
    raw = Path(str(value))
    if raw.is_absolute() or ".." in raw.parts:
        raise FinalSourceIntentError("Downloaded source path must be job-relative")
    try:
        return resolve_job_owned_path(job, job.resolve() / raw)
    except ValueError as exc:
        raise FinalSourceIntentError("Downloaded source path escapes the job") from exc
def _source_index(row: dict[str, Any]) -> int:
    try:
        return int(row.get("index", row.get("source_index")))
    except (TypeError, ValueError) as exc:
        raise FinalSourceIntentError(f"Invalid source index: {row.get('index', row.get('source_index'))}") from exc
def _plain_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_plain_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_plain_text(item) for item in value)
    return str(value or "")
def _clean_line(value: Any) -> str:
    text = clean_evidence_text(value).strip(" ,;:")
    return "" if has_bad_encoding(text) else text
def _compact_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]
