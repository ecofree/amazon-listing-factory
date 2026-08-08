from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_store_path() -> Path:
    raw = os.environ.get("AMAZON_FACTORY_PROVIDER_SMOKE_STORE", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "runtime" / "provider_smoke_results.json"


def registry_fingerprint(entry: dict[str, Any]) -> str:
    relevant = {
        key: entry.get(key)
        for key in (
            "name",
            "family",
            "scope",
            "scopes",
            "protocol",
            "base_url",
            "url",
            "model",
            "api_type",
            "capabilities",
            "protocol_profile",
        )
    }
    raw = json.dumps(relevant, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_smoke_results(path: str | Path | None = None) -> list[dict[str, Any]]:
    target = Path(path) if path else default_store_path()
    if not target.exists():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return []
    rows = payload.get("results") if isinstance(payload, dict) else payload
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def write_smoke_results(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "results": rows,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def upsert_smoke_result(result: dict[str, Any], path: str | Path | None = None) -> None:
    target = Path(path) if path else default_store_path()
    rows = read_smoke_results(target)
    marker = (str(result.get("provider") or ""), str(result.get("scope") or ""))
    kept = [
        row
        for row in rows
        if (str(row.get("provider") or ""), str(row.get("scope") or "")) != marker
    ]
    kept.append(result)
    write_smoke_results(target, kept)


def smoke_errors_for_entries(entries: list[Any], *, path: str | Path | None = None) -> list[dict[str, str]]:
    rows = read_smoke_results(path)
    errors: list[dict[str, str]] = []
    for entry in entries:
        raw = getattr(entry, "raw", {}) if not isinstance(entry, dict) else entry
        if str(raw.get("smoke_required") or "").strip().lower() not in {"1", "true", "yes", "on"}:
            continue
        name = str(getattr(entry, "name", "") or raw.get("name") or "")
        scopes = getattr(entry, "scopes", None) or raw.get("scopes") or raw.get("scope") or []
        if isinstance(scopes, str):
            scopes = [scopes]
        fingerprint = registry_fingerprint(raw)
        for scope in [str(scope or "").strip() for scope in scopes if str(scope or "").strip()]:
            found = next(
                (
                    row
                    for row in rows
                    if str(row.get("provider") or "") == name
                    and str(row.get("scope") or "") == scope
                    and str(row.get("registry_fingerprint") or "") == fingerprint
                    and str(row.get("status") or "") == "passed"
                ),
                None,
            )
            if found is None:
                errors.append({"error": f"api_registry {name}: missing passed smoke result for {scope}"})
    return errors
