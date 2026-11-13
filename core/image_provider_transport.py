from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
import uuid
from http.client import IncompleteRead
from dataclasses import dataclass
from typing import Any

from . import api_registry
from .image_provider_common import (
    ImageGenerationError,
    ProviderConfigurationError,
    ProviderTransportError,
    image_url_download_attempts,
    image_url_download_retry_delay,
    is_transient_imagegen_error,
    provider_timeout_seconds,
    assert_imagegen_prompt_contract,
)
from .url_safety import request_public_url
from .image_provider_common import CandidateCommitError, ImageOutputRejected
from .imagegen_artifacts import (IMAGE_OUTPUT_MAX_BYTES, IMAGE_RESPONSE_MAX_BYTES,
                                IMAGE_OUTPUT_MAX_DIMENSION, IMAGE_OUTPUT_MAX_PIXELS, _is_invalid_image_encoding)


def _bounded_response_bytes(response, maximum=None):
    maximum = IMAGE_RESPONSE_MAX_BYTES if maximum is None else maximum
    declared = response.headers.get('Content-Length') if response.headers else None
    if declared and str(declared).isdigit() and int(declared) > maximum:
        raise ImageOutputRejected(f'Generated response declares {declared} bytes, exceeding limit {maximum}')
    buffered = bytearray()
    while True:
        interrupted = None
        try:
            chunk = response.read(min(65536, maximum - len(buffered) + 1))
        except IncompleteRead as exc:
            chunk, interrupted = exc.partial, exc
        received = len(buffered) + len(chunk)
        if received > maximum:
            rejection = ImageOutputRejected(f'Generated response exceeds byte limit {maximum}; stopped at {received}')
            rejection.partial = bytes(buffered) + chunk[:maximum - len(buffered)]
            raise rejection from interrupted
        buffered.extend(chunk)
        if interrupted is not None:
            raise IncompleteRead(bytes(buffered), interrupted.expected) from interrupted
        if not chunk:
            return bytes(buffered)


def _validate_output_bytes(data):
    if not data or len(data) > IMAGE_OUTPUT_MAX_BYTES:
        raise ImageOutputRejected(f'Generated image exceeds byte limit {IMAGE_OUTPUT_MAX_BYTES} or is empty')
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as image:
            if max(image.size) > IMAGE_OUTPUT_MAX_DIMENSION or image.width * image.height > IMAGE_OUTPUT_MAX_PIXELS:
                raise ImageOutputRejected('Generated image exceeds the output pixel limit')
    except UnidentifiedImageError:
        pass  # Native validation owns decodability; bytes still have a hard bound.
    except Image.DecompressionBombError as exc:
        raise ImageOutputRejected(f'Generated image exceeds safe pixel limits: {exc}') from exc
    except MemoryError as exc:
        raise CandidateCommitError('Image header validation needs local memory recovery; paid bytes retained') from exc
    except (OSError, SyntaxError, ValueError) as exc:
        if isinstance(exc, OSError) and not _is_invalid_image_encoding(exc):
            raise CandidateCommitError('Image header validation needs local system recovery; paid bytes retained') from exc
        raise ImageOutputRejected(f'Generated image header is malformed: {type(exc).__name__}: {exc}') from exc
    return data


IMAGE_DATA_URL_MAX_DIMENSION = 4096
IMAGE_DATA_URL_MAX_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ImageEditRequest:
    prompt: str
    size: str
    background: str
    moderation: str
    quality: str


@dataclass(frozen=True)
class ImageProviderSpec:
    name: str
    display: str
    url: str
    api_type: str
    key_env: str
    model: str = "gpt-image-2"
    api_key: str = ""
    request_size: str = ""
    output_contract: str = ""
    protocol_profile: dict[str, Any] | None = None


def has_registry_image_provider(provider_name: str) -> bool:
    return _image_provider_spec(provider_name) is not None


