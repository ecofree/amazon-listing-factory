from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .text_evidence import has_measurement_text
from .url_safety import request_public_url, assert_response_peer_public


@dataclass(frozen=True)
class OcrBlock:
    text: str
    confidence: float = 0.0
    bbox: list[Any] = field(default_factory=list)
    language: str = ""


@dataclass(frozen=True)
class OcrResult:
    has_text: bool = False
    has_brand_logo: bool = False
    has_cjk_text: bool = False
    has_measurement_text: bool = False
    text_blocks: list[OcrBlock] = field(default_factory=list)
    raw_text: str = ""
    avg_confidence: float = 0.0
    error: str = ""


EMPTY_OCR_RESULT = OcrResult(error="ocr_unavailable")
_CACHE: OrderedDict[str, OcrResult] = OrderedDict()
_CACHE_MAX = 512
_CACHE_LOCK = threading.RLock()

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_LOW_CONFIDENCE_DEFAULT = 0.5
_OCR_REQUEST_VERSION = "ppocr-v7-localized-dedup"
_RESULT_MAX_BYTES = 8 * 1024 * 1024
_MAX_OCR_BLOCKS = 2000
_MAX_OCR_DEPTH = 8


def scan_image(image_path: str | Path) -> OcrResult:
    """Return OCR text evidence for an image.

    Disabled, unconfigured, low-confidence, and failed OCR return explicit
    errors so QA can emit a human-review warning instead of guessing.
    """

    path = Path(image_path)
    if not _ocr_enabled() or not _api_token() or not path.exists():
        return EMPTY_OCR_RESULT
    cache_key = ocr_request_fingerprint(path)
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached is not None:
            _CACHE.move_to_end(cache_key)
            return cached
    try:
        result = _scan_image_uncached(path)
    except Exception as exc:
        result = OcrResult(error=f"{type(exc).__name__}: {exc}")
    if result.error:
        return result
    with _CACHE_LOCK:
        _CACHE[cache_key] = result
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return result


def _scan_image_uncached(path: Path) -> OcrResult:
    headers = {"Authorization": f"Bearer {_api_token()}"}
    optional_payload = json.dumps(_optional_payload(), separators=(",", ":"), sort_keys=True)
    with path.open("rb") as handle:
        response = _request_with_retries(
            lambda: (
                handle.seek(0)
                or requests.post(
                    _api_url(),
                    headers=headers,
                    data={"model": _model(), "optionalPayload": optional_payload},
                    files={"file": (path.name, handle, _content_type(path))},
                    timeout=_submit_timeout(),
                )
            )
        )
    payload = response.json()
    job_id = str((payload.get("data") or {}).get("jobId") or payload.get("jobId") or "").strip()
    if not job_id:
        return _parse_result_payload(payload)
    return _poll_result(job_id, headers)


def _poll_result(job_id: str, headers: dict[str, str]) -> OcrResult:
    deadline = time.time() + _timeout_seconds()
    interval = _poll_interval()
    max_interval = _poll_max_interval()
    while time.time() < deadline:
        remaining = deadline - time.time()
        time.sleep(min(interval, max(0.0, remaining)))
        response = _request_with_retries(
            lambda: request_public_url(
                "GET",
                f"{_api_url().rstrip('/')}/{job_id}",
                headers=headers,
                timeout=_request_timeout(),
            )
        )
        try:
            assert_response_peer_public(response, hostname=urlparse(_api_url()).hostname or "")
            payload = response.json()
        finally:
            response.close()
        data = payload.get("data") if isinstance(payload, dict) else {}
        data = data if isinstance(data, dict) else payload
        state = str(data.get("state") or data.get("status") or "").strip().lower()
        if state in {"done", "completed", "succeeded", "success"}:
            return _parse_result_payload(data)
        if state in {"failed", "error", "canceled", "cancelled"}:
            return OcrResult(error=str(data.get("errorMsg") or data.get("error") or state))
        interval = min(max_interval, interval * 1.5)
    return OcrResult(error="timeout")


def _parse_result_payload(payload: dict[str, Any]) -> OcrResult:
    blocks: list[OcrBlock] = []
    blocks.extend(_extract_blocks(payload))
    result_url = _result_json_url(payload)
    if result_url:
        try:
            response = _request_with_retries(
                lambda: request_public_url("GET", result_url, timeout=_request_timeout())
            )
            try:
                assert_response_peer_public(response, hostname=urlparse(result_url).hostname or "")
                declared_length = int(response.headers.get("Content-Length") or 0)
                if declared_length > _RESULT_MAX_BYTES:
                    raise RuntimeError("OCR result exceeds size limit")
                body = response.content
                if len(body) > _RESULT_MAX_BYTES:
                    raise RuntimeError("OCR result exceeds size limit")
                blocks.extend(_extract_blocks_from_jsonl(body.decode("utf-8", errors="replace")))
            finally:
                response.close()
        except Exception as exc:
            if not blocks:
                return OcrResult(error=f"{type(exc).__name__}: {exc}")
    return _analyze_blocks(blocks)


