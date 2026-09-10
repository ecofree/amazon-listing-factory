from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
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
from .url_safety import assert_public_http_url


IMAGE_DATA_URL_MAX_DIMENSION = 4096
IMAGE_DATA_URL_MAX_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ImageEditRequest:
    image_url: str
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
    mask_bytes: bytes | None = None, request_id: str = "", request_audit: dict[str, Any] | None = None,
) -> bytes:
    if not image_inputs:
        raise ProviderConfigurationError(provider_name, "image provider requires at least one reference image")
    spec = _image_provider_spec(provider_name)
    if len(image_inputs) > 1 and not api_registry.image_provider_supports_multiple_references(provider_name, len(image_inputs)):
        raise ProviderConfigurationError(provider_name, "Route does not support the required reference set")
    profile = spec.protocol_profile or {} if spec else {}
    originals = [hashlib.sha256(data).hexdigest() for data in image_inputs]
    image_inputs = [_bounded_image_data_url_bytes(data) for data in image_inputs]
    original_mask_sha = hashlib.sha256(mask_bytes).hexdigest() if mask_bytes else ""
    if mask_bytes is not None:
        mask_bytes = _validated_mask_bytes(mask_bytes, expected_image_bytes=image_inputs[0])
    if request_audit is not None:
        request_audit.update({
            "request_id": request_id, "provider": provider_name, "model": spec.model if spec else "",
            "request_size": str(profile.get("request_size") or ""), "quality": str(profile.get("quality") or "low"),
            "output_contract": str(profile.get("output_contract") or ""),
            "mask_sha256": hashlib.sha256(mask_bytes).hexdigest() if mask_bytes else "",
            "original_mask_sha256": original_mask_sha,
            "inputs": [{"original_sha256": original, "sent_sha256": hashlib.sha256(data).hexdigest(),
                        "sent_bytes": len(data), "transform": "unchanged" if original == hashlib.sha256(data).hexdigest() else "bounded_image_encoding"}
                       for original, data in zip(originals, image_inputs)],
        })
    if spec and spec.api_type == "openai_images_edit":
        return _generate_with_openai_images_edit(
            provider_name=provider_name,
            image_inputs=image_inputs,
            prompt=prompt,
            mask_bytes=mask_bytes,
        )
    if spec and spec.api_type == "openai_chat_completions_image":
        if mask_bytes is not None:
            raise ProviderConfigurationError(provider_name, "chat completions image provider cannot enforce protected masks")
        return _generate_with_openai_chat_completions_image(
            provider_name=provider_name,
            image_inputs=image_inputs,
            prompt=prompt,
        )
    if spec and spec.api_type == "async_image_generation":
        if mask_bytes is not None:
            raise ProviderConfigurationError(provider_name, "async image generation provider cannot enforce protected masks")
        return _generate_with_async_image_generation(
            provider_name=provider_name,
            image_inputs=image_inputs,
            prompt=prompt,
            request_id=request_id,
        )
    if spec and spec.api_type == "highwayapi":
        return _generate_with_highwayapi(
            provider_name=provider_name,
            image_inputs=image_inputs,
            prompt=prompt,
            mask_bytes=mask_bytes,
        )
    raise ProviderConfigurationError(provider_name, f"Unsupported registry image provider: {provider_name}")


