"""Compact category and audience fact context for visual planning."""

from __future__ import annotations

from typing import Any


_TEXT_FIELDS = ("primary_setting", "buyer", "user")
_LIST_FIELDS = ("required_cues", "allowed_alternates", "avoid")


def _text(value: Any, limit: int = 220) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit].strip()


def _items(value: Any, limit: int = 4, item_limit: int = 150) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        cleaned = _text(item, item_limit)
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
        if value:
            parts.append(f"{label}={value}")
    text = "Program visual context: " + "; ".join(parts)
    return text[:max_chars].rstrip(" ;")


def planner_visual_context_instruction(
    policy: dict[str, Any] | None,
    *,
    max_chars: int = 980,
) -> str:
    """Give the planner usable context without duplicating the full policy."""

    context = format_visual_context(policy, max_chars=max_chars - 190)
    if not context:
        return ""
    return (
        "CATEGORY AND AUDIENCE CONTEXT (FACT INPUT)\n"
        f"{context}\n"
        "Use this to understand the buyer and plausible setting. Choose the visual expression yourself, "
        "keep it believable for the US market, and do not turn context into a product claim or copy."
    )[:max_chars]