def _image_provider_spec(provider_name: str) -> ImageProviderSpec | None:
    return _registry_image_provider_specs().get(provider_name)


def _registry_image_provider_specs() -> dict[str, ImageProviderSpec]:
    specs: dict[str, ImageProviderSpec] = {}
    for entry in api_registry.image_provider_entries():
        specs[entry.name] = ImageProviderSpec(
            name=entry.name,
            display=entry.display or entry.name,
            url=entry.url,
            api_type=entry.api_type,
            key_env=entry.key_env,
            model=entry.model or "gpt-image-2",
            api_key=entry.api_key,
            request_size=str(entry.protocol_profile.get("request_size") or ""),
            output_contract=str(entry.protocol_profile.get("output_contract") or ""),
            protocol_profile=dict(entry.protocol_profile),
        )
    return specs


def generate_with_registry_image_provider(
    *, provider_name: str, image_inputs: list[bytes], prompt: str,
    region_map_bytes: bytes | None = None, request_id: str = "", request_audit: dict[str, Any] | None = None,
    request_observer: Any | None = None,
    transport_observer: Any | None = None,
) -> bytes:
    if not image_inputs:
        raise ProviderConfigurationError(provider_name, "image provider requires at least one reference image")
    spec = _image_provider_spec(provider_name)
    count = len(image_inputs) + int(region_map_bytes is not None)
    if count > 1 and not api_registry.image_provider_supports_multiple_references(provider_name, count):
        raise ProviderConfigurationError(provider_name, "Route does not support the required reference set")
    profile = spec.protocol_profile or {} if spec else {}
    originals = image_inputs + ([region_map_bytes] if region_map_bytes is not None else [])
    original_sizes = [_input_size(data) for data in originals]
    originals = [hashlib.sha256(data).hexdigest() for data in originals]
    image_inputs = _prepare_edit_inputs(image_inputs, region_map_bytes)
    if request_audit is not None:
        from urllib.parse import urlsplit
        endpoint = urlsplit(_provider_url(spec) if spec else "")
        request_audit.update({
            "request_id": request_id, "provider": provider_name, "model": spec.model if spec else "",
            "model_identity_verification": "configured_alias_only",
            "endpoint": {"scheme": endpoint.scheme, "host": endpoint.hostname, "port": endpoint.port, "path": endpoint.path},
            "request_size": str(profile.get("request_size") or ""), "quality": str(profile.get("quality") or "low"),
            "output_contract": str(profile.get("output_contract") or ""),
            "region_map_attachment": count if region_map_bytes is not None else None,
            "region_guidance_mode": "opaque_reference" if region_map_bytes is not None else "none",
            'original_sizes': original_sizes, 'sent_sizes': [_input_size(data) for data in image_inputs],
            "inputs": [{"original_sha256": original, "sent_sha256": hashlib.sha256(data).hexdigest(),
                        "sent_bytes": len(data), "transform": "unchanged" if original == hashlib.sha256(data).hexdigest() else "bounded_image_encoding"}
                       for original, data in zip(originals, image_inputs)],
        })
    if spec and spec.api_type == "openai_images_edit":
        return _generate_with_openai_images_edit(
            provider_name=provider_name,
            image_inputs=image_inputs,
            prompt=prompt,
            request_audit=request_audit,
            transport_observer=transport_observer,
            request_observer=request_observer,
        )
    raise ProviderConfigurationError(provider_name, f"Unsupported registry image provider: {provider_name}")