def _generate_with_openai_images_edit(
    *, provider_name: str, image_inputs: list[bytes], prompt: str, mask_bytes: bytes | None
) -> bytes:
    spec = _image_provider_spec(provider_name)
    if spec is None or spec.api_type != "openai_images_edit":
        raise ProviderConfigurationError(provider_name, f"Unsupported OpenAI images.edit provider: {provider_name}")
    key = _provider_api_key(spec)
    if not key:
        token_hint = f" Set {spec.key_env}." if spec.key_env else ""
        raise ProviderConfigurationError(provider_name, f"Provider '{spec.display}' API key is not configured.{token_hint}")
    edit_request = _canonical_image_edit_request(spec=spec, image_bytes=image_inputs[0], prompt=prompt)
    model = spec.model
    if not model:
        raise ProviderConfigurationError(provider_name, "image provider requires an explicit registry model")
    body, content_type = _openai_images_edit_multipart_body(
        edit_request=edit_request,
        model=model,
        image_inputs=image_inputs,
        mask_bytes=mask_bytes,
    )
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
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        excerpt = exc.read().decode("utf-8", errors="replace")[:800]
        if exc.code in {408, 504, 524}:
            raise ProviderTransportError(provider_name, f"Remote image result unknown after HTTP {exc.code}: {excerpt}", ambiguous=True) from exc
        raise ImageGenerationError(f"{provider_name} HTTP {exc.code}: {excerpt}") from exc
    except urllib.error.URLError as exc:
        raise ImageGenerationError(f"{provider_name} request failed: {exc}") from exc
    data = _decode_image_response(text)
    return data


def _generate_with_openai_chat_completions_image(
    *, provider_name: str, image_inputs: list[bytes], prompt: str
) -> bytes:
    spec = _image_provider_spec(provider_name)
    if spec is None or spec.api_type != "openai_chat_completions_image":
        raise ProviderConfigurationError(provider_name, f"Unsupported OpenAI chat image provider: {provider_name}")
    key = _provider_api_key(spec)
    if not key:
        token_hint = f" Set {spec.key_env}." if spec.key_env else ""
        raise ProviderConfigurationError(provider_name, f"Provider '{spec.display}' API key is not configured.{token_hint}")
    body = json.dumps(
        {
            "model": spec.model or "gpt-image-2",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": str(prompt or "")},
                        *[
                            {"type": "image_url", "image_url": {"url": _image_data_url_from_bytes(image_bytes)}}
                            for image_bytes in image_inputs
                        ],
                    ],
                }
            ],
            "modalities": ["image", "text"],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        _provider_url(spec),
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "Mozilla/5.0",
        },
    )
    timeout = provider_timeout_seconds(provider_name)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        excerpt = exc.read().decode("utf-8", errors="replace")[:800]
        raise ImageGenerationError(f"{provider_name} HTTP {exc.code}: {excerpt}") from exc
    except urllib.error.URLError as exc:
        raise ImageGenerationError(f"{provider_name} request failed: {exc}") from exc
    return _decode_image_response(text)


def _generate_with_async_image_generation(
    *, provider_name: str, image_inputs: list[bytes], prompt: str, request_id: str = ""
) -> bytes:
    spec = _image_provider_spec(provider_name)
    if spec is None or spec.api_type != "async_image_generation":
        raise ProviderConfigurationError(provider_name, f"Unsupported async image provider: {provider_name}")
    key = _provider_api_key(spec)
    if not key:
        token_hint = f" Set {spec.key_env}." if spec.key_env else ""
        raise ProviderConfigurationError(provider_name, f"Provider '{spec.display}' API key is not configured.{token_hint}")
    submit_payload = _async_image_generation_payload(spec=spec, image_inputs=image_inputs, prompt=prompt)
    idempotency_key = _async_idempotency_key(provider_name, request_id, prompt, image_inputs)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "Mozilla/5.0",
        "Idempotency-Key": idempotency_key,
    }
    submit_text = _async_submit_with_retry(
        _provider_url(spec), submit_payload, headers=headers, provider_name=provider_name,
    )
    submit_data = _loads_provider_json(submit_text, provider_name=provider_name)
    task_id = _async_task_id(submit_data)
    if not task_id:
        raise ImageGenerationError(f"{provider_name} async image response did not contain task_id: {submit_text[:800]}")
    task_url = _async_task_status_url(_provider_url(spec), task_id)
    timeout = provider_timeout_seconds(provider_name)
    deadline = time.monotonic() + timeout
    poll_interval = 2.0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ImageGenerationError(f"{provider_name} async image generation timed out after {timeout}s (task_id={task_id})")
        status_text = _async_poll_with_retry(
            task_url,
            headers=headers,
            timeout=min(30, max(5, int(remaining))),
            provider_name=provider_name,
            task_id=task_id,
        )
        status_data = _loads_provider_json(status_text, provider_name=provider_name)
        task_data = status_data.get("data") if isinstance(status_data, dict) else None
        if isinstance(task_data, list) and task_data:
            task_data = task_data[0]
        if not isinstance(task_data, dict):
            task_data = status_data if isinstance(status_data, dict) else {}
        status = str(task_data.get("status") or "").strip().lower()
        if status in {"failed", "error", "cancelled", "canceled"}:
            error = task_data.get("error") or status_data.get("error") if isinstance(status_data, dict) else None
            raise ImageGenerationError(f"{provider_name} async image task failed: {error or status_text[:800]}")
        image_url = _async_result_image_url(task_data)
        progress = task_data.get("progress")
        if image_url and (status in {"completed", "succeeded", "success"} or str(progress) == "100"):
            return _download_image_bytes(image_url)
        time.sleep(min(poll_interval, max(0.5, remaining)))
        poll_interval = min(5.0, poll_interval + 0.5)


