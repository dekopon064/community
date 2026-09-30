"""Offline contracts for scheduled and manual un-targeted AI queue runs."""

from __future__ import annotations

import unittest
from pathlib import Path

from ingest.constants import DEFAULT_JOB_LEASE_SECONDS
from ingest.source_identity import CANONICAL_POLICY_SOURCE
from ingest.store import MemoryIngestStore
from test_ingest import Clock
from test_ingest_assessment import _ai_jobs, _event_item, _policy_connector, _v4_upsert
from test_ingest_user_category_period import _resolve


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/manual-ai-queue.yml"
CLAIM_MIGRATION = ROOT / "supabase/migrations/20260928000000_ingest_user_category_period.sql"


def _items(store: MemoryIngestStore, *keys: str):
    records = [
        _policy_connector().to_observation(
            _event_item(key, aplyPrdSeCd="0057001", aplyYmd="2026-09-30"),
            permission_status="testing_only",
            enabled=True,
        )
        for key in keys
    ]
    _v4_upsert(store, CANONICAL_POLICY_SOURCE, records)
    return [store.items[(CANONICAL_POLICY_SOURCE, key)] for key in keys]


class ManualAiQueueContractTests(unittest.TestCase):
    def test_workflow_schedules_five_jobs_and_keeps_manual_one_job(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("schedule:", workflow)
        self.assertIn("cron: '0 10 * * *'", workflow)
        self.assertIn("timezone: Asia/Seoul", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("group: machimoa-ingest-production", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("environment: machimoa-ingest-production", workflow)
        self.assertIn("if: github.ref == 'refs/heads/main'", workflow)
        self.assertIn("AI_LIMIT: ${{ github.event_name == 'schedule' && '5' || '1' }}", workflow)
        self.assertIn('--ai-only --execute --ai-limit "$AI_LIMIT"', workflow)
        self.assertNotIn("--ai-source-item-id", workflow)
        self.assertNotIn("--ai-revision-hash", workflow)
        self.assertNotIn("YOUTH_API_KEY", workflow)
        self.assertNotIn("YOUTH_CONTENT_API_KEY", workflow)
        self.assertNotIn("publish_curation_candidate", workflow)
        self.assertIn("timeout-minutes: 9", workflow)
        self.assertLess(9 * 60, DEFAULT_JOB_LEASE_SECONDS)

    def test_sql_claim_checks_current_revision_gates_and_row_lock(self) -> None:
        migration = CLAIM_MIGRATION.read_text(encoding="utf-8").lower()
        claim = migration.split(
            "create or replace function machimoa_review.claim_processing_jobs(", 1
        )[1].split("$function$;", 1)[0]
        self.assertIn("si.revision_hash is not distinct from j.revision_hash", claim)
        self.assertIn("category_period_ready(j.source_item_id, j.revision_hash)", claim)
        self.assertIn("r.status in ('queued', 'claimed')", claim)
        self.assertIn("j.next_retry_at <= v_now", claim)
        self.assertIn("j.claim_lease_until <= v_now", claim)
        self.assertIn("for update of j skip locked", claim)
        self.assertIn("limit v_limit", claim)

    def test_one_claim_at_a_time_and_no_duplicate_after_completion(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        first, second = _items(store, "manual-queue-first", "manual-queue-second")
        _resolve(store, first, "policy")
        _resolve(store, second, "policy")

        first_claim = store.claim_processing_jobs(
            "ai_enrichment", limit=1, worker_id="worker-one"
        )
        self.assertEqual(len(first_claim), 1)
        second_claim = store.claim_processing_jobs(
            "ai_enrichment", limit=1, worker_id="worker-two"
        )
        self.assertEqual(len(second_claim), 1)
        self.assertNotEqual(first_claim[0].job_id, second_claim[0].job_id)
        store.complete_processing_job(first_claim[0].job_id, worker_id="worker-one")
        store.complete_processing_job(second_claim[0].job_id, worker_id="worker-two")
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", limit=1, worker_id="worker-three"),
            [],
        )

    def test_five_claim_limit_leaves_sixth_for_next_run(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        items = _items(store, *(f"scheduled-{index}" for index in range(6)))
        for item in items:
            _resolve(store, item, "policy")

        first_run = store.claim_processing_jobs(
            "ai_enrichment", limit=5, worker_id="worker-one"
        )
        self.assertEqual(len(first_run), 5)
        for job in first_run:
            store.complete_processing_job(job.job_id, worker_id="worker-one")

        next_run = store.claim_processing_jobs(
            "ai_enrichment", limit=5, worker_id="worker-two"
        )
        self.assertEqual(len(next_run), 1)
        self.assertNotIn(next_run[0].job_id, {job.job_id for job in first_run})

    def test_missing_category_or_period_open_review_and_stale_revision_block(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        no_category, no_period, open_review, stale = _items(
            store, "no-category", "no-period", "open-review", "stale-revision"
        )
        _resolve(store, no_period, "policy")
        _resolve(store, open_review, "policy")
        _resolve(store, stale, "policy")
        store.application_deadlines.pop((no_period.id, no_period.revision_hash))
        store._insert_job(
            no_category.id, no_category.revision_hash,
            "ai_enrichment", clock.now, (),
        )
        store._insert_job(
            open_review.id, open_review.revision_hash,
            "content_review", clock.now, (),
        )
        store.jobs[_ai_jobs(store, stale)[0].id].revision_hash = "0" * 64
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", limit=1, worker_id="worker"),
            [],
        )

    def test_retry_wait_and_terminal_failure_are_not_claimed(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        (item,) = _items(store, "manual-queue-retry")
        _resolve(store, item, "policy")

        for attempt in range(3):
            claimed = store.claim_processing_jobs(
                "ai_enrichment", limit=1, worker_id="worker"
            )
            self.assertEqual(len(claimed), 1)
            status = store.fail_processing_job(
                claimed[0].job_id, worker_id="worker", error_code="test_failure"
            )
            self.assertEqual(status, "failed" if attempt == 2 else "queued")
            self.assertEqual(
                store.claim_processing_jobs("ai_enrichment", limit=1, worker_id="worker"),
                [],
            )
            clock.advance(30)

    def test_live_lease_blocks_duplicate_claim_until_expiry(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        (item,) = _items(store, "manual-queue-lease")
        _resolve(store, item, "policy")

        first = store.claim_processing_jobs(
            "ai_enrichment", limit=1, worker_id="worker-one"
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", limit=1, worker_id="worker-two"),
            [],
        )
        clock.advance(DEFAULT_JOB_LEASE_SECONDS)
        reclaimed = store.claim_processing_jobs(
            "ai_enrichment", limit=1, worker_id="worker-two"
        )
        self.assertEqual([job.job_id for job in reclaimed], [first[0].job_id])


if __name__ == "__main__":
    unittest.main()
