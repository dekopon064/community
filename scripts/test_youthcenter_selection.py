"""Synthetic discovery/RPC/AI regression only. No external services."""
from __future__ import annotations

import copy
import unittest
from datetime import date, datetime, timedelta, timezone

from ingest.assessment import propose_assessment
from ingest.connectors.youthcenter_content import YouthcenterContentConnector
from ingest.connectors.youthcenter_policy import YouthcenterPolicyConnector
from ingest.models import Checkpoint
from ingest.orchestrator import run_connector
from ingest.rpc_errors import RpcAmbiguous, RpcFailure, RpcTimeout
from ingest.source_identity import CANONICAL_CONTENT_SOURCE as CONTENT, CANONICAL_POLICY_SOURCE as POLICY
from ingest.store import LeaseLost, MemoryIngestStore
from ingest.supabase_store import SupabaseIngestStore, _v4_proposal_record
from ingest.youthcenter_selection import attach_selection, select_discovery
from test_ingest import FakeStreamResponse, NO_SLEEP
from test_ingest_supabase_store import FakeClient
from test_ingest_ai_worker import _ai_deps
from ingest.ai_worker import process_ai_jobs

TODAY = date(2030, 6, 15)
FUTURE = (TODAY + timedelta(days=10)).isoformat()
PAST = (TODAY - timedelta(days=1)).isoformat()
TARGET = "지원 대상: 외국인 주민."
REGION = "전국 거주자 신청 가능."
USE = "신청 방법: 홈페이지에서 신청 가능."


def policy(body: str, *, title="생활 지원 정책", key="synthetic-policy", **extra):
    item = {
        "plcyNo": key, "plcyNm": title, "plcyExplnCn": body,
        "plcySprtCn": "", "aplyUrlAddr": "https://example.invalid/apply",
        "aplyPrdSeCd": "0057001", "aplyYmd": FUTURE,
        "frstRegDt": "2030-06-15 12:00:00", "zipCd": "50110",
    }
    item.update(extra)
    return item


def content(body: str, *, title="체험 행사", key="1", **extra):
    item = {
        "bbsSn": "synthetic", "pstSn": key, "pstTtl": title,
        "pstWholCn": body, "pstUrlAddr": "https://example.invalid/detail",
        "frstRegDt": "2030-06-15 12:00:00", "pstSeNm": "행사",
    }
    item.update(extra)
    return item


def normalize(source, item):
    cls = YouthcenterPolicyConnector if source == POLICY else YouthcenterContentConnector
    return cls(api_key_provider=lambda: "fake").to_observation(
        item, permission_status="approved_noncommercial", enabled=True,
    )


def decision(source, item):
    return select_discovery(source, normalize(source, item), today=TODAY)


def active_content(body="", **extra):
    return content(f"{body}\n{REGION}\n{USE}\n행사일: {FUTURE}", **extra)


class PolicySelectionTests(unittest.TestCase):
    def test_clear_person_targets_and_unrestricted_nationality(self):
        for eligible in (
            TARGET, "신청 대상: 일본인 청년.", "외국인 주민도 신청 가능.",
            "신청 자격: 국적 제한 없음.", "국적에 관계없이 신청 가능.",
            "외국인만 신청 가능.", "외국인 주민은 지원 대상입니다.",
            "외국인 외에는 신청 불가.",
            "센터의 지원 대상: 외국인 주민.",
            "지원 대상: 19세 이상 외국인 주민.",
            "외국인 주민은 신청 가능. 외국인 중 미취업자는 신청 불가.",
        ):
            with self.subTest(eligible=eligible):
                result = decision(POLICY, policy(f"{eligible}\n{REGION}"))
                self.assertEqual(result.decision, "include")
                self.assertTrue(result.evidence)

    def test_unconfirmed_negative_indirect_and_institution_targets_excluded(self):
        for text in (
            "청년을 위한 지원 정책입니다.",
            "외국인 관련 연구를 소개합니다. 신청 대상: 청년.",
            "외국인 역사 소개. 신청 대상: 내국인 청년.",
            "외국인 역사 교육 신청 대상: 청년.",
            "기관 직원은 국적 제한 없음.",
            "일본 문화 관련 기관 지원입니다.",
            "지원 대상: 외국인 지원 기관 및 업체.",
            "지원 대상: 외국인 연구센터.",
            "외국인 대상 서비스를 개발하는 기업 모집.",
            "지원 대상: 외국인을 고용한 업체.",
            "외국인은 신청 불가.", "외국인은 지원할 수 없습니다.",
            "대한민국 국적자만 신청 가능. 외국인 주민 신청 가능.",
            "외국인은 신청 가능. 외국인은 지원 대상에서 제외.",
            "국적 제한 없음. 신청 대상: 외국인이 아닌 청년만.",
            "지원 대상: 외국인 주민 여부는 미확인.",
        ):
            with self.subTest(text=text):
                result = decision(POLICY, policy(f"{text}\n{REGION}"))
                self.assertEqual(result.decision, "exclude")
                self.assertIn("policy_direct_target_unconfirmed", result.reason_codes)

    def test_title_keywords_are_not_beneficiary_evidence(self):
        result = decision(POLICY, policy(f"청년 정책 안내. {REGION}", title="외국인 일본인 지원"))
        self.assertEqual(result.decision, "exclude")

    def test_target_exclusion_takes_precedence_over_missing_information(self):
        result = decision(POLICY, policy("문의", aplyUrlAddr="", aplyPrdSeCd=""))
        self.assertEqual(result.decision, "exclude")