def _generate_with_openai_images_edit(
    *, provider_name: str, image_inputs: list[bytes], prompt: str,
    request_audit: dict[str, Any] | None = None,
    transport_observer: Any | None = None,
    request_observer: Any | None = None,
) -> bytes:
    spec = _image_provider_spec(provider_name)
    if spec is None or spec.api_type != "openai_images_edit":
        raise ProviderConfigurationError(provider_name, f"Unsupported OpenAI images.edit provider: {provider_name}")
    key = _provider_api_key(spec)
    if not key:
        token_hint = f" Set {spec.key_env}." if spec.key_env else ""
        raise ProviderConfigurationError(provider_name, f"Provider '{spec.display}' API key is not configured.{token_hint}")
    edit_request = _canonical_image_edit_request(spec=spec, prompt=prompt)
    model = spec.model
    if not model:
        raise ProviderConfigurationError(provider_name, "image provider requires an explicit registry model")
    body, content_type = _openai_images_edit_multipart_body(
        edit_request=edit_request,
        model=model,
        image_inputs=image_inputs,
    )
    if request_audit is not None:
        request_audit.update(request_body_sha256=hashlib.sha256(body).hexdigest(), request_fields={
            "model": model, "prompt_sha256": hashlib.sha256(edit_request.prompt.encode("utf-8")).hexdigest(),
            **{name: getattr(edit_request, name) for name in ("quality", "background", "moderation", "size")
               if getattr(edit_request, name) and (name != "size" or edit_request.size.strip().lower() not in {"1:1", "square"})}})
    url = _provider_url(spec)
    timeout = provider_timeout_seconds(provider_name)
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": content_type,
            "Accept": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "Mozilla/5.0",
        },
    )
    if not request_audit or not request_audit.get('receipt_path') or not callable(request_observer):
        raise ProviderConfigurationError(provider_name, 'Image submission requires a durable attempt and submission observer')
    from pathlib import Path
    from .io import read_json
    from .image_response import RESPONSE_SCHEMA
    receipt=Path(request_audit['receipt_path'])
    prepared=read_json(receipt)
    if (prepared.get('schema')!=RESPONSE_SCHEMA or prepared.get('binding')!=receipt.parent.name
            or prepared.get('provider')!=provider_name or prepared.get('status')!='prepared'
            or request_audit.get('attempt_id')!=receipt.stem
            or request_audit.get('response_binding')!=prepared.get('binding')):
        raise ProviderConfigurationError(provider_name,'Image request is not bound to a prepared receipt')
    from .batch_ledger import admit_paid_request
    request_audit['admission_id'] = admit_paid_request('image',receipt.stem,receipt_path=receipt)
    request_audit['transport_phase'] = 'submission_call_started'
    request_observer(dict(request_audit))
    submitted=read_json(receipt)
    if submitted.get('status')!='submitted' or not submitted.get('submitted_at'):
        raise ProviderConfigurationError(provider_name,'Submission observer did not persist the POST boundary')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if request_audit is not None:
                request_audit["remote_request_id"] = str(response.headers.get("x-request-id") or "")[:200]
                request_audit['transport_phase'] = 'response_headers_received'
            if transport_observer:
                transport_observer('headers', b'', request_audit or {})
            try:
                raw = _bounded_response_bytes(response)
            except (IncompleteRead, ImageOutputRejected) as exc:
                if request_audit is not None:
                    request_audit.update(transport_phase='response_body_interrupted', response_bytes_received=len(getattr(exc,'partial',b'')))
                if transport_observer and hasattr(exc, 'partial'):
                    transport_observer('partial', exc.partial, request_audit or {})
                raise
            if request_audit is not None:
                request_audit.update(transport_phase='response_body_received', response_bytes_received=len(raw))
            text = raw.decode("utf-8", errors="replace")
            payload = _raise_image_rejection(provider_name, text, 200, request_audit=request_audit, api_key=key)
            if transport_observer:
                transport_observer('body', raw, request_audit or {})
    except urllib.error.HTTPError as exc:
        if request_audit is not None:
            request_audit['remote_request_id'] = str(exc.headers.get('x-request-id') or '')[:200] if exc.headers else ''
            request_audit['http_status'] = exc.code
        if transport_observer:
            transport_observer('headers', b'', request_audit or {})
        try:
            excerpt = exc.read(8192).decode("utf-8", errors="replace")
        except Exception as body_error:
            excerpt = f'Unreadable error body: {type(body_error).__name__}'
        _raise_image_rejection(provider_name, excerpt, exc.code, request_audit=request_audit, api_key=key)
        raise ImageGenerationError(f"{provider_name} HTTP {exc.code}: {_image_error_text(excerpt, key)}") from exc
    except (ProviderConfigurationError, ProviderTransportError, CandidateCommitError):
        raise
    except Exception as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise ProviderConfigurationError(provider_name, f'TLS certificate rejected before image submission: {reason}') from exc
        if isinstance(reason, (socket.gaierror, ConnectionRefusedError)):
            raise ProviderTransportError(provider_name, f'Connection failed before image submission: {reason}') from exc
        raise ProviderTransportError(provider_name, f"Remote image result unknown after {type(exc).__name__}: {exc}", ambiguous=True) from exc
    finally:
        if transport_observer and request_audit and request_audit.get('provider_error'):
            transport_observer('headers', b'', request_audit)
    if request_audit is not None:
        if isinstance(payload, dict):
            request_audit["response_metadata"] = {key: value for key in ("model", "id", "created")
                if isinstance((value := payload.get(key)), (str, int, float)) and len(str(value)) <= 200}
            if request_audit["response_metadata"].get("model"):
                request_audit["model_identity_verification"] = "gateway_reported_not_independently_verified"
    return _decode_image_response(text)


