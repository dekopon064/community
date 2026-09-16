"""Supabase public-RPC ingest store. Table DML and private schema calls are forbidden."""

from __future__ import annotations

import re
import uuid
from typing import Any

from ingest.constants import (
    AI_CLAIM_LIMIT,
    DEFAULT_JOB_LEASE_SECONDS,
    DEFAULT_LEASE_SECONDS,
)
from ingest.models import (
    AI_STAGE,
    Checkpoint,
    ClaimedJob,
    FinishRunResult,
    ObservationRecord,
    ObservationResult,
    ProcessingStage,
    ReviewDecisionResult,
    StartRunResult,
)
from ingest.rpc_errors import (
    LEASE_LOST,
    RpcAmbiguous,
    RpcError,
    RpcFailure,
    map_rpc_exception,
    safe_api_message,
)
from ingest.source_identity import ALLOWED_PERMISSION_TRANSITIONS
from ingest.store import LeaseLost

INGEST_RPC_TIMEOUT_SECONDS = 30
STOP_REASON_MAX_LEN = 64
REVISION_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_PERMISSION_STATUSES = frozenset(ALLOWED_PERMISSION_TRANSITIONS)
ALLOWED_SKIP_REASONS = frozenset({"lease_held", "source_disabled"})
ALLOWED_OUTCOMES = frozenset({"new", "changed", "unchanged"})
ALLOWED_RUN_STATUSES = frozenset({"complete", "incomplete", "failed"})

CLAIMED_JOB_FIELDS = (
    "job_id",
    "source_item_id",
    "source_id",
    "external_key",
    "revision_hash",
    "processing_stage",
    "curation_source",
    "normalized_payload",
    "disposition",
)
SOURCE_FIELDS = (
    "source_id",
    "enabled",
    "permission_status",
    "legacy_curation_source",
)
START_FIELDS = (
    "run_id",
    "bootstrap_complete",
    "committed_checkpoint",
    "skipped",
    "skip_reason",
)
UPSERT_FIELDS = (
    "input_index",
    "external_key",
    "outcome",
    "duplicate_in_batch",
)
FINISH_FIELDS = ("status", "stop_reason")
REVIEW_DECISION_FIELDS = (
    "decision_id",
    "source_item_id",
    "revision_hash",
    "review_type",
    "decision",
    "ai_job_id",
    "ai_job_status",
    "review_job_id",
    "review_job_status",
)
RECONCILE_FIELDS = ("action_result",) + REVIEW_DECISION_FIELDS

GET_INGEST_SOURCE = "get_ingest_source"
START_INGEST_RUN = "start_ingest_run"
UPSERT_SOURCE_OBSERVATIONS = "upsert_source_observations_v2"
FINISH_INGEST_RUN = "finish_ingest_run"
CLAIM_PROCESSING_JOBS = "claim_processing_jobs"
COMPLETE_PROCESSING_JOB = "complete_processing_job"
FAIL_PROCESSING_JOB = "fail_processing_job"
RESOLVE_INGEST_REVIEW_DECISION = "resolve_ingest_review_decision"
RECONCILE_QUEUED_AI_JOB = "reconcile_queued_ai_job"


def ingest_client_options(client_options_cls: Any) -> Any:
    return client_options_cls(postgrest_client_timeout=INGEST_RPC_TIMEOUT_SECONDS)


def create_ingest_client(supabase_url: str, supabase_service_key: str) -> Any:
    from supabase import ClientOptions, create_client

    return create_client(
        supabase_url,
        supabase_service_key,
        options=ingest_client_options(ClientOptions),
    )


def _rpc_data(client: Any, name: str, params: dict[str, Any]) -> Any:
    mapped: BaseException | None = None
    try:
        response = client.rpc(name, params).execute()
    except (LeaseLost, RpcError):
        raise
    except Exception as exc:
        message = safe_api_message(exc)
        if message == LEASE_LOST:
            mapped = LeaseLost()
        else:
            mapped = map_rpc_exception(exc)
    if mapped is not None:
        raise mapped
    if not hasattr(response, "data"):
        raise RpcAmbiguous()
    return response.data


