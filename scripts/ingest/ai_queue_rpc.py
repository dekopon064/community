"""AI-only public enqueue/revision RPC wrappers. Independent of the legacy pipeline module."""

from __future__ import annotations

from typing import Any

from ingest.rpc_errors import RpcAmbiguous, RpcTimeout, map_rpc_exception

PRECHECK_RPC_NAME = "is_latest_source_revision"
PRECHECK_PARAM_NAMES = (
    "p_source",
    "p_source_item_id",
    "p_source_revision_hash",
)
ENQUEUE_RPC_NAME = "enqueue_curation_candidate"
ALLOWED_ENQUEUE_OUTCOMES = frozenset({"inserted", "duplicate"})
ENQUEUE_PARAM_NAMES = (
    "p_source",
    "p_source_item_id",
    "p_source_revision_hash",
    "p_slug",
    "p_title_ko",
    "p_content_ko",
    "p_raw_payload",
    "p_ai_status_ko",
    "p_category",
    "p_summary_ko",
    "p_source_url",
    "p_ai_model",
    "p_title_ja",
    "p_content_ja",
    "p_summary_ja",
    "p_ai_status_ja",
)
REMOVED_ENQUEUE_PARAM_NAMES = frozenset(
    {
        "p_title",
        "p_content",
        "p_summary",
        "p_ai_status",
    }
)
FORBIDDEN_ENQUEUE_FIELDS = frozenset(
    {
        "review_status",
        "reviewed_at",
        "reviewed_by",
        "review_notes",
        "published_at",
        "published_curation_id",
        "superseded_at",
        "superseded_by_candidate_id",
        "revision_seq",
        "created_at",
        "updated_at",
        "facts",
        "p_facts",
    }
)


def build_precheck_params(
    source: str,
    source_item_id: str,
    source_revision_hash: str,
) -> dict[str, str]:
    params = {
        "p_source": source,
        "p_source_item_id": source_item_id,
        "p_source_revision_hash": source_revision_hash,
    }
    if tuple(params) != PRECHECK_PARAM_NAMES:
        raise RpcAmbiguous()
    return params


def parse_precheck_result(data: object) -> bool:
    if type(data) is bool:
        return data
    raise RpcAmbiguous()


def parse_enqueue_result(data: object) -> dict[str, Any]:
    row: object
    if isinstance(data, list):
        if len(data) != 1:
            raise RpcAmbiguous()
        row = data[0]
    else:
        row = data

    if not isinstance(row, dict):
        raise RpcAmbiguous()

    outcome = row.get("outcome")
    if outcome not in ALLOWED_ENQUEUE_OUTCOMES:
        raise RpcAmbiguous()
    if "candidate_id" not in row:
        raise RpcAmbiguous()
    return row


def _raise_mapped(exc: BaseException) -> None:
    mapped = map_rpc_exception(exc)
    if isinstance(mapped, (RpcTimeout, RpcAmbiguous)):
        raise mapped
    raise RpcAmbiguous() from None


def is_latest_source_revision(
    supabase: Any,
    source: str,
    source_item_id: str,
    source_revision_hash: str,
) -> bool:
    params = build_precheck_params(source, source_item_id, source_revision_hash)
    try:
        response = supabase.rpc(PRECHECK_RPC_NAME, params).execute()
    except Exception as exc:  # noqa: BLE001 - map to Secret-safe RPC errors
        _raise_mapped(exc)
        raise AssertionError("unreachable") from None
    try:
        return parse_precheck_result(getattr(response, "data", None))
    except RpcAmbiguous:
        raise
    except Exception:
        raise RpcAmbiguous() from None


def enqueue_curation_candidate(supabase: Any, params: dict[str, Any]) -> dict[str, Any]:
    unexpected = FORBIDDEN_ENQUEUE_FIELDS.intersection(params)
    if unexpected:
        raise RpcAmbiguous()
    if REMOVED_ENQUEUE_PARAM_NAMES.intersection(params):
        raise RpcAmbiguous()
    if set(params) != set(ENQUEUE_PARAM_NAMES):
        raise RpcAmbiguous()
    if "facts" in params or "p_facts" in params:
        raise RpcAmbiguous()
    try:
        response = supabase.rpc(ENQUEUE_RPC_NAME, params).execute()
    except Exception as exc:  # noqa: BLE001 - map to Secret-safe RPC errors
        _raise_mapped(exc)
        raise AssertionError("unreachable") from None
    try:
        return parse_enqueue_result(getattr(response, "data", None))
    except RpcAmbiguous:
        raise
    except Exception:
        raise RpcAmbiguous() from None
