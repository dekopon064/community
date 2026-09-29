"""No-network tests for the revision-pinned 48:10799 AI input."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest.models import ClaimedJob
from ingest.ai_worker import AI_STATE_UNKNOWN, process_ai_jobs
from run_one_off_ai_10799 import (
    EXTERNAL_KEY,
    MANIFEST,
    OFFICIAL_URL,
    REVISION_HASH,
    SOURCE_ID,
    SOURCE_ITEM_ID,
    OneOffInputStore,
    load_evidence,
    run_one_off,
)


def claimed_job() -> ClaimedJob:
    return ClaimedJob(
        job_id="11111111-1111-4111-8111-111111111111",
        source_item_id=SOURCE_ITEM_ID,
        source_id=SOURCE_ID,
        external_key=EXTERNAL_KEY,
        revision_hash=REVISION_HASH,
        processing_stage="ai_enrichment",
        curation_source=SOURCE_ID,
        normalized_payload={
            "pstTtl": "뿌꾸의 돌봄시간(심화)",
            "plain_text": "홈페이지 링크: https://buly.kr/jc9Pam",
            "source_url": "https://buly.kr/jc9Pam",
        },
        disposition="target",
    )


class FakeStore:
    def __init__(self, job: ClaimedJob | None = None) -> None:
        self.job = claimed_job() if job is None else job
        self.claim_calls: list[tuple[str, dict[str, Any]]] = []
        self.completed: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.other_job = "22222222-2222-4222-8222-222222222222"
        self.other_job_status = "queued"

    def claim_processing_jobs(self, stage: str, **kwargs: Any) -> list[ClaimedJob]:
        self.claim_calls.append((stage, kwargs))
        if kwargs.get("target_source_item_id") != SOURCE_ITEM_ID:
            self.other_job_status = "claimed"
        return [self.job]

    def complete_processing_job(self, job_id: str, *, worker_id: str) -> None:
        self.completed.append(job_id)

    def fail_processing_job(self, job_id: str, *, worker_id: str, error_code: str) -> str:
        self.failed.append((job_id, error_code))
        return "failed"


class OneOffAi10799Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = load_evidence()
        self.store = FakeStore()
        self.ai_inputs: list[tuple[str, str, str]] = []
        self.enqueued: list[dict[str, Any]] = []

    def summarize(self, body: str, url: str, *, title: str) -> tuple[str, str, str]:
        self.ai_inputs.append((body, url, title))
        return "[한 줄 요약]\n집수리 실습 프로그램\n[대상]\n서울 청년 1인 가구", "success", "fake-model"

    def translate(self, title: str, content: str) -> tuple[str, str, str, str]:
        return "住居修理講座", "[要約]\n住居修理の実習", "success", "fake-model"

    def enqueue(self, _supabase: Any, params: dict[str, Any]) -> dict[str, Any]:
        self.enqueued.append(params)
        return {"outcome": "inserted", "candidate_id": "33333333-3333-4333-8333-333333333333"}

    def exercise(self, *, summarize: Any = None, precheck: Any = None, enqueue: Any = None) -> Any:
        return run_one_off(
            store=self.store,
            supabase=object(),
            evidence=self.evidence,
            summarize_ko=self.summarize if summarize is None else summarize,
            translate_ja=self.translate,
            enqueue=self.enqueue if enqueue is None else enqueue,
            revision_precheck=(lambda *_args: False) if precheck is None else precheck,
        )

    def test_manifest_records_exact_input_and_source(self) -> None:
        self.assertGreater(len(self.evidence.body), 300)
        self.assertEqual(
            hashlib.sha256(self.evidence.body.encode("utf-8")).hexdigest(),
            self.evidence.sha256,
        )
        self.assertIn("서울시 생활권 청년 1인 가구", self.evidence.body)
        self.assertIn("10월 1일 23:00", self.evidence.body)
        self.assertEqual(self.evidence.provenance("https://buly.kr/jc9Pam")["official_url"], OFFICIAL_URL)

    def test_exact_target_receives_body_and_candidate_provenance(self) -> None:
        original = dict(self.store.job.normalized_payload or {})
        result = self.exercise()
        self.assertEqual((result.claimed, result.completed, result.failed), (1, 1, 0))
        self.assertEqual(len(self.ai_inputs), 1)
        self.assertEqual(self.ai_inputs[0][:2], (self.evidence.body, OFFICIAL_URL))
        self.assertEqual(self.store.job.normalized_payload, original)
        self.assertEqual(self.store.completed, [self.store.job.job_id])
        self.assertEqual(self.store.other_job, "22222222-2222-4222-8222-222222222222")
        self.assertEqual(self.store.other_job_status, "queued")
        stage, kwargs = self.store.claim_calls[0]
        self.assertEqual(stage, "ai_enrichment")
        self.assertEqual(kwargs["target_source_item_id"], SOURCE_ITEM_ID)
        self.assertEqual(kwargs["target_revision_hash"], REVISION_HASH)
        self.assertEqual(kwargs["limit"], 1)
        candidate = self.enqueued[0]
        self.assertEqual(candidate["p_source_url"], OFFICIAL_URL)
        self.assertEqual(candidate["p_raw_payload"]["plain_text"], self.evidence.body)
        self.assertEqual(candidate["p_raw_payload"]["one_off_ai_input"]["input_sha256"], self.evidence.sha256)
        self.assertEqual(candidate["p_raw_payload"]["one_off_ai_input"]["source_item_id"], SOURCE_ITEM_ID)

    def test_wrong_id_or_revision_never_calls_ai(self) -> None:
        for modified in (
            replace(claimed_job(), source_item_id="99999999-9999-4999-8999-999999999999"),
            replace(claimed_job(), revision_hash="a" * 64),
            replace(claimed_job(), external_key="48:other"),
        ):
            with self.subTest(modified=modified):
                self.store = FakeStore(modified)
                self.ai_inputs.clear()
                self.enqueued.clear()
                result = self.exercise()
                self.assertEqual(result.status, AI_STATE_UNKNOWN)
                self.assertEqual(self.ai_inputs, [])
                self.assertEqual(self.enqueued, [])
                self.assertEqual(self.store.completed, [])

    def test_link_only_and_tampered_manifest_rejected_before_claim(self) -> None:
        source = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            source["input_lines"] = [source["original_plain_text"]]
            source["input_sha256"] = hashlib.sha256(
                source["original_plain_text"].encode("utf-8")
            ).hexdigest()
            path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "one_off_input_link_only"):
                load_evidence(path)
            source["input_lines"] = json.loads(MANIFEST.read_text(encoding="utf-8"))["input_lines"]
            path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "one_off_input_hash_mismatch"):
                load_evidence(path)

    def test_failed_ai_keeps_manifest_and_does_not_enqueue(self) -> None:
        def fail_summary(_body: str, _url: str, *, title: str) -> Any:
            raise RuntimeError("fake AI failure")

        result = self.exercise(summarize=fail_summary)
        self.assertEqual((result.claimed, result.failed), (1, 1))
        self.assertEqual(self.enqueued, [])
        self.assertEqual(len(self.store.failed), 1)
        self.assertTrue(MANIFEST.is_file())
        self.assertEqual(load_evidence().sha256, self.evidence.sha256)

    def test_wrong_original_payload_does_not_call_ai(self) -> None:
        self.store = FakeStore(replace(
            claimed_job(),
            normalized_payload={"plain_text": "different", "source_url": "https://buly.kr/jc9Pam"},
        ))
        result = self.exercise()
        self.assertEqual(result.status, AI_STATE_UNKNOWN)
        self.assertEqual(self.ai_inputs, [])

    def test_generic_worker_cannot_send_link_only_to_ai(self) -> None:
        result = process_ai_jobs(
            self.store,
            supabase=object(),
            summarize_ko=self.summarize,
            translate_ja=self.translate,
            enqueue=self.enqueue,
            revision_precheck=lambda *_args: False,
            limit=1,
            require_jobs=True,
            target_source_item_id=SOURCE_ITEM_ID,
            target_revision_hash=REVISION_HASH,
        )
        self.assertEqual(result.failed, 1)
        self.assertEqual(self.ai_inputs, [])
        self.assertEqual(self.enqueued, [])

    def test_existing_candidate_is_not_reported_as_ai_success(self) -> None:
        result = self.exercise(precheck=lambda *_args: True)
        self.assertEqual(result.status, AI_STATE_UNKNOWN)
        self.assertEqual(self.ai_inputs, [])
        self.assertEqual(self.enqueued, [])
        self.assertEqual(self.store.completed, [])

    def test_duplicate_enqueue_is_not_reported_as_success(self) -> None:
        result = self.exercise(enqueue=lambda *_args: {
            "outcome": "duplicate", "candidate_id": "33333333-3333-4333-8333-333333333333"
        })
        self.assertEqual(result.status, AI_STATE_UNKNOWN)
        self.assertEqual(self.store.completed, [])


if __name__ == "__main__":
    unittest.main()
