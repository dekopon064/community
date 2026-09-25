"""Human content_review close: insufficient_evidence ends the current revision."""

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone

from ingest.gate_facts import GATE_FACTS_SCHEMA_VERSION
from ingest.rpc_errors import RpcFailure
from ingest.source_identity import CANONICAL_POLICY_SOURCE, curation_source_for_enqueue
from ingest.store import _Candidate
from legacy_category_test_store import LegacyCategoryFixtureStore as MemoryIngestStore
from test_ingest import policy_item
from test_ingest_assessment import _event_item, _policy_connector

REVIEWER = "human:content-close"
RULE_VERSION = "content-close-v1"
PASSING_POLICY_FACTS = {
    "schema_version": GATE_FACTS_SCHEMA_VERSION,
    "eligibility_scope": "nationwide",
    "eligibility_region_codes": [],
    "eligibility_region_evidence": "human",
    "foreign_resident_eligibility": "eligible",
}


def _review_item(key: str = "hold"):
    body = "상시 지원 자격과 이용 방법입니다. 지역 주민 안내입니다."
    record = _policy_connector().to_observation(
        policy_item(
            key,
            zip_cd="",
            oper_cd="",
            plcyExplnCn=body,
            plcySprtCn=body,
        ),
        permission_status="testing_only",
        enabled=True,
    )
    store = MemoryIngestStore()
    started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
    store.upsert_source_observations_v4(
        CANONICAL_POLICY_SOURCE, started.run_id, [record], None
    )
    item = store.items[(CANONICAL_POLICY_SOURCE, key)]
    return store, started, item


def _content_jobs(store: MemoryIngestStore, item):
    return [
        job
        for job in store.jobs.values()
        if job.source_item_id == item.id
        and job.revision_hash == item.revision_hash
        and job.processing_stage == "content_review"
    ]


def _ai_jobs(store: MemoryIngestStore, item, revision_hash: str | None = None):
    revision = item.revision_hash if revision_hash is None else revision_hash
    return [
        job
        for job in store.jobs.values()
        if job.source_item_id == item.id
        and job.revision_hash == revision
        and job.processing_stage == "ai_enrichment"
    ]


def _reject(store: MemoryIngestStore, item, **overrides: object):
    params = dict(
        source_item_id=item.id,
        revision_hash=item.revision_hash,
        review_type="content",
        decision="reject",
        region_scope="unknown",
        reason_codes=("insufficient_evidence",),
        rule_version=RULE_VERSION,
        reviewer=REVIEWER,
    )
    params.update(overrides)
    return store.resolve_ingest_review_decision(**params)


