from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .simple_yaml import load_yaml


def load_yaml_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = load_yaml(path)
    return data if isinstance(data, dict) else {}


def deep_merge(base: dict[str, Any], overlay: dict[str, Any], *, _depth: int = 0) -> dict[str, Any]:
    if _depth > 50:
        raise ValueError("Configuration nesting is too deep to merge safely")
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value, _depth=_depth + 1)
        else:
            result[key] = deepcopy(value)
    return result
