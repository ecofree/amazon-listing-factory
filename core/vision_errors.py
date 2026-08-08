from __future__ import annotations

from typing import Any


class VisionQAError(RuntimeError):
    pass


class VisionRequestError(VisionQAError):
    def __init__(
        self,
        scope: str,
        failure_kind: str,
        message: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.scope = str(scope or "unknown")
        self.failure_kind = str(failure_kind or "unknown_failure")
        self.metadata = dict(metadata or {})
