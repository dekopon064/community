"""수집 저장소 계약과 테스트용 메모리 구현. 실제 Supabase는 테스트에서 쓰지 않는다."""

from __future__ import annotations

import copy
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
    APPROVE_REGION_SCOPES,
    AUDIENCE_AXES,
    Checkpoint,
    ClaimedJob,
    CLASSIFIER_DECISION_KEYS,
    CLASSIFIER_REVIEWER_PREFIX,
    FinishRunResult,
    GateFactsResult,
    ObservationRecord,
    ObservationResult,
    PRODUCT_TYPE_REVIEW_STAGE,
    ProcessingStage,
    ProductTypeResult,
    RECONCILE_ACTIONS,
    RELEVANCE_REVIEW_STAGE,
    REVIEW_DECISIONS,
    REVIEW_TYPES,
    ReviewDecisionResult,
    StartRunResult,
)
from ingest.product_type import (
    PRODUCT_TYPE_ACTION_CONFIRM,
    PRODUCT_TYPE_ACTION_OVERRIDE,
    PRODUCT_TYPE_ACTION_ROLLBACK,
    PRODUCT_TYPE_ACTIONS,
    PRODUCT_TYPE_CLASSIFICATION_KEYS,
    PRODUCT_TYPE_EVENT_PROGRAM,
    PRODUCT_TYPE_KIND_CONFIRMED,
    PRODUCT_TYPE_KIND_REVIEW,
    PRODUCT_TYPE_ORIGIN_CLASSIFIER,
    PRODUCT_TYPE_ORIGIN_HUMAN,
    PRODUCT_TYPE_RULE_VERSION,
    PRODUCT_TYPES,
)
from ingest.assessment import evaluate_proposal, propose_assessment
from ingest.evaluate_gates import CAPITAL_V1_PROFILE, EvaluationResult, evaluate_capital_v1
from ingest.gate_facts import (
    GATE_FACTS_SCHEMA_VERSION,
    InvalidGateFacts,
    is_complete_v1_facts,
    is_legacy_facts_row,
    parse_gate_facts,
)
from ingest.rpc_errors import RpcFailure
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
REVIEW_TYPE_TO_STAGE = {
    "region": "region_review",
    "relevance": RELEVANCE_REVIEW_STAGE,
    "content": "content_review",
}
BLOCKING_REVIEW_STAGES = frozenset(
    {
        "region_review",
        RELEVANCE_REVIEW_STAGE,
        "content_review",
        PRODUCT_TYPE_REVIEW_STAGE,
    }
)
UNRESOLVED_REVIEW_STATUSES = frozenset({"queued", "claimed"})
FORBIDDEN_PROMOTE_DISPOSITIONS = frozenset(
    {"non_target", "observe_only", "attachment_dependent"}
)


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

    def upsert_source_observations_v4(
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

    def resolve_ingest_review_decision(
        self,
        *,
        source_item_id: str,
        revision_hash: str,
        review_type: str,
        decision: str,
        region_scope: str,
        audience_relevance: tuple[str, ...] | list[str] = (),
        reason_codes: tuple[str, ...] | list[str] = (),
        rule_version: str,
        reviewer: str,
        memo: str | None = None,
    ) -> ReviewDecisionResult:
        ...

    def reconcile_queued_ai_job(
        self,
        job_id: str,
        *,
        action: str,
        review_type: str,
        region_scope: str,
        audience_relevance: tuple[str, ...] | list[str] = (),
        reason_codes: tuple[str, ...] | list[str] = (),
        rule_version: str,
        reviewer: str,
        memo: str | None = None,
    ) -> ReviewDecisionResult:
        ...

    def resolve_source_item_product_type(
        self,
        *,
        source_item_id: str,
        revision_hash: str,
        action: str,
        product_type: str | None = None,
        reason_codes: tuple[str, ...] | list[str] = (),
        period_signals: tuple[str, ...] | list[str] = (),
        rule_version: str,
        reviewer: str,
        memo: str | None = None,
    ) -> ProductTypeResult:
        ...

    def resolve_source_item_gate_facts(
        self,
        *,
        source_item_id: str,
        revision_hash: str,
        gate_facts: dict[str, Any],
        assessment_schema_version: str,
        reviewer: str,
        memo: str | None = None,
    ) -> GateFactsResult:
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
class _Candidate:
    source: str
    source_item_id: str
    source_revision_hash: str


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
class _Decision:
    id: str
    source_item_id: str
    revision_hash: str
    review_type: str
    decision: str
    region_scope: str
    audience_relevance: tuple[str, ...]
    reason_codes: tuple[str, ...]
    rule_version: str
    reviewer: str
    reviewed_at: datetime
    memo: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class _ProductType:
    source_item_id: str
    revision_hash: str
    product_type: str
    origin: str
    rule_version: str
    reason_codes: tuple[str, ...]
    period_signals: tuple[str, ...]
    reviewer: str
    memo: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    gate_facts: dict[str, Any] | None = None
    assessment_schema_version: str | None = None
    evaluated_profile: str | None = None
    evaluated_at: datetime | None = None


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
        self.decisions: dict[tuple[str, str, str], _Decision] = {}
        self.product_types: dict[tuple[str, str], _ProductType] = {}
        self.candidates: list[_Candidate] = []
        self._fail_permission_event = False
        self._fail_decision_core = False
        self._fail_decision_core_after_mapped = False
        self._fail_product_type_core = False
        self._fail_after_product_type = False
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
        for record in records:
            self._reject_v3_input(record)

        sync = self.sync[source_id]
        run = self.runs[run_id]
        snapshot = {
            "items": copy.deepcopy(self.items),
            "jobs": copy.deepcopy(self.jobs),
            "decisions": copy.deepcopy(self.decisions),
            "product_types": copy.deepcopy(self.product_types),
            "relationships": copy.deepcopy(self.relationships),
            "checkpoint": copy.deepcopy(sync.committed_checkpoint),
            "lease_expires_at": sync.lease_expires_at,
            "batches_ok": run.batches_ok,
        }
        try:
            pending_items = copy.deepcopy(self.items)
            pending_jobs = copy.deepcopy(self.jobs)
            pending_rels = copy.deepcopy(self.relationships)
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

            sync.committed_checkpoint = (
                next_checkpoint.to_json() if next_checkpoint is not None else None
            )
            sync.lease_expires_at = now + timedelta(seconds=run.lease_seconds)
            self.items = pending_items
            self.jobs = pending_jobs
            self.relationships = pending_rels
            self._apply_product_type_classifications(source_id, records, results)
            self._apply_classifier_approvals(source_id, records, results)
            run.batches_ok += 1
            return results
        except Exception:
            self.items = snapshot["items"]
            self.jobs = snapshot["jobs"]
            self.decisions = snapshot["decisions"]
            self.product_types = snapshot["product_types"]
            self.relationships = snapshot["relationships"]
            sync.committed_checkpoint = snapshot["checkpoint"]
            sync.lease_expires_at = snapshot["lease_expires_at"]
            run.batches_ok = snapshot["batches_ok"]
            raise

    def upsert_source_observations_v4(
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
        source = self.sources[source_id]
        assessed: list[ObservationRecord] = []
        for record in records:
            self._reject_v4_input(record)
            proposal = propose_assessment(record, source_kind=source.source_kind)
            evaluation = evaluate_proposal(record, proposal)
            rel_jobs = tuple(
                job for job in record.jobs if job.stage == "relationship_review"
            )
            classification = None
            if proposal.product_type_classification is not None:
                classification = proposal.product_type_classification.to_payload()
            facts_payload = None
            schema = None
            profile = None
            if proposal.gate_facts is not None:
                facts_payload = proposal.gate_facts.to_payload()
                schema = GATE_FACTS_SCHEMA_VERSION
                profile = CAPITAL_V1_PROFILE
            assessed.append(
                replace(
                    record,
                    disposition=evaluation.disposition,  # type: ignore[arg-type]
                    jobs=evaluation.jobs + rel_jobs,
                    classifier_decision=None,
                    product_type_classification=classification,
                    gate_facts=facts_payload,
                    assessment_schema_version=schema,
                    evaluated_profile=profile,
                )
            )

        sync = self.sync[source_id]
        run = self.runs[run_id]
        snapshot = {
            "items": copy.deepcopy(self.items),
            "jobs": copy.deepcopy(self.jobs),
            "decisions": copy.deepcopy(self.decisions),
            "product_types": copy.deepcopy(self.product_types),
            "relationships": copy.deepcopy(self.relationships),
            "checkpoint": copy.deepcopy(sync.committed_checkpoint),
            "lease_expires_at": sync.lease_expires_at,
            "batches_ok": run.batches_ok,
        }
        try:
            pending_items = copy.deepcopy(self.items)
            pending_jobs = copy.deepcopy(self.jobs)
            pending_rels = copy.deepcopy(self.relationships)
            results: list[ObservationResult] = []
            seen_keys: set[str] = set()

            for index, record in enumerate(assessed):
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

            sync.committed_checkpoint = (
                next_checkpoint.to_json() if next_checkpoint is not None else None
            )
            sync.lease_expires_at = now + timedelta(seconds=run.lease_seconds)
            self.items = pending_items
            self.jobs = pending_jobs
            self.relationships = pending_rels
            self._apply_v4_product_types(source_id, assessed, results, now)
            run.batches_ok += 1
            return results
        except Exception:
            self.items = snapshot["items"]
            self.jobs = snapshot["jobs"]
            self.decisions = snapshot["decisions"]
            self.product_types = snapshot["product_types"]
            self.relationships = snapshot["relationships"]
            sync.committed_checkpoint = snapshot["checkpoint"]
            sync.lease_expires_at = snapshot["lease_expires_at"]
            run.batches_ok = snapshot["batches_ok"]
            raise

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
            and self._ai_job_is_claim_ready(job, now)
            and self._claimable_item_for_ai_job(job) is not None
        ]
        eligible.sort(key=lambda job: (job.queued_at, job.id))
        claimed: list[ClaimedJob] = []
        for job in eligible[:limit]:
            job.status = "claimed"
            job.claimed_at = now
            job.claim_lease_until = now + timedelta(seconds=lease_seconds)
            job.claimed_by = worker_id
            item = self._claimable_item_for_ai_job(job)
            if item is None:
                continue
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
        job = self._require_claimed_ai_job(job_id, worker_id)
        job.status = "completed"
        job.completed_at = self._clock()
        job.claimed_by = None
        job.claim_lease_until = None
        job.next_retry_at = None

    def fail_processing_job(
        self, job_id: str, *, worker_id: str, error_code: str
    ) -> str:
        job = self._require_claimed_ai_job(job_id, worker_id)
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

    def resolve_ingest_review_decision(
        self,
        *,
        source_item_id: str,
        revision_hash: str,
        review_type: str,
        decision: str,
        region_scope: str,
        audience_relevance: tuple[str, ...] | list[str] = (),
        reason_codes: tuple[str, ...] | list[str] = (),
        rule_version: str,
        reviewer: str,
        memo: str | None = None,
    ) -> ReviewDecisionResult:
        return self._apply_ingest_review_decision(
            source_item_id=source_item_id,
            revision_hash=revision_hash,
            review_type=review_type,
            decision=decision,
            region_scope=region_scope,
            audience_relevance=audience_relevance,
            reason_codes=reason_codes,
            rule_version=rule_version,
            reviewer=reviewer,
            memo=memo,
        )

    def _apply_ingest_review_decision(
        self,
        *,
        source_item_id: str,
        revision_hash: str,
        review_type: str,
        decision: str,
        region_scope: str,
        audience_relevance: tuple[str, ...] | list[str] = (),
        reason_codes: tuple[str, ...] | list[str] = (),
        rule_version: str,
        reviewer: str,
        memo: str | None = None,
    ) -> ReviewDecisionResult:
        snapshot = {
            "items": copy.deepcopy(self.items),
            "jobs": copy.deepcopy(self.jobs),
            "decisions": copy.deepcopy(self.decisions),
            "candidates": copy.deepcopy(self.candidates),
        }
        try:
            return self._apply_ingest_review_decision_inner(
                source_item_id=source_item_id,
                revision_hash=revision_hash,
                review_type=review_type,
                decision=decision,
                region_scope=region_scope,
                audience_relevance=audience_relevance,
                reason_codes=reason_codes,
                rule_version=rule_version,
                reviewer=reviewer,
                memo=memo,
            )
        except Exception:
            self.items = snapshot["items"]
            self.jobs = snapshot["jobs"]
            self.decisions = snapshot["decisions"]
            self.candidates = snapshot["candidates"]
            raise

    def _apply_ingest_review_decision_inner(
        self,
        *,
        source_item_id: str,
        revision_hash: str,
        review_type: str,
        decision: str,
        region_scope: str,
        audience_relevance: tuple[str, ...] | list[str] = (),
        reason_codes: tuple[str, ...] | list[str] = (),
        rule_version: str,
        reviewer: str,
        memo: str | None = None,
    ) -> ReviewDecisionResult:
        if self._fail_decision_core:
            raise RpcFailure("decision_conflict")
        now = self._clock()
        axes = tuple(audience_relevance)
        reasons = tuple(reason_codes)
        v_hash = (revision_hash or "").strip()
        v_type = (review_type or "").strip()
        v_decision = (decision or "").strip()
        v_scope = (region_scope or "").strip()
        v_rule = (rule_version or "").strip()
        v_reviewer = (reviewer or "").strip()
        v_memo = (memo or "").strip() or None
        if not source_item_id:
            raise RpcFailure("source_item_not_found")
        if len(v_hash) != 64 or any(ch not in "0123456789abcdef" for ch in v_hash):
            raise RpcFailure("revision_mismatch")
        if v_type not in REVIEW_TYPES:
            raise RpcFailure("invalid_review_type")
        if v_decision not in REVIEW_DECISIONS:
            raise RpcFailure("invalid_decision")
        if v_type == "content" and v_decision != "reject":
            raise RpcFailure("invalid_decision")
        if v_type == "content" and "insufficient_evidence" not in reasons:
            raise RpcFailure("insufficient_evidence_required")
        if v_scope not in {
            "capital",
            "nationwide_or_online",
            "noncapital",
            "unknown",
        }:
            raise RpcFailure("invalid_region_scope")
        if not (1 <= len(v_rule) <= 64):
            raise RpcFailure("invalid_rule_version")
        if not (1 <= len(v_reviewer) <= 128):
            raise RpcFailure("invalid_reviewer")
        if v_memo is not None and len(v_memo) > 500:
            raise RpcFailure("invalid_memo")
        if any(axis not in AUDIENCE_AXES for axis in axes):
            raise RpcFailure("invalid_audience_relevance")
        if v_decision == "approve_ai" and (
            len(axes) < 1 or v_scope not in APPROVE_REGION_SCOPES
        ):
            raise RpcFailure("approve_requirements_not_met")

        item = self._item_by_id(source_item_id)
        if item.revision_hash != v_hash:
            raise RpcFailure("revision_mismatch")
        if v_type == "content" and v_decision == "reject":
            self._assert_content_reject_ready(item, v_hash, now)

        key = (item.id, v_hash, v_type)
        existing = self.decisions.get(key)
        if existing is not None:
            if existing.decision == v_decision:
                pass
            elif existing.decision == "needs_review" and v_decision in {
                "approve_ai",
                "reject",
            }:
                pass
            else:
                raise RpcFailure("decision_conflict")
            existing.decision = v_decision
            existing.region_scope = v_scope
            existing.audience_relevance = axes
            existing.reason_codes = reasons
            existing.rule_version = v_rule
            existing.reviewer = v_reviewer
            existing.reviewed_at = now
            existing.memo = v_memo
            existing.updated_at = now
            decision_row = existing
        else:
            decision_row = _Decision(
                id=str(uuid.uuid4()),
                source_item_id=item.id,
                revision_hash=v_hash,
                review_type=v_type,
                decision=v_decision,
                region_scope=v_scope,
                audience_relevance=axes,
                reason_codes=reasons,
                rule_version=v_rule,
                reviewer=v_reviewer,
                reviewed_at=now,
                memo=v_memo,
                created_at=now,
                updated_at=now,
            )
            self.decisions[key] = decision_row

        ai_job = self._job_for(item.id, v_hash, AI_STAGE)
        if ai_job is not None and self._is_malformed_claimed(ai_job):
            raise RpcFailure("ai_job_malformed_lease")
        live_claimed = ai_job is not None and self._is_live_claimed(ai_job, now)
        review_stage = REVIEW_TYPE_TO_STAGE.get(v_type)
        if review_stage is None:
            raise RpcFailure("invalid_review_type")

        if v_decision == "approve_ai":
            self._complete_mapped_review_job(item.id, v_hash, review_stage, now)
            if self._fail_decision_core_after_mapped:
                raise RpcFailure("decision_conflict")
            if self._can_promote_to_target(item, v_hash, v_scope):
                item.disposition = "target"
            self._ensure_queued_ai_job(item, v_hash, now, reasons)
        elif v_decision == "reject":
            if live_claimed:
                raise RpcFailure("ai_job_claimed")
            self._complete_mapped_review_job(item.id, v_hash, review_stage, now)
            if ai_job is not None and (
                ai_job.status == "queued" or self._is_lease_expired_claimed(ai_job, now)
            ):
                self._cancel_ai_job(
                    ai_job, reasons or ("rejected_non_target",)
                )
            item.disposition = "non_target"
        else:
            if live_claimed:
                raise RpcFailure("ai_job_claimed")
            if ai_job is not None and (
                ai_job.status == "queued" or self._is_lease_expired_claimed(ai_job, now)
            ):
                self._cancel_ai_job(ai_job, reasons or ("needs_review",))
            review_job = self._job_for(item.id, v_hash, review_stage)
            if review_job is None:
                self._insert_job(item.id, v_hash, review_stage, now, reasons)
            elif review_job.status != "queued":
                review_job.status = "queued"
                review_job.available_at = now
                review_job.claimed_by = None
                review_job.claim_lease_until = None
                review_job.completed_at = None
                review_job.next_retry_at = None
                review_job.reason_codes = reasons

        ai_job = self._job_for(item.id, v_hash, AI_STAGE)
        review_job = self._job_for(item.id, v_hash, review_stage)
        return ReviewDecisionResult(
            decision_id=decision_row.id,
            source_item_id=item.id,
            revision_hash=v_hash,
            review_type=v_type,
            decision=v_decision,
            ai_job_id=None if ai_job is None else ai_job.id,
            ai_job_status=None if ai_job is None else ai_job.status,
            review_job_id=None if review_job is None else review_job.id,
            review_job_status=None if review_job is None else review_job.status,
        )

    def reconcile_queued_ai_job(
        self,
        job_id: str,
        *,
        action: str,
        review_type: str,
        region_scope: str,
        audience_relevance: tuple[str, ...] | list[str] = (),
        reason_codes: tuple[str, ...] | list[str] = (),
        rule_version: str,
        reviewer: str,
        memo: str | None = None,
    ) -> ReviewDecisionResult:
        now = self._clock()
        v_action = (action or "").strip()
        if not job_id:
            raise RpcFailure("job not found")
        if v_action not in RECONCILE_ACTIONS:
            raise RpcFailure("invalid_reconcile_action")
        job = self.jobs.get(job_id)
        if job is None:
            raise RpcFailure("job not found")
        if job.processing_stage != AI_STAGE:
            raise RpcFailure("unexpected_job_status")
        if job.status == "completed":
            raise RpcFailure("completed_job_not_reconcileable")
        if job.status == "failed":
            raise RpcFailure("unexpected_job_status")
        if self._is_malformed_claimed(job):
            raise RpcFailure("ai_job_malformed_lease")
        if self._is_live_claimed(job, now):
            raise RpcFailure("ai_job_claimed")
        if job.status not in {"queued", "claimed", "cancelled"}:
            raise RpcFailure("unexpected_job_status")
        item = self._item_by_id(job.source_item_id)
        if item.revision_hash != job.revision_hash:
            raise RpcFailure("revision_mismatch")
        reasons = tuple(reason_codes)
        if v_action == "keep_with_approve":
            decision = "approve_ai"
        elif v_action == "cancel_unfit":
            decision = "reject"
            if not reasons:
                reasons = ("reconcile_unfit",)
        else:
            decision = "needs_review"
            if not reasons:
                reasons = ("needs_review",)
        result = self._apply_ingest_review_decision(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            review_type=review_type,
            decision=decision,
            region_scope=region_scope,
            audience_relevance=audience_relevance,
            reason_codes=reasons,
            rule_version=rule_version,
            reviewer=reviewer,
            memo=memo,
        )
        return replace(result, action_result=v_action)

    def resolve_source_item_product_type(
        self,
        *,
        source_item_id: str,
        revision_hash: str,
        action: str,
        product_type: str | None = None,
        reason_codes: tuple[str, ...] | list[str] = (),
        period_signals: tuple[str, ...] | list[str] = (),
        rule_version: str,
        reviewer: str,
        memo: str | None = None,
    ) -> ProductTypeResult:
        snapshot = {
            "items": copy.deepcopy(self.items),
            "jobs": copy.deepcopy(self.jobs),
            "product_types": copy.deepcopy(self.product_types),
        }
        try:
            return self._resolve_source_item_product_type_inner(
                source_item_id=source_item_id,
                revision_hash=revision_hash,
                action=action,
                product_type=product_type,
                reason_codes=reason_codes,
                period_signals=period_signals,
                rule_version=rule_version,
                reviewer=reviewer,
                memo=memo,
            )
        except Exception:
            self.items = snapshot["items"]
            self.jobs = snapshot["jobs"]
            self.product_types = snapshot["product_types"]
            raise

    def resolve_source_item_gate_facts(
        self,
        *,
        source_item_id: str,
        revision_hash: str,
        gate_facts: dict[str, Any],
        assessment_schema_version: str,
        reviewer: str,
        memo: str | None = None,
    ) -> GateFactsResult:
        snapshot = {
            "items": copy.deepcopy(self.items),
            "jobs": copy.deepcopy(self.jobs),
            "product_types": copy.deepcopy(self.product_types),
        }
        try:
            return self._resolve_source_item_gate_facts_inner(
                source_item_id=source_item_id,
                revision_hash=revision_hash,
                gate_facts=gate_facts,
                assessment_schema_version=assessment_schema_version,
                reviewer=reviewer,
                memo=memo,
            )
        except Exception:
            self.items = snapshot["items"]
            self.jobs = snapshot["jobs"]
            self.product_types = snapshot["product_types"]
            raise

    def _resolve_source_item_gate_facts_inner(
        self,
        *,
        source_item_id: str,
        revision_hash: str,
        gate_facts: dict[str, Any],
        assessment_schema_version: str,
        reviewer: str,
        memo: str | None,
    ) -> GateFactsResult:
        now = self._clock()
        v_hash = (revision_hash or "").strip()
        v_reviewer = (reviewer or "").strip()
        v_schema = (assessment_schema_version or "").strip()
        v_memo = (memo or "").strip() or None
        if not source_item_id:
            raise RpcFailure("source_item_not_found")
        if len(v_hash) != 64 or any(ch not in "0123456789abcdef" for ch in v_hash):
            raise RpcFailure("revision_mismatch")
        if not (1 <= len(v_reviewer) <= 128):
            raise RpcFailure("invalid_reviewer")
        if v_memo is not None and len(v_memo) > 500:
            raise RpcFailure("invalid_memo")
        if v_schema != GATE_FACTS_SCHEMA_VERSION:
            raise RpcFailure("invalid_assessment_schema_version")
        item = self._item_by_id(source_item_id)
        if item.revision_hash != v_hash:
            raise RpcFailure("revision_mismatch")
        row = self._product_type_row(item.id, v_hash)
        if row is None:
            raise RpcFailure("product_type_not_confirmed")
        try:
            parsed_facts = parse_gate_facts(row.product_type, gate_facts)
        except InvalidGateFacts as exc:
            raise RpcFailure(exc.code) from None
        ai_job = self._job_for(item.id, v_hash, AI_STAGE)
        if ai_job is not None and self._is_live_claimed(ai_job, now):
            raise RpcFailure("ai_job_claimed")
        row.gate_facts = parsed_facts.to_payload()
        row.assessment_schema_version = GATE_FACTS_SCHEMA_VERSION
        row.evaluated_profile = CAPITAL_V1_PROFILE
        row.evaluated_at = now
        row.reviewer = v_reviewer
        row.memo = v_memo
        row.updated_at = now
        authority = evaluate_capital_v1(
            body_usable=item.body_usable,
            has_source_url=item.has_source_url,
            attachment_present=item.attachment_present,
            product_type=row.product_type,
            product_type_reasons=row.reason_codes,
            facts=row.gate_facts,
        )
        self._apply_evaluation_authority(item, authority, now)
        review_job = None
        for stage in (
            "content_review",
            "region_review",
            RELEVANCE_REVIEW_STAGE,
            PRODUCT_TYPE_REVIEW_STAGE,
        ):
            found = self._job_for(item.id, v_hash, stage)
            if found is not None and found.status in {"queued", "claimed"}:
                review_job = found
                break
        ai_job = self._job_for(item.id, v_hash, AI_STAGE)
        return GateFactsResult(
            source_item_id=item.id,
            revision_hash=v_hash,
            product_type=row.product_type,
            disposition=item.disposition,
            assessment_schema_version=GATE_FACTS_SCHEMA_VERSION,
            evaluated_profile=CAPITAL_V1_PROFILE,
            ai_job_id=None if ai_job is None else ai_job.id,
            ai_job_status=None if ai_job is None else ai_job.status,
            review_job_id=None if review_job is None else review_job.id,
            review_job_status=None if review_job is None else review_job.status,
            action_result="confirmed",
        )

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

    def _item_by_id(self, item_id: str) -> _Item:
        for item in self.items.values():
            if item.id == item_id:
                return item
        raise RpcFailure("source_item_not_found")

    def _job_for(
        self, item_id: str, revision_hash: str, stage: str
    ) -> _Job | None:
        for job in self.jobs.values():
            if (
                job.source_item_id == item_id
                and job.revision_hash == revision_hash
                and job.processing_stage == stage
            ):
                return job
        return None

    def _has_approve_ai(self, item_id: str, revision_hash: str) -> bool:
        return any(
            row.source_item_id == item_id
            and row.revision_hash == revision_hash
            and row.decision == "approve_ai"
            for row in self.decisions.values()
        )

    def _has_confirmed_product_type(self, item_id: str, revision_hash: str) -> bool:
        return (item_id, revision_hash) in self.product_types

    def _ai_job_is_claim_ready(self, job: _Job, now: datetime) -> bool:
        if job.status == "queued":
            return job.available_at <= now and (
                job.next_retry_at is None or job.next_retry_at <= now
            )
        if job.status == "claimed":
            return (
                job.claim_lease_until is not None and job.claim_lease_until <= now
            )
        return False

    def _has_unresolved_blocking_review(
        self, item_id: str, revision_hash: str
    ) -> bool:
        return any(
            row.source_item_id == item_id
            and row.revision_hash == revision_hash
            and row.processing_stage in BLOCKING_REVIEW_STAGES
            and row.status in UNRESOLVED_REVIEW_STATUSES
            for row in self.jobs.values()
        )

    def _claimable_item_for_ai_job(self, job: _Job) -> _Item | None:
        item = next(
            (value for value in self.items.values() if value.id == job.source_item_id),
            None,
        )
        if item is None:
            return None
        if item.revision_hash != job.revision_hash:
            return None
        if self._legacy_ai_ready(item, job.revision_hash):
            return item
        if self._v1_ai_ready(item, job.revision_hash):
            return item
        return None

    def _product_type_row(self, item_id: str, revision_hash: str) -> _ProductType | None:
        return self.product_types.get((item_id, revision_hash))

    def _is_legacy_product_type_row(self, row: _ProductType) -> bool:
        return is_legacy_facts_row(
            gate_facts=row.gate_facts,
            assessment_schema_version=row.assessment_schema_version,
            evaluated_profile=row.evaluated_profile,
            evaluated_at=row.evaluated_at,
        )

    def _is_v1_complete_product_type_row(self, row: _ProductType) -> bool:
        return is_complete_v1_facts(
            product_type=row.product_type,
            gate_facts=row.gate_facts,
            assessment_schema_version=row.assessment_schema_version,
            evaluated_profile=row.evaluated_profile,
            evaluated_at=row.evaluated_at,
            expected_profile=CAPITAL_V1_PROFILE,
        )

    def _legacy_ai_ready(self, item: _Item, revision_hash: str) -> bool:
        if item.disposition != "target":
            return False
        if item.revision_hash != revision_hash:
            return False
        if not item.body_usable or not item.has_source_url:
            return False
        row = self._product_type_row(item.id, revision_hash)
        if row is None or not self._is_legacy_product_type_row(row):
            return False
        if not self._has_approve_ai(item.id, revision_hash):
            return False
        if self._has_unresolved_blocking_review(item.id, revision_hash):
            return False
        return True

    def _v1_ai_ready(self, item: _Item, revision_hash: str) -> bool:
        if item.disposition != "target":
            return False
        if item.revision_hash != revision_hash:
            return False
        if not item.body_usable or not item.has_source_url:
            return False
        row = self._product_type_row(item.id, revision_hash)
        if row is None or not self._is_v1_complete_product_type_row(row):
            return False
        if self._has_unresolved_blocking_review(item.id, revision_hash):
            return False
        try:
            evaluation = evaluate_capital_v1(
                body_usable=item.body_usable,
                has_source_url=item.has_source_url,
                attachment_present=item.attachment_present,
                product_type=row.product_type,
                product_type_reasons=row.reason_codes,
                facts=row.gate_facts,
            )
        except InvalidGateFacts:
            return False
        return evaluation.disposition == "target"

    def _has_review_decision(
        self, item_id: str, revision_hash: str, review_type: str, decision: str
    ) -> bool:
        row = self.decisions.get((item_id, revision_hash, review_type))
        return row is not None and row.decision == decision

    def _has_reject_decision(self, item_id: str, revision_hash: str) -> bool:
        return any(
            row.source_item_id == item_id
            and row.revision_hash == revision_hash
            and row.decision == "reject"
            for row in self.decisions.values()
        )

    def _can_promote_to_target(
        self, item: _Item, revision_hash: str, region_scope: str
    ) -> bool:
        if item.revision_hash != revision_hash:
            return False
        if not item.body_usable or not item.has_source_url:
            return False
        if item.disposition in FORBIDDEN_PROMOTE_DISPOSITIONS:
            return False
        if region_scope not in APPROVE_REGION_SCOPES:
            return False
        if not self._has_review_decision(item.id, revision_hash, "region", "approve_ai"):
            return False
        if not self._has_review_decision(
            item.id, revision_hash, "relevance", "approve_ai"
        ):
            return False
        if self._has_reject_decision(item.id, revision_hash):
            return False
        if self._has_unresolved_blocking_review(item.id, revision_hash):
            return False
        return True

    def _can_ensure_ai_job(self, item: _Item, revision_hash: str) -> bool:
        if self._has_reject_decision(item.id, revision_hash):
            return False
        return self._legacy_ai_ready(item, revision_hash)

    def _can_ensure_ai_job_v1(self, item: _Item, revision_hash: str) -> bool:
        return self._v1_ai_ready(item, revision_hash)

    def _requeue_ai_job(
        self, job: _Job, now: datetime, reasons: tuple[str, ...]
    ) -> None:
        job.status = "queued"
        job.available_at = now
        job.claimed_by = None
        job.claim_lease_until = None
        job.claimed_at = None
        job.next_retry_at = None
        job.reason_codes = reasons

    def _ensure_queued_ai_job(
        self,
        item: _Item,
        revision_hash: str,
        now: datetime,
        reasons: tuple[str, ...],
    ) -> None:
        job = self._job_for(item.id, revision_hash, AI_STAGE)
        if job is not None and self._is_malformed_claimed(job):
            if self._can_ensure_ai_job(item, revision_hash):
                raise RpcFailure("ai_job_malformed_lease")
            return
        if not self._can_ensure_ai_job(item, revision_hash):
            return
        if job is None:
            self._insert_job(item.id, revision_hash, AI_STAGE, now, reasons)
            return
        if job.status == "cancelled":
            self._requeue_ai_job(job, now, reasons)
            return
        if self._is_lease_expired_claimed(job, now):
            self._requeue_ai_job(job, now, reasons)

    def _ensure_queued_ai_job_v1(
        self,
        item: _Item,
        revision_hash: str,
        now: datetime,
        reasons: tuple[str, ...],
    ) -> None:
        job = self._job_for(item.id, revision_hash, AI_STAGE)
        if job is not None and self._is_malformed_claimed(job):
            if self._can_ensure_ai_job_v1(item, revision_hash):
                raise RpcFailure("ai_job_malformed_lease")
            return
        if not self._can_ensure_ai_job_v1(item, revision_hash):
            if job is not None and (
                job.status == "queued" or self._is_lease_expired_claimed(job, now)
            ):
                self._cancel_ai_job(job, reasons or ("v1_not_ai_ready",))
            return
        if job is None:
            self._insert_job(item.id, revision_hash, AI_STAGE, now, reasons)
            return
        if job.status == "cancelled":
            self._requeue_ai_job(job, now, reasons)
            return
        if self._is_lease_expired_claimed(job, now):
            self._requeue_ai_job(job, now, reasons)

    def _job_revision_is_current(self, job: _Job) -> bool:
        item = next(
            (value for value in self.items.values() if value.id == job.source_item_id),
            None,
        )
        return item is not None and item.revision_hash == job.revision_hash

    def _is_live_claimed(self, job: _Job, now: datetime) -> bool:
        return (
            job.status == "claimed"
            and job.claim_lease_until is not None
            and job.claim_lease_until > now
        )

    def _is_lease_expired_claimed(self, job: _Job, now: datetime) -> bool:
        return (
            job.status == "claimed"
            and job.claim_lease_until is not None
            and job.claim_lease_until <= now
        )

    def _is_malformed_claimed(self, job: _Job) -> bool:
        return job.status == "claimed" and job.claim_lease_until is None

    def _complete_mapped_review_job(
        self, item_id: str, revision_hash: str, stage: str, now: datetime
    ) -> None:
        if stage not in {
            "region_review",
            RELEVANCE_REVIEW_STAGE,
            "content_review",
        }:
            raise RpcFailure("invalid_review_type")
        job = self._job_for(item_id, revision_hash, stage)
        if job is not None and job.status in {"queued", "claimed"}:
            job.status = "completed"
            job.completed_at = now
            job.claimed_by = None
            job.claim_lease_until = None

    def _cancel_ai_job(self, job: _Job, reasons: tuple[str, ...]) -> None:
        job.status = "cancelled"
        job.claimed_by = None
        job.claim_lease_until = None
        job.claimed_at = None
        job.next_retry_at = None
        job.reason_codes = reasons

    def _insert_job(
        self,
        item_id: str,
        revision_hash: str,
        stage: str,
        now: datetime,
        reasons: tuple[str, ...],
    ) -> _Job:
        job = _Job(
            id=str(uuid.uuid4()),
            source_item_id=item_id,
            revision_hash=revision_hash,
            processing_stage=stage,
            status="queued",
            queued_at=now,
            available_at=now,
            reason_codes=reasons,
        )
        self.jobs[job.id] = job
        return job

    def _require_claimed_ai_job(self, job_id: str, worker_id: str) -> _Job:
        now = self._clock()
        job = self.jobs.get(job_id)
        if job is None:
            raise ValueError("job not found")
        if job.processing_stage != AI_STAGE:
            raise ValueError("human_job_not_completable_by_ai")
        if job.status != "claimed":
            raise ValueError("unexpected_job_status")
        if job.claimed_by != worker_id:
            raise LeaseLost()
        if job.claim_lease_until is None or job.claim_lease_until <= now:
            raise LeaseLost()
        return job

    def _require_active_lease(self, source_id: str, run_id: str, now: datetime) -> None:
        sync = self.sync[source_id]
        if (
            sync.active_run_id != run_id
            or sync.lease_owner != run_id
            or sync.lease_expires_at is None
            or sync.lease_expires_at <= now
        ):
            raise LeaseLost()

    def _reject_v2_input(self, record: ObservationRecord) -> None:
        if any(job.stage == AI_STAGE for job in record.jobs):
            raise RpcFailure("ai_job_not_allowed_in_upsert")
        meta = record.classifier_decision
        if record.disposition != "target":
            if meta is not None:
                raise RpcFailure("classifier_metadata_forbidden")
            return
        if meta is not None:
            self._parsed_classifier_decision(meta)

    def _reject_v3_input(self, record: ObservationRecord) -> None:
        self._reject_v2_input(record)
        if any(job.stage == PRODUCT_TYPE_REVIEW_STAGE for job in record.jobs):
            raise RpcFailure("product_type_review_not_allowed_in_upsert")
        meta = record.product_type_classification
        if record.disposition != "target":
            if meta is not None:
                raise RpcFailure("product_type_metadata_forbidden")
            return
        if meta is not None:
            self._parsed_product_type_classification(meta)

    def _reject_v4_input(self, record: ObservationRecord) -> None:
        if any(job.stage == AI_STAGE for job in record.jobs):
            raise RpcFailure("ai_job_not_allowed_in_upsert")
        if any(job.stage == PRODUCT_TYPE_REVIEW_STAGE for job in record.jobs):
            raise RpcFailure("product_type_review_not_allowed_in_upsert")
        if record.classifier_decision is not None:
            raise RpcFailure("classifier_metadata_forbidden")
        allowed_jobs = {"relationship_review"}
        extra_jobs = [job.stage for job in record.jobs if job.stage not in allowed_jobs]
        if extra_jobs:
            raise RpcFailure("invalid_classifier_decision")
        if record.product_type_classification is not None:
            self._parsed_product_type_classification(record.product_type_classification)

    def _parsed_product_type_classification(self, raw: object) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise RpcFailure("invalid_product_type_classification")
        extra = set(raw) - PRODUCT_TYPE_CLASSIFICATION_KEYS
        if extra:
            raise RpcFailure("invalid_product_type_classification")
        kind = str(raw.get("kind") or "").strip()
        if kind not in {PRODUCT_TYPE_KIND_CONFIRMED, PRODUCT_TYPE_KIND_REVIEW}:
            raise RpcFailure("invalid_product_type_classification")
        reasons_raw = raw.get("reason_codes", ())
        if reasons_raw is None:
            reasons_raw = ()
        if not isinstance(reasons_raw, (list, tuple)):
            raise RpcFailure("invalid_product_type_classification")
        signals_raw = raw.get("period_signals", ())
        if signals_raw is None:
            signals_raw = ()
        if not isinstance(signals_raw, (list, tuple)):
            raise RpcFailure("invalid_period_signals")
        rule_version = str(raw.get("rule_version") or "").strip()
        if not (1 <= len(rule_version) <= 64):
            raise RpcFailure("invalid_rule_version")
        if kind == PRODUCT_TYPE_KIND_REVIEW:
            if "product_type" in raw:
                raise RpcFailure("invalid_product_type")
            return {
                "kind": kind,
                "product_type": None,
                "reason_codes": tuple(str(code) for code in reasons_raw),
                "period_signals": tuple(str(signal) for signal in signals_raw),
                "rule_version": rule_version,
            }
        confirmed = str(raw.get("product_type") or "").strip()
        if confirmed not in PRODUCT_TYPES:
            raise RpcFailure("invalid_product_type")
        return {
            "kind": kind,
            "product_type": confirmed,
            "reason_codes": tuple(str(code) for code in reasons_raw),
            "period_signals": tuple(str(signal) for signal in signals_raw),
            "rule_version": rule_version,
        }

    def _parsed_classifier_decision(self, raw: object) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise RpcFailure("invalid_classifier_decision")
        extra = set(raw) - CLASSIFIER_DECISION_KEYS
        if extra:
            raise RpcFailure("invalid_classifier_decision")
        decision = str(raw.get("decision") or "").strip()
        if decision != "approve_ai":
            raise RpcFailure("invalid_classifier_decision")
        review_type = str(raw.get("review_type") or "").strip()
        if review_type != "relevance":
            raise RpcFailure("invalid_review_type")
        region_scope = str(raw.get("region_scope") or "").strip()
        if region_scope not in APPROVE_REGION_SCOPES:
            raise RpcFailure("invalid_region_scope")
        axes_raw = raw.get("audience_relevance")
        if not isinstance(axes_raw, (list, tuple)):
            raise RpcFailure("invalid_audience_relevance")
        axes = tuple(str(axis) for axis in axes_raw)
        if any(axis not in AUDIENCE_AXES for axis in axes):
            raise RpcFailure("invalid_audience_relevance")
        if not axes:
            raise RpcFailure("approve_requirements_not_met")
        reasons_raw = raw.get("reason_codes", ())
        if reasons_raw is None:
            reasons_raw = ()
        if not isinstance(reasons_raw, (list, tuple)):
            raise RpcFailure("invalid_classifier_decision")
        rule_version = str(raw.get("rule_version") or "").strip()
        if not (1 <= len(rule_version) <= 64):
            raise RpcFailure("invalid_rule_version")
        return {
            "decision": decision,
            "review_type": review_type,
            "region_scope": region_scope,
            "audience_relevance": axes,
            "reason_codes": tuple(str(code) for code in reasons_raw),
            "rule_version": rule_version,
        }

    def _apply_classifier_approvals(
        self,
        source_id: str,
        records: list[ObservationRecord],
        results: list[ObservationResult],
    ) -> None:
        for record, result in zip(records, results):
            if result.duplicate_in_batch:
                continue
            if result.outcome not in {"new", "changed"}:
                continue
            if record.disposition != "target":
                continue
            if record.classifier_decision is None:
                raise RpcFailure("classifier_metadata_required")
            parsed = self._parsed_classifier_decision(record.classifier_decision)
            item = self.items[(source_id, record.external_key)]
            if item.revision_hash != record.revision_hash:
                raise RpcFailure("revision_mismatch")
            self._apply_ingest_review_decision(
                source_item_id=item.id,
                revision_hash=item.revision_hash,
                review_type=parsed["review_type"],
                decision=parsed["decision"],
                region_scope=parsed["region_scope"],
                audience_relevance=parsed["audience_relevance"],
                reason_codes=parsed["reason_codes"],
                rule_version=parsed["rule_version"],
                reviewer=f"{CLASSIFIER_REVIEWER_PREFIX}{parsed['rule_version']}",
            )

    def _apply_product_type_classifications(
        self,
        source_id: str,
        records: list[ObservationRecord],
        results: list[ObservationResult],
    ) -> None:
        for record, result in zip(records, results):
            if result.duplicate_in_batch:
                continue
            if result.outcome not in {"new", "changed"}:
                continue
            item = self.items[(source_id, record.external_key)]
            if item.revision_hash != record.revision_hash:
                raise RpcFailure("revision_mismatch")
            self._apply_source_item_product_type(item, record)
            if self._fail_after_product_type:
                raise RpcFailure("decision_conflict")

    def _apply_source_item_product_type(
        self, item: _Item, record: ObservationRecord
    ) -> None:
        if self._fail_product_type_core:
            raise RpcFailure("decision_conflict")
        key = (item.id, item.revision_hash)
        if key in self.product_types:
            return
        if record.disposition != "target":
            return
        if record.product_type_classification is None:
            raise RpcFailure("product_type_metadata_required")
        parsed = self._parsed_product_type_classification(
            record.product_type_classification
        )
        source = self.sources[item.source_id]
        now = self._clock()
        if source.source_kind == SOURCE_KIND_CONTENT:
            if (
                parsed["kind"] != PRODUCT_TYPE_KIND_CONFIRMED
                or parsed["product_type"] != PRODUCT_TYPE_EVENT_PROGRAM
            ):
                raise RpcFailure("content_product_type_locked")
            self._insert_product_type(
                item,
                parsed,
                origin=PRODUCT_TYPE_ORIGIN_CLASSIFIER,
                reviewer=f"{CLASSIFIER_REVIEWER_PREFIX}{parsed['rule_version']}",
                memo=None,
                now=now,
            )
            return
        if parsed["kind"] == PRODUCT_TYPE_KIND_REVIEW:
            self._ensure_product_type_review_job(
                item.id, item.revision_hash, now, parsed["reason_codes"]
            )
            return
        self._insert_product_type(
            item,
            parsed,
            origin=PRODUCT_TYPE_ORIGIN_CLASSIFIER,
            reviewer=f"{CLASSIFIER_REVIEWER_PREFIX}{parsed['rule_version']}",
            memo=None,
            now=now,
        )

    def _insert_product_type(
        self,
        item: _Item,
        parsed: dict[str, Any],
        *,
        origin: str,
        reviewer: str,
        memo: str | None,
        now: datetime,
        gate_facts: dict[str, Any] | None = None,
        assessment_schema_version: str | None = None,
        evaluated_profile: str | None = None,
        evaluated_at: datetime | None = None,
    ) -> _ProductType:
        row = _ProductType(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            product_type=parsed["product_type"],
            origin=origin,
            rule_version=parsed["rule_version"],
            reason_codes=parsed["reason_codes"],
            period_signals=parsed["period_signals"],
            reviewer=reviewer,
            memo=memo,
            created_at=now,
            updated_at=now,
            gate_facts=None if gate_facts is None else dict(gate_facts),
            assessment_schema_version=assessment_schema_version,
            evaluated_profile=evaluated_profile,
            evaluated_at=evaluated_at,
        )
        self.product_types[(item.id, item.revision_hash)] = row
        return row

    def _apply_v4_product_types(
        self,
        source_id: str,
        records: list[ObservationRecord],
        results: list[ObservationResult],
        now: datetime,
    ) -> None:
        for record, result in zip(records, results):
            if result.duplicate_in_batch:
                continue
            if result.outcome not in {"new", "changed"}:
                continue
            item = self.items[(source_id, record.external_key)]
            if item.revision_hash != record.revision_hash:
                raise RpcFailure("revision_mismatch")
            key = (item.id, item.revision_hash)
            if key in self.product_types:
                self._ensure_queued_ai_job_v1(item, item.revision_hash, now, ())
                continue
            if record.product_type_classification is None:
                self._ensure_queued_ai_job_v1(item, item.revision_hash, now, ())
                continue
            parsed = self._parsed_product_type_classification(
                record.product_type_classification
            )
            if parsed["kind"] == PRODUCT_TYPE_KIND_REVIEW:
                self._ensure_queued_ai_job_v1(item, item.revision_hash, now, ())
                continue
            if record.gate_facts is None:
                raise RpcFailure("invalid_gate_facts")
            try:
                facts = parse_gate_facts(parsed["product_type"], record.gate_facts)
            except InvalidGateFacts as exc:
                raise RpcFailure(exc.code) from None
            self._insert_product_type(
                item,
                parsed,
                origin=PRODUCT_TYPE_ORIGIN_CLASSIFIER,
                reviewer=f"{CLASSIFIER_REVIEWER_PREFIX}{parsed['rule_version']}",
                memo=None,
                now=now,
                gate_facts=facts.to_payload(),
                assessment_schema_version=GATE_FACTS_SCHEMA_VERSION,
                evaluated_profile=CAPITAL_V1_PROFILE,
                evaluated_at=now,
            )
            persisted = self.product_types[key]
            authority = evaluate_capital_v1(
                body_usable=item.body_usable,
                has_source_url=item.has_source_url,
                attachment_present=item.attachment_present,
                product_type=persisted.product_type,
                product_type_reasons=persisted.reason_codes,
                facts=persisted.gate_facts,
            )
            self._apply_evaluation_authority(item, authority, now)

    def _assert_content_reject_ready(
        self, item: _Item, revision_hash: str, now: datetime
    ) -> None:
        review = self._job_for(item.id, revision_hash, "content_review")
        if review is None or review.status not in {"queued", "claimed"}:
            raise RpcFailure("content_review_not_open")
        ai_job = self._job_for(item.id, revision_hash, AI_STAGE)
        if ai_job is not None and self._is_malformed_claimed(ai_job):
            raise RpcFailure("ai_job_malformed_lease")
        if ai_job is not None and self._is_live_claimed(ai_job, now):
            raise RpcFailure("ai_job_claimed")
        sources = {item.source_id, curation_source_for_enqueue(item.source_id)}
        if any(
            candidate.source in sources
            and candidate.source_item_id == item.external_key
            and candidate.source_revision_hash == revision_hash
            for candidate in self.candidates
        ):
            raise RpcFailure("curation_candidate_exists")

    def _content_close_pins(self, item: _Item) -> bool:
        row = self.decisions.get((item.id, item.revision_hash, "content"))
        return (
            row is not None
            and row.decision == "reject"
            and "insufficient_evidence" in row.reason_codes
        )

    def _apply_evaluation_authority(
        self,
        item: _Item,
        authority: EvaluationResult,
        now: datetime,
        fallback_reasons: tuple[str, ...] = (),
    ) -> None:
        reasons = (
            authority.jobs[0].reason_codes if authority.jobs else fallback_reasons
        )
        if self._content_close_pins(item):
            authority = EvaluationResult(
                disposition="non_target",
                jobs=(),
                region_status="not_applicable",
                audience_status="not_applicable",
            )
            reasons = ("insufficient_evidence",)
        item.disposition = authority.disposition
        self._sync_v1_jobs_from_evaluation(item, authority, now)
        self._ensure_queued_ai_job_v1(item, item.revision_hash, now, reasons)

    def _sync_v1_jobs_from_evaluation(
        self, item: _Item, evaluation: Any, now: datetime
    ) -> None:
        wanted = {job.stage: job.reason_codes for job in evaluation.jobs}
        for stage in (
            "region_review",
            RELEVANCE_REVIEW_STAGE,
            PRODUCT_TYPE_REVIEW_STAGE,
            "content_review",
        ):
            job = self._job_for(item.id, item.revision_hash, stage)
            if stage in wanted:
                if job is None:
                    self._insert_job(
                        item.id, item.revision_hash, stage, now, wanted[stage]
                    )
                elif job.status not in {"queued", "claimed"}:
                    job.status = "queued"
                    job.available_at = now
                    job.claimed_by = None
                    job.claim_lease_until = None
                    job.completed_at = None
                    job.next_retry_at = None
                    job.reason_codes = wanted[stage]
            elif job is not None and job.status in {"queued", "claimed"}:
                job.status = "completed"
                job.completed_at = now
                job.claimed_by = None
                job.claim_lease_until = None

    def _ensure_product_type_review_job(
        self,
        item_id: str,
        revision_hash: str,
        now: datetime,
        reasons: tuple[str, ...],
    ) -> _Job:
        job = self._job_for(item_id, revision_hash, PRODUCT_TYPE_REVIEW_STAGE)
        if job is None:
            return self._insert_job(
                item_id, revision_hash, PRODUCT_TYPE_REVIEW_STAGE, now, reasons
            )
        if job.status != "queued":
            job.status = "queued"
            job.available_at = now
            job.claimed_by = None
            job.claim_lease_until = None
            job.completed_at = None
            job.next_retry_at = None
            job.reason_codes = reasons
        return job

    def _complete_product_type_review_job(
        self, item_id: str, revision_hash: str, now: datetime
    ) -> None:
        job = self._job_for(item_id, revision_hash, PRODUCT_TYPE_REVIEW_STAGE)
        if job is not None and job.status in {"queued", "claimed"}:
            job.status = "completed"
            job.completed_at = now
            job.claimed_by = None
            job.claim_lease_until = None

    def _reevaluate_confirmed_product_type(
        self,
        item: _Item,
        row: _ProductType,
        now: datetime,
        reasons: tuple[str, ...],
    ) -> None:
        authority = evaluate_capital_v1(
            body_usable=item.body_usable,
            has_source_url=item.has_source_url,
            attachment_present=item.attachment_present,
            product_type=row.product_type,
            product_type_reasons=row.reason_codes,
            facts=row.gate_facts,
        )
        self._apply_evaluation_authority(item, authority, now, reasons)

    def _resolve_source_item_product_type_inner(
        self,
        *,
        source_item_id: str,
        revision_hash: str,
        action: str,
        product_type: str | None,
        reason_codes: tuple[str, ...] | list[str],
        period_signals: tuple[str, ...] | list[str],
        rule_version: str,
        reviewer: str,
        memo: str | None,
    ) -> ProductTypeResult:
        now = self._clock()
        v_hash = (revision_hash or "").strip()
        v_action = (action or "").strip()
        v_type = (product_type or "").strip() or None
        v_rule = (rule_version or "").strip()
        v_reviewer = (reviewer or "").strip()
        v_memo = (memo or "").strip() or None
        reasons = tuple(reason_codes)
        signals = tuple(period_signals)
        if not source_item_id:
            raise RpcFailure("source_item_not_found")
        if len(v_hash) != 64 or any(ch not in "0123456789abcdef" for ch in v_hash):
            raise RpcFailure("revision_mismatch")
        if v_action not in PRODUCT_TYPE_ACTIONS:
            raise RpcFailure("invalid_product_type_action")
        if v_action in {PRODUCT_TYPE_ACTION_CONFIRM, PRODUCT_TYPE_ACTION_OVERRIDE}:
            if v_type not in PRODUCT_TYPES:
                raise RpcFailure("invalid_product_type")
        if not (1 <= len(v_rule) <= 64):
            raise RpcFailure("invalid_rule_version")
        if not (1 <= len(v_reviewer) <= 128):
            raise RpcFailure("invalid_reviewer")
        if v_memo is not None and len(v_memo) > 500:
            raise RpcFailure("invalid_memo")

        item = self._item_by_id(source_item_id)
        if item.revision_hash != v_hash:
            raise RpcFailure("revision_mismatch")
        if item.source_id not in self.sources:
            raise RpcFailure("source_not_found")

        key = (item.id, v_hash)
        existing = self.product_types.get(key)
        kind = self._classify_product_type_request(v_action, existing, v_type)
        if kind == "no-op":
            return self._product_type_result(item, v_hash, "no-op")
        if kind == "reject":
            raise RpcFailure("decision_conflict")

        ai_job = self._job_for(item.id, v_hash, AI_STAGE)
        if ai_job is not None and self._is_live_claimed(ai_job, now):
            raise RpcFailure("ai_job_claimed")
        if v_action in {PRODUCT_TYPE_ACTION_OVERRIDE, PRODUCT_TYPE_ACTION_ROLLBACK}:
            if v_memo is None:
                raise RpcFailure("invalid_memo")

        parsed = {
            "kind": PRODUCT_TYPE_KIND_CONFIRMED,
            "product_type": v_type,
            "reason_codes": reasons,
            "period_signals": signals,
            "rule_version": v_rule,
        }
        action_result = "confirmed"
        if v_action == PRODUCT_TYPE_ACTION_CONFIRM:
            self._insert_product_type(
                item,
                parsed,
                origin=PRODUCT_TYPE_ORIGIN_HUMAN,
                reviewer=v_reviewer,
                memo=v_memo,
                now=now,
            )
            self._complete_product_type_review_job(item.id, v_hash, now)
            row = self._product_type_row(item.id, v_hash)
            if row is not None and self._is_v1_complete_product_type_row(row):
                self._reevaluate_confirmed_product_type(item, row, now, reasons)
            else:
                self._ensure_queued_ai_job(item, v_hash, now, reasons)
            action_result = "confirmed"
        elif v_action == PRODUCT_TYPE_ACTION_OVERRIDE:
            existing.product_type = v_type  # type: ignore[union-attr]
            existing.origin = PRODUCT_TYPE_ORIGIN_HUMAN  # type: ignore[union-attr]
            existing.rule_version = v_rule  # type: ignore[union-attr]
            existing.reason_codes = reasons  # type: ignore[union-attr]
            existing.period_signals = signals  # type: ignore[union-attr]
            existing.reviewer = v_reviewer  # type: ignore[union-attr]
            existing.memo = v_memo  # type: ignore[union-attr]
            existing.updated_at = now  # type: ignore[union-attr]
            self._complete_product_type_review_job(item.id, v_hash, now)
            row = self._product_type_row(item.id, v_hash)
            if row is not None and self._is_v1_complete_product_type_row(row):
                self._reevaluate_confirmed_product_type(item, row, now, reasons)
            else:
                self._ensure_queued_ai_job(item, v_hash, now, reasons)
            action_result = "overridden"
        else:
            del self.product_types[key]
            self._ensure_product_type_review_job(item.id, v_hash, now, reasons)
            ai_job = self._job_for(item.id, v_hash, AI_STAGE)
            if ai_job is not None and (
                ai_job.status == "queued"
                or self._is_lease_expired_claimed(ai_job, now)
            ):
                self._cancel_ai_job(ai_job, reasons or ("product_type_rollback",))
            action_result = "rolled_back"
        return self._product_type_result(item, v_hash, action_result)

    def _classify_product_type_request(
        self,
        action: str,
        existing: _ProductType | None,
        requested: str | None,
    ) -> str:
        if action == PRODUCT_TYPE_ACTION_CONFIRM:
            if existing is None:
                return "mutate"
            if existing.product_type == requested:
                return "no-op"
            return "reject"
        if action == PRODUCT_TYPE_ACTION_OVERRIDE:
            if existing is None:
                return "reject"
            if existing.product_type == requested:
                return "no-op"
            return "mutate"
        if existing is None:
            return "no-op"
        return "mutate"

    def _product_type_result(
        self, item: _Item, revision_hash: str, action_result: str
    ) -> ProductTypeResult:
        row = self.product_types.get((item.id, revision_hash))
        review_job = self._job_for(item.id, revision_hash, PRODUCT_TYPE_REVIEW_STAGE)
        ai_job = self._job_for(item.id, revision_hash, AI_STAGE)
        return ProductTypeResult(
            source_item_id=item.id,
            revision_hash=revision_hash,
            product_type=None if row is None else row.product_type,
            origin=None if row is None else row.origin,
            review_job_id=None if review_job is None else review_job.id,
            review_job_status=None if review_job is None else review_job.status,
            ai_job_id=None if ai_job is None else ai_job.id,
            ai_job_status=None if ai_job is None else ai_job.status,
            action_result=action_result,
        )


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
