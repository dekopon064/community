"""Application deadline facts, review merge, and AI gate."""

from __future__ import annotations

import pathlib
import unittest
from datetime import datetime, timedelta, timezone

from ingest.application_deadline import (
    APPLICATION_DEADLINE_UNKNOWN,
    parse_content_application_deadline,
    parse_policy_application_deadline,
)
from ingest.connectors.youthcenter_policy import (
    YouthcenterPolicyConnector,
    policy_revision_hash,
)
from ingest.rpc_errors import RpcFailure
from ingest.source_identity import CANONICAL_POLICY_SOURCE
from test_ingest import policy_item
from test_ingest_assessment import _ai_jobs, _event_item, _policy_connector, _v4_upsert
from test_ingest_min_workflow import REVIEWER

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260926000000_ingest_application_deadline_facts.sql"
)
ROLLBACK = (
    ROOT
    / "supabase"
    / "rollback"
    / "20260926000000_ingest_application_deadline_facts_down.sql"
)


def _content_reviews(store, item):
    return [
        job
        for job in store.jobs.values()
        if job.source_item_id == item.id
        and job.revision_hash == item.revision_hash
        and job.processing_stage == "content_review"
    ]


class ApplicationDeadlineParseTests(unittest.TestCase):
    def test_policy_codes_and_complete_period(self) -> None:
        none = parse_policy_application_deadline("0057002", None)
        closed = parse_policy_application_deadline("0057003", "2026-01-01")
        fixed = parse_policy_application_deadline("0057001", "2026-01-01~2026-03-31")
        self.assertEqual((none.kind, none.on), ("none", None))
        self.assertEqual((closed.kind, closed.on), ("closed", None))
        self.assertEqual((fixed.kind, fixed.on), ("fixed", "2026-03-31"))

    def test_year_omitted_end_stays_unconfirmed(self) -> None:
        self.assertIsNone(
            parse_policy_application_deadline("0057001", "2026-01-01~03-31")
        )
        self.assertIsNone(
            parse_policy_application_deadline(
                "0057001", "2026년 1월 1일부터 3월 31일까지"
            )
        )

    def test_business_period_is_not_an_application_deadline(self) -> None:
        self.assertIsNone(parse_policy_application_deadline("", "2026-12-31"))
        self.assertIsNone(parse_policy_application_deadline("0057004", "2026-12-31"))
        item = policy_item(
            "biz",
            zip_cd="11680",
            oper_cd="11680",
            aplyPrdSeCd="",
            bizPrdEndYmd="2026-12-31",
            bizPrdBgngYmd="2026-01-01",
        )
        record = _policy_connector().to_observation(
            item, permission_status="testing_only", enabled=True
        )
        self.assertIsNone(record.application_deadline)
        self.assertNotIn("bizPrdEndYmd", record.normalized_payload)
        self.assertIn("aplyPrdSeCd", record.normalized_payload)
        self.assertIn("aplyYmd", record.normalized_payload)

    def test_content_phrases(self) -> None:
        for sentence in (
            "접수가 마감되었습니다",
            "신청이 마감되었습니다",
            "모집이 종료되었습니다",
            "접수 종료",
            "접수가 마감되었습니다.",
        ):
            self.assertEqual(
                parse_content_application_deadline(sentence).kind,
                "closed",
                sentence,
            )
        for sentence in (
            "상시 모집 중",
            "상시 접수 중",
            "신청은 상시 가능",
            "상시 모집 중.",
        ):
            self.assertEqual(
                parse_content_application_deadline(sentence).kind,
                "none",
                sentence,
            )
        self.assertEqual(
            parse_content_application_deadline(
                "프로그램 안내입니다. 접수가 마감되었습니다."
            ).kind,
            "closed",
        )
        self.assertEqual(
            parse_content_application_deadline("안내입니다.\n상시 접수 중").kind,
            "none",
        )
        for sentence in (
            "접수 마감",
            "신청 마감",
            "모집 마감",
            "상시 접수",
            "상시 모집",
            "신청 상시",
            "접수 마감 예정",
            "접수 마감 전",
            "접수 마감하기 전",
            "접수 마감되기 전",
            "접수 마감일 추후 공지",
            "접수 종료 예정",
            "상시 접수 아님",
            "상시 모집 중 아님",
            "신청은 상시 가능하지 않음",
            "상시 운영",
            "현재 상시 모집 중",
            "참가자는 상시 모집합니다.",
            "상시 접수로 받습니다.",
            "이번 모집은 접수 마감되었습니다.",
            "시설은 상시 운영합니다.",
            "접수가 마감되었습니다만",
            "상시 모집 중입니다",
        ):
            self.assertIsNone(
                parse_content_application_deadline(sentence),
                sentence,
            )
        self.assertIsNone(
            parse_content_application_deadline(
                "접수가 마감되었습니다. 상시 모집 중"
            )
        )
        fixed = parse_content_application_deadline(
            "신청 마감일은 2026년 9월 30일입니다."
        )
        self.assertEqual((fixed.kind, fixed.on), ("fixed", "2026-09-30"))
        with_closed = parse_content_application_deadline(
            "신청 마감일은 2026년 9월 30일입니다. 접수가 마감되었습니다."
        )
        self.assertEqual((with_closed.kind, with_closed.on), ("fixed", "2026-09-30"))
        with_none = parse_content_application_deadline(
            "신청 마감일은 2026년 9월 30일입니다. 상시 모집 중"
        )
        self.assertEqual((with_none.kind, with_none.on), ("fixed", "2026-09-30"))
        self.assertIsNone(
            parse_content_application_deadline(
                "신청 마감일은 2026년 9월 30일입니다. 모집 마감일은 2026년 10월 1일입니다. 접수가 마감되었습니다."
            )
        )
        self.assertIsNone(
            parse_content_application_deadline(
                "신청 기간은 2026년 1월 1일 ~ 3월 31일입니다. 상시 모집 중"
            )
        )
        self.assertIsNone(
            parse_content_application_deadline("행사일은 2026년 5월 1일입니다.")
        )
        self.assertIsNone(
            parse_content_application_deadline("교육일: 2026-05-01")
        )
        self.assertIsNone(
            parse_content_application_deadline(
                "사업기간은 2026-01-01부터 2026-12-31까지입니다."
            )
        )
        self.assertIsNone(
            parse_content_application_deadline(
                "신청 기간은 2026년 1월 1일 ~ 3월 31일입니다."
            )
        )

    def test_revision_hash_tracks_application_fields_only(self) -> None:
        base = policy_item("h", zip_cd="11680", oper_cd="11680")
        code_changed = dict(base, aplyPrdSeCd="0057003")
        date_changed = dict(base, aplyYmd="2026-03-31")
        business_changed = dict(base, bizPrdEndYmd="2026-12-31")
        original = policy_revision_hash(base, "https://example.go.kr/apply")
        self.assertNotEqual(
            original,
            policy_revision_hash(code_changed, "https://example.go.kr/apply"),
        )
        self.assertNotEqual(
            original,
            policy_revision_hash(date_changed, "https://example.go.kr/apply"),
        )
        self.assertEqual(
            original,
            policy_revision_hash(business_changed, "https://example.go.kr/apply"),
        )
        connector = YouthcenterPolicyConnector(api_key_provider=lambda: "unused")
        self.assertIn(
            "aplyPrdSeCd",
            connector.to_observation(
                base, permission_status="testing_only", enabled=True
            ).normalized_payload,
        )


