from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


AMAZON_HOSTS = {
    "US": "www.amazon.com",
    "CA": "www.amazon.ca",
    "MX": "www.amazon.com.mx",
    "UK": "www.amazon.co.uk",
    "DE": "www.amazon.de",
    "FR": "www.amazon.fr",
    "IT": "www.amazon.it",
    "ES": "www.amazon.es",
    "JP": "www.amazon.co.jp",
    "AU": "www.amazon.com.au",
}


@dataclass
class ApifyClient:
    tokens: list[str] | str
    actor_id: str
    marketplace: str = "US"
    poll_seconds: int = 5
    timeout_seconds: int = 300
    _token_index: int = field(default=0, init=False, repr=False)
    _token_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _token_cooldowns: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        raw_tokens = [self.tokens] if isinstance(self.tokens, str) else list(self.tokens)
        self.tokens = [str(token).strip() for token in raw_tokens if str(token).strip()]
        if not self.tokens:
            raise RuntimeError("At least one Apify token is required")

    def _next_token(self) -> str:
        with self._token_lock:
            now = time.time()
            for _ in range(len(self.tokens)):
                token = self.tokens[self._token_index % len(self.tokens)]
                self._token_index += 1
                if self._token_cooldowns.get(token, 0.0) <= now:
                    return token
            token = min(self.tokens, key=lambda item: self._token_cooldowns.get(item, 0.0))
            self._token_index += 1
            return token

    def _mark_token_cooldown(self, token: str, *, seconds: float = 60.0) -> None:
        with self._token_lock:
            self._token_cooldowns[token] = time.time() + max(1.0, seconds)

    def product_url(self, asin: str) -> str:
        host = AMAZON_HOSTS.get((self.marketplace or "US").upper(), "www.amazon.com")
        return f"https://{host}/dp/{asin}?th=1&psc=1"

    def fetch_product(self, asin: str) -> dict[str, Any]:
        items = self.fetch_items(asin)
        if not items:
            raise RuntimeError(f"Apify returned no items for {asin}")
        return items[0]

    def fetch_items(self, asin: str) -> list[dict[str, Any]]:
        payload = {
            "categoryOrProductUrls": [{"url": self.product_url(asin)}],
            "startUrls": [{"url": self.product_url(asin)}],
            "asins": [asin],
        }
        actor_or_task = urllib.parse.quote(self.actor_id, safe="~")
        endpoints = [
            f"https://api.apify.com/v2/acts/{actor_or_task}/runs",
            f"https://api.apify.com/v2/actor-tasks/{actor_or_task}/runs",
        ]
        last_status = 0
        last_body = ""
        for _token_attempt in range(max(1, len(self.tokens))):
            token = self._next_token()
            rate_limited = False
            for endpoint in endpoints:
                status, response = self._post_run(endpoint, payload, token=token)
                if status == 429:
                    last_status = status
                    last_body = str(response)
                    rate_limited = True
                    break
                if status == 404:
                    last_status = status
                    last_body = str(response)
                    continue
                if status >= 400:
                    raise RuntimeError(f"Apify request failed HTTP {status}: {str(response)[:500]}")
                run = response.get("data", {})
                completed = self._wait_for_run(run["id"], token=token)
                if completed.get("status") != "SUCCEEDED":
                    raise RuntimeError(f"Apify run ended with status {completed.get('status')} for {completed.get('id')}")
                dataset_id = completed.get("defaultDatasetId")
                if not dataset_id:
                    return []
                items = self._json_request(f"https://api.apify.com/v2/datasets/{dataset_id}/items?clean=true", token=token)
                return items if isinstance(items, list) else []
            if rate_limited:
                continue
            break
        if last_status == 429:
            raise RuntimeError(f"Apify request failed HTTP 429 after trying available tokens: {last_body[:500]}")
        raise RuntimeError(
            "Apify actor/task was not found. Use an actor name like 'username~actor-name' "
            f"or a valid task id. Last status: {last_status}. {last_body[:500]}"
        )

    def _headers(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self._next_token()}", "Accept": "application/json"}

    def _json_request(
        self,
        url: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        token: str | None = None,
        retry_attempts: int | None = None,
    ) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        attempts = (
            max(1, min(8, int(retry_attempts)))
            if retry_attempts is not None
            else _retry_attempts("AMAZON_FACTORY_APIFY_REQUEST_RETRY_ATTEMPTS", 3)
        )
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            headers = self._headers(token)
            if payload is not None:
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    body = response.read().decode("utf-8", errors="replace")
                return json.loads(body) if body else {}
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code == 429 and token:
                    self._mark_token_cooldown(token, seconds=_retry_after_seconds(exc.headers.get("Retry-After")))
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= attempts:
                    raise
            except urllib.error.URLError as exc:
                last_exc = exc
                if _is_socket_permission_error(exc):
                    raise RuntimeError(f"Apify request blocked by local socket permissions: {exc.reason}") from exc
                if attempt >= attempts:
                    raise
            time.sleep(_request_retry_delay(attempt))
        if last_exc:
            raise last_exc
        return {}

    def _post_run(self, endpoint: str, payload: dict[str, Any], *, token: str) -> tuple[int, Any]:
        last_status = 0
        last_body: Any = ""
        for attempt in range(5):
            try:
                # Endpoint retry owns run-start retry budget; do not nest the
                # request-level 3-attempt loop inside it.
                return 200, self._json_request(
                    endpoint, method="POST", payload=payload, token=token, retry_attempts=1
                )
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_status = exc.code
                last_body = body
                if exc.code == 429:
                    self._mark_token_cooldown(token, seconds=_retry_after_seconds(exc.headers.get("Retry-After")))
                    return exc.code, body
                if exc.code in {500, 502, 503, 504} and attempt < 4:
                    time.sleep(min(2.0, 0.25 * (attempt + 1)))
                    continue
                if exc.code != 402 or "actor-memory-limit-exceeded" not in body:
                    return exc.code, body
                time.sleep(min(20 * (attempt + 1), 90))
            except urllib.error.URLError as exc:
                last_status = 599
                last_body = str(exc.reason)
                if attempt < 4:
                    time.sleep(min(2.0, 0.25 * (attempt + 1)))
                    continue
                return last_status, last_body
        return last_status, last_body

    def _wait_for_run(self, run_id: str, *, token: str) -> dict[str, Any]:
        deadline = time.time() + self.timeout_seconds
        while True:
            try:
                response = self._json_request(f"https://api.apify.com/v2/actor-runs/{run_id}", token=token)
            except urllib.error.HTTPError as exc:
                if exc.code != 404 or time.time() >= deadline:
                    raise
                time.sleep(self.poll_seconds)
                continue
            run = response.get("data", {})
            if run.get("status") in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
                return run
            if time.time() >= deadline:
                raise RuntimeError(f"Timed out waiting for Apify run {run_id}")
            time.sleep(self.poll_seconds)


def _retry_after_seconds(value: str | None) -> float:
    try:
        return min(300.0, max(1.0, float(value or "")))
    except (TypeError, ValueError):
        return 60.0


def _retry_attempts(env_name: str, default: int) -> int:
    try:
        return max(1, min(8, int(float(os.environ.get(env_name) or default))))
    except (TypeError, ValueError):
        return default


def _request_retry_delay(attempt: int) -> float:
    return min(8.0, 0.5 * (2 ** max(0, attempt - 1)))


def _is_socket_permission_error(exc: BaseException) -> bool:
    errno = getattr(exc, "errno", None)
    winerror = getattr(exc, "winerror", None)
    if errno == 10013 or winerror == 10013:
        return True
    reason = getattr(exc, "reason", None)
    if reason is not None and _is_socket_permission_error(reason):
        return True
    cause = getattr(exc, "__cause__", None)
    if cause is not None and _is_socket_permission_error(cause):
        return True
    text = str(exc)
    return "WinError 10013" in text or "10013" in text and "socket" in text.lower()