def _image_error_text(value: Any, api_key: str = '', limit: int = 500) -> str:
    text = str(value) if isinstance(value, (str, int, float)) else ''
    if api_key:
        text = text.replace(api_key, '[redacted]')
    text = re.sub(r'(?i)(bearer\s+|(?:api[_-]?key|token|authorization)[\s\"\x27:=]+)\S+', r'\1[redacted]', text)
    text = re.sub(r'(?:data:[^\s,]*;base64,\S+|[A-Za-z0-9+/=]{128,})', '[redacted payload]', text)
    return text[:limit]


def _raise_image_rejection(provider_name: str, text: str, status: int, *, request_audit: dict[str, Any] | None = None, api_key: str = '') -> Any:
    """A complete rejection is not a recoverable paid-image body, even on HTTP 200."""
    try:
        payload = json.loads(text)
        error = payload.get('error') if isinstance(payload, dict) else None
        has_result = isinstance(payload, dict) and any(payload.get(key) for key in (
            'data', 'images', 'output', 'result', 'choices', 'content', 'image', 'url', 'b64_json'))
        code = (error.get('code') or error.get('type')) if isinstance(error, dict) and not has_result else ''
    except ValueError:
        payload, error, code = None, None, ''
    code = code if isinstance(code, str) else ''
    if request_audit is not None and (error or status >= 400):
        message = error.get('message') if isinstance(error, dict) else error if isinstance(error, str) else ''
        message = message or (payload.get('message') if isinstance(payload, dict) else '') or (text if payload is None else '')
        request_audit['provider_error'] = {
            'http_status': status, 'code': _image_error_text(code, api_key, 100),
            'message': _image_error_text(message, api_key),
            'request_id': _image_error_text((error.get('request_id') if isinstance(error, dict) else '')
                or (payload.get('request_id') if isinstance(payload, dict) else '')
                or request_audit.get('remote_request_id'), api_key, 200),
        }
    if code in {'model_not_found', 'invalid_api_key', 'insufficient_quota', 'permission_denied'}:
        raise ProviderConfigurationError(provider_name, f'Image request rejected: {code}')
    if status == 429 or code in {'rate_limit_exceeded', 'no_available_channel', 'image_account_selection_timeout'}:
        raise ProviderTransportError(provider_name, f'Image request rejected before generation: HTTP {status}: {code}')
    if status == 408 or status >= 500:
        raise ProviderTransportError(provider_name, f'Remote image result unknown after HTTP {status}: {_image_error_text(text, api_key)}', ambiguous=True)
    return payload


