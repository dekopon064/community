"""AI worker Class A/B tests. 실제 Gemini·Supabase를 쓰지 않는다."""

from __future__ import annotations

import unittest
from typing import Any

from ingest.ai_errors import AiJobError
from ingest.ai_worker import (
    AI_NO_JOBS,
    AI_PROCESSED,
    AI_STATE_UNKNOWN,
    process_ai_jobs,
)
from ingest.connectors.youthcenter_policy import YouthcenterPolicyConnector
from ingest.models import Checkpoint, ObservationRecord
from ingest.rpc_errors import RpcAmbiguous, RpcTimeout
from ingest.source_identity import CANONICAL_POLICY_SOURCE
from ingest.store import MemoryIngestStore

SECRET_MARKER = "svc-secret-marker-DoNotLog"
URL_QUERY_MARKER = "apiKeyNm=secret-query-marker"
RPC_PAYLOAD_MARKER = "rpc-payload-marker-XYZ"
RESPONSE_BODY_MARKER = "response-body-marker-ABC"
CONTENT_BODY_MARKER = "content-body-plain-text-MARKER"


def _policy_item(plcy_no: str) -> dict[str, Any]:
    return {
        "plcyNo": plcy_no,
        "plcyNm": "테스트 정책",
        "plcyExplnCn": "설명입니다. 본문이 충분히 있습니다.",
        "plcySprtCn": "지원 내용입니다.",
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


def _seed(store: MemoryIngestStore, count: int) -> None:
    started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
    records = [_observation(f"p{i}") for i in range(count)]
    store.upsert_source_observations(
        CANONICAL_POLICY_SOURCE,
        started.run_id,
        records,
        Checkpoint.for_rest_page(2),
    )


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
        self.complete_error: Exception | None = None
        self.fail_error: Exception | None = None

    def claim_processing_jobs(self, *args: Any, **kwargs: Any) -> Any:
        self.claim_calls += 1
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
        job = next(iter(store.jobs.values()))
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


if __name__ == "__main__":
    unittest.main()
