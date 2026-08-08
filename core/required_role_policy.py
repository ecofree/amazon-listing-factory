from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .image_role_utils import role_key


class RequiredRolePolicyError(ValueError):
    pass


def main_image_policy(plugin: Any) -> str:
    config = plugin.merged_config() if hasattr(plugin, "merged_config") else {}
    image_config = config.get("image_generation") if isinstance(config, dict) else None
    policy = str((image_config or {}).get("main_image_policy") or "").strip()
    if policy not in {"white_background", "product_first_lifestyle"}:
        raise RequiredRolePolicyError(
            f"{getattr(plugin, 'category_id', 'unknown')} must declare a valid image_generation.main_image_policy"
        )
    return policy


def structural_component_checks(plugin: Any, *, required: bool = False) -> list[str]:
    config = plugin.merged_config() if hasattr(plugin, "merged_config") else {}
    image_config = config.get("image_generation") if isinstance(config, dict) else None
    raw = image_config.get("structure_invariants") if isinstance(image_config, dict) else None
    checks = [str(item or "").strip() for item in raw] if isinstance(raw, list) else []
    if any(not item for item in checks) or len(checks) != len(set(checks)) or len(checks) > 16:
        raise RequiredRolePolicyError("image_generation.structure_invariants must contain 1-16 unique nonblank items")
    if required and not checks:
        raise RequiredRolePolicyError("image_generation.structure_invariants is required for production")
    return checks


def compiled_image_policy(plugin: Any) -> dict[str, Any]:
    config = plugin.merged_config() if hasattr(plugin, "merged_config") else {}
    image_config = config.get("image_generation") if isinstance(config, dict) else None
    if not isinstance(image_config, dict):
        raise RequiredRolePolicyError("image_generation policy is required")
    order = _string_list(image_config.get("template_image_role_order") or ["main", "scene", "func", "size"])
    if order != ["main", "scene", "func", "size"]:
        raise RequiredRolePolicyError("template_image_role_order must be main, scene, func, size")
    policy = {
        "category_id": str(getattr(plugin, "category_id", "") or ""),
        "main_image_policy": main_image_policy(plugin),
        "structure_invariants": structural_component_checks(plugin, required=True),
        "allowed_internal_props": _string_list(image_config.get("allowed_internal_props")),
        "replaceable_staging": _string_list(image_config.get("replaceable_staging")),
        "forbidden_additions": _forbidden_addition_list(image_config.get("forbidden_additions")),
        "role_specific_rules": _role_rules(image_config.get("role_specific_rules")),
        "template_image_role_order": order,
    }
    policy["policy_id"] = hashlib.sha256(json.dumps(policy, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return policy


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RequiredRolePolicyError("image_generation executable contract fields must be lists")
    rows = [_policy_text(item) for item in value]
    if any(not item for item in rows):
        raise RequiredRolePolicyError("image_generation executable contract lists cannot contain blanks")
    return list(dict.fromkeys(rows))


def _policy_text(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value or "").strip()


def _forbidden_addition_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RequiredRolePolicyError("image_generation.forbidden_additions must be a list")
    rows: list[str] = []
    for item in value:
        if isinstance(item, dict):
            part = " ".join(str(item.get("part") or "").split())
            if not part:
                raise RequiredRolePolicyError("forbidden_additions entries require part")
            text = f"Do not add {part}"
            if item.get("unless_source_visible"):
                text += " unless visible in the editable reference"
        else:
            text = " ".join(str(item or "").split())
        if not text:
            raise RequiredRolePolicyError("forbidden_additions cannot contain blanks")
        if text not in rows:
            rows.append(text)
    return rows


def _role_rules(value: Any) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RequiredRolePolicyError("image_generation.role_specific_rules must be an object")
    out: dict[str, list[str]] = {}
    for role, rules in value.items():
        normalized = role_key(str(role))
        if normalized not in {"main", "scene", "func", "size"}:
            raise RequiredRolePolicyError(f"Unsupported role_specific_rules role: {role}")
        out[normalized] = _string_list(rules)
    return out


@dataclass(frozen=True)
class RequiredRolePolicy:
    category_id: str
    counts: dict[str, int]
    policy_id: str


def required_role_policy(plugin: Any) -> RequiredRolePolicy:
    config = plugin.merged_config() if hasattr(plugin, "merged_config") else {}
    policy = config.get("required_role_policy") if isinstance(config, dict) else None
    raw = policy.get("counts") if isinstance(policy, dict) else None
    if not isinstance(raw, dict) or not raw:
        raise RequiredRolePolicyError(
            f"{getattr(plugin, 'category_id', 'unknown')} must declare "
            "required_role_policy.counts explicitly"
        )
    counts: dict[str, int] = {}
    for role, value in raw.items():
        normalized = role_key(str(role))
        if not normalized:
            raise RequiredRolePolicyError(f"Required role name is blank: {role!r}")
        try:
            count = int(value)
        except (TypeError, ValueError) as exc:
            raise RequiredRolePolicyError(f"Invalid required role count for {role}: {value}") from exc
        if count < 1:
            raise RequiredRolePolicyError(f"Required role count must be positive for {role}: {value}")
        if normalized in counts:
            raise RequiredRolePolicyError(f"Required role is declared more than once: {normalized}")
        counts[normalized] = count
    if counts.get("main") != 1:
        raise RequiredRolePolicyError("RequiredRolePolicy must declare exactly one main image")
    if set(counts) != {"main", "scene", "size", "func"}:
        raise RequiredRolePolicyError(
            "RequiredRolePolicy must declare only main, scene, size, and func"
        )
    category_id = str(getattr(plugin, "category_id", "") or "")
    raw_policy = json.dumps(
        {"category_id": category_id, "counts": counts},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return RequiredRolePolicy(
        category_id=category_id,
        counts=counts,
        policy_id=hashlib.sha256(raw_policy.encode("utf-8")).hexdigest(),
    )
