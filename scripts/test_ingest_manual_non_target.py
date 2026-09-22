"""Manual non-target exclude for open content_review and product_type_review."""

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone

from ingest.gate_facts import GATE_FACTS_SCHEMA_VERSION
from ingest.rpc_errors import RpcFailure
from ingest.source_identity import CANONICAL_POLICY_SOURCE, curation_source_for_enqueue
from ingest.store import MemoryIngestStore, _Candidate, _Publication
from test_ingest import policy_item
from test_ingest_assessment import _event_item, _policy_connector

REVIEWER = "human:manual-exclude"
RULE_VERSION = "manual-non-target-v1"
NOW = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
OTHER_HASH = "c" * 64
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
    store = MemoryIngestStore(clock=lambda: NOW)
    started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
    store.upsert_source_observations_v4(
        CANONICAL_POLICY_SOURCE, started.run_id, [record], None
    )
    item = store.items[(CANONICAL_POLICY_SOURCE, key)]
    return store, started, item


def _jobs(store: MemoryIngestStore, item, stage: str, revision_hash: str | None = None):
    revision = item.revision_hash if revision_hash is None else revision_hash
    return [
        job
        for job in store.jobs.values()
        if job.source_item_id == item.id
        and job.revision_hash == revision
        and job.processing_stage == stage
    ]


def _candidate(item, revision_hash: str, *, review_status: str = "pending") -> _Candidate:
    return _Candidate(
        source=curation_source_for_enqueue(item.source_id),
        source_item_id=item.external_key,
        source_revision_hash=revision_hash,
        review_status=review_status,
        reviewed_at=NOW if review_status == "published" else None,
        reviewed_by=REVIEWER if review_status == "published" else None,
    )


def _publication(item, revision_hash: str, *, status: str = "published") -> _Publication:
    return _Publication(
        id="pub-1",
        source_id=item.source_id,
        external_key=item.external_key,
        revision_hash=revision_hash,
        candidate_id=None,
        public_curation_id="curation-1",
        publication_status=status,
        published_at=NOW,
    )


def _exclude(store: MemoryIngestStore, item, **overrides: object):
    params = dict(
        source_item_id=item.id,
        revision_hash=item.revision_hash,
        review_type="content",
        decision="reject",
        region_scope="unknown",
        reason_codes=("manual_non_target",),
        rule_version=RULE_VERSION,
        reviewer=REVIEWER,
    )
    params.update(overrides)
    return store.resolve_ingest_review_decision(**params)


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
                job.completed_at,
            )
            for job in store.jobs.values()
        },
        "candidates": copy.deepcopy(store.candidates),
        "publications": copy.deepcopy(store.publications),
    }


