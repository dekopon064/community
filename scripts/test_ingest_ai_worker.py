"""AI worker Class A/B tests. 실제 Gemini·Supabase를 쓰지 않는다."""

from __future__ import annotations

import unittest
from typing import Any

from ingest.ai_errors import AiJobError
from ingest.ai_worker import (
    AI_NO_JOBS,
    AI_PROCESSED,
    AI_STATE_UNKNOWN,
    WORKER_ID,
    process_ai_jobs,
)
from ingest.constants import DEFAULT_JOB_LEASE_SECONDS
from ingest.connectors.youthcenter_policy import YouthcenterPolicyConnector
from ingest.models import Checkpoint, ObservationRecord, AI_STAGE
from ingest.relevance import AXIS_JP_RESIDENTS_IN_KR, RULE_VERSION
from ingest.rpc_errors import RpcAmbiguous, RpcTimeout
from ingest.source_identity import CANONICAL_POLICY_SOURCE
from ingest.store import AI_CLAIM_LIMIT, MemoryIngestStore

SECRET_MARKER = "svc-secret-marker-DoNotLog"
URL_QUERY_MARKER = "apiKeyNm=secret-query-marker"
RPC_PAYLOAD_MARKER = "rpc-payload-marker-XYZ"
RESPONSE_BODY_MARKER = "response-body-marker-ABC"
CONTENT_BODY_MARKER = "content-body-plain-text-MARKER"


def _policy_item(plcy_no: str) -> dict[str, Any]:
    return {
        "plcyNo": plcy_no,
        "plcyNm": "테스트 정책",
        "plcyExplnCn": "재한 일본인은 신청 가능합니다. 서울 거주자를 대상으로 합니다.",
        "plcySprtCn": "재한 일본인은 신청 가능합니다. 서울 거주자를 대상으로 합니다.",
        "aplyUrlAddr": "https://example.go.kr/apply",
        "zipCd": "11680",
        "operInstCd": "11680",
        "operInstNm": "",
        "pvsnInstGroupCd": "0054002",
        "frstRegDt": "2026-09-01 12:00:00",
        "lastMdfcnDt": "2026-09-13 12:00:00",
        "inqCnt": "999",
    }


def _observation(plcy_no: str) -> ObservationRecord:
    return YouthcenterPolicyConnector(api_key_provider=lambda: "unused").to_observation(
        _policy_item(plcy_no), permission_status="testing_only", enabled=True
    )


def _human_review_observation(plcy_no: str) -> ObservationRecord:
    item = _policy_item(plcy_no)
    item["plcyExplnCn"] = "서울 거주 청년을 대상으로 합니다."
    item["plcySprtCn"] = "서울 거주 청년을 대상으로 합니다."
    return YouthcenterPolicyConnector(api_key_provider=lambda: "unused").to_observation(
        item, permission_status="testing_only", enabled=True
    )


def _assert_v2_created_clear_target_ai(store: MemoryIngestStore, count: int) -> None:
    items = list(store.items.values())
    if len(items) != count:
        raise AssertionError("v2_clear_target_item_count")
    if len(store.decisions) != count:
        raise AssertionError("v2_clear_target_decision_count")
    for item in items:
        decisions = [
            row
            for row in store.decisions.values()
            if row.source_item_id == item.id and row.revision_hash == item.revision_hash
        ]
        if len(decisions) != 1:
            raise AssertionError("v2_clear_target_decision_missing")
        decision = decisions[0]
        if decision.decision != "approve_ai":
            raise AssertionError("v2_clear_target_decision_not_approve")
        if decision.reviewer != f"classifier:{RULE_VERSION}":
            raise AssertionError("v2_clear_target_reviewer")
        ais = [
            job
            for job in store.jobs.values()
            if job.source_item_id == item.id
            and job.revision_hash == item.revision_hash
            and job.processing_stage == AI_STAGE
        ]
        if len(ais) != 1 or ais[0].status != "queued":
            raise AssertionError("v2_clear_target_ai_missing")


