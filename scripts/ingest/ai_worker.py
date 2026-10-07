"""AI worker. ai_enrichment만 claim하며 사람 검수 job은 가져가지 않는다."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable

from ingest.ai_errors import AI_OR_ENQUEUE_FAILED, AiJobError
from ingest.models import ClaimedJob
from ingest.rpc_errors import RpcAmbiguous, RpcTimeout, RpcFailure
from ingest.source_identity import (
    CANONICAL_POLICY_SOURCE,
    curation_source_for_enqueue,
)
from ingest.store import AI_CLAIM_LIMIT, DEFAULT_JOB_LEASE_SECONDS, IngestStore, LeaseLost
from ingest.content_filters import validate_claim_filter

WORKER_ID = "ingest-ai-worker"
AI_SKIPPED_NOT_CONFIGURED = "ai_skipped_not_configured"
AI_DISABLED = "ai_disabled"
AI_PROCESSED = "processed"
AI_STATE_UNKNOWN = "ai_state_unknown"
AI_SKIPPED_SOURCE_INCOMPLETE = "ai_skipped_source_incomplete"
AI_NO_JOBS = "ai_no_jobs"
_RAW_PAYLOAD_SKIP_KEYS = frozenset({"atchfile", "atch_file", "facts", "content_filter_context", "filterfacts"})
_ONE_OFF_INCOMPLETE_SOURCE_ITEM_ID = "98396243-8907-4c70-b823-066d972c4ac2"
_ONE_OFF_INCOMPLETE_REVISION = "c43eb4a979733eb688a75aa98fb6d9c28f5af61dc71850494d2d82a580e8476f"
_ONE_OFF_INCOMPLETE_BODY = "홈페이지 링크: https://buly.kr/jc9Pam"
SUMMARY_MAX_CHARS = 1000
KO_SUMMARY_HEADER = "[한 줄 요약]"
JA_SUMMARY_HEADER = "[要約]"
KO_SECTION_HEADERS = (
    "[한 줄 요약]",
    "[대상]",
    "[기간·상태]",
    "[주요 내용]",
    "[신청 방법]",
)
JA_SECTION_HEADERS = (
    "[要約]",
    "[対象]",
    "[期間・状況]",
    "[主な内容]",
    "[申請方法]",
)

SummarizeFn = Callable[..., tuple[str, str, str | None]]
TranslateFn = Callable[..., tuple[str | None, str | None, str, str | None]]
EnqueueFn = Callable[..., dict[str, Any]]
PrecheckFn = Callable[..., bool]


@dataclass(frozen=True)
class AiWorkerResult:
    status: str
    claimed: int = 0
    completed: int = 0
    retried: int = 0
    failed: int = 0
    state_unknown: int = 0


def ai_dependencies_ready(
    *,
    supabase: Any | None,
    summarize_ko: SummarizeFn | None,
    enqueue: EnqueueFn | None,
) -> bool:
    return supabase is not None and summarize_ko is not None and enqueue is not None


def process_ai_jobs(
    store: IngestStore,
    *,
    supabase: Any | None = None,
    summarize_ko: SummarizeFn | None = None,
    translate_ja: TranslateFn | None = None,
    enqueue: EnqueueFn | None = None,
    revision_precheck: PrecheckFn | None = None,
    limit: int = AI_CLAIM_LIMIT,
    require_jobs: bool = False,
    target_source_item_id: str | None = None,
    target_revision_hash: str | None = None,
    program_adapter: Any | None = None,
) -> AiWorkerResult:
    if program_adapter is not None:
        # Explicit, single-target program path; scheduled legacy callers do not opt in.
        if limit != 1 or not target_source_item_id or not target_revision_hash or summarize_ko is None or translate_ja is None:
            return AiWorkerResult(status=AI_STATE_UNKNOWN, state_unknown=1)
        from ingest.program_ai import process_seoul_program_job
        return process_seoul_program_job(program_adapter, source_item_id=target_source_item_id,
            revision=target_revision_hash, summarize_ko=summarize_ko, translate_ja=translate_ja)
    if not ai_dependencies_ready(
        supabase=supabase, summarize_ko=summarize_ko, enqueue=enqueue
    ):
        return AiWorkerResult(status=AI_SKIPPED_NOT_CONFIGURED)

    try:
        claim_kwargs: dict[str, Any] = {
            "limit": limit,
            "worker_id": WORKER_ID,
            "lease_seconds": DEFAULT_JOB_LEASE_SECONDS,
        }
        if target_source_item_id is not None or target_revision_hash is not None:
            claim_kwargs["target_source_item_id"] = target_source_item_id
            claim_kwargs["target_revision_hash"] = target_revision_hash
        jobs = store.claim_processing_jobs("ai_enrichment", **claim_kwargs)
    except Exception:
        return AiWorkerResult(status=AI_STATE_UNKNOWN)

    claimed = list(jobs)
    if not claimed:
        if require_jobs:
            return AiWorkerResult(status=AI_NO_JOBS, claimed=0)
        return AiWorkerResult(status=AI_PROCESSED, claimed=0)

    completed = 0
    retried = 0
    failed = 0
    state_unknown = 0
    for job in claimed:
        filter_context = None
        payload = job.normalized_payload or {}
        if "content_filter_context" in payload:
            try:
                from uuid import UUID
                import re
                UUID(job.job_id); UUID(job.source_item_id)
                if (job.source_id not in {"youthcenter_content", "youthcenter_policy"}
                        or job.processing_stage != "ai_enrichment" or job.disposition != "target"
                        or not re.fullmatch(r"[a-f0-9]{64}", job.revision_hash)
                        or not job.external_key or not callable(getattr(store, "finish_content_filter_ai", None))):
                    raise ValueError()
                filter_context = validate_claim_filter(payload["content_filter_context"], worker=WORKER_ID)
                _validate_filter_input(payload)
            except Exception:
                # An untrusted claim cannot authorize any failure/completion write.
                state_unknown += 1
                break
        try:
            atomic = _process_one(
                job,
                supabase=supabase,
                summarize_ko=summarize_ko,
                translate_ja=translate_ja,
                enqueue=enqueue,
                revision_precheck=revision_precheck,
                filter_context=filter_context,
                finish_filter=getattr(store, "finish_content_filter_ai", None),
            )
        except (RpcTimeout, RpcAmbiguous):
            state_unknown += 1
            break
        except AiJobError as exc:
            if filter_context is not None:
                if _record_filter_failure(store, job, filter_context, exc.code):
                    failed += 1
                    continue
                state_unknown += 1
                break
            try:
                new_status = store.fail_processing_job(
                    job.job_id, worker_id=WORKER_ID, error_code=exc.code
                )
            except Exception:
                state_unknown += 1
                break
            if new_status == "failed":
                failed += 1
            elif new_status == "queued":
                retried += 1
            else:
                state_unknown += 1
                break
            continue
        except Exception as exc:
            if filter_context is not None:
                if isinstance(exc, LeaseLost) or isinstance(exc, RpcFailure) and exc.code == "lease_lost":
                    state_unknown += 1
                    break
                if _record_filter_failure(store, job, filter_context, AI_OR_ENQUEUE_FAILED):
                    failed += 1
                    continue
                state_unknown += 1
                break
            try:
                new_status = store.fail_processing_job(
                    job.job_id, worker_id=WORKER_ID, error_code=AI_OR_ENQUEUE_FAILED
                )
            except Exception:
                state_unknown += 1
                break
            if new_status == "failed":
                failed += 1
            elif new_status == "queued":
                retried += 1
            else:
                state_unknown += 1
                break
            continue

        if atomic:
            completed += 1
            continue
        try:
            store.complete_processing_job(job.job_id, worker_id=WORKER_ID)
        except Exception:
            state_unknown += 1
            break
        completed += 1

    status = AI_STATE_UNKNOWN if state_unknown > 0 else AI_PROCESSED
    return AiWorkerResult(
        status=status,
        claimed=len(claimed),
        completed=completed,
        retried=retried,
        failed=failed,
        state_unknown=state_unknown,
    )


def _validate_filter_input(payload: dict) -> None:
    title = payload.get("plcyNm") or payload.get("pstTtl")
    body = payload.get("plain_text")
    if type(title) is not str or not 1 <= len(title.strip()) <= 300 or type(body) is not str or not body.strip():
        raise AiJobError("ai_schema_error")


def _record_filter_failure(store: IngestStore, job: ClaimedJob, context: dict, code: str) -> bool:
    try:
        # Recheck the same captured lease after generation; never renew or retry.
        validate_claim_filter(context, worker=WORKER_ID)
        return store.fail_content_filter_ai(job, context=context, error_code=AiJobError(code).code) == "failed"
    except Exception:
        return False


def _process_one(
    job: ClaimedJob,
    *,
    supabase: Any,
    summarize_ko: SummarizeFn,
    translate_ja: TranslateFn | None,
    enqueue: EnqueueFn,
    revision_precheck: PrecheckFn | None,
    filter_context: dict | None = None,
    finish_filter: Callable | None = None,
) -> bool | None:
    if job.processing_stage != "ai_enrichment":
        raise ValueError("human_job_claimed")
    if job.source_id in {"seoul_reservation", "myseoul_program"}:
        # Source identity alone is not permission to consume program facts through v1.
        raise AiJobError("ai_schema_error")
    payload = job.normalized_payload or {}
    curation_source = job.curation_source or curation_source_for_enqueue(job.source_id)
    if "content_filter_context" in payload and filter_context is None:
        # Direct callers cannot silently route filter jobs through legacy enqueue.
        raise ValueError("content_filter_fence_required")
    if revision_precheck is not None and filter_context is None:
        is_latest = revision_precheck(
            supabase,
            curation_source,
            job.external_key,
            job.revision_hash,
        )
        if is_latest:
            return

    if filter_context is not None:
        _validate_filter_input(payload)
    title = str(payload.get("plcyNm") or payload.get("pstTtl") or job.external_key)
    body = str(payload.get("plain_text") or "")
    if (
        job.source_id == "youthcenter_content"
        and job.external_key == "48:10799"
        and job.source_item_id == _ONE_OFF_INCOMPLETE_SOURCE_ITEM_ID
        and job.revision_hash == _ONE_OFF_INCOMPLETE_REVISION
        and body.strip() == _ONE_OFF_INCOMPLETE_BODY
    ):
        raise AiJobError("ai_schema_error")
    source_url = payload.get("source_url")
    content_ko, ai_status_ko, ai_model = _call_summarize(
        summarize_ko, body, source_url, title
    )

    title_ja = content_ja = ai_status_ja = None
    if ai_status_ko == "success" and translate_ja is not None:
        title_ja, content_ja, ai_status_ja, _model = translate_ja(title, content_ko)

    summary_ko = extract_summary_section(
        content_ko, KO_SUMMARY_HEADER, KO_SECTION_HEADERS
    )
    summary_ja = None
    if content_ja is not None:
        summary_ja = extract_summary_section(
            content_ja, JA_SUMMARY_HEADER, JA_SECTION_HEADERS
        )

    if filter_context is not None:
        from ingest.myseoul_ai_support import section_body
        if ai_status_ko != "success" or ai_status_ja != "success" or finish_filter is None:
            raise AiJobError("ai_schema_error")
        for content, headers in ((content_ko, KO_SECTION_HEADERS), (content_ja, JA_SECTION_HEADERS)):
            for header in headers:
                section_body(content, header, headers)
        output = {"aiModel": ai_model, "titleKo": title, "titleJa": title_ja,
                  "summaryKo": summary_ko, "summaryJa": summary_ja,
                  "contentKo": content_ko, "contentJa": content_ja}
        for key, value in output.items():
            maximum = 300 if key.startswith("title") else 1000 if key.startswith("summary") else 100 if key == "aiModel" else 200000
            if type(value) is not str or not 1 <= len(value.strip()) <= maximum:
                raise AiJobError("ai_schema_error")
        result = finish_filter(job, context=filter_context, output=output)
        from uuid import UUID
        if type(result) is not dict or set(result) != {"candidateId", "outcome"} or result["outcome"] != "inserted":
            raise RpcAmbiguous()
        try:
            UUID(result["candidateId"])
        except (ValueError, TypeError, AttributeError):
            raise RpcAmbiguous() from None
        return True  # Server atomically finished candidate/snapshot/job.

    slug_prefix = "policy" if job.source_id == CANONICAL_POLICY_SOURCE else "content"
    params = {
        "p_source": curation_source,
        "p_source_item_id": job.external_key,
        "p_source_revision_hash": job.revision_hash,
        "p_slug": f"{slug_prefix}-{job.external_key.replace(':', '-')}",
        "p_title_ko": title,
        "p_content_ko": content_ko,
        "p_raw_payload": {
            key: value
            for key, value in payload.items()
            if str(key).lower() not in _RAW_PAYLOAD_SKIP_KEYS
        },
        "p_ai_status_ko": ai_status_ko,
        "p_category": str(
            payload.get("plcyTpNm") or payload.get("pstSeNm") or "기타"
        ),
        "p_summary_ko": summary_ko,
        "p_source_url": source_url,
        "p_ai_model": ai_model,
        "p_title_ja": title_ja,
        "p_content_ja": content_ja,
        "p_summary_ja": summary_ja,
        "p_ai_status_ja": ai_status_ja,
    }
    if "facts" in params or "p_facts" in params:
        raise ValueError("facts_not_allowed_in_enqueue")
    enqueue(supabase, params)


def extract_summary_section(
    content: object,
    header: str,
    headers: tuple[str, ...],
) -> str:
    """Return the trimmed body of one labeled section.

    The header itself is not part of the value. A missing, empty, or
    over-long section uses the existing AI schema failure.
    """
    if not isinstance(content, str):
        raise AiJobError("ai_schema_error")
    ordered = tuple(sorted(headers, key=len, reverse=True))
    parts: list[str] = []
    collecting = False
    found = False
    for line in content.splitlines():
        matched = _section_header(line.strip(), ordered)
        if matched is not None:
            matched_header, remainder = matched
            if collecting:
                break
            if matched_header == header:
                found = True
                collecting = True
                if remainder:
                    parts.append(remainder)
            continue
        if collecting:
            parts.append(line)
    if not found:
        raise AiJobError("ai_schema_error")
    body = "\n".join(parts).strip()
    if not body or len(body) > SUMMARY_MAX_CHARS:
        raise AiJobError("ai_schema_error")
    return body


def _section_header(stripped: str, headers: tuple[str, ...]) -> tuple[str, str] | None:
    for header in headers:
        if stripped == header:
            return header, ""
        if stripped.startswith(header):
            return header, stripped[len(header) :].strip()
    return None


def _call_summarize(
    summarize_ko: SummarizeFn,
    body: str,
    source_url: Any,
    title: str,
) -> tuple[str, str, str | None]:
    try:
        parameters = inspect.signature(summarize_ko).parameters
    except (TypeError, ValueError):
        return summarize_ko(body, source_url)
    accepts_title = "title" in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    if accepts_title:
        return summarize_ko(body, source_url, title=title)
    return summarize_ko(body, source_url)
