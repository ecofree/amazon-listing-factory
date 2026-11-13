from __future__ import annotations

import json
from typing import Any

from . import api_registry


MODEL_SCOPES = {"visual_planning", "vision_qa"}


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


def validate_routes(*, require_smoke: bool = False,
                    required_scopes: tuple[str, ...] = ('visual_planning', 'image_generation')) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    invalid, warnings = api_registry.validate_registry()
    warnings.extend({'warning': row['error']} for row in invalid)
    errors, selected = [], []
    for scope in set(required_scopes):
        if scope not in api_registry.VALID_SCOPES:
            errors.append({'error': f'model_router: unsupported required scope {scope}'})
            continue
        try:
            usable = [entry for entry in api_registry.load_registry_entries()
                      if scope in entry.scopes and entry.api_key and _entry_has_required_capabilities(entry)]
        except (ValueError, OSError):
            usable = []
        selected.extend(usable)
        if not usable:
            errors.append({'error': f'model_router: no enabled, credentialed and capable provider for {scope}'})
    if require_smoke:
        from .provider_smoke_store import smoke_errors_for_entries

        errors.extend(smoke_errors_for_entries(list({entry.name: entry for entry in selected}.values())))
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