class ApplicationDeadlineReviewTests(unittest.TestCase):
    def test_unconfirmed_potential_target_opens_one_content_review(self) -> None:
        from legacy_category_test_store import LegacyCategoryFixtureStore as MemoryIngestStore

        store = MemoryIngestStore()
        record = _policy_connector().to_observation(
            _event_item("open", aplyPrdSeCd=""),
            permission_status="testing_only",
            enabled=True,
        )
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "open")]
        self.assertEqual(item.disposition, "target")
        reviews = _content_reviews(store, item)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].reason_codes, (APPLICATION_DEADLINE_UNKNOWN,))
        self.assertEqual(_ai_jobs(store, item), [])

    def test_existing_reason_is_merged_and_removed_without_closing_review(self) -> None:
        from legacy_category_test_store import LegacyCategoryFixtureStore as MemoryIngestStore

        store = MemoryIngestStore()
        record = _policy_connector().to_observation(
            policy_item(
                "mix",
                zip_cd="",
                oper_cd="",
                aplyPrdSeCd="",
                plcyExplnCn="이번 회차 신청과 개최 안내입니다.",
                plcySprtCn="이번 회차 신청과 개최 안내입니다.",
            ),
            permission_status="testing_only",
            enabled=True,
        )
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "mix")]
        reviews = _content_reviews(store, item)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(
            set(reviews[0].reason_codes),
            {"region_scope_unknown", APPLICATION_DEADLINE_UNKNOWN},
        )
        result = store.resolve_source_item_application_deadline(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            kind="fixed",
            deadline_on="2026-09-30",
            reviewer=REVIEWER,
        )
        self.assertEqual(result.application_deadline_kind, "fixed")
        self.assertEqual(result.application_deadline_on, "2026-09-30")
        self.assertEqual(reviews[0].status, "queued")
        self.assertEqual(reviews[0].reason_codes, ("region_scope_unknown",))
        self.assertEqual(_ai_jobs(store, item), [])

    def test_non_target_does_not_open_deadline_review(self) -> None:
        from legacy_category_test_store import LegacyCategoryFixtureStore as MemoryIngestStore

        store = MemoryIngestStore()
        record = _policy_connector().to_observation(
            policy_item(
                "nt",
                zip_cd="11680",
                oper_cd="11680",
                aplyPrdSeCd="",
                plcyExplnCn="",
                plcySprtCn="",
            ),
            permission_status="testing_only",
            enabled=True,
        )
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "nt")]
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(_content_reviews(store, item), [])

    def test_resolving_the_only_reason_completes_review_and_allows_ai(self) -> None:
        from legacy_category_test_store import LegacyCategoryFixtureStore as MemoryIngestStore

        store = MemoryIngestStore()
        record = _policy_connector().to_observation(
            _event_item("done", aplyPrdSeCd=""),
            permission_status="testing_only",
            enabled=True,
        )
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "done")]
        for kind, deadline_on in (("none", None),):
            store.resolve_source_item_application_deadline(
                source_item_id=item.id,
                revision_hash=item.revision_hash,
                kind=kind,
                deadline_on=deadline_on,
                reviewer=REVIEWER,
            )
        review = _content_reviews(store, item)[0]
        self.assertEqual(review.status, "completed")
        self.assertNotIn(APPLICATION_DEADLINE_UNKNOWN, review.reason_codes)
        self.assertEqual(len(_ai_jobs(store, item)), 1)

    def test_closed_input_and_invalid_combo_are_fail_closed(self) -> None:
        from legacy_category_test_store import LegacyCategoryFixtureStore as MemoryIngestStore

        store = MemoryIngestStore()
        record = _policy_connector().to_observation(
            _event_item("bad", aplyPrdSeCd=""),
            permission_status="testing_only",
            enabled=True,
        )
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "bad")]
        with self.assertRaises(RpcFailure) as raised:
            store.resolve_source_item_application_deadline(
                source_item_id=item.id,
                revision_hash=item.revision_hash,
                kind="fixed",
                deadline_on=None,
                reviewer=REVIEWER,
            )
        self.assertEqual(str(raised.exception), "invalid_application_deadline")
        self.assertNotIn((item.id, item.revision_hash), store.application_deadlines)
        with self.assertRaises(RpcFailure) as mismatch:
            store.resolve_source_item_application_deadline(
                source_item_id=item.id,
                revision_hash="a" * 64,
                kind="closed",
                deadline_on=None,
                reviewer=REVIEWER,
            )
        self.assertEqual(str(mismatch.exception), "revision_mismatch")
        self.assertIn(
            APPLICATION_DEADLINE_UNKNOWN,
            _content_reviews(store, item)[0].reason_codes,
        )
        store.resolve_source_item_application_deadline(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            kind="closed",
            deadline_on=None,
            reviewer=REVIEWER,
        )
        fact = store.application_deadlines[(item.id, item.revision_hash)]
        self.assertEqual((fact.kind, fact.on), ("closed", None))

    def test_same_revision_keeps_fact_and_new_revision_does_not_inherit(self) -> None:
        from legacy_category_test_store import LegacyCategoryFixtureStore as MemoryIngestStore

        store = MemoryIngestStore()
        connector = _policy_connector()
        first = connector.to_observation(
            _event_item("rev", aplyPrdSeCd="0057001", aplyYmd="2026-04-30"),
            permission_status="testing_only",
            enabled=True,
        )
        started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
        store.upsert_source_observations_v4(
            CANONICAL_POLICY_SOURCE, started.run_id, [first], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "rev")]
        original_hash = item.revision_hash
        self.assertEqual(
            store.application_deadlines[(item.id, original_hash)].on, "2026-04-30"
        )
        store.upsert_source_observations_v4(
            CANONICAL_POLICY_SOURCE, started.run_id, [first], None
        )
        self.assertEqual(item.revision_hash, original_hash)
        self.assertEqual(
            store.application_deadlines[(item.id, original_hash)].kind, "fixed"
        )
        changed = connector.to_observation(
            _event_item("rev", aplyPrdSeCd="", title="수도권 행사 개정"),
            permission_status="testing_only",
            enabled=True,
        )
        store.upsert_source_observations_v4(
            CANONICAL_POLICY_SOURCE, started.run_id, [changed], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "rev")]
        self.assertNotEqual(item.revision_hash, original_hash)
        self.assertNotIn((item.id, item.revision_hash), store.application_deadlines)
        self.assertIn((item.id, original_hash), store.application_deadlines)
        self.assertIn(
            APPLICATION_DEADLINE_UNKNOWN,
            _content_reviews(store, item)[0].reason_codes,
        )


