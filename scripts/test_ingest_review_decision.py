"""Phase 2 review-decision RPC, claim gate, and classifier-id blocker tests."""

from __future__ import annotations

import copy
import unittest
from dataclasses import fields, replace

from ingest.models import (
    AI_STAGE,
    Checkpoint,
    CLASSIFIER_DECISION_KEYS,
    JobPlan,
    ObservationResult,
    RELEVANCE_REVIEW_STAGE,
    RelationshipPlan,
)
from ingest.relevance import (
    AXIS_FOREIGN_RESIDENTS_IN_KR,
    AXIS_JP_RESIDENTS_IN_KR,
    RULE_VERSION,
)
from ingest.rpc_errors import RpcFailure
from ingest.source_identity import CANONICAL_CONTENT_SOURCE, CANONICAL_POLICY_SOURCE
from ingest.store import BLOCKING_REVIEW_STAGES, MemoryIngestStore
from test_ingest import (
    Clock,
    load_content,
    observation_for,
    policy_item,
    v3_content_observation,
)

REVIEWER = f"classifier:{RULE_VERSION}"
HASH_B = "b" * 64
CLEAR_FIT_BODY = "재한 일본인은 신청 가능합니다. 서울 거주자를 대상으로 합니다."
HUMAN_REVIEW_STAGES = (
    "region_review",
    RELEVANCE_REVIEW_STAGE,
    "content_review",
    "relationship_review",
)
REVIEW_TYPE_TO_STAGE = {
    "region": "region_review",
    "relevance": RELEVANCE_REVIEW_STAGE,
}


def _start(store: MemoryIngestStore):
    return store.start_ingest_run(CANONICAL_POLICY_SOURCE)


def _clear_fit(key: str = "p-fit", **extra: object):
    return observation_for(
        policy_item(
            key,
            zip_cd="11680",
            oper_cd="11680",
            plcyExplnCn=CLEAR_FIT_BODY,
            plcySprtCn=CLEAR_FIT_BODY,
            **extra,
        )
    )


def _inject_unapproved_ai(store: MemoryIngestStore, item) -> None:
    store._insert_job(item.id, item.revision_hash, AI_STAGE, store._clock(), ())


def _upsert_injected_ai(store: MemoryIngestStore, key: str = "p1") -> None:
    started = _start(store)
    record = observation_for(policy_item(key, zip_cd="11680", oper_cd="11680"))
    store.upsert_source_observations(
        CANONICAL_POLICY_SOURCE,
        started.run_id,
        [record],
        None,
    )
    _inject_unapproved_ai(store, store.items[(CANONICAL_POLICY_SOURCE, key)])


def _upsert_target_no_job(store: MemoryIngestStore, key: str = "p-fit") -> None:
    started = _start(store)
    store.upsert_source_observations(
        CANONICAL_POLICY_SOURCE,
        started.run_id,
        [_clear_fit(key)],
        None,
    )


def _item(store: MemoryIngestStore):
    return next(iter(store.items.values()))


def _ai_job(store: MemoryIngestStore):
    jobs = [job for job in store.jobs.values() if job.processing_stage == AI_STAGE]
    return jobs[0] if jobs else None


def _enable_ai_claim(store: MemoryIngestStore, item) -> None:
    item.disposition = "target"
    item.body_usable = True
    item.has_source_url = True
    for job in store.jobs.values():
        if (
            job.source_item_id == item.id
            and job.revision_hash == item.revision_hash
            and job.processing_stage in BLOCKING_REVIEW_STAGES
            and job.status in {"queued", "claimed"}
        ):
            job.status = "completed"
    store.resolve_source_item_product_type(
        source_item_id=item.id,
        revision_hash=item.revision_hash,
        action="confirm",
        product_type="event_program",
        rule_version="product-type-v1",
        reviewer="human:test",
    )


def _seed_approved_target_ai(store: MemoryIngestStore, key: str = "ok"):
    started = _start(store)
    store.upsert_source_observations(
        CANONICAL_POLICY_SOURCE, started.run_id, [_clear_fit(key)], None
    )
    item = store.items[(CANONICAL_POLICY_SOURCE, key)]
    if item.disposition != "target" or not item.body_usable or not item.has_source_url:
        raise AssertionError("clear_fit_item_not_claimable")
    if _ai_job(store) is None:
        raise AssertionError("clear_fit_ai_missing")
    return item


def _insert_review_job(
    store: MemoryIngestStore, item, stage: str, status: str = "queued"
):
    job = store._insert_job(item.id, item.revision_hash, stage, store._clock(), ())
    job.status = status
    return job


def _human_jobs(store: MemoryIngestStore, item) -> dict[str, tuple]:
    found: dict[str, tuple] = {}
    for job in store.jobs.values():
        if job.source_item_id != item.id:
            continue
        if job.processing_stage not in HUMAN_REVIEW_STAGES:
            continue
        found[job.processing_stage] = (
            job.id,
            job.status,
            job.revision_hash,
            job.completed_at,
            job.claimed_by,
            job.claim_lease_until,
            job.reason_codes,
        )
    return found


def _seed_four_review_jobs(store: MemoryIngestStore, key: str = "four"):
    started = _start(store)
    record = observation_for(policy_item(key, zip_cd="11680", oper_cd="11680"))
    store.upsert_source_observations(
        CANONICAL_POLICY_SOURCE, started.run_id, [record], None
    )
    item = store.items[(CANONICAL_POLICY_SOURCE, key)]
    now = store._clock()
    existing = {
        job.processing_stage
        for job in store.jobs.values()
        if job.source_item_id == item.id and job.revision_hash == item.revision_hash
    }
    for stage in HUMAN_REVIEW_STAGES:
        if stage not in existing:
            store._insert_job(item.id, item.revision_hash, stage, now, ())
    jobs = _human_jobs(store, item)
    if set(jobs) != set(HUMAN_REVIEW_STAGES):
        raise AssertionError("four_review_jobs_required")
    if any(row[1] != "queued" for row in jobs.values()):
        raise AssertionError("four_review_jobs_must_start_queued")
    return item


def _seed_blocking_pair(store: MemoryIngestStore, key: str = "pair"):
    started = _start(store)
    record = observation_for(policy_item(key, zip_cd="11680", oper_cd="11680"))
    store.upsert_source_observations(
        CANONICAL_POLICY_SOURCE, started.run_id, [record], None
    )
    item = store.items[(CANONICAL_POLICY_SOURCE, key)]
    if item.disposition != "region_review_required":
        raise AssertionError("human_review_item_required")
    if not item.body_usable or not item.has_source_url:
        raise AssertionError("usable_human_review_item_required")
    stages = {
        job.processing_stage
        for job in store.jobs.values()
        if job.source_item_id == item.id and job.revision_hash == item.revision_hash
    }
    if "region_review" not in stages:
        raise AssertionError("region_review_required")
    if RELEVANCE_REVIEW_STAGE not in stages:
        store._insert_job(
            item.id, item.revision_hash, RELEVANCE_REVIEW_STAGE, store._clock(), ()
        )
    return item


def _current_stage_job(store: MemoryIngestStore, item, stage: str):
    for job in store.jobs.values():
        if (
            job.source_item_id == item.id
            and job.revision_hash == item.revision_hash
            and job.processing_stage == stage
        ):
            return job
    return None


def _current_ai(store: MemoryIngestStore, item):
    return [
        job
        for job in store.jobs.values()
        if job.source_item_id == item.id
        and job.revision_hash == item.revision_hash
        and job.processing_stage == AI_STAGE
    ]


def _run_counters(store: MemoryIngestStore) -> dict[str, object]:
    return {
        run_id: (run.batches_ok, run.status, run.stop_reason)
        for run_id, run in store.runs.items()
    }


