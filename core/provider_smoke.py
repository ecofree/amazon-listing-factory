from __future__ import annotations

import json
import io
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from . import api_registry
from . import vision_gemini_client as vision_client
from .image_provider_transport import generate_with_registry_image_provider
from .provider_smoke_store import registry_fingerprint


class ProviderSmokeError(RuntimeError):
    pass


def smoke_model_provider(client: dict[str, Any], *, scope: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    status = "passed"
    try:
        _run_text_step(client)
        steps.append({"step": "text", "status": "passed"})
        if _has_capability(client, "vision_input"):
            _run_image_step(client)
            steps.append({"step": "image", "status": "passed"})
    except Exception as exc:
        status = "failed"
        steps.append({"step": steps[-1]["step"] if steps else "text", "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    return {
        "provider": str(client.get("name") or ""),
        "scope": scope,
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
    }


def smoke_registry_provider(provider_name: str, *, scope: str = "") -> list[dict[str, Any]]:
    entries = [entry for entry in api_registry.load_registry_entries() if entry.name == provider_name]
    if not entries:
        raise ProviderSmokeError(f"Provider not found in api_registry: {provider_name}")
    results: list[dict[str, Any]] = []
    for entry in entries:
        scopes = [scope] if scope else list(entry.scopes)
        for item_scope in scopes:
            if item_scope == "image_generation":
                results.append(_smoke_image_provider_result(entry, scope=item_scope))
                continue
            clients = [
                client
                for client in api_registry.model_clients_for_scope(item_scope)
                if client.get("name") == entry.name
            ]
            if not clients:
                results.append(
                    {
                        "provider": entry.name,
                        "scope": item_scope,
                        "status": "failed",
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "registry_fingerprint": registry_fingerprint(entry.raw),
                        "steps": [{"step": "registry", "status": "failed", "error": "No usable model client for scope"}],
                    }
                )
                continue
            result = smoke_model_provider(clients[0], scope=item_scope)
            result["registry_fingerprint"] = registry_fingerprint(entry.raw)
            results.append(result)
    return results


def _run_text_step(client: dict[str, Any]) -> str:
    payload = _model_payload(client, 'Return compact JSON only: {"ok":true}', [])
    return _post_and_parse(client, payload)


def _run_image_step(client: dict[str, Any]) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        image_path = Path(tmp) / "provider_smoke.jpg"
        Image.new("RGB", (32, 32), color=(245, 245, 245)).save(image_path, format="JPEG")
        payload = _model_payload(
            client, 'Return compact JSON only: {"image_received":true}', [image_path]
        )
        return _post_and_parse(client, payload)


def _model_payload(client: dict[str, Any], prompt: str, image_paths: list[Path]) -> dict[str, Any]:
    protocol = str(client.get("protocol") or "").strip().lower()
    model = str(client.get("model") or "")
    if vision_client._is_openai_responses_protocol(protocol):
        return vision_client._openai_responses_payload(model, prompt, image_paths, client)
    if vision_client._is_openai_chat_protocol(protocol):
        return vision_client._openai_chat_payload(model, prompt, image_paths, client)
    if _is_native_gemini_protocol(protocol):
        parts: list[dict[str, Any]] = [{"text": prompt}]
        parts.extend(vision_client._image_part(path) for path in image_paths)
        return vision_client._gemini_native_payload(parts, client)
    raise ProviderSmokeError(f"Unsupported model protocol for smoke test: {protocol or '<blank>'}")


def _post_and_parse(client: dict[str, Any], payload: dict[str, Any]) -> str:
    protocol = str(client.get("protocol") or "").strip().lower()
    if vision_client._is_openai_responses_protocol(protocol):
        url = vision_client._openai_responses_url(str(client.get("base_url") or ""))
        parser = vision_client._parse_openai_responses_candidates
    elif vision_client._is_openai_chat_protocol(protocol):
        url = vision_client._openai_chat_completions_url(str(client.get("base_url") or ""))
        parser = vision_client._parse_openai_chat_candidates
    elif _is_native_gemini_protocol(protocol):
        endpoint_url = vision_client._gemini_native_endpoint_url(
            str(client.get("base_url") or ""),
            str(client.get("model") or ""),
            "generateContent",
        )
        mode = vision_client._normalize_gemini_auth_mode(str(client.get("auth_mode") or ""))
        if not mode:
            mode = vision_client._gemini_auth_modes(str(client.get("base_url") or ""))[0]
        url, headers = vision_client._gemini_request_auth(
            endpoint_url,
            str(client.get("api_key") or ""),
            mode,
            client.get("bearer_token"),
        )
        body = vision_client._post_json_preserve_redirects(
            url,
            payload,
            headers=headers,
            timeout_seconds=90,
        )
        candidates = vision_client._parse_generate_content_candidates(body)
        if not candidates:
            raise ProviderSmokeError("Provider returned no parseable text")
        return candidates[0]
    else:
        raise ProviderSmokeError(f"Unsupported model protocol for smoke test: {protocol or '<blank>'}")
    body = vision_client._post_json_preserve_redirects(
        url,
        payload,
        headers=vision_client._openai_chat_headers(str(client.get("api_key") or ""), auth_mode=str(client.get("openai_auth_mode") or "bearer"), bearer_token=client.get("bearer_token")),
        timeout_seconds=90,
    )
    candidates = parser(body)
    if not candidates:
        raise ProviderSmokeError("Provider returned no parseable text")
    return candidates[0]


def _is_native_gemini_protocol(protocol: str | None) -> bool:
    return str(protocol or "").strip().lower() in {"gemini", "google_gemini", "native_gemini"}


def _smoke_image_provider_result(entry: api_registry.ApiRegistryEntry, *, scope: str) -> dict[str, Any]:
    missing = []
    if not entry.url:
        missing.append("url")
    if not (entry.key_env or entry.api_key):
        missing.append("key")
    steps: list[dict[str, Any]] = [
        {
            "step": "configured",
            "status": "failed" if missing else "passed",
            "error": f"Missing {', '.join(missing)}" if missing else "",
        }
    ]
    status = "failed" if missing else "passed"
    if not missing:
        try:
            _run_image_generation_step(entry.name)
            steps.append({"step": "image_generation", "status": "passed"})
        except Exception as exc:
            status = "failed"
            steps.append({"step": "image_generation", "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    return {
        "provider": entry.name,
        "scope": scope,
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "registry_fingerprint": registry_fingerprint(entry.raw),
        "steps": steps,
    }


def _run_image_generation_step(provider_name: str) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color=(245, 245, 245)).save(buffer, format="PNG")
    mask = io.BytesIO()
    Image.new("RGBA", (32, 32), color=(255, 255, 255, 0)).save(mask, format="PNG")
    data = generate_with_registry_image_provider(
        provider_name=provider_name,
        image_inputs=[buffer.getvalue()],
        mask_bytes=mask.getvalue() if api_registry.image_provider_supports_mask(provider_name) else None,
        prompt=(
            "Provider smoke test. Return a simple clean square product-style image. "
            "No text, no logo, no watermark."
        ),
    )
    if not data:
        raise ProviderSmokeError("Image provider returned empty bytes")
    with Image.open(io.BytesIO(data)) as image:
        image.verify()


def _has_capability(client: dict[str, Any], capability: str) -> bool:
    raw = client.get("capabilities")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = raw.replace(",", " ").split()
    values = {str(item or "").strip().lower().replace("-", "_") for item in raw or []}
    return capability in values
