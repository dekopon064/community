"""Revision-scoped display category, event period, and AI gate contracts."""

from __future__ import annotations

import copy
import pathlib
import re
import unittest
from datetime import timedelta

from ingest.rpc_errors import RpcFailure
from ingest.application_deadline import APPLICATION_DEADLINE_UNKNOWN
from ingest.source_identity import CANONICAL_POLICY_SOURCE
from ingest.store import MemoryIngestStore
from ingest.supabase_store import (
    RESOLVE_SOURCE_ITEM_USER_CATEGORY,
    SupabaseIngestStore,
)
from ingest.user_category import (
    EVENT_PERIOD_UNKNOWN,
    USER_CATEGORY_UNCONFIRMED,
)
from test_ingest_assessment import _ai_jobs, _event_item, _policy_connector, _v4_upsert
from test_ingest_application_deadline import _content_reviews
from test_ingest import policy_item
from test_ingest_supabase_store import FakeClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase/migrations/20260928000000_ingest_user_category_period.sql"
ROLLBACK = ROOT / "supabase/rollback/20260928000000_ingest_user_category_period_down.sql"


def _observed(store: MemoryIngestStore, key: str, **extra: object):
    record = _policy_connector().to_observation(
        _event_item(key, **extra), permission_status="testing_only", enabled=True
    )
    _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
    return store.items[(CANONICAL_POLICY_SOURCE, key)]


def _resolve(store: MemoryIngestStore, item, category: str, start=None, end=None):
    return store.resolve_source_item_user_category(
        source_item_id=item.id,
        revision_hash=item.revision_hash,
        user_category=category,
        event_start_on=start,
        event_end_on=end,
        reviewer="human:test",
    )


