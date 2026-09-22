"""수집 공통 모델. orchestrator는 페이지 번호를 알지 않는다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol

StartMode = Literal["fresh_from_origin", "resume_committed"]
# Orchestrator processing policy, not an official source sort guarantee.
OrderingCapability = Literal["require_descending", "untrusted"]
OrderingDiagnostic = Literal["missing_stamp", "non_monotonic_stamp"]
ORDERING_CAPABILITIES: frozenset[str] = frozenset(
    {"require_descending", "untrusted"}
)
ORDERING_DIAGNOSTIC_ORDER: tuple[str, ...] = (
    "missing_stamp",
    "non_monotonic_stamp",
)
Disposition = Literal[
    "target",
    "non_target",
    "region_review_required",
    "observe_only",
    "attachment_dependent",
]
RegionScope = Literal[
    "capital",
    "nationwide_or_online",
    "noncapital",
    "unknown",
]
REASON_REGION_SCOPE_UNKNOWN = "region_scope_unknown"
REASON_RELEVANCE_UNCONFIRMED = "relevance_unconfirmed"
ParseStatus = Literal["ok", "missing", "unparsed"]
ProcessingStage = Literal[
    "region_review",
    "content_review",
    "relationship_review",
    "ai_enrichment",
    "relevance_review",
    "product_type_review",
]
ProductType = Literal["event_program", "policy_reference", "living_guide"]
ProductTypeAction = Literal["confirm", "override", "rollback"]
JobStatus = Literal["queued", "claimed", "completed", "failed", "cancelled"]
ReviewType = Literal["region", "relevance", "content", "product_type"]
ReviewDecision = Literal["approve_ai", "reject", "needs_review"]
ReconcileAction = Literal["keep_with_approve", "cancel_unfit", "move_to_review"]
REVIEW_TYPES: frozenset[str] = frozenset(
    {"region", "relevance", "content", "product_type"}
)
REVIEW_DECISIONS: frozenset[str] = frozenset(
    {"approve_ai", "reject", "needs_review"}
)
RECONCILE_ACTIONS: frozenset[str] = frozenset(
    {"keep_with_approve", "cancel_unfit", "move_to_review"}
)
APPROVE_REGION_SCOPES: frozenset[str] = frozenset(
    {"capital", "nationwide_or_online"}
)
AUDIENCE_AXES: frozenset[str] = frozenset(
    {
        "jp_residents_in_kr",
        "foreign_residents_in_kr",
        "kr_japan_activity",
        "kr_jp_exchange",
    }
)
HUMAN_REVIEW_STAGES: frozenset[str] = frozenset(
    {
        "region_review",
        "content_review",
        "relationship_review",
        "relevance_review",
        "product_type_review",
    }
)
RunStatus = Literal["complete", "incomplete", "failed"]
ObservationOutcome = Literal["new", "changed", "unchanged"]

AI_STAGE: ProcessingStage = "ai_enrichment"
RELEVANCE_REVIEW_STAGE: ProcessingStage = "relevance_review"
PRODUCT_TYPE_REVIEW_STAGE: ProcessingStage = "product_type_review"
CLASSIFIER_DECISION_KEYS: frozenset[str] = frozenset(
    {
        "decision",
        "review_type",
        "region_scope",
        "audience_relevance",
        "reason_codes",
        "rule_version",
    }
)
CLASSIFIER_REVIEWER_PREFIX = "classifier:"

CHECKPOINT_PAGE_KEY = "page_num"


@dataclass(frozen=True)
class Checkpoint:
    """Connector 소유 불투명 checkpoint. orchestrator는 내부를 해석하지 않는다."""

    payload: Mapping[str, Any]

    def to_json(self) -> dict[str, Any]:
        return dict(self.payload)

    @staticmethod
    def from_json(raw: Mapping[str, Any] | None) -> Checkpoint | None:
        if not raw:
            return None
        return Checkpoint(payload=dict(raw))

    @staticmethod
    def for_rest_page(page_num: int) -> Checkpoint:
        return Checkpoint(payload={CHECKPOINT_PAGE_KEY: int(page_num)})

    def rest_page_num(self) -> int | None:
        value = self.payload.get(CHECKPOINT_PAGE_KEY)
        if isinstance(value, int):
            return value
        return None


@dataclass(frozen=True)
class BatchMeta:
    http_status: int | None = None
    response_bytes: int | None = None
    timed_out: bool = False
    request_count_delta: int = 0


@dataclass(frozen=True)
class BatchResult:
    items: tuple[dict[str, Any], ...]
    next_checkpoint: Checkpoint | None
    natural_end: bool
    progress: Mapping[str, Any] = field(default_factory=dict)
    meta: BatchMeta = field(default_factory=BatchMeta)


@dataclass(frozen=True)
class JobPlan:
    stage: ProcessingStage
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelationshipPlan:
    to_source_id: str
    to_external_key: str
    relation_kind: Literal["candidate"] = "candidate"


@dataclass(frozen=True)
class ObservationRecord:
    external_key: str
    revision_hash: str
    disposition: Disposition
    min_fields: dict[str, Any]
    normalized_payload: dict[str, Any] | None
    source_created_at: str | None
    source_created_raw: str | None
    source_created_parse_status: ParseStatus
    source_updated_at: str | None
    source_updated_raw: str | None
    source_updated_parse_status: ParseStatus
    has_source_url: bool
    body_usable: bool
    attachment_present: bool
    attachment_length: int
    is_data_url: bool
    jobs: tuple[JobPlan, ...] = ()
    relationships: tuple[RelationshipPlan, ...] = ()
    classifier_decision: Mapping[str, Any] | None = None
    product_type_classification: Mapping[str, Any] | None = None
    gate_facts: Mapping[str, Any] | None = None
    assessment_schema_version: str | None = None
    evaluated_profile: str | None = None

    def to_rpc_item(self) -> dict[str, Any]:
        payload = {
            "external_key": self.external_key,
            "revision_hash": self.revision_hash,
            "disposition": self.disposition,
            "min_fields": self.min_fields,
            "normalized_payload": self.normalized_payload,
            "source_created_at": self.source_created_at,
            "source_created_raw": self.source_created_raw,
            "source_created_parse_status": self.source_created_parse_status,
            "source_updated_at": self.source_updated_at,
            "source_updated_raw": self.source_updated_raw,
            "source_updated_parse_status": self.source_updated_parse_status,
            "has_source_url": self.has_source_url,
            "body_usable": self.body_usable,
            "attachment_present": self.attachment_present,
            "attachment_length": self.attachment_length,
            "is_data_url": self.is_data_url,
            "jobs": [
                {"stage": job.stage, "reason_codes": list(job.reason_codes)}
                for job in self.jobs
            ],
            "relationships": [
                {
                    "to_source_id": rel.to_source_id,
                    "to_external_key": rel.to_external_key,
                    "relation_kind": rel.relation_kind,
                }
                for rel in self.relationships
            ],
        }
        if self.classifier_decision is not None:
            payload["classifier_decision"] = dict(self.classifier_decision)
        if self.product_type_classification is not None:
            payload["product_type_classification"] = dict(
                self.product_type_classification
            )
        if self.gate_facts is not None:
            payload["gate_facts"] = dict(self.gate_facts)
        if self.assessment_schema_version is not None:
            payload["assessment_schema_version"] = self.assessment_schema_version
        if self.evaluated_profile is not None:
            payload["evaluated_profile"] = self.evaluated_profile
        return payload


@dataclass(frozen=True)
class ObservationResult:
    input_index: int
    external_key: str
    outcome: ObservationOutcome
    duplicate_in_batch: bool = False
    skipped_streak: bool = False


@dataclass(frozen=True)
class StartRunResult:
    run_id: str
    bootstrap_complete: bool
    committed_checkpoint: Checkpoint | None
    skipped: bool = False
    skip_reason: str | None = None


@dataclass(frozen=True)
class FinishRunResult:
    status: str
    stop_reason: str


@dataclass(frozen=True)
class ProductTypeResult:
    source_item_id: str
    revision_hash: str
    product_type: str | None
    origin: str | None
    review_job_id: str | None
    review_job_status: str | None
    ai_job_id: str | None
    ai_job_status: str | None
    action_result: str


@dataclass(frozen=True)
class GateFactsResult:
    source_item_id: str
    revision_hash: str
    product_type: str
    disposition: str
    assessment_schema_version: str
    evaluated_profile: str
    ai_job_id: str | None
    ai_job_status: str | None
    review_job_id: str | None
    review_job_status: str | None
    action_result: str


@dataclass(frozen=True)
class ReviewDecisionResult:
    decision_id: str
    source_item_id: str
    revision_hash: str
    review_type: str
    decision: str
    ai_job_id: str | None
    ai_job_status: str | None
    review_job_id: str | None
    review_job_status: str | None
    action_result: str | None = None


@dataclass(frozen=True)
class ClaimedJob:
    job_id: str
    source_item_id: str
    source_id: str
    external_key: str
    revision_hash: str
    processing_stage: ProcessingStage
    curation_source: str
    normalized_payload: dict[str, Any] | None
    disposition: str


class SourceConnector(Protocol):
    canonical_source_id: str
    provider: str
    source_kind: str
    connector_type: str
    legacy_curation_source: str
    start_mode: StartMode
    page_size: int
    bootstrap_max_pages: int
    bootstrap_max_items: int
    max_pages: int
    http_budget: int
    streak_needed: int
    batch_delay_seconds: float
    # Required. Missing or unknown values fail closed before ingest I/O.
    ordering_capability: OrderingCapability

    def fetch_batch(self, checkpoint: Checkpoint | None) -> BatchResult:
        ...

    def to_observation(
        self,
        item: dict[str, Any],
        *,
        permission_status: str,
        enabled: bool,
    ) -> ObservationRecord:
        ...