class ContentSelectionTests(unittest.TestCase):
    def test_actionable_event_and_institution_promotion_ignore_nationality(self):
        for title in ("체험 행사", "기관 홍보 프로그램", "내국인 체험 행사"):
            with self.subTest(title=title):
                self.assertEqual(decision(CONTENT, active_content(title=title)).decision, "include")

    def test_pure_promotion_outcome_and_review_excluded(self):
        for title, body in (
            ("행사 홍보", "새로운 사업을 홍보합니다."),
            ("기관 소개", "성과 소개를 전합니다."),
            ("참여 후기", "축제에 참여한 후기를 소개합니다."),
            ("센터 소개", "우리 기관을 소개합니다."),
            ("참여 후기", "당시 신청 방법은 온라인이었습니다."),
        ):
            with self.subTest(title=title):
                result = decision(CONTENT, content(body, title=title))
                self.assertEqual(result.decision, "exclude")
                self.assertIn("use_information_missing", result.reason_codes)

    def test_job_training_requires_target_audience_or_purpose(self):
        for relevance in (TARGET, "외국인을 위한 취업 교육.", "일본인 청년 대상 직무 훈련."):
            with self.subTest(relevance=relevance):
                self.assertEqual(decision(CONTENT, active_content(relevance, title="취업 교육")).decision, "include")
        for relevance in (
            "누구나 신청 가능.", "국적 제한 없음.", "취업 교육에 일본 관련 기업을 소개.",
            "지원 대상: 외국인 지원 기관.", "외국인 대상이 아닌 취업 교육.",
            "외국인을 위한 교육이 아닙니다.", "외국인 대상 여부는 불명확.",
        ):
            with self.subTest(relevance=relevance):
                result = decision(CONTENT, active_content(relevance, title="취업 교육"))
                self.assertEqual(result.decision, "exclude")
                self.assertIn("job_training_target_unconfirmed", result.reason_codes)

    def test_event_label_cannot_bypass_main_job_training(self):
        result = decision(CONTENT, active_content("이력서 작성 교육과 면접 훈련.", title="청년 행사", pstSeNm="행사"))
        self.assertEqual(result.decision, "exclude")

    def test_incidental_training_mention_does_not_confirm_main_activity(self):
        result = decision(CONTENT, active_content("축제에서는 일반 취업 교육 성과도 소개합니다.", title="체험 축제"))
        self.assertEqual(result.decision, "review")
        self.assertIn("activity_type_uncertain", result.reason_codes)

    def test_unknown_type_and_tiny_body_remain_review(self):
        for item in (content("신청 가능", title="안내"), content("자세한 이용 정보는 미확인", title="안내")):
            with self.subTest(item=item):
                record = normalize(CONTENT, item)
                result = select_discovery(CONTENT, record, today=TODAY)
                self.assertEqual(result.decision, "review")
                self.assertIsNone(result.proposed_type)
                self.assertIn("activity_type_uncertain", result.reason_codes)
                self.assertTrue(record.body_usable)
                proposal = propose_assessment(attach_selection(record, result), source_id=CONTENT)
                self.assertEqual(proposal.product_type_classification.kind, "review")
                self.assertIsNone(proposal.gate_facts)

    def test_useful_current_capital_space_uses_existing_living_type_contract(self):
        item = content("공간 이용 안내. 주소: 서울특별시. 운영시간: 평일 9시~18시.", title="청년 공간")
        result = decision(CONTENT, item)
        self.assertEqual(result.decision, "include")
        self.assertEqual(result.proposed_type, "living_guide")
        self.assertEqual(result.region_codes, ("11",))
        self.assertNotIn("period_meaning_uncertain", result.reason_codes)
        record = attach_selection(normalize(CONTENT, item), result)
        proposed = _v4_proposal_record(record, source_id=CONTENT)
        self.assertEqual(proposed.product_type_classification["product_type"], "living_guide")
        self.assertNotIn("eligibility_scope", proposed.gate_facts)
        self.assertEqual(proposed.normalized_payload["discovery_selection"]["eligibility_region_codes"], ["11"])

    def test_space_venue_does_not_turn_training_into_living_information(self):
        result = decision(CONTENT, active_content(f"{TARGET}\n개최 장소: 서울 청년 공간.", title="취업 교육"))
        self.assertEqual(result.decision, "include")
        self.assertEqual(result.proposed_type, "event_program")

    def test_useful_space_with_old_application_date_is_not_silently_excluded(self):
        result = decision(CONTENT, content(f"시설 이용 안내. 주소: 서울. 운영시간: 평일 10시~18시.\n신청 마감일: {PAST}", title="청년 공간"))
        self.assertEqual(result.decision, "review")
        self.assertIn("period_evidence_conflict", result.reason_codes)


class EmploymentEventSelectionTests(unittest.TestCase):
    def test_job_briefings_and_preparation_events_cannot_bypass_audience_gate(self):
        for title in ("의료 IT직무설명회", "채용 설명회", "취업준비콘서트", "취업 준비 행사", "취업 지원 설명회"):
            with self.subTest(title=title):
                result = decision(CONTENT, active_content("누구나 신청 가능.", title=title))
                self.assertEqual(result.decision, "exclude")
                self.assertIn("job_training_target_unconfirmed", result.reason_codes)

    def test_job_main_purpose_in_body_and_explicit_target_or_support_purpose(self):
        for target in ("참여 대상: 외국인 주민.", "일본인 유학생도 참여 가능.",
                       "외국인 취업 지원 직무설명회입니다.", "외국인 주민을 위한 취업 준비 행사입니다."):
            with self.subTest(target=target):
                result = decision(CONTENT, active_content(target, title="직무설명회"))
                self.assertEqual(result.decision, "include")
        result = decision(CONTENT, active_content("주된 활동: 의료 IT직무설명회.", title="청년 교류 행사"))
        self.assertEqual(result.decision, "exclude")
        self.assertIn("job_training_target_unconfirmed", result.reason_codes)

    def test_negative_institution_company_mentions_and_keywords_do_not_supply_target(self):
        for body in ("일본 기업의 의료IT 직무를 소개합니다.", "외국인 취업 통계를 소개합니다.",
                     "참여 대상: 외국인 주민. 외국인은 신청 불가.",
                     "지원 대상: 외국인 지원 기관 및 업체.", "국적에 관계없이 누구나 신청 가능.",
                     "외국인 주민을 위한 취업 행사가 아닙니다."):
            with self.subTest(body=body):
                result = decision(CONTENT, active_content(body, title="취업준비 콘서트"))
                self.assertEqual(result.decision, "exclude")
                self.assertIn("job_training_target_unconfirmed", result.reason_codes)

    def test_culture_incidental_job_talk_and_uncertain_main_activity_are_distinct(self):
        cultural = decision(CONTENT, active_content("음악 공연 중 취업 이야기도 나눕니다.", title="문화 공연 행사"))
        self.assertEqual(cultural.decision, "include")
        uncertain = decision(CONTENT, active_content("부대 프로그램으로 직무설명회를 소개합니다.", title="문화 교류 행사"))
        self.assertEqual(uncertain.decision, "review")
        self.assertIn("activity_type_uncertain", uncertain.reason_codes)
        self.assertNotIn("job_training_target_unconfirmed", uncertain.reason_codes)


