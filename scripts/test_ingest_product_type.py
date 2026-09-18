"""product_type value/stage split, writers, human matrix, AI gates, and lease equality."""

from __future__ import annotations

import unittest
from ingest.models import PRODUCT_TYPE_REVIEW_STAGE, ProductTypeResult
from ingest.product_type import (
    PRODUCT_TYPE_EVENT_PROGRAM,
    PRODUCT_TYPE_KIND_CONFIRMED,
    PRODUCT_TYPE_KIND_REVIEW,
    PRODUCT_TYPE_ORIGIN_CLASSIFIER,
    PRODUCT_TYPE_ORIGIN_HUMAN,
    PRODUCT_TYPE_POLICY_REFERENCE,
    PRODUCT_TYPE_RULE_VERSION,
    REASON_CONTENT_FIXED,
    REASON_END_DATE_ABSENT,
    REASON_POLICY_CONFLICT,
    classify_content_product_type,
    classify_policy_product_type,
)
from ingest.rpc_errors import RpcFailure
from ingest.source_identity import CANONICAL_CONTENT_SOURCE, CANONICAL_POLICY_SOURCE
from ingest.store import MemoryIngestStore
from test_ingest import Clock, load_content, observation_for, policy_item
from test_ingest_review_decision import (
    _approve,
    _clear_fit,
    _current_ai,
    _item,
    _seed_blocking_pair,
    _start,
)

REVIEWER = "human:product-type"


def _confirm(store: MemoryIngestStore, item, product_type: str, **overrides: object):
    params = dict(
        source_item_id=item.id,
        revision_hash=item.revision_hash,
        action="confirm",
        product_type=product_type,
        rule_version=PRODUCT_TYPE_RULE_VERSION,
        reviewer=REVIEWER,
    )
    params.update(overrides)
    return store.resolve_source_item_product_type(**params)


def _override(store: MemoryIngestStore, item, product_type: str, **overrides: object):
    params = dict(
        source_item_id=item.id,
        revision_hash=item.revision_hash,
        action="override",
        product_type=product_type,
        rule_version=PRODUCT_TYPE_RULE_VERSION,
        reviewer=REVIEWER,
        memo="override memo",
    )
    params.update(overrides)
    return store.resolve_source_item_product_type(**params)


def _rollback(store: MemoryIngestStore, item, **overrides: object):
    params = dict(
        source_item_id=item.id,
        revision_hash=item.revision_hash,
        action="rollback",
        rule_version=PRODUCT_TYPE_RULE_VERSION,
        reviewer=REVIEWER,
        memo="rollback memo",
    )
    params.update(overrides)
    return store.resolve_source_item_product_type(**params)


def _product_type_row(store: MemoryIngestStore, item):
    return store.product_types.get((item.id, item.revision_hash))


def _review_jobs(store: MemoryIngestStore, item):
    return [
        job
        for job in store.jobs.values()
        if job.source_item_id == item.id
        and job.revision_hash == item.revision_hash
        and job.processing_stage == PRODUCT_TYPE_REVIEW_STAGE
    ]


