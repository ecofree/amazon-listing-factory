from __future__ import annotations

def role_key(role: str) -> str:
    role = str(role or "").strip().lower().replace("-", "_")
    family = normalize_role_family(role)
    if family:
        return family
    if role.startswith("function"):
        return "func"
    if role.startswith("dimension"):
        return "size"
    return role


def normalize_role_family(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    for family in ("main", "scene", "size", "detail", "func"):
        if normalized.startswith(family):
            return family
    return ""
