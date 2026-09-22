"""ingest 단위·통합 테스트. 운영 API·Anthropic·Supabase에 연결하지 않는다."""

from __future__ import annotations

import io
import json
import logging
import os
import pathlib
import sys
import time
import traceback
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import requests

from ingest.ai_worker import (
    AI_SKIPPED_NOT_CONFIGURED,
    AI_SKIPPED_SOURCE_INCOMPLETE,
    AI_STATE_UNKNOWN,
    WORKER_ID,
    process_ai_jobs,
)
from ingest.attachments import (
    contains_forbidden_attachment_key,
    drop_forbidden_attachments,
    extract_sanitized_source_items,
)
from ingest.connectors.youthcenter_content import (
    CONTENT_API_KEY_ENV,
    CONTENT_BOOTSTRAP_MAX_ITEMS,
    CONTENT_BOOTSTRAP_MAX_PAGES,
    CONTENT_HTTP_BUDGET,
    CONTENT_MAX_PAGES,
    CONTENT_MAX_RESPONSE_BYTES,
    CONTENT_PAGE_SIZE,
    YouthcenterContentConnector,
    content_job_and_flags,
)
from ingest.connectors.youthcenter_policy import (
    POLICY_PAGE_SIZE,
    YouthcenterPolicyConnector,
    policy_job_plan,
)
from ingest.constants import (
    AI_MAX_ATTEMPTS,
    DEFAULT_JOB_LEASE_SECONDS,
    DEFAULT_LEASE_SECONDS,
    LEASE_SECONDS_MAX,
    LEASE_SECONDS_MIN,
)
from ingest.dates import parse_source_datetime
from ingest.http_client import (
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    HttpBudgetExhausted,
    HttpClient,
    HttpRequestFailed,
    HttpStatusError,
    MAX_ATTEMPTS,
    PRODUCTION_SLEEP,
    RETRYABLE_STATUSES,
    ResponseTooLarge,
)
from ingest.models import BatchResult, Checkpoint, FinishRunResult, ObservationRecord
from ingest.orchestrator import (
    BOOTSTRAP_COMPLETE_REASONS,
    InvalidOrderingCapability,
    format_ordering_cli_token,
    run_connector,
    run_ingest,
)
from ingest.region import classify_eligibility, classify_policy_disposition, classify_region_scope
from ingest.product_type import (
    classify_content_product_type,
    classify_policy_product_type,
    product_type_classification_payload,
)
from ingest.relevance import (
    AXIS_FOREIGN_RESIDENTS_IN_KR,
    AXIS_JP_RESIDENTS_IN_KR,
    AXIS_KR_JAPAN_ACTIVITY,
    AXIS_KR_JP_EXCHANGE,
    RULE_VERSION,
    classify_content_relevance,
    classify_policy_relevance,
    classifier_decision_metadata,
    screen_content,
    screen_policy,
)
from ingest.rpc_errors import RpcAmbiguous, RpcTimeout
from ingest.run import build_youthcenter_connectors, run_ingest_architecture
from ingest.sanitize import html_to_plain_text
from ingest.source_identity import (
    CANONICAL_CONTENT_SOURCE,
    CANONICAL_POLICY_SOURCE,
    LEGACY_POLICY_CURATION_SOURCE,
    canonical_source_id,
    curation_source_for_enqueue,
)
from ingest.store import LeaseLost, MemoryIngestStore

FIXTURES = pathlib.Path(__file__).resolve().parent / "ingest" / "fixtures"
HWASUN_PATH = FIXTURES / "hwasun_policy.json"
CONTENT_PATH = FIXTURES / "content_with_tiny_attachment.json"
CONTENT_NONCAPITAL_PATH = FIXTURES / "content_noncapital_jeju.json"
ATCH_SNIPPET = "data:text/plain;base64,QUFBQQ=="
ATCH_MARKER = "ATCHFILE_MARKER_x7kQ2n"
HTTP_KEY_MARKER = "ingest-http-marker-K9q2Vx7LmN4p"
NO_SLEEP = lambda _seconds: None
OBSERVED_CONTENT_PROBE_BYTES = 8_060_928


def _ascii_json_of_size(n: int) -> bytes:
    prefix = b'{"k":"'
    suffix = b'"}'
    pad = n - len(prefix) - len(suffix)
    if pad < 0:
        raise AssertionError("synthetic_json_too_small")
    return prefix + (b"a" * pad) + suffix


def _content_list_json_bytes(target: int) -> bytes:
    seed = ATCH_MARKER

    def encode(atch: str) -> bytes:
        payload = {
            "result": {
                "youthPolicyList": [
                    {
                        "bbsSn": "bbs-1",
                        "pstSn": "pst-1",
                        "pstTtl": "title",
                        "pstWholCn": "body-text",
                        "pstSeNm": "cat",
                        "atchFile": atch,
                    }
                ]
            }
        }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode(
            "ascii"
        )

    extra = target - len(encode(seed))
    if extra < 0:
        raise AssertionError("synthetic_content_json_too_small")
    raw = encode(seed + ("x" * extra))
    if len(raw) != target:
        raise AssertionError("synthetic_content_json_size_mismatch")
    return raw


