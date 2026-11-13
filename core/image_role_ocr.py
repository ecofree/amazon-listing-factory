from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from .io import file_sha256, write_json
from .text_evidence import normalize_text


ROLE_OCR_EVIDENCE_CACHE_VERSION = "role-ocr-evidence-cache-v10-completeness"
OCR_CONCLUSIVE_CONFIDENCE = 0.8


def cached_ocr_evidence_for_image(image_path: Path, *, cache_root: Path) -> dict[str, Any] | None:
    from .ocr_scanner import ocr_request_fingerprint

    fingerprint = ocr_request_fingerprint(image_path)
    cache_path = _ocr_evidence_cache_path(cache_root, image_path, fingerprint)
    return _read_ocr_evidence_cache(cache_path, image_path=image_path, fingerprint=fingerprint)


def ocr_evidence_for_image(
    image_path: Path, *, cache_root: Path | None = None, deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    from .ocr_scanner import ocr_request_fingerprint

    fingerprint = ocr_request_fingerprint(image_path)
    cache_path = _ocr_evidence_cache_path(cache_root, image_path, fingerprint)
    cached = _read_ocr_evidence_cache(cache_path, image_path=image_path, fingerprint=fingerprint)
    if cached is not None and not cached.get("retryable"):
        return cached
    attempts = int((cached or {}).get("attempts") or 0) + 1
    try:
        from .ocr_scanner import scan_image

        ocr = scan_image(image_path, deadline_monotonic=deadline_monotonic,
                         receipt_root=cache_root / 'requests' if cache_root is not None else None)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        evidence = {"available": False, "error": error, "raw_text": "", "retryable": _ocr_error_retryable(error),
                    'completeness': 'unavailable', 'completeness_reasons': ['scan_failed']}
    else:
        error = str(getattr(ocr, "error", "") or "")
        truncation = list(getattr(ocr, 'summary_truncation', []) or [])
        evidence = {
            "available": bool(getattr(ocr, 'text_blocks', []) or getattr(ocr, 'raw_text', '')) or
                         (getattr(ocr, 'completeness', 'unknown') == 'complete' and not error),
            "error": error,
            "raw_text": clean_source_text_evidence(brief_value(getattr(ocr, "raw_text", ""))),
            "lines": _ocr_lines(getattr(ocr, "text_blocks", []), diagnostics=truncation),
            "retryable": _ocr_error_retryable(error),
            'completeness': getattr(ocr, 'completeness', 'unknown'),
            'completeness_source': getattr(ocr, 'completeness_source', ''),
            'completeness_reasons': list(getattr(ocr, 'completeness_reasons', []) or []),
            'summary_truncation': truncation,
        }
    evidence["attempts"] = attempts
    evidence["retryable"] = bool(evidence.get("retryable"))
    _write_ocr_evidence_cache(cache_path, image_path=image_path, fingerprint=fingerprint, evidence=evidence)
    return evidence


def _ocr_evidence_cache_path(
    cache_root: Path | None,
    image_path: Path,
    fingerprint: str,
) -> Path | None:
    if cache_root is None:
        return None
    return cache_root / file_sha256(image_path)[:24] / f"{fingerprint}.json"


def _read_ocr_evidence_cache(
    cache_path: Path | None,
    *,
    image_path: Path,
    fingerprint: str,
) -> dict[str, Any] | None:
    if cache_path is None or not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("cache_version") != ROLE_OCR_EVIDENCE_CACHE_VERSION:
        return None
    if data.get("fingerprint") != fingerprint or data.get("image_sha256") != file_sha256(image_path):
        return None
    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        return None
    canonical = _canonical_ocr_evidence(evidence)
    if canonical.get("error"):
        from .ocr_scanner import ocr_credential_revision

        if data.get("credential_revision") != ocr_credential_revision():
            return None
    return canonical


def _write_ocr_evidence_cache(
    cache_path: Path | None,
    *,
    image_path: Path,
    fingerprint: str,
    evidence: dict[str, Any],
) -> None:
    if cache_path is None:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    from .ocr_scanner import ocr_credential_revision

    write_json(
        cache_path,
        {
            "cache_version": ROLE_OCR_EVIDENCE_CACHE_VERSION,
            "fingerprint": fingerprint,
            "image_sha256": file_sha256(image_path),
            "credential_revision": ocr_credential_revision(),
            "evidence": _canonical_ocr_evidence(evidence),
        },
    )


def _canonical_ocr_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    error = str(evidence.get("error") or "").strip()
    attempts = max(0, int(evidence.get("attempts") or 0))
    truncation = list(evidence.get('summary_truncation') or [])
    raw_text = clean_source_text_evidence(str(evidence.get('raw_text') or ''))
    if len(raw_text) > 1200:
        truncation.append('raw_text_1200')
    lines = _canonical_ocr_lines(evidence.get('lines'), diagnostics=truncation)
    completeness = str(evidence.get('completeness') or 'unknown')
    if completeness not in {'complete', 'partial', 'unknown', 'unavailable'}:
        completeness = 'unknown'
    return {
        "available": bool(evidence.get("available")) and (bool(raw_text or lines) or completeness != 'unavailable'),
        "error": error,
        "raw_text": raw_text[:1200],
        "lines": lines,
        'completeness': completeness,
        'completeness_source': str(evidence.get('completeness_source') or ''),
        'completeness_reasons': list(dict.fromkeys(str(reason) for reason in evidence.get('completeness_reasons') or [])),
        'summary_truncation': list(dict.fromkeys(truncation)),
        "retryable": bool(error) and (bool(evidence.get("retryable")) or _ocr_error_retryable(error)),
        "attempts": attempts,
    }


def _ocr_error_retryable(error: str) -> bool:
    text = str(error or "").lower()
    return any(token in text for token in ("timeout", "timed out", "connection", "temporar", "429", " 500", " 502", " 503", " 504"))


def _ocr_lines(value: Any, *, diagnostics: list[str] | None = None) -> list[dict[str, Any]]:
    return _canonical_ocr_lines(
        [
            {
                "text": getattr(item, "text", ""),
                "confidence": getattr(item, "confidence", 0.0),
                "box": getattr(item, "bbox", []),
            }
            for item in value if getattr(item, "text", "")
        ], diagnostics=diagnostics,
    )


def _canonical_ocr_lines(value: Any, *, diagnostics: list[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        text = clean_source_text_evidence(str(raw.get("text") or ""))
        box = raw.get("box")
        if not text or not isinstance(box, list):
            continue
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        rows.append({"text": text, "confidence": confidence, "box": box})
    if len(rows) > 32 and diagnostics is not None:
        diagnostics.append('lines_32')
    return rows[:32]


def clean_source_text_evidence(value: str) -> str:
    text = normalize_text(html.unescape(str(value or "")))
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\b(?:imgs?/)?img_in_[A-Za-z0-9_./-]+\.(?:jpe?g|png|webp)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:src|alt|width|height|style|text-align|center|image|jpg|jpeg|png|webp)\b", " ", text, flags=re.I)
    text = re.sub(r"#{1,6}\s*", " ", text)
    text = re.sub(r"[_/\\|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;:-")
    if not re.search(r"[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text):
        return ""
    return text


def brief_value(value: Any) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()[:1200]
    if isinstance(value, list):
        parts = [brief_value(item) for item in value]
        return re.sub(r"\s+", " ", "; ".join(part for part in parts if part)).strip()[:1200]
    if isinstance(value, dict):
        parts = [f"{key}: {brief_value(item)}" for key, item in value.items()]
        return re.sub(r"\s+", " ", "; ".join(parts)).strip()[:1200]
    return str(value).strip()[:1200]
