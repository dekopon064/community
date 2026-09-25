"""Secret-safe RPC error types for ingest and job-state mutations."""

from __future__ import annotations

LEASE_LOST = "lease_lost"
RPC_TIMEOUT = "rpc_timeout"
RPC_AMBIGUOUS = "rpc_ambiguous"
RPC_FAILURE = "rpc_failure"

SAFE_RPC_MESSAGES = frozenset(
    {
        LEASE_LOST,
        "job not found",
        "run not found",
        "human_job_not_completable_by_ai",
        "source_not_found",
        "source_row_malformed",
        "invalid source_id",
        "invalid source_id or run_id",
        "invalid lease_seconds",
        "invalid status",
        "invalid stop_reason",
        "invalid claim limit",
        "invalid worker_id",
        "run_id is required",
        "items must be a json array",
        "complete_status_mismatch",
        "unexpected_job_status",
        "batch_too_large",
        "forbidden_attachment_key",
        RPC_TIMEOUT,
        RPC_AMBIGUOUS,
        RPC_FAILURE,
        "enqueue_failed",
        "permission_rpc_not_supported",
        "publish_rpc_not_supported",
        "revision_mismatch",
        "decision_conflict",
        "ai_job_claimed",
        "source_item_not_found",
        "invalid_review_type",
        "invalid_decision",
        "insufficient_evidence_required",
        "manual_non_target_required",
        "content_review_not_open",
        "product_type_review_not_open",
        "curation_candidate_exists",
        "candidate_already_published",
        "invalid_region_scope",
        "invalid_audience_relevance",
        "invalid_rule_version",
        "invalid_reviewer",
        "invalid_memo",
        "approve_requirements_not_met",
        "invalid_reconcile_action",
        "completed_job_not_reconcileable",
        "ai_job_not_allowed_in_upsert",
        "classifier_metadata_forbidden",
        "classifier_metadata_required",
        "invalid_classifier_decision",
        "content_product_type_locked",
        "invalid_product_type",
        "invalid_product_type_action",
        "product_type_metadata_forbidden",
        "product_type_metadata_required",
        "invalid_product_type_classification",
        "product_type_review_not_allowed_in_upsert",
        "ai_job_malformed_lease",
        "invalid_period_signals",
        "invalid_gate_facts",
        "gate_facts_incomplete",
        "invalid_assessment_schema_version",
        "product_type_not_confirmed",
        "invalid_evaluated_profile",
        "invalid_application_deadline",
        "application_deadline_required",
        "application_deadline_review_not_open",
        "invalid_user_category",
        "user_category_required",
        "user_category_review_not_open",
        "invalid_event_period",
        "event_period_required",
        "invalid_user_category_period",
    }
)

_TIMEOUT_TYPE_NAMES = frozenset(
    {
        "TimeoutException",
        "ReadTimeout",
        "ConnectTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "TimeoutError",
    }
)
_LOST_TYPE_NAMES = frozenset(
    {
        "ConnectError",
        "RemoteProtocolError",
        "NetworkError",
        "ProtocolError",
    }
)


class RpcError(Exception):
    def __init__(self, code: str) -> None:
        safe = code if code in SAFE_RPC_MESSAGES else RPC_FAILURE
        self.code = safe
        super().__init__(safe)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.code!r})"


class RpcFailure(RpcError):
    """Deterministic RPC failure with a known safe code."""


class RpcAmbiguous(RpcError):
    """Commit or job state cannot be confirmed."""

    def __init__(self, code: str = RPC_AMBIGUOUS) -> None:
        super().__init__(code if code in SAFE_RPC_MESSAGES else RPC_AMBIGUOUS)


class RpcTimeout(RpcAmbiguous):
    def __init__(self) -> None:
        super().__init__(RPC_TIMEOUT)


def _type_names(exc: BaseException) -> set[str]:
    return {base.__name__ for base in type(exc).mro()}


def is_timeout_exception(exc: BaseException) -> bool:
    return bool(_type_names(exc) & _TIMEOUT_TYPE_NAMES)


def is_lost_response_exception(exc: BaseException) -> bool:
    return bool(_type_names(exc) & _LOST_TYPE_NAMES)


def safe_api_message(exc: BaseException) -> str | None:
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message in SAFE_RPC_MESSAGES:
        return message
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code in SAFE_RPC_MESSAGES:
        return code
    return None


def map_rpc_exception(exc: BaseException) -> RpcError:
    if isinstance(exc, RpcError):
        return exc
    message = safe_api_message(exc)
    if message == LEASE_LOST:
        return RpcFailure(LEASE_LOST)
    if message is not None:
        return RpcFailure(message)
    if is_timeout_exception(exc):
        return RpcTimeout()
    if is_lost_response_exception(exc):
        return RpcAmbiguous()
    return RpcAmbiguous()
