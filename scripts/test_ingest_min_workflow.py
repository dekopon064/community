"""User-flow acceptance for the minimum V1 review workflow."""

from __future__ import annotations

import pathlib
import subprocess
import unittest

from ingest.ai_worker import process_ai_jobs
from ingest.evaluate_gates import REASON_MISSING_SOURCE_URL, REASON_REGION_SCOPE_UNKNOWN
from ingest.gate_facts import GATE_FACTS_SCHEMA_VERSION
from ingest.product_type import (
    PRODUCT_TYPE_LIVING_GUIDE,
    PRODUCT_TYPE_POLICY_REFERENCE,
    PRODUCT_TYPE_RULE_VERSION,
)
from ingest.rpc_errors import RpcFailure
from ingest.source_identity import CANONICAL_POLICY_SOURCE
from ingest.store import MemoryIngestStore
from test_ingest import _ai_deps, policy_item
from test_ingest_assessment import (
    _ai_jobs,
    _event_item,
    _policy_connector,
    _v4_upsert,
)


REVIEWER = "human:min-workflow"
LIVING_GUIDE_FACTS = {"schema_version": GATE_FACTS_SCHEMA_VERSION}
INVALID_LIVING_GUIDE_FACTS = {
    "schema_version": GATE_FACTS_SCHEMA_VERSION,
    "eligibility_scope": "nationwide",
    "eligibility_region_codes": [],
    "eligibility_region_evidence": "",
}


def _review_jobs(store: MemoryIngestStore, item, stage: str = "content_review"):
    return [
        job
        for job in store.jobs.values()
        if job.source_item_id == item.id and job.processing_stage == stage
    ]


def _open_review_jobs(store: MemoryIngestStore, item, stage: str = "content_review"):
    return [
        job
        for job in _review_jobs(store, item, stage)
        if job.status in {"queued", "claimed"}
    ]


def _unclear_policy(key: str):
    return policy_item(key, zip_cd="11680", oper_cd="11680")


def _confirm(store: MemoryIngestStore, item, product_type: str):
    return store.resolve_source_item_product_type(
        source_item_id=item.id,
        revision_hash=item.revision_hash,
        action="confirm",
        product_type=product_type,
        rule_version=PRODUCT_TYPE_RULE_VERSION,
        reviewer=REVIEWER,
    )


