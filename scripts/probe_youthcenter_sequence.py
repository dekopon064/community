"""Read-only, bounded policy-to-content HTTP sequence for 403 diagnosis."""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from typing import Callable

from ingest.connectors.youthcenter_content import (
    CONTENT_MAX_RESPONSE_BYTES,
    YouthcenterContentConnector,
)
from ingest.connectors.youthcenter_policy import YouthcenterPolicyConnector
from ingest.http_client import (
    DEFAULT_MAX_RESPONSE_BYTES,
    HttpClient,
    HttpStatusError,
)
from ingest.models import BatchResult, Checkpoint

POLICY_PAGES = 5
PAGE_SIZE = 5
MAX_REQUESTS = 6


def run_sequence(
    policy: YouthcenterPolicyConnector,
    content: YouthcenterContentConnector,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    emit: Callable[[str], None] = print,
) -> int:
    """Return 0 only after five policy pages and one content page are read."""
    if (
        policy.page_size != PAGE_SIZE
        or content.page_size != PAGE_SIZE
        or policy.http.budget != POLICY_PAGES
        or content.http.budget != 1
        or policy.http.max_attempts != 1
        or content.http.max_attempts != 1
    ):
        emit("sequence_probe result=stopped reason=unsafe_probe_configuration")
        return 1

    previous_start: float | None = None
    last_policy_end: float | None = None

    def fetch(connector, source: str, page: int, checkpoint: Checkpoint | None) -> BatchResult | None:
        nonlocal previous_start, last_policy_end
        started = clock()
        started_at = utc_now().astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        since_previous = "-" if previous_start is None else str(round((started - previous_start) * 1000))
        after_policy = (
            str(round((started - last_policy_end) * 1000))
            if source == "youthcenter_content" and last_policy_end is not None
            else "-"
        )
        previous_start = started
        before = connector.http.request_count
        try:
            batch = connector.fetch_batch(checkpoint)
        except HttpStatusError as exc:
            emit(
                f"sequence_probe source={source} page={page} started_at={started_at} "
                f"since_previous_start_ms={since_previous} after_policy_response_ms={after_policy} "
                f"status=failed reason=http_{exc.status} requests={connector.http.request_count - before}"
            )
            return None
        except Exception:
            # Third-party exceptions can embed keys or URLs. Never print them.
            emit(
                f"sequence_probe source={source} page={page} started_at={started_at} "
                f"since_previous_start_ms={since_previous} after_policy_response_ms={after_policy} "
                f"status=failed reason=request_or_parse_failed requests={connector.http.request_count - before}"
            )
            return None
        ended = clock()
        if source == "youthcenter_policy":
            last_policy_end = ended
        emit(
            f"sequence_probe source={source} page={page} started_at={started_at} "
            f"since_previous_start_ms={since_previous} after_policy_response_ms={after_policy} "
            f"status=ok http_status={batch.meta.http_status} items={len(batch.items)} "
            f"duration_ms={round((ended - started) * 1000)} "
            f"requests={connector.http.request_count - before}"
        )
        return batch

    checkpoint: Checkpoint | None = None
    for page in range(1, POLICY_PAGES + 1):
        if page > 1:
            sleep(policy.batch_delay_seconds)
        batch = fetch(policy, "youthcenter_policy", page, checkpoint)
        if batch is None:
            emit(
                f"sequence_probe result=stopped reason=policy_error "
                f"policy_requests={policy.http.request_count} content_requests=0"
            )
            return 1
        if page < POLICY_PAGES and batch.natural_end:
            emit(
                f"sequence_probe result=stopped reason=policy_early_end "
                f"policy_requests={policy.http.request_count} content_requests=0"
            )
            return 1
        checkpoint = batch.next_checkpoint

    # No intentional sleep between the fifth policy response and content.
    content_batch = fetch(content, "youthcenter_content", 1, None)
    if content_batch is None:
        emit(
            f"sequence_probe result=stopped reason=content_error "
            f"policy_requests={policy.http.request_count} "
            f"content_requests={content.http.request_count}"
        )
        return 1
    total = policy.http.request_count + content.http.request_count
    emit(
        f"sequence_probe result=complete policy_requests={policy.http.request_count} "
        f"content_requests={content.http.request_count} total_requests={total}"
    )
    return 0 if total == MAX_REQUESTS else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="approve up to six read-only Youthcenter HTTP requests")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for HTTP I/O")
    policy_key = os.environ.get("YOUTH_API_KEY")
    content_key = os.environ.get("YOUTH_CONTENT_API_KEY")
    if not policy_key or not content_key:
        print("sequence_probe result=stopped reason=missing_source_api_key")
        return 1
    policy = YouthcenterPolicyConnector(
        http=HttpClient(budget=POLICY_PAGES, max_attempts=1, max_response_bytes=DEFAULT_MAX_RESPONSE_BYTES),
        api_key_provider=lambda: policy_key,
    )
    content = YouthcenterContentConnector(
        http=HttpClient(budget=1, max_attempts=1, max_response_bytes=CONTENT_MAX_RESPONSE_BYTES),
        api_key_provider=lambda: content_key,
    )
    return run_sequence(policy, content)


if __name__ == "__main__":
    raise SystemExit(main())