class ContentReviewCloseTests(unittest.TestCase):
    def test_no_call_leaves_content_review_queued(self) -> None:
        store, _started, item = _review_item()
        reviews = _content_jobs(store, item)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].status, "queued")
        self.assertEqual(item.disposition, "region_review_required")
        self.assertEqual(store.decisions, {})
        self.assertEqual(_ai_jobs(store, item), [])

    def test_content_reject_closes_revision_without_ai(self) -> None:
        store, _started, item = _review_item()
        result = _reject(store, item)
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(result.decision, "reject")
        self.assertEqual(result.review_job_status, "completed")
        self.assertEqual([job.status for job in _content_jobs(store, item)], ["completed"])
        self.assertEqual(_ai_jobs(store, item), [])
        decision = store.decisions[(item.id, item.revision_hash, "content")]
        self.assertEqual(decision.decision, "reject")
        self.assertIn("insufficient_evidence", decision.reason_codes)

    def test_queued_or_expired_ai_is_cancelled(self) -> None:
        now = datetime.now(timezone.utc)
        queued_store, _started, queued_item = _review_item("queued-ai")
        queued = queued_store._insert_job(
            queued_item.id,
            queued_item.revision_hash,
            "ai_enrichment",
            now,
            ("stale",),
        )
        _reject(queued_store, queued_item)
        self.assertEqual(queued.status, "cancelled")
        self.assertEqual(queued_item.disposition, "non_target")

        expired_store, _started, expired_item = _review_item("expired-ai")
        expired = expired_store._insert_job(
            expired_item.id,
            expired_item.revision_hash,
            "ai_enrichment",
            now,
            ("expired",),
        )
        expired.status = "claimed"
        expired.claim_lease_until = now - timedelta(minutes=1)
        expired.claimed_by = "old-worker"
        _reject(expired_store, expired_item)
        self.assertEqual(expired.status, "cancelled")
        self.assertEqual(expired_item.disposition, "non_target")
        self.assertEqual(
            [
                job.status
                for job in _ai_jobs(expired_store, expired_item)
                if job.status in {"queued", "claimed"}
            ],
            [],
        )

    def test_reject_without_insufficient_evidence_is_refused(self) -> None:
        store, _started, item = _review_item()
        before_jobs = copy.deepcopy(store.jobs)
        with self.assertRaises(RpcFailure) as err:
            _reject(store, item, reason_codes=("region_scope_unknown",))
        self.assertEqual(err.exception.code, "insufficient_evidence_required")
        self.assertEqual(item.disposition, "region_review_required")
        self.assertEqual(store.decisions, {})
        self.assertEqual(_content_jobs(store, item)[0].status, "queued")
        self.assertEqual(
            {job.id: job.status for job in store.jobs.values()},
            {job.id: job.status for job in before_jobs.values()},
        )

    def test_content_approve_ai_is_refused(self) -> None:
        store, _started, item = _review_item()
        with self.assertRaises(RpcFailure) as err:
            _reject(
                store,
                item,
                decision="approve_ai",
                region_scope="capital",
                audience_relevance=("jp_residents_in_kr",),
                reason_codes=("insufficient_evidence",),
            )
        self.assertEqual(err.exception.code, "invalid_decision")
        self.assertEqual(item.disposition, "region_review_required")
        self.assertEqual(store.decisions, {})
        self.assertEqual(_content_jobs(store, item)[0].status, "queued")
        self.assertEqual(_ai_jobs(store, item), [])

    def test_revision_mismatch_is_refused(self) -> None:
        store, _started, item = _review_item()
        with self.assertRaises(RpcFailure) as err:
            _reject(store, item, revision_hash="b" * 64)
        self.assertEqual(err.exception.code, "revision_mismatch")
        self.assertEqual(store.decisions, {})
        self.assertEqual(_content_jobs(store, item)[0].status, "queued")

    def test_live_claimed_ai_rolls_back_the_call(self) -> None:
        store, _started, item = _review_item()
        now = datetime.now(timezone.utc)
        ai = store._insert_job(
            item.id, item.revision_hash, "ai_enrichment", now, ("live",)
        )
        ai.status = "claimed"
        ai.claimed_by = "live-worker"
        ai.claim_lease_until = now + timedelta(minutes=5)
        before_disposition = item.disposition
        before_jobs = copy.deepcopy(store.jobs)
        before_decisions = copy.deepcopy(store.decisions)
        with self.assertRaises(RpcFailure) as err:
            _reject(store, item)
        self.assertEqual(err.exception.code, "ai_job_claimed")
        self.assertEqual(item.disposition, before_disposition)
        self.assertEqual(store.decisions, before_decisions)
        self.assertEqual(ai.status, "claimed")
        self.assertEqual(ai.claimed_by, "live-worker")
        self.assertEqual(
            {job.id: (job.status, job.claim_lease_until) for job in store.jobs.values()},
            {
                job.id: (job.status, job.claim_lease_until)
                for job in before_jobs.values()
            },
        )
        self.assertEqual(_content_jobs(store, item)[0].status, "queued")

    def test_same_revision_reevaluation_keeps_non_target(self) -> None:
        store, _started, item = _review_item()
        _reject(store, item)
        result = store.resolve_source_item_gate_facts(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            gate_facts=PASSING_POLICY_FACTS,
            assessment_schema_version=GATE_FACTS_SCHEMA_VERSION,
            reviewer=REVIEWER,
        )
        self.assertEqual(result.disposition, "non_target")
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(_content_jobs(store, item)[0].status, "completed")
        self.assertEqual(
            [job.status for job in _ai_jobs(store, item) if job.status in {"queued", "claimed"}],
            [],
        )

    def test_new_revision_evaluates_without_inheriting_the_close(self) -> None:
        store, started, item = _review_item("again")
        _reject(store, item)
        old_hash = item.revision_hash
        record = _policy_connector().to_observation(
            _event_item("again"),
            permission_status="testing_only",
            enabled=True,
        )
        store.upsert_source_observations_v4(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "again")]
        self.assertNotEqual(item.revision_hash, old_hash)
        self.assertEqual(item.disposition, "target")
        self.assertNotIn((item.id, item.revision_hash, "content"), store.decisions)
        self.assertEqual(
            store.decisions[(item.id, old_hash, "content")].decision,
            "reject",
        )
        ais = _ai_jobs(store, item)
        self.assertEqual(len(ais), 1)
        self.assertEqual(ais[0].status, "queued")