def _require_list(data: Any) -> list[Any]:
    if type(data) is list:
        return data
    raise RpcAmbiguous()


def _unwrap_scalar_text(data: Any) -> str:
    if type(data) is str:
        return data
    if type(data) is list:
        if len(data) != 1:
            raise RpcAmbiguous()
        item = data[0]
        if type(item) is str:
            return item
        if type(item) is dict and len(item) == 1:
            value = next(iter(item.values()))
            if type(value) is str:
                return value
        raise RpcAmbiguous()
    raise RpcAmbiguous()


def _one_row(data: Any) -> dict[str, Any]:
    if type(data) is dict:
        return data
    rows = _require_list(data)
    if len(rows) != 1 or type(rows[0]) is not dict:
        raise RpcAmbiguous()
    return rows[0]


def _require_keys(row: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        if key not in row:
            raise RpcAmbiguous()


def _exact_bool(value: Any) -> bool:
    if type(value) is not bool:
        raise RpcAmbiguous()
    return value


def _exact_int(value: Any) -> int:
    if type(value) is not int:
        raise RpcAmbiguous()
    return value


def _exact_str(value: Any) -> str:
    if type(value) is not str:
        raise RpcAmbiguous()
    return value


def _nonempty_str(value: Any) -> str:
    text = _exact_str(value)
    if text == "":
        raise RpcAmbiguous()
    return text


def _uuid_str(value: Any) -> str:
    text = _nonempty_str(value)
    try:
        parsed = uuid.UUID(text)
    except (ValueError, AttributeError, TypeError):
        raise RpcAmbiguous()
    if str(parsed) != text:
        raise RpcAmbiguous()
    return text


def _revision_hash(value: Any) -> str:
    text = _nonempty_str(value)
    if REVISION_HASH_RE.fullmatch(text) is None:
        raise RpcAmbiguous()
    return text


def _optional_uuid(value: Any) -> str | None:
    if value is None:
        return None
    return _uuid_str(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return _exact_str(value)


def _parse_review_decision_row(
    row: dict[str, Any], *, include_action: bool
) -> ReviewDecisionResult:
    keys = RECONCILE_FIELDS if include_action else REVIEW_DECISION_FIELDS
    _require_keys(row, keys)
    action = _exact_str(row["action_result"]) if include_action else None
    if include_action and action == "":
        raise RpcAmbiguous()
    return ReviewDecisionResult(
        decision_id=_uuid_str(row["decision_id"]),
        source_item_id=_uuid_str(row["source_item_id"]),
        revision_hash=_revision_hash(row["revision_hash"]),
        review_type=_nonempty_str(row["review_type"]),
        decision=_nonempty_str(row["decision"]),
        ai_job_id=_optional_uuid(row["ai_job_id"]),
        ai_job_status=_optional_str(row["ai_job_status"]),
        review_job_id=_optional_uuid(row["review_job_id"]),
        review_job_status=_optional_str(row["review_job_status"]),
        action_result=action,
    )


class SupabaseIngestStore:
    def __init__(self, client: Any) -> None:
        self._client = client

    def get_source(self, source_id: str) -> dict[str, Any]:
        data = _rpc_data(
            self._client, GET_INGEST_SOURCE, {"p_source_id": source_id}
        )
        rows = _require_list(data)
        if len(rows) == 0:
            raise RpcFailure("source_not_found")
        if len(rows) != 1 or type(rows[0]) is not dict:
            raise RpcAmbiguous()
        row = rows[0]
        _require_keys(row, SOURCE_FIELDS)
        got_source_id = _nonempty_str(row["source_id"])
        if got_source_id != source_id:
            raise RpcAmbiguous()
        permission = _nonempty_str(row["permission_status"])
        if permission not in ALLOWED_PERMISSION_STATUSES:
            raise RpcAmbiguous()
        return {
            "source_id": got_source_id,
            "enabled": _exact_bool(row["enabled"]),
            "permission_status": permission,
            "legacy_curation_source": _nonempty_str(row["legacy_curation_source"]),
        }

    def start_ingest_run(
        self, source_id: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS
    ) -> StartRunResult:
        data = _rpc_data(
            self._client,
            START_INGEST_RUN,
            {"p_source_id": source_id, "p_lease_seconds": lease_seconds},
        )
        row = _one_row(data)
        _require_keys(row, START_FIELDS)
        skipped = _exact_bool(row["skipped"])
        bootstrap_complete = _exact_bool(row["bootstrap_complete"])
        checkpoint = row["committed_checkpoint"]
        if checkpoint is not None and type(checkpoint) is not dict:
            raise RpcAmbiguous()
        if skipped:
            if row["run_id"] not in (None, ""):
                raise RpcAmbiguous()
            skip_reason = _nonempty_str(row["skip_reason"])
            if skip_reason not in ALLOWED_SKIP_REASONS:
                raise RpcAmbiguous()
            run_id = ""
        else:
            run_id = _uuid_str(row["run_id"])
            if row["skip_reason"] is not None:
                raise RpcAmbiguous()
            skip_reason = None
        return StartRunResult(
            run_id=run_id,
            bootstrap_complete=bootstrap_complete,
            committed_checkpoint=Checkpoint.from_json(checkpoint)
            if type(checkpoint) is dict
            else None,
            skipped=skipped,
            skip_reason=skip_reason,
        )

    def upsert_source_observations(
        self,
        source_id: str,
        run_id: str,
        records: list[ObservationRecord],
        next_checkpoint: Checkpoint | None,
    ) -> list[ObservationResult]:
        data = _rpc_data(
            self._client,
            UPSERT_SOURCE_OBSERVATIONS,
            {
                "p_source_id": source_id,
                "p_run_id": run_id,
                "p_items": [record.to_rpc_item() for record in records],
                "p_next_checkpoint": None
                if next_checkpoint is None
                else next_checkpoint.to_json(),
            },
        )
        rows = _require_list(data)
        if len(rows) != len(records):
            raise RpcAmbiguous()
        results: list[ObservationResult] = []
        for index, (record, row) in enumerate(zip(records, rows)):
            if type(row) is not dict:
                raise RpcAmbiguous()
            _require_keys(row, UPSERT_FIELDS)
            if _exact_int(row["input_index"]) != index:
                raise RpcAmbiguous()
            external_key = _exact_str(row["external_key"])
            if external_key != record.external_key:
                raise RpcAmbiguous()
            outcome = row["outcome"]
            if type(outcome) is not str or outcome not in ALLOWED_OUTCOMES:
                raise RpcAmbiguous()
            duplicate = _exact_bool(row["duplicate_in_batch"])
            results.append(
                ObservationResult(
                    input_index=index,
                    external_key=external_key,
                    outcome=outcome,
                    duplicate_in_batch=duplicate,
                    skipped_streak=duplicate,
                )
            )
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
        data = _rpc_data(
            self._client,
            FINISH_INGEST_RUN,
            {
                "p_run_id": run_id,
                "p_status": status,
                "p_stop_reason": stop_reason,
                "p_http_request_count": http_request_count,
                "p_bootstrap_complete": bootstrap_complete,
                "p_batches_ok": batches_ok,
            },
        )
        row = _one_row(data)
        _require_keys(row, FINISH_FIELDS)
        result_status = _exact_str(row["status"])
        result_reason = _nonempty_str(row["stop_reason"])
        if result_status not in ALLOWED_RUN_STATUSES:
            raise RpcAmbiguous()
        if len(result_reason) > STOP_REASON_MAX_LEN:
            raise RpcAmbiguous()
        return FinishRunResult(status=result_status, stop_reason=result_reason)

    def claim_processing_jobs(
        self,
        stage: ProcessingStage,
        *,
        limit: int = AI_CLAIM_LIMIT,
        worker_id: str,
        lease_seconds: int = DEFAULT_JOB_LEASE_SECONDS,
    ) -> list[ClaimedJob]:
        data = _rpc_data(
            self._client,
            CLAIM_PROCESSING_JOBS,
            {
                "p_stage": stage,
                "p_limit": limit,
                "p_worker_id": worker_id,
                "p_lease_seconds": lease_seconds,
            },
        )
        rows = _require_list(data)
        jobs: list[ClaimedJob] = []
        for row in rows:
            if type(row) is not dict:
                raise RpcAmbiguous()
            _require_keys(row, CLAIMED_JOB_FIELDS)
            payload = row["normalized_payload"]
            if payload is not None and type(payload) is not dict:
                raise RpcAmbiguous()
            processing_stage = row["processing_stage"]
            if type(processing_stage) is not str or processing_stage != AI_STAGE:
                raise RpcAmbiguous()
            jobs.append(
                ClaimedJob(
                    job_id=_uuid_str(row["job_id"]),
                    source_item_id=_uuid_str(row["source_item_id"]),
                    source_id=_nonempty_str(row["source_id"]),
                    external_key=_nonempty_str(row["external_key"]),
                    revision_hash=_revision_hash(row["revision_hash"]),
                    processing_stage=AI_STAGE,
                    curation_source=_nonempty_str(row["curation_source"]),
                    normalized_payload=payload,
                    disposition=_nonempty_str(row["disposition"]),
                )
            )
        return jobs

    def complete_processing_job(self, job_id: str, *, worker_id: str) -> None:
        data = _rpc_data(
            self._client,
            COMPLETE_PROCESSING_JOB,
            {"p_job_id": job_id, "p_worker_id": worker_id},
        )
        token = _unwrap_scalar_text(data)
        if token != "completed":
            raise RpcAmbiguous()

    def fail_processing_job(
        self, job_id: str, *, worker_id: str, error_code: str
    ) -> str:
        data = _rpc_data(
            self._client,
            FAIL_PROCESSING_JOB,
            {
                "p_job_id": job_id,
                "p_worker_id": worker_id,
                "p_error_code": error_code,
            },
        )
        token = _unwrap_scalar_text(data)
        if token not in {"queued", "failed"}:
            raise RpcAmbiguous()
        return token

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
        data = _rpc_data(
            self._client,
            RESOLVE_INGEST_REVIEW_DECISION,
            {
                "p_source_item_id": source_item_id,
                "p_revision_hash": revision_hash,
                "p_review_type": review_type,
                "p_decision": decision,
                "p_region_scope": region_scope,
                "p_audience_relevance": list(audience_relevance),
                "p_reason_codes": list(reason_codes),
                "p_rule_version": rule_version,
                "p_reviewer": reviewer,
                "p_memo": memo,
            },
        )
        return _parse_review_decision_row(_one_row(data), include_action=False)

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
        data = _rpc_data(
            self._client,
            RECONCILE_QUEUED_AI_JOB,
            {
                "p_job_id": job_id,
                "p_action": action,
                "p_review_type": review_type,
                "p_region_scope": region_scope,
                "p_audience_relevance": list(audience_relevance),
                "p_reason_codes": list(reason_codes),
                "p_rule_version": rule_version,
                "p_reviewer": reviewer,
                "p_memo": memo,
            },
        )
        return _parse_review_decision_row(_one_row(data), include_action=True)

    def set_source_permission(
        self,
        source_id: str,
        to_status: str,
        *,
        reason: str,
        evidence_note: str | None,
        actor: str,
    ) -> None:
        raise RpcFailure("permission_rpc_not_supported")
