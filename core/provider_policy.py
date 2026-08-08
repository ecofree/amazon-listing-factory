from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json
from .paths import CONFIGS_ROOT


# The example file is documentation only.  Runtime routing must read the
# explicit production policy so a stale example cannot silently re-enable or
# ignore a provider restriction.
DEFAULT_POLICY_PATH = CONFIGS_ROOT / "provider_policy.json"


class ProviderPolicyError(RuntimeError):
    pass


def load_provider_policy(path: str | Path | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path else DEFAULT_POLICY_PATH
    if not policy_path.exists():
        raise ProviderPolicyError(f"Provider policy file not found: {policy_path}")
    return read_json(policy_path)


def assert_provider_allowed(provider: str, policy: dict[str, Any]) -> None:
    forbidden = forbidden_provider_set(policy)
    image_generation = policy.get("image_generation") if isinstance(policy, dict) else None
    if isinstance(image_generation, dict):
        forbidden |= forbidden_provider_set(image_generation)
    _assert_not_forbidden(provider, forbidden)


def assert_provider_allowed_for_config(provider: str, config: dict[str, Any], global_policy: dict[str, Any] | None = None) -> None:
    if global_policy:
        assert_provider_allowed(provider, global_policy)
    for section_name in ("provider_policy", "generation_policy"):
        section = config.get(section_name)
        if isinstance(section, dict):
            _assert_not_forbidden(provider, forbidden_provider_set(section))


def filter_not_forbidden_providers(providers: list[str], config: dict[str, Any], global_policy: dict[str, Any] | None = None) -> list[str]:
    clean: list[str] = []
    for provider in providers:
        try:
            assert_provider_allowed_for_config(provider, config, global_policy=global_policy)
        except ProviderPolicyError:
            continue
        clean.append(provider)
    return clean


def forbidden_provider_set(policy: dict[str, Any] | None) -> set[str]:
    policy = policy if isinstance(policy, dict) else {}
    return {
        str(item).lower()
        for key in ("forbidden_providers", "forbidden_image_providers")
        for item in policy.get(key, [])
    }


def _assert_not_forbidden(provider: str, forbidden: set[str]) -> None:
    value = provider.strip().lower()
    if value in forbidden:
        raise ProviderPolicyError(f"Image provider is forbidden by policy: {provider}")
