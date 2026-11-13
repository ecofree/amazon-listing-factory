from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str | Path) -> Any:
    """Use the required PyYAML safe loader; no separate subset parser authority."""
    return yaml.load(Path(path).read_text(encoding="utf-8-sig"), Loader=yaml.CSafeLoader) or {}