class UserCategoryPeriodTests(unittest.TestCase):
    def test_missing_category_blocks_ai_and_requests_one_review(self) -> None:
        store = MemoryIngestStore()
        item = _observed(
            store, "missing-category", aplyPrdSeCd="0057001", aplyYmd="2026-09-30"
        )
        reviews = _content_reviews(store, item)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].reason_codes, (USER_CATEGORY_UNCONFIRMED,))
        self.assertEqual(item.disposition, "target")
        self.assertEqual(_ai_jobs(store, item), [])

    def test_policy_with_existing_deadline_releases_ai(self) -> None:
        store = MemoryIngestStore()
        item = _observed(
            store, "policy", aplyPrdSeCd="0057001", aplyYmd="2026-09-30"
        )
        result = _resolve(store, item, "policy")
        self.assertEqual(result.user_category, "policy")
        self.assertEqual(_content_reviews(store, item)[0].status, "completed")
        self.assertEqual(_ai_jobs(store, item)[0].status, "queued")

    def test_program_without_deadline_stays_in_review(self) -> None:
        store = MemoryIngestStore()
        item = _observed(store, "program", aplyPrdSeCd="", aplyYmd="")
        _resolve(store, item, "program")
        review = _content_reviews(store, item)[0]
        self.assertEqual(review.status, "queued")
        self.assertEqual(review.reason_codes, (APPLICATION_DEADLINE_UNKNOWN,))
        self.assertEqual(_ai_jobs(store, item), [])
        store.resolve_source_item_application_deadline(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            kind="none",
            deadline_on=None,
            reviewer="human:test",
        )
        self.assertEqual(_content_reviews(store, item)[0].status, "completed")
        self.assertEqual(_ai_jobs(store, item)[0].status, "queued")

    def test_live_claimed_review_can_continue_to_deadline_input(self) -> None:
        store = MemoryIngestStore()
        item = _observed(store, "claimed-program", aplyPrdSeCd="", aplyYmd="")
        review = _content_reviews(store, item)[0]
        review.status = "claimed"
        review.claimed_by = "human:test"
        review.claim_lease_until = store._clock() + timedelta(minutes=5)
        _resolve(store, item, "program")
        review = _content_reviews(store, item)[0]
        self.assertEqual(review.status, "claimed")
        self.assertEqual(review.reason_codes, (APPLICATION_DEADLINE_UNKNOWN,))
        store.resolve_source_item_application_deadline(
            source_item_id=item.id, revision_hash=item.revision_hash,
            kind="none", deadline_on=None, reviewer="human:test",
        )
        self.assertEqual(_content_reviews(store, item)[0].status, "completed")
        self.assertEqual(_ai_jobs(store, item)[0].status, "queued")

    def test_unchanged_legacy_queued_ai_gets_category_review(self) -> None:
        store = MemoryIngestStore()
        item = _observed(
            store, "legacy-queued", aplyPrdSeCd="0057001", aplyYmd="2026-09-30"
        )
        for review in _content_reviews(store, item):
            store.jobs.pop(review.id)
        queued = store._insert_job(
            item.id, item.revision_hash, "ai_enrichment", store._clock(), ()
        )
        unchanged = _policy_connector().to_observation(
            _event_item(
                "legacy-queued", aplyPrdSeCd="0057001", aplyYmd="2026-09-30"
            ),
            permission_status="testing_only", enabled=True,
        )
        run = next(iter(store.runs.values()))
        result = store.upsert_source_observations_v4(
            CANONICAL_POLICY_SOURCE, run.id, [unchanged], None
        )
        self.assertEqual(result[0].outcome, "unchanged")
        self.assertEqual(
            _content_reviews(store, item)[0].reason_codes,
            (USER_CATEGORY_UNCONFIRMED,),
        )
        self.assertEqual(store.jobs[queued.id].status, "cancelled")
        _resolve(store, item, "policy")
        self.assertEqual(_content_reviews(store, item)[0].status, "completed")
        self.assertEqual(store.jobs[queued.id].status, "queued")

    def test_unchanged_live_claimed_review_receives_category_reason(self) -> None:
        store = MemoryIngestStore()
        item = _observed(store, "legacy-claimed", aplyPrdSeCd="", aplyYmd="")
        review = _content_reviews(store, item)[0]
        review.status = "claimed"
        review.claimed_by = "human:test"
        review.claim_lease_until = store._clock() + timedelta(minutes=5)
        review.reason_codes = ("other_content_reason",)
        unchanged = _policy_connector().to_observation(
            _event_item("legacy-claimed", aplyPrdSeCd="", aplyYmd=""),
            permission_status="testing_only", enabled=True,
        )
        run = next(iter(store.runs.values()))
        store.upsert_source_observations_v4(
            CANONICAL_POLICY_SOURCE, run.id, [unchanged], None
        )
        review = _content_reviews(store, item)[0]
        self.assertEqual(review.status, "claimed")
        self.assertEqual(
            review.reason_codes,
            ("other_content_reason", USER_CATEGORY_UNCONFIRMED),
        )

    def test_event_period_is_required_and_copied_without_application_deadline(self) -> None:
        store = MemoryIngestStore()
        item = _observed(store, "event", aplyPrdSeCd="", aplyYmd="")
        _resolve(store, item, "event", "2026-10-03", "2026-10-04")
        self.assertEqual(_content_reviews(store, item)[0].status, "completed")
        self.assertEqual(_ai_jobs(store, item)[0].status, "queued")
        store.enqueue_curation_candidate(
            source="youthcenter", source_item_id=item.external_key,
            source_revision_hash=item.revision_hash, slug="event",
            title_ko="행사", content_ko="행사 본문", raw_payload={}, ai_status_ko="success",
        )
        candidate = store.candidates[-1]
        self.assertEqual(candidate.user_category, "event")
        self.assertEqual((candidate.event_start_on, candidate.event_end_on),
                         ("2026-10-03", "2026-10-04"))
        self.assertIsNone(candidate.application_deadline_kind)
        store.sources[CANONICAL_POLICY_SOURCE].permission_status = "approved_noncommercial"
        curation_id = store.publish_candidate(
            candidate_source="youthcenter", external_key=item.external_key,
            revision_hash=item.revision_hash, candidate_id="test-candidate", slug="event",
        )
        public = store.public_curations[curation_id]
        self.assertEqual(public["user_category"], "event")
        self.assertEqual((public["event_start_on"], public["event_end_on"]),
                         ("2026-10-03", "2026-10-04"))

    def test_youth_space_and_living_need_no_period(self) -> None:
        for category in ("youth_space", "living"):
            with self.subTest(category=category):
                store = MemoryIngestStore()
                item = _observed(store, category, aplyPrdSeCd="", aplyYmd="")
                _resolve(store, item, category)
                self.assertEqual(_content_reviews(store, item)[0].status, "completed")
                self.assertEqual(_ai_jobs(store, item)[0].status, "queued")
                store.enqueue_curation_candidate(
                    source="youthcenter", source_item_id=item.external_key,
                    source_revision_hash=item.revision_hash, slug=category,
                    title_ko=category, content_ko="본문", raw_payload={},
                    ai_status_ko="success",
                )
                candidate = store.candidates[-1]
                self.assertEqual(candidate.user_category, category)
                self.assertIsNone(candidate.application_deadline_kind)
                self.assertIsNone(candidate.event_start_on)

    def test_publish_rejects_invalid_category_period_combinations(self) -> None:
        store = MemoryIngestStore()
        item = _observed(store, "bad-publish", aplyPrdSeCd="", aplyYmd="")
        _resolve(store, item, "event", "2026-10-03", "2026-10-04")
        store.enqueue_curation_candidate(
            source="youthcenter", source_item_id=item.external_key,
            source_revision_hash=item.revision_hash, slug="bad-publish",
            title_ko="행사", content_ko="본문", raw_payload={}, ai_status_ko="success",
        )
        store.sources[CANONICAL_POLICY_SOURCE].permission_status = "approved_noncommercial"
        candidate = store.candidates[-1]
        original = copy.deepcopy(candidate)
        for overrides, expected in (
            ({"user_category": "other"}, "user_category_required"),
            ({"event_start_on": "2026-10-05"}, "event_period_required"),
            ({"application_deadline_kind": "none"}, "event_period_required"),
            ({"user_category": "living"}, "invalid_user_category_period"),
            ({"user_category": "policy", "event_start_on": None,
              "event_end_on": None, "application_deadline_kind": "fixed"},
             "application_deadline_required"),
        ):
            with self.subTest(overrides=overrides):
                candidate.__dict__.update(copy.deepcopy(original.__dict__))
                candidate.__dict__.update(overrides)
                with self.assertRaises(RpcFailure) as failure:
                    store.publish_candidate(
                        candidate_source="youthcenter", external_key=item.external_key,
                        revision_hash=item.revision_hash, candidate_id="test-candidate",
                        slug="bad-publish",
                    )
                self.assertEqual(failure.exception.code, expected)
                self.assertEqual(store.public_curations, {})
                self.assertEqual(store.publication_events, [])

    def test_invalid_input_does_not_change_state(self) -> None:
        store = MemoryIngestStore()
        item = _observed(store, "invalid", aplyPrdSeCd="", aplyYmd="")
        for category, start, end, expected in (
            ("other", None, None, "invalid_user_category"),
            ("event", None, None, "invalid_event_period"),
            ("event", "2026-10-04", "2026-10-03", "invalid_event_period"),
            ("policy", "2026-10-03", "2026-10-04", "invalid_event_period"),
        ):
            with self.subTest(category=category, start=start, end=end):
                before = copy.deepcopy((store.user_categories, store.event_periods, store.jobs))
                with self.assertRaises(RpcFailure) as failure:
                    _resolve(store, item, category, start, end)
                self.assertEqual(failure.exception.code, expected)
                self.assertEqual(
                    (store.user_categories, store.event_periods, store.jobs), before
                )

    def test_revision_and_review_guards(self) -> None:
        store = MemoryIngestStore()
        item = _observed(store, "guards", aplyPrdSeCd="", aplyYmd="")
        with self.assertRaises(RpcFailure) as failure:
            store.resolve_source_item_user_category(
                source_item_id=item.id, revision_hash="0" * 64,
                user_category="event", event_start_on="2026-10-03",
                event_end_on="2026-10-04", reviewer="human:test",
            )
        self.assertEqual(failure.exception.code, "revision_mismatch")
        _resolve(store, item, "event", "2026-10-03", "2026-10-04")
        with self.assertRaises(RpcFailure) as failure:
            _resolve(store, item, "event", "2026-10-03", "2026-10-04")
        self.assertEqual(failure.exception.code, "user_category_review_not_open")

    def test_new_revision_never_inherits_category_or_event_period(self) -> None:
        store = MemoryIngestStore()
        item = _observed(store, "revision", aplyPrdSeCd="", aplyYmd="")
        original_hash = item.revision_hash
        _resolve(store, item, "event", "2026-10-03", "2026-10-04")
        changed = _policy_connector().to_observation(
            _event_item("revision", title="수도권 행사 변경", aplyPrdSeCd="", aplyYmd=""),
            permission_status="testing_only", enabled=True,
        )
        run = next(iter(store.runs.values()))
        store.upsert_source_observations_v4(
            CANONICAL_POLICY_SOURCE, run.id, [changed], None
        )
        current = store.items[(CANONICAL_POLICY_SOURCE, "revision")]
        self.assertNotEqual(current.revision_hash, original_hash)
        self.assertEqual(store.user_categories[(current.id, original_hash)], "event")
        self.assertNotIn((current.id, current.revision_hash), store.user_categories)
        self.assertNotIn((current.id, current.revision_hash), store.event_periods)
        self.assertEqual(
            _content_reviews(store, current)[0].reason_codes,
            (USER_CATEGORY_UNCONFIRMED,),
        )
        self.assertEqual(_ai_jobs(store, current)[-1].revision_hash, original_hash)

    def test_non_target_has_no_category_review(self) -> None:
        store = MemoryIngestStore()
        record = _policy_connector().to_observation(
            policy_item(
                "non-target", zip_cd="50110", oper_cd="50110",
                plcyExplnCn="이번 회차 신청과 개최 안내입니다.",
                plcySprtCn="이번 회차 신청과 개최 안내입니다.",
            ),
            permission_status="testing_only", enabled=True,
        )
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "non-target")]
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(_content_reviews(store, item), [])
        self.assertEqual(_ai_jobs(store, item), [])

    def test_queued_ai_is_not_claimed_without_current_category(self) -> None:
        store = MemoryIngestStore()
        item = _observed(store, "claim", aplyPrdSeCd="0057001", aplyYmd="2026-09-30")
        _resolve(store, item, "policy")
        self.assertEqual(len(_ai_jobs(store, item)), 1)
        store.user_categories.pop((item.id, item.revision_hash))
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="test-worker"), []
        )
        self.assertEqual(_ai_jobs(store, item)[0].status, "queued")


