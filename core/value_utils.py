from __future__ import annotations

import os
from typing import Any, Iterable


DEFAULT_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
DEFAULT_FALSE_VALUES = {"0", "false", "no", "n", "off"}


def truthy(value: Any, *, extra_true: Iterable[str] = ()) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if value in (None, ""):
        return False
    allowed = DEFAULT_TRUE_VALUES | {str(item).strip().lower() for item in extra_true if str(item).strip()}
    return str(value).strip().lower() in allowed


def env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in DEFAULT_TRUE_VALUES:
        return True
    if raw in DEFAULT_FALSE_VALUES:
        return False
    return default


def env_int(*names: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    for name in names:
        raw = os.environ.get(name, "")
        if not raw:
            continue
        try:
            value = int(str(raw).strip())
        except ValueError:
            continue
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value
    return default