def _seed(record):
    store = MemoryIngestStore()
    started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
    store.upsert_source_observations_v4(
        CANONICAL_POLICY_SOURCE, started.run_id, [record], None
    )
    item = next(iter(store.items.values()))
    return store, item


def _target_record(key: str):
    return _policy_connector().to_observation(
        _event_item(key),
        permission_status="testing_only",
        enabled=True,
    )


def _non_target_record(key: str):
    body = "이번 회차 신청과 개최 안내입니다."
    return _policy_connector().to_observation(
        policy_item(
            key,
            zip_cd="50110",
            oper_cd="50110",
            plcyExplnCn=body,
            plcySprtCn=body,
        ),
        permission_status="testing_only",
        enabled=True,
    )


def _candidate(item, revision_hash: str) -> _Candidate:
    return _Candidate(
        source=curation_source_for_enqueue(item.source_id),
        source_item_id=item.external_key,
        source_revision_hash=revision_hash,
    )


def _snapshot(store: MemoryIngestStore, item):
    return {
        "disposition": item.disposition,
        "decisions": copy.deepcopy(store.decisions),
        "jobs": {
            job.id: (
                job.status,
                job.revision_hash,
                job.processing_stage,
                job.reason_codes,
                job.claimed_by,
                job.claim_lease_until,
            )
            for job in store.jobs.values()
        },
        "candidates": copy.deepcopy(store.candidates),
    }


class ContentRejectGuardTests(unittest.TestCase):
    def test_target_without_open_content_review_is_refused(self) -> None:
        store, item = _seed(_target_record("target-closed"))
        self.assertEqual(item.disposition, "target")
        self.assertEqual(_content_jobs(store, item), [])
        before = _snapshot(store, item)
        with self.assertRaises(RpcFailure) as err:
            _reject(store, item)
        self.assertEqual(err.exception.code, "content_review_not_open")
        self.assertEqual(_snapshot(store, item), before)

    def test_non_target_without_open_content_review_is_refused(self) -> None:
        store, item = _seed(_non_target_record("non-target-closed"))
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(_content_jobs(store, item), [])
        before = _snapshot(store, item)
        with self.assertRaises(RpcFailure) as err:
            _reject(store, item)
        self.assertEqual(err.exception.code, "content_review_not_open")
        self.assertEqual(_snapshot(store, item), before)

    def test_current_revision_candidate_blocks_content_reject(self) -> None:
        store, _started, item = _review_item("has-candidate")
        candidate = _candidate(item, item.revision_hash)
        store.candidates.append(candidate)
        before = _snapshot(store, item)
        with self.assertRaises(RpcFailure) as err:
            _reject(store, item)
        self.assertEqual(err.exception.code, "curation_candidate_exists")
        self.assertEqual(_snapshot(store, item), before)
        self.assertEqual(store.candidates, [candidate])

    def test_other_revision_candidate_does_not_block_close(self) -> None:
        store, _started, item = _review_item("old-candidate")
        other = _candidate(item, "a" * 64)
        store.candidates.append(other)
        _reject(store, item)
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(_content_jobs(store, item)[0].status, "completed")
        self.assertEqual(_ai_jobs(store, item), [])
        self.assertEqual(store.candidates, [other])
        self.assertIn((item.id, item.revision_hash, "content"), store.decisions)

    def test_open_content_review_without_candidate_still_closes(self) -> None:
        store, _started, item = _review_item("still-open")
        self.assertEqual(_content_jobs(store, item)[0].status, "queued")
        self.assertEqual(store.candidates, [])
        _reject(store, item)
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(_content_jobs(store, item)[0].status, "completed")
        self.assertEqual(_ai_jobs(store, item), [])

    def test_region_reject_ignores_current_candidate(self) -> None:
        store, item = _seed(_target_record("region-still"))
        candidate = _candidate(item, item.revision_hash)
        store.candidates.append(candidate)
        result = store.resolve_ingest_review_decision(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            review_type="region",
            decision="reject",
            region_scope="capital",
            rule_version=RULE_VERSION,
            reviewer=REVIEWER,
        )
        self.assertEqual(result.review_type, "region")
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(store.candidates, [candidate])
        self.assertNotIn((item.id, item.revision_hash, "content"), store.decisions)


if __name__ == "__main__":
    unittest.main()
