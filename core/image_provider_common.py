from __future__ import annotations

import os
import random
import re
import threading
import time
import urllib.error
from http.client import IncompleteRead
from contextlib import contextmanager
from pathlib import Path

from .image_prompt_compiler import assert_prompt_contract

class ImageGenerationError(RuntimeError):
    pass


class PromptCompileError(ImageGenerationError):
    pass


class CandidateCommitError(ImageGenerationError):
    """Local atomic-commit failure; retry the role without spending another provider."""


class ProviderFailure(ImageGenerationError):
    failure_code = "provider_content_failure"
    status = "content_failure"

    def __init__(self, provider_name: str, message: str) -> None:
        super().__init__(message)
        self.provider_name = str(provider_name or "unknown")


class ProviderTransportError(ProviderFailure):
    failure_code = "provider_transport_failure"

    def __init__(
        self,
        provider_name: str,
        message: str,
        *,
        status: str = "transport_failure",
        ambiguous: bool = False,
    ) -> None:
        super().__init__(provider_name, message)
        self.status = status if status in {"timeout_failure", "transport_failure"} else "transport_failure"
        self.ambiguous = bool(ambiguous)


class ProviderQueueUnavailable(ProviderFailure):
    """The physical provider is healthy but its bounded local queue is full."""

    failure_code = "provider_queue_unavailable"
    status = "queue_unavailable"


class ProviderContentError(ProviderFailure):
    pass


class ProviderConfigurationError(ProviderFailure):
    failure_code = "local_contract_mismatch"
    status = "configuration_failure"