def _request_with_retries(request_fn):
    attempts = _retry_attempts()
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            response = request_fn()
            response.raise_for_status()
            return response
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
        except requests.HTTPError as exc:
            last_exc = exc
            if not _retryable_http_error(exc):
                raise
        if attempt < attempts - 1:
            time.sleep(_retry_delay_seconds(attempt))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("OCR request failed without an exception")


def _retryable_http_error(exc: requests.HTTPError) -> bool:
    response = getattr(exc, "response", None)
    status = int(getattr(response, "status_code", 0) or 0)
    return status == 429 or status >= 500


def _extract_blocks_from_jsonl(text: str) -> list[OcrBlock]:
    blocks: list[OcrBlock] = []
    for line in text.splitlines():
        if len(blocks) >= _MAX_OCR_BLOCKS:
            break
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        blocks.extend(_extract_blocks(payload, depth=0)[: max(0, _MAX_OCR_BLOCKS - len(blocks))])
    return blocks


def _extract_blocks(payload: Any, *, depth: int = 0) -> list[OcrBlock]:
    if not isinstance(payload, dict):
        return []
    if depth > _MAX_OCR_DEPTH:
        return []
    blocks: list[OcrBlock] = []
    texts = payload.get("rec_texts", payload.get("recTexts"))
    scores = payload.get("rec_scores", payload.get("recScores"))
    polygons = payload.get("rec_polys", payload.get("recPolys"))
    if isinstance(texts, list):
        score_rows = scores if isinstance(scores, list) else []
        polygon_rows = polygons if isinstance(polygons, list) else []
        for index, text in enumerate(texts):
            if not isinstance(text, str) or not text.strip():
                continue
            score = score_rows[index] if index < len(score_rows) else 0.0
            bbox = polygon_rows[index] if index < len(polygon_rows) else []
            blocks.append(_block(text, {"confidence": score, "bbox": bbox}))
    for key in ("text", "rec_text", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            blocks.append(_block(value, payload))
    markdown = payload.get("markdown")
    if isinstance(markdown, dict) and isinstance(markdown.get("text"), str):
        blocks.append(_block(markdown["text"], payload))
    for key in (
        "ocrResults",
        "ocr_results",
        "layoutElements",
        "layoutParsingResults",
        "parsing_res_list",
        "prunedResult",
        "results",
        "pages",
        "items",
        "result",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                blocks.extend(_extract_blocks(item, depth=depth + 1))
        elif isinstance(value, dict):
            blocks.extend(_extract_blocks(value, depth=depth + 1))
        if len(blocks) >= _MAX_OCR_BLOCKS:
            break
    return blocks[:_MAX_OCR_BLOCKS]


def _block(text: str, payload: dict[str, Any]) -> OcrBlock:
    cleaned = _clean_ocr_text(text)
    confidence = payload.get("confidence", payload.get("score", payload.get("rec_score", 0.0)))
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        conf = 0.0
    return OcrBlock(
        text=cleaned,
        confidence=conf,
        bbox=payload.get("bbox") if isinstance(payload.get("bbox"), list) else [],
        language=_language(cleaned),
    )


def _clean_ocr_text(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\b(?:imgs?/)?img_in_[A-Za-z0-9_./-]+\.(?:jpe?g|png|webp)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:src|alt|width|height|style|text-align|center|image|jpg|jpeg|png|webp)\b", " ", text, flags=re.I)
    text = re.sub(r"#{1,6}\s*", " ", text)
    text = re.sub(r"[_/\\|]+", " ", text)
    return re.sub(r"\s+", " ", text).strip(" ,;:-")


def _analyze_blocks(blocks: list[OcrBlock]) -> OcrResult:
    min_conf = _low_confidence()
    cleaned = [
        OcrBlock(
            text=_clean_ocr_text(block.text),
            confidence=block.confidence,
            bbox=block.bbox,
            language=_language(block.text),
        )
        for block in blocks
        if _clean_ocr_text(block.text)
    ]
    filtered = [
        block for block in cleaned if block.confidence >= min_conf
    ]
    if cleaned and not filtered:
        highest = max((float(block.confidence) for block in cleaned), default=0.0)
        return OcrResult(avg_confidence=round(highest, 3), error="ocr_low_confidence")
    localized_text = {
        re.sub(r"\s+", " ", block.text.casefold()).strip()
        for block in filtered if block.bbox
    }
    deduped: list[OcrBlock] = []
    seen: set[tuple[str, tuple[Any, ...]]] = set()
    for block in filtered:
        normalized = re.sub(r"\s+", " ", block.text.lower()).strip()
        if not block.bbox and normalized in localized_text:
            continue
        bbox = _freeze_bbox(block.bbox) if block.bbox else ()
        identity = (normalized, bbox)
        if normalized and identity not in seen:
            deduped.append(block)
            seen.add(identity)
    raw_text = " ".join(block.text for block in deduped).strip()
    if _looks_garbled(raw_text):
        return OcrResult(error="ocr_garbled_text")
    avg = sum(block.confidence for block in deduped) / len(deduped) if deduped else 0.0
    return OcrResult(
        has_text=bool(deduped),
        has_brand_logo=_looks_like_logo(deduped),
        has_cjk_text=bool(_CJK_RE.search(raw_text)),
        has_measurement_text=has_measurement_text(raw_text),
        text_blocks=deduped,
        raw_text=raw_text[:1200],
        avg_confidence=round(avg, 3),
    )


def _freeze_bbox(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_freeze_bbox(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze_bbox(item)) for key, item in value.items()))
    return value


def _looks_garbled(text: str) -> bool:
    value = str(text or "")
    return "\ufffd" in value or any(marker in value for marker in ("锟斤拷", "灏哄", "瀹絴", "楂榺", "娣眧", "闀縷"))


def _looks_like_logo(blocks: list[OcrBlock]) -> bool:
    if len(blocks) != 1:
        return False
    text = blocks[0].text.strip()
    if has_measurement_text(text) or re.search(r"\d", text):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'&-]*", text)
    non_word = re.sub(r"[A-Za-z'&\-\s]", "", text)
    return blocks[0].confidence >= 0.7 and len(text) <= 32 and len(words) <= 4 and not non_word.strip()


def _language(text: str) -> str:
    if _CJK_RE.search(text):
        return "cjk"
    if re.fullmatch(r"[\d\s.,;:\-+/()'\"%]+", text.strip()):
        return "numeric"
    return "en"


def _result_json_url(payload: dict[str, Any]) -> str:
    result_url = payload.get("resultUrl") or payload.get("result_url")
    if isinstance(result_url, dict):
        return str(result_url.get("jsonUrl") or result_url.get("json_url") or result_url.get("url") or "").strip()
    return str(payload.get("jsonUrl") or payload.get("json_url") or "").strip()


def ocr_request_fingerprint(image_path: str | Path) -> str:
    path = Path(image_path)
    source_sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            source_sha.update(chunk)
    material = json.dumps(
        {
            "source_sha256": source_sha.hexdigest(),
            "api_url": _api_url(),
            "model": _model(),
            "optional_payload": _optional_payload(),
            "min_confidence": _low_confidence(),
            "request_version": _OCR_REQUEST_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def ocr_credential_revision() -> str:
    return hashlib.sha256(_api_token().encode("utf-8")).hexdigest()


def _optional_payload() -> dict[str, Any]:
    if _model().lower().startswith("paddleocr-vl"):
        return {
            "useChartRecognition": False,
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useOcrForImageBlock": True,
        }
    return {
        "textRecScoreThresh": 0.0,
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useTextlineOrientation": False,
    }


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


def _ocr_enabled() -> bool:
    return os.environ.get("PADDLEOCR_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def _api_token() -> str:
    return os.environ.get("PADDLEOCR_API_TOKEN", "").strip()


def _api_url() -> str:
    return os.environ.get("PADDLEOCR_API_URL", "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs").strip().rstrip("/")


def _model() -> str:
    return os.environ.get("PADDLEOCR_MODEL", "PP-OCRv5").strip() or "PP-OCRv5"


def _poll_interval() -> float:
    try:
        return max(0.2, min(10.0, float(os.environ.get("PADDLEOCR_POLL_INTERVAL") or "3")))
    except ValueError:
        return 3.0


def _poll_max_interval() -> float:
    try:
        return max(_poll_interval(), min(30.0, float(os.environ.get("PADDLEOCR_POLL_MAX_INTERVAL") or "12")))
    except ValueError:
        return 12.0


def _timeout_seconds() -> float:
    try:
        return max(1.0, min(180.0, float(os.environ.get("PADDLEOCR_TIMEOUT") or "60")))
    except ValueError:
        return 60.0


def _submit_timeout() -> float:
    try:
        return max(2.0, min(60.0, float(os.environ.get("PADDLEOCR_SUBMIT_TIMEOUT") or "30")))
    except ValueError:
        return 30.0


def _request_timeout() -> float:
    try:
        return max(2.0, min(60.0, float(os.environ.get("PADDLEOCR_REQUEST_TIMEOUT") or "15")))
    except ValueError:
        return 15.0


def _retry_attempts() -> int:
    try:
        return max(1, min(2, int(os.environ.get("PADDLEOCR_RETRY_ATTEMPTS") or "2")))
    except ValueError:
        return 2


def _retry_delay_seconds(attempt: int) -> float:
    try:
        base = max(0.0, min(5.0, float(os.environ.get("PADDLEOCR_RETRY_BASE_DELAY") or "0.5")))
    except ValueError:
        base = 0.5
    return base * (2 ** max(0, attempt))


def _low_confidence() -> float:
    return _LOW_CONFIDENCE_DEFAULT
