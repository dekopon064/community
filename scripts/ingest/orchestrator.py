"""공통 orchestrator. 페이지 번호를 해석하지 않고 batch/checkpoint만 다룬다."""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

from ingest.http_client import (
    HttpBudgetExhausted,
    HttpRequestFailed,
    HttpStatusError,
    ResponseTooLarge,
)
from ingest.models import (
    Checkpoint,
    ObservationRecord,
    ObservationResult,
    ORDERING_CAPABILITIES,
    ORDERING_DIAGNOSTIC_ORDER,
    OrderingCapability,
    SourceConnector,
    StartMode,
)
from ingest.rpc_errors import RpcAmbiguous, RpcFailure, RpcTimeout
from ingest.store import (
    DEFAULT_LEASE_SECONDS,
    IngestStore,
    LeaseLost,
)

SleepFn = Callable[[float], None]

BOOTSTRAP_COMPLETE_REASONS = frozenset(
    {"bootstrap_range_complete", "empty_batch", "short_batch"}
)
ORDERING_OVERLAY_EXEMPT_REASONS = frozenset(
    {
        "empty_batch",
        "short_batch",
        "lease_lost",
        "http_budget_exhausted",
        "response_too_large",
    }
)


class InvalidOrderingCapability(RuntimeError):
    """Missing or unsupported ordering_capability. Do not coerce the value."""

    def __init__(self) -> None:
        super().__init__("invalid_ordering_capability")


def require_ordering_capability(connector: object) -> OrderingCapability:
    try:
        value = connector.ordering_capability
    except AttributeError:
        raise InvalidOrderingCapability() from None
    if value not in ORDERING_CAPABILITIES:
        raise InvalidOrderingCapability()
    return value  # type: ignore[return-value]


def format_ordering_cli_token(diagnostics: Iterable[str]) -> str:
    parts = [name for name in ORDERING_DIAGNOSTIC_ORDER if name in set(diagnostics)]
    if not parts:
        return "ok"
    return ",".join(parts)


class SourceRunResult:
    def __init__(
        self,
        source_id: str,
        *,
        status: str,
        stop_reason: str,
        batches_ok: int,
        http_request_count: int,
        bootstrap_complete: bool,
        skipped: bool = False,
        ordering_diagnostics: frozenset[str] = frozenset(),
    ) -> None:
        self.source_id = source_id
        self.status = status
        self.stop_reason = stop_reason
        self.batches_ok = batches_ok
        self.http_request_count = http_request_count
        self.bootstrap_complete = bootstrap_complete
        self.skipped = skipped
        self.ordering_diagnostics = frozenset(ordering_diagnostics)

    def ordering_cli_token(self) -> str:
        return format_ordering_cli_token(self.ordering_diagnostics)


def record_sort_stamp(record: ObservationRecord) -> str | None:
    if record.source_updated_parse_status == "ok":
        return record.source_updated_at
    if record.source_created_parse_status == "ok":
        return record.source_created_at
    return None


def ordering_anomaly_in_records(
    records: Sequence[ObservationRecord],
    previous: str | None = None,
) -> tuple[bool, str | None, frozenset[str]]:
    found: set[str] = set()
    last = previous
    for record in records:
        stamp = record_sort_stamp(record)
        if stamp is None:
            found.add("missing_stamp")
            continue
        if last is not None and stamp > last:
            found.add("non_monotonic_stamp")
        last = stamp
    return bool(found), last, frozenset(found)


def streak_delta(results: Sequence[ObservationResult]) -> int | None:
    """unchanged는 +1, new/changed는 0으로 리셋. 배치 내 중복은 무시.

    Returns:
        None if the batch contains a reset, otherwise added streak count.
    """
    added = 0
    for row in results:
        if row.duplicate_in_batch or row.skipped_streak:
            continue
        if row.outcome in {"new", "changed"}:
            return None
        added += 1
    return added


