"""수집 저장소 계약과 테스트용 메모리 구현. 실제 Supabase는 테스트에서 쓰지 않는다."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from ingest.attachments import contains_forbidden_attachment_key
from ingest.constants import (
    AI_CLAIM_LIMIT,
    AI_MAX_ATTEMPTS,
    AI_RETRY_BACKOFF_SECONDS,
    DEFAULT_JOB_LEASE_SECONDS,
    DEFAULT_LEASE_SECONDS,
    LEASE_SECONDS_MAX,
    LEASE_SECONDS_MIN,
    MAX_BATCH_BYTES,
)
from ingest.models import (
    AI_STAGE,
    HUMAN_REVIEW_STAGES,
    Checkpoint,
    ClaimedJob,
    FinishRunResult,
    ObservationRecord,
    ObservationResult,
    ProcessingStage,
    StartRunResult,
)
from ingest.source_identity import (
    CANONICAL_CONTENT_SOURCE,
    CANONICAL_POLICY_SOURCE,
    CONNECTOR_TYPE_REST,
    CONTENT_CURATION_SOURCE,
    LEGACY_POLICY_CURATION_SOURCE,
    PROVIDER_YOUTHCENTER,
    SOURCE_KIND_CONTENT,
    SOURCE_KIND_POLICY,
    allows_publish,
    canonical_source_id,
    curation_source_for_enqueue,
    permission_transition_allowed,
)

ClockFn = Callable[[], datetime]


class LeaseLost(RuntimeError):
    def __init__(self) -> None:
        super().__init__("lease_lost")


class IngestStore(Protocol):
    def get_source(self, source_id: str) -> dict[str, Any]:
        ...

    def start_ingest_run(
        self, source_id: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS
    ) -> StartRunResult:
        ...

    def upsert_source_observations(
        self,
        source_id: str,
        run_id: str,
        records: list[ObservationRecord],
        next_checkpoint: Checkpoint | None,
    ) -> list[ObservationResult]:
        ...

    def finish_ingest_run(
        self,
        run_id: str,
        *,
        status: str,
        stop_reason: str,
        http_request_count: int,
        bootstrap_complete: bool = False,
        batches_ok: int = 0,
    ) -> FinishRunResult:
        ...

    def claim_processing_jobs(
        self,
        stage: ProcessingStage,
        *,
        limit: int = AI_CLAIM_LIMIT,
        worker_id: str,
        lease_seconds: int = DEFAULT_JOB_LEASE_SECONDS,
    ) -> list[ClaimedJob]:
        ...

    def complete_processing_job(self, job_id: str, *, worker_id: str) -> None:
        ...

    def fail_processing_job(
        self, job_id: str, *, worker_id: str, error_code: str
    ) -> str:
        ...

    def set_source_permission(
        self,
        source_id: str,
        to_status: str,
        *,
        reason: str,
        evidence_note: str | None,
        actor: str,
    ) -> None:
        ...


@dataclass
class _Source:
    source_id: str
    provider: str
    source_kind: str
    connector_type: str
    enabled: bool = True
    permission_status: str = "testing_only"
    legacy_curation_source: str = ""


@dataclass
class _Sync:
    source_id: str
    bootstrap_complete: bool = False
    committed_checkpoint: dict[str, Any] | None = None
    last_success_at: datetime | None = None
    last_stop_reason: str | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    lease_seconds: int | None = None
    active_run_id: str | None = None


@dataclass
class _Item:
    id: str
    source_id: str
    external_key: str
    revision_hash: str
    first_seen_at: datetime
    last_seen_at: datetime
    source_created_at: str | None
    source_created_raw: str | None
    source_created_parse_status: str
    source_updated_at: str | None
    source_updated_raw: str | None
    source_updated_parse_status: str
    disposition: str
    min_fields: dict[str, Any]
    normalized_payload: dict[str, Any] | None
    has_source_url: bool
    body_usable: bool
    attachment_present: bool
    attachment_length: int
    is_data_url: bool
    last_run_id: str


@dataclass
class _Job:
    id: str
    source_item_id: str
    revision_hash: str
    processing_stage: str
    status: str
    queued_at: datetime
    available_at: datetime
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    claim_lease_until: datetime | None = None
    claimed_by: str | None = None
    retry_count: int = 0
    next_retry_at: datetime | None = None
    error_code: str | None = None
    reason_codes: tuple[str, ...] = ()


@dataclass
class _Run:
    id: str
    source_id: str
    status: str = "running"
    stop_reason: str | None = None
    batches_ok: int = 0
    http_request_count: int = 0
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None


@dataclass
class _Publication:
    id: str
    source_id: str
    external_key: str
    revision_hash: str
    candidate_id: str | None
    public_curation_id: str | None
    publication_status: str
    published_at: datetime
    unpublished_at: datetime | None = None
    takedown_status: str = "none"


class MemoryIngestStore:
    """RPC 계약을 메모리에서 재현한다. 한 batch는 모두 성공하거나 모두 롤백된다."""

    def __init__(self, *, clock: ClockFn | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.sources: dict[str, _Source] = {}
        self.sync: dict[str, _Sync] = {}
        self.items: dict[tuple[str, str], _Item] = {}
        self.jobs: dict[str, _Job] = {}
        self.runs: dict[str, _Run] = {}
        self.relationships: list[dict[str, Any]] = []
        self.publications: list[_Publication] = []
        self.publication_events: list[dict[str, Any]] = []
        self.permission_events: list[dict[str, Any]] = []
        self.public_curations: dict[str, dict[str, Any]] = {}
        self._fail_permission_event = False
        seed_youthcenter_sources(self)

    def seed_source(self, source: _Source) -> None:
        self.sources[source.source_id] = source
        self.sync.setdefault(source.source_id, _Sync(source_id=source.source_id))

    def get_source(self, source_id: str) -> dict[str, Any]:
        row = self.sources[source_id]
        return {
            "source_id": row.source_id,
            "enabled": row.enabled,
            "permission_status": row.permission_status,
            "legacy_curation_source": row.legacy_curation_source,
        }

    def start_ingest_run(
        self, source_id: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS
    ) -> StartRunResult:
        now = self._clock()
        if lease_seconds < LEASE_SECONDS_MIN or lease_seconds > LEASE_SECONDS_MAX:
            raise ValueError("invalid lease_seconds")
        source = self.sources.get(source_id)
        if source is None or not source.enabled:
            return StartRunResult(
                run_id="",
                bootstrap_complete=False,
                committed_checkpoint=None,
                skipped=True,
                skip_reason="source_disabled",
            )
        sync = self.sync.setdefault(source_id, _Sync(source_id=source_id))
        if (
            sync.lease_owner
            and sync.lease_expires_at
            and sync.lease_expires_at > now
        ):
            return StartRunResult(
                run_id="",
                bootstrap_complete=sync.bootstrap_complete,
                committed_checkpoint=Checkpoint.from_json(sync.committed_checkpoint),
                skipped=True,
                skip_reason="lease_held",
            )
        run_id = str(uuid.uuid4())
        sync.lease_owner = run_id
        sync.lease_expires_at = now + timedelta(seconds=lease_seconds)
        sync.lease_seconds = lease_seconds
        sync.active_run_id = run_id
        self.runs[run_id] = _Run(
            id=run_id, source_id=source_id, lease_seconds=lease_seconds
        )
        return StartRunResult(
            run_id=run_id,
            bootstrap_complete=sync.bootstrap_complete,
            committed_checkpoint=Checkpoint.from_json(sync.committed_checkpoint),
        )

    def upsert_source_observations(
        self,
        source_id: str,
        run_id: str,
        records: list[ObservationRecord],
        next_checkpoint: Checkpoint | None,
    ) -> list[ObservationResult]:
        now = self._clock()
        self._require_active_lease(source_id, run_id, now)
        encoded = repr([record.to_rpc_item() for record in records]).encode("utf-8")
        if len(encoded) > MAX_BATCH_BYTES * 16:
            raise ValueError("batch_too_large")
        pending_items = dict(self.items)
        pending_jobs = dict(self.jobs)
        pending_rels = list(self.relationships)
        results: list[ObservationResult] = []
        seen_keys: set[str] = set()

        for index, record in enumerate(records):
            if not record.external_key:
                raise ValueError("external_key_required")
            if contains_forbidden_attachment_key(record.to_rpc_item()):
                raise ValueError("forbidden_attachment_key")
            duplicate = record.external_key in seen_keys
            seen_keys.add(record.external_key)
            key = (source_id, record.external_key)
            existing = pending_items.get(key)
            if existing is None:
                outcome = "new"
                item_id = str(uuid.uuid4())
                pending_items[key] = _item_from_record(
                    item_id, source_id, record, run_id, now, now
                )
            elif existing.revision_hash != record.revision_hash:
                outcome = "changed"
                item_id = existing.id
                pending_items[key] = _item_from_record(
                    item_id,
                    source_id,
                    record,
                    run_id,
                    existing.first_seen_at,
                    now,
                )
            else:
                outcome = "unchanged"
                item_id = existing.id
                updated = existing
                updated.last_seen_at = now
                updated.last_run_id = run_id
                pending_items[key] = updated

            if outcome in {"new", "changed"} and not duplicate:
                _insert_jobs(pending_jobs, item_id, record, now)
                _insert_relationships(
                    pending_rels, source_id, record.external_key, record
                )

            results.append(
                ObservationResult(
                    input_index=index,
                    external_key=record.external_key,
                    outcome=outcome,  # type: ignore[arg-type]
                    duplicate_in_batch=duplicate,
                    skipped_streak=duplicate,
                )
            )

        sync = self.sync[source_id]
        run = self.runs[run_id]
        sync.committed_checkpoint = (
            next_checkpoint.to_json() if next_checkpoint is not None else None
        )
        sync.lease_expires_at = now + timedelta(seconds=run.lease_seconds)
        self.items = pending_items
        self.jobs = pending_jobs
        self.relationships = pending_rels
        run.batches_ok += 1
        return results

    def finish_ingest_run(
        self,
        run_id: str,
        *,
        status: str,
        stop_reason: str,
        http_request_count: int,
        bootstrap_complete: bool = False,
        batches_ok: int = 0,
    ) -> FinishRunResult:
        now = self._clock()
        run = self.runs.get(run_id)
        if run is None:
            raise ValueError("run not found")
        run.status = status
        run.stop_reason = stop_reason
        run.http_request_count = http_request_count
        run.finished_at = now
        if batches_ok:
            run.batches_ok = batches_ok
        sync = self.sync[run.source_id]
        owns_lease = sync.lease_owner == run_id and sync.active_run_id == run_id
        if owns_lease:
            sync.lease_owner = None
            sync.lease_expires_at = None
            sync.active_run_id = None
            sync.last_stop_reason = stop_reason
            if run.batches_ok > 0:
                sync.last_success_at = now
            if (
                bootstrap_complete
                and status == "complete"
                and stop_reason
                in {"bootstrap_range_complete", "empty_batch", "short_batch"}
            ):
                sync.bootstrap_complete = True
        else:
            run.stop_reason = "lease_lost"
            run.status = "incomplete"
        return FinishRunResult(status=run.status, stop_reason=run.stop_reason or "")

    def claim_processing_jobs(
        self,
        stage: ProcessingStage,
        *,
        limit: int = AI_CLAIM_LIMIT,
        worker_id: str,
        lease_seconds: int = DEFAULT_JOB_LEASE_SECONDS,
    ) -> list[ClaimedJob]:
        if stage != AI_STAGE:
            return []
        now = self._clock()
        eligible = [
            job
            for job in self.jobs.values()
            if job.processing_stage == AI_STAGE
            and (
                (
                    job.status == "queued"
                    and job.available_at <= now
                    and (job.next_retry_at is None or job.next_retry_at <= now)
                )
                or (
                    job.status == "claimed"
                    and job.claim_lease_until is not None
                    and job.claim_lease_until < now
                )
            )
        ]
        eligible.sort(key=lambda job: (job.queued_at, job.id))
        claimed: list[ClaimedJob] = []
        for job in eligible[:limit]:
            job.status = "claimed"
            job.claimed_at = now
            job.claim_lease_until = now + timedelta(seconds=lease_seconds)
            job.claimed_by = worker_id
            item = next(value for value in self.items.values() if value.id == job.source_item_id)
            source = self.sources[item.source_id]
            claimed.append(
                ClaimedJob(
                    job_id=job.id,
                    source_item_id=item.id,
                    source_id=item.source_id,
                    external_key=item.external_key,
                    revision_hash=job.revision_hash,
                    processing_stage="ai_enrichment",
                    curation_source=source.legacy_curation_source
                    or curation_source_for_enqueue(item.source_id),
                    normalized_payload=item.normalized_payload,
                    disposition=item.disposition,
                )
            )
        return claimed

    def complete_processing_job(self, job_id: str, *, worker_id: str) -> None:
        job = self.jobs[job_id]
        if job.processing_stage in HUMAN_REVIEW_STAGES:
            raise ValueError("human_job_not_completable_by_ai")
        if job.claimed_by != worker_id:
            raise LeaseLost()
        job.status = "completed"
        job.completed_at = self._clock()

    def fail_processing_job(
        self, job_id: str, *, worker_id: str, error_code: str
    ) -> str:
        job = self.jobs[job_id]
        if job.processing_stage in HUMAN_REVIEW_STAGES:
            raise ValueError("human_job_not_completable_by_ai")
        if job.claimed_by != worker_id:
            raise LeaseLost()
        job.retry_count += 1
        job.error_code = error_code[:64]
        job.claimed_by = None
        job.claim_lease_until = None
        if job.retry_count >= AI_MAX_ATTEMPTS:
            job.status = "failed"
            job.next_retry_at = None
        else:
            job.status = "queued"
            job.next_retry_at = self._clock() + timedelta(
                seconds=AI_RETRY_BACKOFF_SECONDS
            )
        return job.status

    def publish_candidate(
        self,
        *,
        candidate_source: str,
        external_key: str,
        revision_hash: str,
        candidate_id: str,
        slug: str,
    ) -> str:
        canonical = canonical_source_id(candidate_source)
        source = self.sources[canonical]
        if not allows_publish(source.permission_status, enabled=source.enabled):
            raise PermissionError("publish_not_permitted")
        curation_id = str(uuid.uuid4())
        self.public_curations[curation_id] = {
            "id": curation_id,
            "slug": slug,
            "is_published": True,
            "source": candidate_source,
            "source_item_id": external_key,
        }
        now = self._clock()
        self.publication_events.append(
            {
                "event_kind": "published",
                "source_id": canonical,
                "external_key": external_key,
                "revision_hash": revision_hash,
                "candidate_id": candidate_id,
                "public_curation_id": curation_id,
                "slug": slug,
                "occurred_at": now,
            }
        )
        snapshot = next(
            (
                row
                for row in self.publications
                if row.source_id == canonical and row.external_key == external_key
            ),
            None,
        )
        if snapshot is None:
            self.publications.append(
                _Publication(
                    id=str(uuid.uuid4()),
                    source_id=canonical,
                    external_key=external_key,
                    revision_hash=revision_hash,
                    candidate_id=candidate_id,
                    public_curation_id=curation_id,
                    publication_status="published",
                    published_at=now,
                )
            )
        else:
            snapshot.revision_hash = revision_hash
            snapshot.candidate_id = candidate_id
            snapshot.public_curation_id = curation_id
            snapshot.publication_status = "published"
            snapshot.published_at = now
            snapshot.unpublished_at = None
            snapshot.takedown_status = "none"
        return curation_id

    def hard_delete_published_curation(self, public_curation_id: str, *, actor: str) -> None:
        """계약 테스트용. 운영 RPC로 노출하지 않는다."""
        pub = next(
            row
            for row in self.publications
            if row.public_curation_id == public_curation_id
        )
        now = self._clock()
        self.publication_events.append(
            {
                "event_kind": "hard_deleted",
                "source_id": pub.source_id,
                "external_key": pub.external_key,
                "revision_hash": pub.revision_hash,
                "candidate_id": pub.candidate_id,
                "public_curation_id": public_curation_id,
                "occurred_at": now,
                "actor": actor,
            }
        )
        pub.public_curation_id = None
        pub.takedown_status = "hard_deleted"
        del self.public_curations[public_curation_id]

    def set_source_permission(
        self,
        source_id: str,
        to_status: str,
        *,
        reason: str,
        evidence_note: str | None,
        actor: str,
    ) -> None:
        canonical = canonical_source_id(source_id)
        source = self.sources[canonical]
        actor_value = (actor or "").strip()
        reason_value = (reason or "").strip()
        note_value = (evidence_note or "").strip() or None
        if not actor_value or len(actor_value) > 128:
            raise ValueError("invalid actor")
        if not reason_value or len(reason_value) > 500:
            raise ValueError("invalid reason")
        if note_value is not None and len(note_value) > 500:
            raise ValueError("invalid evidence_note")
        if not permission_transition_allowed(source.permission_status, to_status):
            raise ValueError("permission_transition_not_allowed")
        pending_source = replace(source, permission_status=to_status)
        event = {
            "source_id": canonical,
            "from_status": source.permission_status,
            "to_status": to_status,
            "reason": reason_value,
            "evidence_note": note_value,
            "actor": actor_value,
        }
        if self._fail_permission_event:
            raise RuntimeError("permission_event_write_failed")
        self.sources[canonical] = pending_source
        self.permission_events.append(event)

    def delete_candidate(self, candidate_id: str) -> None:
        for pub in self.publications:
            if pub.candidate_id == candidate_id:
                pub.candidate_id = None

    def delete_public_curation(self, curation_id: str) -> None:
        self.public_curations.pop(curation_id, None)
        for pub in self.publications:
            if pub.public_curation_id == curation_id:
                pub.public_curation_id = None

    def ai_job_counts(self) -> dict[str, int]:
        counts = {
            "queued": 0,
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "retry_waiting": 0,
        }
        for job in self.jobs.values():
            if job.processing_stage != AI_STAGE:
                continue
            counts[job.status] = counts.get(job.status, 0) + 1
            if job.status == "queued" and job.retry_count > 0:
                counts["retry_waiting"] += 1
        return counts

    def jobs_for_stage(self, stage: str) -> list[_Job]:
        return [job for job in self.jobs.values() if job.processing_stage == stage]

    def _require_active_lease(self, source_id: str, run_id: str, now: datetime) -> None:
        sync = self.sync[source_id]
        if (
            sync.active_run_id != run_id
            or sync.lease_owner != run_id
            or sync.lease_expires_at is None
            or sync.lease_expires_at <= now
        ):
            raise LeaseLost()


def _item_from_record(
    item_id: str,
    source_id: str,
    record: ObservationRecord,
    run_id: str,
    first_seen: datetime,
    last_seen: datetime,
) -> _Item:
    return _Item(
        id=item_id,
        source_id=source_id,
        external_key=record.external_key,
        revision_hash=record.revision_hash,
        first_seen_at=first_seen,
        last_seen_at=last_seen,
        source_created_at=record.source_created_at,
        source_created_raw=record.source_created_raw,
        source_created_parse_status=record.source_created_parse_status,
        source_updated_at=record.source_updated_at,
        source_updated_raw=record.source_updated_raw,
        source_updated_parse_status=record.source_updated_parse_status,
        disposition=record.disposition,
        min_fields=dict(record.min_fields),
        normalized_payload=(
            dict(record.normalized_payload) if record.normalized_payload else None
        ),
        has_source_url=record.has_source_url,
        body_usable=record.body_usable,
        attachment_present=record.attachment_present,
        attachment_length=record.attachment_length,
        is_data_url=record.is_data_url,
        last_run_id=run_id,
    )


def _insert_jobs(
    pending_jobs: dict[str, _Job],
    item_id: str,
    record: ObservationRecord,
    now: datetime,
) -> None:
    for plan in record.jobs:
        exists = any(
            job.source_item_id == item_id
            and job.revision_hash == record.revision_hash
            and job.processing_stage == plan.stage
            for job in pending_jobs.values()
        )
        if exists:
            continue
        job_id = str(uuid.uuid4())
        pending_jobs[job_id] = _Job(
            id=job_id,
            source_item_id=item_id,
            revision_hash=record.revision_hash,
            processing_stage=plan.stage,
            status="queued",
            queued_at=now,
            available_at=now,
            reason_codes=plan.reason_codes,
        )


def _insert_relationships(
    pending_rels: list[dict[str, Any]],
    source_id: str,
    external_key: str,
    record: ObservationRecord,
) -> None:
    for rel in record.relationships:
        pending_rels.append(
            {
                "from_source_id": source_id,
                "from_external_key": external_key,
                "to_source_id": rel.to_source_id,
                "to_external_key": rel.to_external_key,
                "relation_kind": rel.relation_kind,
            }
        )


def seed_youthcenter_sources(store: MemoryIngestStore) -> None:
    store.seed_source(
        _Source(
            source_id=CANONICAL_POLICY_SOURCE,
            provider=PROVIDER_YOUTHCENTER,
            source_kind=SOURCE_KIND_POLICY,
            connector_type=CONNECTOR_TYPE_REST,
            permission_status="testing_only",
            legacy_curation_source=LEGACY_POLICY_CURATION_SOURCE,
        )
    )
    store.seed_source(
        _Source(
            source_id=CANONICAL_CONTENT_SOURCE,
            provider=PROVIDER_YOUTHCENTER,
            source_kind=SOURCE_KIND_CONTENT,
            connector_type=CONNECTOR_TYPE_REST,
            permission_status="testing_only",
            legacy_curation_source=CONTENT_CURATION_SOURCE,
        )
    )