class ProductTypeValueAndClassifierTests(unittest.TestCase):
    def test_confirmed_values_exclude_review_stage(self) -> None:
        self.assertEqual(
            classify_content_product_type().product_type,
            PRODUCT_TYPE_EVENT_PROGRAM,
        )
        self.assertNotEqual(PRODUCT_TYPE_REVIEW_STAGE, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertNotEqual(PRODUCT_TYPE_REVIEW_STAGE, PRODUCT_TYPE_POLICY_REFERENCE)
        payload = classify_content_product_type().to_payload()
        self.assertNotIn(PRODUCT_TYPE_REVIEW_STAGE, payload.values())
        self.assertEqual(payload["reason_codes"], [REASON_CONTENT_FIXED])

    def test_policy_lifecycle_and_content_lock_in_classifier(self) -> None:
        event = classify_policy_product_type("이번 회차 신청과 개최 안내입니다.")
        standing = classify_policy_product_type("상시 지원 자격과 이용 방법입니다.")
        mixed = classify_policy_product_type("상시 지원이며 이번 회차 신청이 가능합니다.")
        absent = classify_policy_product_type("종료일 없음")
        unclear = classify_policy_product_type("설명입니다. 본문이 충분히 있습니다.")
        self.assertEqual(event.kind, PRODUCT_TYPE_KIND_CONFIRMED)
        self.assertEqual(event.product_type, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(standing.product_type, PRODUCT_TYPE_POLICY_REFERENCE)
        self.assertEqual(mixed.kind, PRODUCT_TYPE_KIND_REVIEW)
        self.assertIn(REASON_POLICY_CONFLICT, mixed.reason_codes)
        self.assertEqual(absent.kind, PRODUCT_TYPE_KIND_REVIEW)
        self.assertIn(REASON_END_DATE_ABSENT, absent.reason_codes)
        self.assertEqual(unclear.kind, PRODUCT_TYPE_KIND_REVIEW)
        self.assertIsNone(unclear.product_type)
        content = classify_content_product_type()
        self.assertEqual(content.product_type, PRODUCT_TYPE_EVENT_PROGRAM)

    def test_content_target_upsert_inserts_event_program(self) -> None:
        store = MemoryIngestStore()
        started = store.start_ingest_run(CANONICAL_CONTENT_SOURCE)
        from ingest.connectors.youthcenter_content import YouthcenterContentConnector

        raw = load_content()
        raw["pstTtl"] = "서울 한일 교류 설명회"
        raw["pstWholCn"] = (
            "<p>서울에서 열리는 한일 교류 설명회입니다. "
            "한국 거주 일본인은 참석 가능합니다.</p>"
        )
        record = YouthcenterContentConnector(
            api_key_provider=lambda: "unused"
        ).to_observation(raw, permission_status="testing_only", enabled=True)
        self.assertEqual(record.disposition, "target")
        self.assertEqual(
            record.product_type_classification["product_type"],
            PRODUCT_TYPE_EVENT_PROGRAM,
        )
        store.upsert_source_observations(
            CANONICAL_CONTENT_SOURCE, started.run_id, [record], None
        )
        item = store.items[(CANONICAL_CONTENT_SOURCE, record.external_key)]
        row = _product_type_row(store, item)
        self.assertIsNotNone(row)
        self.assertEqual(row.product_type, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(row.origin, PRODUCT_TYPE_ORIGIN_CLASSIFIER)
        self.assertEqual(_review_jobs(store, item), [])
        self.assertEqual(len(_current_ai(store, item)), 1)

    def test_policy_uncertain_has_review_job_not_row(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = observation_for(
            policy_item(
                "mixed",
                zip_cd="11680",
                oper_cd="11680",
                plcyExplnCn="재한 일본인은 상시 지원이며 이번 회차 신청이 가능합니다.",
                plcySprtCn="재한 일본인은 상시 지원이며 이번 회차 신청이 가능합니다.",
            )
        )
        self.assertEqual(record.disposition, "target")
        self.assertEqual(record.product_type_classification["kind"], PRODUCT_TYPE_KIND_REVIEW)
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "mixed")]
        self.assertIsNone(_product_type_row(store, item))
        reviews = _review_jobs(store, item)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].status, "queued")
        self.assertEqual(_current_ai(store, item), [])
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])

    def test_existing_revision_unchanged_is_fail_closed(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = observation_for(
            policy_item("old", zip_cd="11680", oper_cd="11680")
        )
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "old")]
        self.assertEqual(item.disposition, "region_review_required")
        self.assertIsNone(_product_type_row(store, item))
        self.assertEqual(_review_jobs(store, item), [])
        again = store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        self.assertEqual(again[0].outcome, "unchanged")
        self.assertIsNone(_product_type_row(store, item))
        self.assertEqual(_review_jobs(store, item), [])
        self.assertEqual(store.claim_processing_jobs("ai_enrichment", worker_id="w"), [])


