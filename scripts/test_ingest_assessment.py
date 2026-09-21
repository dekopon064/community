"""Unit A: V1 assessment pipeline, capital_v1 evaluator, MemoryStore v4."""

from __future__ import annotations

import inspect
import json
import pathlib
import unittest

from ingest.assessment import assess_observation, propose_assessment
from ingest.connectors.youthcenter_content import YouthcenterContentConnector
from ingest.connectors.youthcenter_policy import YouthcenterPolicyConnector
from ingest.evaluate_gates import (
    CAPITAL_V1_PROFILE,
    EVALUATOR_CONTRACT_ID,
    evaluate_capital_v1,
)
from ingest.gate_facts import (
    GATE_FACTS_SCHEMA_VERSION,
    InvalidGateFacts,
    parse_gate_facts,
)
from ingest.models import BatchResult, Checkpoint
from ingest.orchestrator import run_connector
from ingest.product_type import (
    PRODUCT_TYPE_EVENT_PROGRAM,
    PRODUCT_TYPE_KIND_CONFIRMED,
    PRODUCT_TYPE_KIND_REVIEW,
    PRODUCT_TYPE_LIVING_GUIDE,
    PRODUCT_TYPE_POLICY_REFERENCE,
    PRODUCT_TYPE_RULE_VERSION,
    propose_product_type,
)
from ingest.region import extract_eligibility_facts
from ingest.relevance import classify_foreign_resident_eligibility
from ingest.source_identity import CANONICAL_CONTENT_SOURCE, CANONICAL_POLICY_SOURCE
from ingest.store import MemoryIngestStore
from test_ingest import (
    FakeConnector,
    NO_SLEEP,
    load_content,
    observation_for,
    policy_item,
)

FIXTURES = pathlib.Path(__file__).resolve().parent / "ingest" / "fixtures"
EVALUATOR_FIXTURE = FIXTURES / "capital_v1_evaluator.json"


def _policy_connector():
    return YouthcenterPolicyConnector(api_key_provider=lambda: "unused")


def _content_connector():
    return YouthcenterContentConnector(api_key_provider=lambda: "unused")


def _event_item(key: str, **extra: object) -> dict:
    extra.setdefault("plcyExplnCn", "이번 회차 신청과 개최 안내입니다. 재한 일본인은 신청 가능합니다.")
    extra.setdefault("plcySprtCn", extra["plcyExplnCn"])
    extra.setdefault("title", "수도권 행사")
    return policy_item(key, zip_cd="11680", oper_cd="11680", **extra)


def _v4_upsert(store: MemoryIngestStore, source_id: str, records) -> None:
    started = store.start_ingest_run(source_id)
    store.upsert_source_observations_v4(source_id, started.run_id, list(records), None)


def _ai_jobs(store: MemoryIngestStore, item):
    return [
        job
        for job in store.jobs.values()
        if job.source_item_id == item.id and job.processing_stage == "ai_enrichment"
    ]


def _stale_promote_to_target(store: MemoryIngestStore, item) -> None:
    item.disposition = "target"
    for job in store.jobs.values():
        if (
            job.source_item_id == item.id
            and job.revision_hash == item.revision_hash
            and job.processing_stage
            in {
                "region_review",
                "relevance_review",
                "content_review",
                "product_type_review",
            }
            and job.status in {"queued", "claimed"}
        ):
            job.status = "completed"


class ConnectorNormalizeTests(unittest.TestCase):
    def test_policy_connector_does_not_screen_or_choose_jobs(self) -> None:
        record = _policy_connector().to_observation(
            _event_item("p1"), permission_status="testing_only", enabled=True
        )
        self.assertIsNone(record.classifier_decision)
        self.assertIsNone(record.product_type_classification)
        self.assertEqual(record.jobs, ())
        self.assertIsNotNone(record.normalized_payload)
        self.assertIn("activity_location_text", record.normalized_payload or {})
        self.assertIn("zipCd", record.normalized_payload or {})
        src = inspect.getsource(YouthcenterPolicyConnector.to_observation)
        self.assertNotIn("screen_policy", src)
        self.assertNotIn("classifier_decision_metadata", src)

    def test_content_connector_does_not_lock_event_program(self) -> None:
        record = _content_connector().to_observation(
            load_content(), permission_status="testing_only", enabled=True
        )
        self.assertIsNone(record.product_type_classification)
        self.assertIsNone(record.classifier_decision)
        src = inspect.getsource(YouthcenterContentConnector.to_observation)
        self.assertNotIn("classify_content_product_type", src)
        self.assertNotIn("screen_content", src)