def _async_idempotency_key(provider_name: str, request_id: str, prompt: str, image_inputs: list[bytes]) -> str:
    digest = hashlib.sha256()
    digest.update(str(provider_name).encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(request_id or "").encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(prompt or "").encode("utf-8"))
    for image in image_inputs:
        digest.update(b"\0")
        digest.update(bytes(image))
    return digest.hexdigest()


def _is_ambiguous_transport_error(exc: Exception) -> bool:
    text = str(exc).casefold()
    return any(marker in text for marker in (
        "unexpected_eof", "ssl eof", "ssl: eof", "remote end closed",
        "remote disconnected", "incompleteread", "connection reset",
    ))


def _async_submit_with_retry(
    url: str, payload: dict[str, Any], *, headers: dict[str, str],
    provider_name: str,
) -> str:
    last: Exception | None = None
    for attempt in range(1, 3):
        try:
            return _post_json(url, payload, headers=headers, timeout=30, provider_name=provider_name)
        except Exception as exc:
            last = exc
            if not _is_ambiguous_transport_error(exc) or attempt >= 2:
                break
            time.sleep(0.75 * attempt)
    assert last is not None
    if _is_ambiguous_transport_error(last):
        raise ProviderTransportError(
            provider_name,
            f"async_submit_response_ambiguous: {last}",
            ambiguous=True,
        ) from last
    raise last


def _async_poll_with_retry(
    url: str, *, headers: dict[str, str], timeout: int,
    provider_name: str, task_id: str,
) -> str:
    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            return _get_text(url, headers=headers, timeout=timeout, provider_name=provider_name)
        except Exception as exc:
            last = exc
            if not _is_ambiguous_transport_error(exc) or attempt >= 3:
                break
            time.sleep(0.75 * attempt)
    assert last is not None
    if _is_ambiguous_transport_error(last):
        raise ProviderTransportError(
            provider_name,
            f"async_poll_response_ambiguous: task_id={task_id}: {last}",
            ambiguous=True,
        ) from last
    raise last


def _async_image_generation_payload(*, spec: ImageProviderSpec, image_inputs: list[bytes], prompt: str) -> dict[str, Any]:
    profile = spec.protocol_profile or {}
    size = str(profile.get("async_size") or profile.get("size") or "").strip()
    if not size:
        size = "1:1" if (spec.request_size or "").lower() in {"1024x1024", "2048x2048"} else spec.request_size or "1:1"
    resolution = str(profile.get("resolution") or "1k").strip().lower()
    return {
        "model": spec.model or "gpt-image-2",
        "prompt": str(prompt or ""),
        "n": 1,
        "size": size,
        "resolution": resolution,
        "image_urls": [_image_data_url_from_bytes(image_bytes) for image_bytes in image_inputs],
    }


def _post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str], timeout: int, provider_name: str) -> str:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        excerpt = exc.read().decode("utf-8", errors="replace")[:800]
        raise ImageGenerationError(f"{provider_name} HTTP {exc.code}: {excerpt}") from exc
    except urllib.error.URLError as exc:
        raise ImageGenerationError(f"{provider_name} request failed: {exc}") from exc