def _openai_images_edit_multipart_body(
    *,
    edit_request: ImageEditRequest,
    model: str,
    image_inputs: list[bytes],
) -> tuple[bytes, str]:
    boundary = f"amazonfactory-{uuid.uuid4().hex}"
    bounded_images = image_inputs  # Prepared references, no second bounding pass.
    chunks: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")

    def add_file(name: str, filename: str, mime: str, data: bytes) -> None:
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode("ascii")
        )
        chunks.append(data)
        chunks.append(b"\r\n")

    add_field("model", model or "gpt-image-2")
    add_field("prompt", edit_request.prompt)
    if edit_request.quality:
        add_field("quality", edit_request.quality)
    if edit_request.background:
        add_field("background", edit_request.background)
    if edit_request.moderation:
        add_field("moderation", edit_request.moderation)
    # OpenAI-compatible edit endpoints can choose their native square pixel
    # size. The production contract is an aspect ratio, not a hard-coded
    # provider pixel dimension.
    if str(edit_request.size or "").strip().lower() not in {"", "1:1", "square"}:
        add_field("size", edit_request.size)
    image_field = "image[]" if len(bounded_images) > 1 else "image"
    for index, bounded_image in enumerate(bounded_images):
        image_mime = _image_mime_from_bytes(bounded_image)
        add_file(image_field, _image_filename_from_mime(f"source-{index}", image_mime), image_mime, bounded_image)
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _input_size(data):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        return list(image.size)


def _prepare_edit_inputs(image_inputs, region_map_bytes):
    from PIL import Image
    if region_map_bytes is not None:
        with Image.open(io.BytesIO(region_map_bytes)) as region:
            if region.mode != 'RGB' or 'transparency' in region.info or list(region.size) != _input_size(image_inputs[0]):
                raise ImageGenerationError('Region map must be opaque RGB with exact original source dimensions')
    bounded = [_bounded_image_data_url_bytes(data) for data in image_inputs]
    if region_map_bytes is not None:
        with Image.open(io.BytesIO(region_map_bytes)) as region:
            size = tuple(_input_size(bounded[0]))
            if region.size != size:
                out = io.BytesIO()
                region.resize(size, resample=Image.Resampling.NEAREST).save(out, format='PNG')
                region_map_bytes = out.getvalue()
        bounded.append(region_map_bytes)
    return bounded


def _image_filename_from_mime(stem: str, mime: str) -> str:
    extension = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(mime, "png")
    return f"{stem}.{extension}"


def _provider_api_key(spec: ImageProviderSpec) -> str:
    if spec.api_key:
        return spec.api_key
    for key_env in [spec.key_env]:
        value = os.environ.get(key_env, "").strip()
        if value:
            return value
    return ""


def _provider_url(spec: ImageProviderSpec) -> str:
    return spec.url


def _canonical_image_edit_request(
    *, spec: ImageProviderSpec, prompt: str
) -> ImageEditRequest:
    if spec.output_contract != "square" or not spec.request_size:
        raise ProviderConfigurationError(spec.name, "image provider requires square output_contract and request_size")
    return ImageEditRequest(
        prompt=str(prompt or ""),
        size=spec.request_size,
        background=str((spec.protocol_profile or {}).get("background") or "auto"),
        moderation="",
        quality=str((spec.protocol_profile or {}).get("quality") or "low"),
    )


def provider_prompt_max_chars(provider_name: str) -> int:
    entry = next(
        (item for item in api_registry.image_provider_entries() if item.name == str(provider_name or "").strip()),
        None,
    )
    raw = entry.raw.get("prompt_max_chars") if entry is not None else None
    try:
        limit = int(raw)
    except (TypeError, ValueError) as exc:
        raise ProviderConfigurationError(provider_name, "image provider requires prompt_max_chars") from exc
    if limit < 1000:
        raise ProviderConfigurationError(provider_name, "image provider prompt_max_chars must be at least 1000")
    return limit


