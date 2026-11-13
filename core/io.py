from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import time
import threading
from types import MappingProxyType
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


def parse_json_object_response(text: str, *, label: str = "JSON response") -> dict[str, Any]:
    """Parse one JSON object from a provider response without trusting prose."""
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    decoder = json.JSONDecoder()
    start = raw.find("{")
    if start < 0:
        raise ValueError(f"{label} does not contain a JSON object")
    try:
        value, end = decoder.raw_decode(raw[start:])
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    trailing = raw[start + end:].strip()
    if trailing.startswith("{"):
        raise ValueError(f"{label} contains more than one JSON object")
    return value


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


_FROZEN_ENV = None
_ENV_LOCK = threading.RLock()


def read_env_values(path: str | Path | None, *, only_keys: set[str] | None = None) -> dict[str,str]:
    if not path:
        return {}
    env_path = Path(path)
    values: dict[str, str] = {}
    locations: dict[str, int] = {}
    duplicate_keys: dict[str, tuple[int, int]] = {}
    if not env_path.exists():
        return values
    for line_number, line in enumerate(env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if only_keys is not None and key not in only_keys:
            continue
        value = value.strip().strip('"').strip("'")
        if key in values and values[key] != value:
            duplicate_keys[key] = (locations[key], line_number)
        locations.setdefault(key, line_number)
        values[key] = value
    if duplicate_keys:
        details = ", ".join(f"{key} (lines {first}, {last})" for key, (first, last) in sorted(duplicate_keys.items()))
        raise ValueError(f"Conflicting duplicate environment keys in {env_path}: {details}")
    return values


def environment_values(*paths):
    """One config precedence for local preflight and the frozen production context."""
    if _FROZEN_ENV is not None:return dict(_FROZEN_ENV)
    # Business defaults may come from explicit files, not arbitrary inherited shell values.
    prefixes=('AMAZON_FACTORY_','COPY_AI_','DEEPSEEK_','APIFY_','GEMINI_','OCR_','R2_','OCI_','IMAGE_PUBLISH_')
    business=('DEFAULT_','AMAZON_FACTORY_BRAND','AMAZON_FACTORY_MANUFACTURER','AMAZON_FACTORY_COUNTRY_OF_ORIGIN','AMAZON_FACTORY_TEMPLATE_')
    values={key:value for key,value in os.environ.items() if (key.startswith(prefixes) or key.upper() in {'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY'}
        or key.endswith(('_API_KEY','_API_TOKEN','_BEARER_TOKEN'))) and not key.startswith(business)}
    for path in paths:
        if path:values.update(read_env_values(path))
    return values


def load_env(path, *, override=False,only_keys=None):
    if _FROZEN_ENV is not None:
        return {k:v for k,v in _FROZEN_ENV.items() if only_keys is None or k in only_keys}
    values=read_env_values(path,only_keys=only_keys)
    for key,value in values.items():
        if override:os.environ[key]=value
        else:os.environ.setdefault(key,value)
    return values


@contextmanager
def frozen_execution_environment(*paths):
    """One job per interpreter configuration; child threads see the same immutable values."""
    global _FROZEN_ENV
    with _ENV_LOCK:
        if _FROZEN_ENV is not None:raise RuntimeError('Nested production configuration is not allowed')
        previous=dict(os.environ);values=environment_values(*paths)
        try:
            for key in list(os.environ):
                if key.startswith(('DEFAULT_','AMAZON_FACTORY_','COPY_AI_','DEEPSEEK_')) and key not in values:os.environ.pop(key)
            os.environ.update(values)
            os.environ['FACTORY_ENV_REVISION']=hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()
            os.environ['FACTORY_ENV_KEYS']=json.dumps(sorted(values))
            _FROZEN_ENV=MappingProxyType(values)
            yield _FROZEN_ENV
        finally:
            _FROZEN_ENV=None;os.environ.clear();os.environ.update(previous)


def assert_execution_environment():
    """Child interpreters inherit the same seal; reject late configuration mutation."""
    expected=os.environ.get('FACTORY_ENV_REVISION')
    if not expected:return  # Pure local diagnostics may run without a production environment.
    keys=json.loads(os.environ['FACTORY_ENV_KEYS'])
    current={key:os.environ.get(key) for key in keys}
    if hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()!=expected:
        raise ValueError('Frozen execution environment changed before transport admission')


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
