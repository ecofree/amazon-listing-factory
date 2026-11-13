from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from copy import deepcopy
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
        "replaceable_staging": _staging_slots(image_config.get("replaceable_staging")),
        "forbidden_additions": _forbidden_addition_list(image_config.get("forbidden_additions")),
        "role_specific_rules": _role_rules(image_config.get("role_specific_rules")),
        "template_image_role_order": order,
        "recovery_fact_policy": config.get('recovery_fact_policy',{}),
    }
    # These fields are executable visual context, not planner-owned decoration.
    # Keep them in the same policy projection so manifest changes reach both the
    # planner and every current ImageTask instead of remaining inert metadata.
    visual_context = image_config.get("visual_context")
    if isinstance(visual_context, dict):
        policy["visual_context"] = visual_context
    role_visual_direction = image_config.get("role_visual_direction")
    if isinstance(role_visual_direction, dict):
        policy["role_visual_direction"] = role_visual_direction
    policy["policy_id"] = hashlib.sha256(json.dumps(policy, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return policy


ROLE_POLICY_FIELDS=('role_specific_rules','role_visual_direction')


def scope_image_policy(policy: dict, roles) -> dict:
    """Only explicitly role-keyed maps narrow; unknown/shared constraints stay global."""
    families={str(role).split('_',1)[0] for role in roles}
    known={'main','scene','func','size'}
    if families-known:raise RequiredRolePolicyError('Invalid policy role scope')
    result=deepcopy(policy);had_id=result.pop('policy_id',None)
    for field in ROLE_POLICY_FIELDS:
        mapping=policy.get(field)
        if mapping is None:mapping={}
        result[field]=({key:deepcopy(value) for key,value in mapping.items() if key in families or key not in known}
                       if isinstance(mapping,dict) else deepcopy(mapping))
    if had_id is not None:
        result['policy_id']=hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
    return result


def _staging_slots(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    fields = {'target_id', 'physical_scope', 'roles', 'environment_modes', 'non_sold_required'}
    if not isinstance(value, list):
        raise RequiredRolePolicyError('replaceable_staging requires typed non-sold target slots')
    seen, slots = set(), []
    for row in value:
        if (not isinstance(row, dict) or set(row) != fields
                or not isinstance(row['target_id'], str) or not re.fullmatch(r'[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*', row['target_id'])
                or row['target_id'] in seen or row['non_sold_required'] is not True
                or not isinstance(row['physical_scope'], str) or not row['physical_scope'].strip()):
            raise RequiredRolePolicyError('Invalid or repeated non-sold staging target')
        for field, allowed in (('roles', {'main', 'scene', 'func', 'size'}),
                               ('environment_modes', {'designed_environment', 'graphic_canvas', 'source_setting'})):
            if (not isinstance(row[field], list) or not row[field] or any(not isinstance(v, str) or v not in allowed for v in row[field])
                    or len(row[field]) != len(set(row[field]))):
                raise RequiredRolePolicyError(f'Invalid staging target {field}')
        seen.add(row['target_id']); slots.append({k: row[k] for k in fields})
    return slots


def authorized_staging_targets(policy: dict[str, Any], sources=(), *, role='', environment_mode='') -> dict[str, dict[str, Any]]:
    """Typed slots apply only to non-sold staging, never to any registered owned/disputed instance."""
    protected=[{'source_id':source['source_id'],'object_id':obj['object_id']}
               for source in sources for obj in source.get('observation',{}).get('objects',[])
               if obj.get('sale_membership') in {'product','included_accessory','unknown'}]
    result = {}
    for slot in _staging_slots(policy.get('replaceable_staging', [])):
        if role and (role.split('_', 1)[0] not in slot['roles']
                     or role.split('_', 1)[0] == 'main' and policy.get('main_image_policy') == 'white_background'):
            continue
        if environment_mode and environment_mode not in slot['environment_modes']:
            continue
        result[slot['target_id']] = {**slot,'protected_instances':protected}
    return result


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