class RegionAndPeriodTests(unittest.TestCase):
    def test_nationwide_noncapital_venue_and_api_codes_not_overexcluded(self):
        for source, item in (
            (POLICY, policy(f"{TARGET}\n{REGION}\n개최 장소: 제주도.")),
            (CONTENT, active_content("개최 장소: 제주도.")),
        ):
            with self.subTest(source=source):
                result = decision(source, item)
                self.assertEqual(result.decision, "include")
                self.assertEqual(result.region_scope, "nationwide")
                self.assertEqual(result.region_codes, ())

    def test_only_explicit_noncapital_residence_is_excluded(self):
        for text, expected in (
            ("지원 대상: 제주도 거주자만 신청 가능.", "exclude"),
            ("서울 개최, 신청 대상: 제주도 거주자만 신청 가능.", "exclude"),
            ("개최 장소: 제주도. 기관 주소: 서울특별시.", "review"),
            ("온라인 프로그램 참여 가능.", "review"),
            ("전국 기관을 소개합니다.", "review"),
            ("제주도 거주 청년 지원.", "review"),
            ("지원 대상: 제주도 거주 청년 우선 지원.", "review"),
            ("수도권 거주자는 신청 불가.", "exclude"),
            ("서울 거주자는 제외하고 신청 가능.", "review"),
            ("지원 대상: 서울 거주 청년 신청 가능.", "include"),
            ("지원 대상: 수도권 거주자 신청 가능.", "include"),
        ):
            with self.subTest(text=text):
                self.assertEqual(decision(POLICY, policy(f"{TARGET}\n{text}")).decision, expected)

    def test_conflicting_region_evidence_goes_to_review(self):
        result = decision(POLICY, policy(f"{TARGET}\n{REGION}\n신청 대상: 제주도 거주자만."))
        self.assertEqual(result.decision, "review")
        self.assertIn("region_evidence_conflict", result.reason_codes)

    def test_nationwide_mentions_are_not_eligibility_evidence(self):
        result = decision(POLICY, policy(f"{TARGET}\n전국 청년의 활동 성과를 소개합니다."))
        self.assertEqual(result.decision, "review")
        self.assertIn("region_scope_unknown", result.reason_codes)

    def test_preregistration_and_date_unit_end_are_included(self):
        for end in (FUTURE, TODAY.isoformat()):
            with self.subTest(end=end):
                result = decision(POLICY, policy(f"{TARGET}\n{REGION}", aplyYmd=f"{TODAY.isoformat()}~{end}"))
                self.assertEqual(result.decision, "include")

    def test_finished_applications_and_events_excluded(self):
        for source, item, reason in (
            (POLICY, policy(f"{TARGET}\n{REGION}", aplyYmd=PAST), "application_ended"),
            (POLICY, policy(f"{TARGET}\n{REGION}", aplyPrdSeCd="0057003"), "application_closed"),
            (CONTENT, content(f"{REGION}\n{USE}\n행사일: {PAST}"), "event_ended"),
            (CONTENT, content(f"{REGION}\n{USE}\n접수가 마감되었습니다."), "application_closed"),
            (CONTENT, content(f"{REGION}\n{USE}\n행사가 종료되었습니다."), "event_ended"),
        ):
            with self.subTest(source=source, reason=reason):
                result = decision(source, item)
                self.assertEqual(result.decision, "exclude")
                self.assertIn(reason, result.reason_codes)

    def test_ongoing_api_code_does_not_override_explicit_closed_text(self):
        result = decision(POLICY, policy(f"{TARGET}\n{REGION}\n접수가 마감되었습니다.", aplyPrdSeCd="0057002"))
        self.assertEqual(result.decision, "exclude")
        self.assertIn("application_closed", result.reason_codes)

    def test_conflicting_api_and_body_deadlines_require_review(self):
        result = decision(POLICY, policy(f"{TARGET}\n{REGION}\n신청 마감일: {PAST}", aplyYmd=FUTURE))
        self.assertEqual(result.decision, "review")
        self.assertIn("period_evidence_conflict", result.reason_codes)

    def test_current_standing_policy_preserved_but_word_alone_not_enough(self):
        for text, expected in (("상시 신청 가능.", "include"), ("신청은 상시 가능.", "include"), ("상시 정책.", "review")):
            with self.subTest(text=text):
                result = decision(POLICY, policy(f"{TARGET}\n{REGION}\n{text}", aplyPrdSeCd="0057002"))
                self.assertEqual(result.decision, expected)

    def test_registration_update_dates_and_yearless_dates_not_periods(self):
        for text in (
            "", "행사일: 6월 1일", "행사일: 내일", f"행사일: {PAST} 18:00",
            f"행사기간: {FUTURE}~{PAST}", f"기관 운영기간: {PAST}",
        ):
            with self.subTest(text=text):
                result = decision(CONTENT, content(f"{REGION}\n{USE}\n{text}", frstRegDt=PAST, lastMdfcnDt=PAST))
                self.assertEqual(result.decision, "review")
                self.assertIn("period_meaning_uncertain", result.reason_codes)

    def test_no_inferred_age_nationality_or_residence_facts(self):
        record = normalize(CONTENT, active_content("참여 대상: 만 19세 이상 외국인."))
        original = copy.deepcopy(record)
        selection = select_discovery(CONTENT, record, today=TODAY)
        prepared = attach_selection(record, selection)
        proposal = _v4_proposal_record(prepared, source_id=CONTENT)
        self.assertEqual(record, original)
        self.assertEqual(proposal.normalized_payload["plain_text"], original.normalized_payload["plain_text"])
        self.assertNotIn("age", proposal.gate_facts)
        self.assertNotIn("nationality", proposal.gate_facts)
        self.assertEqual(proposal.revision_hash, original.revision_hash)
        self.assertEqual(proposal.application_deadline, original.application_deadline)


class PageHttp:
    def __init__(self, pages):
        self.pages = pages
        self.request_count = 0
        self.params = []

    def get_json(self, _url, **kwargs):
        self.request_count += 1
        self.params.append(kwargs["params"])
        rows = self.pages[kwargs["params"]["pageNum"] - 1]
        return {"result": {"youthPolicyList": copy.deepcopy(rows)}}, 200, 100


class SpyMemoryStore(MemoryIngestStore):
    def __init__(self, error=None):
        super().__init__()
        self.calls = []
        self.error = error

    def upsert_source_observations_v4(self, source_id, run_id, records, checkpoint):
        self.calls.append((copy.deepcopy(records), checkpoint))
        if self.error:
            raise self.error
        return super().upsert_source_observations_v4(source_id, run_id, records, checkpoint)


