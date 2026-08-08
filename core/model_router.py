from __future__ import annotations

import json
from typing import Any

from . import api_registry


MODEL_SCOPES = {"vision_qa", "visual_planning"}


class ModelRouterError(RuntimeError):
    pass


def normalize_scope(scope: str) -> str:
    return api_registry.normalize_scope(scope)


def clients_for_scope(scope: str) -> list[dict[str, str]]:
    normalized = normalize_scope(scope)
    if normalized not in MODEL_SCOPES:
        raise ModelRouterError(f"Scope '{scope}' is not a text/vision model scope")
    return [
        client
        for client in api_registry.model_clients_for_scope(normalized)
        if _client_matches_scope(normalized, client)
    ]


def require_clients_for_scope(scope: str) -> list[dict[str, str]]:
    clients = clients_for_scope(scope)
    if clients:
        return clients
    normalized = normalize_scope(scope)
    raise ModelRouterError(f"Missing model provider for scope '{normalized}' in configs/api_registry.json.")


def provider_names_for_scope(scope: str) -> list[str]:
    normalized = normalize_scope(scope)
    if normalized != "image_generation":
        raise ModelRouterError(f"Scope '{scope}' is not an image provider scope")
    return [
        entry.name
        for entry in api_registry.image_provider_entries()
        if _entry_has_required_capabilities(entry)
    ]


def validate_routes(*, require_smoke: bool = False) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    errors, warnings = api_registry.validate_registry()
    if not provider_names_for_scope("image_generation"):
        errors.append({"error": "model_router: no enabled provider for image_generation"})
    if require_smoke:
        from .provider_smoke_store import smoke_errors_for_entries

        errors.extend(smoke_errors_for_entries(api_registry.load_registry_entries()))
    return errors, warnings


def _client_matches_scope(scope: str, client: dict[str, str]) -> bool:
    return _client_has_required_capabilities(scope, client)


def _client_has_required_capabilities(scope: str, client: dict[str, str]) -> bool:
    required = api_registry.REQUIRED_SCOPE_CAPABILITIES.get(scope, set())
    return required.issubset(_client_capabilities(client))


def _client_capabilities(client: dict[str, str]) -> set[str]:
    raw: Any = client.get("capabilities")
    if not raw:
        return set()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = raw.replace(",", " ").split()
    if isinstance(raw, (list, tuple, set)):
        return {str(item or "").strip().lower().replace("-", "_") for item in raw if str(item or "").strip()}
    return {str(raw or "").strip().lower().replace("-", "_")} if str(raw or "").strip() else set()


def _entry_has_required_capabilities(entry: api_registry.ApiRegistryEntry) -> bool:
    required: set[str] = set()
    for scope in entry.scopes:
        required.update(api_registry.REQUIRED_SCOPE_CAPABILITIES.get(scope, set()))
    return required.issubset(set(entry.capabilities))