class FakeStreamResponse:
    def __init__(
        self,
        status_code: int = 200,
        *,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
        json_payload: Any = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        if chunks is None:
            if json_payload is not None:
                chunks = [json.dumps(json_payload).encode("utf-8")]
            else:
                chunks = []
        self._chunks = list(chunks)
        self.closed = False
        self.chunk_reads = 0

    def iter_content(self, chunk_size: int = 8192):
        for chunk in self._chunks:
            if self.closed:
                break
            self.chunk_reads += 1
            yield chunk

    def close(self) -> None:
        self.closed = True

    def json(self) -> Any:
        raise AssertionError("response.json() would buffer the body")


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class FakeConnector:
    canonical_source_id = CANONICAL_POLICY_SOURCE
    provider = "youthcenter"
    source_kind = "policy"
    connector_type = "rest"
    legacy_curation_source = LEGACY_POLICY_CURATION_SOURCE
    start_mode = "fresh_from_origin"
    page_size = 5
    bootstrap_max_pages = 5
    bootstrap_max_items = 25
    max_pages = 10
    http_budget = 30
    streak_needed = 3
    batch_delay_seconds = 1.0
    ordering_capability = "require_descending"

    def __init__(
        self,
        batches: list[BatchResult] | None = None,
        fetch_error: Exception | None = None,
        error_on: int = 0,
        start_mode: str | None = None,
        http_budget: int = 30,
        max_pages: int = 10,
        bootstrap_max_pages: int = 5,
        bootstrap_max_items: int = 25,
        source_id: str = CANONICAL_POLICY_SOURCE,
        ordering_capability: str = "require_descending",
    ) -> None:
        self.batches = list(batches or [])
        self.fetch_error = fetch_error
        self.error_on = error_on
        if start_mode is not None:
            self.start_mode = start_mode  # type: ignore[assignment]
        self.http_budget = http_budget
        self.max_pages = max_pages
        self.bootstrap_max_pages = bootstrap_max_pages
        self.bootstrap_max_items = bootstrap_max_items
        self.canonical_source_id = source_id
        self.ordering_capability = ordering_capability
        self.calls = 0
        self.http = SimpleNamespace(request_count=0)

    def fetch_batch(self, checkpoint: Checkpoint | None) -> BatchResult:
        self.calls += 1
        self.http.request_count += 1
        if self.fetch_error is not None and self.calls >= self.error_on:
            raise self.fetch_error
        if not self.batches:
            return BatchResult(items=(), next_checkpoint=None, natural_end=True)
        return self.batches.pop(0)

    def to_observation(
        self,
        item: dict[str, Any],
        *,
        permission_status: str,
        enabled: bool,
    ) -> ObservationRecord:
        return YouthcenterPolicyConnector(api_key_provider=lambda: "unused").to_observation(
            item, permission_status=permission_status, enabled=enabled
        )


def policy_item(
    plcy_no: str,
    *,
    zip_cd: str,
    oper_cd: str,
    group: str = "0054002",
    updated: str = "2026-09-13 12:00:00",
    created: str = "2026-09-01 12:00:00",
    title: str = "테스트 정책",
    **extra: Any,
) -> dict[str, Any]:
    item = {
        "plcyNo": plcy_no,
        "plcyNm": title,
        "plcyExplnCn": "설명입니다. 본문이 충분히 있습니다.",
        "plcySprtCn": "지원 내용입니다.",
        "aplyUrlAddr": "https://example.go.kr/apply",
        "zipCd": zip_cd,
        "operInstCd": oper_cd,
        "operInstNm": extra.pop("operInstNm", ""),
        "pvsnInstGroupCd": group,
        "frstRegDt": created,
        "lastMdfcnDt": updated,
        "inqCnt": "999",
    }
    item.update(extra)
    return item


def observation_for(item: dict[str, Any]) -> ObservationRecord:
    """v3 regression helper. Live connectors no longer screen."""
    normalized = YouthcenterPolicyConnector(
        api_key_provider=lambda: "unused"
    ).to_observation(item, permission_status="testing_only", enabled=True)
    title = html_to_plain_text(item.get("plcyNm"))
    body = html_to_plain_text(
        f"{item.get('plcyExplnCn') or ''}\n\n{item.get('plcySprtCn') or ''}"
    )
    screening = screen_policy(item, f"{title}\n{body}", body_usable=bool(body))
    disposition = screening.disposition
    payload = None if disposition == "non_target" else normalized.normalized_payload
    jobs = policy_job_plan(disposition, reason_codes=screening.reason_codes)
    product_type_classification = None
    if disposition == "target":
        product_type_classification = product_type_classification_payload(
            classify_policy_product_type(f"{title}\n{body}")
        )
    return replace(
        normalized,
        disposition=disposition,  # type: ignore[arg-type]
        normalized_payload=payload,
        jobs=jobs,
        classifier_decision=classifier_decision_metadata(screening),
        product_type_classification=product_type_classification,
    )


def v3_content_observation(item: dict[str, Any]) -> ObservationRecord:
    """v3 regression helper for content lock/upsert tests."""
    from ingest.models import JobPlan

    connector = YouthcenterContentConnector(api_key_provider=lambda: "unused")
    normalized = connector.to_observation(
        item, permission_status="testing_only", enabled=True
    )
    title = html_to_plain_text(item.get("pstTtl"))
    plain = str((normalized.normalized_payload or {}).get("plain_text") or "")
    screening = screen_content(title, plain, body_usable=normalized.body_usable)
    disposition, jobs = content_job_and_flags(
        body_usable=normalized.body_usable,
        has_source_url=normalized.has_source_url,
        attachment_present=normalized.attachment_present,
        permission_ok=True,
        region_scope=screening.region_scope,
        relevance_confirmed=screening.relevance.confirmed,
        screening_reasons=screening.reason_codes,
    )
    if normalized.relationships:
        jobs = jobs + (
            JobPlan(stage="relationship_review", reason_codes=("policy_link_candidate",)),
        )
    product_type_classification = None
    classifier_decision = None
    if disposition == "target":
        product_type_classification = product_type_classification_payload(
            classify_content_product_type()
        )
        classifier_decision = classifier_decision_metadata(screening)
    return replace(
        normalized,
        disposition=disposition,  # type: ignore[arg-type]
        jobs=jobs,
        classifier_decision=classifier_decision,
        product_type_classification=product_type_classification,
    )


def _page_batches(
    items: list[dict[str, Any]],
    *,
    page_size: int = 5,
    natural_end: bool = False,
) -> list[BatchResult]:
    batches: list[BatchResult] = []
    page = 1
    for start in range(0, len(items), page_size):
        chunk = items[start : start + page_size]
        last = start + page_size >= len(items)
        batches.append(
            BatchResult(
                items=tuple(chunk),
                next_checkpoint=(
                    None
                    if last and natural_end
                    else Checkpoint.for_rest_page(page + 1)
                ),
                natural_end=last and natural_end,
            )
        )
        page += 1
    return batches


def _descending_target(key: str, rank: int, **extra: Any) -> dict[str, Any]:
    day = max(1, 28 - rank)
    extra.setdefault("updated", f"2026-08-{day:02d} 12:00:00")
    extra.setdefault("created", "2026-08-01 12:00:00")
    extra.setdefault("title", f"합성정책{rank:02d}")
    return policy_item(key, zip_cd="11680", oper_cd="11680", **extra)


def _hide_ordering_capability(inner: FakeConnector) -> Any:
    class Hidden:
        def __init__(self, wrapped: FakeConnector) -> None:
            object.__setattr__(self, "_wrapped", wrapped)

        def __getattr__(self, name: str) -> Any:
            if name == "ordering_capability":
                raise AttributeError(name)
            return getattr(self._wrapped, name)

    return Hidden(inner)


class _SpyStore(MemoryIngestStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.get_source_calls = 0
        self.start_calls = 0
        self.upsert_calls = 0

    def get_source(self, source_id: str) -> dict[str, Any]:
        self.get_source_calls += 1
        return super().get_source(source_id)

    def start_ingest_run(self, *args: Any, **kwargs: Any) -> Any:
        self.start_calls += 1
        return super().start_ingest_run(*args, **kwargs)

    def upsert_source_observations(self, *args: Any, **kwargs: Any) -> Any:
        self.upsert_calls += 1
        return super().upsert_source_observations(*args, **kwargs)

    def upsert_source_observations_v4(self, *args: Any, **kwargs: Any) -> Any:
        self.upsert_calls += 1
        return super().upsert_source_observations_v4(*args, **kwargs)


def _ai_deps(**overrides: Any) -> dict[str, Any]:
    deps: dict[str, Any] = {
        "supabase": object(),
        "summarize_ko": lambda text, url: (text, "success", "model"),
        "translate_ja": lambda title, body: ("t", "b", "success", "model"),
        "enqueue": lambda *_a, **_k: {"outcome": "inserted", "candidate_id": "x"},
        "revision_precheck": lambda *_a, **_k: False,
    }
    deps.update(overrides)
    return deps


CLEAR_FIT_BODY = "재한 일본인은 신청 가능합니다. 서울 거주자를 대상으로 합니다."


def _assert_v2_created_clear_target_ai(store: MemoryIngestStore, count: int) -> None:
    items = list(store.items.values())
    if len(items) != count:
        raise AssertionError("v2_clear_target_item_count")
    if len(store.decisions) != count:
        raise AssertionError("v2_clear_target_decision_count")
    reviewer = f"classifier:{RULE_VERSION}"
    for item in items:
        decisions = [
            row
            for row in store.decisions.values()
            if row.source_item_id == item.id and row.revision_hash == item.revision_hash
        ]
        if len(decisions) != 1 or decisions[0].decision != "approve_ai":
            raise AssertionError("v2_clear_target_decision_missing")
        if decisions[0].reviewer != reviewer:
            raise AssertionError("v2_clear_target_reviewer")
        ais = [
            job
            for job in store.jobs.values()
            if job.source_item_id == item.id
            and job.revision_hash == item.revision_hash
            and job.processing_stage == "ai_enrichment"
        ]
        if len(ais) != 1 or ais[0].status != "queued":
            raise AssertionError("v2_clear_target_ai_missing")


def _seed_ai_jobs(store: MemoryIngestStore, count: int) -> None:
    started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
    records = []
    for index in range(count):
        records.append(
            observation_for(
                policy_item(
                    f"p{index}",
                    zip_cd="11680",
                    oper_cd="11680",
                    title=f"정책{index}",
                    plcyExplnCn=CLEAR_FIT_BODY,
                    plcySprtCn=CLEAR_FIT_BODY,
                )
            )
        )
    store.upsert_source_observations(
        CANONICAL_POLICY_SOURCE,
        started.run_id,
        records,
        Checkpoint.for_rest_page(2),
    )
    _assert_v2_created_clear_target_ai(store, count)


def load_hwasun() -> dict[str, Any]:
    return json.loads(HWASUN_PATH.read_text(encoding="utf-8"))


def load_content() -> dict[str, Any]:
    return json.loads(CONTENT_PATH.read_text(encoding="utf-8"))


def load_noncapital_content() -> dict[str, Any]:
    return json.loads(CONTENT_NONCAPITAL_PATH.read_text(encoding="utf-8"))


class SourceIdentityTests(unittest.TestCase):
    def test_legacy_policy_maps_to_canonical_and_back(self) -> None:
        self.assertEqual(canonical_source_id("youthcenter"), CANONICAL_POLICY_SOURCE)
        self.assertEqual(
            curation_source_for_enqueue(CANONICAL_POLICY_SOURCE),
            LEGACY_POLICY_CURATION_SOURCE,
        )
        self.assertEqual(
            curation_source_for_enqueue(CANONICAL_CONTENT_SOURCE),
            "youthcenter_content",
        )


class RegionTests(unittest.TestCase):
    def test_eligibility_distinguishes_only_mixed_and_unknown(self) -> None:
        self.assertEqual(classify_eligibility("11680"), "capital_only")
        self.assertEqual(classify_eligibility("50110"), "non_capital_only")
        self.assertEqual(
            classify_eligibility("11680,50110"), "mixed_capital_and_non_capital"
        )
        self.assertEqual(classify_eligibility(""), "unknown")
        self.assertEqual(classify_eligibility(None), "unknown")

    def test_capital_zip_without_relevance_is_review_not_target(self) -> None:
        self.assertEqual(
            classify_policy_disposition(
                policy_item("p1", zip_cd="11680", oper_cd="11680")
            ),
            "region_review_required",
        )

    def test_capital_operator_non_capital_only_is_non_target(self) -> None:
        self.assertEqual(
            classify_policy_disposition(
                policy_item("p1", zip_cd="50110", oper_cd="11680")
            ),
            "non_target",
        )

    def test_mixed_zip_without_nationwide_body_is_not_nationwide(self) -> None:
        item = policy_item("p1", zip_cd="11680,50110", oper_cd="11680")
        scope = classify_region_scope(
            eligibility="mixed_capital_and_non_capital",
            text=f"{item['plcyNm']}\n{item['plcyExplnCn']}",
            operator="capital_operator",
        )
        self.assertEqual(scope, "capital")
        self.assertNotEqual(scope, "nationwide_or_online")

    def test_central_operator_does_not_imply_nationwide(self) -> None:
        item = policy_item(
            "p1", zip_cd="11680,28100,50110", oper_cd="", group="0054001"
        )
        scope = classify_region_scope(
            eligibility="mixed_capital_and_non_capital",
            text=f"{item['plcyNm']}\n{item['plcyExplnCn']}",
            operator="central",
        )
        self.assertEqual(scope, "capital")
        self.assertNotEqual(scope, "nationwide_or_online")
        self.assertEqual(classify_policy_disposition(item), "region_review_required")

    def test_central_empty_zip_is_unknown_not_nationwide(self) -> None:
        item = policy_item("p1", zip_cd="", oper_cd="", group="0054001")
        scope = classify_region_scope(
            eligibility="unknown",
            text=f"{item['plcyNm']}\n{item['plcyExplnCn']}",
            operator="central",
        )
        self.assertEqual(scope, "unknown")

    def test_explicit_nationwide_body_is_nationwide(self) -> None:
        scope = classify_region_scope(
            eligibility="unknown",
            text="전국 청년을 대상으로 합니다. 온라인 참여가 가능합니다.",
            operator="central",
        )
        self.assertEqual(scope, "nationwide_or_online")

    def test_online_apply_only_is_not_nationwide(self) -> None:
        scope = classify_region_scope(
            eligibility="capital_only",
            text="서울 거주 청년을 대상으로 합니다. 온라인으로 신청하세요.",
            operator="capital_operator",
        )
        self.assertEqual(scope, "capital")
        self.assertNotEqual(scope, "nationwide_or_online")

    def test_non_capital_operator_and_only_is_non_target(self) -> None:
        self.assertEqual(
            classify_policy_disposition(
                policy_item("p1", zip_cd="50110", oper_cd="50110")
            ),
            "non_target",
        )

    def test_hwasun_fixture_is_region_review(self) -> None:
        self.assertEqual(
            classify_policy_disposition(load_hwasun()),
            "region_review_required",
        )

    def test_legacy_003_code_does_not_force_target(self) -> None:
        self.assertEqual(
            classify_policy_disposition(
                policy_item(
                    "p1",
                    zip_cd="003002001",
                    oper_cd="50110",
                    operInstNm="서울특별시",
                )
            ),
            "non_target",
        )

    def test_ambiguous_gwangju_is_unknown(self) -> None:
        scope = classify_region_scope(
            eligibility="unknown",
            text="광주 청년 모집 안내입니다.",
        )
        self.assertEqual(scope, "unknown")

    def test_new_observations_never_create_ai_jobs(self) -> None:
        mixed = observation_for(
            policy_item("p-mix", zip_cd="11680,50110", oper_cd="11680")
        )
        self.assertNotEqual(mixed.disposition, "target")
        self.assertTrue(all(job.stage != "ai_enrichment" for job in mixed.jobs))
        central = observation_for(
            policy_item(
                "p-central", zip_cd="11680,28100,50110", oper_cd="", group="0054001"
            )
        )
        self.assertTrue(all(job.stage != "ai_enrichment" for job in central.jobs))


class PolicyRelevanceTests(unittest.TestCase):
    def _capital_item(self, key: str, expln: str, sprt: str = "") -> dict[str, Any]:
        return policy_item(
            key,
            zip_cd="11680",
            oper_cd="11680",
            plcyExplnCn=expln,
            plcySprtCn=sprt or expln,
        )

    def test_generic_capital_welfare_is_review_not_ai(self) -> None:
        record = observation_for(
            self._capital_item("welfare", "서울 청년 주거비와 창업 금융 지원 안내입니다.")
        )
        self.assertEqual(record.disposition, "region_review_required")
        self.assertEqual(record.jobs[0].stage, "region_review")
        self.assertIn("relevance_unconfirmed", record.jobs[0].reason_codes)
        self.assertTrue(all(job.stage != "ai_enrichment" for job in record.jobs))

    def test_jp_resident_axis_is_target_without_ai_job(self) -> None:
        expln = "한국 거주 일본인은 신청 가능합니다. 서울 거주자를 대상으로 합니다."
        record = observation_for(self._capital_item("jp-res", expln))
        relevance = classify_policy_relevance(expln)
        self.assertIn(AXIS_JP_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertEqual(record.disposition, "target")
        self.assertEqual(record.jobs, ())
        self.assertIsNotNone(record.classifier_decision)
        self.assertEqual(record.classifier_decision["decision"], "approve_ai")
        self.assertEqual(record.classifier_decision["review_type"], "relevance")
        self.assertNotIn("reviewer", record.classifier_decision)
        self.assertNotIn("classifier_decision", record.normalized_payload or {})

    def test_foreign_resident_axis_is_target_without_ai_job(self) -> None:
        expln = "외국인 청년도 신청 가능합니다. 국적 제한 없음. 서울 거주 청년이 대상입니다."
        record = observation_for(self._capital_item("foreign", expln))
        relevance = classify_policy_relevance(expln)
        self.assertIn(AXIS_FOREIGN_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertEqual(record.disposition, "target")
        self.assertEqual(record.jobs, ())

    def test_kr_japan_activity_axis_is_target_without_ai_job(self) -> None:
        expln = "한국 청년을 위한 일본 유학 지원 사업입니다. 서울·경기 거주자가 대상입니다."
        record = observation_for(self._capital_item("study", expln))
        relevance = classify_policy_relevance(expln)
        self.assertIn(AXIS_KR_JAPAN_ACTIVITY, relevance.confirmed_axes)
        self.assertEqual(record.disposition, "target")
        self.assertEqual(record.jobs, ())

    def test_exchange_axis_with_explicit_online_is_target_without_ai_job(self) -> None:
        expln = "한일 청년 교류 포럼입니다. 온라인 참여가 가능합니다."
        item = policy_item(
            "exchange",
            zip_cd="",
            oper_cd="",
            group="0054001",
            plcyExplnCn=expln,
            plcySprtCn=expln,
        )
        record = observation_for(item)
        relevance = classify_policy_relevance(expln)
        screening = screen_policy(item, expln, body_usable=True)
        self.assertIn(AXIS_KR_JP_EXCHANGE, relevance.confirmed_axes)
        self.assertEqual(screening.region_scope, "nationwide_or_online")
        self.assertEqual(record.disposition, "target")
        self.assertEqual(record.jobs, ())

    def test_keyword_with_negation_is_not_auto_approved(self) -> None:
        expln = "외국인 참여가 불가합니다. 서울 거주 내국인만 신청 가능합니다."
        record = observation_for(self._capital_item("neg", expln))
        relevance = classify_policy_relevance(expln)
        self.assertEqual(relevance.confirmed_axes, ())
        self.assertEqual(record.disposition, "region_review_required")
        self.assertIn("relevance_unconfirmed", record.jobs[0].reason_codes)
        self.assertTrue(all(job.stage != "ai_enrichment" for job in record.jobs))

    def test_korean_nationals_only_lock_is_review_not_target(self) -> None:
        expln = "재한 일본인은 대한민국 국민만 신청 가능합니다. 서울 거주자를 대상으로 합니다."
        relevance = classify_policy_relevance(expln)
        record = observation_for(self._capital_item("nationals-only", expln))
        self.assertNotIn(AXIS_JP_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertEqual(relevance.confirmed_axes, ())
        self.assertEqual(record.disposition, "region_review_required")
        self.assertEqual(record.jobs[0].stage, "region_review")
        self.assertIn("relevance_unconfirmed", record.jobs[0].reason_codes)
        self.assertNotEqual(record.disposition, "non_target")
        self.assertTrue(all(job.stage != "ai_enrichment" for job in record.jobs))

    def test_korean_nationals_limited_phrase_is_review_not_target(self) -> None:
        expln = "재한 일본인 신청은 대한민국 국민에 한함. 서울 거주자를 대상으로 합니다."
        relevance = classify_policy_relevance(expln)
        record = observation_for(self._capital_item("nationals-limited", expln))
        self.assertNotIn(AXIS_JP_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertEqual(record.disposition, "region_review_required")
        self.assertIn("relevance_unconfirmed", record.jobs[0].reason_codes)
        self.assertTrue(all(job.stage != "ai_enrichment" for job in record.jobs))

    def test_each_national_exclusive_limit_blocks_resident_axes(self) -> None:
        phrases = (
            "대한민국 국민만",
            "한국 국민만",
            "대한민국 국민에 한함",
            "한국 국민에 한함",
            "대한민국 국민 한정",
            "한국 국민 한정",
        )
        self.assertEqual(len(phrases), 6)
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                expln = (
                    f"재한 일본인은 신청 가능합니다. {phrase} 대상입니다. "
                    "서울 거주자를 대상으로 합니다."
                )
                relevance = classify_policy_relevance(expln)
                record = observation_for(
                    self._capital_item(f"limit-{phrase}", expln)
                )
                self.assertNotIn(AXIS_JP_RESIDENTS_IN_KR, relevance.confirmed_axes)
                self.assertNotIn(AXIS_FOREIGN_RESIDENTS_IN_KR, relevance.confirmed_axes)
                self.assertEqual(record.disposition, "region_review_required")
                self.assertEqual(record.jobs[0].stage, "region_review")
                self.assertIn("relevance_unconfirmed", record.jobs[0].reason_codes)
                self.assertNotEqual(record.disposition, "non_target")
                self.assertTrue(all(job.stage != "ai_enrichment" for job in record.jobs))

    def test_cross_sentence_national_limit_after_positive_is_review(self) -> None:
        expln = (
            "재한 일본인은 신청 가능합니다. 외국인 청년도 신청 가능합니다. "
            "대한민국 국민만 대상입니다. 서울 거주자를 대상으로 합니다."
        )
        relevance = classify_policy_relevance(expln)
        record = observation_for(self._capital_item("cross-after", expln))
        self.assertNotIn(AXIS_JP_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertNotIn(AXIS_FOREIGN_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertEqual(relevance.confirmed_axes, ())
        self.assertEqual(record.disposition, "region_review_required")
        self.assertTrue(all(job.stage != "ai_enrichment" for job in record.jobs))

    def test_cross_sentence_national_limit_before_positive_is_review(self) -> None:
        expln = (
            "대한민국 국민만 대상입니다. 재한 일본인은 신청 가능합니다. "
            "외국인 청년도 신청 가능합니다. 서울 거주자를 대상으로 합니다."
        )
        relevance = classify_policy_relevance(expln)
        record = observation_for(self._capital_item("cross-before", expln))
        self.assertNotIn(AXIS_JP_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertNotIn(AXIS_FOREIGN_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertEqual(record.disposition, "region_review_required")
        self.assertTrue(all(job.stage != "ai_enrichment" for job in record.jobs))

    def test_national_limit_does_not_block_kr_japan_activity_axis(self) -> None:
        expln = (
            "한국 청년을 위한 일본 유학 지원 사업입니다. "
            "대한민국 국민만 대상입니다. 서울·경기 거주자가 대상입니다."
        )
        relevance = classify_policy_relevance(expln)
        record = observation_for(self._capital_item("study-limit", expln))
        self.assertIn(AXIS_KR_JAPAN_ACTIVITY, relevance.confirmed_axes)
        self.assertNotIn(AXIS_JP_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertNotIn(AXIS_FOREIGN_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertEqual(record.disposition, "target")
        self.assertEqual(record.jobs, ())

    def test_national_limit_does_not_block_exchange_axis(self) -> None:
        expln = "한일 청년 교류 포럼입니다. 대한민국 국민만 대상입니다. 온라인 참여가 가능합니다."
        item = policy_item(
            "exchange-limit",
            zip_cd="",
            oper_cd="",
            group="0054001",
            plcyExplnCn=expln,
            plcySprtCn=expln,
        )
        relevance = classify_policy_relevance(expln)
        record = observation_for(item)
        self.assertIn(AXIS_KR_JP_EXCHANGE, relevance.confirmed_axes)
        self.assertNotIn(AXIS_JP_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertNotIn(AXIS_FOREIGN_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertEqual(record.disposition, "target")
        self.assertEqual(record.jobs, ())

    def test_nationals_and_foreigners_both_eligible_is_not_lock_false_positive(self) -> None:
        expln = "대한민국 국민과 외국인 모두 참여 가능합니다. 서울 거주 청년이 대상입니다."
        relevance = classify_policy_relevance(expln)
        record = observation_for(self._capital_item("nationals-and-foreign", expln))
        self.assertIn(AXIS_FOREIGN_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertEqual(record.disposition, "target")
        self.assertEqual(record.jobs, ())

    def test_bare_korean_national_word_does_not_lock_clear_jp_eligibility(self) -> None:
        expln = "한국 거주 일본인은 신청 가능합니다. 대한민국 국민과 함께하는 서울 프로그램입니다."
        relevance = classify_policy_relevance(expln)
        record = observation_for(self._capital_item("nationals-word", expln))
        self.assertIn(AXIS_JP_RESIDENTS_IN_KR, relevance.confirmed_axes)
        self.assertEqual(record.disposition, "target")
        self.assertEqual(record.jobs, ())

    def test_keyword_only_japan_is_not_target(self) -> None:
        expln = "일본 관련 통계를 참고한 서울 청년 주거 지원입니다."
        record = observation_for(self._capital_item("kw", expln))
        self.assertEqual(record.disposition, "region_review_required")
        self.assertEqual(record.jobs[0].stage, "region_review")

    def test_noncapital_policy_has_observation_without_ai_job(self) -> None:
        record = observation_for(policy_item("p1", zip_cd="50110", oper_cd="50110"))
        self.assertEqual(record.disposition, "non_target")
        self.assertEqual(record.jobs, ())
        self.assertEqual(record.external_key, "p1")
        self.assertTrue(record.revision_hash)
        self.assertIsNone(record.classifier_decision)


class ContentScreeningTests(unittest.TestCase):
    def test_connector_does_not_screen_or_attach_classifier_decision(self) -> None:
        connector = YouthcenterContentConnector(api_key_provider=lambda: "unused")
        record = connector.to_observation(
            load_content(), permission_status="testing_only", enabled=True
        )
        self.assertIsNone(record.classifier_decision)
        self.assertIsNone(record.product_type_classification)
        self.assertTrue(all(job.stage != "ai_enrichment" for job in record.jobs))
        self.assertTrue(all(job.stage != "region_review" for job in record.jobs))
        self.assertTrue(record.body_usable)
        self.assertIsNotNone(record.normalized_payload)
        self.assertIn("activity_location_text", record.normalized_payload or {})

    def test_generic_fixture_is_review_not_ai(self) -> None:
        record = v3_content_observation(load_content())
        self.assertEqual(record.disposition, "region_review_required")
        self.assertEqual(record.jobs[0].stage, "region_review")
        self.assertTrue(all(job.stage != "content_review" for job in record.jobs))
        self.assertTrue(all(job.stage != "ai_enrichment" for job in record.jobs))
        self.assertTrue(record.body_usable)
        self.assertIsNotNone(record.normalized_payload)

    def test_c1_noncapital_content_has_no_ai_job(self) -> None:
        record = v3_content_observation(load_noncapital_content())
        self.assertEqual(record.disposition, "non_target")
        self.assertEqual(record.jobs, ())
        self.assertIsNotNone(record.normalized_payload)
        self.assertEqual(record.external_key, "syn-c1:jeju-1")

    def test_noncapital_empty_body_has_no_review_job(self) -> None:
        item = load_noncapital_content()
        item["pstWholCn"] = ""
        record = v3_content_observation(item)
        self.assertEqual(record.disposition, "non_target")
        self.assertEqual(record.jobs, ())
        self.assertFalse(record.body_usable)
        self.assertIsNotNone(record.normalized_payload)

    def test_noncapital_missing_source_url_has_no_review_job(self) -> None:
        item = load_noncapital_content()
        item["pstUrlAddr"] = None
        item["pstWholCn"] = "<p>제주 서귀포시 거주 청년만 현장 참여할 수 있습니다.</p>"
        record = v3_content_observation(item)
        self.assertFalse(record.has_source_url)
        self.assertEqual(record.disposition, "non_target")
        self.assertEqual(record.jobs, ())
        self.assertIsNotNone(record.normalized_payload)

    def test_content_capital_exchange_is_target_without_ai_job(self) -> None:
        item = load_content()
        item["pstTtl"] = "서울 한일 교류 설명회"
        item["pstWholCn"] = (
            "<p>서울에서 열리는 한일 교류 설명회입니다. "
            "한국 거주 일본인은 참석 가능합니다.</p>"
        )
        record = v3_content_observation(item)
        relevance = classify_content_relevance(
            "서울 한일 교류 설명회",
            "서울에서 열리는 한일 교류 설명회입니다. 한국 거주 일본인은 참석 가능합니다.",
        )
        self.assertTrue(relevance.confirmed)
        self.assertEqual(record.disposition, "target")
        self.assertEqual(record.jobs, ())
        self.assertIsNotNone(record.classifier_decision)
        self.assertEqual(record.classifier_decision["decision"], "approve_ai")
        self.assertNotIn("reviewer", record.classifier_decision)
        self.assertNotIn("classifier_decision", record.normalized_payload or {})


class DateParseTests(unittest.TestCase):
    def test_created_and_updated_parse_independently(self) -> None:
        ok = parse_source_datetime("2026-09-01 10:00:00")
        bad = parse_source_datetime("not-a-date")
        missing = parse_source_datetime(None)
        self.assertEqual(ok.status, "ok")
        self.assertEqual(bad.status, "unparsed")
        self.assertEqual(bad.raw, "not-a-date")
        self.assertIsNone(bad.value)
        self.assertEqual(missing.status, "missing")


class AttachmentAndSanitizeTests(unittest.TestCase):
    def test_atchfile_dropped_and_meta_kept(self) -> None:
        payload = load_content()
        cleaned, meta = drop_forbidden_attachments(payload)
        self.assertTrue(meta.present)
        self.assertTrue(meta.is_data_url)
        self.assertGreater(meta.length, 0)
        self.assertNotIn("atchFile", cleaned)
        blob = json.dumps(cleaned, ensure_ascii=False)
        self.assertNotIn(ATCH_SNIPPET, blob)
        self.assertNotIn("atchFile", blob)

    def test_html_to_plain_text_strips_script(self) -> None:
        text = html_to_plain_text(
            "<p>안녕</p><script>alert(1)</script><iframe src='x'></iframe>"
        )
        self.assertIn("안녕", text)
        self.assertNotIn("alert", text)
        self.assertNotIn("<script", text)


class ContentJobPlanTests(unittest.TestCase):
    def test_usable_unknown_region_creates_review_not_ai(self) -> None:
        disposition, jobs = content_job_and_flags(
            body_usable=True,
            has_source_url=True,
            attachment_present=False,
            permission_ok=True,
            region_scope="unknown",
            relevance_confirmed=False,
        )
        self.assertEqual(disposition, "region_review_required")
        self.assertEqual(jobs[0].stage, "region_review")
        self.assertTrue(all(job.stage != "ai_enrichment" for job in jobs))

    def test_usable_unconfirmed_relevance_creates_relevance_review(self) -> None:
        disposition, jobs = content_job_and_flags(
            body_usable=True,
            has_source_url=True,
            attachment_present=False,
            permission_ok=True,
            region_scope="capital",
            relevance_confirmed=False,
        )
        self.assertEqual(disposition, "region_review_required")
        self.assertEqual(jobs[0].stage, "relevance_review")

    def test_clear_fit_is_target_without_ai_job(self) -> None:
        disposition, jobs = content_job_and_flags(
            body_usable=True,
            has_source_url=True,
            attachment_present=False,
            permission_ok=True,
            region_scope="capital",
            relevance_confirmed=True,
        )
        self.assertEqual(disposition, "target")
        self.assertEqual(jobs, ())

    def test_noncapital_has_no_job(self) -> None:
        disposition, jobs = content_job_and_flags(
            body_usable=True,
            has_source_url=True,
            attachment_present=False,
            permission_ok=True,
            region_scope="noncapital",
            relevance_confirmed=True,
        )
        self.assertEqual(disposition, "non_target")
        self.assertEqual(jobs, ())

    def test_noncapital_empty_body_or_missing_url_has_no_review_job(self) -> None:
        cases = [
            dict(body_usable=False, has_source_url=True, attachment_present=False),
            dict(body_usable=True, has_source_url=False, attachment_present=False),
            dict(body_usable=False, has_source_url=False, attachment_present=True),
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                disposition, jobs = content_job_and_flags(
                    permission_ok=True,
                    region_scope="noncapital",
                    relevance_confirmed=False,
                    **kwargs,
                )
                self.assertEqual(disposition, "non_target")
                self.assertEqual(jobs, ())

    def test_unknown_empty_body_still_content_review(self) -> None:
        disposition, jobs = content_job_and_flags(
            body_usable=False,
            has_source_url=True,
            attachment_present=False,
            permission_ok=True,
            region_scope="unknown",
            relevance_confirmed=False,
        )
        self.assertEqual(disposition, "observe_only")
        self.assertEqual(jobs[0].stage, "content_review")
        self.assertIn("empty_body", jobs[0].reason_codes)

    def test_each_missing_positive_condition_skips_ai(self) -> None:
        cases = [
            dict(body_usable=False, has_source_url=True, attachment_present=False, permission_ok=True),
            dict(body_usable=True, has_source_url=False, attachment_present=False, permission_ok=True),
            dict(body_usable=True, has_source_url=True, attachment_present=False, permission_ok=False),
            dict(body_usable=False, has_source_url=True, attachment_present=True, permission_ok=True),
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                _disposition, jobs = content_job_and_flags(
                    region_scope="capital",
                    relevance_confirmed=True,
                    **kwargs,
                )
                self.assertTrue(all(job.stage != "ai_enrichment" for job in jobs))
                self.assertTrue(any(job.stage == "content_review" for job in jobs))


class HttpClientTests(unittest.TestCase):
    def test_default_sleeper_is_production_sleep(self) -> None:
        self.assertIs(HttpClient(budget=1).sleep, PRODUCTION_SLEEP)
        self.assertIs(PRODUCTION_SLEEP, time.sleep)

    def test_budget_includes_retries_and_blocks_extra_calls(self) -> None:
        calls: list[int] = []
        sleeps: list[float] = []

        def transport(*_args: Any, **_kwargs: Any) -> FakeStreamResponse:
            calls.append(1)
            if len(calls) < 3:
                return FakeStreamResponse(500, chunks=[b"err"])
            return FakeStreamResponse(200, json_payload={"ok": True})

        client = HttpClient(budget=3, sleep=sleeps.append, transport=transport)
        payload, status, _size = client.get_json("https://example.test/x")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(client.request_count, 3)
        self.assertEqual(sleeps, [1.0, 2.0])
        with self.assertRaises(HttpBudgetExhausted):
            client.get_json("https://example.test/x")
        self.assertEqual(len(calls), 3)

    def test_retryable_statuses_stop_after_three_attempts(self) -> None:
        for status in sorted(RETRYABLE_STATUSES):
            with self.subTest(status=status):
                calls = {"n": 0}

                def transport(*_args: Any, **_kwargs: Any) -> FakeStreamResponse:
                    calls["n"] += 1
                    return FakeStreamResponse(status, chunks=[b"err"])

                client = HttpClient(
                    budget=10, sleep=NO_SLEEP, transport=transport, max_attempts=3
                )
                with self.assertRaises(HttpStatusError) as ctx:
                    client.get_json("https://example.test/x")
                self.assertEqual(ctx.exception.status, status)
                self.assertEqual(calls["n"], 3)
                self.assertEqual(client.request_count, 3)

    def test_403_is_not_retried(self) -> None:
        calls = {"n": 0}

        def transport(*_args: Any, **_kwargs: Any) -> FakeStreamResponse:
            calls["n"] += 1
            return FakeStreamResponse(403, chunks=[b"secret"])

        client = HttpClient(budget=10, sleep=NO_SLEEP, transport=transport)
        with self.assertRaises(HttpStatusError):
            client.get_json("https://example.test/x")
        self.assertEqual(calls["n"], 1)

    def test_oversized_content_length_does_not_read_chunks(self) -> None:
        response = FakeStreamResponse(
            200,
            headers={"Content-Length": str(9_000_000)},
            chunks=[ATCH_MARKER.encode("utf-8") * 10],
        )
        client = HttpClient(
            budget=5,
            max_response_bytes=8_000_000,
            sleep=NO_SLEEP,
            transport=lambda *_a, **_k: response,
        )
        with self.assertRaises(ResponseTooLarge) as ctx:
            client.get_json("https://example.test/x")
        self.assertEqual(response.chunk_reads, 0)
        self.assertTrue(response.closed)
        self.assertNotIn(ATCH_MARKER, str(ctx.exception))
        self.assertEqual(client.request_count, 1)

    def test_missing_content_length_stops_when_chunks_exceed_cap(self) -> None:
        response = FakeStreamResponse(
            200,
            headers={},
            chunks=[b"a" * 5_000_000, (ATCH_MARKER + "b" * 4_000_000).encode("utf-8")],
        )
        client = HttpClient(
            budget=5,
            max_response_bytes=8_000_000,
            sleep=NO_SLEEP,
            transport=lambda *_a, **_k: response,
        )
        with self.assertRaises(ResponseTooLarge) as ctx:
            client.get_json("https://example.test/x")
        self.assertEqual(response.chunk_reads, 2)
        self.assertTrue(response.closed)
        self.assertNotIn(ATCH_MARKER, str(ctx.exception))
        self.assertNotIn(ATCH_MARKER, repr(ctx.exception))

    def test_under_cap_parses_json(self) -> None:
        client = HttpClient(
            budget=5,
            sleep=NO_SLEEP,
            transport=lambda *_a, **_k: FakeStreamResponse(
                200, json_payload={"result": {"ok": True}}
            ),
        )
        payload, status, size = client.get_json("https://example.test/x")
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["ok"], True)
        self.assertGreater(size, 0)

    def test_api_key_not_exposed_in_exception_traceback_or_logs(self) -> None:
        leaky_url = f"https://example.test/x?apiKeyNm={HTTP_KEY_MARKER}"

        def transport(*_args: Any, **_kwargs: Any) -> Any:
            raise requests.Timeout(f"Read timed out. (url: {leaky_url})")

        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        logger = logging.getLogger("ingest.http_client")
        logger.addHandler(handler)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = buf
        sys.stderr = buf
        try:
            client = HttpClient(budget=5, sleep=NO_SLEEP, transport=transport)
            with self.assertRaises(HttpRequestFailed) as ctx:
                client.get_json(leaky_url, params={"apiKeyNm": HTTP_KEY_MARKER})
        finally:
            sys.stdout = old_out
            sys.stderr = old_err
            logger.removeHandler(handler)
        exc = ctx.exception
        visible = "".join(
            [
                str(exc),
                repr(exc),
                "".join(traceback.format_exception(exc)),
                buf.getvalue(),
            ]
        )
        self.assertEqual(str(exc), "timeout")
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        self.assertNotIn(HTTP_KEY_MARKER, visible)
        self.assertNotIn("apiKeyNm=", str(exc))
        self.assertNotIn("apiKeyNm=", repr(exc))


class StoreLeaseTests(unittest.TestCase):
    def test_stale_worker_cannot_advance_checkpoint_or_release_new_lease(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        first = store.start_ingest_run(CANONICAL_POLICY_SOURCE, lease_seconds=60)
        clock.advance(120)
        second = store.start_ingest_run(CANONICAL_POLICY_SOURCE, lease_seconds=60)
        self.assertFalse(second.skipped)
        record = observation_for(policy_item("p1", zip_cd="11680", oper_cd="11680"))
        with self.assertRaises(LeaseLost):
            store.upsert_source_observations(
                CANONICAL_POLICY_SOURCE,
                first.run_id,
                [record],
                Checkpoint.for_rest_page(2),
            )
        self.assertIsNone(store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint)
        store.finish_ingest_run(
            first.run_id,
            status="complete",
            stop_reason="streak_complete",
            http_request_count=1,
            bootstrap_complete=True,
        )
        sync = store.sync[CANONICAL_POLICY_SOURCE]
        self.assertEqual(sync.lease_owner, second.run_id)
        self.assertFalse(sync.bootstrap_complete)
        self.assertEqual(store.runs[first.run_id].stop_reason, "lease_lost")

    def test_batch_mid_failure_rolls_back_entire_batch(self) -> None:
        store = MemoryIngestStore()
        started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
        good = observation_for(policy_item("p1", zip_cd="11680", oper_cd="11680"))
        bad = observation_for(policy_item("p2", zip_cd="11680", oper_cd="11680"))
        bad = ObservationRecord(**{**bad.__dict__, "external_key": ""})
        with self.assertRaises(ValueError):
            store.upsert_source_observations(
                CANONICAL_POLICY_SOURCE,
                started.run_id,
                [good, bad],
                Checkpoint.for_rest_page(2),
            )
        self.assertEqual(store.items, {})
        self.assertIsNone(store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint)

    def test_previous_batch_survives_later_failure(self) -> None:
        store = MemoryIngestStore()
        item = policy_item("p1", zip_cd="11680", oper_cd="11680")
        connector = FakeConnector(
            batches=[
                BatchResult(
                    items=(item,),
                    next_checkpoint=Checkpoint.for_rest_page(2),
                    natural_end=False,
                )
            ],
            fetch_error=HttpStatusError(500),
            error_on=2,
        )
        result = run_connector(connector, store, sleep=lambda _s: None)
        self.assertEqual(result.status, "incomplete")
        self.assertIn((CANONICAL_POLICY_SOURCE, "p1"), store.items)
        self.assertIsNotNone(
            store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint
        )


class JobClaimTests(unittest.TestCase):
    def test_human_jobs_are_not_claimed_by_ai_worker(self) -> None:
        store = MemoryIngestStore()
        started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
        hwasun = observation_for(load_hwasun())
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE,
            started.run_id,
            [hwasun],
            Checkpoint.for_rest_page(2),
        )
        stages = {job.processing_stage for job in store.jobs.values()}
        self.assertEqual(stages, {"region_review"})
        claimed = store.claim_processing_jobs(
            "ai_enrichment", limit=10, worker_id=WORKER_ID
        )
        self.assertEqual(claimed, [])
        self.assertEqual(store.jobs_for_stage("region_review")[0].status, "queued")

    def test_injected_ai_without_approve_is_not_claimed(self) -> None:
        store = MemoryIngestStore()
        started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
        record = observation_for(
            policy_item("p-no-approve", zip_cd="11680", oper_cd="11680")
        )
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE,
            started.run_id,
            [record],
            Checkpoint.for_rest_page(2),
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "p-no-approve")]
        store._insert_job(
            item.id, item.revision_hash, "ai_enrichment", store._clock(), ()
        )
        self.assertEqual(len(store.jobs_for_stage("ai_enrichment")), 1)
        self.assertEqual(
            store.claim_processing_jobs(
                "ai_enrichment", limit=10, worker_id=WORKER_ID
            ),
            [],
        )
        self.assertEqual(store.jobs_for_stage("ai_enrichment")[0].status, "queued")

    def test_ai_claim_cap_ten_keeps_backlog(self) -> None:
        store = MemoryIngestStore()
        _seed_ai_jobs(store, 12)
        result = process_ai_jobs(store, limit=10, **_ai_deps())
        self.assertEqual(result.status, "processed")
        self.assertEqual(result.claimed, 10)
        self.assertEqual(result.completed, 10)
        queued = [
            job
            for job in store.jobs.values()
            if job.processing_stage == "ai_enrichment" and job.status == "queued"
        ]
        self.assertEqual(len(queued), 2)


class OrchestratorTests(unittest.TestCase):
    def test_bootstrap_incomplete_does_not_set_complete_flag(self) -> None:
        store = MemoryIngestStore()
        item = policy_item("p1", zip_cd="11680", oper_cd="11680")
        connector = FakeConnector(
            batches=[
                BatchResult(
                    items=(item,),
                    next_checkpoint=Checkpoint.for_rest_page(2),
                    natural_end=False,
                )
            ],
            fetch_error=HttpStatusError(500),
            error_on=2,
            bootstrap_max_pages=5,
        )
        result = run_connector(connector, store, sleep=lambda _s: None)
        self.assertEqual(result.status, "incomplete")
        self.assertFalse(store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete)
        self.assertIn((CANONICAL_POLICY_SOURCE, "p1"), store.items)

    def test_ordering_anomaly_continues_to_max_pages(self) -> None:
        store = MemoryIngestStore()
        # seed bootstrap complete so this is a normal run using max_pages
        store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete = True
        batches = []
        for page in range(1, 4):
            batches.append(
                BatchResult(
                    items=(
                        policy_item(
                            f"p{page}",
                            zip_cd="11680",
                            oper_cd="11680",
                            updated="2026-09-01 00:00:00"
                            if page == 2
                            else f"2026-09-{10 + page:02d} 00:00:00",
                        ),
                    ),
                    next_checkpoint=Checkpoint.for_rest_page(page + 1),
                    natural_end=False,
                )
            )
        connector = FakeConnector(batches=batches, max_pages=3, bootstrap_max_pages=3)
        result = run_connector(connector, store, sleep=lambda _s: None)
        self.assertEqual(result.stop_reason, "ordering_anomaly")
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.batches_ok, 3)

    def test_fresh_from_origin_ignores_committed_checkpoint(self) -> None:
        store = MemoryIngestStore()
        store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint = {"page_num": 9}
        seen: list[Checkpoint | None] = []

        class Tracking(FakeConnector):
            def fetch_batch(self, checkpoint: Checkpoint | None) -> BatchResult:
                seen.append(checkpoint)
                return super().fetch_batch(checkpoint)

        connector = Tracking(
            batches=[
                BatchResult(items=(), next_checkpoint=None, natural_end=True),
            ]
        )
        run_connector(connector, store, sleep=lambda _s: None)
        self.assertEqual(seen[0], None)

    def test_resume_committed_uses_saved_checkpoint(self) -> None:
        store = MemoryIngestStore()
        store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint = {"page_num": 4}
        seen: list[int | None] = []

        class Resume(FakeConnector):
            start_mode = "resume_committed"

            def fetch_batch(self, checkpoint: Checkpoint | None) -> BatchResult:
                seen.append(None if checkpoint is None else checkpoint.rest_page_num())
                return BatchResult(items=(), next_checkpoint=None, natural_end=True)

        run_connector(Resume(), store, sleep=lambda _s: None)
        self.assertEqual(seen[0], 4)

    def test_source_failures_are_isolated(self) -> None:
        store = MemoryIngestStore()
        bad = FakeConnector(fetch_error=HttpStatusError(403), error_on=1)
        good_item = policy_item("ok1", zip_cd="11680", oper_cd="11680")
        good = FakeConnector(
            batches=[
                BatchResult(items=(good_item,), next_checkpoint=None, natural_end=True)
            ],
            source_id=CANONICAL_POLICY_SOURCE,
        )
        # two sequential runs on same source would conflict; isolation is per call.
        first = run_connector(bad, store, sleep=lambda _s: None)
        second = run_connector(good, store, sleep=lambda _s: None)
        self.assertEqual(first.status, "failed")
        self.assertGreaterEqual(second.batches_ok, 1)

    def test_http_budget_stop_keeps_prior_batch(self) -> None:
        store = MemoryIngestStore()
        item = policy_item("p1", zip_cd="11680", oper_cd="11680")
        connector = FakeConnector(
            batches=[
                BatchResult(
                    items=(item,),
                    next_checkpoint=Checkpoint.for_rest_page(2),
                    natural_end=False,
                )
            ],
            http_budget=1,
            max_pages=10,
        )
        connector.http.request_count = 0
        result = run_connector(connector, store, sleep=lambda _s: None)
        self.assertEqual(result.stop_reason, "http_budget_exhausted")
        self.assertEqual(result.status, "incomplete")
        self.assertIn((CANONICAL_POLICY_SOURCE, "p1"), store.items)


class PolicyConnectorTests(unittest.TestCase):
    def test_hwasun_creates_region_review_not_ai(self) -> None:
        store = MemoryIngestStore()
        started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
        record = observation_for(load_hwasun())
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE,
            started.run_id,
            [record],
            Checkpoint.for_rest_page(2),
        )
        self.assertEqual(record.disposition, "region_review_required")
        self.assertEqual(
            {job.processing_stage for job in store.jobs.values()},
            {"region_review"},
        )

    def test_non_target_has_no_normalized_payload_or_job(self) -> None:
        record = observation_for(policy_item("p1", zip_cd="50110", oper_cd="50110"))
        self.assertEqual(record.disposition, "non_target")
        self.assertIsNone(record.normalized_payload)
        self.assertEqual(record.jobs, ())

    def test_revision_hash_ignores_view_count(self) -> None:
        a = observation_for(policy_item("p1", zip_cd="11680", oper_cd="11680", inqCnt="1"))
        b = observation_for(policy_item("p1", zip_cd="11680", oper_cd="11680", inqCnt="999"))
        self.assertEqual(a.revision_hash, b.revision_hash)


class ContentConnectorTests(unittest.TestCase):
    def test_fixture_drops_atchfile_from_payload_and_hash_inputs(self) -> None:
        connector = YouthcenterContentConnector(api_key_provider=lambda: "unused")
        item = load_content()
        record = connector.to_observation(
            item, permission_status="testing_only", enabled=True
        )
        dumped = json.dumps(record.to_rpc_item(), ensure_ascii=False)
        self.assertNotIn(ATCH_SNIPPET, dumped)
        self.assertNotIn("atchFile", dumped)
        self.assertTrue(record.attachment_present)
        self.assertTrue(record.body_usable)
        self.assertTrue(record.has_source_url)
        self.assertTrue(all(job.stage != "ai_enrichment" for job in record.jobs))

    def test_pstwholcn_html_becomes_plain_text_without_ai_job(self) -> None:
        connector = YouthcenterContentConnector(api_key_provider=lambda: "unused")
        item = load_content()
        self.assertIn("pstWholCn", item)
        self.assertNotIn("pstCn", item)
        record = connector.to_observation(
            item, permission_status="testing_only", enabled=True
        )
        plain = (record.normalized_payload or {})["plain_text"]
        self.assertIn("본문이 있는 게시물입니다", plain)
        self.assertNotIn("<p>", plain)
        self.assertNotIn("<a ", plain)
        self.assertTrue(record.body_usable)
        self.assertTrue(record.has_source_url)
        self.assertNotEqual(record.disposition, "target")
        self.assertTrue(all(job.stage != "ai_enrichment" for job in record.jobs))
        dumped = json.dumps(record.to_rpc_item(), ensure_ascii=False)
        self.assertNotIn(ATCH_SNIPPET, dumped)
        self.assertNotIn("atchFile", dumped)

    def test_empty_pstwholcn_with_attachment_stays_content_review(self) -> None:
        item = load_content()
        item["pstWholCn"] = ""
        connector = YouthcenterContentConnector(api_key_provider=lambda: "unused")
        raw = connector.to_observation(
            item, permission_status="testing_only", enabled=True
        )
        self.assertFalse(raw.body_usable)
        self.assertTrue(raw.attachment_present)
        self.assertIsNone(raw.classifier_decision)
        self.assertEqual(raw.jobs, ())
        record = v3_content_observation(item)
        self.assertEqual(record.disposition, "attachment_dependent")
        self.assertEqual(record.jobs[0].stage, "content_review")
        self.assertIn("attachment_dependent", record.jobs[0].reason_codes)

    def test_runtime_and_fixture_do_not_depend_on_pstcn(self) -> None:
        connector_src = (
            pathlib.Path(__file__).resolve().parent
            / "ingest"
            / "connectors"
            / "youthcenter_content.py"
        ).read_text(encoding="utf-8")
        fixture = load_content()
        self.assertNotIn("pstCn", connector_src)
        self.assertNotIn("pstCn", fixture)
        self.assertIn("pstWholCn", connector_src)
        self.assertIn("pstWholCn", fixture)

    def test_missing_source_url_creates_content_review(self) -> None:
        item = load_content()
        item["pstUrlAddr"] = None
        item["pstWholCn"] = "<p>본문만 있고 링크는 없습니다. 충분한 텍스트입니다.</p>"
        connector = YouthcenterContentConnector(api_key_provider=lambda: "unused")
        raw = connector.to_observation(
            item, permission_status="testing_only", enabled=True
        )
        self.assertFalse(raw.has_source_url)
        self.assertEqual(raw.jobs, ())
        record = v3_content_observation(item)
        self.assertEqual(record.jobs[0].stage, "content_review")
        self.assertIn("missing_source_url", record.jobs[0].reason_codes)


class PublishGateTests(unittest.TestCase):
    def test_testing_only_publish_is_rejected(self) -> None:
        store = MemoryIngestStore()
        with self.assertRaises(PermissionError):
            store.publish_candidate(
                candidate_source="youthcenter",
                external_key="p1",
                revision_hash="a" * 64,
                candidate_id="cand-1",
                slug="policy-p1",
            )

    def test_approved_publish_writes_event_before_lineage_lookup(self) -> None:
        store = MemoryIngestStore()
        store.sources[CANONICAL_POLICY_SOURCE].permission_status = (
            "approved_noncommercial"
        )
        curation_id = store.publish_candidate(
            candidate_source="youthcenter",
            external_key="p1",
            revision_hash="a" * 64,
            candidate_id="cand-1",
            slug="policy-p1",
        )
        self.assertEqual(store.publication_events[0]["event_kind"], "published")
        self.assertEqual(store.publication_events[0]["source_id"], CANONICAL_POLICY_SOURCE)
        self.assertEqual(store.publications[0].public_curation_id, curation_id)

    def test_hard_delete_keeps_event_after_row_removed(self) -> None:
        store = MemoryIngestStore()
        store.sources[CANONICAL_POLICY_SOURCE].permission_status = (
            "approved_noncommercial"
        )
        curation_id = store.publish_candidate(
            candidate_source="youthcenter",
            external_key="p1",
            revision_hash="a" * 64,
            candidate_id="cand-1",
            slug="policy-p1",
        )
        store.hard_delete_published_curation(curation_id, actor="postgres")
        kinds = [event["event_kind"] for event in store.publication_events]
        self.assertEqual(kinds, ["published", "hard_deleted"])
        self.assertNotIn(curation_id, store.public_curations)
        self.assertIsNone(store.publications[0].public_curation_id)


class AiWorkerEnqueueAliasTests(unittest.TestCase):
    def test_policy_jobs_use_legacy_youthcenter_source(self) -> None:
        store = MemoryIngestStore()
        _seed_ai_jobs(store, 1)
        captured: dict[str, Any] = {}

        def enqueue(_supabase: Any, params: dict[str, Any]) -> dict[str, Any]:
            captured.update(params)
            return {"outcome": "inserted", "candidate_id": "x"}

        process_ai_jobs(
            store,
            supabase=object(),
            summarize_ko=lambda text, url: (text, "success", "model"),
            translate_ja=lambda title, body: ("t", "b", "success", "model"),
            enqueue=enqueue,
            revision_precheck=lambda *_a, **_k: False,
        )
        self.assertEqual(captured["p_source"], LEGACY_POLICY_CURATION_SOURCE)
        self.assertNotIn("atchFile", json.dumps(captured["p_raw_payload"]))


class LogSafetyTests(unittest.TestCase):
    def test_atchfile_snippet_not_logged_during_content_observation(self) -> None:
        connector = YouthcenterContentConnector(api_key_provider=lambda: "unused")
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            record = connector.to_observation(
                load_content(), permission_status="testing_only", enabled=True
            )
            print("observed", record.external_key, record.disposition)
        finally:
            sys.stdout = old
        text = buf.getvalue()
        self.assertNotIn(ATCH_SNIPPET, text)
        self.assertNotIn("atchFile", text)


class AiDependencyAndRetryTests(unittest.TestCase):
    def test_missing_dependencies_do_not_claim_or_complete(self) -> None:
        store = MemoryIngestStore()
        _seed_ai_jobs(store, 3)
        queued_before = store.ai_job_counts()["queued"]
        result = process_ai_jobs(store)
        self.assertEqual(result.status, AI_SKIPPED_NOT_CONFIGURED)
        self.assertEqual(result.claimed, 0)
        self.assertEqual(result.completed, 0)
        self.assertEqual(store.ai_job_counts()["queued"], queued_before)
        self.assertEqual(store.ai_job_counts()["completed"], 0)

    def test_summarize_without_enqueue_does_not_claim(self) -> None:
        store = MemoryIngestStore()
        _seed_ai_jobs(store, 2)
        result = process_ai_jobs(
            store,
            supabase=object(),
            summarize_ko=lambda text, url: (text, "success", "model"),
        )
        self.assertEqual(result.claimed, 0)
        self.assertEqual(store.ai_job_counts()["queued"], 2)

    def test_enqueue_without_summarize_does_not_claim(self) -> None:
        store = MemoryIngestStore()
        _seed_ai_jobs(store, 2)
        result = process_ai_jobs(
            store,
            supabase=object(),
            enqueue=lambda *_a, **_k: {"outcome": "inserted"},
        )
        self.assertEqual(result.claimed, 0)
        self.assertEqual(store.ai_job_counts()["queued"], 2)

    def test_processing_exception_retries_then_terminal_failed(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        _seed_ai_jobs(store, 1)
        job_id = next(iter(store.jobs))

        def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
            raise RuntimeError("enqueue_failed")

        for attempt in range(1, AI_MAX_ATTEMPTS + 1):
            if attempt > 1:
                clock.advance(30)
            result = process_ai_jobs(store, **_ai_deps(enqueue=boom))
            job = store.jobs[job_id]
            self.assertEqual(result.claimed, 1)
            self.assertEqual(result.completed, 0)
            self.assertEqual(job.retry_count, attempt)
            if attempt < AI_MAX_ATTEMPTS:
                self.assertEqual(job.status, "queued")
                self.assertEqual(result.retried, 1)
            else:
                self.assertEqual(job.status, "failed")
                self.assertEqual(result.failed, 1)

        later = process_ai_jobs(store, **_ai_deps(enqueue=boom))
        self.assertEqual(later.claimed, 0)
        self.assertEqual(store.jobs[job_id].status, "failed")
        counts = store.ai_job_counts()
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(counts["queued"], 0)
        self.assertEqual(counts["retry_waiting"], 0)

    def test_success_completes_regardless_of_retry_count(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        _seed_ai_jobs(store, 1)
        job_id = next(iter(store.jobs))

        def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
            raise RuntimeError("enqueue_failed")

        process_ai_jobs(store, **_ai_deps(enqueue=boom))
        clock.advance(30)
        result = process_ai_jobs(store, **_ai_deps())
        self.assertEqual(result.completed, 1)
        self.assertEqual(store.jobs[job_id].status, "completed")
        self.assertEqual(store.jobs[job_id].retry_count, 1)

    def test_run_ai_false_leaves_queue_unchanged(self) -> None:
        store = MemoryIngestStore()
        _seed_ai_jobs(store, 2)
        connector = FakeConnector(
            batches=[BatchResult(items=(), next_checkpoint=None, natural_end=True)]
        )
        result = run_ingest_architecture(
            store=store,
            connectors=[connector],
            sleep=NO_SLEEP,
            run_ai=False,
        )
        self.assertEqual(result.ai.status, "ai_disabled")
        self.assertEqual(store.ai_job_counts()["queued"], 2)
        self.assertEqual(store.ai_job_counts()["completed"], 0)

    def test_run_ai_true_without_deps_keeps_collection_and_queue(self) -> None:
        store = MemoryIngestStore()
        item = policy_item("keep1", zip_cd="11680", oper_cd="11680")
        connector = FakeConnector(
            batches=[
                BatchResult(items=(item,), next_checkpoint=None, natural_end=True)
            ]
        )
        result = run_ingest_architecture(
            store=store,
            connectors=[connector],
            sleep=NO_SLEEP,
            run_ai=True,
        )
        self.assertEqual(result.ai.status, AI_SKIPPED_NOT_CONFIGURED)
        self.assertIn((CANONICAL_POLICY_SOURCE, "keep1"), store.items)
        self.assertEqual(store.ai_job_counts()["queued"], 0)
        self.assertEqual(store.ai_job_counts()["completed"], 0)
        self.assertTrue(
            any(
                job.processing_stage in {
                    "region_review",
                    "product_type_review",
                    "content_review",
                }
                for job in store.jobs.values()
            )
        )

    def test_latest_revision_skip_completes_without_enqueue(self) -> None:
        store = MemoryIngestStore()
        _seed_ai_jobs(store, 1)
        called = {"enqueue": 0}

        def enqueue(*_a: Any, **_k: Any) -> dict[str, Any]:
            called["enqueue"] += 1
            return {"outcome": "skipped"}

        result = process_ai_jobs(
            store,
            **_ai_deps(enqueue=enqueue, revision_precheck=lambda *_a, **_k: True),
        )
        self.assertEqual(result.completed, 1)
        self.assertEqual(called["enqueue"], 0)


class ProcessingJobTerminalStateTests(unittest.TestCase):
    def _claim_one(self, store: MemoryIngestStore, worker_id: str = "gate5-worker"):
        claimed = store.claim_processing_jobs(
            "ai_enrichment", worker_id=worker_id, lease_seconds=300
        )
        self.assertEqual(len(claimed), 1)
        return claimed[0]

    def test_complete_clears_claim_and_rejects_follow_up_fail(self) -> None:
        store = MemoryIngestStore()
        _seed_ai_jobs(store, 1)
        claimed = self._claim_one(store)
        store.complete_processing_job(claimed.job_id, worker_id="gate5-worker")
        job = store.jobs[claimed.job_id]
        self.assertEqual(job.status, "completed")
        self.assertIsNone(job.claimed_by)
        self.assertIsNone(job.claim_lease_until)
        self.assertEqual(job.retry_count, 0)
        with self.assertRaises(ValueError) as caught:
            store.fail_processing_job(
                claimed.job_id, worker_id="gate5-worker", error_code="x"
            )
        self.assertEqual(str(caught.exception), "unexpected_job_status")
        self.assertEqual(store.jobs[claimed.job_id].status, "completed")
        self.assertEqual(store.jobs[claimed.job_id].retry_count, 0)

    def test_failed_and_queued_reject_complete_and_fail(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        _seed_ai_jobs(store, 1)
        job_id = next(iter(store.jobs))
        with self.assertRaises(ValueError) as queued:
            store.complete_processing_job(job_id, worker_id="gate5-worker")
        self.assertEqual(str(queued.exception), "unexpected_job_status")
        with self.assertRaises(ValueError) as queued_fail:
            store.fail_processing_job(
                job_id, worker_id="gate5-worker", error_code="x"
            )
        self.assertEqual(str(queued_fail.exception), "unexpected_job_status")

        for attempt in range(1, AI_MAX_ATTEMPTS + 1):
            if attempt > 1:
                clock.advance(30)
            claimed = self._claim_one(store)
            status = store.fail_processing_job(
                claimed.job_id, worker_id="gate5-worker", error_code="x"
            )
            job = store.jobs[job_id]
            self.assertIsNone(job.claimed_by)
            self.assertIsNone(job.claim_lease_until)
            if attempt < AI_MAX_ATTEMPTS:
                self.assertEqual(status, "queued")
                self.assertEqual(job.status, "queued")
                self.assertEqual(job.retry_count, attempt)
            else:
                self.assertEqual(status, "failed")
                self.assertEqual(job.status, "failed")
                self.assertEqual(job.retry_count, 3)

        with self.assertRaises(ValueError):
            store.complete_processing_job(job_id, worker_id="gate5-worker")
        with self.assertRaises(ValueError):
            store.fail_processing_job(job_id, worker_id="gate5-worker", error_code="x")
        self.assertEqual(store.jobs[job_id].status, "failed")
        self.assertEqual(
            store.claim_processing_jobs(
                "ai_enrichment", worker_id="other", lease_seconds=300
            ),
            [],
        )

    def test_other_worker_and_expired_lease_are_rejected(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        _seed_ai_jobs(store, 1)
        claimed = store.claim_processing_jobs(
            "ai_enrichment", worker_id="owner", lease_seconds=30
        )[0]
        with self.assertRaises(LeaseLost):
            store.complete_processing_job(claimed.job_id, worker_id="other")
        with self.assertRaises(LeaseLost):
            store.fail_processing_job(
                claimed.job_id, worker_id="other", error_code="x"
            )
        self.assertEqual(store.jobs[claimed.job_id].status, "claimed")
        clock.advance(31)
        with self.assertRaises(LeaseLost):
            store.complete_processing_job(claimed.job_id, worker_id="owner")
        with self.assertRaises(LeaseLost):
            store.fail_processing_job(
                claimed.job_id, worker_id="owner", error_code="x"
            )
        self.assertEqual(store.jobs[claimed.job_id].status, "claimed")
        self.assertEqual(store.jobs[claimed.job_id].retry_count, 0)

    def test_human_stage_rejects_ai_complete_and_fail(self) -> None:
        store = MemoryIngestStore()
        _seed_ai_jobs(store, 1)
        claimed = self._claim_one(store)
        job = store.jobs[claimed.job_id]
        job.processing_stage = "region_review"
        with self.assertRaises(ValueError) as complete_err:
            store.complete_processing_job(claimed.job_id, worker_id="gate5-worker")
        with self.assertRaises(ValueError) as fail_err:
            store.fail_processing_job(
                claimed.job_id, worker_id="gate5-worker", error_code="x"
            )
        self.assertEqual(str(complete_err.exception), "human_job_not_completable_by_ai")
        self.assertEqual(str(fail_err.exception), "human_job_not_completable_by_ai")
        self.assertEqual(job.status, "claimed")
        self.assertEqual(job.retry_count, 0)


class StreakAndPageBoundTests(unittest.TestCase):
    def test_unchanged_streak_three_completes(self) -> None:
        store = MemoryIngestStore()
        store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete = True
        item = policy_item("p1", zip_cd="11680", oper_cd="11680")
        batches = [
            BatchResult(
                items=(item,),
                next_checkpoint=Checkpoint.for_rest_page(page + 1),
                natural_end=False,
            )
            for page in range(1, 5)
        ]
        result = run_connector(
            FakeConnector(batches=batches, max_pages=10),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.stop_reason, "streak_complete")
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.batches_ok, 4)

    def test_streak_crosses_batch_boundary(self) -> None:
        store = MemoryIngestStore()
        store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete = True
        item = policy_item("p1", zip_cd="11680", oper_cd="11680")
        batches = [
            BatchResult(
                items=(item,),
                next_checkpoint=Checkpoint.for_rest_page(2),
                natural_end=False,
            ),
            BatchResult(
                items=(item,),
                next_checkpoint=Checkpoint.for_rest_page(3),
                natural_end=False,
            ),
            BatchResult(
                items=(item,),
                next_checkpoint=Checkpoint.for_rest_page(4),
                natural_end=False,
            ),
            BatchResult(
                items=(item,),
                next_checkpoint=Checkpoint.for_rest_page(5),
                natural_end=False,
            ),
        ]
        result = run_connector(FakeConnector(batches=batches), store, sleep=NO_SLEEP)
        self.assertEqual(result.stop_reason, "streak_complete")
        self.assertEqual(result.batches_ok, 4)

    def test_new_or_changed_resets_streak(self) -> None:
        store = MemoryIngestStore()
        store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete = True
        first = policy_item("p1", zip_cd="11680", oper_cd="11680")
        changed = policy_item(
            "p1", zip_cd="11680", oper_cd="11680", title="바뀐 제목"
        )
        other = policy_item("p2", zip_cd="11680", oper_cd="11680")
        batches = [
            BatchResult(
                items=(first,),
                next_checkpoint=Checkpoint.for_rest_page(2),
                natural_end=False,
            ),
            BatchResult(
                items=(first,),
                next_checkpoint=Checkpoint.for_rest_page(3),
                natural_end=False,
            ),
            BatchResult(
                items=(first,),
                next_checkpoint=Checkpoint.for_rest_page(4),
                natural_end=False,
            ),
            BatchResult(
                items=(changed,),
                next_checkpoint=Checkpoint.for_rest_page(5),
                natural_end=False,
            ),
            BatchResult(
                items=(other,),
                next_checkpoint=None,
                natural_end=True,
            ),
        ]
        result = run_connector(FakeConnector(batches=batches), store, sleep=NO_SLEEP)
        self.assertNotEqual(result.stop_reason, "streak_complete")
        self.assertEqual(store.items[(CANONICAL_POLICY_SOURCE, "p1")].revision_hash,
                         observation_for(changed).revision_hash)

    def test_in_batch_duplicate_is_excluded_from_streak(self) -> None:
        store = MemoryIngestStore()
        store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete = True
        item = policy_item("p1", zip_cd="11680", oper_cd="11680")
        batches = [
            BatchResult(
                items=(item,),
                next_checkpoint=Checkpoint.for_rest_page(2),
                natural_end=False,
            ),
            BatchResult(
                items=(item,),
                next_checkpoint=Checkpoint.for_rest_page(3),
                natural_end=False,
            ),
            BatchResult(
                items=(item,),
                next_checkpoint=Checkpoint.for_rest_page(4),
                natural_end=False,
            ),
            BatchResult(
                items=(item, dict(item)),
                next_checkpoint=Checkpoint.for_rest_page(5),
                natural_end=False,
            ),
        ]
        result = run_connector(FakeConnector(batches=batches), store, sleep=NO_SLEEP)
        self.assertEqual(result.stop_reason, "streak_complete")
        self.assertEqual(result.batches_ok, 4)

    def test_max_pages_is_incomplete(self) -> None:
        store = MemoryIngestStore()
        store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete = True
        batches = [
            BatchResult(
                items=(
                    policy_item(f"p{page}", zip_cd="11680", oper_cd="11680"),
                ),
                next_checkpoint=Checkpoint.for_rest_page(page + 1),
                natural_end=False,
            )
            for page in range(1, 4)
        ]
        result = run_connector(
            FakeConnector(batches=batches, max_pages=3),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.stop_reason, "max_pages")
        self.assertEqual(result.batches_ok, 3)


class ConnectorRequestAndAttachmentTests(unittest.TestCase):
    def test_content_request_uses_page_size_two_without_pstsecd(self) -> None:
        captured: dict[str, Any] = {}

        def transport(url: str, **kwargs: Any) -> FakeStreamResponse:
            captured["url"] = url
            captured["params"] = dict(kwargs.get("params") or {})
            return FakeStreamResponse(
                200, json_payload={"result": {"youthPolicyList": []}}
            )

        http = HttpClient(budget=15, sleep=NO_SLEEP, transport=transport)
        connector = YouthcenterContentConnector(
            http=http, api_key_provider=lambda: "unused-key"
        )
        batch = connector.fetch_batch(None)
        self.assertEqual(captured["params"]["pageSize"], CONTENT_PAGE_SIZE)
        self.assertEqual(captured["params"]["pageSize"], 2)
        self.assertNotIn("pstSeCd", captured["params"])
        self.assertEqual(batch.items, ())

    def test_policy_request_uses_page_size_five(self) -> None:
        captured: dict[str, Any] = {}

        def transport(_url: str, **kwargs: Any) -> FakeStreamResponse:
            captured["params"] = dict(kwargs.get("params") or {})
            return FakeStreamResponse(
                200, json_payload={"result": {"youthPolicyList": []}}
            )

        http = HttpClient(budget=30, sleep=NO_SLEEP, transport=transport)
        connector = YouthcenterPolicyConnector(
            http=http, api_key_provider=lambda: "unused-key"
        )
        connector.fetch_batch(None)
        self.assertEqual(captured["params"]["pageSize"], POLICY_PAGE_SIZE)


POLICY_KEY_MARKER = "policy-fixture-key-DoNotLog"
CONTENT_KEY_MARKER = "content-fixture-key-DoNotLog"


class ContentCredentialSeparationTests(unittest.TestCase):
    def test_missing_content_key_does_not_fallback_or_call_http(self) -> None:
        calls = {"count": 0}

        def transport(*_args: Any, **_kwargs: Any) -> FakeStreamResponse:
            calls["count"] += 1
            raise AssertionError("youth_api_called")

        http = HttpClient(budget=15, sleep=NO_SLEEP, transport=transport)
        with patch.dict(os.environ, {"YOUTH_API_KEY": POLICY_KEY_MARKER}, clear=True):
            connector = YouthcenterContentConnector(http=http)
            with self.assertRaises(RuntimeError) as caught:
                connector.fetch_batch(None)
        self.assertEqual(str(caught.exception), "youth_content_api_key_missing")
        self.assertEqual(calls["count"], 0)
        visible = str(caught.exception)
        self.assertNotIn(POLICY_KEY_MARKER, visible)
        self.assertNotIn("apiKeyNm", visible)
        self.assertNotIn("YOUTH_API_KEY", visible)

    def test_content_env_key_is_sent_not_policy_key(self) -> None:
        captured: dict[str, Any] = {}

        def transport(_url: str, **kwargs: Any) -> FakeStreamResponse:
            captured["params"] = dict(kwargs.get("params") or {})
            return FakeStreamResponse(
                200, json_payload={"result": {"youthPolicyList": []}}
            )

        http = HttpClient(budget=15, sleep=NO_SLEEP, transport=transport)
        env = {
            "YOUTH_API_KEY": POLICY_KEY_MARKER,
            CONTENT_API_KEY_ENV: CONTENT_KEY_MARKER,
        }
        with patch.dict(os.environ, env, clear=True):
            connector = YouthcenterContentConnector(http=http)
            connector.fetch_batch(None)
        self.assertEqual(captured["params"]["apiKeyNm"], CONTENT_KEY_MARKER)
        self.assertNotEqual(captured["params"]["apiKeyNm"], POLICY_KEY_MARKER)

    def test_builder_providers_are_not_crossed(self) -> None:
        captured: dict[str, Any] = {}

        def policy_transport(_url: str, **kwargs: Any) -> FakeStreamResponse:
            captured["policy"] = dict(kwargs.get("params") or {})
            return FakeStreamResponse(
                200, json_payload={"result": {"youthPolicyList": []}}
            )

        def content_transport(_url: str, **kwargs: Any) -> FakeStreamResponse:
            captured["content"] = dict(kwargs.get("params") or {})
            return FakeStreamResponse(
                200, json_payload={"result": {"youthPolicyList": []}}
            )

        policy, content = build_youthcenter_connectors(
            policy_http=HttpClient(
                budget=30, sleep=NO_SLEEP, transport=policy_transport
            ),
            content_http=HttpClient(
                budget=15, sleep=NO_SLEEP, transport=content_transport
            ),
            policy_api_key_provider=lambda: POLICY_KEY_MARKER,
            content_api_key_provider=lambda: CONTENT_KEY_MARKER,
        )
        policy.fetch_batch(None)
        content.fetch_batch(None)
        self.assertEqual(captured["policy"]["apiKeyNm"], POLICY_KEY_MARKER)
        self.assertEqual(captured["content"]["apiKeyNm"], CONTENT_KEY_MARKER)


class ContentResponseSizeTests(unittest.TestCase):
    def test_content_cap_and_invariants_do_not_change_policy_http(self) -> None:
        content = YouthcenterContentConnector(api_key_provider=lambda: "unused")
        policy = YouthcenterPolicyConnector(api_key_provider=lambda: "unused")
        generic = HttpClient(budget=1)
        self.assertEqual(CONTENT_MAX_RESPONSE_BYTES, 16_000_000)
        self.assertEqual(content.http.max_response_bytes, 16_000_000)
        self.assertEqual(content.http.max_response_bytes, CONTENT_MAX_RESPONSE_BYTES)
        self.assertEqual(DEFAULT_MAX_RESPONSE_BYTES, 8_000_000)
        self.assertEqual(policy.http.max_response_bytes, 8_000_000)
        self.assertEqual(generic.max_response_bytes, 8_000_000)
        self.assertEqual(CONTENT_PAGE_SIZE, 2)
        self.assertEqual(CONTENT_BOOTSTRAP_MAX_PAGES, 5)
        self.assertEqual(CONTENT_BOOTSTRAP_MAX_ITEMS, 10)
        self.assertEqual(CONTENT_MAX_PAGES, 5)
        self.assertEqual(CONTENT_HTTP_BUDGET, 15)
        self.assertEqual(content.page_size, 2)
        self.assertEqual(content.bootstrap_max_pages, 5)
        self.assertEqual(content.bootstrap_max_items, 10)
        self.assertEqual(content.max_pages, 5)
        self.assertEqual(content.http_budget, 15)
        self.assertEqual(content.ordering_capability, "untrusted")
        self.assertEqual(content.http.timeout_seconds, 15)
        self.assertEqual(content.http.max_attempts, 3)
        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, 15)
        self.assertEqual(MAX_ATTEMPTS, 3)
        self.assertEqual(policy.http.timeout_seconds, DEFAULT_TIMEOUT_SECONDS)
        self.assertEqual(policy.http.max_attempts, MAX_ATTEMPTS)

    def test_content_cap_allows_one_byte_under_and_exact_limit(self) -> None:
        under = _ascii_json_of_size(CONTENT_MAX_RESPONSE_BYTES - 1)
        exact = _ascii_json_of_size(CONTENT_MAX_RESPONSE_BYTES)

        def transport_under(*_a: Any, **_k: Any) -> FakeStreamResponse:
            return FakeStreamResponse(200, chunks=[under])

        def transport_exact(*_a: Any, **_k: Any) -> FakeStreamResponse:
            return FakeStreamResponse(200, chunks=[exact])

        under_client = HttpClient(
            budget=5,
            max_response_bytes=CONTENT_MAX_RESPONSE_BYTES,
            sleep=NO_SLEEP,
            transport=transport_under,
        )
        exact_client = HttpClient(
            budget=5,
            max_response_bytes=CONTENT_MAX_RESPONSE_BYTES,
            sleep=NO_SLEEP,
            transport=transport_exact,
        )
        payload_under, status_under, size_under = under_client.get_json(
            "https://example.test/x"
        )
        payload_exact, status_exact, size_exact = exact_client.get_json(
            "https://example.test/x"
        )
        self.assertEqual(status_under, 200)
        self.assertEqual(status_exact, 200)
        self.assertEqual(size_under, CONTENT_MAX_RESPONSE_BYTES - 1)
        self.assertEqual(size_exact, CONTENT_MAX_RESPONSE_BYTES)
        self.assertIsInstance(payload_under, dict)
        self.assertIsInstance(payload_exact, dict)

    def test_content_length_over_cap_does_not_stream_or_parse(self) -> None:
        response = FakeStreamResponse(
            200,
            headers={"Content-Length": str(CONTENT_MAX_RESPONSE_BYTES + 1)},
            chunks=[ATCH_MARKER.encode("ascii")],
        )
        client = HttpClient(
            budget=5,
            max_response_bytes=CONTENT_MAX_RESPONSE_BYTES,
            sleep=NO_SLEEP,
            transport=lambda *_a, **_k: response,
        )
        with patch("ingest.http_client.json.loads") as loads:
            with self.assertRaises(ResponseTooLarge) as ctx:
                client.get_json("https://example.test/x")
            loads.assert_not_called()
        self.assertEqual(response.chunk_reads, 0)
        self.assertTrue(response.closed)
        self.assertEqual(str(ctx.exception), "response_too_large")
        self.assertNotIn(ATCH_MARKER, str(ctx.exception))
        self.assertEqual(client.request_count, 1)

    def test_streaming_over_cap_does_not_parse_json(self) -> None:
        response = FakeStreamResponse(
            200,
            headers={},
            chunks=[
                b"a" * CONTENT_MAX_RESPONSE_BYTES,
                ATCH_MARKER.encode("ascii"),
            ],
        )
        client = HttpClient(
            budget=5,
            max_response_bytes=CONTENT_MAX_RESPONSE_BYTES,
            sleep=NO_SLEEP,
            transport=lambda *_a, **_k: response,
        )
        with patch("ingest.http_client.json.loads") as loads:
            with self.assertRaises(ResponseTooLarge) as ctx:
                client.get_json("https://example.test/x")
            loads.assert_not_called()
        self.assertEqual(response.chunk_reads, 2)
        self.assertTrue(response.closed)
        self.assertEqual(str(ctx.exception), "response_too_large")
        self.assertNotIn(ATCH_MARKER, str(ctx.exception))
        self.assertNotIn(ATCH_MARKER, repr(ctx.exception))
        self.assertEqual(client.request_count, 1)

    def test_one_byte_over_cap_is_blocked_before_json(self) -> None:
        response = FakeStreamResponse(
            200,
            headers={},
            chunks=[b"a" * (CONTENT_MAX_RESPONSE_BYTES + 1)],
        )
        client = HttpClient(
            budget=5,
            max_response_bytes=CONTENT_MAX_RESPONSE_BYTES,
            sleep=NO_SLEEP,
            transport=lambda *_a, **_k: response,
        )
        with patch("ingest.http_client.json.loads") as loads:
            with self.assertRaises(ResponseTooLarge):
                client.get_json("https://example.test/x")
            loads.assert_not_called()
        self.assertEqual(response.chunk_reads, 1)
        self.assertTrue(response.closed)
        self.assertEqual(client.request_count, 1)

    def test_observed_probe_size_parses_and_drops_attachment(self) -> None:
        raw = _content_list_json_bytes(OBSERVED_CONTENT_PROBE_BYTES)
        self.assertEqual(len(raw), OBSERVED_CONTENT_PROBE_BYTES)

        def transport(*_a: Any, **_k: Any) -> FakeStreamResponse:
            return FakeStreamResponse(200, chunks=[raw])

        http = HttpClient(
            budget=CONTENT_HTTP_BUDGET,
            max_response_bytes=CONTENT_MAX_RESPONSE_BYTES,
            sleep=NO_SLEEP,
            transport=transport,
        )
        connector = YouthcenterContentConnector(
            http=http, api_key_provider=lambda: "unused-key"
        )
        batch = connector.fetch_batch(None)
        self.assertEqual(len(batch.items), 1)
        item = batch.items[0]
        self.assertNotIn("atchFile", item)
        self.assertFalse(contains_forbidden_attachment_key(item))
        self.assertTrue(item["attachment_present"])
        dumped_item = json.dumps(item, ensure_ascii=True)
        self.assertNotIn(ATCH_MARKER, dumped_item)

        record = connector.to_observation(
            item, permission_status="testing_only", enabled=True
        )
        normalized = record.normalized_payload or {}
        dumped_normalized = json.dumps(normalized, ensure_ascii=True)
        dumped_rpc = json.dumps(record.to_rpc_item(), ensure_ascii=True)
        self.assertNotIn(ATCH_MARKER, dumped_normalized)
        self.assertNotIn(ATCH_MARKER, dumped_rpc)
        self.assertNotIn("atchFile", dumped_normalized)
        self.assertNotIn("atchFile", dumped_rpc)
        self.assertNotIn(ATCH_MARKER, record.revision_hash)
        self.assertFalse(contains_forbidden_attachment_key(normalized))
        self.assertEqual(record.external_key, "bbs-1:pst-1")


class ConnectorRequestAndAttachmentFollowupTests(unittest.TestCase):
    def test_fetch_batch_drops_atchfile_immediately_without_mutating_input(self) -> None:
        original = load_content()
        original["atchFile"] = ATCH_MARKER
        original["nested"] = {"atchFile": ATCH_MARKER}
        payload_items = [original]

        def transport(*_a: Any, **_k: Any) -> FakeStreamResponse:
            return FakeStreamResponse(
                200,
                json_payload={"result": {"youthPolicyList": payload_items}},
            )

        http = HttpClient(budget=15, sleep=NO_SLEEP, transport=transport)
        connector = YouthcenterContentConnector(
            http=http, api_key_provider=lambda: "unused-key"
        )
        batch = connector.fetch_batch(None)
        self.assertEqual(len(batch.items), 1)
        self.assertNotIn("atchFile", batch.items[0])
        self.assertFalse(contains_forbidden_attachment_key(batch.items[0]))
        dumped = json.dumps(batch.items[0], ensure_ascii=False)
        self.assertNotIn(ATCH_MARKER, dumped)
        self.assertTrue(batch.items[0]["attachment_present"])
        self.assertIn("atchFile", original)
        self.assertEqual(original["atchFile"], ATCH_MARKER)
        self.assertEqual(original["nested"]["atchFile"], ATCH_MARKER)

        record = connector.to_observation(
            batch.items[0], permission_status="testing_only", enabled=True
        )
        rpc = json.dumps(record.to_rpc_item(), ensure_ascii=False)
        self.assertNotIn(ATCH_MARKER, rpc)
        self.assertNotIn("atchFile", rpc)
        self.assertTrue(record.attachment_present)

    def test_policy_fetch_batch_strips_nested_atchfile(self) -> None:
        original = policy_item("p1", zip_cd="11680", oper_cd="11680")
        original["atchFile"] = ATCH_MARKER
        original["extra"] = {"atch_file": ATCH_MARKER}

        def transport(*_a: Any, **_k: Any) -> FakeStreamResponse:
            return FakeStreamResponse(
                200,
                json_payload={"result": {"youthPolicyList": [original]}},
            )

        http = HttpClient(budget=30, sleep=NO_SLEEP, transport=transport)
        connector = YouthcenterPolicyConnector(
            http=http, api_key_provider=lambda: "unused-key"
        )
        batch = connector.fetch_batch(None)
        self.assertNotIn("atchFile", batch.items[0])
        self.assertFalse(contains_forbidden_attachment_key(batch.items[0]))
        self.assertEqual(original["atchFile"], ATCH_MARKER)

    def test_sanitize_copies_do_not_share_input_dicts(self) -> None:
        item = {"pstSn": "1", "atchFile": ATCH_MARKER}
        copies = extract_sanitized_source_items([item, item])
        copies[0]["pstSn"] = "changed"
        self.assertEqual(item["pstSn"], "1")
        self.assertEqual(copies[1]["pstSn"], "1")
        self.assertIn("atchFile", item)


class LeaseAndPermissionTests(unittest.TestCase):
    def test_default_lease_ttl_is_120(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
        sync = store.sync[CANONICAL_POLICY_SOURCE]
        self.assertEqual(store.runs[started.run_id].lease_seconds, DEFAULT_LEASE_SECONDS)
        self.assertEqual(
            sync.lease_expires_at,
            clock.now + timedelta(seconds=DEFAULT_LEASE_SECONDS),
        )

    def test_default_job_claim_lease_is_600(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        _seed_ai_jobs(store, 1)
        claimed = store.claim_processing_jobs("ai_enrichment", worker_id="w")
        self.assertEqual(len(claimed), 1)
        self.assertEqual(DEFAULT_JOB_LEASE_SECONDS, 600)
        self.assertEqual(DEFAULT_LEASE_SECONDS, 120)
        job = store.jobs[claimed[0].job_id]
        self.assertEqual(
            job.claim_lease_until,
            clock.now + timedelta(seconds=DEFAULT_JOB_LEASE_SECONDS),
        )

    def test_explicit_job_claim_lease_override_is_kept(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        _seed_ai_jobs(store, 1)
        claimed = store.claim_processing_jobs(
            "ai_enrichment", worker_id="w", lease_seconds=300
        )
        job = store.jobs[claimed[0].job_id]
        self.assertEqual(
            job.claim_lease_until,
            clock.now + timedelta(seconds=300),
        )

    def test_custom_ttl_is_reused_on_batch_renew(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        started = store.start_ingest_run(CANONICAL_POLICY_SOURCE, lease_seconds=180)
        clock.advance(10)
        record = observation_for(policy_item("p1", zip_cd="11680", oper_cd="11680"))
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE,
            started.run_id,
            [record],
            Checkpoint.for_rest_page(2),
        )
        sync = store.sync[CANONICAL_POLICY_SOURCE]
        self.assertEqual(store.runs[started.run_id].lease_seconds, 180)
        self.assertEqual(sync.lease_expires_at, clock.now + timedelta(seconds=180))

    def test_out_of_range_ttl_is_rejected(self) -> None:
        store = MemoryIngestStore()
        with self.assertRaises(ValueError):
            store.start_ingest_run(
                CANONICAL_POLICY_SOURCE, lease_seconds=LEASE_SECONDS_MIN - 1
            )
        with self.assertRaises(ValueError):
            store.start_ingest_run(
                CANONICAL_POLICY_SOURCE, lease_seconds=LEASE_SECONDS_MAX + 1
            )

    def test_other_run_cannot_change_ttl(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        first = store.start_ingest_run(CANONICAL_POLICY_SOURCE, lease_seconds=60)
        clock.advance(120)
        second = store.start_ingest_run(CANONICAL_POLICY_SOURCE, lease_seconds=240)
        record = observation_for(policy_item("p1", zip_cd="11680", oper_cd="11680"))
        with self.assertRaises(LeaseLost):
            store.upsert_source_observations(
                CANONICAL_POLICY_SOURCE,
                first.run_id,
                [record],
                Checkpoint.for_rest_page(2),
            )
        self.assertEqual(store.runs[second.run_id].lease_seconds, 240)
        self.assertEqual(store.sync[CANONICAL_POLICY_SOURCE].lease_seconds, 240)

    def test_permission_change_is_atomic_with_event(self) -> None:
        store = MemoryIngestStore()
        store.set_source_permission(
            CANONICAL_POLICY_SOURCE,
            "approved_noncommercial",
            reason="review passed",
            evidence_note="note",
            actor="postgres",
        )
        self.assertEqual(
            store.sources[CANONICAL_POLICY_SOURCE].permission_status,
            "approved_noncommercial",
        )
        self.assertEqual(len(store.permission_events), 1)
        self.assertEqual(store.permission_events[0]["from_status"], "testing_only")

        store._fail_permission_event = True
        with self.assertRaises(RuntimeError):
            store.set_source_permission(
                CANONICAL_POLICY_SOURCE,
                "commercial_review_required",
                reason="next step",
                evidence_note=None,
                actor="postgres",
            )
        self.assertEqual(
            store.sources[CANONICAL_POLICY_SOURCE].permission_status,
            "approved_noncommercial",
        )
        self.assertEqual(len(store.permission_events), 1)

        store._fail_permission_event = False
        with self.assertRaises(ValueError):
            store.set_source_permission(
                CANONICAL_POLICY_SOURCE,
                "approved_commercial",
                reason="skip",
                evidence_note=None,
                actor="postgres",
            )
        self.assertEqual(
            store.sources[CANONICAL_POLICY_SOURCE].permission_status,
            "approved_noncommercial",
        )
        self.assertEqual(
            store.sources[CANONICAL_CONTENT_SOURCE].permission_status,
            "testing_only",
        )


class PublicationSnapshotTests(unittest.TestCase):
    def test_republish_upserts_snapshot_and_appends_event(self) -> None:
        store = MemoryIngestStore()
        store.sources[CANONICAL_POLICY_SOURCE].permission_status = (
            "approved_noncommercial"
        )
        first = store.publish_candidate(
            candidate_source="youthcenter",
            external_key="p1",
            revision_hash="a" * 64,
            candidate_id="cand-1",
            slug="policy-p1",
        )
        second = store.publish_candidate(
            candidate_source="youthcenter",
            external_key="p1",
            revision_hash="b" * 64,
            candidate_id="cand-2",
            slug="policy-p1-v2",
        )
        self.assertEqual(len(store.publications), 1)
        self.assertEqual(len(store.publication_events), 2)
        snap = store.publications[0]
        self.assertEqual(snap.source_id, CANONICAL_POLICY_SOURCE)
        self.assertEqual(snap.revision_hash, "b" * 64)
        self.assertEqual(snap.public_curation_id, second)
        self.assertNotEqual(first, second)

        store.publish_candidate(
            candidate_source="youthcenter",
            external_key="p2",
            revision_hash="c" * 64,
            candidate_id="cand-3",
            slug="policy-p2",
        )
        self.assertEqual(len(store.publications), 2)

    def test_deleting_candidate_or_curation_keeps_snapshot(self) -> None:
        store = MemoryIngestStore()
        store.sources[CANONICAL_POLICY_SOURCE].permission_status = (
            "approved_noncommercial"
        )
        curation_id = store.publish_candidate(
            candidate_source="youthcenter",
            external_key="p1",
            revision_hash="a" * 64,
            candidate_id="cand-1",
            slug="policy-p1",
        )
        store.delete_candidate("cand-1")
        store.delete_public_curation(curation_id)
        self.assertEqual(len(store.publications), 1)
        self.assertIsNone(store.publications[0].candidate_id)
        self.assertIsNone(store.publications[0].public_curation_id)
        self.assertEqual(len(store.publication_events), 1)


class DefaultConnectorSleeperTests(unittest.TestCase):
    def test_default_connectors_hold_production_sleeper(self) -> None:
        policy, content = build_youthcenter_connectors(
            policy_api_key_provider=lambda: "x",
            content_api_key_provider=lambda: "y",
        )
        self.assertIs(policy.http.sleep, PRODUCTION_SLEEP)
        self.assertIs(content.http.sleep, PRODUCTION_SLEEP)


class ClaimCountingStore(MemoryIngestStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.claim_calls = 0
        self.finish_calls = 0

    def claim_processing_jobs(self, *args: Any, **kwargs: Any) -> Any:
        self.claim_calls += 1
        return super().claim_processing_jobs(*args, **kwargs)

    def finish_ingest_run(self, *args: Any, **kwargs: Any) -> FinishRunResult:
        self.finish_calls += 1
        return super().finish_ingest_run(*args, **kwargs)


def _complete_connector() -> FakeConnector:
    return FakeConnector(
        batches=[BatchResult(items=(), next_checkpoint=None, natural_end=True)]
    )


def _incomplete_connector() -> FakeConnector:
    item = policy_item("p1", zip_cd="11680", oper_cd="11680")
    return FakeConnector(
        batches=[
            BatchResult(
                items=(item,),
                next_checkpoint=Checkpoint.for_rest_page(2),
                natural_end=False,
            )
        ],
        max_pages=1,
        bootstrap_max_pages=1,
    )


class MemoryFinishContractTests(unittest.TestCase):
    def test_missing_run_is_not_success(self) -> None:
        store = MemoryIngestStore()
        with self.assertRaises(ValueError) as caught:
            store.finish_ingest_run(
                "missing",
                status="complete",
                stop_reason="empty_batch",
                http_request_count=0,
            )
        self.assertIn("run not found", str(caught.exception))

    def test_lease_lost_returns_actual_status(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        first = store.start_ingest_run(CANONICAL_POLICY_SOURCE, lease_seconds=60)
        clock.advance(120)
        second = store.start_ingest_run(CANONICAL_POLICY_SOURCE, lease_seconds=60)
        self.assertFalse(second.skipped)
        result = store.finish_ingest_run(
            first.run_id,
            status="complete",
            stop_reason="streak_complete",
            http_request_count=1,
            bootstrap_complete=True,
        )
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.stop_reason, "lease_lost")
        self.assertEqual(store.sync[CANONICAL_POLICY_SOURCE].lease_owner, second.run_id)


class OrchestratorFinishTests(unittest.TestCase):
    def test_finish_status_is_authority(self) -> None:
        class ForcedFinish(MemoryIngestStore):
            def finish_ingest_run(self, *args: Any, **kwargs: Any) -> FinishRunResult:
                super().finish_ingest_run(*args, **kwargs)
                return FinishRunResult(status="incomplete", stop_reason="lease_lost")

        store = ForcedFinish()
        result = run_connector(_complete_connector(), store, sleep=NO_SLEEP)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.stop_reason, "lease_lost")
        self.assertFalse(result.bootstrap_complete)

    def test_finish_raise_is_finish_failed_once(self) -> None:
        class BoomFinish(ClaimCountingStore):
            def finish_ingest_run(self, *args: Any, **kwargs: Any) -> FinishRunResult:
                self.finish_calls += 1
                raise RpcAmbiguous()

        store = BoomFinish()
        store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete = True
        result = run_connector(_incomplete_connector(), store, sleep=NO_SLEEP)
        self.assertEqual(result.stop_reason, "finish_failed")
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(store.finish_calls, 1)
        self.assertFalse(result.bootstrap_complete)
        self.assertIsNotNone(store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint)

        failed_store = BoomFinish()
        failed = run_connector(
            FakeConnector(fetch_error=HttpStatusError(403), error_on=1),
            failed_store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.stop_reason, "finish_failed")
        self.assertEqual(failed_store.finish_calls, 1)

    def test_run_ingest_does_not_run_ai(self) -> None:
        store = ClaimCountingStore()
        _seed_ai_jobs(store, 2)
        run_ingest([_complete_connector()], store, sleep=NO_SLEEP)
        self.assertEqual(store.claim_calls, 0)
        self.assertEqual(store.ai_job_counts()["queued"], 2)


class SourceCompleteAiGateTests(unittest.TestCase):
    def test_complete_source_may_claim(self) -> None:
        store = ClaimCountingStore()
        result = run_ingest_architecture(
            store=store,
            connectors=[_complete_connector()],
            sleep=NO_SLEEP,
            run_ai=True,
            **_ai_deps(),
        )
        self.assertEqual(result.source_results[0].status, "complete")
        self.assertEqual(result.ai.status, "processed")
        self.assertEqual(store.claim_calls, 1)

    def test_non_complete_sources_do_not_claim(self) -> None:
        cases = []
        incomplete = ClaimCountingStore()
        incomplete.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete = True
        cases.append((incomplete, _incomplete_connector(), "incomplete"))

        failed = ClaimCountingStore()
        cases.append(
            (
                failed,
                FakeConnector(fetch_error=HttpStatusError(403), error_on=1),
                "failed",
            )
        )

        held = ClaimCountingStore()
        held.start_ingest_run(CANONICAL_POLICY_SOURCE)
        cases.append((held, _complete_connector(), "lease_held"))

        disabled = ClaimCountingStore()
        disabled.sources[CANONICAL_POLICY_SOURCE].enabled = False
        cases.append((disabled, _complete_connector(), "source_disabled"))

        for store, connector, reason in cases:
            result = run_ingest_architecture(
                store=store,
                connectors=[connector],
                sleep=NO_SLEEP,
                run_ai=True,
                **_ai_deps(),
            )
            self.assertEqual(result.ai.status, AI_SKIPPED_SOURCE_INCOMPLETE, reason)
            self.assertEqual(store.claim_calls, 0, reason)

        class LostFinish(ClaimCountingStore):
            def finish_ingest_run(self, *args: Any, **kwargs: Any) -> FinishRunResult:
                self.finish_calls += 1
                return FinishRunResult(status="incomplete", stop_reason="lease_lost")

        lost_store = LostFinish()
        lost_result = run_ingest_architecture(
            store=lost_store,
            connectors=[_complete_connector()],
            sleep=NO_SLEEP,
            run_ai=True,
            **_ai_deps(),
        )
        self.assertEqual(lost_result.ai.status, AI_SKIPPED_SOURCE_INCOMPLETE)
        self.assertEqual(lost_store.claim_calls, 0)

        class Boom(ClaimCountingStore):
            def finish_ingest_run(self, *args: Any, **kwargs: Any) -> FinishRunResult:
                self.finish_calls += 1
                raise RpcTimeout()

        boom_store = Boom()
        boom_result = run_ingest_architecture(
            store=boom_store,
            connectors=[_complete_connector()],
            sleep=NO_SLEEP,
            run_ai=True,
            **_ai_deps(),
        )
        self.assertEqual(boom_result.source_results[0].stop_reason, "finish_failed")
        self.assertEqual(boom_result.ai.status, AI_SKIPPED_SOURCE_INCOMPLETE)
        self.assertEqual(boom_store.claim_calls, 0)

    def test_complete_empty_queue_is_processed_claimed_zero(self) -> None:
        store = ClaimCountingStore()
        result = run_ingest_architecture(
            store=store,
            connectors=[_complete_connector()],
            sleep=NO_SLEEP,
            run_ai=True,
            **_ai_deps(),
        )
        self.assertEqual(result.ai.status, "processed")
        self.assertEqual(result.ai.claimed, 0)
        self.assertEqual(store.claim_calls, 1)

    def test_source_incomplete_is_not_empty_queue_success(self) -> None:
        store = ClaimCountingStore()
        store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete = True
        result = run_ingest_architecture(
            store=store,
            connectors=[_incomplete_connector()],
            sleep=NO_SLEEP,
            run_ai=True,
            **_ai_deps(),
        )
        self.assertEqual(result.ai.status, AI_SKIPPED_SOURCE_INCOMPLETE)
        self.assertEqual(result.ai.claimed, 0)
        self.assertEqual(store.claim_calls, 0)


class OrderingCapabilityDeclarationTests(unittest.TestCase):
    def test_policy_is_untrusted(self) -> None:
        self.assertEqual(
            YouthcenterPolicyConnector.ordering_capability, "untrusted"
        )
        connector = YouthcenterPolicyConnector(api_key_provider=lambda: "unused")
        self.assertEqual(connector.ordering_capability, "untrusted")

    def test_content_is_untrusted(self) -> None:
        self.assertEqual(
            YouthcenterContentConnector.ordering_capability, "untrusted"
        )
        connector = YouthcenterContentConnector(api_key_provider=lambda: "unused")
        self.assertEqual(connector.ordering_capability, "untrusted")

    def test_fake_connector_is_explicit_require_descending(self) -> None:
        self.assertEqual(FakeConnector.ordering_capability, "require_descending")
        self.assertEqual(FakeConnector().ordering_capability, "require_descending")

    def test_configured_range_complete_is_not_bootstrap_reason(self) -> None:
        self.assertNotIn("configured_range_complete", BOOTSTRAP_COMPLETE_REASONS)


class InvalidOrderingCapabilityTests(unittest.TestCase):
    def test_missing_capability_fails_before_store_or_fetch(self) -> None:
        store = _SpyStore()
        inner = FakeConnector(
            batches=_page_batches([_descending_target("cap-miss-01", 0)])
        )
        connector = _hide_ordering_capability(inner)
        with self.assertRaises(InvalidOrderingCapability) as caught:
            run_connector(connector, store, sleep=NO_SLEEP)
        self.assertEqual(str(caught.exception), "invalid_ordering_capability")
        self.assertEqual(store.get_source_calls, 0)
        self.assertEqual(store.start_calls, 0)
        self.assertEqual(store.upsert_calls, 0)
        self.assertEqual(inner.calls, 0)
        self.assertEqual(store.items, {})
        self.assertEqual(store.jobs, {})

    def test_invalid_capability_fails_before_store_or_fetch(self) -> None:
        store = _SpyStore()
        connector = FakeConnector(
            batches=_page_batches([_descending_target("cap-bad-01", 0)]),
            ordering_capability="guaranteed_descending",
        )
        with self.assertRaises(InvalidOrderingCapability):
            run_connector(connector, store, sleep=NO_SLEEP)
        self.assertEqual(store.get_source_calls, 0)
        self.assertEqual(store.start_calls, 0)
        self.assertEqual(store.upsert_calls, 0)
        self.assertEqual(connector.calls, 0)

    def test_none_and_empty_capability_are_not_coerced(self) -> None:
        for value in (None, ""):
            store = _SpyStore()
            connector = FakeConnector(
                batches=_page_batches([_descending_target("cap-empty-01", 0)]),
                ordering_capability=value,  # type: ignore[arg-type]
            )
            with self.assertRaises(InvalidOrderingCapability):
                run_connector(connector, store, sleep=NO_SLEEP)
            self.assertEqual(store.get_source_calls, 0)
            self.assertEqual(store.start_calls, 0)
            self.assertEqual(connector.calls, 0)

    def test_run_ingest_does_not_isolate_invalid_capability(self) -> None:
        store = _SpyStore()
        connector = FakeConnector(ordering_capability="trusted")
        with self.assertRaises(InvalidOrderingCapability):
            run_ingest([connector], store, sleep=NO_SLEEP)
        self.assertEqual(store.get_source_calls, 0)
        self.assertEqual(store.start_calls, 0)


class OrderingDiagnosticTests(unittest.TestCase):
    def test_cli_token_four_states(self) -> None:
        self.assertEqual(format_ordering_cli_token(frozenset()), "ok")
        self.assertEqual(
            format_ordering_cli_token(frozenset({"missing_stamp"})), "missing_stamp"
        )
        self.assertEqual(
            format_ordering_cli_token(frozenset({"non_monotonic_stamp"})),
            "non_monotonic_stamp",
        )
        self.assertEqual(
            format_ordering_cli_token(
                frozenset({"non_monotonic_stamp", "missing_stamp"})
            ),
            "missing_stamp,non_monotonic_stamp",
        )

    def test_ok_descending_bootstrap(self) -> None:
        items = [_descending_target(f"ok-{i:02d}", i) for i in range(25)]
        store = MemoryIngestStore()
        result = run_connector(
            FakeConnector(batches=_page_batches(items), ordering_capability="untrusted"),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.stop_reason, "bootstrap_range_complete")
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.ordering_cli_token(), "ok")
        self.assertEqual(result.ordering_diagnostics, frozenset())

    def test_missing_stamp_only(self) -> None:
        items = [
            policy_item(
                f"miss-{i:02d}",
                zip_cd="11680",
                oper_cd="11680",
                updated="",
                created="",
                title=f"누락{i:02d}",
            )
            for i in range(5)
        ]
        store = MemoryIngestStore()
        result = run_connector(
            FakeConnector(
                batches=_page_batches(items, page_size=5, natural_end=True),
                ordering_capability="untrusted",
                bootstrap_max_items=5,
                bootstrap_max_pages=1,
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.ordering_cli_token(), "missing_stamp")
        self.assertNotIn("non_monotonic_stamp", result.ordering_diagnostics)

    def test_unparsed_stamp_is_missing_stamp(self) -> None:
        items = [
            policy_item(
                "unparsed-01",
                zip_cd="11680",
                oper_cd="11680",
                updated="not-a-date",
                created="also-bad",
                title="합성언파스드",
            )
        ]
        store = MemoryIngestStore()
        result = run_connector(
            FakeConnector(
                batches=_page_batches(items, page_size=1, natural_end=True),
                ordering_capability="untrusted",
                bootstrap_max_items=1,
                bootstrap_max_pages=1,
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.ordering_cli_token(), "missing_stamp")
        self.assertIn((CANONICAL_POLICY_SOURCE, "unparsed-01"), store.items)

    def test_non_monotonic_stamp_only(self) -> None:
        items = [_descending_target(f"mono-{i:02d}", i) for i in range(10)]
        items[5] = _descending_target(
            "mono-05", 5, updated="2026-09-15 12:00:00"
        )
        store = MemoryIngestStore()
        result = run_connector(
            FakeConnector(
                batches=_page_batches(items),
                ordering_capability="untrusted",
                bootstrap_max_items=10,
                bootstrap_max_pages=2,
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.ordering_cli_token(), "non_monotonic_stamp")

    def test_compound_missing_and_non_monotonic(self) -> None:
        items = [
            _descending_target("both-00", 0),
            policy_item(
                "both-01",
                zip_cd="11680",
                oper_cd="11680",
                updated="",
                created="",
                title="합성누락",
            ),
            _descending_target("both-02", 2, updated="2026-09-20 12:00:00"),
        ]
        store = MemoryIngestStore()
        result = run_connector(
            FakeConnector(
                batches=_page_batches(items, page_size=3, natural_end=True),
                ordering_capability="untrusted",
                bootstrap_max_items=3,
                bootstrap_max_pages=1,
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(
            result.ordering_cli_token(), "missing_stamp,non_monotonic_stamp"
        )
        self.assertEqual(result.status, "complete")
        blob = result.ordering_cli_token()
        self.assertNotIn("https://", blob)
        self.assertNotIn("합성누락", blob)
        self.assertNotIn("both-01", blob)


class RequireDescendingBehaviorTests(unittest.TestCase):
    def test_strict_descending_bootstrap_completes(self) -> None:
        items = [_descending_target(f"strict-ok-{i:02d}", i) for i in range(25)]
        store = MemoryIngestStore()
        result = run_connector(
            FakeConnector(batches=_page_batches(items)),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "bootstrap_range_complete")
        self.assertTrue(result.bootstrap_complete)
        self.assertTrue(store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete)
        self.assertEqual(result.ordering_cli_token(), "ok")

    def test_strict_non_monotonic_bootstrap_is_incomplete(self) -> None:
        items = [_descending_target(f"strict-bad-{i:02d}", i) for i in range(25)]
        items[10] = _descending_target(
            "strict-bad-10", 10, updated="2026-09-15 12:00:00"
        )
        store = MemoryIngestStore()
        result = run_connector(
            FakeConnector(batches=_page_batches(items)),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.stop_reason, "ordering_anomaly")
        self.assertFalse(result.bootstrap_complete)
        self.assertFalse(store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete)
        self.assertEqual(result.ordering_cli_token(), "non_monotonic_stamp")
        self.assertEqual(len(store.items), 25)

    def test_content_source_keeps_fail_closed_overlay(self) -> None:
        items = [_descending_target(f"content-bad-{i:02d}", i) for i in range(10)]
        items[5] = _descending_target(
            "content-bad-05", 5, updated="2026-09-15 12:00:00"
        )
        store = MemoryIngestStore()
        result = run_connector(
            FakeConnector(
                batches=_page_batches(items, page_size=2),
                source_id=CANONICAL_CONTENT_SOURCE,
                ordering_capability="require_descending",
                bootstrap_max_pages=5,
                bootstrap_max_items=10,
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.stop_reason, "ordering_anomaly")
        self.assertFalse(result.bootstrap_complete)
        self.assertFalse(store.sync[CANONICAL_CONTENT_SOURCE].bootstrap_complete)


class UntrustedRangeTests(unittest.TestCase):
    def test_untrusted_non_monotonic_bootstrap_completes(self) -> None:
        items = [_descending_target(f"u-boot-{i:02d}", i) for i in range(25)]
        items[10] = _descending_target(
            "u-boot-10", 10, updated="2026-09-15 12:00:00"
        )
        store = MemoryIngestStore()
        result = run_connector(
            FakeConnector(
                batches=_page_batches(items), ordering_capability="untrusted"
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "bootstrap_range_complete")
        self.assertTrue(result.bootstrap_complete)
        self.assertTrue(store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete)
        self.assertEqual(result.ordering_cli_token(), "non_monotonic_stamp")
        self.assertEqual(len(store.items), 25)
        self.assertIsNotNone(store.sync[CANONICAL_POLICY_SOURCE].last_success_at)

    def test_untrusted_missing_stamp_bootstrap_completes(self) -> None:
        items = [
            policy_item(
                f"u-miss-{i:02d}",
                zip_cd="11680",
                oper_cd="11680",
                updated="",
                created="",
                title=f"미싱{i:02d}",
            )
            for i in range(25)
        ]
        store = MemoryIngestStore()
        result = run_connector(
            FakeConnector(
                batches=_page_batches(items), ordering_capability="untrusted"
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "bootstrap_range_complete")
        self.assertTrue(result.bootstrap_complete)
        self.assertEqual(result.ordering_cli_token(), "missing_stamp")

    def test_untrusted_general_does_not_use_streak(self) -> None:
        store = MemoryIngestStore()
        store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete = True
        item = _descending_target("u-streak-01", 0)
        batches = [
            BatchResult(
                items=(item,),
                next_checkpoint=Checkpoint.for_rest_page(page + 1),
                natural_end=False,
            )
            for page in range(1, 11)
        ]
        result = run_connector(
            FakeConnector(
                batches=batches, max_pages=10, ordering_capability="untrusted"
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertNotEqual(result.stop_reason, "streak_complete")
        self.assertEqual(result.stop_reason, "configured_range_complete")
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.batches_ok, 10)
        self.assertTrue(store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete)

    def test_untrusted_empty_and_short_natural_end(self) -> None:
        empty_store = MemoryIngestStore()
        empty = run_connector(
            FakeConnector(
                batches=[BatchResult(items=(), next_checkpoint=None, natural_end=True)],
                ordering_capability="untrusted",
            ),
            empty_store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(empty.status, "complete")
        self.assertEqual(empty.stop_reason, "empty_batch")
        self.assertTrue(empty.bootstrap_complete)
        self.assertEqual(empty.ordering_cli_token(), "ok")

        short_store = MemoryIngestStore()
        short_item = _descending_target("u-short-01", 0)
        short = run_connector(
            FakeConnector(
                batches=[
                    BatchResult(
                        items=(short_item,),
                        next_checkpoint=None,
                        natural_end=True,
                    )
                ],
                ordering_capability="untrusted",
            ),
            short_store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(short.status, "complete")
        self.assertEqual(short.stop_reason, "short_batch")
        self.assertTrue(short.bootstrap_complete)

    def test_untrusted_http_failure_keeps_existing_contract(self) -> None:
        store = MemoryIngestStore()
        item = _descending_target("u-http-01", 0)
        connector = FakeConnector(
            batches=[
                BatchResult(
                    items=(item,),
                    next_checkpoint=Checkpoint.for_rest_page(2),
                    natural_end=False,
                )
            ],
            fetch_error=HttpStatusError(500),
            error_on=2,
            ordering_capability="untrusted",
        )
        result = run_connector(connector, store, sleep=NO_SLEEP)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.stop_reason, "http_500")
        self.assertFalse(result.bootstrap_complete)
        self.assertIn((CANONICAL_POLICY_SOURCE, "u-http-01"), store.items)


def _content_untrusted_fake(**kwargs: Any) -> FakeConnector:
    kwargs.setdefault("source_id", CANONICAL_CONTENT_SOURCE)
    kwargs.setdefault("ordering_capability", "untrusted")
    kwargs.setdefault("bootstrap_max_pages", 5)
    kwargs.setdefault("bootstrap_max_items", 10)
    return FakeConnector(**kwargs)


class ContentUntrustedBootstrapTests(unittest.TestCase):
    def test_class_and_instance_are_untrusted(self) -> None:
        self.assertEqual(
            YouthcenterContentConnector.ordering_capability, "untrusted"
        )
        self.assertEqual(
            YouthcenterContentConnector(api_key_provider=lambda: "unused").ordering_capability,
            "untrusted",
        )
        self.assertEqual(
            YouthcenterPolicyConnector.ordering_capability, "untrusted"
        )

    def test_non_monotonic_bootstrap_completes(self) -> None:
        items = [_descending_target(f"c-u-{i:02d}", i) for i in range(10)]
        items[5] = _descending_target(
            "c-u-05", 5, updated="2026-09-15 12:00:00"
        )
        store = MemoryIngestStore()
        result = run_connector(
            _content_untrusted_fake(batches=_page_batches(items, page_size=2)),
            store,
            sleep=NO_SLEEP,
        )
        sync = store.sync[CANONICAL_CONTENT_SOURCE]
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "bootstrap_range_complete")
        self.assertTrue(result.bootstrap_complete)
        self.assertTrue(sync.bootstrap_complete)
        self.assertEqual(result.ordering_cli_token(), "non_monotonic_stamp")
        self.assertIsNotNone(sync.committed_checkpoint)
        self.assertIsNone(sync.lease_owner)
        self.assertIsNone(sync.lease_expires_at)
        self.assertIsNone(sync.active_run_id)
        self.assertEqual(len(store.items), 10)

    def test_missing_stamp_does_not_block_range_complete(self) -> None:
        items = [
            policy_item(
                f"c-miss-{i:02d}",
                zip_cd="11680",
                oper_cd="11680",
                updated="",
                created="",
                title=f"콘텐츠누락{i:02d}",
            )
            for i in range(10)
        ]
        store = MemoryIngestStore()
        result = run_connector(
            _content_untrusted_fake(batches=_page_batches(items, page_size=2)),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "bootstrap_range_complete")
        self.assertTrue(result.bootstrap_complete)
        self.assertEqual(result.ordering_cli_token(), "missing_stamp")
        self.assertNotIn("non_monotonic_stamp", result.ordering_diagnostics)

    def test_compound_diagnostics_keep_range_complete(self) -> None:
        items = [
            _descending_target("c-both-00", 0),
            policy_item(
                "c-both-01",
                zip_cd="11680",
                oper_cd="11680",
                updated="",
                created="",
                title="콘텐츠복합누락",
            ),
            _descending_target("c-both-02", 2, updated="2026-09-20 12:00:00"),
        ]
        store = MemoryIngestStore()
        result = run_connector(
            _content_untrusted_fake(
                batches=_page_batches(items, page_size=2),
                bootstrap_max_items=3,
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "bootstrap_range_complete")
        self.assertTrue(result.bootstrap_complete)
        self.assertEqual(
            result.ordering_cli_token(), "missing_stamp,non_monotonic_stamp"
        )
        blob = result.ordering_cli_token()
        self.assertNotIn("https://", blob)
        self.assertNotIn("콘텐츠복합누락", blob)
        self.assertNotIn("c-both-01", blob)

    def test_non_bootstrap_does_not_use_streak(self) -> None:
        store = MemoryIngestStore()
        store.sync[CANONICAL_CONTENT_SOURCE].bootstrap_complete = True
        item = _descending_target("c-streak-01", 0)
        batches = [
            BatchResult(
                items=(item,),
                next_checkpoint=Checkpoint.for_rest_page(page + 1),
                natural_end=False,
            )
            for page in range(1, 6)
        ]
        result = run_connector(
            _content_untrusted_fake(batches=batches, max_pages=5),
            store,
            sleep=NO_SLEEP,
        )
        self.assertNotEqual(result.stop_reason, "streak_complete")
        self.assertEqual(result.stop_reason, "configured_range_complete")
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.batches_ok, 5)
        self.assertTrue(store.sync[CANONICAL_CONTENT_SOURCE].bootstrap_complete)

    def test_http_oversized_and_parse_still_fail(self) -> None:
        http_store = MemoryIngestStore()
        first = _descending_target("c-http-01", 0)
        http_result = run_connector(
            _content_untrusted_fake(
                batches=[
                    BatchResult(
                        items=(first,),
                        next_checkpoint=Checkpoint.for_rest_page(2),
                        natural_end=False,
                    )
                ],
                fetch_error=HttpStatusError(500),
                error_on=2,
            ),
            http_store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(http_result.status, "incomplete")
        self.assertEqual(http_result.stop_reason, "http_500")
        self.assertFalse(http_result.bootstrap_complete)

        oversized_store = MemoryIngestStore()
        oversized = run_connector(
            _content_untrusted_fake(
                batches=[],
                fetch_error=ResponseTooLarge(),
                error_on=1,
            ),
            oversized_store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(oversized.status, "failed")
        self.assertEqual(oversized.stop_reason, "response_too_large")
        self.assertFalse(oversized.bootstrap_complete)

        parse_store = MemoryIngestStore()
        parsed = run_connector(
            _content_untrusted_fake(
                batches=[],
                fetch_error=RuntimeError("youth_content_list_invalid"),
                error_on=1,
            ),
            parse_store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(parsed.status, "failed")
        self.assertEqual(parsed.stop_reason, "rpc_error")
        self.assertFalse(parsed.bootstrap_complete)


def _review_seed_item(key: str, title: str) -> dict[str, Any]:
    return policy_item(key, zip_cd="", oper_cd="", title=title)


def _seed_synthetic_lineage(store: MemoryIngestStore) -> dict[str, str]:
    items: list[dict[str, Any]] = []
    for i in range(3):
        items.append(
            policy_item(
                f"seed-target-{i:02d}",
                zip_cd="11680",
                oper_cd="11680",
                title=f"시드타겟{i:02d}",
            )
        )
    for i in range(9):
        items.append(_review_seed_item(f"seed-review-{i:02d}", f"시드리뷰{i:02d}"))
    for i in range(13):
        items.append(
            policy_item(
                f"seed-nontarget-{i:02d}",
                zip_cd="50110",
                oper_cd="50110",
                title=f"시드비대상{i:02d}",
            )
        )
    started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
    store.upsert_source_observations(
        CANONICAL_POLICY_SOURCE,
        started.run_id,
        [observation_for(item) for item in items],
        Checkpoint.for_rest_page(6),
    )
    store.finish_ingest_run(
        started.run_id,
        status="incomplete",
        stop_reason="ordering_anomaly",
        http_request_count=5,
        bootstrap_complete=False,
    )
    self_jobs = {job_id: job.status for job_id, job in store.jobs.items()}
    return self_jobs


class RecanaryLineageTests(unittest.TestCase):
    def test_all_unchanged_keeps_items_and_queued_jobs(self) -> None:
        store = ClaimCountingStore()
        job_snapshot = _seed_synthetic_lineage(store)
        self.assertEqual(len(store.items), 25)
        self.assertEqual(len(store.jobs), 12)
        self.assertFalse(store.sync[CANONICAL_POLICY_SOURCE].bootstrap_complete)
        items = []
        for i in range(3):
            items.append(
                policy_item(
                    f"seed-target-{i:02d}",
                    zip_cd="11680",
                    oper_cd="11680",
                    title=f"시드타겟{i:02d}",
                )
            )
        for i in range(9):
            items.append(
                policy_item(
                    f"seed-review-{i:02d}",
                    zip_cd="",
                    oper_cd="",
                    title=f"시드리뷰{i:02d}",
                )
            )
        for i in range(13):
            items.append(
                policy_item(
                    f"seed-nontarget-{i:02d}",
                    zip_cd="50110",
                    oper_cd="50110",
                    title=f"시드비대상{i:02d}",
                )
            )
        result = run_connector(
            FakeConnector(
                batches=_page_batches(items), ordering_capability="untrusted"
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "bootstrap_range_complete")
        self.assertEqual(len(store.items), 25)
        self.assertEqual(len(store.jobs), 12)
        self.assertEqual(
            {job_id: job.status for job_id, job in store.jobs.items()},
            job_snapshot,
        )
        self.assertTrue(all(status == "queued" for status in job_snapshot.values()))
        self.assertEqual(store.claim_calls, 0)

    def test_some_changed_adds_revision_jobs_only(self) -> None:
        store = ClaimCountingStore()
        job_snapshot = _seed_synthetic_lineage(store)
        items = []
        for i in range(3):
            title = f"시드타겟{i:02d}-변경" if i == 0 else f"시드타겟{i:02d}"
            items.append(
                policy_item(
                    f"seed-target-{i:02d}",
                    zip_cd="11680",
                    oper_cd="11680",
                    title=title,
                )
            )
        for i in range(9):
            items.append(
                policy_item(
                    f"seed-review-{i:02d}",
                    zip_cd="",
                    oper_cd="",
                    title=f"시드리뷰{i:02d}",
                )
            )
        for i in range(13):
            items.append(
                policy_item(
                    f"seed-nontarget-{i:02d}",
                    zip_cd="50110",
                    oper_cd="50110",
                    title=f"시드비대상{i:02d}",
                )
            )
        result = run_connector(
            FakeConnector(
                batches=_page_batches(items), ordering_capability="untrusted"
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(store.items), 25)
        self.assertEqual(len(store.jobs), 13)
        for job_id, status in job_snapshot.items():
            self.assertEqual(store.jobs[job_id].status, status)
            self.assertEqual(store.jobs[job_id].status, "queued")
        self.assertEqual(store.claim_calls, 0)

    def test_all_new_and_plus_25_bounds(self) -> None:
        store = ClaimCountingStore()
        job_snapshot = _seed_synthetic_lineage(store)
        new_items = [_descending_target(f"recanary-new-{i:02d}", i) for i in range(25)]
        result = run_connector(
            FakeConnector(
                batches=_page_batches(new_items), ordering_capability="untrusted"
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "bootstrap_range_complete")
        self.assertEqual(len(store.items), 50)
        self.assertEqual(len(store.jobs), 37)
        for job_id, status in job_snapshot.items():
            self.assertEqual(store.jobs[job_id].status, status)
        unique_keys = {
            (job.source_item_id, job.revision_hash, job.processing_stage)
            for job in store.jobs.values()
        }
        self.assertEqual(len(unique_keys), len(store.jobs))
        self.assertEqual(store.claim_calls, 0)
        claimed = [
            job for job in store.jobs.values() if job.status in {"claimed", "completed", "failed"}
        ]
        self.assertEqual(claimed, [])

    def test_duplicate_stage_hash_does_not_add_job(self) -> None:
        store = MemoryIngestStore()
        job_snapshot = _seed_synthetic_lineage(store)
        items = []
        for i in range(3):
            items.append(
                policy_item(
                    f"seed-target-{i:02d}",
                    zip_cd="11680",
                    oper_cd="11680",
                    title=f"시드타겟{i:02d}",
                )
            )
        for i in range(9):
            items.append(
                policy_item(
                    f"seed-review-{i:02d}",
                    zip_cd="",
                    oper_cd="",
                    title=f"시드리뷰{i:02d}",
                )
            )
        for i in range(13):
            items.append(
                policy_item(
                    f"seed-nontarget-{i:02d}",
                    zip_cd="50110",
                    oper_cd="50110",
                    title=f"시드비대상{i:02d}",
                )
            )
        run_connector(
            FakeConnector(
                batches=_page_batches(items), ordering_capability="untrusted"
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertEqual(len(store.jobs), len(job_snapshot))


if __name__ == "__main__":
    unittest.main()
