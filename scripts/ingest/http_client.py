"""수집 HTTP 클라이언트. 구현 설정이며 공식 API 제한이 아니다."""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import timezone
from email.utils import format_datetime, parsedate_to_datetime
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
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_RFC850_DATE = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
    r"[0-9]{2}-[A-Za-z]{3}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT\Z"
)
_ASCTIME_DATE = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Za-z]{3} "
    r"(?: [1-9]|[12][0-9]|3[01]) [0-9]{2}:[0-9]{2}:[0-9]{2} [0-9]{4}\Z"
)


def _safe_header(headers: Any, name: str, *, request_id: bool = False) -> str:
    if headers is None or not hasattr(headers, "get"):
        return "-"
    raw = headers.get(name)
    if not isinstance(raw, str):
        return "-"
    if request_id:
        return raw if _SAFE_REQUEST_ID.fullmatch(raw) else "-"
    if re.fullmatch(r"[0-9]{1,6}", raw):
        return raw
    # Parse only valid HTTP-date shapes and log a canonical UTC timestamp.
    # A round-trip or recognized obsolete form keeps attacker text out of logs.
    if len(raw) <= 64:
        try:
            parsed = parsedate_to_datetime(raw)
            utc = (
                parsed.replace(tzinfo=timezone.utc)
                if parsed.tzinfo is None
                else parsed.astimezone(timezone.utc)
            )
            canonical = format_datetime(utc, usegmt=True)
            if canonical[:3] == raw[:3] and (
                canonical == raw
                or _RFC850_DATE.fullmatch(raw)
                or _ASCTIME_DATE.fullmatch(raw)
            ):
                return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError, OverflowError):
            pass
    return "present"


def _log_http_status(
    response: Any, *, source_id: str | None, page_num: int | None,
    attempt: int, status: int, params: Mapping[str, Any] | None,
    sensitive_values: tuple[str, ...] = (),
) -> None:
    headers = getattr(response, "headers", None)
    source = source_id if source_id in {"youthcenter_policy", "youthcenter_content", "seoul_reservation"} else "-"
    page = page_num if isinstance(page_num, int) and 1 <= page_num <= 100000 else "-"
    secret_values = sensitive_values + tuple(
        str(value) for key, value in (params or {}).items()
        if ("key" in key.lower() or "token" in key.lower())
        and value is not None and str(value)
    )
    request_id = next(
        (value for name in ("X-Request-ID", "X-Correlation-ID", "CF-Ray")
         if (value := _safe_header(headers, name, request_id=True)) != "-"),
        "-",
    )
    retry_after = _safe_header(headers, "Retry-After")
    if any(secret in request_id for secret in secret_values):
        request_id = "-"
    if any(secret in retry_after for secret in secret_values):
        retry_after = "-"
    print(
        f"ingest_http source={source} page={page} attempt={attempt} "
        f"status={status} retry_after={retry_after} "
        f"request_id={request_id}",
        file=sys.stderr,
    )


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
    last_diagnostic: dict[str, Any] = field(default_factory=dict, init=False)

    def remaining(self) -> int:
        return max(0, self.budget - self.request_count)

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        source_id: str | None = None,
        page_num: int | None = None,
        sensitive_values: tuple[str, ...] = (),
    ) -> tuple[Any, int, int]:
        """JSON을 반환한다. query·본문·키는 예외에 넣지 않는다.

        Returns:
            (payload, http_status, response_bytes)
        """
        self.last_diagnostic = {"stage": "http_request", "response_bytes": 0}
        last_status: int | None = None
        for attempt in range(1, self.max_attempts + 1):
            if self.request_count >= self.budget:
                self.last_diagnostic["error_code"] = "http_budget_exhausted"
                raise HttpBudgetExhausted()
            self.request_count += 1
            for key in ('http_status', 'error_code', 'declared_bytes', 'json_error_position'):
                self.last_diagnostic.pop(key, None)
            self.last_diagnostic.update(stage="http_request", attempt=attempt, response_bytes=0)
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
                    self.last_diagnostic["error_code"] = failure
                    raise HttpRequestFailed(failure)

                status = int(getattr(response, "status_code", 0) or 0)
                last_status = status
                self.last_diagnostic.update(stage="http_status", http_status=status)
                if status >= 400:
                    _log_http_status(
                        response, source_id=source_id, page_num=page_num,
                        attempt=attempt, status=status, params=params,
                        sensitive_values=sensitive_values,
                    )
                if status in RETRYABLE_STATUSES:
                    if attempt >= self.max_attempts:
                        self.last_diagnostic["error_code"] = "http_status_error"
                        raise HttpStatusError(status)
                    backoff_index = min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)
                    self.sleep(RETRY_BACKOFF_SECONDS[backoff_index])
                    continue
                if status == 403 or status >= 400:
                    self.last_diagnostic["error_code"] = "http_status_error"
                    raise HttpStatusError(status)
                payload, size = _read_limited_json(response, self.max_response_bytes, diagnostic=self.last_diagnostic)
                self.last_diagnostic.update(stage="http_complete", response_bytes=size)
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


def _read_limited_json(response: Any, max_bytes: int, *, diagnostic: dict | None = None) -> tuple[Any, int]:
    diagnostic = {} if diagnostic is None else diagnostic
    diagnostic["stage"] = "body_read"
    declared = _header_content_length(getattr(response, "headers", None))
    if declared is not None and declared > max_bytes:
        diagnostic.update(error_code="response_too_large", declared_bytes=declared)
        raise ResponseTooLarge()

    iterator = getattr(response, "iter_content", None)
    if not callable(iterator):
        diagnostic["error_code"] = "non_json"
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
            diagnostic["response_bytes"] = size
            if size > max_bytes:
                raise ResponseTooLarge()
            chunks.append(chunk)
    except ResponseTooLarge:
        too_large = True
    except Exception:
        read_failed = True
    if too_large:
        diagnostic["error_code"] = "response_too_large"
        raise ResponseTooLarge()
    if read_failed:
        diagnostic["error_code"] = "request_failed"
        raise HttpRequestFailed("request_failed")

    parsed_ok = False
    payload: Any = None
    diagnostic["stage"] = "json_decode"
    try:
        payload = json.loads(b"".join(chunks).decode("utf-8"))
        parsed_ok = True
    except UnicodeDecodeError:
        diagnostic["error_code"] = "invalid_utf8"
    except json.JSONDecodeError as exc:
        diagnostic.update(error_code="invalid_json", json_error_position=exc.pos)
    except (ValueError, TypeError):
        diagnostic["error_code"] = "non_json"
        parsed_ok = False
    if not parsed_ok:
        raise HttpRequestFailed("non_json")
    return payload, size