def eligible_imagegen_providers(prompt: str, providers: list[str]) -> list[str]:
    if not providers:
        raise ImageGenerationError("Image generation prompt preflight requires at least one provider")
    # Prompt validity is task-scoped; a malformed task must stop before any
    # provider call.  Provider-specific prompt limits are configuration data,
    # however, so one broken registry entry must not veto otherwise usable
    # providers in the same lane.
    assert_imagegen_prompt_contract(prompt, str(providers[0]))
    eligible: list[str] = []
    rejected: list[str] = []
    for name in providers:
        try:
            if len(prompt) <= provider_prompt_max_chars(name):
                eligible.append(name)
            else:
                rejected.append(f"{name} ({provider_prompt_max_chars(name)})")
        except ProviderConfigurationError:
            rejected.append(f"{name} (invalid prompt limit)")
    # Provider capability/configuration is execution environment state, not an
    # immutable ImageTask failure.  Callers need an empty result so they can
    # persist a retryable provider-availability outcome.  Prompt-contract
    # failures still raise above before any provider is considered.
    if not eligible:
        return []
    return eligible


def assert_imagegen_prompt_preflight(prompt: str, providers: list[str]) -> None:
    eligible = eligible_imagegen_providers(prompt, providers)
    if not eligible:
        raise ProviderConfigurationError(
            str(providers[0] if providers else "unknown"),
            "No selected image provider accepts the compiled prompt under its current capability configuration",
        )


def _bounded_image_data_url_bytes(image_bytes: bytes) -> bytes:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
            if len(image_bytes) <= IMAGE_DATA_URL_MAX_BYTES and max(width, height) <= IMAGE_DATA_URL_MAX_DIMENSION:
                return image_bytes
            if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
                rgba = image.convert("RGBA")
                flattened = Image.new("RGB", rgba.size, (255, 255, 255))
                flattened.paste(rgba, mask=rgba.getchannel("A"))
                working = flattened
            else:
                working = image.convert("RGB")
            working.thumbnail((IMAGE_DATA_URL_MAX_DIMENSION, IMAGE_DATA_URL_MAX_DIMENSION), Image.Resampling.LANCZOS)
            quality = 90
            while True:
                out = io.BytesIO()
                working.save(out, format="JPEG", quality=quality, optimize=True)
                bounded = out.getvalue()
                if len(bounded) <= IMAGE_DATA_URL_MAX_BYTES or quality <= 72:
                    return bounded
                quality -= 6
    except Exception:
        if len(image_bytes) <= IMAGE_DATA_URL_MAX_BYTES:
            return image_bytes
        raise ImageGenerationError(
            f"Reference image payload is too large for image generation request: {len(image_bytes)} bytes"
        )


