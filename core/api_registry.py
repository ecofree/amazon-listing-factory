from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .provider_profiles import profile_to_client_value


FACTORY_ROOT = Path(__file__).resolve().parents[1]
VALID_SCOPES = {"vision_qa", "visual_planning", "image_generation"}
IMAGE_API_TYPES = {
    "openai_images_edit",
    "openai_chat_completions_image",
    "async_image_generation",
    "highwayapi",
}


@dataclass(frozen=True)
class ApiRegistryEntry:
    name: str
    family: str
    scopes: tuple[str, ...]
    protocol: str
    base_url: str
    url: str
    key_env: str
    api_key: str
    bearer_env: str
    bearer_token: str
    model: str
    api_type: str
    auth_mode: str
    openai_auth_mode: str
    response_modalities: tuple[str, ...]
    capabilities: tuple[str, ...]
    protocol_profile: dict[str, Any]
    priority: int
    display: str
    raw: dict[str, Any]


def load_registry_entries() -> list[ApiRegistryEntry]:
    entries: list[ApiRegistryEntry] = []
    for item in _raw_registry_items():
        entry = _normalize_entry(item)
        if entry is not None:
            entries.append(entry)
    return _dedupe_entries(entries)


def model_clients_for_scope(scope: str) -> list[dict[str, str]]:
    wanted = _normalize_scope(scope) or "vision_qa"
    clients: list[dict[str, str]] = []
    for entry in _entries_for_scope(wanted, family="gemini"):
        if entry.family != "gemini" or wanted not in entry.scopes:
            continue
        if not entry.base_url or not entry.api_key:
            continue
        client: dict[str, str] = {
            "name": entry.name,
            "protocol": entry.protocol or "gemini",
            "base_url": entry.base_url.rstrip("/"),
            "key_env": entry.key_env,
            "api_key": entry.api_key,
            "model": entry.model,
        }
        if entry.bearer_token:
            client["bearer_token"] = entry.bearer_token
        if entry.auth_mode:
            client["auth_mode"] = entry.auth_mode
        if entry.openai_auth_mode:
            client["openai_auth_mode"] = entry.openai_auth_mode
        if entry.response_modalities:
            client["response_modalities"] = json.dumps(list(entry.response_modalities))
        if entry.capabilities:
            client["capabilities"] = json.dumps(list(entry.capabilities))
        profile_value = profile_to_client_value(entry.protocol_profile)
        if profile_value:
            client["protocol_profile"] = profile_value
        client["priority"] = str(entry.priority)
        for raw_key, client_key in (
            ("reasoning_effort", "reasoning_effort"),
            ("model_reasoning_effort", "reasoning_effort"),
            ("disable_response_storage", "disable_response_storage"),
            ("store", "store"),
            ("max_output_tokens", "max_output_tokens"),
            ("max_tokens", "max_output_tokens"),
            ("temperature", "temperature"),
        ):
            if raw_key in entry.raw and entry.raw.get(raw_key) not in (None, ""):
                client[client_key] = str(entry.raw.get(raw_key))
        clients.append(client)
    return clients


def image_provider_entries() -> list[ApiRegistryEntry]:
    return [
        entry
        for entry in _entries_for_scope("image_generation", family="image_generation")
        if entry.family == "image_generation"
        and "image_generation" in entry.scopes
        and entry.name
        and entry.url
        and (entry.key_env or entry.api_key)
        and entry.api_type in IMAGE_API_TYPES
    ]


def image_provider_names() -> list[str]:
    return [entry.name for entry in image_provider_entries()]


def image_provider_supports_mask(name: str) -> bool:
    """Only native image-edit transports can enforce an immutable pixel mask."""
    logical_name = str(name or "").strip()
    return any(
        entry.name == logical_name
        and entry.api_type in {"openai_images_edit", "highwayapi"}
        and "protected_mask" in entry.capabilities
        for entry in image_provider_entries()
    )


def image_provider_supports_multiple_references(name: str, reference_count: int = 2) -> bool:
    logical_name = str(name or "").strip()
    return any(
        entry.name == logical_name and "multiple_reference_images" in entry.capabilities
        and reference_count <= int(entry.protocol_profile.get("max_reference_images") or (1 if entry.api_type == "highwayapi" else 16))
        for entry in image_provider_entries()
    )


