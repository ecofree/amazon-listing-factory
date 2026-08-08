from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProtocolProfile:
    instructions_mode: str = "system_message"
    token_limit_param: str = "max_output_tokens"
    response_format: str = "json"
    image_input_format: str = "input_image_data_url"
    supports_reasoning: bool = True
    supports_store: bool = True


def profile_from_value(value: Any, *, protocol: str = "") -> ProtocolProfile:
    data = _profile_dict(value)
    defaults = _defaults_for_protocol(protocol)
    merged = {**defaults, **data}
    return ProtocolProfile(
        instructions_mode=_choice(
            merged.get("instructions_mode"),
            {"system_message", "top_level"},
            defaults["instructions_mode"],
        ),
        token_limit_param=_choice(
            merged.get("token_limit_param"),
            {"max_output_tokens", "max_tokens", "none"},
            defaults["token_limit_param"],
        ),
        response_format=_choice(
            merged.get("response_format"),
            {"json", "sse", "auto"},
            defaults["response_format"],
        ),
        image_input_format=_choice(
            merged.get("image_input_format"),
            {"input_image_data_url"},
            defaults["image_input_format"],
        ),
        supports_reasoning=_bool(merged.get("supports_reasoning"), True),
        supports_store=_bool(merged.get("supports_store"), True),
    )


def profile_from_client(client: dict[str, Any]) -> ProtocolProfile:
    return profile_from_value(client.get("protocol_profile"), protocol=str(client.get("protocol") or ""))


def profile_to_client_value(value: Any) -> str:
    data = _profile_dict(value)
    return json.dumps(data, ensure_ascii=False, sort_keys=True) if data else ""


def _defaults_for_protocol(protocol: str) -> dict[str, Any]:
    normalized = str(protocol or "").strip().lower().replace("-", "_")
    if normalized in {"openai_responses", "responses", "responses_api"}:
        return {
            "instructions_mode": "system_message",
            "token_limit_param": "max_output_tokens",
            "response_format": "json",
            "image_input_format": "input_image_data_url",
        }
    return {
        "instructions_mode": "system_message",
        "token_limit_param": "max_tokens",
        "response_format": "json",
        "image_input_format": "input_image_data_url",
    }


def _profile_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _choice(value: Any, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized if normalized in allowed else default


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