def _item_snapshot(item) -> dict[str, object]:
    return {field.name: copy.deepcopy(getattr(item, field.name)) for field in fields(item)}


def _jobs_snapshot(store: MemoryIngestStore) -> dict[str, tuple]:
    return {
        job.id: (
            job.source_item_id,
            job.revision_hash,
            job.processing_stage,
            job.status,
            job.queued_at,
            job.available_at,
            job.claimed_at,
            job.completed_at,
            job.claim_lease_until,
            job.claimed_by,
            job.retry_count,
            job.next_retry_at,
            job.error_code,
            job.reason_codes,
        )
        for job in store.jobs.values()
    }


def _decisions_snapshot(store: MemoryIngestStore) -> dict[str, tuple]:
    return {
        row.id: (
            row.source_item_id,
            row.revision_hash,
            row.review_type,
            row.decision,
            row.region_scope,
            row.audience_relevance,
            row.reason_codes,
            row.rule_version,
            row.reviewer,
            row.reviewed_at,
            row.memo,
        )
        for row in store.decisions.values()
    }


def _approve(store: MemoryIngestStore, item, **overrides: object):
    params = dict(
        source_item_id=item.id,
        revision_hash=item.revision_hash,
        review_type="relevance",
        decision="approve_ai",
        region_scope="capital",
        audience_relevance=(AXIS_JP_RESIDENTS_IN_KR,),
        rule_version=RULE_VERSION,
        reviewer=REVIEWER,
    )
    params.update(overrides)
    return store.resolve_ingest_review_decision(**params)


class ClassifierApprovePathTests(unittest.TestCase):
    def test_upsert_result_has_no_source_item_id(self) -> None:
        names = {field.name for field in fields(ObservationResult)}
        self.assertNotIn("source_item_id", names)
        self.assertEqual(
            names,
            {
                "input_index",
                "external_key",
                "outcome",
                "duplicate_in_batch",
                "skipped_streak",
            },
        )

    def test_clear_fit_upsert_creates_decision_and_ai(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = _clear_fit()
        self.assertEqual(record.jobs, ())
        self.assertIsNotNone(record.classifier_decision)
        self.assertNotIn("reviewer", record.classifier_decision or {})
        self.assertEqual(
            set(record.classifier_decision or {}),
            CLASSIFIER_DECISION_KEYS,
        )
        results = store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE,
            started.run_id,
            [record],
            Checkpoint.for_rest_page(2),
        )
        self.assertEqual(results[0].outcome, "new")
        item = _item(store)
        self.assertEqual(item.disposition, "target")
        self.assertNotIn("classifier_decision", item.normalized_payload or {})
        self.assertEqual(len(store.decisions), 1)
        decision = next(iter(store.decisions.values()))
        self.assertEqual(decision.decision, "approve_ai")
        self.assertEqual(decision.reviewer, REVIEWER)
        self.assertEqual(len(store.jobs_for_stage(AI_STAGE)), 1)
        self.assertEqual(
            store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint,
            {"page_num": 2},
        )
        claimed = store.claim_processing_jobs("ai_enrichment", worker_id="w")
        self.assertEqual(len(claimed), 1)

    def test_upsert_then_resolve_partial_success_boundary(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = observation_for(
            policy_item("rev", zip_cd="11680", oper_cd="11680")
        )
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        item = _item(store)
        self.assertEqual(store.jobs_for_stage(AI_STAGE), [])
        with self.assertRaises(RpcFailure) as err:
            _approve(store, item, revision_hash=HASH_B)
        self.assertEqual(err.exception.code, "revision_mismatch")
        self.assertEqual(store.jobs_for_stage(AI_STAGE), [])
        self.assertEqual(store.decisions, {})
        self.assertEqual(item.disposition, "region_review_required")
        result = _approve(store, item)
        self.assertEqual(result.decision, "approve_ai")
        self.assertIsNone(result.ai_job_status)
        self.assertEqual(store.jobs_for_stage(AI_STAGE), [])
        self.assertEqual(item.disposition, "region_review_required")

    def test_unclear_and_noncapital_are_not_auto_approved(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        unclear = observation_for(
            policy_item("unclear", zip_cd="11680", oper_cd="11680")
        )
        noncap = observation_for(
            policy_item("noncap", zip_cd="50110", oper_cd="50110")
        )
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE,
            started.run_id,
            [unclear, noncap],
            None,
        )
        self.assertEqual(store.decisions, {})
        self.assertEqual(store.jobs_for_stage(AI_STAGE), [])
        self.assertTrue(store.jobs_for_stage("region_review"))
        noncap_item = store.items[(CANONICAL_POLICY_SOURCE, "noncap")]
        self.assertEqual(noncap_item.disposition, "non_target")
        self.assertIsNone(unclear.classifier_decision)
        self.assertIsNone(noncap.classifier_decision)


class ResolveDecisionTests(unittest.TestCase):
    def test_approve_records_decision_completes_review_and_creates_one_ai(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = observation_for(
            policy_item("rev", zip_cd="11680", oper_cd="11680")
        )
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        item = _item(store)
        self.assertTrue(store.jobs_for_stage("region_review"))
        result = _approve(store, item, review_type="region")
        self.assertEqual(result.decision, "approve_ai")
        self.assertEqual(store.jobs_for_stage(AI_STAGE), [])
        self.assertIsNone(result.ai_job_id)
        self.assertEqual(store.jobs_for_stage("region_review")[0].status, "completed")
        self.assertEqual(item.disposition, "region_review_required")
        claimed = store.claim_processing_jobs("ai_enrichment", worker_id="w")
        self.assertEqual(len(claimed), 0)

    def test_second_approve_does_not_create_another_ai(self) -> None:
        store = MemoryIngestStore()
        _upsert_target_no_job(store)
        item = _item(store)
        first = _approve(store, item)
        second = _approve(store, item)
        self.assertEqual(first.ai_job_id, second.ai_job_id)
        self.assertEqual(len(store.jobs_for_stage(AI_STAGE)), 1)

    def test_reject_cancels_queued_ai_without_failed_or_delete(self) -> None:
        store = MemoryIngestStore()
        _upsert_injected_ai(store)
        item = _item(store)
        ai_id = _ai_job(store).id
        result = store.resolve_ingest_review_decision(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            review_type="relevance",
            decision="reject",
            region_scope="capital",
            audience_relevance=(),
            reason_codes=("rejected_non_target",),
            rule_version=RULE_VERSION,
            reviewer="human:reviewer",
        )
        job = store.jobs[ai_id]
        self.assertEqual(result.ai_job_status, "cancelled")
        self.assertEqual(job.status, "cancelled")
        self.assertIsNone(job.claimed_by)
        self.assertIsNone(job.claim_lease_until)
        self.assertNotEqual(job.status, "failed")
        self.assertIn((CANONICAL_POLICY_SOURCE, "p1"), store.items)
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="w"),
            [],
        )
        self.assertEqual(len(store.runs), 1)

    def test_needs_review_keeps_review_queued_and_blocks_claim(self) -> None:
        store = MemoryIngestStore()
        _upsert_injected_ai(store, key="need")
        item = _item(store)
        result = store.resolve_ingest_review_decision(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            review_type="relevance",
            decision="needs_review",
            region_scope="capital",
            audience_relevance=(AXIS_FOREIGN_RESIDENTS_IN_KR,),
            rule_version=RULE_VERSION,
            reviewer="human:reviewer",
        )
        self.assertEqual(result.review_job_status, "queued")
        self.assertEqual(result.review_job_id is not None, True)
        self.assertEqual(store.jobs[result.review_job_id].processing_stage, RELEVANCE_REVIEW_STAGE)
        self.assertEqual(_ai_job(store).status, "cancelled")
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="w"),
            [],
        )
        self.assertEqual(
            store.claim_processing_jobs(RELEVANCE_REVIEW_STAGE, worker_id="w"),
            [],
        )

    def test_revision_mismatch_and_reject_approve_conflict(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = observation_for(
            policy_item("rev-conflict", zip_cd="11680", oper_cd="11680")
        )
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        item = _item(store)
        with self.assertRaises(RpcFailure) as mismatch:
            _approve(store, item, revision_hash=HASH_B)
        self.assertEqual(mismatch.exception.code, "revision_mismatch")
        store.resolve_ingest_review_decision(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            review_type="relevance",
            decision="reject",
            region_scope="capital",
            rule_version=RULE_VERSION,
            reviewer="human:reviewer",
        )
        with self.assertRaises(RpcFailure) as conflict:
            _approve(store, item)
        self.assertEqual(conflict.exception.code, "decision_conflict")
        self.assertEqual(store.jobs_for_stage(AI_STAGE), [])

    def test_live_claimed_ai_is_rejected_on_reject(self) -> None:
        store = MemoryIngestStore()
        _upsert_injected_ai(store)
        item = _item(store)
        _approve(store, item)
        _enable_ai_claim(store, item)
        claimed = store.claim_processing_jobs(
            "ai_enrichment", worker_id="owner", lease_seconds=300
        )
        self.assertEqual(len(claimed), 1)
        with self.assertRaises(RpcFailure) as err:
            store.resolve_ingest_review_decision(
                source_item_id=item.id,
                revision_hash=item.revision_hash,
                review_type="region",
                decision="reject",
                region_scope="capital",
                rule_version=RULE_VERSION,
                reviewer="human:reviewer",
            )
        self.assertEqual(err.exception.code, "ai_job_claimed")
        self.assertEqual(store.jobs[claimed[0].job_id].status, "claimed")

    def test_approve_rejects_noncapital_scope(self) -> None:
        store = MemoryIngestStore()
        _upsert_target_no_job(store)
        item = _item(store)
        with self.assertRaises(RpcFailure) as err:
            _approve(
                store,
                item,
                region_scope="noncapital",
                audience_relevance=(AXIS_JP_RESIDENTS_IN_KR,),
            )
        self.assertEqual(err.exception.code, "approve_requirements_not_met")

    def test_stale_revision_ai_is_not_claimed(self) -> None:
        store = MemoryIngestStore()
        _upsert_injected_ai(store)
        item = _item(store)
        _approve(store, item)
        ai = _ai_job(store)
        ai.revision_hash = HASH_B
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="w"),
            [],
        )
        self.assertEqual(ai.status, "queued")

    def test_expired_claimed_without_approve_is_not_claimed(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        _upsert_injected_ai(store)
        job = _ai_job(store)
        job.status = "claimed"
        job.claimed_by = "old"
        job.claim_lease_until = clock.now
        clock.advance(1)
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="w"),
            [],
        )