def run_connector(
    connector: SourceConnector,
    store: IngestStore,
    *,
    sleep: SleepFn = lambda _seconds: None,
    permission_status: str | None = None,
    enabled: bool | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> SourceRunResult:
    capability = require_ordering_capability(connector)
    source_id = connector.canonical_source_id
    source_row = store.get_source(source_id)
    enabled_flag = source_row["enabled"] if enabled is None else enabled
    permission = (
        source_row["permission_status"]
        if permission_status is None
        else permission_status
    )
    if not enabled_flag:
        return SourceRunResult(
            source_id,
            status="failed",
            stop_reason="source_disabled",
            batches_ok=0,
            http_request_count=0,
            bootstrap_complete=False,
            skipped=True,
        )

    started = store.start_ingest_run(source_id, lease_seconds=lease_seconds)
    if started.skipped:
        return SourceRunResult(
            source_id,
            status="incomplete",
            stop_reason=started.skip_reason or "skipped",
            batches_ok=0,
            http_request_count=0,
            bootstrap_complete=started.bootstrap_complete,
            skipped=True,
        )

    run_id = started.run_id
    bootstrap = not started.bootstrap_complete
    checkpoint = _starting_checkpoint(connector.start_mode, started.committed_checkpoint)
    max_pages = connector.bootstrap_max_pages if bootstrap else connector.max_pages
    max_items = connector.bootstrap_max_items if bootstrap else None
    streak = 0
    anomaly = False
    last_stamp: str | None = None
    ordering_diagnostics: set[str] = set()
    batches_ok = 0
    pages_fetched = 0
    items_committed = 0
    http_count = _http_count(connector)
    status = "failed"
    stop_reason = "rpc_error"
    mark_bootstrap_complete = False

    try:
        while pages_fetched < max_pages:
            if batches_ok > 0:
                sleep(connector.batch_delay_seconds)
            if _http_count(connector) >= connector.http_budget:
                status = "incomplete" if batches_ok else "failed"
                stop_reason = "http_budget_exhausted"
                break
            try:
                batch = connector.fetch_batch(checkpoint)
            except HttpBudgetExhausted:
                status = "incomplete" if batches_ok else "failed"
                stop_reason = "http_budget_exhausted"
                break
            except ResponseTooLarge:
                status = "incomplete" if batches_ok else "failed"
                stop_reason = "response_too_large"
                break
            except HttpStatusError as exc:
                status = "incomplete" if batches_ok else "failed"
                stop_reason = f"http_{exc.status}"
                break
            except HttpRequestFailed:
                status = "incomplete" if batches_ok else "failed"
                stop_reason = "http_error"
                break

            pages_fetched += 1
            http_count = _http_count(connector)
            records = []
            for item in batch.items:
                record = connector.to_observation(
                    item, permission_status=permission, enabled=enabled_flag
                )
                if record.external_key:
                    records.append(record)
            found_anomaly, last_stamp, batch_diagnostics = ordering_anomaly_in_records(
                records, last_stamp
            )
            ordering_diagnostics.update(batch_diagnostics)
            if found_anomaly:
                anomaly = True

            if not batch.items:
                try:
                    store.upsert_source_observations_v4(
                        source_id, run_id, [], batch.next_checkpoint
                    )
                except LeaseLost:
                    status = "incomplete"
                    stop_reason = "lease_lost"
                    break
                batches_ok += 1
                status = "complete"
                stop_reason = "empty_batch"
                mark_bootstrap_complete = bootstrap
                break

            try:
                results = store.upsert_source_observations_v4(
                    source_id, run_id, records, batch.next_checkpoint
                )
            except LeaseLost:
                status = "incomplete"
                stop_reason = "lease_lost"
                break

            batches_ok += 1
            items_committed += len(records)
            checkpoint = batch.next_checkpoint

            if capability == "require_descending" and not anomaly:
                delta = streak_delta(results)
                if delta is None:
                    streak = 0
                else:
                    streak += delta

            natural_short = batch.natural_end and bool(batch.items)
            if batch.natural_end and not batch.items:
                status = "complete"
                stop_reason = "empty_batch"
                mark_bootstrap_complete = bootstrap
                break
            if natural_short:
                status = "complete"
                stop_reason = "short_batch"
                mark_bootstrap_complete = bootstrap
                break

            if bootstrap and items_committed >= (max_items or 0):
                status = "complete"
                stop_reason = "bootstrap_range_complete"
                mark_bootstrap_complete = True
                break

            if (
                capability == "require_descending"
                and not bootstrap
                and not anomaly
                and streak >= connector.streak_needed
            ):
                status = "complete"
                stop_reason = "streak_complete"
                break

            if checkpoint is None:
                status = "complete"
                stop_reason = "short_batch"
                mark_bootstrap_complete = bootstrap
                break
        else:
            if bootstrap and batches_ok > 0:
                status = "complete"
                stop_reason = "bootstrap_range_complete"
                mark_bootstrap_complete = True
            elif capability == "untrusted" and batches_ok > 0:
                # Configured observation range finished. Not full source coverage.
                # Store last_success_at, if updated, is this range's success time.
                status = "complete"
                stop_reason = "configured_range_complete"
            else:
                status = "incomplete" if batches_ok else "failed"
                stop_reason = "max_pages"

        if (
            capability == "require_descending"
            and anomaly
            and stop_reason not in ORDERING_OVERLAY_EXEMPT_REASONS
        ):
            status = "incomplete"
            stop_reason = "ordering_anomaly"
            mark_bootstrap_complete = False

    except LeaseLost:
        status = "incomplete"
        stop_reason = "lease_lost"
        mark_bootstrap_complete = False
    except RpcTimeout:
        status = "incomplete" if batches_ok else "failed"
        stop_reason = "rpc_timeout"
        mark_bootstrap_complete = False
    except (RpcAmbiguous, RpcFailure):
        status = "incomplete" if batches_ok else "failed"
        stop_reason = "rpc_error"
        mark_bootstrap_complete = False
    except Exception:
        status = "incomplete" if batches_ok else "failed"
        stop_reason = "rpc_error"
        mark_bootstrap_complete = False

    try:
        finish_result = store.finish_ingest_run(
            run_id,
            status=status,
            stop_reason=stop_reason,
            http_request_count=_http_count(connector),
            bootstrap_complete=mark_bootstrap_complete
            and status == "complete"
            and stop_reason in BOOTSTRAP_COMPLETE_REASONS,
            batches_ok=batches_ok,
        )
    except Exception:
        return SourceRunResult(
            source_id,
            status="incomplete" if batches_ok else "failed",
            stop_reason="finish_failed",
            batches_ok=batches_ok,
            http_request_count=_http_count(connector),
            bootstrap_complete=False,
            ordering_diagnostics=frozenset(ordering_diagnostics),
        )

    result_status = finish_result.status
    result_reason = finish_result.stop_reason
    if result_status not in {"complete", "incomplete", "failed"}:
        return SourceRunResult(
            source_id,
            status="incomplete" if batches_ok else "failed",
            stop_reason="finish_failed",
            batches_ok=batches_ok,
            http_request_count=_http_count(connector),
            bootstrap_complete=False,
            ordering_diagnostics=frozenset(ordering_diagnostics),
        )
    return SourceRunResult(
        source_id,
        status=result_status,
        stop_reason=result_reason,
        batches_ok=batches_ok,
        http_request_count=_http_count(connector),
        bootstrap_complete=(
            mark_bootstrap_complete
            and result_status == "complete"
            and result_reason in BOOTSTRAP_COMPLETE_REASONS
        ),
        ordering_diagnostics=frozenset(ordering_diagnostics),
    )


def run_ingest(
    connectors: Iterable[SourceConnector],
    store: IngestStore,
    *,
    sleep: SleepFn = lambda _seconds: None,
) -> list[SourceRunResult]:
    results: list[SourceRunResult] = []
    for connector in connectors:
        try:
            results.append(run_connector(connector, store, sleep=sleep))
        except InvalidOrderingCapability:
            raise
        except Exception:
            results.append(
                SourceRunResult(
                    connector.canonical_source_id,
                    status="failed",
                    stop_reason="source_isolated_failure",
                    batches_ok=0,
                    http_request_count=_http_count(connector),
                    bootstrap_complete=False,
                )
            )
    return results


def _starting_checkpoint(
    start_mode: StartMode, committed: Checkpoint | None
) -> Checkpoint | None:
    if start_mode == "resume_committed":
        return committed
    return None


def _http_count(connector: SourceConnector) -> int:
    http = getattr(connector, "http", None)
    return int(getattr(http, "request_count", 0) or 0)