class ProductTypeProposalTests(unittest.TestCase):
    def test_propose_never_returns_living_guide(self) -> None:
        living = propose_product_type("생활 가이드와 이용 방법입니다.")
        self.assertNotEqual(living.product_type, PRODUCT_TYPE_LIVING_GUIDE)
        unclear = propose_product_type("설명입니다. 본문이 충분히 있습니다.")
        self.assertEqual(unclear.kind, PRODUCT_TYPE_KIND_REVIEW)
        self.assertIsNone(unclear.product_type)
        event = propose_product_type("이번 회차 신청과 개최 안내입니다.")
        self.assertEqual(event.product_type, PRODUCT_TYPE_EVENT_PROGRAM)
        standing = propose_product_type("상시 지원 자격과 이용 방법입니다.")
        self.assertEqual(standing.product_type, PRODUCT_TYPE_POLICY_REFERENCE)

    def test_product_type_rule_version_is_not_evaluator_id(self) -> None:
        self.assertNotEqual(PRODUCT_TYPE_RULE_VERSION, CAPITAL_V1_PROFILE)
        self.assertNotEqual(PRODUCT_TYPE_RULE_VERSION, EVALUATOR_CONTRACT_ID)
        self.assertNotEqual(PRODUCT_TYPE_RULE_VERSION, GATE_FACTS_SCHEMA_VERSION)


class EligibilityExtractTests(unittest.TestCase):
    def test_zip_tokens_are_specific_not_place_text(self) -> None:
        scope, codes, evidence = extract_eligibility_facts(
            zip_cd="11680,50110",
            text="서울에서 열리는 설명회입니다. 온라인 참여가 가능합니다.",
        )
        self.assertEqual(scope, "specific")
        self.assertEqual(codes, ("11", "50"))
        self.assertIn("11680", evidence)

    def test_online_is_not_nationwide(self) -> None:
        scope, codes, _evidence = extract_eligibility_facts(
            zip_cd="",
            text="한일 청년 교류 포럼입니다. 온라인 참여가 가능합니다.",
        )
        self.assertEqual(scope, "unknown")
        self.assertEqual(codes, ())

    def test_nationwide_phrase_without_zip(self) -> None:
        scope, codes, _evidence = extract_eligibility_facts(
            zip_cd="",
            text="전국 대상 청년 지원입니다. 거주 지역 제한 없음.",
        )
        self.assertEqual(scope, "nationwide")
        self.assertEqual(codes, ())

    def test_activity_location_is_not_eligibility(self) -> None:
        scope, codes, _evidence = extract_eligibility_facts(
            zip_cd="",
            text="행사는 서울 시청에서 개최합니다. 신청 자격 지역은 적혀 있지 않습니다.",
        )
        self.assertEqual(scope, "unknown")
        self.assertEqual(codes, ())


class ForeignEligibilityTests(unittest.TestCase):
    def test_three_states(self) -> None:
        self.assertEqual(
            classify_foreign_resident_eligibility(
                "재한 일본인은 신청 가능합니다. 서울 거주자를 대상으로 합니다."
            ),
            "eligible",
        )
        self.assertEqual(
            classify_foreign_resident_eligibility(
                "외국인 청년도 신청 가능합니다. 국적 제한 없음."
            ),
            "eligible",
        )
        self.assertEqual(
            classify_foreign_resident_eligibility(
                "대한민국 국민만 신청 가능합니다. 서울 거주자를 대상으로 합니다."
            ),
            "ineligible",
        )
        self.assertEqual(
            classify_foreign_resident_eligibility(
                "모든 주민이 이용할 수 있습니다. 서울 거주 청년 안내입니다."
            ),
            "unknown",
        )