class MappedReviewStageTests(unittest.TestCase):
    def _assert_unmapped_jobs_unchanged(
        self,
        before: dict[str, tuple],
        after: dict[str, tuple],
        mapped_stage: str,
        mapped_status: str,
    ) -> None:
        self.assertEqual(set(after), set(HUMAN_REVIEW_STAGES))
        self.assertEqual(after[mapped_stage][1], mapped_status)
        self.assertEqual(after[mapped_stage][0], before[mapped_stage][0])
        for stage in HUMAN_REVIEW_STAGES:
            if stage == mapped_stage:
                continue
            self.assertEqual(after[stage], before[stage])

    def test_region_approve_completes_only_region_review(self) -> None:
        store = MemoryIngestStore()
        item = _seed_four_review_jobs(store)
        before = _human_jobs(store, item)
        result = _approve(store, item, review_type="region")
        after = _human_jobs(store, item)
        self.assertEqual(result.decision, "approve_ai")
        self._assert_unmapped_jobs_unchanged(before, after, "region_review", "completed")
        self.assertEqual(store.jobs_for_stage(AI_STAGE), [])
        self.assertEqual(item.disposition, "region_review_required")
        claimed = store.claim_processing_jobs("ai_enrichment", worker_id="w")
        self.assertEqual(len(claimed), 0)

    def test_relevance_approve_completes_only_relevance_review(self) -> None:
        store = MemoryIngestStore()
        item = _seed_four_review_jobs(store)
        before = _human_jobs(store, item)
        result = _approve(store, item, review_type="relevance")
        after = _human_jobs(store, item)
        self.assertEqual(result.decision, "approve_ai")
        self._assert_unmapped_jobs_unchanged(
            before, after, RELEVANCE_REVIEW_STAGE, "completed"
        )
        self.assertEqual(before["region_review"][1], "queued")
        self.assertEqual(after["region_review"][1], "queued")

    def test_region_and_relevance_reject_resolve_only_mapped_job(self) -> None:
        for review_type, stage in REVIEW_TYPE_TO_STAGE.items():
            with self.subTest(review_type=review_type):
                store = MemoryIngestStore()
                item = _seed_four_review_jobs(store, key=f"rej-{review_type}")
                before = _human_jobs(store, item)
                result = store.resolve_ingest_review_decision(
                    source_item_id=item.id,
                    revision_hash=item.revision_hash,
                    review_type=review_type,
                    decision="reject",
                    region_scope="capital",
                    audience_relevance=(),
                    reason_codes=("rejected_non_target",),
                    rule_version=RULE_VERSION,
                    reviewer="human:reviewer",
                )
                after = _human_jobs(store, item)
                self.assertEqual(result.decision, "reject")
                self._assert_unmapped_jobs_unchanged(before, after, stage, "completed")
                self.assertEqual(store.jobs_for_stage(AI_STAGE), [])
                self.assertEqual(item.disposition, "non_target")

    def test_needs_review_keeps_only_mapped_stage_queued(self) -> None:
        for review_type, stage in REVIEW_TYPE_TO_STAGE.items():
            with self.subTest(review_type=review_type):
                store = MemoryIngestStore()
                item = _seed_four_review_jobs(store, key=f"need-{review_type}")
                before = _human_jobs(store, item)
                result = store.resolve_ingest_review_decision(
                    source_item_id=item.id,
                    revision_hash=item.revision_hash,
                    review_type=review_type,
                    decision="needs_review",
                    region_scope="capital",
                    audience_relevance=(AXIS_FOREIGN_RESIDENTS_IN_KR,),
                    rule_version=RULE_VERSION,
                    reviewer="human:reviewer",
                )
                after = _human_jobs(store, item)
                self.assertEqual(result.review_job_status, "queued")
                self.assertEqual(result.review_job_id, before[stage][0])
                self._assert_unmapped_jobs_unchanged(before, after, stage, "queued")
                self.assertEqual(after[stage], before[stage])

    def test_ai_idempotency_and_claim_gate_stay_on_mapped_approve(self) -> None:
        store = MemoryIngestStore()
        item = _seed_four_review_jobs(store, key="idemp-map")
        first = _approve(store, item, review_type="region")
        second = _approve(store, item, review_type="region")
        self.assertEqual(first.decision_id, second.decision_id)
        self.assertIsNone(first.ai_job_id)
        self.assertIsNone(second.ai_job_id)
        self.assertEqual(store.jobs_for_stage(AI_STAGE), [])
        relevance = _approve(store, item, review_type="relevance")
        self.assertIsNone(relevance.ai_job_id)
        after = _human_jobs(store, item)
        self.assertEqual(after["region_review"][1], "completed")
        self.assertEqual(after[RELEVANCE_REVIEW_STAGE][1], "completed")
        self.assertEqual(after["content_review"][1], "queued")
        self.assertEqual(after["relationship_review"][1], "queued")
        self.assertEqual(item.disposition, "region_review_required")
        claimed = store.claim_processing_jobs("ai_enrichment", worker_id="w")
        self.assertEqual(len(claimed), 0)

    def test_unsupported_review_type_fails_closed(self) -> None:
        store = MemoryIngestStore()
        item = _seed_four_review_jobs(store, key="closed")
        before = _human_jobs(store, item)
        with self.assertRaises(RpcFailure) as err:
            store.resolve_ingest_review_decision(
                source_item_id=item.id,
                revision_hash=item.revision_hash,
                review_type="relationship",
                decision="approve_ai",
                region_scope="capital",
                audience_relevance=(AXIS_JP_RESIDENTS_IN_KR,),
                rule_version=RULE_VERSION,
                reviewer="human:reviewer",
            )
        self.assertEqual(err.exception.code, "invalid_review_type")
        self.assertEqual(_human_jobs(store, item), before)
        self.assertEqual(store.jobs_for_stage(AI_STAGE), [])
        self.assertEqual(store.decisions, {})


