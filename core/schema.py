from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json
from .paths import SCHEMAS_ROOT


class SchemaValidationError(RuntimeError):
    pass


def validate_file(path: str | Path, schema_name: str) -> None:
    validate_data(read_json(path), schema_name, label=str(path))


def validate_data(data: Any, schema_name: str, *, label: str = "data") -> None:
    try:
        import jsonschema
    except ModuleNotFoundError as exc:
        raise SchemaValidationError("jsonschema is required for runtime schema validation") from exc

    if Path(schema_name).name != schema_name or schema_name in {"", ".", ".."}:
        raise SchemaValidationError(f"Invalid schema name: {schema_name}")
    schema_path = (SCHEMAS_ROOT / schema_name).resolve()
    if SCHEMAS_ROOT.resolve() not in schema_path.parents:
        raise SchemaValidationError(f"Schema path escapes schema root: {schema_name}")
    schema = read_json(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda item: list(item.path))
    if errors:
        details: list[str] = []
        for error in errors[:8]:
            location = ".".join(str(part) for part in error.path) or "<root>"
            details.append(f"{location}: {error.message}")
        suffix = "" if len(errors) <= len(details) else f"; ... {len(errors) - len(details)} more"
        raise SchemaValidationError(
            f"{label} does not match {schema_name}: {len(errors)} validation error(s): "
            + "; ".join(details)
            + suffix
        )
