from __future__ import annotations

from pathlib import Path


FACTORY_ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_ROOT = FACTORY_ROOT / "products"
JOBS_ROOT = FACTORY_ROOT / "jobs"
CONFIGS_ROOT = FACTORY_ROOT / "configs"
SCHEMAS_ROOT = FACTORY_ROOT / "schemas"
DEFAULTS_ROOT = FACTORY_ROOT / "core" / "defaults"
ARCHETYPES_ROOT = FACTORY_ROOT / "core" / "archetypes"


def resolve_job_owned_path(job_dir: str | Path, value: str | Path) -> Path:
    """Resolve one runtime artifact path and reject traversal/symlink escape."""
    root = Path(job_dir).resolve()
    raw = Path(value)
    resolved = (raw if raw.is_absolute() else root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Artifact path escapes the current job: {value}") from exc
    return resolved