class ManualNonTargetTests(unittest.TestCase):
    def test_content_review_manual_exclude_succeeds_without_interpreting_memo(self) -> None:
        store, _started, item = _review_item("content-memo")
        result = _exclude(store, item, memo="운영 메모. target라고 적어도 제외다.")
        self.assertEqual(result.decision, "reject")
        self.assertEqual(result.review_type, "content")
        self.assertEqual(result.review_job_status, "completed")
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(_jobs(store, item, "content_review")[0].status, "completed")
        decision = store.decisions[(item.id, item.revision_hash, "content")]
        self.assertEqual(decision.reason_codes, ("manual_non_target",))
        self.assertEqual(decision.memo, "운영 메모. target라고 적어도 제외다.")
        self.assertEqual(_jobs(store, item, "ai_enrichment"), [])

        bare, _started, bare_item = _review_item("content-no-memo")
        _exclude(bare, bare_item)
        bare_decision = bare.decisions[(bare_item.id, bare_item.revision_hash, "content")]
        self.assertIsNone(bare_decision.memo)
        self.assertEqual(bare_item.disposition, "non_target")

    def test_product_type_review_manual_exclude_succeeds(self) -> None:
        store, _started, item = _review_item("type-open")
        review = store._insert_job(
            item.id, item.revision_hash, "product_type_review", NOW, ("type_unknown",)
        )
        result = _exclude(store, item, review_type="product_type")
        self.assertEqual(result.review_type, "product_type")
        self.assertEqual(result.review_job_status, "completed")
        self.assertEqual(review.status, "completed")
        self.assertEqual(item.disposition, "non_target")
        decision = store.decisions[(item.id, item.revision_hash, "product_type")]
        self.assertEqual(decision.decision, "reject")
        self.assertIn("manual_non_target", decision.reason_codes)
        rerun = store.resolve_source_item_gate_facts(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            gate_facts=PASSING_POLICY_FACTS,
            assessment_schema_version=GATE_FACTS_SCHEMA_VERSION,
            reviewer=REVIEWER,
        )
        self.assertEqual(rerun.disposition, "non_target")
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(review.status, "completed")
        self.assertEqual(_jobs(store, item, "ai_enrichment"), [])

    def test_v1r006_shape_rejects_pending_candidate_and_keeps_completed_ai(self) -> None:
        store, _started, item = _review_item("v1r-006")
        review = store._insert_job(
            item.id, item.revision_hash, "product_type_review", NOW, ("type_unknown",)
        )
        ai = store._insert_job(
            item.id, item.revision_hash, "ai_enrichment", NOW, ("already_done",)
        )
        ai.status = "completed"
        ai.completed_at = NOW
        pending = _candidate(item, item.revision_hash)
        store.candidates.append(pending)
        _exclude(store, item, review_type="product_type", memo="범위 밖")
        self.assertEqual(pending.review_status, "rejected")
        self.assertEqual(pending.review_notes, "범위 밖")
        self.assertEqual(pending.reviewed_by, REVIEWER)
        self.assertEqual(pending.reviewed_at, NOW)
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(review.status, "completed")
        self.assertEqual(ai.status, "completed")
        self.assertEqual(ai.completed_at, NOW)
        self.assertEqual(len(_jobs(store, item, "ai_enrichment")), 1)

    def test_no_open_review_is_refused(self) -> None:
        store, _started, item = _review_item("no-review")
        content = _jobs(store, item, "content_review")[0]
        content.status = "completed"
        content.completed_at = NOW
        before = _snapshot(store, item)
        with self.assertRaises(RpcFailure) as content_err:
            _exclude(store, item)
        self.assertEqual(content_err.exception.code, "content_review_not_open")
        self.assertEqual(_snapshot(store, item), before)
        with self.assertRaises(RpcFailure) as type_err:
            _exclude(store, item, review_type="product_type")
        self.assertEqual(type_err.exception.code, "product_type_review_not_open")
        self.assertEqual(_snapshot(store, item), before)

    def test_live_claimed_ai_rolls_back_the_whole_call(self) -> None:
        store, _started, item = _review_item("live-ai")
        store._insert_job(
            item.id, item.revision_hash, "product_type_review", NOW, ("type_unknown",)
        )
        ai = store._insert_job(
            item.id, item.revision_hash, "ai_enrichment", NOW, ("live",)
        )
        ai.status = "claimed"
        ai.claimed_by = "live-worker"
        ai.claim_lease_until = NOW + timedelta(minutes=5)
        pending = _candidate(item, item.revision_hash)
        store.candidates.append(pending)
        before = _snapshot(store, item)
        with self.assertRaises(RpcFailure) as err:
            _exclude(store, item, review_type="product_type", memo="should not stick")
        self.assertEqual(err.exception.code, "ai_job_claimed")
        self.assertEqual(_snapshot(store, item), before)
        self.assertEqual(pending.review_status, "pending")

    def test_published_candidate_or_publication_rolls_back(self) -> None:
        store, _started, item = _review_item("published-candidate")
        published = _candidate(item, item.revision_hash, review_status="published")
        pending = _candidate(item, item.revision_hash)
        store.candidates.extend([published, pending])
        before = _snapshot(store, item)
        with self.assertRaises(RpcFailure) as err:
            _exclude(store, item)
        self.assertEqual(err.exception.code, "candidate_already_published")
        self.assertEqual(_snapshot(store, item), before)
        self.assertEqual(pending.review_status, "pending")
        self.assertEqual(published.review_status, "published")

        pub_store, _started, pub_item = _review_item("published-lineage")
        publication = _publication(pub_item, pub_item.revision_hash)
        pub_store.publications.append(publication)
        waiting = _candidate(pub_item, pub_item.revision_hash)
        pub_store.candidates.append(waiting)
        before_pub = _snapshot(pub_store, pub_item)
        with self.assertRaises(RpcFailure) as pub_err:
            _exclude(pub_store, pub_item)
        self.assertEqual(pub_err.exception.code, "candidate_already_published")
        self.assertEqual(_snapshot(pub_store, pub_item), before_pub)
        self.assertEqual(publication.publication_status, "published")
        self.assertEqual(waiting.review_status, "pending")

    def test_pending_candidate_is_rejected_in_the_same_call(self) -> None:
        store, _started, item = _review_item("pending")
        pending = _candidate(item, item.revision_hash)
        superseded = _candidate(item, item.revision_hash, review_status="superseded")
        store.candidates.extend([pending, superseded])
        _exclude(store, item)
        self.assertEqual(pending.review_status, "rejected")
        self.assertEqual(pending.reviewed_by, REVIEWER)
        self.assertIsNone(pending.review_notes)
        self.assertEqual(superseded.review_status, "superseded")
        self.assertIsNone(superseded.reviewed_by)
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(_jobs(store, item, "content_review")[0].status, "completed")

    def test_other_revision_candidate_does_not_affect_current_revision(self) -> None:
        store, _started, item = _review_item("other-rev")
        other = _candidate(item, OTHER_HASH, review_status="published")
        current = _candidate(item, item.revision_hash)
        store.candidates.extend([other, current])
        publication = _publication(item, OTHER_HASH)
        store.publications.append(publication)
        _exclude(store, item)
        self.assertEqual(other.review_status, "published")
        self.assertEqual(current.review_status, "rejected")
        self.assertEqual(publication.publication_status, "published")
        self.assertEqual(publication.revision_hash, OTHER_HASH)
        self.assertEqual(item.disposition, "non_target")

    def test_same_revision_reevaluation_keeps_non_target_and_completed_ai(self) -> None:
        store, _started, item = _review_item("pin")
        ai = store._insert_job(
            item.id, item.revision_hash, "ai_enrichment", NOW, ("done",)
        )
        ai.status = "completed"
        ai.completed_at = NOW
        _exclude(store, item)
        result = store.resolve_source_item_gate_facts(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            gate_facts=PASSING_POLICY_FACTS,
            assessment_schema_version=GATE_FACTS_SCHEMA_VERSION,
            reviewer=REVIEWER,
        )
        self.assertEqual(result.disposition, "non_target")
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(_jobs(store, item, "content_review")[0].status, "completed")
        self.assertEqual(ai.status, "completed")
        self.assertEqual(ai.completed_at, NOW)
        self.assertEqual(
            [job.status for job in _jobs(store, item, "ai_enrichment")],
            ["completed"],
        )

    def test_new_revision_evaluates_without_inheriting_manual_non_target(self) -> None:
        store, started, item = _review_item("again")
        _exclude(store, item)
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
        self.assertNotIn((item.id, item.revision_hash, "product_type"), store.decisions)
        self.assertEqual(
            store.decisions[(item.id, old_hash, "content")].reason_codes,
            ("manual_non_target",),
        )
        ais = _jobs(store, item, "ai_enrichment")
        self.assertEqual(len(ais), 1)
        self.assertEqual(ais[0].status, "queued")

    def test_queued_or_expired_ai_is_cancelled_and_completed_ai_is_kept(self) -> None:
        queued_store, _started, queued_item = _review_item("queued-ai")
        queued = queued_store._insert_job(
            queued_item.id,
            queued_item.revision_hash,
            "ai_enrichment",
            NOW,
            ("stale",),
        )
        _exclude(queued_store, queued_item)
        self.assertEqual(queued.status, "cancelled")
        self.assertEqual(queued_item.disposition, "non_target")

        expired_store, _started, expired_item = _review_item("expired-ai")
        expired = expired_store._insert_job(
            expired_item.id,
            expired_item.revision_hash,
            "ai_enrichment",
            NOW,
            ("expired",),
        )
        expired.status = "claimed"
        expired.claim_lease_until = NOW - timedelta(minutes=1)
        expired.claimed_by = "old-worker"
        _exclude(expired_store, expired_item)
        self.assertEqual(expired.status, "cancelled")

    def test_content_and_product_type_reject_only(self) -> None:
        store, _started, item = _review_item("reject-only")
        store._insert_job(
            item.id, item.revision_hash, "product_type_review", NOW, ("type_unknown",)
        )
        before = _snapshot(store, item)
        with self.assertRaises(RpcFailure) as approve_err:
            _exclude(
                store,
                item,
                decision="approve_ai",
                region_scope="capital",
                audience_relevance=("jp_residents_in_kr",),
            )
        self.assertEqual(approve_err.exception.code, "invalid_decision")
        with self.assertRaises(RpcFailure) as needs_err:
            _exclude(store, item, review_type="product_type", decision="needs_review")
        self.assertEqual(needs_err.exception.code, "invalid_decision")
        with self.assertRaises(RpcFailure) as reason_err:
            _exclude(store, item, review_type="product_type", reason_codes=("type_unknown",))
        self.assertEqual(reason_err.exception.code, "manual_non_target_required")
        self.assertEqual(_snapshot(store, item), before)

    def test_region_and_relevance_do_not_reject_candidates(self) -> None:
        store, started, _item = _review_item("region-still")
        record = _policy_connector().to_observation(
            _event_item("region-still"),
            permission_status="testing_only",
            enabled=True,
        )
        store.upsert_source_observations_v4(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "region-still")]
        self.assertEqual(item.disposition, "target")
        candidate = _candidate(item, item.revision_hash)
        store.candidates.append(candidate)
        result = store.resolve_ingest_review_decision(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            review_type="region",
            decision="reject",
            region_scope="noncapital",
            rule_version=RULE_VERSION,
            reviewer=REVIEWER,
        )
        self.assertEqual(result.review_type, "region")
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(candidate.review_status, "pending")
        self.assertIsNone(candidate.reviewed_at)
        relevance = store.resolve_ingest_review_decision(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            review_type="relevance",
            decision="needs_review",
            region_scope="unknown",
            reason_codes=("relevance_unconfirmed",),
            rule_version=RULE_VERSION,
            reviewer=REVIEWER,
        )
        self.assertEqual(relevance.review_type, "relevance")
        self.assertEqual(relevance.review_job_status, "queued")
        self.assertEqual(candidate.review_status, "pending")
        self.assertNotIn((item.id, item.revision_hash, "content"), store.decisions)


if __name__ == "__main__":
    unittest.main()