def image_provider_resource_group(name: str) -> str:
    entry = next((row for row in image_provider_entries() if row.name == name), None)
    return str((entry.raw.get("resource_group") if entry else "") or name)


def dedupe_image_provider_names(names: list[str]) -> list[str]:
    """Collapse logical aliases that resolve to the same physical endpoint/model."""
    unique: list[str] = []
    identities: set[str] = set()
    for name in names:
        logical_name = str(name or "").strip()
        if not logical_name:
            continue
        identity = image_provider_identity_key(image_provider_physical_identity(logical_name))
        if identity in identities:
            continue
        identities.add(identity)
        unique.append(logical_name)
    return unique


def image_provider_identity_key(identity: dict[str, Any]) -> str:
    return json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)


def model_client_physical_identity(client: dict[str, Any]) -> dict[str, Any]:
    """Behavior-affecting model identity, excluding logical aliases and secrets."""
    return {
        key: client[key]
        for key in (
            "base_url",
            "protocol",
            "model",
            "protocol_profile",
            "capabilities",
            "response_modalities",
            "key_env",
            "max_output_tokens",
            "reasoning_effort",
            "temperature",
        )
        if client.get(key) not in (None, "")
    }


def image_provider_physical_identity(name: str) -> dict[str, Any]:
    logical_name = str(name or "").strip()
    if logical_name in {"copy", "mock"}:
        return {"builtin": logical_name}
    for entry in image_provider_entries():
        if entry.name == logical_name:
            return {
                "url": entry.url,
                "api_type": entry.api_type,
                "model": entry.model,
                "capabilities": entry.capabilities,
                "response_modalities": entry.response_modalities,
                "protocol_profile": entry.protocol_profile,
                "key_env": entry.key_env,
            }
    return {"unresolved_provider": logical_name}


def validate_registry() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for item in _raw_registry_items(include_disabled=True):
        if not isinstance(item, dict):
            errors.append({"error": "api_registry entry must be an object"})
            continue
        if _disabled(item):
            continue
        entry = _normalize_entry(item)
        if entry is None:
            continue
        label = entry.name or "(unnamed)"
        if not entry.name:
            errors.append({"error": "api_registry entry missing name"})
        if not entry.scopes:
            errors.append({"error": f"api_registry {label}: requires explicit scope"})
        invalid_scopes = [scope for scope in entry.scopes if scope not in VALID_SCOPES]
        if invalid_scopes:
            errors.append({"error": f"api_registry {label}: unsupported scope(s): {', '.join(invalid_scopes)}"})
        if entry.family == "gemini":
            if not entry.base_url:
                errors.append({"error": f"api_registry {label}: gemini entry requires base_url"})
            if not entry.model:
                errors.append({"error": f"api_registry {label}: gemini entry requires explicit model"})
        elif entry.family == "image_generation":
            roles = entry.raw.get("allowed_roles")
            if not isinstance(roles, list) or not roles or any(role not in {"main", "scene", "func", "size"} for role in roles):
                errors.append({"error": f"api_registry {label}: requires explicit allowed_roles (main, scene, func, size)"})
            preference = entry.raw.get("role_priority", {})
            if not isinstance(preference, dict) or any(key not in (roles if isinstance(roles, list) else []) or type(value) is not int for key, value in preference.items()):
                errors.append({"error": f"api_registry {label}: role_priority must assign integers to allowed roles"})
            if not entry.url:
                errors.append({"error": f"api_registry {label}: image_generation entry requires url"})
            if entry.api_type not in IMAGE_API_TYPES:
                errors.append(
                    {
                        "error": (
                            f"api_registry {label}: image_generation api_type must be "
                            "openai_images_edit, openai_chat_completions_image, "
                            "async_image_generation, or highwayapi"
                        )
                    }
                )
            if not entry.model.startswith("gpt-image-2"):
                warnings.append({"warning": f"api_registry {label}: image_generation model is not gpt-image-2 series"})
            try:
                prompt_limit = int(entry.raw.get("prompt_max_chars"))
            except (TypeError, ValueError):
                prompt_limit = 0
            if prompt_limit < 1000:
                errors.append({"error": f"api_registry {label}: image_generation requires prompt_max_chars >= 1000"})
            request_size = str(entry.protocol_profile.get("request_size") or "")
            output_contract = str(entry.protocol_profile.get("output_contract") or "")
            if not re.fullmatch(r"[1-9]\d{2,4}x[1-9]\d{2,4}", request_size):
                errors.append({"error": f"api_registry {label}: image_generation requires a pixel request_size"})
            if output_contract != "square":
                errors.append({"error": f"api_registry {label}: image_generation output_contract must be square"})
        else:
            errors.append({"error": f"api_registry {label}: unsupported family '{entry.family}'"})
        if not entry.key_env and not entry.api_key:
            warnings.append({"warning": f"api_registry {label}: no key_env or api_key configured"})
        if entry.key_env and not os.environ.get(entry.key_env, "").strip():
            warnings.append({"warning": f"api_registry {label}: token env {entry.key_env} is not set"})
        if entry.bearer_env and not os.environ.get(entry.bearer_env, "").strip():
            warnings.append({"warning": f"api_registry {label}: bearer env {entry.bearer_env} is not set"})
        missing_caps = _missing_required_capabilities(entry)
        if missing_caps:
            errors.append(
                {
                    "error": (
                        f"api_registry {label}: missing capabilities for "
                        f"{', '.join(scope for scope in entry.scopes if scope in REQUIRED_SCOPE_CAPABILITIES)}: "
                        f"{', '.join(missing_caps)}"
                    )
                }
            )
    return errors, warnings