class MinimumWorkflowAcceptanceTests(unittest.TestCase):
    def test_living_guide_common_pass_starts_ai_without_approve_ai(self) -> None:
        record = _policy_connector().to_observation(
            _unclear_policy("lg"), permission_status="testing_only", enabled=True
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "lg")]
        _confirm(store, item, PRODUCT_TYPE_LIVING_GUIDE)
        result = store.resolve_source_item_gate_facts(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            gate_facts=LIVING_GUIDE_FACTS,
            assessment_schema_version=GATE_FACTS_SCHEMA_VERSION,
            reviewer=REVIEWER,
        )
        self.assertEqual(result.disposition, "target")
        self.assertEqual(store.decisions, {})
        ais = _ai_jobs(store, item)
        self.assertEqual(len(ais), 1)
        self.assertEqual(ais[0].status, "queued")
        self.assertEqual(_open_review_jobs(store, item), [])

    def test_policy_region_and_audience_unknown_share_one_content_review(self) -> None:
        body = "상시 지원 자격과 이용 방법입니다. 지역 주민 안내입니다."
        record = _policy_connector().to_observation(
            policy_item(
                "both",
                zip_cd="",
                oper_cd="",
                plcyExplnCn=body,
                plcySprtCn=body,
            ),
            permission_status="testing_only",
            enabled=True,
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "both")]
        reviews = _review_jobs(store, item)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].processing_stage, "content_review")
        self.assertEqual(
            set(reviews[0].reason_codes),
            {"region_scope_unknown", "relevance_unconfirmed"},
        )
        self.assertEqual(_ai_jobs(store, item), [])

    def test_event_region_unknown_has_no_audience_reason(self) -> None:
        record = _policy_connector().to_observation(
            policy_item(
                "evt",
                zip_cd="",
                oper_cd="",
                plcyExplnCn="이번 회차 신청과 개최 안내입니다.",
                plcySprtCn="이번 회차 신청과 개최 안내입니다.",
            ),
            permission_status="testing_only",
            enabled=True,
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "evt")]
        reviews = _review_jobs(store, item)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].reason_codes, (REASON_REGION_SCOPE_UNKNOWN,))
        self.assertNotIn("relevance_unconfirmed", reviews[0].reason_codes)
        self.assertEqual(_ai_jobs(store, item), [])

    def test_missing_source_url_is_content_review_and_never_ai(self) -> None:
        record = _policy_connector().to_observation(
            policy_item(
                "nourl",
                zip_cd="11680",
                oper_cd="11680",
                aplyUrlAddr=None,
                refUrlAddr1=None,
                refUrlAddr2=None,
            ),
            permission_status="testing_only",
            enabled=True,
        )
        self.assertFalse(record.has_source_url)
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "nourl")]
        reviews = _review_jobs(store, item)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].reason_codes, (REASON_MISSING_SOURCE_URL,))
        self.assertEqual(_ai_jobs(store, item), [])
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="w"), []
        )

    def test_type_confirm_then_failed_facts_keeps_content_review(self) -> None:
        record = _policy_connector().to_observation(
            _unclear_policy("hold"), permission_status="testing_only", enabled=True
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "hold")]
        queued = _review_jobs(store, item)
        self.assertEqual(len(queued), 1)
        _confirm(store, item, PRODUCT_TYPE_LIVING_GUIDE)
        self.assertEqual(_review_jobs(store, item)[0].status, "queued")
        self.assertEqual(_ai_jobs(store, item), [])
        with self.assertRaises(RpcFailure) as err:
            store.resolve_source_item_gate_facts(
                source_item_id=item.id,
                revision_hash=item.revision_hash,
                gate_facts=INVALID_LIVING_GUIDE_FACTS,
                assessment_schema_version=GATE_FACTS_SCHEMA_VERSION,
                reviewer=REVIEWER,
            )
        self.assertEqual(err.exception.code, "invalid_gate_facts")
        self.assertEqual(_review_jobs(store, item)[0].status, "queued")
        self.assertEqual(_ai_jobs(store, item), [])
        row = store.product_types[(item.id, item.revision_hash)]
        self.assertIsNone(row.gate_facts)

    def test_evaluator_pass_starts_ai_without_approve_ai(self) -> None:
        record = _policy_connector().to_observation(
            _event_item("pass"), permission_status="testing_only", enabled=True
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "pass")]
        self.assertEqual(item.disposition, "target")
        self.assertEqual(store.decisions, {})
        self.assertEqual(len(_ai_jobs(store, item)), 1)
        self.assertEqual(
            len(store.claim_processing_jobs("ai_enrichment", worker_id="w")), 1
        )

    def test_ai_result_is_not_public_before_publish(self) -> None:
        record = _policy_connector().to_observation(
            _event_item("pub"), permission_status="testing_only", enabled=True
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        self.assertEqual(store.public_curations, {})
        result = process_ai_jobs(store, **_ai_deps())
        self.assertEqual(result.completed, 1)
        self.assertEqual(store.public_curations, {})
        store.sources[CANONICAL_POLICY_SOURCE].permission_status = (
            "approved_noncommercial"
        )
        curation_id = store.publish_candidate(
            candidate_source="youthcenter",
            external_key="pub",
            revision_hash=store.items[(CANONICAL_POLICY_SOURCE, "pub")].revision_hash,
            candidate_id="cand-pub",
            slug="policy-pub",
        )
        self.assertIn(curation_id, store.public_curations)

    def test_legacy_open_reviews_close_on_reeval_and_decisions_remain(self) -> None:
        body = "이번 회차 개최 안내입니다. 재한 일본인은 참여 가능합니다."
        record = _policy_connector().to_observation(
            policy_item(
                "legacy-open",
                zip_cd="",
                oper_cd="",
                plcyExplnCn=body,
                plcySprtCn=body,
            ),
            permission_status="testing_only",
            enabled=True,
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "legacy-open")]
        now = store._clock()
        leftover_region = store._insert_job(
            item.id, item.revision_hash, "region_review", now, ("region_scope_unknown",)
        )
        leftover_relevance = store._insert_job(
            item.id,
            item.revision_hash,
            "relevance_review",
            now,
            ("relevance_unconfirmed",),
        )
        store.resolve_ingest_review_decision(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            review_type="region",
            decision="needs_review",
            region_scope="unknown",
            rule_version="relevance-capital-v1",
            reviewer=REVIEWER,
        )
        original = dict(store.decisions)
        store.resolve_source_item_gate_facts(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            gate_facts={
                "schema_version": GATE_FACTS_SCHEMA_VERSION,
                "eligibility_scope": "nationwide",
                "eligibility_region_codes": [],
                "eligibility_region_evidence": "human",
            },
            assessment_schema_version=GATE_FACTS_SCHEMA_VERSION,
            reviewer=REVIEWER,
        )
        self.assertEqual(leftover_region.status, "completed")
        self.assertEqual(leftover_relevance.status, "completed")
        self.assertEqual(_open_review_jobs(store, item), [])
        self.assertEqual(_open_review_jobs(store, item, "region_review"), [])
        self.assertEqual(_open_review_jobs(store, item, "relevance_review"), [])
        self.assertEqual(store.decisions, original)
        self.assertEqual(len(_ai_jobs(store, item)), 1)

    def test_unknown_product_type_is_one_content_review(self) -> None:
        record = _policy_connector().to_observation(
            _unclear_policy("type"), permission_status="testing_only", enabled=True
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "type")]
        stages = {job.processing_stage for job in store.jobs.values()}
        self.assertEqual(stages, {"content_review"})
        self.assertNotIn((item.id, item.revision_hash), store.product_types)
        self.assertEqual(_ai_jobs(store, item), [])

    def test_policy_pass_has_no_human_preapproval(self) -> None:
        body = (
            "상시 지원 자격과 이용 방법입니다. "
            "재한 일본인은 이용 가능합니다. 전국 대상 청년 지원입니다. "
            "거주 지역 제한 없음."
        )
        record = _policy_connector().to_observation(
            policy_item(
                "policy-pass",
                zip_cd="",
                oper_cd="",
                plcyExplnCn=body,
                plcySprtCn=body,
            ),
            permission_status="testing_only",
            enabled=True,
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "policy-pass")]
        row = store.product_types[(item.id, item.revision_hash)]
        self.assertEqual(row.product_type, PRODUCT_TYPE_POLICY_REFERENCE)
        self.assertEqual(item.disposition, "target")
        self.assertEqual(store.decisions, {})
        self.assertEqual(len(_ai_jobs(store, item)), 1)