class ApplicationDeadlineAiGateTests(unittest.TestCase):
    def test_missing_fact_does_not_enqueue_or_claim(self) -> None:
        from legacy_category_test_store import LegacyCategoryFixtureStore as MemoryIngestStore

        store = MemoryIngestStore()
        record = _policy_connector().to_observation(
            _event_item("block", aplyPrdSeCd=""),
            permission_status="testing_only",
            enabled=True,
        )
        started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
        store.upsert_source_observations_v4(
            CANONICAL_POLICY_SOURCE, started.run_id, [record], None
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "block")]
        self.assertEqual(_ai_jobs(store, item), [])
        ready = _policy_connector().to_observation(
            _event_item("queued", aplyPrdSeCd="0057002"),
            permission_status="testing_only",
            enabled=True,
        )
        store.upsert_source_observations_v4(
            CANONICAL_POLICY_SOURCE, started.run_id, [ready], None
        )
        queued = store.items[(CANONICAL_POLICY_SOURCE, "queued")]
        self.assertEqual(len(_ai_jobs(store, queued)), 1)
        store.application_deadlines.pop((queued.id, queued.revision_hash))
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="worker-1"),
            [],
        )
        self.assertEqual(_ai_jobs(store, queued)[0].status, "queued")

    def test_fixed_none_and_closed_can_proceed(self) -> None:
        from legacy_category_test_store import LegacyCategoryFixtureStore as MemoryIngestStore

        cases = (
            ("fixed-case", "0057001", "2026-05-31"),
            ("none-case", "0057002", None),
            ("closed-case", "0057003", None),
        )
        for key, code, aply_ymd in cases:
            store = MemoryIngestStore()
            extra = {"aplyPrdSeCd": code}
            if aply_ymd is not None:
                extra["aplyYmd"] = aply_ymd
            record = _policy_connector().to_observation(
                _event_item(key, **extra),
                permission_status="testing_only",
                enabled=True,
            )
            _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
            item = store.items[(CANONICAL_POLICY_SOURCE, key)]
            self.assertEqual(len(_ai_jobs(store, item)), 1, key)
            claimed = store.claim_processing_jobs(
                "ai_enrichment", worker_id="worker-1"
            )
            self.assertEqual(len(claimed), 1, key)

    def test_other_open_human_review_still_blocks_ai(self) -> None:
        from legacy_category_test_store import LegacyCategoryFixtureStore as MemoryIngestStore

        store = MemoryIngestStore()
        record = _policy_connector().to_observation(
            policy_item(
                "region",
                zip_cd="",
                oper_cd="",
                aplyPrdSeCd="0057002",
                plcyExplnCn="이번 회차 신청과 개최 안내입니다.",
                plcySprtCn="이번 회차 신청과 개최 안내입니다.",
            ),
            permission_status="testing_only",
            enabled=True,
        )
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "region")]
        self.assertIn((item.id, item.revision_hash), store.application_deadlines)
        self.assertEqual(_content_reviews(store, item)[0].reason_codes, ("region_scope_unknown",))
        self.assertEqual(_ai_jobs(store, item), [])
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="worker-1"),
            [],
        )

    def test_expired_claim_reasons_update_and_live_claim_keeps_worker(self) -> None:
        from legacy_category_test_store import LegacyCategoryFixtureStore as MemoryIngestStore

        store = MemoryIngestStore()
        record = _policy_connector().to_observation(
            policy_item(
                "lease",
                zip_cd="",
                oper_cd="",
                aplyPrdSeCd="",
                plcyExplnCn="이번 회차 신청과 개최 안내입니다.",
                plcySprtCn="이번 회차 신청과 개최 안내입니다.",
            ),
            permission_status="testing_only",
            enabled=True,
        )
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "lease")]
        review = _content_reviews(store, item)[0]
        review.status = "claimed"
        review.claimed_by = "worker-1"
        review.claim_lease_until = datetime.now(timezone.utc) - timedelta(seconds=5)
        store.resolve_source_item_application_deadline(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            kind="none",
            deadline_on=None,
            reviewer=REVIEWER,
        )
        self.assertNotIn(APPLICATION_DEADLINE_UNKNOWN, review.reason_codes)
        self.assertIn("region_scope_unknown", review.reason_codes)