class ProductTypeWriterAndHumanMatrixTests(unittest.TestCase):
    def test_classifier_does_not_update_existing_row(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        first = _clear_fit("keep")
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [first], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "keep")]
        row = _product_type_row(store, item)
        self.assertEqual(row.product_type, PRODUCT_TYPE_EVENT_PROGRAM)
        _override(store, item, PRODUCT_TYPE_POLICY_REFERENCE)
        self.assertEqual(
            _product_type_row(store, item).origin, PRODUCT_TYPE_ORIGIN_HUMAN
        )
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [first], None
        )
        kept = _product_type_row(store, item)
        self.assertEqual(kept.product_type, PRODUCT_TYPE_POLICY_REFERENCE)
        self.assertEqual(kept.origin, PRODUCT_TYPE_ORIGIN_HUMAN)

    def test_new_revision_does_not_update_old_hash_row(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        first = _clear_fit("rev")
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [first], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "rev")]
        old_hash = item.revision_hash
        old_row = store.product_types[(item.id, old_hash)]
        second = _clear_fit("rev", title="다른 제목 신청")
        self.assertNotEqual(second.revision_hash, old_hash)
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [second], None
        )
        self.assertEqual(store.product_types[(item.id, old_hash)].product_type, old_row.product_type)
        self.assertIn((item.id, second.revision_hash), store.product_types)

    def test_confirm_override_rollback_matrix(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = observation_for(
            policy_item(
                "mx",
                zip_cd="11680",
                oper_cd="11680",
                plcyExplnCn="재한 일본인은 상시 지원이며 이번 회차 신청이 가능합니다.",
                plcySprtCn="재한 일본인은 상시 지원이며 이번 회차 신청이 가능합니다.",
            )
        )
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "mx")]
        self.assertIsNone(_product_type_row(store, item))
        with self.assertRaises(RpcFailure) as missing:
            _override(store, item, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(missing.exception.code, "decision_conflict")
        noop_rb = _rollback(store, item, memo=None)
        self.assertEqual(noop_rb.action_result, "no-op")
        self.assertEqual(_review_jobs(store, item)[0].status, "queued")
        confirmed = _confirm(store, item, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(confirmed.action_result, "confirmed")
        self.assertEqual(confirmed.origin, PRODUCT_TYPE_ORIGIN_HUMAN)
        self.assertEqual(_review_jobs(store, item)[0].status, "completed")
        same = _confirm(store, item, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(same.action_result, "no-op")
        with self.assertRaises(RpcFailure) as conflict:
            _confirm(store, item, PRODUCT_TYPE_POLICY_REFERENCE)
        self.assertEqual(conflict.exception.code, "decision_conflict")
        same_ov = _override(store, item, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(same_ov.action_result, "no-op")
        changed = _override(store, item, PRODUCT_TYPE_POLICY_REFERENCE)
        self.assertEqual(changed.action_result, "overridden")
        self.assertEqual(
            _product_type_row(store, item).product_type,
            PRODUCT_TYPE_POLICY_REFERENCE,
        )
        rolled = _rollback(store, item)
        self.assertEqual(rolled.action_result, "rolled_back")
        self.assertIsNone(_product_type_row(store, item))
        self.assertEqual(_review_jobs(store, item)[0].status, "queued")

    def test_content_lock_before_noop(self) -> None:
        store = MemoryIngestStore()
        started = store.start_ingest_run(CANONICAL_CONTENT_SOURCE)
        from ingest.connectors.youthcenter_content import YouthcenterContentConnector

        raw = load_content()
        raw["pstTtl"] = "서울 한일 교류 설명회"
        raw["pstWholCn"] = (
            "<p>서울에서 열리는 한일 교류 설명회입니다. "
            "한국 거주 일본인은 참석 가능합니다.</p>"
        )
        record = YouthcenterContentConnector(
            api_key_provider=lambda: "unused"
        ).to_observation(raw, permission_status="testing_only", enabled=True)
        store.upsert_source_observations(
            CANONICAL_CONTENT_SOURCE, started.run_id, [record], None
        )
        item = store.items[(CANONICAL_CONTENT_SOURCE, record.external_key)]
        same = _confirm(store, item, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(same.action_result, "no-op")
        for action, product_type in (
            ("confirm", PRODUCT_TYPE_POLICY_REFERENCE),
            ("override", PRODUCT_TYPE_POLICY_REFERENCE),
            ("rollback", None),
        ):
            with self.subTest(action=action):
                with self.assertRaises(RpcFailure) as err:
                    store.resolve_source_item_product_type(
                        source_item_id=item.id,
                        revision_hash=item.revision_hash,
                        action=action,
                        product_type=product_type,
                        rule_version=PRODUCT_TYPE_RULE_VERSION,
                        reviewer=REVIEWER,
                        memo="x",
                    )
                self.assertEqual(err.exception.code, "content_product_type_locked")

    def test_invalid_enum_and_stale_revision_are_not_noop(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [_clear_fit("bad")], None
        )
        item = _item(store)
        with self.assertRaises(RpcFailure) as action_err:
            store.resolve_source_item_product_type(
                source_item_id=item.id,
                revision_hash=item.revision_hash,
                action="approve_ai",
                product_type=PRODUCT_TYPE_EVENT_PROGRAM,
                rule_version=PRODUCT_TYPE_RULE_VERSION,
                reviewer=REVIEWER,
            )
        self.assertEqual(action_err.exception.code, "invalid_product_type_action")
        with self.assertRaises(RpcFailure) as type_err:
            _confirm(store, item, "product_type_review")
        self.assertEqual(type_err.exception.code, "invalid_product_type")
        with self.assertRaises(RpcFailure) as stale:
            _confirm(store, item, PRODUCT_TYPE_EVENT_PROGRAM, revision_hash="b" * 64)
        self.assertEqual(stale.exception.code, "revision_mismatch")

    def test_noop_and_conflict_ignore_live_claimed(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        started = _start(store)
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [_clear_fit("live")], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "live")]
        claimed = store.claim_processing_jobs(
            "ai_enrichment", worker_id="owner", lease_seconds=300
        )
        self.assertEqual(len(claimed), 1)
        noop = _confirm(store, item, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(noop.action_result, "no-op")
        self.assertEqual(store.jobs[claimed[0].job_id].status, "claimed")
        with self.assertRaises(RpcFailure) as conflict:
            _confirm(store, item, PRODUCT_TYPE_POLICY_REFERENCE)
        self.assertEqual(conflict.exception.code, "decision_conflict")
        self.assertEqual(store.jobs[claimed[0].job_id].status, "claimed")
        self.assertEqual(
            _product_type_row(store, item).product_type, PRODUCT_TYPE_EVENT_PROGRAM
        )

    def test_actual_mutation_blocked_by_live_claimed(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [_clear_fit("mut")], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "mut")]
        claimed = store.claim_processing_jobs(
            "ai_enrichment", worker_id="owner", lease_seconds=300
        )
        self.assertEqual(len(claimed), 1)
        with self.assertRaises(RpcFailure) as err:
            _override(store, item, PRODUCT_TYPE_POLICY_REFERENCE)
        self.assertEqual(err.exception.code, "ai_job_claimed")
        self.assertEqual(
            _product_type_row(store, item).product_type, PRODUCT_TYPE_EVENT_PROGRAM
        )


class ProductTypeAiGateTests(unittest.TestCase):
    def test_gate_order_converges_and_exactly_once(self) -> None:
        first = MemoryIngestStore()
        item = _seed_blocking_pair(first, "ord-a")
        _approve(first, item, review_type="region")
        _approve(first, item, review_type="relevance")
        self.assertEqual(_current_ai(first, item), [])
        _confirm(first, item, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(len(_current_ai(first, item)), 1)

        second = MemoryIngestStore()
        item2 = _seed_blocking_pair(second, "ord-b")
        _confirm(second, item2, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(_current_ai(second, item2), [])
        _approve(second, item2, review_type="region")
        _approve(second, item2, review_type="relevance")
        self.assertEqual(len(_current_ai(second, item2)), 1)

    def test_cancelled_and_lease_expired_requeue_same_row(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        started = _start(store)
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [_clear_fit("rq")], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "rq")]
        ai = _current_ai(store, item)[0]
        ai_id = ai.id
        ai.status = "cancelled"
        _override(store, item, PRODUCT_TYPE_POLICY_REFERENCE)
        self.assertEqual(store.jobs[ai_id].status, "queued")
        ai.status = "claimed"
        ai.claimed_by = "old"
        ai.claim_lease_until = clock.now
        _override(store, item, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(store.jobs[ai_id].status, "queued")
        self.assertIsNone(store.jobs[ai_id].claim_lease_until)
        self.assertEqual(len(_current_ai(store, item)), 1)

    def test_queued_completed_failed_live_claimed_and_null_lease(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        started = _start(store)
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [_clear_fit("tr")], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "tr")]
        ai = _current_ai(store, item)[0]
        ai_id = ai.id
        _confirm(store, item, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(store.jobs[ai_id].status, "queued")
        ai.status = "completed"
        _override(store, item, PRODUCT_TYPE_POLICY_REFERENCE)
        self.assertEqual(store.jobs[ai_id].status, "completed")
        self.assertEqual(len(_current_ai(store, item)), 1)
        ai.status = "failed"
        _override(store, item, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(store.jobs[ai_id].status, "failed")
        self.assertEqual(len(_current_ai(store, item)), 1)
        store.jobs[ai_id].status = "queued"
        claimed = store.claim_processing_jobs(
            "ai_enrichment", worker_id="owner", lease_seconds=300
        )
        self.assertEqual(len(claimed), 1)
        with self.assertRaises(RpcFailure) as live:
            _override(store, item, PRODUCT_TYPE_POLICY_REFERENCE)
        self.assertEqual(live.exception.code, "ai_job_claimed")
        store.jobs[ai_id].status = "claimed"
        store.jobs[ai_id].claim_lease_until = None
        with self.assertRaises(RpcFailure) as malformed:
            _override(store, item, PRODUCT_TYPE_POLICY_REFERENCE)
        self.assertEqual(malformed.exception.code, "ai_job_malformed_lease")
        self.assertEqual(store.jobs[ai_id].status, "claimed")
        self.assertIsNone(store.jobs[ai_id].claim_lease_until)

    def test_lease_equal_now_is_expired(self) -> None:
        clock = Clock()
        store = MemoryIngestStore(clock=clock)
        started = _start(store)
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [_clear_fit("eq")], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "eq")]
        ai = _current_ai(store, item)[0]
        ai.status = "claimed"
        ai.claimed_by = "old"
        ai.claim_lease_until = clock.now
        claimed = store.claim_processing_jobs(
            "ai_enrichment", worker_id="w", lease_seconds=300
        )
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].job_id, ai.id)

    def test_partial_failure_rolls_back_revision_product_type_review_and_ai(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        store._fail_after_product_type = True
        record = _clear_fit("boom")
        with self.assertRaises(RpcFailure):
            store.upsert_source_observations(
                CANONICAL_POLICY_SOURCE, started.run_id, [record], None
            )
        self.assertEqual(store.items, {})
        self.assertEqual(store.product_types, {})
        self.assertEqual(store.jobs, {})
        self.assertEqual(store.decisions, {})

    def test_hash_payload_excludes_product_type(self) -> None:
        record = _clear_fit("hash")
        self.assertNotIn("product_type", record.revision_hash)
        self.assertNotIn("product_type", record.min_fields)
        encoded = str(record.to_rpc_item())
        self.assertIn("product_type_classification", encoded)


class ProductTypeConcurrentIdempotencyTests(unittest.TestCase):
    def test_second_confirm_is_noop_not_second_row(self) -> None:
        store = MemoryIngestStore()
        started = _start(store)
        record = observation_for(
            policy_item(
                "uniq",
                zip_cd="11680",
                oper_cd="11680",
                plcyExplnCn="재한 일본인은 상시 지원이며 이번 회차 신청이 가능합니다.",
                plcySprtCn="재한 일본인은 상시 지원이며 이번 회차 신청이 가능합니다.",
            )
        )
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "uniq")]
        first = _confirm(store, item, PRODUCT_TYPE_EVENT_PROGRAM)
        second = _confirm(store, item, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertEqual(first.action_result, "confirmed")
        self.assertEqual(second.action_result, "no-op")
        self.assertEqual(len(store.product_types), 1)
        self.assertIsInstance(first, ProductTypeResult)


if __name__ == "__main__":
    unittest.main()
