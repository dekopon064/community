"""승인된 ingest 아키텍처 진입점. 레거시 main()과 분리한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from ingest.ai_worker import (
    AI_DISABLED,
    AI_SKIPPED_NOT_CONFIGURED,
    AI_SKIPPED_SOURCE_INCOMPLETE,
    AiWorkerResult,
    ai_dependencies_ready,
    process_ai_jobs,
)
from ingest.connectors.youthcenter_content import YouthcenterContentConnector
from ingest.connectors.youthcenter_policy import YouthcenterPolicyConnector
from ingest.http_client import HttpClient, PRODUCTION_SLEEP
from ingest.models import SourceConnector
from ingest.orchestrator import SourceRunResult, run_ingest
from ingest.store import AI_CLAIM_LIMIT, IngestStore, MemoryIngestStore


@dataclass(frozen=True)
class IngestArchitectureResult:
    exit_code: int
    source_results: tuple[SourceRunResult, ...]
    ai: AiWorkerResult


def build_youthcenter_connectors(
    *,
    policy_http: HttpClient | None = None,
    content_http: HttpClient | None = None,
    api_key_provider: Callable[[], str] | None = None,
) -> list[SourceConnector]:
    return [
        YouthcenterPolicyConnector(
            http=policy_http, api_key_provider=api_key_provider
        ),
        YouthcenterContentConnector(
            http=content_http, api_key_provider=api_key_provider
        ),
    ]


def sources_are_non_skipped_complete(results: Sequence[SourceRunResult]) -> bool:
    if not results:
        return False
    return all(
        (not result.skipped) and result.status == "complete" for result in results
    )


def run_ingest_architecture(
    *,
    store: IngestStore,
    connectors: Sequence[SourceConnector],
    supabase: Any | None = None,
    sleep: Callable[[float], None] | None = None,
    summarize_ko: Callable[..., tuple[str, str, str | None]] | None = None,
    translate_ja: Callable[..., tuple[str | None, str | None, str, str | None]] | None = None,
    enqueue: Callable[..., dict[str, Any]] | None = None,
    revision_precheck: Callable[..., bool] | None = None,
    run_ai: bool = True,
    ai_limit: int = AI_CLAIM_LIMIT,
) -> IngestArchitectureResult:
    """실제 API·Gemini·DB는 주입된 의존성이 있을 때만 호출된다."""
    sleeper = PRODUCTION_SLEEP if sleep is None else sleep
    results = run_ingest(connectors, store, sleep=sleeper)

    if not run_ai:
        ai_result = AiWorkerResult(status=AI_DISABLED)
    elif not sources_are_non_skipped_complete(results):
        ai_result = AiWorkerResult(status=AI_SKIPPED_SOURCE_INCOMPLETE)
    elif not ai_dependencies_ready(
        supabase=supabase, summarize_ko=summarize_ko, enqueue=enqueue
    ):
        ai_result = AiWorkerResult(status=AI_SKIPPED_NOT_CONFIGURED)
    else:
        ai_result = process_ai_jobs(
            store,
            supabase=supabase,
            summarize_ko=summarize_ko,
            translate_ja=translate_ja,
            enqueue=enqueue,
            revision_precheck=revision_precheck,
            limit=ai_limit,
        )

    exit_code = (
        1
        if any(result.status == "failed" and not result.skipped for result in results)
        else 0
    )
    return IngestArchitectureResult(
        exit_code=exit_code,
        source_results=tuple(results),
        ai=ai_result,
    )


def default_memory_store() -> MemoryIngestStore:
    return MemoryIngestStore()