class ApplicationDeadlineCandidateTests(unittest.TestCase):
    def test_candidate_copies_fact_and_publish_rejects_null_kind(self) -> None:
        from ingest.store import _Candidate
        from legacy_category_test_store import LegacyCategoryFixtureStore as MemoryIngestStore

        store = MemoryIngestStore()
        record = _policy_connector().to_observation(
            _event_item("cand", aplyPrdSeCd="0057001", aplyYmd="2026-06-15"),
            permission_status="testing_only",
            enabled=True,
        )
        missing = _policy_connector().to_observation(
            _event_item("nofact", aplyPrdSeCd=""),
            permission_status="testing_only",
            enabled=True,
        )
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record, missing])
        item = store.items[(CANONICAL_POLICY_SOURCE, "cand")]
        with self.assertRaises(RpcFailure) as raised:
            store.enqueue_curation_candidate(
                source="youthcenter",
                source_item_id=missing.external_key,
                source_revision_hash=missing.revision_hash,
                slug="nofact",
                title_ko="제목",
                content_ko="본문",
                raw_payload={},
                ai_status_ko="success",
            )
        self.assertEqual(str(raised.exception), "application_deadline_required")
        inserted = store.enqueue_curation_candidate(
            source="youthcenter",
            source_item_id=item.external_key,
            source_revision_hash=item.revision_hash,
            slug="cand",
            title_ko="제목",
            content_ko="본문",
            raw_payload={},
            ai_status_ko="success",
        )
        self.assertEqual(inserted["outcome"], "inserted")
        self.assertEqual(store.candidates[-1].application_deadline_kind, "fixed")
        self.assertEqual(store.candidates[-1].application_deadline_on, "2026-06-15")
        store.sources[CANONICAL_POLICY_SOURCE].permission_status = "approved_noncommercial"
        store.candidates.append(
            _Candidate(
                source="youthcenter",
                source_item_id="legacy-null",
                source_revision_hash="b" * 64,
                application_deadline_kind=None,
                user_category="policy",
            )
        )
        with self.assertRaises(RpcFailure) as null_kind:
            store.publish_candidate(
                candidate_source="youthcenter",
                external_key="legacy-null",
                revision_hash="b" * 64,
                candidate_id="cand-null",
                slug="legacy-null",
            )
        self.assertEqual(str(null_kind.exception), "application_deadline_required")
        curation_id = store.publish_candidate(
            candidate_source="youthcenter",
            external_key=item.external_key,
            revision_hash=item.revision_hash,
            candidate_id="cand-1",
            slug="policy-cand",
        )
        published = store.public_curations[curation_id]
        self.assertEqual(published["application_deadline_kind"], "fixed")
        self.assertEqual(published["application_deadline_on"], "2026-06-15")
        legacy_id = "legacy-row"
        store.public_curations[legacy_id] = {
            "id": legacy_id,
            "application_deadline_kind": None,
            "application_deadline_on": None,
        }
        self.assertIsNone(store.public_curations[legacy_id]["application_deadline_kind"])


