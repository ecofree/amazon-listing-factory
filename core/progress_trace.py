from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .io import utc_now


PROGRESS_TRACE_SCHEMA_VERSION = "progress-v1"
PROGRESS_TRACE_ARTIFACT = "progress_v1.jsonl"
_LOCK = threading.RLock()


def record_progress(job_dir: str | Path, event: str, **fields: Any) -> None:
    row = {
        "schema_version": PROGRESS_TRACE_SCHEMA_VERSION,
        "ts": utc_now(),
        "event": str(event),
        **{key: value for key, value in fields.items() if value not in (None, "")},
    }
    path = Path(job_dir) / "reports" / PROGRESS_TRACE_ARTIFACT
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