class MinimumWorkflowContractTests(unittest.TestCase):
    def test_fail_does_not_start_ai(self) -> None:
        record = _policy_connector().to_observation(
            policy_item(
                "fail",
                zip_cd="50110",
                oper_cd="50110",
                plcyExplnCn="이번 회차 신청과 개최 안내입니다.",
                plcySprtCn="이번 회차 신청과 개최 안내입니다.",
            ),
            permission_status="testing_only",
            enabled=True,
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "fail")]
        self.assertEqual(item.disposition, "non_target")
        self.assertEqual(_ai_jobs(store, item), [])
        self.assertEqual(_open_review_jobs(store, item), [])

    def test_applied_migrations_match_origin_main_blobs(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        for rel in (
            "supabase/migrations/20260918000000_ingest_product_type.sql",
            "supabase/migrations/20260921000000_ingest_gate_facts.sql",
        ):
            origin = subprocess.check_output(
                ["git", "rev-parse", f"origin/main:{rel}"],
                cwd=root,
                text=True,
            ).strip()
            working = subprocess.check_output(
                ["git", "hash-object", str(root / rel)],
                cwd=root,
                text=True,
            ).strip()
            self.assertEqual(origin, working, rel)

    def test_unit_c_files_and_writer_are_absent(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        for rel in (
            "supabase/migrations/20260922000000_ingest_human_assessment_v1.sql",
            "supabase/rollback/20260922000000_ingest_human_assessment_v1_down.sql",
            "scripts/test_ingest_human_assessment.py",
        ):
            self.assertFalse((root / rel).exists(), rel)
        store_src = (root / "scripts" / "ingest" / "store.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("apply_source_item_human_assessment", store_src)
        self.assertNotIn("HumanAssessment", store_src)
        forward = (
            root / "supabase" / "migrations" / "20260923000000_ingest_min_review_workflow.sql"
        ).read_text(encoding="utf-8")
        self.assertNotIn("apply_source_item_human_assessment", forward)
        self.assertNotIn("decisions.v1", forward)


if __name__ == "__main__":
    unittest.main()