class DiscoveryConnectionTests(unittest.TestCase):
    def test_all_excluded_page_does_not_end_scan_and_checkpoint_uses_raw_page(self):
        denied = [policy("일반 청년 지원", key=str(i)) for i in range(5)]
        allowed = policy(f"{TARGET}\n{REGION}", key="allowed")
        http = PageHttp([denied, [allowed]])
        store = SpyMemoryStore()
        connector = YouthcenterPolicyConnector(http=http, api_key_provider=lambda: "fake")
        result = run_connector(connector, store, sleep=NO_SLEEP, discovered_on=TODAY)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "short_batch")
        self.assertEqual(result.batches_ok, 2)
        self.assertEqual(http.request_count, 2)
        self.assertEqual(store.calls[0], ([], Checkpoint.for_rest_page(2)))
        self.assertEqual(result.selection_counts, {"exclude": 5, "include": 1})
        self.assertEqual(list(store.items), [(POLICY, "allowed")])
        self.assertEqual(set(http.params[0]), {"apiKeyNm", "pageNum", "pageSize", "pageType", "rtnType"})

    def test_filtered_items_do_not_consume_rpc_indices_or_look_unchanged(self):
        allowed = policy(f"{TARGET}\n{REGION}")
        for outcome in ("new", "changed", "unchanged"):
            with self.subTest(outcome=outcome):
                client = FakeClient({
                    "get_ingest_source": lambda p: [{"source_id": POLICY, "enabled": True, "permission_status": "approved_noncommercial", "legacy_curation_source": "youthcenter"}],
                    "start_ingest_run": lambda p: [{"run_id": "11111111-1111-1111-1111-111111111111", "bootstrap_complete": True, "committed_checkpoint": None, "skipped": False, "skip_reason": None}],
                    "upsert_source_observations_v4": lambda p: [{"input_index": 0, "external_key": allowed["plcyNo"], "outcome": outcome, "duplicate_in_batch": False}],
                    "finish_ingest_run": lambda p: [{"status": p["p_status"], "stop_reason": p["p_stop_reason"]}],
                })
                connector = YouthcenterPolicyConnector(http=PageHttp([[policy("일반 청년 지원", key="denied"), allowed]]), api_key_provider=lambda: "fake")
                result = run_connector(connector, SupabaseIngestStore(client), sleep=NO_SLEEP, discovered_on=TODAY)
                self.assertEqual(result.status, "complete")
                calls = [p for name, p in client.calls if name == "upsert_source_observations_v4"]
                self.assertEqual(len(calls), 1)
                rpc_item = calls[0]["p_items"][0]
                self.assertEqual(len(calls[0]["p_items"]), 1)
                self.assertEqual(rpc_item["gate_facts"]["eligibility_scope"], "nationwide")
                self.assertEqual(rpc_item["product_type_classification"]["product_type"], "policy_reference")
                self.assertEqual(rpc_item["normalized_payload"]["discovery_selection"]["decision"], "include")
                self.assertEqual(client.table_calls, [])
                self.assertEqual({n for n, _ in client.calls}, {"get_ingest_source", "start_ingest_run", "upsert_source_observations_v4", "finish_ingest_run"})

    def test_v4_bad_response_identity_shape_count_and_outcome_rejected_once(self):
        raw = normalize(POLICY, policy(f"{TARGET}\n{REGION}"))
        record = attach_selection(raw, select_discovery(POLICY, raw, today=TODAY))
        valid = {"input_index": 0, "external_key": record.external_key, "outcome": "new", "duplicate_in_batch": False}
        malformed = (
            None, {}, [None], [], [valid, valid],
            [{key: value for key, value in valid.items() if key != "outcome"}],
            [{**valid, "input_index": True}], [{**valid, "external_key": "other"}],
            [{**valid, "outcome": "excluded"}], [{**valid, "duplicate_in_batch": "false"}],
        )
        for response in malformed:
            with self.subTest(response=response):
                client = FakeClient({"upsert_source_observations_v4": lambda p: response})
                with self.assertRaises(RpcAmbiguous):
                    SupabaseIngestStore(client).upsert_source_observations_v4(POLICY, "run", [record], None)
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(client.calls[0][1]["p_items"][0]["revision_hash"], raw.revision_hash)

    def test_bad_v4_reply_cannot_finish_collector_as_processed(self):
        client = FakeClient({
            "get_ingest_source": lambda p: [{"source_id": POLICY, "enabled": True, "permission_status": "approved_noncommercial", "legacy_curation_source": "youthcenter"}],
            "start_ingest_run": lambda p: [{"run_id": "11111111-1111-1111-1111-111111111111", "bootstrap_complete": False, "committed_checkpoint": None, "skipped": False, "skip_reason": None}],
            "upsert_source_observations_v4": lambda p: [],
            "finish_ingest_run": lambda p: [{"status": p["p_status"], "stop_reason": p["p_stop_reason"]}],
        })
        connector = YouthcenterPolicyConnector(http=PageHttp([[policy(f"{TARGET}\n{REGION}")]]), api_key_provider=lambda: "fake")
        result = run_connector(connector, SupabaseIngestStore(client), sleep=NO_SLEEP, discovered_on=TODAY)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.batches_ok, 0)
        self.assertEqual(result.stop_reason, "rpc_error")
        self.assertEqual(len([n for n, _ in client.calls if n == "upsert_source_observations_v4"]), 1)

    def test_http_failure_after_exclusion_keeps_only_committed_checkpoint(self):
        store = SpyMemoryStore()
        http = PageHttp([[policy("일반 청년 정책", key=str(i)) for i in range(5)]])
        original_get = http.get_json
        from ingest.http_client import HttpRequestFailed

        def get(_url, **kwargs):
            if kwargs["params"]["pageNum"] == 2:
                http.request_count += 1
                raise HttpRequestFailed()
            return original_get(_url, **kwargs)

        http.get_json = get
        result = run_connector(YouthcenterPolicyConnector(http=http, api_key_provider=lambda: "fake"), store, sleep=NO_SLEEP, discovered_on=TODAY)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.stop_reason, "http_error")
        self.assertEqual(result.batches_ok, 1)
        self.assertEqual(store.sync[POLICY].committed_checkpoint, {"page_num": 2})
        self.assertEqual(len(store.calls), 1)
        self.assertEqual(http.request_count, 2)

    def test_review_reasons_reach_current_review_contract_without_fabricated_facts(self):
        item = content("신청 가능", title="안내")
        store = SpyMemoryStore()
        connector = YouthcenterContentConnector(http=PageHttp([[item]]), api_key_provider=lambda: "fake")
        result = run_connector(connector, store, sleep=NO_SLEEP, discovered_on=TODAY)
        self.assertEqual(result.status, "complete")
        current = store.items[(CONTENT, "synthetic:1")]
        reviews = [j for j in store.jobs.values() if j.source_item_id == current.id]
        self.assertTrue(any("activity_type_uncertain" in j.reason_codes and j.processing_stage == "content_review" for j in reviews))
        self.assertFalse(any(j.processing_stage == "ai_enrichment" for j in reviews))
        self.assertEqual(current.normalized_payload["plain_text"], "신청 가능")
        self.assertEqual(current.normalized_payload["discovery_selection"]["decision"], "review")
        request = _v4_proposal_record(store.calls[0][0][0], source_id=CONTENT).to_rpc_item()
        self.assertNotIn("gate_facts", request)
        self.assertEqual(request["jobs"], [])
        self.assertNotIn("product_type", request["product_type_classification"])

    def test_empty_body_review_contract_gap_is_not_silently_excluded_or_saved(self):
        for title in ("안내", "기관 홍보"):
            with self.subTest(title=title):
                record = normalize(CONTENT, content("", title=title, activity_location_text="방문 안내: 예약 후 방문 가능."))
                selection = select_discovery(CONTENT, record, today=TODAY)
                self.assertEqual(selection.decision, "review")
                self.assertNotIn("empty_item_no_use_information", selection.reason_codes)
                self.assertNotIn("use_information_missing", selection.reason_codes)
                self.assertTrue(selection.evidence)
                with self.assertRaisesRegex(ValueError, "empty_body_review_contract_required"):
                    _v4_proposal_record(attach_selection(record, selection), source_id=CONTENT)

    def test_existing_human_facts_and_history_are_not_rejudged_by_filter(self):
        store = SpyMemoryStore()
        record = normalize(POLICY, policy(f"{TARGET}\n{REGION}"))
        record = attach_selection(record, select_discovery(POLICY, record, today=TODAY))
        started = store.start_ingest_run(POLICY)
        store.upsert_source_observations_v4(POLICY, started.run_id, [record], None)
        current = store.items[(POLICY, record.external_key)]
        store.resolve_source_item_user_category(source_item_id=current.id, revision_hash=current.revision_hash, user_category="policy", event_start_on=None, event_end_on=None, reviewer="human:test")
        store.finish_ingest_run(started.run_id, status="complete", stop_reason="short_batch", http_request_count=0, bootstrap_complete=True)
        before = copy.deepcopy((store.items, store.product_types, store.user_categories, store.application_deadlines, store.jobs, store.candidates))
        # Ended/empty discoveries are omitted, never written as non_target.
        for item in (
            policy(f"{TARGET}\n{REGION}", aplyYmd=PAST),
            policy("", aplyUrlAddr=None, aplyPrdSeCd="0057002", aplyYmd=None),
        ):
            with self.subTest(item=item):
                connector = YouthcenterPolicyConnector(http=PageHttp([[item]]), api_key_provider=lambda: "fake")
                result = run_connector(connector, store, sleep=NO_SLEEP, discovered_on=TODAY)
                self.assertEqual(result.selection_counts, {"exclude": 1})
                self.assertEqual((store.items, store.product_types, store.user_categories, store.application_deadlines, store.jobs, store.candidates), before)

    def test_timeout_and_ambiguous_store_failures_do_not_retry_or_commit(self):
        for error in (RpcTimeout(), RpcAmbiguous()):
            with self.subTest(error=error):
                store = SpyMemoryStore(error)
                http = PageHttp([[policy(f"{TARGET}\n{REGION}")]])
                result = run_connector(YouthcenterPolicyConnector(http=http, api_key_provider=lambda: "fake"), store, sleep=NO_SLEEP, discovered_on=TODAY)
                self.assertEqual(result.status, "failed")
                self.assertIn(result.stop_reason, {"rpc_timeout", "rpc_error"})
                self.assertEqual(len(store.calls), 1)
                self.assertEqual(http.request_count, 1)
                self.assertEqual(store.items, {})
                self.assertIsNone(store.sync[POLICY].committed_checkpoint)

    def test_page_item_and_http_limits_remain_raw_limits(self):
        pages = [[policy("일반 청년 지원", key=f"{page}-{i}") for i in range(5)] for page in range(5)]
        store = SpyMemoryStore()
        http = PageHttp(pages)
        connector = YouthcenterPolicyConnector(http=http, api_key_provider=lambda: "fake")
        result = run_connector(connector, store, sleep=NO_SLEEP, discovered_on=TODAY)
        self.assertEqual(result.batches_ok, 5)
        self.assertEqual(http.request_count, 5)
        self.assertEqual(result.selection_counts, {"exclude": 25})
        self.assertEqual(store.items, {})
        store = SpyMemoryStore()
        http = PageHttp(pages)
        connector = YouthcenterPolicyConnector(http=http, api_key_provider=lambda: "fake")
        connector.http_budget = 1
        result = run_connector(connector, store, sleep=NO_SLEEP, discovered_on=TODAY)
        self.assertEqual(result.stop_reason, "http_budget_exhausted")
        self.assertEqual(http.request_count, 1)
        self.assertEqual(result.batches_ok, 1)

    def test_default_connectors_make_one_http_attempt(self):
        for cls in (YouthcenterPolicyConnector, YouthcenterContentConnector):
            with self.subTest(source=cls):
                connector = cls(api_key_provider=lambda: "fake")
                calls = []
                connector.http.transport = lambda *a, **k: (calls.append(1) or FakeStreamResponse(503))
                store = SpyMemoryStore()
                result = run_connector(connector, store, sleep=NO_SLEEP, discovered_on=TODAY)
                self.assertEqual(result.stop_reason, "http_503")
                self.assertEqual(len(calls), 1)
                self.assertEqual(store.calls, [])

    def test_other_sources_do_not_opt_in_and_source_mismatch_is_rejected(self):
        record = normalize(POLICY, policy(f"{TARGET}\n{REGION}"))
        for source in ("myseoul_program", "seoul_reservation", "future_policy"):
            self.assertIsNone(select_discovery(source, record, today=TODAY))
            self.assertEqual(_v4_proposal_record(record, source_id=source), _v4_proposal_record(record))
        selection = select_discovery(POLICY, record, today=TODAY)
        with self.assertRaisesRegex(ValueError, "discovery_source_mismatch"):
            _v4_proposal_record(attach_selection(record, selection), source_id=CONTENT)

    def test_excluded_input_cannot_be_submitted_directly(self):
        record = normalize(POLICY, policy("청년 정책 소개"))
        with self.assertRaisesRegex(ValueError, "excluded_discovery_not_storable"):
            _v4_proposal_record(attach_selection(record, select_discovery(POLICY, record, today=TODAY)), source_id=POLICY)