class ImageGenerationBatchError(ImageGenerationError):
    def __init__(self, message: str, failures: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.failures = [dict(item) for item in failures]
        codes = {str(item.get("failure_code") or "") for item in failures}
        self.failure_code = next(iter(codes)) if len(codes) == 1 else "provider_content_failure"


_DEFAULT_PROVIDER_TIMEOUT_SECONDS = {
    "aicost_gpt_image_2": 420,
}
_DEFAULT_PROVIDER_TIMEOUT_FALLBACK_SECONDS = 420
_MAX_PROVIDER_TIMEOUT_SECONDS = 480
_DEFAULT_PROVIDER_CONCURRENCY = 1
_DEFAULT_VISION_PROVIDER_CONCURRENCY = 3
_PROVIDER_SEMAPHORES: dict[tuple[str, int], threading.BoundedSemaphore] = {}
_PROVIDER_SEMAPHORES_LOCK = threading.Lock()


def assert_imagegen_prompt_contract(prompt: str, provider_name: str) -> None:
    try:
        assert_prompt_contract(prompt)
    except ValueError as exc:
        raise PromptCompileError(
            f"Provider '{provider_name}' received an invalid compiled image prompt: {exc}"
        ) from exc


def provider_timeout_seconds(provider_name: str) -> int:
    specific = (
        os.environ.get(f"AMAZON_FACTORY_PROVIDER_TIMEOUT_SECONDS_{provider_env_suffix(provider_name)}")
        or os.environ.get(f"AMAZON_FACTORY_PROVIDER_TIMEOUT_SECONDS_{provider_name.upper()}")
    )
    value = (
        specific
        or os.environ.get("AMAZON_FACTORY_PROVIDER_TIMEOUT_SECONDS")
        or str(_DEFAULT_PROVIDER_TIMEOUT_SECONDS.get(provider_name, _DEFAULT_PROVIDER_TIMEOUT_FALLBACK_SECONDS))
    )
    try:
        return min(_MAX_PROVIDER_TIMEOUT_SECONDS, max(30, int(value)))
    except ValueError:
        return _DEFAULT_PROVIDER_TIMEOUT_FALLBACK_SECONDS


def provider_attempts(provider_name: str) -> int:
    specific = os.environ.get(f"AMAZON_FACTORY_PROVIDER_ATTEMPTS_{provider_env_suffix(provider_name)}")
    value = specific or os.environ.get("AMAZON_FACTORY_IMAGEGEN_PROVIDER_ATTEMPTS") or "2"
    try:
        return min(2, max(1, int(value)))
    except ValueError:
        return 1


def provider_retry_delay_seconds(provider_name: str, attempt: int) -> float:
    specific = os.environ.get(
        f"AMAZON_FACTORY_PROVIDER_RETRY_DELAY_SECONDS_{provider_env_suffix(provider_name)}"
    )
    value = specific or os.environ.get("AMAZON_FACTORY_IMAGEGEN_RETRY_DELAY_SECONDS") or "10"
    try:
        base = max(0.0, float(value))
    except ValueError:
        base = 10.0
    return min(180.0, base * max(1, attempt)) + min(3.0, random_jitter_seconds())


def image_url_download_attempts() -> int:
    value = os.environ.get("AMAZON_FACTORY_IMAGE_URL_DOWNLOAD_ATTEMPTS", "3")
    try:
        return max(1, min(8, int(value)))
    except ValueError:
        return 3


def image_url_download_retry_delay(attempt: int) -> float:
    value = os.environ.get("AMAZON_FACTORY_IMAGE_URL_DOWNLOAD_RETRY_BASE_SECONDS", "1")
    try:
        base = max(0.0, float(value))
    except ValueError:
        base = 1.0
    return min(20.0, base * attempt) + (0.0 if base == 0 else min(0.5, random_jitter_seconds()))


def random_jitter_seconds() -> float:
    return random.uniform(0.0, 1.0)


def is_transient_imagegen_error(exc: Exception) -> bool:
    return provider_failure_code(exc) == "provider_transport_failure"


def provider_failure_code(exc: Exception) -> str:
    if isinstance(exc, PromptCompileError):
        return "prompt_compile_failed"
    if isinstance(exc, CandidateCommitError):
        return "candidate_commit_failed"
    if isinstance(exc, ProviderFailure):
        return exc.failure_code
    if _structured_content_rejection(exc):
        return "provider_content_failure"
    if _structured_configuration_failure(exc):
        return "local_contract_mismatch"
    if _structured_transport_status(exc):
        return "provider_transport_failure"
    return "provider_content_failure"


def provider_failure_status(exc: Exception) -> str:
    if isinstance(exc, CandidateCommitError):
        return "candidate_commit_failure"
    if isinstance(exc, ProviderFailure):
        return exc.status
    if _structured_content_rejection(exc):
        return "content_failure"
    if _structured_configuration_failure(exc):
        return "configuration_failure"
    transport = _structured_transport_status(exc)
    if transport:
        return transport
    return "content_failure"


def provider_failure_class(exc: Exception) -> str:
    """Classify retry authority, not provider quality.

    Transport, configuration, and provider-output failures belong to physical
    providers and may move to another provider inside the role budget. Only a
    locally compiled prompt/contract failure belongs to the immutable task.
    """
    if isinstance(exc, PromptCompileError):
        return "contract"
    if isinstance(exc, CandidateCommitError):
        return "candidate_commit"
    if isinstance(exc, ProviderConfigurationError):
        return "configuration"
    if isinstance(exc, ProviderQueueUnavailable):
        return "queue"
    if isinstance(exc, ProviderTransportError):
        return "transient"
    return "content"


def normalize_provider_error(provider_name: str, exc: Exception) -> Exception:
    if isinstance(exc, (PromptCompileError, ProviderFailure)):
        return exc
    message = f"{type(exc).__name__}: {exc}"
    if _structured_content_rejection(exc):
        return ProviderContentError(provider_name, message)
    if _structured_configuration_failure(exc):
        return ProviderConfigurationError(provider_name, message)
    status = _structured_transport_status(exc)
    if status:
        return ProviderTransportError(provider_name, message, status=status)
    return ProviderContentError(provider_name, message)


def _structured_transport_status(exc: Exception) -> str:
    if _structured_content_rejection(exc):
        return ""
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            return "timeout_failure"
        if isinstance(current, (IncompleteRead, ConnectionError)):
            return "transport_failure"
        message = str(current).lower().replace("_", " ").replace("-", " ")
        if _terminal_provider_route_failure(message):
            return ""
        if isinstance(current, urllib.error.HTTPError):
            if current.code in {408, 504, 522, 524}:
                return "timeout_failure"
            if current.code in {409, 425, 429} or 500 <= current.code <= 599:
                return "transport_failure"
        if isinstance(current, urllib.error.URLError):
            if isinstance(current.reason, BaseException):
                pending.append(current.reason)
            else:
                return "transport_failure"
        http_status = re.search(r"\bhttp\s+(\d{3})\b", message)
        if http_status:
            status_code = int(http_status.group(1))
            if status_code in {408, 504, 522, 524}:
                return "timeout_failure"
            if status_code in {409, 425, 429} or 500 <= status_code <= 599:
                return "transport_failure"
        if any(marker in message for marker in _TRANSPORT_ERROR_MARKERS):
            return "transport_failure"
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return ""


def _structured_configuration_failure(exc: Exception) -> bool:
    if _structured_content_rejection(exc):
        return False
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        message = str(current).lower().replace("_", " ").replace("-", " ")
        if _terminal_provider_route_failure(message):
            return True
        http_status = re.search(r"\bhttp\s+(400|401|403|404)\b", message)
        if http_status:
            return True
        if isinstance(current, urllib.error.HTTPError) and current.code in {400, 401, 403, 404}:
            return True
        if any(marker in message for marker in ("model not found", "authentication failed", "invalid api key")):
            return True
        if any(marker in message for marker in _TRANSPORT_ERROR_MARKERS):
            return False
        if isinstance(current, urllib.error.URLError) and isinstance(current.reason, BaseException):
            pending.append(current.reason)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return False


def _structured_content_rejection(exc: Exception) -> bool:
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        message = str(current).casefold().replace("_", " ").replace("-", " ")
        if any(marker in message for marker in _CONTENT_REJECTION_MARKERS):
            return True
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return False


def _terminal_provider_route_failure(message: str) -> bool:
    text = str(message or "").casefold()
    return any(marker in text for marker in (
        "model not found",
        "model_not_found",
        "no available channel",
        "no available route",
        "no route",
        "无可用渠道",
        "没有可用渠道",
    ))


_CONTENT_REJECTION_MARKERS = (
    "moderation blocked",
    "rejected by the safety system",
    "image generation user error",
    "content policy",
    "safety policy",
)


_TRANSPORT_ERROR_MARKERS = (
    "service unavailable",
    "internal error",
    "incomplete read",
    "connection pool timed out",
    "failed to acquire connection",
    "timed out",
    "timeout",
    "read timed out",
    "connect timed out",
    # httpx/urllib/OpenSSL often surface these as plain OSError text rather
    # than ConnectionError.  They are transport failures and must be eligible
    # for the role-level provider switch, not misclassified as bad content.
    "ssl eof",
    "ssl: eof",
    "eof occurred in violation of protocol",
    "unexpected eof while reading",
    "remote protocol error",
    "connection reset by peer",
    "connection aborted",
    "broken pipe",
)


def provider_concurrency_limit(provider_name: str) -> int:
    suffix = provider_env_suffix(provider_name)
    specific = os.environ.get(f"AMAZON_FACTORY_PROVIDER_CONCURRENCY_{suffix}")
    is_vision = str(provider_name or "").casefold().startswith("vision_")
    shared = (
        os.environ.get("AMAZON_FACTORY_VISION_PROVIDER_CONCURRENCY")
        if is_vision else os.environ.get("AMAZON_FACTORY_IMAGEGEN_PROVIDER_CONCURRENCY")
    )
    default = _DEFAULT_VISION_PROVIDER_CONCURRENCY if is_vision else _DEFAULT_PROVIDER_CONCURRENCY
    value = specific or shared or str(default)
    try:
        return min(32, max(0, int(value)))
    except ValueError:
        return 0


@contextmanager
def provider_concurrency_slot(provider_name: str, *, deadline: float | None = None):
    """Acquire a provider slot across every local factory process.

    This is intentionally two-layered.  The thread semaphore limits concurrent
    calls inside one CLI job, while the file lease limits the same provider
    across independently launched jobs.  Either layer alone is insufficient on
    Windows: file locks are reentrant for handles in one process, and a Python
    semaphore is invisible to other processes.
    """
    limit = provider_concurrency_limit(provider_name)
    if limit <= 0:
        yield
        return
    effective_deadline = deadline if deadline is not None else time.monotonic() + provider_timeout_seconds(provider_name)
    semaphore = _provider_semaphore(provider_name, limit)
    remaining = effective_deadline - time.monotonic()
    if remaining <= 0 or not semaphore.acquire(timeout=max(0.0, remaining)):
        raise ProviderQueueUnavailable(
            provider_name,
            "Timed out waiting for an in-process provider concurrency slot",
        )
    handle = None
    try:
        while handle is None:
            handle = _try_acquire_provider_slot(provider_name, limit)
            if handle is not None:
                break
            remaining = effective_deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderQueueUnavailable(
                    provider_name,
                    "Timed out waiting for a cross-process provider concurrency slot",
                )
            time.sleep(min(0.1, remaining))
        yield
    finally:
        if handle is not None:
            _release_provider_slot(handle)
        semaphore.release()


def _provider_semaphore(provider_name: str, limit: int) -> threading.BoundedSemaphore:
    key = (str(provider_name).strip(), int(limit))
    with _PROVIDER_SEMAPHORES_LOCK:
        semaphore = _PROVIDER_SEMAPHORES.get(key)
        if semaphore is None:
            semaphore = threading.BoundedSemaphore(limit)
            _PROVIDER_SEMAPHORES[key] = semaphore
        return semaphore


def _provider_slot_directory(provider_name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "runtime" / "provider_slots" / provider_env_suffix(provider_name).casefold()


def _try_acquire_provider_slot(provider_name: str, limit: int):
    directory = _provider_slot_directory(provider_name)
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(limit):
        path = directory / f"slot-{index}.lock"
        handle = path.open("a+b")
        try:
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            _lock_file_nonblocking(handle)
            return handle
        except OSError:
            handle.close()
    return None


def _release_provider_slot(handle) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _lock_file_nonblocking(handle) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def provider_env_suffix(provider_name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", provider_name.upper()).strip("_")