class ClaimGateBlockingReviewTests(unittest.TestCase):
    def test_approve_with_region_review_queued_is_not_claimed(self) -> None:
        store = MemoryIngestStore()
        item = _seed_approved_target_ai(store, "blk-region")
        _insert_review_job(store, item, "region_review")
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_approve_with_relevance_review_queued_is_not_claimed(self) -> None:
        store = MemoryIngestStore()
        item = _seed_approved_target_ai(store, "blk-rel")
        _insert_review_job(store, item, RELEVANCE_REVIEW_STAGE)
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_approve_with_content_review_queued_is_not_claimed(self) -> None:
        store = MemoryIngestStore()
        item = _seed_approved_target_ai(store, "blk-content")
        _insert_review_job(store, item, "content_review")
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_relationship_review_only_queued_is_claimed(self) -> None:
        store = MemoryIngestStore()
        item = _seed_approved_target_ai(store, "relship")
        _insert_review_job(store, item, "relationship_review")
        claimed = store.claim_processing_jobs("ai_enrichment", worker_id="w")
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].job_id, _ai_job(store).id)

    def test_region_resolved_relevance_open_is_not_claimed(self) -> None:
        store = MemoryIngestStore()
        item = _seed_approved_target_ai(store, "reg-done")
        _insert_review_job(store, item, "region_review", status="completed")
        _insert_review_job(store, item, RELEVANCE_REVIEW_STAGE)
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_relevance_resolved_region_open_is_not_claimed(self) -> None:
        store = MemoryIngestStore()
        item = _seed_approved_target_ai(store, "rel-done")
        _insert_review_job(store, item, RELEVANCE_REVIEW_STAGE, status="completed")
        _insert_review_job(store, item, "region_review")
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_all_blocking_reviews_resolved_is_claimed(self) -> None:
        store = MemoryIngestStore()
        item = _seed_approved_target_ai(store, "all-done")
        _insert_review_job(store, item, "region_review", status="completed")
        _insert_review_job(store, item, RELEVANCE_REVIEW_STAGE, status="failed")
        _insert_review_job(store, item, "content_review", status="cancelled")
        _insert_review_job(store, item, "relationship_review")
        claimed = store.claim_processing_jobs("ai_enrichment", worker_id="w")
        self.assertEqual(len(claimed), 1)

    def test_non_target_dispositions_are_not_claimed(self) -> None:
        for disposition in ("non_target", "observe_only", "attachment_dependent"):
            with self.subTest(disposition=disposition):
                store = MemoryIngestStore()
                item = _seed_approved_target_ai(store, f"disp-{disposition}")
                item.disposition = disposition
                self.assertEqual(
                    store.claim_processing_jobs("ai_enrichment", worker_id="w"),
                    [],
                )

    def test_unusable_body_or_missing_url_is_not_claimed(self) -> None:
        store = MemoryIngestStore()
        item = _seed_approved_target_ai(store, "body")
        item.body_usable = False
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])
        item.body_usable = True
        item.has_source_url = False
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_stale_revision_is_not_claimed(self) -> None:
        store = MemoryIngestStore()
        _seed_approved_target_ai(store, "stale")
        ai = _ai_job(store)
        ai.revision_hash = HASH_B
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])
        self.assertEqual(ai.status, "queued")

    def test_missing_approve_decision_is_not_claimed(self) -> None:
        store = MemoryIngestStore()
        _upsert_injected_ai(store, key="no-dec")
        item = _item(store)
        _enable_ai_claim(store, item)
        self.assertEqual(store.decisions, {})
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_cancelled_ai_is_not_claimed(self) -> None:
        store = MemoryIngestStore()
        _seed_approved_target_ai(store, "cancel-ai")
        ai = _ai_job(store)
        ai.status = "cancelled"
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])


class ReconcileQueuedAiTests(unittest.TestCase):
    def test_keep_with_approve_keeps_single_ai(self) -> None:
        store = MemoryIngestStore()
        _upsert_injected_ai(store)
        job = _ai_job(store)
        item = _item(store)
        result = store.reconcile_queued_ai_job(
            job.id,
            action="keep_with_approve",
            review_type="relevance",
            region_scope="capital",
            audience_relevance=(AXIS_JP_RESIDENTS_IN_KR,),
            rule_version=RULE_VERSION,
            reviewer="human:reconcile",
        )
        self.assertEqual(result.action_result, "keep_with_approve")
        self.assertEqual(result.ai_job_id, job.id)
        self.assertEqual(job.status, "queued")
        self.assertEqual(len(store.jobs_for_stage(AI_STAGE)), 1)
        self.assertEqual(len(store.claim_processing_jobs("ai_enrichment", worker_id="w")), 0)

    def test_cancel_unfit_cancels_without_failed_or_delete(self) -> None:
        store = MemoryIngestStore()
        _upsert_injected_ai(store)
        job = _ai_job(store)
        result = store.reconcile_queued_ai_job(
            job.id,
            action="cancel_unfit",
            review_type="relevance",
            region_scope="capital",
            rule_version=RULE_VERSION,
            reviewer="human:reconcile",
        )
        self.assertEqual(result.action_result, "cancel_unfit")
        self.assertEqual(job.status, "cancelled")
        self.assertIn("reconcile_unfit", job.reason_codes)
        self.assertNotEqual(job.status, "failed")
        self.assertEqual(list(store.items), [(CANONICAL_POLICY_SOURCE, "p1")])
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_move_to_review_cancels_ai_and_queues_review(self) -> None:
        store = MemoryIngestStore()
        _upsert_injected_ai(store)
        job = _ai_job(store)
        result = store.reconcile_queued_ai_job(
            job.id,
            action="move_to_review",
            review_type="relevance",
            region_scope="unknown",
            rule_version=RULE_VERSION,
            reviewer="human:reconcile",
        )
        self.assertEqual(result.action_result, "move_to_review")
        self.assertEqual(job.status, "cancelled")
        self.assertEqual(result.review_job_status, "queued")
        self.assertEqual(
            store.jobs[result.review_job_id].processing_stage,
            RELEVANCE_REVIEW_STAGE,
        )
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_completed_and_live_claimed_are_rejected(self) -> None:
        store = MemoryIngestStore()
        _upsert_injected_ai(store)
        item = _item(store)
        _approve(store, item)
        _enable_ai_claim(store, item)
        job = _ai_job(store)
        claimed = store.claim_processing_jobs(
            "ai_enrichment", worker_id="owner", lease_seconds=300
        )[0]
        with self.assertRaises(RpcFailure) as live:
            store.reconcile_queued_ai_job(
                claimed.job_id,
                action="cancel_unfit",
                review_type="relevance",
                region_scope="capital",
                rule_version=RULE_VERSION,
                reviewer="human:reconcile",
            )
        self.assertEqual(live.exception.code, "ai_job_claimed")
        store.complete_processing_job(claimed.job_id, worker_id="owner")
        with self.assertRaises(RpcFailure) as done:
            store.reconcile_queued_ai_job(
                claimed.job_id,
                action="keep_with_approve",
                review_type="relevance",
                region_scope="capital",
                audience_relevance=(AXIS_JP_RESIDENTS_IN_KR,),
                rule_version=RULE_VERSION,
                reviewer="human:reconcile",
            )
        self.assertEqual(done.exception.code, "completed_job_not_reconcileable")
        self.assertEqual(store.jobs[job.id].status, "completed")

    def test_revision_mismatch_job_is_rejected(self) -> None:
        store = MemoryIngestStore()
        _upsert_injected_ai(store)
        job = _ai_job(store)
        job.revision_hash = HASH_B
        with self.assertRaises(RpcFailure) as err:
            store.reconcile_queued_ai_job(
                job.id,
                action="cancel_unfit",
                review_type="relevance",
                region_scope="capital",
                rule_version=RULE_VERSION,
                reviewer="human:reconcile",
            )
        self.assertEqual(err.exception.code, "revision_mismatch")
        self.assertEqual(job.status, "queued")


