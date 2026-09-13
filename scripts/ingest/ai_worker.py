"""AI worker. ai_enrichment만 claim하며 사람 검수 job은 가져가지 않는다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ingest.models import ClaimedJob
from ingest.source_identity import (
    CANONICAL_POLICY_SOURCE,
    curation_source_for_enqueue,
)
from ingest.store import AI_CLAIM_LIMIT, DEFAULT_JOB_LEASE_SECONDS, IngestStore

WORKER_ID = "ingest-ai-worker"
AI_SKIPPED_NOT_CONFIGURED = "ai_skipped_not_configured"
AI_DISABLED = "ai_disabled"
AI_PROCESSED = "processed"

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
) -> AiWorkerResult:
    if not ai_dependencies_ready(
        supabase=supabase, summarize_ko=summarize_ko, enqueue=enqueue
    ):
        return AiWorkerResult(status=AI_SKIPPED_NOT_CONFIGURED)

    jobs = store.claim_processing_jobs(
        "ai_enrichment",
        limit=limit,
        worker_id=WORKER_ID,
        lease_seconds=DEFAULT_JOB_LEASE_SECONDS,
    )
    completed = 0
    retried = 0
    failed = 0
    for job in jobs:
        try:
            _process_one(
                job,
                supabase=supabase,
                summarize_ko=summarize_ko,
                translate_ja=translate_ja,
                enqueue=enqueue,
                revision_precheck=revision_precheck,
            )
            store.complete_processing_job(job.job_id, worker_id=WORKER_ID)
            completed += 1
        except Exception:
            new_status = store.fail_processing_job(
                job.job_id, worker_id=WORKER_ID, error_code="ai_or_enqueue_failed"
            )
            if new_status == "failed":
                failed += 1
            else:
                retried += 1
    return AiWorkerResult(
        status=AI_PROCESSED,
        claimed=len(jobs),
        completed=completed,
        retried=retried,
        failed=failed,
    )


def _process_one(
    job: ClaimedJob,
    *,
    supabase: Any,
    summarize_ko: SummarizeFn,
    translate_ja: TranslateFn | None,
    enqueue: EnqueueFn,
    revision_precheck: PrecheckFn | None,
) -> None:
    if job.processing_stage != "ai_enrichment":
        raise ValueError("human_job_claimed")
    payload = job.normalized_payload or {}
    curation_source = job.curation_source or curation_source_for_enqueue(job.source_id)
    if revision_precheck is not None:
        is_latest = revision_precheck(
            supabase,
            curation_source,
            job.external_key,
            job.revision_hash,
        )
        if is_latest:
            return

    title = str(payload.get("plcyNm") or payload.get("pstTtl") or job.external_key)
    body = str(payload.get("plain_text") or "")
    source_url = payload.get("source_url")
    content_ko, ai_status_ko, ai_model = summarize_ko(body, source_url)

    title_ja = content_ja = ai_status_ja = None
    if ai_status_ko == "success" and translate_ja is not None:
        title_ja, content_ja, ai_status_ja, _model = translate_ja(title, content_ko)

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
            if str(key).lower() not in {"atchfile", "atch_file"}
        },
        "p_ai_status_ko": ai_status_ko,
        "p_category": str(
            payload.get("plcyTpNm") or payload.get("pstSeNm") or "기타"
        ),
        "p_summary_ko": None,
        "p_source_url": source_url,
        "p_ai_model": ai_model,
        "p_title_ja": title_ja,
        "p_content_ja": content_ja,
        "p_summary_ja": None,
        "p_ai_status_ja": ai_status_ja,
    }
    enqueue(supabase, params)
