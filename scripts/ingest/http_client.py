"""수집 HTTP 클라이언트. 구현 설정이며 공식 API 제한이 아니다."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import requests

DEFAULT_TIMEOUT_SECONDS = 15
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1.0, 2.0)
DEFAULT_MAX_RESPONSE_BYTES = 8_000_000
STREAM_CHUNK_SIZE = 65_536
PRODUCTION_SLEEP: Callable[[float], None] = time.sleep

SleepFn = Callable[[float], None]
TransportFn = Callable[..., Any]


class HttpBudgetExhausted(RuntimeError):
    def __init__(self) -> None:
        super().__init__("http_budget_exhausted")


class ResponseTooLarge(RuntimeError):
    def __init__(self) -> None:
        super().__init__("response_too_large")


class HttpStatusError(RuntimeError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"http_status_{status}")


class HttpRequestFailed(RuntimeError):
    def __init__(self, kind: str = "request_failed") -> None:
        self.kind = kind
        super().__init__(kind)


def _default_transport(*args: Any, **kwargs: Any) -> Any:
    kwargs.setdefault("stream", True)
    return requests.get(*args, **kwargs)


@dataclass
class HttpClient:
    budget: int
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_attempts: int = MAX_ATTEMPTS
    sleep: SleepFn = field(default=PRODUCTION_SLEEP)
    transport: TransportFn | None = None
    request_count: int = 0

    def remaining(self) -> int:
        return max(0, self.budget - self.request_count)

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[Any, int, int]:
        """JSON을 반환한다. query·본문·키는 예외에 넣지 않는다.

        Returns:
            (payload, http_status, response_bytes)
        """
        last_status: int | None = None
        for attempt in range(1, self.max_attempts + 1):
            if self.request_count >= self.budget:
                raise HttpBudgetExhausted()
            self.request_count += 1
            response: Any = None
            failure: str | None = None
            try:
                try:
                    sender = self.transport or _default_transport
                    response = sender(
                        url,
                        params=params,
                        headers=headers,
                        timeout=self.timeout_seconds,
                        allow_redirects=False,
                        stream=True,
                    )
                except requests.Timeout:
                    failure = "timeout"
                except requests.RequestException:
                    failure = "request_failed"
                if failure is not None:
                    raise HttpRequestFailed(failure)

                status = int(getattr(response, "status_code", 0) or 0)
                last_status = status
                if status in RETRYABLE_STATUSES:
                    if attempt >= self.max_attempts:
                        raise HttpStatusError(status)
                    backoff_index = min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)
                    self.sleep(RETRY_BACKOFF_SECONDS[backoff_index])
                    continue
                if status == 403 or status >= 400:
                    raise HttpStatusError(status)
                payload, size = _read_limited_json(response, self.max_response_bytes)
                return payload, status, size
            finally:
                closer = getattr(response, "close", None) if response is not None else None
                if callable(closer):
                    closer()

        raise HttpStatusError(last_status or 0)


def _header_content_length(headers: Any) -> int | None:
    if headers is None or not hasattr(headers, "get"):
        return None
    raw = headers.get("Content-Length")
    if raw is None:
        raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _read_limited_json(response: Any, max_bytes: int) -> tuple[Any, int]:
    declared = _header_content_length(getattr(response, "headers", None))
    if declared is not None and declared > max_bytes:
        raise ResponseTooLarge()

    iterator = getattr(response, "iter_content", None)
    if not callable(iterator):
        raise HttpRequestFailed("non_json")

    chunks: list[bytes] = []
    size = 0
    too_large = False
    read_failed = False
    try:
        for chunk in iterator(chunk_size=STREAM_CHUNK_SIZE):
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                raise ResponseTooLarge()
            chunks.append(chunk)
    except ResponseTooLarge:
        too_large = True
    except Exception:
        read_failed = True
    if too_large:
        raise ResponseTooLarge()
    if read_failed:
        raise HttpRequestFailed("request_failed")

    parsed_ok = False
    payload: Any = None
    try:
        payload = json.loads(b"".join(chunks).decode("utf-8"))
        parsed_ok = True
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        parsed_ok = False
    if not parsed_ok:
        raise HttpRequestFailed("non_json")
    return payload, size