class EmptyItemDiscoveryTests(unittest.TestCase):
    def fake_client(self, source=CONTENT, upsert=None):
        def normal_reply(params):
            return [
                {"input_index": i, "external_key": item["external_key"],
                 "outcome": "new", "duplicate_in_batch": False}
                for i, item in enumerate(params["p_items"])
            ]

        return FakeClient({
            "get_ingest_source": lambda p: [{"source_id": source, "enabled": True, "permission_status": "approved_noncommercial", "legacy_curation_source": "youthcenter"}],
            "start_ingest_run": lambda p: [{"run_id": "11111111-1111-1111-1111-111111111111", "bootstrap_complete": False, "committed_checkpoint": None, "skipped": False, "skip_reason": None}],
            "upsert_source_observations_v4": upsert or normal_reply,
            "finish_ingest_run": lambda p: [{"status": p["p_status"], "stop_reason": p["p_stop_reason"]}],
        })

    def run_pages(self, pages, client):
        http = PageHttp(pages)
        connector = YouthcenterContentConnector(http=http, api_key_provider=lambda: "fake")
        result = run_connector(connector, SupabaseIngestStore(client), sleep=NO_SLEEP, discovered_on=TODAY)
        # No AI, claim, table DML, link or attachment retrieval path is called.
        self.assertEqual(client.table_calls, [])
        self.assertEqual({name for name, _ in client.calls}, {
            "get_ingest_source", "start_ingest_run", "upsert_source_observations_v4", "finish_ingest_run",
        })
        return result, http, [p for name, p in client.calls if name == "upsert_source_observations_v4"]

    def test_empty_unattached_without_use_information_is_excluded_not_storable(self):
        for source, item in (
            (CONTENT, content("")),
            (CONTENT, content("<p>  </p>\n", title="외국인 신청 가능 행사")),
            (CONTENT, content("", activity_location_text="부산광역시", pstSeNm="신청 안내")),
            (POLICY, policy("", title="외국인 신청 지원 정책", aplyUrlAddr=None, aplyPrdSeCd="0057002", aplyYmd=None)),
        ):
            with self.subTest(source=source, item=item):
                before = copy.deepcopy(item)
                record = normalize(source, item)
                original = copy.deepcopy(record)
                selection = select_discovery(source, record, today=TODAY)
                self.assertEqual(selection.decision, "exclude")
                self.assertIn("empty_item_no_use_information", selection.reason_codes)
                self.assertEqual(record, original)
                self.assertEqual(item, before)
                with self.assertRaisesRegex(ValueError, "excluded_discovery_not_storable"):
                    _v4_proposal_record(attach_selection(record, selection), source_id=source)

    def test_other_application_fields_do_not_prove_policy_target_or_empty_item(self):
        for extra in (
            {"aplyPrdSeCd": "0057002", "aplyYmd": None},
            {"aplyUrlAddr": None},
        ):
            with self.subTest(extra=extra):
                selection = decision(POLICY, policy("", **extra))
                self.assertEqual(selection.decision, "exclude")
                self.assertIn("policy_direct_target_unconfirmed", selection.reason_codes)
                self.assertNotIn("empty_item_no_use_information", selection.reason_codes)

    def test_mixed_empty_normal_and_review_reach_only_real_rpc_inputs(self):
        pages = [[content("", key="empty"), active_content(key="normal"), content("신청 가능", title="안내", key="review")]]
        before = copy.deepcopy(pages)
        expected = [normalize(CONTENT, item) for item in pages[0][1:]]
        result, http, calls = self.run_pages(pages, self.fake_client())
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.selection_counts, {"exclude": 1, "include": 1, "review": 1})
        self.assertEqual(result.selection_reasons["empty_item_no_use_information"], 1)
        self.assertEqual(result.batches_ok, 1)
        self.assertEqual(http.request_count, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]["p_items"]), 2)
        for row, record in zip(calls[0]["p_items"], expected):
            self.assertEqual(row["external_key"], record.external_key)
            self.assertEqual(row["revision_hash"], record.revision_hash)
            self.assertEqual(row["normalized_payload"]["plain_text"], record.normalized_payload["plain_text"])
            self.assertEqual(row["body_usable"], record.body_usable)
            self.assertEqual(row["jobs"], [])
        self.assertEqual(calls[0]["p_items"][1]["product_type_classification"]["kind"], "review")
        self.assertNotIn("gate_facts", calls[0]["p_items"][1])
        self.assertEqual(pages, before)

    def test_all_empty_page_and_later_mixed_page_keep_raw_page_checkpoints(self):
        pages = [
            [content("", key=f"empty-{i}") for i in range(5)],
            [content("", key="empty-next"), active_content(key="normal"),
             content("신청 가능", title="안내", key="review"), content("", key="empty-last"), active_content(key="normal-next")],
            [active_content(key="final")],
        ]
        result, http, calls = self.run_pages(pages, self.fake_client())
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.stop_reason, "short_batch")
        self.assertEqual(result.batches_ok, 3)
        self.assertEqual(result.selection_counts, {"exclude": 7, "include": 3, "review": 1})
        self.assertEqual([p["pageNum"] for p in http.params], [1, 2, 3])
        self.assertEqual([len(p["p_items"]) for p in calls], [0, 3, 1])
        self.assertEqual([p["p_next_checkpoint"] for p in calls], [{"page_num": 2}, {"page_num": 3}, None])

    def test_short_useful_body_and_attachment_review_are_saved_as_before(self):
        items = [content("신청 가능", title="안내", key="short"),
                 content("", title="안내", key="attachment", atchFile="synthetic attachment")]
        before = copy.deepcopy(items)
        store = SpyMemoryStore()
        http = PageHttp([items])
        result = run_connector(YouthcenterContentConnector(http=http, api_key_provider=lambda: "fake"), store, sleep=NO_SLEEP, discovered_on=TODAY)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.selection_counts, {"review": 2})
        self.assertNotIn("empty_item_no_use_information", result.selection_reasons)
        self.assertEqual(len(store.items), 2)
        self.assertEqual(len(store.calls), 1)
        attached = store.items[(CONTENT, "synthetic:attachment")]
        self.assertTrue(attached.attachment_present)
        self.assertEqual(attached.normalized_payload["plain_text"], "")
        self.assertEqual(attached.disposition, "attachment_dependent")
        self.assertTrue(any("attachment_dependent" in j.reason_codes for j in store.jobs.values()))
        self.assertFalse(any(j.processing_stage == "ai_enrichment" for j in store.jobs.values()))
        self.assertEqual(items, before)
        self.assertEqual(http.request_count, 1)

    def test_useful_empty_body_unsupported_contract_still_fails_batch_before_rpc(self):
        pages = [[content("", key="excluded"), content("", key="useful", title="안내", activity_location_text="방문 안내: 예약 후 방문 가능."), active_content(key="normal")]]
        client = self.fake_client()
        http = PageHttp(pages)
        result = run_connector(YouthcenterContentConnector(http=http, api_key_provider=lambda: "fake"), SupabaseIngestStore(client), sleep=NO_SLEEP, discovered_on=TODAY)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.stop_reason, "rpc_error")
        self.assertEqual(result.batches_ok, 0)
        self.assertEqual(result.selection_counts, {"exclude": 1, "review": 1, "include": 1})
        self.assertEqual([n for n, _ in client.calls], ["get_ingest_source", "start_ingest_run", "finish_ingest_run"])
        self.assertEqual(http.request_count, 1)

    def test_failed_second_rpc_keeps_previous_success_and_is_not_retried(self):
        for error, reason in ((RpcFailure("rpc_failure"), "rpc_error"), (RpcTimeout(), "rpc_timeout"),
                              (RpcAmbiguous(), "rpc_error"), (LeaseLost(), "lease_lost"), (None, "rpc_error")):
            with self.subTest(error=error):
                confirmed = []
                attempts = []

                def upsert(params):
                    attempts.append(copy.deepcopy(params))
                    if len(attempts) == 2:
                        return error  # None models an unconfirmable response, never success.
                    confirmed.append(copy.deepcopy(params))
                    return [{"input_index": 0, "external_key": params["p_items"][0]["external_key"], "outcome": "new", "duplicate_in_batch": False}]

                client = self.fake_client(upsert=upsert)
                pages = [[active_content(key="saved"), *[content("", key=f"empty-{i}") for i in range(4)]],
                         [content("", key="excluded"), active_content(key="unconfirmed")]]
                result, http, calls = self.run_pages(pages, client)
                self.assertEqual(result.status, "incomplete")
                self.assertEqual(result.stop_reason, reason)
                self.assertEqual(result.batches_ok, 1)
                self.assertEqual(result.selection_counts, {"include": 2, "exclude": 5})
                self.assertEqual(len(calls), 2)
                self.assertEqual(http.request_count, 2)
                self.assertEqual(confirmed[0]["p_next_checkpoint"], {"page_num": 2})
                self.assertEqual(len(confirmed), 1)
                finish = [p for n, p in client.calls if n == "finish_ingest_run"][0]
                self.assertEqual(finish["p_batches_ok"], 1)
                self.assertFalse(finish["p_bootstrap_complete"])

    def test_five_empty_pages_keep_observation_limits_and_http_budget(self):
        pages = [[content("", key=f"{page}-{i}") for i in range(5)] for page in range(5)]
        for budget, count, reason in ((15, 5, "bootstrap_range_complete"), (1, 1, "http_budget_exhausted")):
            with self.subTest(budget=budget):
                http = PageHttp(pages)
                store = SpyMemoryStore()
                connector = YouthcenterContentConnector(http=http, api_key_provider=lambda: "fake")
                connector.http_budget = budget
                result = run_connector(connector, store, sleep=NO_SLEEP, discovered_on=TODAY)
                self.assertEqual(result.stop_reason, reason)
                self.assertEqual(result.batches_ok, count)
                self.assertEqual(http.request_count, count)
                self.assertEqual(result.selection_counts, {"exclude": count * 5})
                self.assertEqual(store.items, {})
                self.assertEqual([rows for rows, _ in store.calls], [[]] * count)
                self.assertEqual(store.sync[CONTENT].committed_checkpoint, {"page_num": count + 1})

    def test_all_excluded_page_still_requires_a_valid_checkpoint_rpc_response(self):
        for response in (None, {}, [{"external_key": "not_submitted"}]):
            with self.subTest(response=response):
                pages = [[content("", key=f"empty-{i}") for i in range(5)], [active_content(key="later")]]
                client = self.fake_client(upsert=lambda p: response)
                result, http, calls = self.run_pages(pages, client)
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.stop_reason, "rpc_error")
                self.assertEqual(result.batches_ok, 0)
                self.assertEqual(result.selection_counts, {"exclude": 5})
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["p_items"], [])
                self.assertEqual(http.request_count, 1)

    def test_failed_mixed_batch_does_not_advance_local_committed_checkpoint(self):
        for error in (RpcFailure("rpc_failure"), RpcTimeout(), RpcAmbiguous(), LeaseLost()):
            with self.subTest(error=error):
                store = SpyMemoryStore()
                original = store.upsert_source_observations_v4
                attempts = []

                def upsert(source_id, run_id, records, checkpoint):
                    attempts.append(checkpoint)
                    if len(attempts) == 2:
                        raise error
                    return original(source_id, run_id, records, checkpoint)

                store.upsert_source_observations_v4 = upsert
                pages = [[active_content(key="saved"), *[content("", key=f"empty-{i}") for i in range(4)]],
                         [content("", key="excluded"), active_content(key="failed")]]
                http = PageHttp(pages)
                result = run_connector(YouthcenterContentConnector(http=http, api_key_provider=lambda: "fake"), store, sleep=NO_SLEEP, discovered_on=TODAY)
                self.assertEqual(result.status, "incomplete")
                self.assertEqual(result.batches_ok, 1)
                self.assertEqual(len(attempts), 2)
                self.assertEqual(http.request_count, 2)
                self.assertEqual(store.sync[CONTENT].committed_checkpoint, {"page_num": 2})
                self.assertEqual(list(store.items), [(CONTENT, "synthetic:saved")])