def _seed(store: MemoryIngestStore, count: int) -> None:
    started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
    records = [_observation(f"p{i}") for i in range(count)]
    store.upsert_source_observations(
        CANONICAL_POLICY_SOURCE,
        started.run_id,
        records,
        Checkpoint.for_rest_page(2),
    )
    _assert_v2_created_clear_target_ai(store, count)


def _ai_deps(**overrides: Any) -> dict[str, Any]:
    deps: dict[str, Any] = {
        "supabase": object(),
        "summarize_ko": lambda text, url, title=None: (text, "success", "model"),
        "translate_ja": lambda title, body: ("t", "b", "success", "model"),
        "enqueue": lambda *_a, **_k: {"outcome": "inserted", "candidate_id": "x"},
        "revision_precheck": lambda *_a, **_k: False,
    }
    deps.update(overrides)
    return deps


class SpyStore(MemoryIngestStore):
    def __init__(self) -> None:
        super().__init__()
        self.complete_calls: list[str] = []
        self.fail_calls: list[str] = []
        self.claim_calls = 0
        self.claim_kwargs: list[dict[str, Any]] = []
        self.complete_error: Exception | None = None
        self.fail_error: Exception | None = None

    def claim_processing_jobs(self, *args: Any, **kwargs: Any) -> Any:
        self.claim_calls += 1
        self.claim_kwargs.append(dict(kwargs))
        return super().claim_processing_jobs(*args, **kwargs)

    def complete_processing_job(self, job_id: str, *, worker_id: str) -> None:
        self.complete_calls.append(job_id)
        if self.complete_error is not None:
            raise self.complete_error
        return super().complete_processing_job(job_id, worker_id=worker_id)

    def fail_processing_job(
        self, job_id: str, *, worker_id: str, error_code: str
    ) -> str:
        self.fail_calls.append(job_id)
        if self.fail_error is not None:
            raise self.fail_error
        return super().fail_processing_job(
            job_id, worker_id=worker_id, error_code=error_code
        )


