from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json, write_json
from .product_family import read_product_family
from .status import input_revision_id


RUN_SCOPE_SCHEMA_VERSION = "run-scope-v5"
RUN_SCOPE_ARTIFACT = "run_scope_v5.json"


class RunScopeError(RuntimeError):
    pass


def ensure_run_scope(
    *, job_dir: str | Path, limit: int = 0, production: bool = False,
) -> dict[str, Any]:
    job_path = Path(job_dir).resolve()
    reports = job_path / "reports"
    path = reports / RUN_SCOPE_ARTIFACT
    legacy = reports / "run_scope_v4.json"
    if not path.is_file() and legacy.is_file():
        raise RunScopeError("RunScopeV4 is retired; create a new job for RunScopeV5")
    family = read_product_family(job_path)
    if path.is_file():
        scope = read_run_scope(job_path)
        if production and scope.get("mode") != "production":
            raise RunScopeError("Production requires a full-family RunScopeV5; create a new production job")
        return scope
    if production and (family.get("source") or {}).get("child_fetch_errors"):
        raise RunScopeError("Production requires a complete ProductFamilyV3; rerun fetch before creating RunScopeV5")
    children = [str(row["asin"]) for row in family["family"]["children"]]
    selected = children if production or limit <= 0 else children[:limit]
    if not selected:
        raise RunScopeError("RunScopeV5 has no selected children")
    inventory = _family_inventory(family, selected_children=set(selected))
    inventory_fingerprint = input_revision_id(inventory)
    selected_sources = {
        child: _reference_source_indexes(row)
        for child, row in ((str(row["asin"]), row) for row in family["family"]["children"])
        if child in set(selected)
    }
    scope = {
        "schema_version": RUN_SCOPE_SCHEMA_VERSION,
        "mode": "production" if production else "debug",
        "selected_children": selected,
        "selected_sources": selected_sources,
        "family_child_count": len(children),
        "family_inventory_fingerprint": inventory_fingerprint,
        "family_complete_required": bool(production),
        "scope_fingerprint": input_revision_id({
            "schema": RUN_SCOPE_SCHEMA_VERSION,
            "mode": "production" if production else "debug",
            "selected_children": selected,
            "selected_sources": selected_sources,
            "family_child_count": len(children),
            "family_inventory_fingerprint": inventory_fingerprint,
        }),
    }
    write_json(path, scope)
    return scope


def read_run_scope(job_dir: str | Path) -> dict[str, Any]:
    path = Path(job_dir) / "reports" / RUN_SCOPE_ARTIFACT
    if not path.is_file():
        raise RunScopeError(f"RunScopeV5 is missing: {path}")
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema_version") != RUN_SCOPE_SCHEMA_VERSION:
        raise RunScopeError(f"Unsupported RunScopeV5: {path}; create a new job")
    children = data.get("selected_children")
    if not isinstance(children, list) or not children or any(not str(child).strip() for child in children):
        raise RunScopeError("RunScopeV5 has invalid selected_children")
    sources = data.get("selected_sources")
    if not isinstance(sources, dict):
        raise RunScopeError("RunScopeV5 has invalid selected_sources")
    if set(str(child) for child in children) != set(str(child) for child in sources):
        raise RunScopeError("RunScopeV5 selected_sources must match selected_children")
    family = read_product_family(Path(job_dir))
    selected = {str(child) for child in children}
    expected_inventory = input_revision_id(_family_inventory(family, selected_children=selected))
    if data.get("family_inventory_fingerprint") != expected_inventory:
        raise RunScopeError(
            "RunScopeV5 no longer matches ProductFamily membership/reference inventory; create a new job"
        )
    family_by_asin = {
        str(row.get("asin") or ""): row
        for row in family.get("family", {}).get("children") or []
        if isinstance(row, dict)
    }
    for child in selected:
        row = family_by_asin.get(child)
        if row is None:
            raise RunScopeError(f"RunScopeV5 child is no longer present: {child}")
        indexes = sources.get(child)
        if not isinstance(indexes, list):
            raise RunScopeError(f"RunScopeV5 selected_sources is invalid for {child}")
        available = set(_reference_source_indexes(row))
        try:
            requested = {int(value) for value in indexes}
        except (TypeError, ValueError) as exc:
            raise RunScopeError(f"RunScopeV5 source index is invalid for {child}") from exc
        if not requested.issubset(available):
            raise RunScopeError(f"RunScopeV5 references a missing source index for {child}")
    return data


def scoped_children(job_dir: str | Path) -> list[str]:
    return [str(child) for child in read_run_scope(job_dir)["selected_children"]]


def scoped_child_set(job_dir: str | Path) -> set[str]:
    return set(scoped_children(job_dir))


def scoped_family_children(family: dict[str, Any], job_dir: str | Path) -> list[dict[str, Any]]:
    selected = scoped_child_set(job_dir)
    return [row for row in family["family"]["children"] if str(row.get("asin") or "") in selected]


def row_in_scope(job_dir: str | Path, row: dict[str, Any]) -> bool:
    scope = read_run_scope(job_dir)
    child = str(row.get("child") or "")
    if child not in set(str(value) for value in scope["selected_children"]):
        return False
    indexes = scope.get("selected_sources", {}).get(child)
    if not indexes:
        return False
    try:
        return int(row.get("index", row.get("source_index"))) in {int(value) for value in indexes}
    except (TypeError, ValueError):
        return False


def scope_input_revision(job_dir: str | Path) -> str:
    scope = read_run_scope(job_dir)
    return input_revision_id({
        "schema": scope.get("schema_version"),
        "fingerprint": scope.get("scope_fingerprint"),
        "selected_children": scope.get("selected_children"),
        "selected_sources": scope.get("selected_sources"),
        "mode": scope.get("mode"),
    })


def _reference_source_indexes(child: dict[str, Any]) -> list[int]:
    rows = child.get("reference_images") if isinstance(child.get("reference_images"), list) else []
    return list(range(len(rows)))


def _family_inventory(
    family: dict[str, Any], *, selected_children: set[str] | None = None,
) -> dict[str, Any]:
    return {
        "parent_asin": str(family.get("family", {}).get("parent_asin") or ""),
        "children": [
            {
                "asin": str(row.get("asin") or ""),
                "reference_sources": _reference_source_inventory(row),
            }
            for row in family.get("family", {}).get("children") or []
            if isinstance(row, dict)
            and (
                selected_children is None
                or str(row.get("asin") or "") in selected_children
            )
        ],
    }


def _reference_source_inventory(child: dict[str, Any]) -> list[str]:
    rows = child.get("reference_images") if isinstance(child.get("reference_images"), list) else []
    inventory: list[str] = []
    for item in rows:
        if isinstance(item, dict):
            inventory.append(str(item.get("url") or item.get("media_location") or ""))
        else:
            inventory.append(str(item or ""))
    return inventory