class ReviewMaterialSelectionTests(unittest.TestCase):
    DATA = "data:application/pdf;base64,U1lOVEhFVElD"

    def test_empty_metadata_values_and_removed_data_have_different_presence_same_no_material_exclusion(self):
        for value in (None, "", [], self.DATA):
            with self.subTest(value=value):
                item = content("", title="월간 안내", pstUrlAddr=None, atchFile=value)
                before = copy.deepcopy(item)
                record = normalize(CONTENT, item)
                selection = select_discovery(CONTENT, record, today=TODAY)
                self.assertEqual(selection.decision, "exclude")
                self.assertIn("no_reviewable_material", selection.reason_codes)
                self.assertEqual(record.attachment_present, value == self.DATA)
                self.assertEqual(record.is_data_url, value == self.DATA)
                if value == self.DATA:
                    self.assertEqual(record.attachment_length, len(self.DATA))
                    self.assertIn("attachment_removed_no_reviewable_material", selection.reason_codes)
                else:
                    self.assertEqual(record.attachment_length, 0)
                    self.assertNotIn("attachment_removed_no_reviewable_material", selection.reason_codes)
                self.assertNotIn("atchFile", record.normalized_payload)
                self.assertEqual(item, before)

    def test_removed_attachment_http_value_is_not_a_retained_review_link(self):
        record = normalize(CONTENT, content("", title="안내", pstUrlAddr=None, atchFile="https://example.invalid/file.pdf"))
        self.assertTrue(record.attachment_present)
        self.assertFalse(record.has_source_url)
        self.assertNotIn("https://example.invalid/file.pdf", str(record.to_rpc_item()))
        self.assertEqual(select_discovery(CONTENT, record, today=TODAY).decision, "exclude")

    def test_retained_source_link_and_useful_body_remain_review_material_without_fetching(self):
        helper = EmptyItemDiscoveryTests()
        pages = [[content("", title="안내", key="linked", atchFile=self.DATA),
                  content("신청 가능", title="안내", key="short", pstUrlAddr=None, atchFile=self.DATA)]]
        before = copy.deepcopy(pages)
        result, http, calls = helper.run_pages(pages, helper.fake_client())
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.selection_counts, {"review": 2})
        self.assertNotIn("no_reviewable_material", result.selection_reasons)
        self.assertEqual(http.request_count, 1)
        self.assertEqual(len(calls[0]["p_items"]), 2)
        for row in calls[0]["p_items"]:
            self.assertTrue(row["attachment_present"])
            self.assertTrue(row["is_data_url"])
        self.assertEqual(calls[0]["p_items"][0]["normalized_payload"]["source_url"], pages[0][0]["pstUrlAddr"])
        self.assertFalse(calls[0]["p_items"][0]["body_usable"])
        self.assertTrue(calls[0]["p_items"][1]["body_usable"])
        self.assertNotIn(self.DATA, str(calls))
        self.assertEqual(pages, before)

    def test_mixed_exclusions_continue_normal_and_supported_review_rpc_inputs(self):
        helper = EmptyItemDiscoveryTests()
        pages = [[active_content("누구나 신청 가능.", title="직무설명회", key="job"),
                  content("", title="월간 안내", key="removed", pstUrlAddr=None, atchFile=self.DATA),
                  active_content(key="normal"), content("신청 가능", title="안내", key="review")]]
        result, http, calls = helper.run_pages(pages, helper.fake_client())
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.selection_counts, {"exclude": 2, "include": 1, "review": 1})
        self.assertEqual(result.selection_reasons["job_training_target_unconfirmed"], 1)
        self.assertEqual(result.selection_reasons["attachment_removed_no_reviewable_material"], 1)
        self.assertEqual([row["external_key"] for row in calls[0]["p_items"]], ["synthetic:normal", "synthetic:review"])
        self.assertEqual(http.request_count, 1)
        self.assertEqual(result.batches_ok, 1)
        for error in (RpcTimeout(), RpcAmbiguous(), LeaseLost()):
            with self.subTest(error=error):
                failed, http, calls = helper.run_pages(pages, helper.fake_client(upsert=lambda p: error))
                self.assertIn(failed.status, {"failed", "incomplete"})
                self.assertEqual(failed.batches_ok, 0)
                self.assertEqual(len(calls), 1)
                self.assertEqual([row["external_key"] for row in calls[0]["p_items"]], ["synthetic:normal", "synthetic:review"])
                self.assertEqual(http.request_count, 1)

    def test_all_removed_attachment_page_progresses_only_after_valid_empty_rpc_reply(self):
        helper = EmptyItemDiscoveryTests()
        pages = [[content("", title="안내", key=str(i), pstUrlAddr=None, atchFile=self.DATA) for i in range(5)], [active_content(key="next")]]
        result, http, calls = helper.run_pages(pages, helper.fake_client())
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.selection_counts, {"exclude": 5, "include": 1})
        self.assertEqual(calls[0]["p_items"], [])
        self.assertEqual(calls[0]["p_next_checkpoint"], {"page_num": 2})
        self.assertEqual(http.request_count, 2)
        self.assertEqual(result.batches_ok, 2)
        result, http, calls = helper.run_pages(pages, helper.fake_client(upsert=lambda p: None))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.batches_ok, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(http.request_count, 1)

    def test_common_empty_value_fix_does_not_change_body_revision_or_policy_selection(self):
        for source, factory in ((CONTENT, lambda: active_content()), (POLICY, lambda: policy(TARGET + " " + REGION))):
            for value in (None, "", []):
                with self.subTest(source=source, value=value):
                    item = factory()
                    baseline = normalize(source, item)
                    item["atchFile"] = value
                    record = normalize(source, item)
                    self.assertFalse(record.attachment_present)
                    self.assertEqual(record.revision_hash, baseline.revision_hash)
                    self.assertEqual(record.normalized_payload, baseline.normalized_payload)
                    self.assertEqual(select_discovery(source, record, today=TODAY).decision, "include")

    def test_internal_alternate_text_does_not_make_removed_attachment_reviewable(self):
        item = content("", title="안내", pstUrlAddr=None, atchFile=self.DATA,
                       activity_location_text="방문 안내: 예약 후 방문 가능.")
        record = normalize(CONTENT, item)
        selection = select_discovery(CONTENT, record, today=TODAY)
        self.assertEqual(selection.decision, "review")
        selected = attach_selection(record, selection)
        before = copy.deepcopy(selected)
        client = EmptyItemDiscoveryTests().fake_client()
        with self.assertRaisesRegex(ValueError, "review_material_contract_required"):
            SupabaseIngestStore(client).upsert_source_observations_v4(CONTENT, "run", [selected], None)
        self.assertEqual(client.calls, [])
        self.assertEqual(selected, before)