def _get_text(url: str, *, headers: dict[str, str], timeout: int, provider_name: str) -> str:
    request = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        excerpt = exc.read().decode("utf-8", errors="replace")[:800]
        raise ImageGenerationError(f"{provider_name} HTTP {exc.code}: {excerpt}") from exc
    except urllib.error.URLError as exc:
        raise ImageGenerationError(f"{provider_name} request failed: {exc}") from exc


def _loads_provider_json(text: str, *, provider_name: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImageGenerationError(f"{provider_name} returned non-JSON response: {text[:500]}") from exc
    if not isinstance(data, dict):
        raise ImageGenerationError(f"{provider_name} returned unexpected JSON response: {text[:500]}")
    return data


def _async_task_id(data: dict[str, Any]) -> str:
    raw = data.get("data")
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict):
        return str(raw.get("task_id") or raw.get("id") or "").strip()
    return str(data.get("task_id") or data.get("id") or "").strip()


def _async_task_status_url(submit_url: str, task_id: str) -> str:
    base = submit_url.rstrip("/")
    if base.lower().endswith("/images/generations"):
        base = base.rsplit("/", 2)[0]
    return f"{base}/tasks/{task_id}"


def _async_result_image_url(task_data: dict[str, Any]) -> str:
    result = task_data.get("result")
    if not isinstance(result, dict):
        return ""
    images = result.get("images")
    if not isinstance(images, list) or not images:
        return ""
    first = images[0]
    if isinstance(first, str):
        return first.strip()
    if isinstance(first, dict):
        url = first.get("url")
        if isinstance(url, list):
            return str(url[0] if url else "").strip()
        return str(url or "").strip()
    return ""


def _generate_with_highwayapi(
    *, provider_name: str, image_inputs: list[bytes], prompt: str, mask_bytes: bytes | None
) -> bytes:
    spec = _image_provider_spec(provider_name)
    if spec is None or spec.api_type != "highwayapi":
        raise ProviderConfigurationError(provider_name, f"Unsupported HighwayAPI image provider: {provider_name}")
    key = _provider_api_key(spec)
    if not key:
        token_hint = f" Set {spec.key_env}." if spec.key_env else ""
        raise ProviderConfigurationError(provider_name, f"Provider '{spec.display}' API key is not configured.{token_hint}")
    profile = spec.protocol_profile or {}
    if len(image_inputs) != 1:
        raise ProviderConfigurationError(provider_name, "HighwayAPI transport supports one reference image per edit")
    image_data_url = _image_data_url_from_bytes(image_inputs[0])
    image_field = str(profile.get("image_field") or "image").strip().lower()
    payload: dict[str, Any] = {
        "prompt": str(prompt or ""),
        "n": 1,
        "size": str(profile.get("size") or spec.request_size or "1024x1024"),
        "quality": str(profile.get("quality") or "low"),
        "background": str(profile.get("background") or "auto"),
        "output_format": str(profile.get("output_format") or "png"),
    }
    if image_field == "images":
        payload["images"] = [{"image_url": image_data_url}]
    else:
        payload["image"] = image_data_url
    if mask_bytes:
        if image_field == "images":
            raise ProviderConfigurationError(provider_name, "HighwayAPI images-array provider cannot enforce protected masks")
        payload["mask"] = _image_data_url_from_bytes(mask_bytes)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "Mozilla/5.0",
    }
    text = _post_json(_provider_url(spec), payload, headers=headers, timeout=provider_timeout_seconds(provider_name), provider_name=provider_name)
    return _decode_image_response(text)