class AiClassBoundaryTests(unittest.TestCase):
    def test_deterministic_failure_fails_once(self) -> None:
        store = SpyStore()
        _seed(store, 1)

        def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
            raise RuntimeError("enqueue_failed")

        result = process_ai_jobs(store, **_ai_deps(enqueue=boom))
        self.assertEqual(result.status, AI_PROCESSED)
        self.assertEqual(len(store.fail_calls), 1)
        self.assertEqual(len(store.complete_calls), 0)
        self.assertEqual(result.retried, 1)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.state_unknown, 0)

    def test_complete_timeout_does_not_fail(self) -> None:
        store = SpyStore()
        _seed(store, 2)
        store.complete_error = RpcTimeout()
        result = process_ai_jobs(store, **_ai_deps())
        self.assertEqual(result.status, AI_STATE_UNKNOWN)
        self.assertEqual(len(store.complete_calls), 1)
        self.assertEqual(len(store.fail_calls), 0)
        self.assertEqual(result.state_unknown, 1)
        self.assertEqual(result.retried, 0)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.completed, 0)

    def test_complete_rpc_error_does_not_fail(self) -> None:
        store = SpyStore()
        _seed(store, 2)
        store.complete_error = RpcAmbiguous()
        result = process_ai_jobs(store, **_ai_deps())
        self.assertEqual(result.status, AI_STATE_UNKNOWN)
        self.assertEqual(len(store.fail_calls), 0)
        self.assertEqual(result.completed, 0)

    def test_complete_null_like_error_stops_remaining_jobs(self) -> None:
        store = SpyStore()
        _seed(store, 2)
        store.complete_error = RpcAmbiguous()
        result = process_ai_jobs(store, **_ai_deps())
        self.assertEqual(len(store.complete_calls), 1)
        queued = store.ai_job_counts()["queued"] + store.ai_job_counts()["claimed"]
        self.assertGreaterEqual(queued, 1)
        self.assertEqual(result.state_unknown, 1)
        self.assertEqual(result.retried, 0)
        self.assertEqual(result.failed, 0)

    def test_fail_timeout_is_not_retried(self) -> None:
        store = SpyStore()
        _seed(store, 2)
        store.fail_error = RpcTimeout()

        def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
            raise RuntimeError("enqueue_failed")

        result = process_ai_jobs(store, **_ai_deps(enqueue=boom))
        self.assertEqual(result.status, AI_STATE_UNKNOWN)
        self.assertEqual(len(store.fail_calls), 1)
        self.assertEqual(result.state_unknown, 1)
        self.assertEqual(result.retried, 0)
        self.assertEqual(result.failed, 0)

    def test_enqueue_timeout_does_not_complete_or_fail(self) -> None:
        store = SpyStore()
        _seed(store, 2)

        def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
            raise RpcTimeout()

        result = process_ai_jobs(store, **_ai_deps(enqueue=boom))
        self.assertEqual(result.status, AI_STATE_UNKNOWN)
        self.assertEqual(len(store.complete_calls), 0)
        self.assertEqual(len(store.fail_calls), 0)
        self.assertEqual(result.state_unknown, 1)
        self.assertEqual(result.retried, 0)
        self.assertEqual(result.failed, 0)

    def test_claim_malformed_does_not_mutate_jobs(self) -> None:
        class BadClaim(SpyStore):
            def claim_processing_jobs(self, *args: Any, **kwargs: Any) -> Any:
                self.claim_calls += 1
                raise RpcAmbiguous()

        store = BadClaim()
        _seed(store, 2)
        result = process_ai_jobs(store, **_ai_deps())
        self.assertEqual(result.status, AI_STATE_UNKNOWN)
        self.assertEqual(result.claimed, 0)
        self.assertEqual(len(store.complete_calls), 0)
        self.assertEqual(len(store.fail_calls), 0)

    def test_state_unknown_not_double_counted(self) -> None:
        store = SpyStore()
        _seed(store, 1)
        store.complete_error = RpcTimeout()
        result = process_ai_jobs(store, **_ai_deps())
        self.assertEqual(result.state_unknown, 1)
        self.assertEqual(result.retried + result.failed, 0)

    def test_secret_markers_are_scrubbed(self) -> None:
        store = SpyStore()
        _seed(store, 1)
        secret = (
            f"{SECRET_MARKER} {URL_QUERY_MARKER} {RPC_PAYLOAD_MARKER} "
            f"{RESPONSE_BODY_MARKER} {CONTENT_BODY_MARKER}"
        )
        store.complete_error = RpcTimeout()
        store.complete_error.__dict__["raw"] = secret
        result = process_ai_jobs(store, **_ai_deps())
        self.assertEqual(result.status, AI_STATE_UNKNOWN)
        text = repr(result) + str(result)
        for marker in (
            SECRET_MARKER,
            URL_QUERY_MARKER,
            RPC_PAYLOAD_MARKER,
            RESPONSE_BODY_MARKER,
            CONTENT_BODY_MARKER,
        ):
            self.assertNotIn(marker, text)


