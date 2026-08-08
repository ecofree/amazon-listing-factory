from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path) -> Any:
    json_path = Path(path)
    try:
        return json.loads(json_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"Could not read JSON file {json_path}: {type(exc).__name__}: {exc}") from exc


def write_json(path: str | Path, data: Any) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    _atomic_write_text(out, text)


def read_jsonl(path: str | Path) -> list[Any]:
    source = Path(path)
    rows: list[Any] = []
    for line_number, line in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not read JSONL row {line_number} in {source}: {exc}") from exc
    return rows


def write_jsonl(path: str | Path, rows: Iterable[Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    _atomic_write_text(out, text)


def write_csv(path: str | Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=str(out.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fieldnames})
        replace_file_with_retries(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()


def write_bytes_atomic(path: str | Path, data: bytes) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=str(out.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        replace_file_with_retries(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()


def safe_path_component(value: Any, *, fallback: str = "item", max_length: int = 120) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-_.")
    if cleaned in {"", ".", ".."}:
        cleaned = fallback
    return cleaned[:max_length]


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        replace_file_with_retries(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def replace_file_with_retries(src: Path, dst: Path) -> None:
    last_exc: OSError | None = None
    for attempt in range(6):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            last_exc = exc
            time.sleep(0.05 * (attempt + 1))
    if last_exc is not None:
        raise last_exc


def load_env(
    path: str | Path | None,
    *,
    override: bool = False,
    only_keys: set[str] | None = None,
) -> dict[str, str]:
    if not path:
        return {}
    env_path = Path(path)
    values: dict[str, str] = {}
    duplicate_keys: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if only_keys is not None and key not in only_keys:
            continue
        value = value.strip().strip('"').strip("'")
        if key in values and values[key] != value:
            duplicate_keys[key] = f"{values[key]!r} != {value!r}"
        values[key] = value
        if override:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)
    if duplicate_keys:
        details = ", ".join(f"{key}: {value}" for key, value in sorted(duplicate_keys.items()))
        raise ValueError(f"Conflicting duplicate environment keys in {env_path}: {details}")
    return values


@contextmanager
def temporary_environ(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