def _openai_images_edit_multipart_body(
    *,
    edit_request: ImageEditRequest,
    model: str,
    image_inputs: list[bytes],
    mask_bytes: bytes | None = None,
) -> tuple[bytes, str]:
    boundary = f"amazonfactory-{uuid.uuid4().hex}"
    bounded_images = [_bounded_image_data_url_bytes(image_bytes) for image_bytes in image_inputs]
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
    if mask_bytes is not None:
        bounded_mask = _validated_mask_bytes(mask_bytes, expected_image_bytes=bounded_images[0])
        add_file("mask", "protected-mask.png", "image/png", bounded_mask)
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _validated_mask_bytes(mask_bytes: bytes, *, expected_image_bytes: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(expected_image_bytes)) as source, Image.open(io.BytesIO(mask_bytes)) as mask:
        if mask.mode != "RGBA":
            raise ImageGenerationError(
                f"Protected-region mask must be RGBA, got {mask.mode}"
            )
        if mask.size != source.size:
            source_ratio = source.width / max(1, source.height)
            mask_ratio = mask.width / max(1, mask.height)
            if abs(source_ratio - mask_ratio) > 0.001:
                raise ImageGenerationError(
                    f"Protected-region mask aspect ratio differs from the submitted reference: {mask.size} != {source.size}"
                )
            mask = mask.resize(source.size, resample=Image.Resampling.NEAREST)
        out = io.BytesIO()
        mask.save(out, format="PNG", optimize=True)
        return out.getvalue()


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
    *, spec: ImageProviderSpec, image_bytes: bytes, prompt: str
) -> ImageEditRequest:
    if spec.output_contract != "square" or not spec.request_size:
        raise ProviderConfigurationError(spec.name, "image provider requires square output_contract and request_size")
    return ImageEditRequest(
        image_url=_image_data_url_from_bytes(image_bytes),
        prompt=str(prompt or ""),
        size=spec.request_size,
        background="auto",
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


def _image_data_url_from_bytes(image_bytes: bytes) -> str:
    image_bytes = _bounded_image_data_url_bytes(image_bytes)
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    mime = _image_mime_from_bytes(image_bytes)
    return f"data:{mime};base64,{image_b64}"


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


def _decode_image_response(text: str) -> bytes:
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
        image = _image_bytes_from_response_item(item)
        if image:
            return image
    raise ImageGenerationError(f"Image edit provider response did not contain image data: {text[:800]}")


def _image_bytes_from_response_item(item: Any) -> bytes | None:
    if item in (None, ""):
        return None
    if isinstance(item, list):
        for value in item:
            data = _image_bytes_from_response_item(value)
            if data:
                return data
        return None
    if isinstance(item, str):
        return _image_bytes_from_string(item)
    if isinstance(item, dict):
        for key in ("b64_json", "base64", "image", "image_base64", "data", "content", "message"):
            value = item.get(key)
            if isinstance(value, str):
                data = _image_bytes_from_string(value)
                if data:
                    return data
            elif isinstance(value, list):
                data = _image_bytes_from_response_item(value)
                if data:
                    return data
            elif isinstance(value, dict):
                data = _image_bytes_from_response_item(value)
                if data:
                    return data
        for key in ("url", "image_url", "output_url", "images"):
            value = item.get(key)
            if isinstance(value, str):
                data = _image_bytes_from_string(value)
                if data:
                    return data
            elif isinstance(value, list):
                data = _image_bytes_from_response_item(value)
                if data:
                    return data
            elif isinstance(value, dict):
                data = _image_bytes_from_response_item(value)
                if data:
                    return data
    return None


def _image_bytes_from_string(value: str) -> bytes | None:
    text = value.strip()
    if not text:
        return None
    markdown_url = re.search(r"!\[[^\]]*]\((https?://[^)\s]+)\)", text)
    if markdown_url:
        return _download_image_bytes(markdown_url.group(1))
    if text.startswith(("http://", "https://")):
        return _download_image_bytes(text)
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    try:
        data = base64.b64decode(text, validate=False)
    except Exception:
        return None
    return data if data else None


def _download_image_bytes(url: str) -> bytes:
    assert_public_http_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*,*/*"})
    attempts = image_url_download_attempts()
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
            if not data:
                raise ImageGenerationError(f"Downloaded generated image is empty: {url}")
            return data
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not is_transient_imagegen_error(exc):
                break
            time.sleep(image_url_download_retry_delay(attempt))
    raise ImageGenerationError(f"Failed to download generated image after {attempts} attempt(s): {url}: {last_exc}") from last_exc