class ApplicationDeadlineSqlContractTests(unittest.TestCase):
    def test_migration_shape_and_rollback_fail_closed(self) -> None:
        sql = MIGRATION.read_text(encoding="utf-8")
        down = ROLLBACK.read_text(encoding="utf-8")
        preamble = sql.split("create function", 1)[0]
        self.assertNotIn("update machimoa_review", preamble.lower())
        self.assertNotIn("update public", preamble.lower())
        self.assertNotIn("delete from", preamble.lower())
        self.assertEqual(sql.lower().count("create table"), 1)
        self.assertEqual(sql.lower().count("grant execute"), 1)
        self.assertIn("to service_role", sql)
        self.assertNotRegex(sql.lower(), r"grant\s+execute[\s\S]{0,240}to\s+anon\b")
        self.assertNotRegex(
            sql.lower(), r"grant\s+execute[\s\S]{0,240}to\s+authenticated\b"
        )
        self.assertNotRegex(sql.lower(), r"grant\s+execute[\s\S]{0,240}to\s+public\b")
        self.assertIn("source_item_application_deadlines", sql)
        self.assertIn("application_deadline_required", sql)
        self.assertIn("append_application_deadline_unknown", sql)
        self.assertIn("public.resolve_source_item_application_deadline", sql)
        self.assertIn("rollback_application_deadline_data_present", down)
        self.assertIn(
            "create or replace function machimoa_review.ensure_ai_enrichment_job",
            down,
        )
        self.assertIn(
            "create or replace function public.enqueue_curation_candidate",
            down,
        )
        self.assertNotIn("delete from machimoa_review.processing_jobs", down.lower())
        self.assertNotIn("delete from machimoa_review.ingest_review_decisions", down.lower())
        self.assertNotIn("delete from machimoa_review.curation_candidates", down.lower())
        self.assertNotIn("delete from public.curations", down.lower())
        worker = (
            ROOT / "scripts" / "ingest" / "ai_queue_rpc.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("application_deadline", worker)
        schema = (
            ROOT / "scripts" / "ingest" / "claude_schemas" / "summary.schema.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn("application_deadline_kind", schema)