def _raw_registry_items(*, include_disabled: bool = False) -> list[Any]:
    raw_env = os.environ.get("AMAZON_FACTORY_API_REGISTRY", "").strip()
    if raw_env:
        items = _items_from_payload(_loads_json(raw_env))
        return items if include_disabled else [item for item in items if not (isinstance(item, dict) and _disabled(item))]
    items: list[Any] = []
    for path in _registry_file_paths():
        if not path.exists():
            continue
        items.extend(_items_from_payload(_loads_json(path.read_text(encoding="utf-8-sig"))))
    if include_disabled:
        return items
    return [item for item in items if not (isinstance(item, dict) and _disabled(item))]


def _registry_file_paths() -> list[Path]:
    paths: list[Path] = []
    raw = os.environ.get("AMAZON_FACTORY_API_REGISTRY_FILE", "").strip()
    for item in re.split(r"[;\r\n]+", raw):
        item = item.strip()
        if item:
            paths.append(Path(item))
    if paths:
        return paths
    default_path = FACTORY_ROOT / "configs" / "api_registry.json"
    if default_path.exists():
        paths.append(default_path)
    return paths


def _loads_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _items_from_payload(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    items: list[Any] = []
    for key in ("endpoints", "providers", "apis", "registry"):
        value = payload.get(key)
        if isinstance(value, list):
            items.extend(value)
    if not items and any(key in payload for key in ("base_url", "url", "model", "key_env")):
        items.append(payload)
    return items


def _normalize_entry(item: Any) -> ApiRegistryEntry | None:
    if not isinstance(item, dict) or _disabled(item):
        return None
    model = str(item.get("model") or "").strip()
    api_type = _normalize_api_type(str(item.get("api_type") or item.get("type") or "").strip())
    family = _normalize_family(str(item.get("family") or item.get("kind") or "").strip(), model=model, api_type=api_type)
    scopes = _normalize_scopes(item.get("scope") or item.get("scopes"), family=family, model=model, api_type=api_type)
    base_url_env = str(item.get("base_url_env") or item.get("api_base_env") or "").strip()
    base_url = str(os.environ.get(base_url_env, "") if base_url_env else item.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        base_url = str(item.get("base_url") or "").strip().rstrip("/")
    url = str(item.get("url") or item.get("endpoint") or "").strip().rstrip("/")
    if family == "gemini" and not base_url:
        base_url = url
    if family == "image_generation" and not api_type:
        if base_url and not url:
            api_type = "openai_images_edit"
    if family == "image_generation" and api_type == "openai_images_edit":
        url = _openai_images_edit_url(base_url=base_url, url=url)
    elif family == "image_generation" and api_type == "openai_chat_completions_image":
        url = _openai_chat_completions_url(base_url=base_url, url=url)
    elif family == "image_generation" and api_type == "async_image_generation":
        url = _async_image_generation_url(base_url=base_url, url=url)
    elif family == "image_generation" and not url:
        url = base_url
    key_env = str(item.get("key_env") or item.get("api_key_env") or "").strip()
    api_key = str(item.get("api_key") or item.get("key") or "").strip()
    if key_env and not api_key:
        api_key = os.environ.get(key_env, "").strip()
    bearer_env = str(
        item.get("bearer_env")
        or item.get("bearer_token_env")
        or item.get("token_env")
        or item.get("authorization_env")
        or ""
    ).strip()
    bearer_token = str(
        item.get("bearer_token")
        or item.get("token")
        or item.get("access_token")
        or ""
    ).strip()
    if bearer_env and not bearer_token:
        bearer_token = os.environ.get(bearer_env, "").strip()
    protocol = str(item.get("protocol") or item.get("api") or ("gemini" if family == "gemini" else "")).strip().lower()
    name = str(item.get("name") or "").strip()
    if not name:
        name = _default_name(family=family, model=model, base_url=base_url or url)
    return ApiRegistryEntry(
        name=_normalize_name(name),
        family=family,
        scopes=scopes,
        protocol=protocol,
        base_url=base_url,
        url=url,
        key_env=key_env,
        api_key=api_key,
        bearer_env=bearer_env,
        bearer_token=bearer_token,
        model=model or ("gpt-image-2" if "image_generation" in scopes else ""),
        api_type=api_type,
        auth_mode=str(item.get("auth_mode") or "").strip().lower(),
        openai_auth_mode=str(
            item.get("openai_auth_mode")
            or item.get("openai_authorization_mode")
            or item.get("authorization_mode")
            or ""
        ).strip().lower(),
        response_modalities=tuple(_response_modalities(item)),
        capabilities=tuple(_capabilities(item)),
        protocol_profile=_protocol_profile(item),
        priority=_priority(item.get("priority")),
        display=str(item.get("display") or item.get("display_name") or item.get("name") or "").strip(),
        raw=dict(item),
    )


def _disabled(item: dict[str, Any]) -> bool:
    value = item.get("enabled")
    if value is None:
        return False
    return str(value).strip().lower() in {"0", "false", "no", "off", "disabled"}


def _normalize_family(raw: str, *, model: str, api_type: str) -> str:
    value = raw.strip().lower().replace("-", "_")
    if value in {"image", "image_gen", "image_generation", "gpt_image"}:
        return "image_generation"
    if value in {
        "gemini",
        "vision",
        "vision_qa",
        "openai",
        "openai_vision",
        "openai_responses",
        "responses",
    }:
        return "gemini"
    model_value = model.lower()
    if model_value.startswith("gpt-image-2") or api_type in IMAGE_API_TYPES:
        return "image_generation"
    if "gemini" in model_value:
        return "gemini"
    return value or "gemini"


def _normalize_scopes(raw: Any, *, family: str, model: str, api_type: str) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(raw, str):
        values = [item.strip() for item in re.split(r"[,;\s]+", raw) if item.strip()]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(item).strip() for item in raw if str(item or "").strip()]
    scopes = [_normalize_scope(value) for value in values]
    scopes = [scope for scope in scopes if scope]
    out: list[str] = []
    for scope in scopes:
        if scope and scope not in out:
            out.append(scope)
    return tuple(out)


def _normalize_scope(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _normalize_api_type(raw: str) -> str:
    value = raw.strip().lower().replace("-", "_")
    if value in {"openai_images_edit", "openai_image_edit", "images_edit", "image_edit", "openai_edit"}:
        return "openai_images_edit"
    if value in {
        "openai_chat_completions_image",
        "openai_chat_completion_image",
        "chat_completions_image",
        "chat_completion_image",
        "openai_chat_image",
    }:
        return "openai_chat_completions_image"
    if value in {
        "async_image_generation",
        "apimart",
        "apimart_async",
        "apimart_image_generation",
        "dragoncode",
        "dragoncode_async",
        "dragoncode_image_generation",
    }:
        return "async_image_generation"
    if value in {"highwayapi", "highway", "highwayapi_image_generation"}:
        return "highwayapi"
    return value


def _openai_images_edit_url(*, base_url: str, url: str) -> str:
    target = (url or base_url).strip().rstrip("/")
    if not target:
        return ""
    normalized = target.lower()
    if normalized.endswith("/images/edits") or normalized.endswith("/images/edit"):
        return target
    return f"{target}/images/edits"


def _openai_chat_completions_url(*, base_url: str, url: str) -> str:
    target = (url or base_url).strip().rstrip("/")
    if not target:
        return ""
    if target.lower().endswith("/chat/completions"):
        return target
    return f"{target}/chat/completions"


def _async_image_generation_url(*, base_url: str, url: str) -> str:
    target = (url or base_url).strip().rstrip("/")
    if not target:
        return ""
    if target.lower().endswith("/images/generations"):
        return target
    return f"{target}/images/generations"


def _response_modalities(item: dict[str, Any]) -> list[str]:
    value = item.get("response_modalities") or item.get("responseModalities") or item.get("modalities")
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = [value]
        value = parsed
    if isinstance(value, (list, tuple)):
        return [str(part).strip().upper() for part in value if str(part or "").strip()]
    return [str(value).strip().upper()]


REQUIRED_SCOPE_CAPABILITIES: dict[str, set[str]] = {
    "vision_qa": {"vision_input", "json_output"},
    "visual_planning": {"vision_input", "json_output", "visual_planning"},
    "image_generation": {"image_edit", "reference_image", "square_output"},
}


def _capabilities(item: dict[str, Any]) -> list[str]:
    value = item.get("capabilities") or item.get("capability")
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = re.split(r"[,;\s]+", value)
        value = parsed
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for part in value:
            normalized = str(part or "").strip().lower().replace("-", "_")
            if normalized and normalized not in out:
                out.append(normalized)
        return out
    normalized = str(value or "").strip().lower().replace("-", "_")
    return [normalized] if normalized else []


def _priority(value: Any) -> int:
    try:
        return int(float(str(value or "0")))
    except (TypeError, ValueError):
        return 0


def _protocol_profile(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("protocol_profile") or item.get("profile") or {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = {}
        value = parsed
    return dict(value) if isinstance(value, dict) else {}


def _missing_required_capabilities(entry: ApiRegistryEntry) -> list[str]:
    required: set[str] = set()
    for scope in entry.scopes:
        required.update(REQUIRED_SCOPE_CAPABILITIES.get(scope, set()))
    return sorted(required - set(entry.capabilities))


def _default_name(*, family: str, model: str, base_url: str) -> str:
    host = re.sub(r"^https?://", "", base_url).split("/", 1)[0]
    seed = "_".join(part for part in (family, model, host) if part)
    return seed or "api_registry_entry"


def _normalize_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_").lower()
    return normalized or "api_registry_entry"


def _dedupe_entries(entries: list[ApiRegistryEntry]) -> list[ApiRegistryEntry]:
    physical: dict[tuple[str, str, str, str, tuple[str, ...]], ApiRegistryEntry] = {}
    for entry in entries:
        marker = (
            entry.family,
            entry.protocol or entry.api_type,
            entry.url if entry.family == "image_generation" else entry.base_url or entry.url,
            entry.model,
            (*entry.scopes, entry.key_env),
        )
        current = physical.get(marker)
        if current is None or entry.priority > current.priority:
            physical[marker] = entry
    return list(physical.values())


def _entries_for_scope(scope: str, *, family: str) -> list[ApiRegistryEntry]:
    wanted = _normalize_scope(scope)
    entries = sorted((
        entry
        for entry in load_registry_entries()
        if entry.family == family and wanted in entry.scopes
    ), key=lambda entry: entry.priority, reverse=True)
    unique: list[ApiRegistryEntry] = []
    seen: set[str] = set()
    for entry in entries:
        marker = json.dumps(
            {
                "family": entry.family,
                "protocol": entry.protocol or entry.api_type,
                "url": entry.url if entry.family == "image_generation" else entry.base_url or entry.url,
                "model": entry.model,
                "capabilities": entry.capabilities,
                "response_modalities": entry.response_modalities,
                "protocol_profile": entry.protocol_profile,
                "key_env": entry.key_env,
            },
            sort_keys=True,
            default=str,
        )
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(entry)
    return unique


def normalize_scope(scope: str) -> str:
    return _normalize_scope(scope)