class GateFactsParseTests(unittest.TestCase):
    def test_empty_object_is_not_complete(self) -> None:
        with self.assertRaises(InvalidGateFacts) as err:
            parse_gate_facts(PRODUCT_TYPE_EVENT_PROGRAM, {})
        self.assertEqual(err.exception.code, "gate_facts_incomplete")

    def test_event_rejects_audience_key(self) -> None:
        with self.assertRaises(InvalidGateFacts):
            parse_gate_facts(
                PRODUCT_TYPE_EVENT_PROGRAM,
                {
                    "schema_version": GATE_FACTS_SCHEMA_VERSION,
                    "eligibility_scope": "nationwide",
                    "eligibility_region_codes": [],
                    "eligibility_region_evidence": "",
                    "foreign_resident_eligibility": "eligible",
                },
            )

    def test_living_guide_rejects_region_keys(self) -> None:
        with self.assertRaises(InvalidGateFacts):
            parse_gate_facts(
                PRODUCT_TYPE_LIVING_GUIDE,
                {
                    "schema_version": GATE_FACTS_SCHEMA_VERSION,
                    "eligibility_scope": "nationwide",
                    "eligibility_region_codes": [],
                    "eligibility_region_evidence": "",
                },
            )

    def test_forbidden_legacy_keys(self) -> None:
        with self.assertRaises(InvalidGateFacts):
            parse_gate_facts(
                PRODUCT_TYPE_EVENT_PROGRAM,
                {
                    "schema_version": GATE_FACTS_SCHEMA_VERSION,
                    "eligibility_scope": "nationwide",
                    "eligibility_region_codes": [],
                    "eligibility_region_evidence": "",
                    "nationwide_or_online": True,
                },
            )


class EvaluatorFixtureParityTests(unittest.TestCase):
    def test_fixed_fixture_parity(self) -> None:
        cases = json.loads(EVALUATOR_FIXTURE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 14)
        for case in cases:
            with self.subTest(case["id"]):
                result = evaluate_capital_v1(
                    body_usable=case["body_usable"],
                    has_source_url=case["has_source_url"],
                    attachment_present=case["attachment_present"],
                    product_type=case["product_type"],
                    facts=case["facts"],
                )
                self.assertEqual(result.disposition, case["expect_disposition"])
                self.assertEqual(
                    [job.stage for job in result.jobs], case["expect_job_stages"]
                )
                self.assertEqual(result.region_status, case["expect_region_status"])
                self.assertEqual(result.audience_status, case["expect_audience_status"])
                self.assertEqual(result.evaluated_profile, CAPITAL_V1_PROFILE)
                self.assertEqual(result.evaluator_contract_id, EVALUATOR_CONTRACT_ID)

    def test_delivery_mode_and_activity_do_not_change_region(self) -> None:
        base = {
            "schema_version": GATE_FACTS_SCHEMA_VERSION,
            "eligibility_scope": "specific",
            "eligibility_region_codes": ["11"],
            "eligibility_region_evidence": "11680",
            "delivery_mode": "online",
        }
        online = evaluate_capital_v1(
            body_usable=True,
            has_source_url=True,
            attachment_present=False,
            product_type=PRODUCT_TYPE_EVENT_PROGRAM,
            facts=base,
        )
        offline = evaluate_capital_v1(
            body_usable=True,
            has_source_url=True,
            attachment_present=False,
            product_type=PRODUCT_TYPE_EVENT_PROGRAM,
            facts={**base, "delivery_mode": "offline"},
        )
        self.assertEqual(online.disposition, "target")
        self.assertEqual(offline.disposition, online.disposition)
        self.assertEqual(online.region_status, "passed")