def _image_mime_from_bytes(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _decode_image_response(text: str, *, deadline: float | None = None) -> bytes:
    if len(text) > IMAGE_RESPONSE_MAX_BYTES or len(text.encode('utf-8')) > IMAGE_RESPONSE_MAX_BYTES:
        raise ImageOutputRejected(f'Generated response exceeds envelope limit {IMAGE_RESPONSE_MAX_BYTES}')
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImageGenerationError(f"Image edit provider returned non-JSON response: {text[:300]}") from exc
    candidates: list[Any] = []
    if isinstance(payload, dict):
        for key in ("data", "images", "output", "result", "choices", "message", "content"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(value)
            elif value is not None:
                candidates.append(value)
        candidates.append(payload)
    elif isinstance(payload, list):
        candidates.extend(payload)
    for item in candidates:
        image = _image_bytes_from_response_item(item, deadline=deadline)
        if image:
            return image
    raise ImageGenerationError(f"Image edit provider response did not contain image data: {text[:800]}")


def _image_bytes_from_response_item(item: Any, *, deadline: float | None = None) -> bytes | None:
    if item in (None, ""):
        return None
    if isinstance(item, list):
        for value in item:
            data = _image_bytes_from_response_item(value, deadline=deadline)
            if data:
                return data
        return None
    if isinstance(item, str):
        return _image_bytes_from_string(item, deadline=deadline)
    if isinstance(item, dict):
        for key in ("b64_json", "base64", "image", "image_base64", "data", "content", "message"):
            value = item.get(key)
            if isinstance(value, str):
                data = _image_bytes_from_string(value, deadline=deadline)
                if data:
                    return data
            elif isinstance(value, list):
                data = _image_bytes_from_response_item(value, deadline=deadline)
                if data:
                    return data
            elif isinstance(value, dict):
                data = _image_bytes_from_response_item(value, deadline=deadline)
                if data:
                    return data
        for key in ("url", "image_url", "output_url", "images"):
            value = item.get(key)
            if isinstance(value, str):
                data = _image_bytes_from_string(value, deadline=deadline)
                if data:
                    return data
            elif isinstance(value, list):
                data = _image_bytes_from_response_item(value, deadline=deadline)
                if data:
                    return data
            elif isinstance(value, dict):
                data = _image_bytes_from_response_item(value, deadline=deadline)
                if data:
                    return data
    return None


def _image_bytes_from_string(value: str, *, deadline: float | None = None) -> bytes | None:
    text = value.strip()
    if not text:
        return None
    markdown_url = re.search(r"!\[[^\]]*]\((https?://[^)\s]+)\)", text)
    if markdown_url:
        return _download_image_bytes(markdown_url.group(1), deadline=deadline)
    if text.startswith(("http://", "https://")):
        return _download_image_bytes(text, deadline=deadline)
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    text = re.sub(r'\s+', '', text)
    if len(text) > 4 * ((IMAGE_OUTPUT_MAX_BYTES + 2) // 3):
        raise ImageOutputRejected(f'Generated base64 exceeds decoded byte limit {IMAGE_OUTPUT_MAX_BYTES}')
    try:
        data = base64.b64decode(text, validate=True)
    except (ValueError, base64.binascii.Error):
        return None
    return _validate_output_bytes(data) if data else None


def _download_image_bytes(url: str, *, deadline: float | None = None) -> bytes:
    deadline = min(time.monotonic() + 120, deadline if deadline is not None else float('inf'))
    attempts = image_url_download_attempts()
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CandidateCommitError('Saved image download deadline exhausted; receipt retained')
            response = request_public_url("GET", url, timeout=remaining,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*,*/*"}, stream=True)
            try:
                if response.status_code >= 400:
                    raise urllib.error.HTTPError(url, response.status_code,
                        f"HTTP {response.status_code}", response.headers, None)
                declared = response.headers.get('Content-Length')
                if declared and str(declared).isdigit() and int(declared) > IMAGE_OUTPUT_MAX_BYTES:
                    raise ImageOutputRejected(f'Generated URL image exceeds byte limit {IMAGE_OUTPUT_MAX_BYTES}')
                chunks, count = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    if time.monotonic() >= deadline:
                        raise CandidateCommitError('Saved image stream exceeded local deadline; receipt retained')
                    count += len(chunk)
                    if count > IMAGE_OUTPUT_MAX_BYTES:
                        raise ImageOutputRejected(f'Generated URL image exceeds byte limit {IMAGE_OUTPUT_MAX_BYTES}')
                    chunks.append(chunk)
                data = b''.join(chunks)
            finally:
                response.close()
            if not data:
                raise ImageGenerationError(f"Downloaded generated image is empty: {url}")
            return _validate_output_bytes(data)
        except CandidateCommitError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not is_transient_imagegen_error(exc):
                break
            delay = image_url_download_retry_delay(attempt)
            if time.monotonic() + delay >= deadline:
                raise CandidateCommitError('Saved image retry exceeds local deadline; receipt retained') from exc
            time.sleep(delay)
    raise ImageGenerationError(f"Failed to download generated image after {attempts} attempt(s): {url}: {last_exc}") from last_exc
