"""Compact category and audience fact context for visual planning."""

from __future__ import annotations

from typing import Any


_TEXT_FIELDS = ("primary_setting", "buyer", "user")
_LIST_FIELDS = ("required_cues", "allowed_alternates", "avoid")


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _items(value: Any, limit: int = 4) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        cleaned = _text(item)
        if cleaned:
            result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def visual_context(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Return bounded context data without making it a new validation gate."""

    raw = policy.get("visual_context") if isinstance(policy, dict) else None
    if not isinstance(raw, dict):
        return {}
    result: dict[str, Any] = {}
    for field in _TEXT_FIELDS:
        value = _text(raw.get(field))
        if value:
            result[field] = value
    for field in _LIST_FIELDS:
        values = _items(raw.get(field))
        if values:
            result[field] = values
    return result


def format_visual_context(
    policy: dict[str, Any] | None,
    *,
    role: str = "",
    max_chars: int = 720,
) -> str:
    """Format context once for a final image prompt; size images do not need it."""

    if role == "size":
        return ""
    context = visual_context(policy)
    if not context:
        return ""
    labels = (
        ("primary_setting", "setting"),
        ("buyer", "buyer"),
        ("user", "user"),
        ("required_cues", "cues"),
        ("allowed_alternates", "alternates"),
        ("avoid", "avoid"),
    )
    parts: list[str] = []
    for field, label in labels:
        value = context.get(field)
        if isinstance(value, list):
            value = ", ".join(value)
        part = f"{label}={value}"
        if value and len("Category context: " + "; ".join([*parts, part])) <= max_chars:
            parts.append(part)
    return "Category context: " + "; ".join(parts) if parts else ""


def planner_visual_context_instruction(
    policy: dict[str, Any] | None,
    *,
    max_chars: int = 980,
) -> str:
    """Give the planner usable context without duplicating the full policy."""

    instruction = "Use child facts for age and buyer suitability; category defaults suggest context, not product claims. Design the US setting yourself."
    heading = "CATEGORY CONTEXT (DESIGN GUIDANCE)\n"
    context = format_visual_context(policy, max_chars=max_chars - len(instruction) - len(heading) - 1)
    if not context:
        return ""
    return heading + context + "\n" + instruction