class AssessmentPipelineTests(unittest.TestCase):
    def test_store_does_not_import_classifiers_to_choose_type(self) -> None:
        import ingest.store as store_mod

        source = inspect.getsource(store_mod)
        self.assertNotIn("classify_policy_product_type", source)
        self.assertNotIn("classify_content_product_type", source)
        self.assertNotIn("screen_policy", source)
        self.assertNotIn("screen_content", source)
        self.assertIn("propose_assessment", source)

    def test_assessment_runs_before_write_and_can_record_type_without_target(self) -> None:
        record = _policy_connector().to_observation(
            policy_item(
                "busan",
                zip_cd="50110",
                oper_cd="50110",
                plcyExplnCn="이번 회차 신청과 개최 안내입니다.",
                plcySprtCn="이번 회차 신청과 개최 안내입니다.",
            ),
            permission_status="testing_only",
            enabled=True,
        )
        self.assertIsNone(record.product_type_classification)
        assessed = assess_observation(record, source_kind="policy")
        self.assertEqual(assessed.disposition, "non_target")
        self.assertEqual(
            assessed.product_type_classification["product_type"],
            PRODUCT_TYPE_EVENT_PROGRAM,
        )
        self.assertEqual(
            assessed.product_type_classification["kind"], PRODUCT_TYPE_KIND_CONFIRMED
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "busan")]
        self.assertEqual(item.disposition, "non_target")
        row = store.product_types[(item.id, item.revision_hash)]
        self.assertEqual(row.product_type, PRODUCT_TYPE_EVENT_PROGRAM)
        self.assertIsNotNone(row.gate_facts)
        self.assertEqual(row.evaluated_profile, CAPITAL_V1_PROFILE)
        self.assertEqual(store.decisions, {})

    def test_v4_does_not_create_approve_ai(self) -> None:
        record = _policy_connector().to_observation(
            _event_item("fit"), permission_status="testing_only", enabled=True
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "fit")]
        self.assertEqual(item.disposition, "target")
        self.assertEqual(store.decisions, {})
        ais = [job for job in store.jobs.values() if job.processing_stage == "ai_enrichment"]
        self.assertEqual(len(ais), 1)
        self.assertEqual(ais[0].status, "queued")
        claimed = store.claim_processing_jobs("ai_enrichment", worker_id="w")
        self.assertEqual(len(claimed), 1)

    def test_unknown_product_type_has_review_job_not_row(self) -> None:
        record = _policy_connector().to_observation(
            policy_item("mix", zip_cd="11680", oper_cd="11680"),
            permission_status="testing_only",
            enabled=True,
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "mix")]
        self.assertEqual(item.disposition, "observe_only")
        self.assertNotIn((item.id, item.revision_hash), store.product_types)
        stages = {job.processing_stage for job in store.jobs.values()}
        self.assertEqual(stages, {"product_type_review"})

    def test_two_unknown_jobs_and_hard_fail_priority(self) -> None:
        both = _policy_connector().to_observation(
            policy_item(
                "both",
                zip_cd="",
                oper_cd="",
                plcyExplnCn="상시 지원 자격과 이용 방법입니다. 지역 주민 안내입니다.",
                plcySprtCn="상시 지원 자격과 이용 방법입니다.",
            ),
            permission_status="testing_only",
            enabled=True,
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [both])
        item = store.items[(CANONICAL_POLICY_SOURCE, "both")]
        self.assertEqual(item.disposition, "region_review_required")
        stages = {
            job.processing_stage
            for job in store.jobs.values()
            if job.source_item_id == item.id
        }
        self.assertEqual(stages, {"region_review", "relevance_review"})

        fail = _policy_connector().to_observation(
            policy_item(
                "fail",
                zip_cd="50110",
                oper_cd="50110",
                plcyExplnCn="상시 지원 자격과 이용 방법입니다. 지역 주민 안내입니다.",
                plcySprtCn="상시 지원 자격과 이용 방법입니다.",
            ),
            permission_status="testing_only",
            enabled=True,
        )
        store2 = MemoryIngestStore()
        _v4_upsert(store2, CANONICAL_POLICY_SOURCE, [fail])
        failed = store2.items[(CANONICAL_POLICY_SOURCE, "fail")]
        self.assertEqual(failed.disposition, "non_target")
        self.assertEqual(
            [
                job.processing_stage
                for job in store2.jobs.values()
                if job.source_item_id == failed.id
            ],
            [],
        )

    def test_event_has_no_audience_key_or_job(self) -> None:
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
        proposal = propose_assessment(record, source_kind="policy")
        self.assertEqual(
            proposal.product_type_classification.product_type, PRODUCT_TYPE_EVENT_PROGRAM
        )
        self.assertIsNone(proposal.gate_facts.foreign_resident_eligibility)
        self.assertNotIn(
            "foreign_resident_eligibility", proposal.gate_facts.to_payload()
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "evt")]
        stages = {job.processing_stage for job in store.jobs.values()}
        self.assertNotIn("relevance_review", stages)
        self.assertEqual(item.disposition, "region_review_required")

    def test_living_guide_is_not_auto_created(self) -> None:
        record = _policy_connector().to_observation(
            _event_item("lg"), permission_status="testing_only", enabled=True
        )
        proposal = propose_assessment(record, source_kind="policy")
        self.assertNotEqual(
            None
            if proposal.product_type_classification is None
            else proposal.product_type_classification.product_type,
            PRODUCT_TYPE_LIVING_GUIDE,
        )

    def test_kr_japan_activity_is_not_a_v4_target_reason(self) -> None:
        body = (
            "상시 지원 자격과 이용 방법입니다. "
            "한국 청년을 위한 일본 유학 지원 사업입니다. 서울·경기 거주자가 대상입니다."
        )
        record = _policy_connector().to_observation(
            policy_item(
                "study",
                zip_cd="11680",
                oper_cd="11680",
                plcyExplnCn=body,
                plcySprtCn=body,
            ),
            permission_status="testing_only",
            enabled=True,
        )
        v3 = observation_for(
            policy_item(
                "study-v3",
                zip_cd="11680",
                oper_cd="11680",
                plcyExplnCn=body,
                plcySprtCn=body,
            )
        )
        self.assertEqual(v3.disposition, "target")
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "study")]
        self.assertEqual(item.disposition, "region_review_required")
        stages = {job.processing_stage for job in store.jobs.values()}
        self.assertIn("relevance_review", stages)

    def test_orchestrator_uses_v4_write(self) -> None:
        store = MemoryIngestStore()
        item = _event_item("orch")
        result = run_connector(
            FakeConnector(
                batches=[
                    BatchResult(
                        items=(item,),
                        next_checkpoint=None,
                        natural_end=True,
                    )
                ]
            ),
            store,
            sleep=NO_SLEEP,
        )
        self.assertGreaterEqual(result.batches_ok, 1)
        stored = store.items[(CANONICAL_POLICY_SOURCE, "orch")]
        self.assertEqual(stored.disposition, "target")
        self.assertEqual(store.decisions, {})
        row = store.product_types[(stored.id, stored.revision_hash)]
        self.assertEqual(row.evaluated_profile, CAPITAL_V1_PROFILE)

    def test_v3_upsert_still_requires_classifier_on_target(self) -> None:
        from dataclasses import replace

        from ingest.rpc_errors import RpcFailure

        store = MemoryIngestStore()
        started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
        raw = observation_for(_event_item("legacy"))
        missing = replace(raw, classifier_decision=None)
        with self.assertRaises(RpcFailure) as err:
            store.upsert_source_observations(
                CANONICAL_POLICY_SOURCE, started.run_id, [missing], None
            )
        self.assertEqual(err.exception.code, "classifier_metadata_required")

    def test_content_v4_has_no_content_lock(self) -> None:
        raw = load_content()
        raw["pstTtl"] = "상시 제도 안내"
        raw["pstWholCn"] = (
            "<p>상시 지원 자격과 이용 방법입니다. 원문은 "
            "https://www.youthcenter.go.kr/notice/10789 입니다.</p>"
        )
        record = _content_connector().to_observation(
            raw, permission_status="testing_only", enabled=True
        )
        store = MemoryIngestStore()
        started = store.start_ingest_run(CANONICAL_CONTENT_SOURCE)
        store.upsert_source_observations_v4(
            CANONICAL_CONTENT_SOURCE, started.run_id, [record], Checkpoint.for_rest_page(2)
        )
        item = next(iter(store.items.values()))
        row = store.product_types.get((item.id, item.revision_hash))
        if row is not None:
            self.assertEqual(row.product_type, PRODUCT_TYPE_POLICY_REFERENCE)

    def test_resolve_gate_facts_reevaluates(self) -> None:
        body = "상시 지원 자격과 이용 방법입니다. 지역 주민 안내입니다."
        record = _policy_connector().to_observation(
            policy_item(
                "fix",
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
        item = store.items[(CANONICAL_POLICY_SOURCE, "fix")]
        self.assertEqual(item.disposition, "region_review_required")
        result = store.resolve_source_item_gate_facts(
            source_item_id=item.id,
            revision_hash=item.revision_hash,
            gate_facts={
                "schema_version": GATE_FACTS_SCHEMA_VERSION,
                "eligibility_scope": "nationwide",
                "eligibility_region_codes": [],
                "eligibility_region_evidence": "human",
                "foreign_resident_eligibility": "eligible",
            },
            assessment_schema_version=GATE_FACTS_SCHEMA_VERSION,
            reviewer="human:facts",
        )
        self.assertEqual(result.disposition, "target")
        self.assertEqual(store.items[(CANONICAL_POLICY_SOURCE, "fix")].disposition, "target")
        ais = [job for job in store.jobs.values() if job.processing_stage == "ai_enrichment"]
        self.assertEqual(len(ais), 1)

    def test_v1_empty_facts_do_not_claim(self) -> None:
        record = _policy_connector().to_observation(
            _event_item("empty"), permission_status="testing_only", enabled=True
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "empty")]
        row = store.product_types[(item.id, item.revision_hash)]
        row.gate_facts = {}
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="w"), []
        )

    def test_stale_target_unknown_region_cannot_ensure_or_claim(self) -> None:
        body = "이번 회차 개최 안내입니다. 재한 일본인은 참여 가능합니다."
        record = _policy_connector().to_observation(
            policy_item(
                "stale-region",
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
        item = store.items[(CANONICAL_POLICY_SOURCE, "stale-region")]
        row = store.product_types[(item.id, item.revision_hash)]
        self.assertEqual(row.gate_facts["eligibility_scope"], "unknown")
        _stale_promote_to_target(store, item)
        self.assertEqual(item.disposition, "target")
        store._ensure_queued_ai_job_v1(item, item.revision_hash, store._clock(), ())
        self.assertEqual(_ai_jobs(store, item), [])
        store._insert_job(
            item.id, item.revision_hash, "ai_enrichment", store._clock(), ()
        )
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="w"), []
        )

    def test_stale_target_unknown_audience_cannot_ensure_or_claim(self) -> None:
        body = "상시 지원 자격과 이용 방법입니다. 지역 주민 안내입니다."
        record = _policy_connector().to_observation(
            policy_item(
                "stale-aud",
                zip_cd="11680",
                oper_cd="11680",
                plcyExplnCn=body,
                plcySprtCn=body,
            ),
            permission_status="testing_only",
            enabled=True,
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "stale-aud")]
        row = store.product_types[(item.id, item.revision_hash)]
        self.assertEqual(row.gate_facts["foreign_resident_eligibility"], "unknown")
        _stale_promote_to_target(store, item)
        store._ensure_queued_ai_job_v1(item, item.revision_hash, store._clock(), ())
        self.assertEqual(_ai_jobs(store, item), [])
        store._insert_job(
            item.id, item.revision_hash, "ai_enrichment", store._clock(), ()
        )
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="w"), []
        )

    def test_complete_v1_evaluator_target_can_ensure_and_claim(self) -> None:
        record = _policy_connector().to_observation(
            _event_item("ready"), permission_status="testing_only", enabled=True
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "ready")]
        self.assertEqual(item.disposition, "target")
        ais = _ai_jobs(store, item)
        self.assertEqual(len(ais), 1)
        self.assertEqual(ais[0].status, "queued")
        claimed = store.claim_processing_jobs("ai_enrichment", worker_id="w")
        self.assertEqual(len(claimed), 1)

    def test_legacy_null_facts_approve_ai_can_still_claim(self) -> None:
        store = MemoryIngestStore()
        started = store.start_ingest_run(CANONICAL_POLICY_SOURCE)
        store.upsert_source_observations(
            CANONICAL_POLICY_SOURCE,
            started.run_id,
            [observation_for(_event_item("legacy-ai"))],
            None,
        )
        item = store.items[(CANONICAL_POLICY_SOURCE, "legacy-ai")]
        row = store.product_types[(item.id, item.revision_hash)]
        self.assertIsNone(row.gate_facts)
        self.assertTrue(store.decisions)
        claimed = store.claim_processing_jobs("ai_enrichment", worker_id="w")
        self.assertEqual(len(claimed), 1)

    def test_incomplete_facts_cannot_ensure_or_claim_either_path(self) -> None:
        record = _policy_connector().to_observation(
            _event_item("incomplete"), permission_status="testing_only", enabled=True
        )
        store = MemoryIngestStore()
        _v4_upsert(store, CANONICAL_POLICY_SOURCE, [record])
        item = store.items[(CANONICAL_POLICY_SOURCE, "incomplete")]
        row = store.product_types[(item.id, item.revision_hash)]
        row.gate_facts = {"schema_version": GATE_FACTS_SCHEMA_VERSION}
        _stale_promote_to_target(store, item)
        store._ensure_queued_ai_job_v1(item, item.revision_hash, store._clock(), ())
        leftover = _ai_jobs(store, item)
        self.assertTrue(
            leftover == [] or all(job.status == "cancelled" for job in leftover)
        )
        if leftover == []:
            store._insert_job(
                item.id, item.revision_hash, "ai_enrichment", store._clock(), ()
            )
        else:
            leftover[0].status = "queued"
        self.assertEqual(
            store.claim_processing_jobs("ai_enrichment", worker_id="w"), []
        )


if __name__ == "__main__":
    unittest.main()