class AiNoJobsAndPayloadTests(unittest.TestCase):
    def test_require_jobs_empty_claim_is_ai_no_jobs(self) -> None:
        store = SpyStore()
        result = process_ai_jobs(store, require_jobs=True, **_ai_deps())
        self.assertEqual(result.status, AI_NO_JOBS)
        self.assertEqual(result.claimed, 0)
        self.assertEqual(len(store.complete_calls), 0)
        self.assertEqual(len(store.fail_calls), 0)

    def test_empty_claim_without_require_jobs_stays_processed(self) -> None:
        store = SpyStore()
        result = process_ai_jobs(store, **_ai_deps())
        self.assertEqual(result.status, AI_PROCESSED)
        self.assertEqual(result.claimed, 0)

    def test_ai_job_error_uses_secret_safe_code(self) -> None:
        store = SpyStore()
        _seed(store, 1)

        def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
            raise AiJobError("ai_blocked_cost_cap")

        result = process_ai_jobs(store, **_ai_deps(enqueue=boom))
        self.assertEqual(result.status, AI_PROCESSED)
        self.assertEqual(result.retried, 1)
        job = next(
            row for row in store.jobs.values() if row.processing_stage == AI_STAGE
        )
        self.assertEqual(job.error_code, "ai_blocked_cost_cap")

    def test_facts_are_not_enqueued_and_model_is_passed(self) -> None:
        store = SpyStore()
        _seed(store, 1)
        captured: dict[str, Any] = {}

        def enqueue(_supabase: Any, params: dict[str, Any]) -> dict[str, Any]:
            captured.update(params)
            return {"outcome": "inserted", "candidate_id": "x"}

        def summarize(text: str, url: str | None, title: str | None = None) -> tuple[str, str, str]:
            self.assertEqual(title, "테스트 정책")
            return ("요약", "success", "claude-sonnet-5")

        result = process_ai_jobs(
            store,
            **_ai_deps(enqueue=enqueue, summarize_ko=summarize),
        )
        self.assertEqual(result.completed, 1)
        self.assertNotIn("facts", captured)
        self.assertNotIn("p_facts", captured)
        self.assertNotIn("facts", captured.get("p_raw_payload", {}))
        self.assertEqual(captured["p_ai_model"], "claude-sonnet-5")

    def test_enqueue_ambiguous_does_not_complete_or_fail(self) -> None:
        store = SpyStore()
        _seed(store, 1)

        def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
            raise RpcAmbiguous()

        result = process_ai_jobs(store, **_ai_deps(enqueue=boom))
        self.assertEqual(result.status, AI_STATE_UNKNOWN)
        self.assertEqual(len(store.complete_calls), 0)
        self.assertEqual(len(store.fail_calls), 0)

    def test_claim_passes_default_job_lease_600(self) -> None:
        store = SpyStore()
        _seed(store, 1)
        result = process_ai_jobs(store, **_ai_deps())
        self.assertEqual(result.status, AI_PROCESSED)
        self.assertEqual(len(store.claim_kwargs), 1)
        kwargs = store.claim_kwargs[0]
        self.assertEqual(kwargs["lease_seconds"], 600)
        self.assertEqual(kwargs["lease_seconds"], DEFAULT_JOB_LEASE_SECONDS)
        self.assertEqual(kwargs["worker_id"], WORKER_ID)
        self.assertEqual(kwargs["limit"], AI_CLAIM_LIMIT)
        job = next(
            row for row in store.jobs.values() if row.processing_stage == AI_STAGE
        )
        self.assertEqual(job.status, "completed")


class HumanApproveWorkerFixtureTests(unittest.TestCase):
    def test_human_region_only_approve_fixture_is_not_claimed(self) -> None:
        store = SpyStore()
        started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
        record = _human_review_observation("human-1")
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE,
            started.run_id,
            [record],
            None,
        )
        item = next(iter(store.items.values()))
        self.assertEqual(store.decisions, {})
        self.assertEqual(store.jobs_for_stage(AI_STAGE), [])
        self.assertTrue(store.jobs_for_stage("region_review"))
        store.resolve_ingest_review_decision(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            review_type="region",
            decision="approve_ai",
            region_scope="capital",
            audience_relevance=(AXIS_JP_RESIDENTS_IN_KR,),
            rule_version=RULE_VERSION,
            reviewer="human:reviewer",
        )
        self.assertEqual(store.jobs_for_stage(AI_STAGE), [])
        self.assertEqual(item.disposition, "region_review_required")
        result = process_ai_jobs(store, **_ai_deps())
        self.assertEqual(result.status, AI_PROCESSED)
        self.assertEqual(result.claimed, 0)
        self.assertEqual(store.jobs_for_stage("region_review")[0].status, "completed")


if __name__ == "__main__":
    unittest.main()