class UpsertSourceObservationsV2Tests(unittest.TestCase):
    def test_changed_clear_target_creates_new_revision_decision_and_ai(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        first = _clear_fit("chg")
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [first], None
        )
        first_item = store.items[(CANONICAL_POLICY_SOURCE, "chg")]
        first_hash = first_item.revision_hash
        first_ai = _ai_job(store).id
        second = _clear_fit("chg", title="정책 개정본")
        self.assertNotEqual(second.revision_hash, first_hash)
        results = store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [second], None
        )
        self.assertEqual(results[0].outcome, "changed")
        item = store.items[(CANONICAL_POLICY_SOURCE, "chg")]
        self.assertEqual(item.revision_hash, second.revision_hash)
        current = [
            row
            for row in store.decisions.values()
            if row.revision_hash == second.revision_hash
        ]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].decision, "approve_ai")
        ais = [
            job
            for job in store.jobs.values()
            if job.processing_stage == AI_STAGE
            and job.revision_hash == second.revision_hash
        ]
        self.assertEqual(len(ais), 1)
        self.assertNotEqual(ais[0].id, first_ai)

    def test_duplicate_does_not_add_decision_or_job(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = _clear_fit("dup")
        results = store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE,
            started.run_id,
            [record, record],
            None,
        )
        self.assertEqual(results[0].outcome, "new")
        self.assertTrue(results[1].duplicate_in_batch)
        self.assertEqual(len(store.decisions), 1)
        self.assertEqual(len(store.jobs_for_stage(AI_STAGE)), 1)

    def test_unchanged_rerun_does_not_add_auto_approve(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = _clear_fit("same")
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        decision_ids = {row.id for row in store.decisions.values()}
        job_ids = {job.id for job in store.jobs_for_stage(AI_STAGE)}
        results = store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        self.assertEqual(results[0].outcome, "unchanged")
        self.assertEqual({row.id for row in store.decisions.values()}, decision_ids)
        self.assertEqual({job.id for job in store.jobs_for_stage(AI_STAGE)}, job_ids)

    def test_invalid_or_missing_classifier_metadata_rolls_back(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        checkpoint = Checkpoint.for_rest_page(3)
        missing = replace(_clear_fit("miss"), classifier_decision=None)
        with self.assertRaises(RpcFailure) as err:
            store.upsert_source_observations(
                CANONICAL_POLICY_SOURCE, started.run_id, [missing], checkpoint
            )
        self.assertEqual(err.exception.code, "classifier_metadata_required")
        self.assertEqual(store.items, {})
        self.assertEqual(store.jobs, {})
        self.assertEqual(store.decisions, {})
        self.assertIsNone(store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint)

        invalid = replace(
            _clear_fit("bad"),
            classifier_decision={
                "decision": "approve_ai",
                "review_type": "relevance",
                "region_scope": "capital",
                "audience_relevance": (AXIS_JP_RESIDENTS_IN_KR,),
                "reason_codes": (),
                "rule_version": RULE_VERSION,
                "reviewer": "client",
            },
        )
        with self.assertRaises(RpcFailure) as extra:
            store.upsert_source_observations(
                CANONICAL_POLICY_SOURCE, started.run_id, [invalid], checkpoint
            )
        self.assertEqual(extra.exception.code, "invalid_classifier_decision")
        self.assertEqual(store.items, {})
        self.assertEqual(store.decisions, {})

    def test_bad_region_relevance_and_rule_version_roll_back(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        base = _clear_fit("gate")
        meta = dict(base.classifier_decision or {})
        cases = (
            ({**meta, "region_scope": "noncapital"}, "invalid_region_scope"),
            ({**meta, "audience_relevance": ("not_an_axis",)}, "invalid_audience_relevance"),
            ({**meta, "rule_version": ""}, "invalid_rule_version"),
        )
        for payload, code in cases:
            with self.subTest(code=code):
                record = replace(base, classifier_decision=payload)
                with self.assertRaises(RpcFailure) as err:
                    store.upsert_source_observations(
                        CANONICAL_POLICY_SOURCE, started.run_id, [record], None
                    )
                self.assertEqual(err.exception.code, code)
                self.assertEqual(store.items, {})
                self.assertEqual(store.jobs, {})
                self.assertEqual(store.decisions, {})

    def test_direct_ai_job_in_upsert_is_rejected(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = replace(
            observation_for(policy_item("ai", zip_cd="11680", oper_cd="11680")),
            disposition="target",
            jobs=(JobPlan(stage="ai_enrichment"),),
            classifier_decision={
                "decision": "approve_ai",
                "review_type": "relevance",
                "region_scope": "capital",
                "audience_relevance": [AXIS_JP_RESIDENTS_IN_KR],
                "reason_codes": [],
                "rule_version": RULE_VERSION,
            },
        )
        with self.assertRaises(RpcFailure) as err:
            store.upsert_source_observations(
                CANONICAL_POLICY_SOURCE, started.run_id, [record], None
            )
        self.assertEqual(err.exception.code, "ai_job_not_allowed_in_upsert")
        self.assertEqual(store.items, {})
        self.assertEqual(store.jobs, {})
        self.assertEqual(store.decisions, {})

    def test_core_forced_error_keeps_state_unchanged(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        store._fail_decision_core = True
        record = _clear_fit("core")
        with self.assertRaises(RpcFailure) as err:
            store.upsert_source_observations(
                CANONICAL_POLICY_SOURCE,
                started.run_id,
                [record],
                Checkpoint.for_rest_page(4),
            )
        self.assertEqual(err.exception.code, "decision_conflict")
        self.assertEqual(store.items, {})
        self.assertEqual(store.jobs, {})
        self.assertEqual(store.decisions, {})
        self.assertIsNone(store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint)
        self.assertEqual(store.runs[started.run_id].batches_ok, 0)

    def test_core_error_restores_existing_nested_item_state(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = replace(
            observation_for(policy_item("keep", zip_cd="11680", oper_cd="11680")),
            relationships=(
                RelationshipPlan(
                    to_source_id=CANONICAL_CONTENT_SOURCE,
                    to_external_key="keep-rel",
                ),
            ),
        )
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE,
            started.run_id,
            [record],
            Checkpoint.for_rest_page(4),
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "keep")]
        item.min_fields["nested"] = {"keep": "min"}
        if item.normalized_payload is None:
            raise AssertionError("normalized_payload_required")
        item.normalized_payload["nested"] = {"keep": "payload"}
        before_item = _item_snapshot(item)
        before_jobs = _jobs_snapshot(store)
        before_decisions = _decisions_snapshot(store)
        before_relationships = copy.deepcopy(store.relationships)
        before_checkpoint = copy.deepcopy(
            store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint
        )
        before_batches = store.runs[started.run_id].batches_ok
        store._fail_decision_core = True
        with self.assertRaises(RpcFailure) as err:
            store.upsert_source_observations(
                CANONICAL_POLICY_SOURCE,
                started.run_id,
                [record, _clear_fit("core-nested")],
                Checkpoint.for_rest_page(9),
            )
        self.assertEqual(err.exception.code, "decision_conflict")
        restored = store.items[(CANONICAL_POLICY_SOURCE, "keep")]
        self.assertEqual(_item_snapshot(restored), before_item)
        self.assertEqual(restored.min_fields, before_item["min_fields"])
        self.assertEqual(
            restored.normalized_payload, before_item["normalized_payload"]
        )
        self.assertEqual(_jobs_snapshot(store), before_jobs)
        self.assertEqual(_decisions_snapshot(store), before_decisions)
        self.assertEqual(store.relationships, before_relationships)
        self.assertEqual(
            store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint,
            before_checkpoint,
        )
        self.assertEqual(store.runs[started.run_id].batches_ok, before_batches)
        self.assertNotIn((CANONICAL_POLICY_SOURCE, "core-nested"), store.items)

    def test_metadata_on_non_target_is_rejected(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = replace(
            observation_for(policy_item("extra", zip_cd="50110", oper_cd="50110")),
            classifier_decision={
                "decision": "approve_ai",
                "review_type": "relevance",
                "region_scope": "capital",
                "audience_relevance": [AXIS_JP_RESIDENTS_IN_KR],
                "reason_codes": [],
                "rule_version": RULE_VERSION,
            },
        )
        with self.assertRaises(RpcFailure) as err:
            store.upsert_source_observations(
                CANONICAL_POLICY_SOURCE, started.run_id, [record], None
            )
        self.assertEqual(err.exception.code, "classifier_metadata_forbidden")
        self.assertEqual(store.items, {})

    def test_review_unknown_unusable_are_not_auto_approved(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        review = observation_for(
            policy_item("review", zip_cd="11680", oper_cd="11680")
        )
        unknown = observation_for(
            policy_item("unk", zip_cd="", oper_cd="", group="0000000")
        )
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [review, unknown], None
        )
        self.assertEqual(store.decisions, {})
        self.assertEqual(store.jobs_for_stage(AI_STAGE), [])
        self.assertTrue(store.jobs_for_stage("region_review"))

    def test_v1_unapproved_ai_is_not_claimed(self) -> None:
        store = MemoryIngestStore()
        _upsert_injected_ai(store, key="legacy")
        self.assertEqual(len(store.jobs_for_stage(AI_STAGE)), 1)
        self.assertEqual(store.decisions, {})
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="w"),
            [],
        )

    def test_resolve_reconcile_and_core_are_idempotent(self) -> None:
        store = MemoryIngestStore()
        _upsert_target_no_job(store, key="idemp")
        item = _item(store)
        first = _approve(store, item)
        second = _approve(store, item)
        self.assertEqual(first.decision_id, second.decision_id)
        self.assertEqual(first.ai_job_id, second.ai_job_id)
        other = MemoryIngestStore()
        _upsert_injected_ai(other, key="recon")
        job = next(
            row
            for row in other.jobs.values()
            if row.processing_stage == AI_STAGE
            and row.source_item_id == other.items[(CANONICAL_POLICY_SOURCE, "recon")].id
        )
        keep = other.reconcile_queued_ai_job(
            job.id,
            action="keep_with_approve",
            review_type="relevance",
            region_scope="capital",
            audience_relevance=(AXIS_JP_RESIDENTS_IN_KR,),
            rule_version=RULE_VERSION,
            reviewer="human:reconcile",
        )
        again = other.reconcile_queued_ai_job(
            job.id,
            action="keep_with_approve",
            review_type="relevance",
            region_scope="capital",
            audience_relevance=(AXIS_JP_RESIDENTS_IN_KR,),
            rule_version=RULE_VERSION,
            reviewer="human:reconcile",
        )
        self.assertEqual(keep.ai_job_id, again.ai_job_id)
        self.assertEqual(keep.decision_id, again.decision_id)

    def test_payload_does_not_copy_source_text_into_decision(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = _clear_fit("text")
        payload = record.to_rpc_item()
        self.assertNotIn("classifier_decision", record.normalized_payload or {})
        self.assertNotIn("plain_text", payload["classifier_decision"])
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        item = _item(store)
        self.assertNotIn("classifier_decision", item.min_fields)
        self.assertNotIn("classifier_decision", item.normalized_payload or {})
        decision = next(iter(store.decisions.values()))
        self.assertNotIn(CLEAR_FIT_BODY, decision.reason_codes)


class ReviewDispositionTransitionTests(unittest.TestCase):
    def test_region_only_approve_does_not_promote_or_enqueue_ai(self) -> None:
        store = MemoryIngestStore()
        item = _seed_blocking_pair(store, "region-only")
        _inject_unapproved_ai(store, item)
        before_disp = item.disposition
        before_ai_id = _current_ai(store, item)[0].id
        result = _approve(store, item, review_type="region")
        self.assertEqual(result.decision, "approve_ai")
        self.assertEqual(_current_stage_job(store, item, "region_review").status, "completed")
        self.assertEqual(
            _current_stage_job(store, item, RELEVANCE_REVIEW_STAGE).status, "queued"
        )
        self.assertEqual(item.disposition, before_disp)
        ais = _current_ai(store, item)
        self.assertEqual(len(ais), 1)
        self.assertEqual(ais[0].id, before_ai_id)
        self.assertEqual(ais[0].status, "queued")
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_relevance_only_approve_does_not_promote_or_enqueue_ai(self) -> None:
        store = MemoryIngestStore()
        item = _seed_blocking_pair(store, "rel-only")
        before_disp = item.disposition
        result = _approve(store, item, review_type="relevance")
        self.assertEqual(result.decision, "approve_ai")
        self.assertEqual(
            _current_stage_job(store, item, RELEVANCE_REVIEW_STAGE).status, "completed"
        )
        self.assertEqual(_current_stage_job(store, item, "region_review").status, "queued")
        self.assertEqual(item.disposition, before_disp)
        self.assertEqual(_current_ai(store, item), [])
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_both_approves_promote_and_enqueue_one_claimable_ai(self) -> None:
        store = MemoryIngestStore()
        item = _seed_blocking_pair(store, "both-ok")
        _approve(store, item, review_type="region")
        result = _approve(store, item, review_type="relevance")
        self.assertEqual(item.disposition, "target")
        self.assertEqual(_current_ai(store, item), [])
        self.assertIsNone(result.ai_job_id)
        confirmed = store.resolve_source_item_product_type(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            action="confirm",
            product_type="event_program",
            rule_version="product-type-v1",
            reviewer="human:test",
        )
        ais = _current_ai(store, item)
        self.assertEqual(len(ais), 1)
        self.assertEqual(ais[0].status, "queued")
        self.assertEqual(confirmed.ai_job_id, ais[0].id)
        claimed = store.claim_processing_jobs("ai_enrichment", worker_id="w")
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].job_id, ais[0].id)

    def test_repeat_approve_is_idempotent_and_does_not_duplicate_ai(self) -> None:
        store = MemoryIngestStore()
        item = _seed_blocking_pair(store, "idemp-both")
        first_region = _approve(store, item, review_type="region")
        first_rel = _approve(store, item, review_type="relevance")
        store.resolve_source_item_product_type(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            action="confirm",
            product_type="event_program",
            rule_version="product-type-v1",
            reviewer="human:test",
        )
        second_rel = _approve(store, item, review_type="relevance")
        second_region = _approve(store, item, review_type="region")
        self.assertEqual(first_region.decision_id, second_region.decision_id)
        self.assertEqual(first_rel.decision_id, second_rel.decision_id)
        self.assertEqual(second_rel.ai_job_id, second_region.ai_job_id)
        self.assertEqual(len(_current_ai(store, item)), 1)
        self.assertEqual(item.disposition, "target")

    def test_both_approves_with_unusable_body_do_not_promote(self) -> None:
        store = MemoryIngestStore()
        item = _seed_blocking_pair(store, "unusable")
        item.body_usable = False
        before = item.disposition
        _approve(store, item, review_type="region")
        _approve(store, item, review_type="relevance")
        self.assertEqual(item.disposition, before)
        self.assertNotEqual(item.disposition, "target")
        self.assertEqual(_current_ai(store, item), [])
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_both_approves_without_source_url_do_not_promote(self) -> None:
        store = MemoryIngestStore()
        item = _seed_blocking_pair(store, "no-url")
        item.has_source_url = False
        before = item.disposition
        _approve(store, item, review_type="region")
        _approve(store, item, review_type="relevance")
        self.assertEqual(item.disposition, before)
        self.assertEqual(_current_ai(store, item), [])
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_noncapital_or_unknown_approve_fails_closed(self) -> None:
        for scope in ("noncapital", "unknown"):
            with self.subTest(region_scope=scope):
                store = MemoryIngestStore()
                item = _seed_blocking_pair(store, f"scope-{scope}")
                before_item = _item_snapshot(item)
                before_jobs = _jobs_snapshot(store)
                before_decisions = _decisions_snapshot(store)
                with self.assertRaises(RpcFailure) as err:
                    _approve(store, item, review_type="region", region_scope=scope)
                self.assertEqual(err.exception.code, "approve_requirements_not_met")
                restored = store.items[(CANONICAL_POLICY_SOURCE, f"scope-{scope}")]
                self.assertEqual(_item_snapshot(restored), before_item)
                self.assertEqual(_jobs_snapshot(store), before_jobs)
                self.assertEqual(_decisions_snapshot(store), before_decisions)
                self.assertEqual(_current_ai(store, restored), [])
                self.assertEqual(
                    store.claim_processing_jobs("ai_enrichment", worker_id="w"),
                    [],
                )

    def test_reject_sets_non_target_cancels_ai_and_keeps_lineage(self) -> None:
        for label, expire_claim in (("queued", False), ("expired_claimed", True)):
            with self.subTest(ai=label):
                clock = Clock()
                store = MemoryIngestStore(clock=clock)
                item = _seed_blocking_pair(store, f"rej-{label}")
                _inject_unapproved_ai(store, item)
                ai = _current_ai(store, item)[0]
                if expire_claim:
                    ai.status = "claimed"
                    ai.claimed_by = "old"
                    ai.claim_lease_until = clock.now
                    clock.advance(1)
                before_item_id = item.id
                before_runs = dict(store.runs)
                result = store.resolve_ingest_review_decision(
                    source_item_id=item.id,
                    revision_hash=item.revision_hash,
                    review_type="region",
                    decision="reject",
                    region_scope="capital",
                    audience_relevance=(),
                    reason_codes=("rejected_non_target",),
                    rule_version=RULE_VERSION,
                    reviewer="human:reviewer",
                )
                self.assertEqual(result.decision, "reject")
                self.assertEqual(
                    _current_stage_job(store, item, "region_review").status, "completed"
                )
                self.assertEqual(
                    _current_stage_job(store, item, RELEVANCE_REVIEW_STAGE).status,
                    "queued",
                )
                self.assertEqual(item.disposition, "non_target")
                self.assertEqual(store.jobs[ai.id].status, "cancelled")
                self.assertNotEqual(store.jobs[ai.id].status, "failed")
                self.assertIn((CANONICAL_POLICY_SOURCE, f"rej-{label}"), store.items)
                self.assertEqual(
                    store.items[(CANONICAL_POLICY_SOURCE, f"rej-{label}")].id,
                    before_item_id,
                )
                self.assertEqual(
                    list(store.decisions),
                    [(item.id, item.revision_hash, "region")],
                )
                self.assertEqual(store.runs, before_runs)
                self.assertEqual(
                    store.claim_processing_jobs("ai_enrichment", worker_id="w"),
                    [],
                )

    def test_needs_review_keeps_disposition_and_queued_review(self) -> None:
        store = MemoryIngestStore()
        item = _seed_blocking_pair(store, "need")
        before = item.disposition
        result = store.resolve_ingest_review_decision(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            review_type="relevance",
            decision="needs_review",
            region_scope="capital",
            audience_relevance=(AXIS_FOREIGN_RESIDENTS_IN_KR,),
            rule_version=RULE_VERSION,
            reviewer="human:reviewer",
        )
        self.assertEqual(result.review_job_status, "queued")
        self.assertEqual(
            _current_stage_job(store, item, RELEVANCE_REVIEW_STAGE).status, "queued"
        )
        self.assertEqual(item.disposition, before)
        self.assertEqual(_current_ai(store, item), [])
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_relationship_review_only_does_not_block_promotion_or_claim(self) -> None:
        store = MemoryIngestStore()
        item = _seed_blocking_pair(store, "relship-only")
        _insert_review_job(store, item, "relationship_review")
        _approve(store, item, review_type="region")
        _approve(store, item, review_type="relevance")
        self.assertEqual(item.disposition, "target")
        self.assertEqual(
            _current_stage_job(store, item, "relationship_review").status, "queued"
        )
        store.resolve_source_item_product_type(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            action="confirm",
            product_type="event_program",
            rule_version="product-type-v1",
            reviewer="human:test",
        )
        self.assertEqual(len(_current_ai(store, item)), 1)
        self.assertEqual(len(store.claim_processing_jobs("ai_enrichment", worker_id="w")), 1)

    def test_current_content_review_cannot_be_completed_or_promoted(self) -> None:
        for status in ("queued", "claimed"):
            with self.subTest(content_review=status):
                store = MemoryIngestStore()
                item = _seed_blocking_pair(store, f"content-{status}")
                review = _insert_review_job(store, item, "content_review", status=status)
                before = item.disposition
                with self.assertRaises(RpcFailure) as err:
                    store.resolve_ingest_review_decision(
                        source_item_id=item.id,
                        revision_hash=item.revision_hash,
                        review_type="content",
                        decision="approve_ai",
                        region_scope="capital",
                        audience_relevance=(AXIS_JP_RESIDENTS_IN_KR,),
                        rule_version=RULE_VERSION,
                        reviewer="human:reviewer",
                    )
                self.assertEqual(err.exception.code, "invalid_decision")
                _approve(store, item, review_type="region")
                _approve(store, item, review_type="relevance")
                self.assertEqual(item.disposition, before)
                self.assertNotEqual(item.disposition, "target")
                self.assertEqual(store.jobs[review.id].status, status)
                self.assertEqual(_current_ai(store, item), [])
                self.assertEqual(
                    store.claim_processing_jobs("ai_enrichment", worker_id="w"),
                    [],
                )

    def test_new_usable_revision_leaves_old_content_review_stale(self) -> None:
        store = MemoryIngestStore()
        started = store.start_ingest_run(CANONICAL_CONTENT_SOURCE)
        first_raw = load_content()
        first_raw["pstWholCn"] = ""
        first = v3_content_observation(first_raw)
        self.assertEqual(first.jobs[0].stage, "content_review")
        store.upsert_source_observations(
            CANONICAL_CONTENT_SOURCE, started.run_id, [first], None
        )
        item = store.items[(CANONICAL_CONTENT_SOURCE, first.external_key)]
        old_hash = item.revision_hash
        old_jobs = [
            job
            for job in store.jobs.values()
            if job.source_item_id == item.id and job.revision_hash == old_hash
        ]
        self.assertTrue(any(job.processing_stage == "content_review" for job in old_jobs))
        second_raw = load_content()
        second_raw["pstTtl"] = "서울 한일 교류 설명회"
        second_raw["pstWholCn"] = (
            "<p>서울에서 열리는 한일 교류 설명회입니다. "
            "한국 거주 일본인은 참석 가능합니다.</p>"
        )
        second = v3_content_observation(second_raw)
        self.assertEqual(second.external_key, first.external_key)
        self.assertNotEqual(second.revision_hash, old_hash)
        self.assertEqual(second.disposition, "target")
        store.upsert_source_observations(
            CANONICAL_CONTENT_SOURCE, started.run_id, [second], None
        )
        current = store.items[(CANONICAL_CONTENT_SOURCE, first.external_key)]
        self.assertEqual(current.revision_hash, second.revision_hash)
        self.assertEqual(current.disposition, "target")
        stale = [
            job
            for job in store.jobs.values()
            if job.source_item_id == current.id and job.revision_hash == old_hash
        ]
        self.assertEqual({job.id for job in stale}, {job.id for job in old_jobs})
        self.assertTrue(
            all(
                job.status == "queued" and job.processing_stage != "ai_enrichment"
                for job in stale
                if job.processing_stage == "content_review"
            )
        )
        self.assertTrue(
            all(job.status != "completed" for job in stale if job.processing_stage == "content_review")
        )
        self.assertEqual(len(_current_ai(store, current)), 1)
        claimed = store.claim_processing_jobs("ai_enrichment", worker_id="w")
        self.assertEqual(len(claimed), 1)

    def test_stale_revision_resolve_changes_nothing(self) -> None:
        store = MemoryIngestStore()
        item = _seed_blocking_pair(store, "stale-res")
        before_item = _item_snapshot(item)
        before_jobs = _jobs_snapshot(store)
        before_decisions = _decisions_snapshot(store)
        with self.assertRaises(RpcFailure) as err:
            _approve(store, item, revision_hash=HASH_B)
        self.assertEqual(err.exception.code, "revision_mismatch")
        restored = store.items[(CANONICAL_POLICY_SOURCE, "stale-res")]
        self.assertEqual(_item_snapshot(restored), before_item)
        self.assertEqual(_jobs_snapshot(store), before_jobs)
        self.assertEqual(_decisions_snapshot(store), before_decisions)

    def test_decision_core_mid_failure_rolls_back_all_state(self) -> None:
        store = MemoryIngestStore()
        item = _seed_blocking_pair(store, "mid-fail")
        item.min_fields["nested"] = {"keep": "min"}
        if item.normalized_payload is None:
            raise AssertionError("normalized_payload_required")
        item.normalized_payload["nested"] = {"keep": "payload"}
        before_item = _item_snapshot(item)
        before_jobs = _jobs_snapshot(store)
        before_decisions = _decisions_snapshot(store)
        before_relationships = copy.deepcopy(store.relationships)
        before_checkpoint = copy.deepcopy(
            store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint
        )
        before_runs = _run_counters(store)
        store._fail_decision_core_after_mapped = True
        with self.assertRaises(RpcFailure) as err:
            _approve(store, item, review_type="region")
        self.assertEqual(err.exception.code, "decision_conflict")
        restored = store.items[(CANONICAL_POLICY_SOURCE, "mid-fail")]
        self.assertEqual(_item_snapshot(restored), before_item)
        self.assertEqual(restored.min_fields, before_item["min_fields"])
        self.assertEqual(restored.normalized_payload, before_item["normalized_payload"])
        self.assertEqual(_jobs_snapshot(store), before_jobs)
        self.assertEqual(_decisions_snapshot(store), before_decisions)
        self.assertEqual(store.relationships, before_relationships)
        self.assertEqual(
            store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint,
            before_checkpoint,
        )
        self.assertEqual(_run_counters(store), before_runs)

    def test_classifier_v2_clear_target_stays_atomic(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = _clear_fit("v2-atomic")
        results = store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE,
            started.run_id,
            [record],
            Checkpoint.for_rest_page(5),
        )
        self.assertEqual(results[0].outcome, "new")
        item = store.items[(CANONICAL_POLICY_SOURCE, "v2-atomic")]
        self.assertEqual(item.disposition, "target")
        self.assertEqual(len(store.decisions), 1)
        self.assertEqual(len(_current_ai(store, item)), 1)
        self.assertEqual(
            store.sync[CANONICAL_POLICY_SOURCE].committed_checkpoint,
            {"page_num": 5},
        )
        again = store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        self.assertEqual(again[0].outcome, "unchanged")
        self.assertEqual(len(store.decisions), 1)
        self.assertEqual(len(_current_ai(store, item)), 1)
        self.assertEqual(len(store.claim_processing_jobs("ai_enrichment", worker_id="w")), 1)

    def test_claim_gate_still_requires_target_usable_approve_and_blocking_zero(self) -> None:
        store = MemoryIngestStore()
        item = _seed_blocking_pair(store, "gate")
        _approve(store, item, review_type="region")
        _approve(store, item, review_type="relevance")
        store.resolve_source_item_product_type(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            action="confirm",
            product_type="event_program",
            rule_version="product-type-v1",
            reviewer="human:test",
        )
        self.assertEqual(len(store.claim_processing_jobs("ai_enrichment", worker_id="w")), 1)
        other = MemoryIngestStore()
        blocked = _seed_blocking_pair(other, "still-block")
        _approve(other, blocked, review_type="region")
        self.assertEqual(other.claim_processing_jobs("ai_enrichment", worker_id="w"), [])
        rel = MemoryIngestStore()
        rel_item = _seed_blocking_pair(rel, "rel-ok")
        _insert_review_job(rel, rel_item, "relationship_review")
        _approve(rel, rel_item, review_type="region")
        _approve(rel, rel_item, review_type="relevance")
        rel.resolve_source_item_product_type(
            source_item_id=rel_item.id,
            revision_hash=rel_item.revision_hash,
            action="confirm",
            product_type="event_program",
            rule_version="product-type-v1",
            reviewer="human:test",
        )
        self.assertEqual(len(rel.claim_processing_jobs("ai_enrichment", worker_id="w")), 1)


class PermissionPublicationGuardTests(unittest.TestCase):
    def test_resolve_does_not_touch_permission_or_publication(self) -> None:
        store = MemoryIngestStore()
        _upsert_target_no_job(store)
        pubs = list(store.publications)
        events = list(store.publication_events)
        perms = list(store.permission_events)
        _approve(store, _item(store))
        self.assertEqual(store.publications, pubs)
        self.assertEqual(store.publication_events, events)
        self.assertEqual(store.permission_events, perms)


if __name__ == "__main__":
    unittest.main()