class ReviewedPeriodAiTests(unittest.TestCase):
    def test_closed_and_past_reviewed_items_use_fake_ai_without_reselection(self):
        for code, end, category in (("0057003", None, "policy"), ("0057001", PAST, "program"), ("", None, "event")):
            with self.subTest(category=category):
                store = MemoryIngestStore(clock=lambda: datetime(2030, 6, 15, tzinfo=timezone.utc))
                item = policy(
                    "재한 일본인은 신청 가능합니다. 서울 거주자를 대상으로 합니다. 이번 회차 신청과 개최 안내입니다.",
                    aplyPrdSeCd=code, aplyYmd=end, zipCd="11680",
                )
                record = normalize(POLICY, item)
                run = store.start_ingest_run(POLICY)
                # Existing observation followed by real MemoryStore review contract.
                store.upsert_source_observations_v4(POLICY, run.run_id, [record], None)
                current = store.items[(POLICY, record.external_key)]
                store.resolve_source_item_user_category(source_item_id=current.id, revision_hash=current.revision_hash, user_category=category, event_start_on=PAST if category == "event" else None, event_end_on=PAST if category == "event" else None, reviewer="human:test")
                snapshots = copy.deepcopy((current.normalized_payload, store.product_types, store.application_deadlines, store.event_periods))
                called = []
                deps = _ai_deps(enqueue=lambda *a: called.append(a) or {"outcome": "inserted"})
                result = process_ai_jobs(store, limit=1, **deps)
                self.assertEqual(result.completed, 1)
                self.assertEqual(len(called), 1)
                self.assertEqual((current.normalized_payload, store.product_types, store.application_deadlines, store.event_periods), snapshots)

    def test_unreviewed_period_and_wrong_revision_still_block(self):
        store = MemoryIngestStore(clock=lambda: datetime(2030, 6, 15, tzinfo=timezone.utc))
        record = normalize(POLICY, policy(
            "재한 일본인은 신청 가능합니다. 서울 거주자를 대상으로 합니다. 이번 회차 신청과 개최 안내입니다.",
            aplyPrdSeCd="0057003", zipCd="11680",
        ))
        run = store.start_ingest_run(POLICY)
        store.upsert_source_observations_v4(POLICY, run.run_id, [record], None)
        current = store.items[(POLICY, record.external_key)]
        called = []
        result = process_ai_jobs(store, limit=1, **_ai_deps(enqueue=lambda *a: called.append(a)))
        self.assertEqual(result.claimed, 0)
        self.assertEqual(called, [])
        store.resolve_source_item_user_category(source_item_id=current.id, revision_hash=current.revision_hash, user_category="policy", event_start_on=None, event_end_on=None, reviewer="human:test")
        result = process_ai_jobs(store, limit=1, target_source_item_id=current.id, target_revision_hash="0" * 64, **_ai_deps(enqueue=lambda *a: called.append(a)))
        self.assertEqual(result.completed, 0)
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