class SqlCategoryPeriodContractTests(unittest.TestCase):
    def test_migration_and_rollback_are_scoped(self) -> None:
        migration = MIGRATION.read_text(encoding="utf-8")
        rollback = ROLLBACK.read_text(encoding="utf-8")
        self.assertIn("create table machimoa_review.source_item_user_categories", migration)
        self.assertIn("create table machimoa_review.source_item_event_periods", migration)
        self.assertIn("machimoa_review.category_period_ready", migration)
        self.assertIn("'user_category_unconfirmed'", migration)
        self.assertIn("'event_period_unknown'", migration)
        self.assertIn("elsif v_upsert_row.outcome = 'unchanged'", migration)
        self.assertIn("v_review.status in ('queued', 'claimed')", migration)
        self.assertIn("grant execute on function public.resolve_source_item_user_category", migration.lower())
        self.assertIn("to service_role", migration.lower())
        self.assertIn("rollback_user_category_period_data_present", rollback)
        self.assertNotIn("delete from machimoa_review.curation_candidates", rollback.lower())

    def test_rollback_restores_exact_previous_function_bodies(self) -> None:
        previous = (
            ROOT / "supabase/migrations/20260926000000_ingest_application_deadline_facts.sql"
        ).read_text(encoding="utf-8")
        rollback = ROLLBACK.read_text(encoding="utf-8")
        for schema, name in (
            ("machimoa_review", "apply_source_item_evaluation"),
            ("machimoa_review", "ensure_ai_enrichment_job"),
            ("machimoa_review", "claim_processing_jobs"),
            ("machimoa_review", "upsert_source_observations_v4"),
            ("public", "enqueue_curation_candidate"),
            ("machimoa_review", "publish_curation_candidate"),
        ):
            with self.subTest(function=name):
                pattern = re.compile(
                    r"create or replace function "
                    + re.escape(schema + "." + name)
                    + r"\([\s\S]*?\$function\$;",
                    re.IGNORECASE,
                )
                original = pattern.search(previous)
                restored = pattern.search(rollback)
                self.assertIsNotNone(original)
                self.assertIsNotNone(restored)
                self.assertEqual(restored.group(0), original.group(0))


class CategoryRpcAdapterTests(unittest.TestCase):
    def test_public_rpc_maps_event_result_without_table_access(self) -> None:
        item_id = "22222222-2222-2222-2222-222222222222"
        revision = "a" * 64
        client = FakeClient({
            RESOLVE_SOURCE_ITEM_USER_CATEGORY: lambda _params: [{
                "source_item_id": item_id,
                "revision_hash": revision,
                "user_category": "event",
                "event_start_on": "2026-10-03",
                "event_end_on": "2026-10-04",
                "disposition": "target",
                "review_job_id": None,
                "review_job_status": None,
            }],
        })
        result = SupabaseIngestStore(client).resolve_source_item_user_category(
            source_item_id=item_id, revision_hash=revision,
            user_category="event", event_start_on="2026-10-03",
            event_end_on="2026-10-04", reviewer="human:test",
        )
        self.assertEqual(result.event_end_on, "2026-10-04")
        self.assertEqual(client.calls[0][0], RESOLVE_SOURCE_ITEM_USER_CATEGORY)
        self.assertEqual(client.calls[0][1]["p_user_category"], "event")
        self.assertEqual(client.table_calls, [])


if __name__ == "__main__":
    unittest.main()
