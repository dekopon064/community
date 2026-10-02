"""Synthetic report-derived examples, NOT captured API responses. No network/DB."""

from __future__ import annotations

import io
import json
import traceback
import unittest
from contextlib import redirect_stderr
from datetime import datetime
from unittest.mock import patch

import requests

from ingest.connectors.seoul_reservation import (
    KST, SERVICE, SeoulContractError, SeoulReservationConnector,
    normalize_seoul_item, parse_body, parse_seoul_date, preview_seoul,
)
from ingest.http_client import HttpBudgetExhausted, HttpClient, ResponseTooLarge
from ingest.models import Checkpoint
from ingest.program_scope import assess_seoul_program, extract_program_facts

NOW = datetime(2026, 10, 1, 18, tzinfo=KST)
TEST_KEY = "synthetic-key-for-unit-tests"


def row(sid="TEST01", **overrides):
    item = {
        "SVCID": sid, "SVCNM": "성인 공원 탐방과 공예 체험",
        "SVCURL": "https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=" + sid,
        "MAXCLASSNM": "문화체험", "MINCLASSNM": "공원탐방", "USETGTINFO": "성인",
        "PLACENM": "용산가족공원", "AREANM": "용산구", "PAYATNM": "무료", "SVCSTATNM": "접수중",
        "RCPTBGNDT": "2026-09-01 10:00:00.0", "RCPTENDDT": "2026-10-30 17:00:00.0",
        "SVCOPNBGNDT": "2026-10-03 10:00:00.0", "SVCOPNENDDT": "2026-11-03 11:30:00.0",
        "DTLCONT": "<p>상세내용</p><p>공원 탐방과 공예 체험을 진행합니다.</p><p>장소: 용산가족공원</p><p>대상: 성인</p><p>예약방법: 공공서비스 예약 선착순 신청</p>",
    }
    item.update(overrides)
    return item


def assess(**overrides):
    return assess_seoul_program(normalize_seoul_item(row(**overrides)), now=NOW)


class Response:
    def __init__(self, payload=None, status=200, headers=None, data=None):
        self.status_code = status
        self.headers = headers or {}
        self.data = data if data is not None else json.dumps(payload, ensure_ascii=False).encode()
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.data

    def close(self):
        self.closed = True


def envelope(rows, total=None):
    return {SERVICE: {"RESULT": {"CODE": "INFO-000"}, "row": rows,
                      "list_total_count": len(rows) if total is None else total}}


def connector(responses, **options):
    pending = iter(responses)
    http = HttpClient(budget=options.get("max_pages", 1) * 3, sleep=lambda _: None,
                      transport=lambda *args, **kwargs: next(pending))
    return SeoulReservationConnector(http, api_key_provider=lambda: TEST_KEY, **options)


class NormalizationTests(unittest.TestCase):
    def test_preserves_fields_dates_and_observation_boundary(self):
        record = normalize_seoul_item(row(IMGURL="https://example.test/cover.png"))
        self.assertEqual(record.external_key, "TEST01")
        self.assertEqual(record.normalized_payload["dates"]["RCPTENDDT"]["value"], "2026-10-30T17:00:00+09:00")
        self.assertIsNone(record.source_created_at)
        self.assertIsNone(record.source_updated_at)
        self.assertEqual(record.jobs, ())
        self.assertIsNone(record.gate_facts)
        self.assertEqual(record.disposition, "observe_only")

    def test_table_language_relationship_and_spans(self):
        body = parse_body('<script>secret()</script><p>상세내용</p><table><tr><th rowspan="2">시간</th><th>수요일</th></tr><tr><td>16:00 일본어</td></tr></table>')
        self.assertNotIn("secret", body["plain_text"])
        self.assertEqual(body["tables"][0][0][0]["rowspan"], 2)
        self.assertEqual(body["tables"][0][1][0]["text"], "16:00 일본어")
        self.assertIn(" | ", body["plain_text"])

    def test_boilerplate_is_not_usable(self):
        record = normalize_seoul_item(row(DTLCONT="공공시설 예약서비스 이용시 필수 준수사항. 모든 서비스는 기관 규정을 따릅니다."))
        self.assertFalse(record.body_usable)
        self.assertIn("program_description_missing", assess_seoul_program(record, now=NOW).reason_codes)

    def test_image_only_and_attachment_metadata(self):
        result = assess(DTLCONT='<p>상세내용</p><img src="x"><a href="a.hwpx">첨부 안내</a>')
        self.assertIn("attachment_dependent", result.reason_codes)

    def test_missing_link_is_review(self):
        self.assertIn("missing_source_url", assess(SVCURL="").reason_codes)

    def test_invalid_identity_link_and_type(self):
        for values in ({"SVCID": ""}, {"SVCNM": ""}, {"SVCURL": "https://evil.test/a"},
                       {"SVCURL": "https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=OTHER"},
                       {"DTLCONT": {"unexpected": True}}):
            with self.subTest(values=values), self.assertRaises(SeoulContractError):
                normalize_seoul_item(row(**values))

    def test_revision_ignores_execution_metadata_preserves_conditions(self):
        a = normalize_seoul_item(row(observed_at="A", page=1, list_total_count=100))
        b = normalize_seoul_item(row(observed_at="B", page=2, list_total_count=300))
        self.assertEqual(a.revision_hash, b.revision_hash)
        self.assertNotEqual(a.revision_hash, normalize_seoul_item(row(USETGTINFO="가족")).revision_hash)
        self.assertNotEqual(a.revision_hash, normalize_seoul_item(row(SVCSTATNM="예약마감")).revision_hash)

    def test_date_precision_and_unparsed(self):
        self.assertEqual(parse_seoul_date("2026-10-03")["value"], "2026-10-03")
        self.assertEqual(parse_seoul_date("2026-10-03 00:02:00.0")["value"], "2026-10-03T00:02:00+09:00")
        self.assertEqual(parse_seoul_date("unknown")["status"], "unparsed")
        self.assertIn("period_missing_or_unparsed", assess(RCPTENDDT="unknown").reason_codes)


class ProgramTests(unittest.TestCase):
    def test_adult_public_no_foreign_phrase_passes(self):
        result = assess()
        self.assertEqual(result.decision, "in_scope")
        self.assertEqual(result.evaluation.disposition, "target")
        self.assertEqual(result.evaluation.jobs, ())
        self.assertFalse(result.db_connected)

    def test_culture_category_and_unlimited_target_are_insufficient(self):
        result = assess(USETGTINFO="제한없음", DTLCONT="설명은 제공되지 않았고 홈페이지 이용규정만 안내하는 자료입니다.")
        self.assertEqual(result.decision, "review_required")

    def test_adults_and_children_not_child_only(self):
        result = assess(USETGTINFO="초등학교 4학년 이상~성인", DTLCONT=row()["DTLCONT"] + "<p>대상: 초등학교 4학년 이상부터 성인까지</p>")
        self.assertEqual(result.decision, "in_scope")
        self.assertEqual(result.facts.editorial_pending, ())

    def test_family_conditions_do_not_force_review(self):
        result = assess(USETGTINFO="유아와 보호자 가족", DTLCONT=row()["DTLCONT"] + "<p>유아 보호자 동반 필수. 1가구당 1개 화분</p>")
        self.assertEqual(result.decision, "in_scope")
        self.assertTrue(any("동반" in c for c in result.facts.conditions))

    def test_individual_and_group_can_pass(self):
        result = assess(DTLCONT=row()["DTLCONT"] + "<p>성인 개인/단체 신청 가능. 단체 사전 협의</p>")
        self.assertEqual(result.facts.application_actor, "individual_or_group")
        self.assertEqual(result.decision, "in_scope")

    def test_institution_only_even_with_unlimited_field(self):
        for text in ("개인 신청불가. 기관 담당자의 인터넷 접수", "학교만 신청 가능. 단체증빙서류 고유번호증 제출"):
            result = assess(USETGTINFO="제한없음", DTLCONT=row()["DTLCONT"] + "<p>" + text + "</p>")
            self.assertEqual(result.decision, "out_of_scope")
            self.assertEqual(result.evaluation.jobs, ())

    def test_group_documents_and_school_names_do_not_exclude_individuals(self):
        for text in ("단체증빙서류 고유번호증 또는 사업자등록증 제출", "학교 담당자의 안내", "참여기관 모집 안내 및 개인 신청 가능"):
            self.assertEqual(assess(DTLCONT=row()["DTLCONT"] + "<p>" + text + "</p>").decision, "in_scope")

    def test_actor_conflict_is_review(self):
        result = assess(DTLCONT=row()["DTLCONT"] + "<p>개인 신청불가. 개인 신청 가능.</p>")
        self.assertIn("application_actor_conflict", result.reason_codes)

    def test_online_is_not_internet_reservation(self):
        self.assertEqual(assess().facts.delivery_mode, "offline")

    def test_online_nationwide_and_unknown(self):
        text = "<p>온라인 문화 체험 교육으로 Zoom 수업을 진행합니다.</p><p>대상: 전국 거주자</p>"
        result = assess(DTLCONT=text)
        self.assertEqual(result.decision, "in_scope")
        self.assertEqual(result.facts.activity_region, "not_applicable")
        unknown = assess(DTLCONT=text.replace("전국 거주자", "성인"))
        self.assertIn("residence_scope_unknown", unknown.reason_codes)

    def test_online_noncapital_residents_excluded(self):
        result = assess(DTLCONT="온라인 문화체험 Zoom 수업<p>대상: 부산 거주자 전용</p>")
        self.assertIn("residence_outside_capital", result.reason_codes)

    def test_noncapital_actual_place_not_seoul_operator(self):
        result = assess(DTLCONT="문화 공예 체험<p>장소: 전남 나주 체험관</p><p>대상: 전국 거주자</p>")
        self.assertIn("activity_outside_capital", result.reason_codes)

    def test_hybrid_venue_still_matters(self):
        for venue, decision in (("서울 체험관", "in_scope"), ("부산 체험관", "out_of_scope")):
            result = assess(DTLCONT=f"온·오프라인 혼합 문화체험 프로그램<p>장소: {venue}</p><p>대상: 전국 거주자</p>")
            self.assertEqual(result.facts.delivery_mode, "hybrid")
            self.assertEqual(result.decision, decision)

    def test_offline_residence_conditions_matter(self):
        self.assertIn("residence_outside_capital", assess(USETGTINFO="부산 주민 전용").reason_codes)

    def test_title_place_is_not_actual_place(self):
        result = assess(SVCNM="부산을 배우는 서울 문화 체험")
        self.assertEqual(result.decision, "in_scope")

    def test_fee_amount_unknown_and_known_are_not_blanket_review(self):
        a = assess(PAYATNM="유료")
        b = assess(PAYATNM="유료", DTLCONT=row()["DTLCONT"] + "<p>참가비: 10,000원</p>")
        self.assertEqual(a.decision, "in_scope")
        self.assertEqual(a.facts.fee_amounts, ())
        self.assertEqual(b.facts.fee_amounts, ("10,000원",))
        self.assertEqual(b.facts.editorial_pending, ())

    def test_fee_conflict_and_target_conflict(self):
        self.assertIn("fee_conflict", assess(PAYATNM="유료", DTLCONT=row()["DTLCONT"] + "<p>참가비: 무료</p>").reason_codes)
        self.assertIn("target_conflict", assess(USETGTINFO="유아, 초등학생", DTLCONT=row()["DTLCONT"] + "<p>참가대상: 제한없음</p>").reason_codes)

    def test_weekday_conflict(self):
        self.assertIn("date_weekday_conflict", assess(DTLCONT=row()["DTLCONT"] + "<p>일시: 2026년 10월 3일(금)</p>").reason_codes)

    def test_status_conflict_not_early_closing_warning(self):
        self.assertIn("source_status_conflict", assess(DTLCONT=row()["DTLCONT"] + "<p>현재 예약마감</p>").reason_codes)
        self.assertEqual(assess(DTLCONT=row()["DTLCONT"] + "<p>초과 시 조기 마감될 수 있습니다.</p>").decision, "in_scope")

    def test_closed_status_and_expired_application_not_program_end(self):
        for change in ({"SVCSTATNM": "예약마감"}, {"SVCSTATNM": "접수종료"}, {"RCPTBGNDT": "2026-02-02 10:00:00.0", "RCPTENDDT": "2026-02-06 18:00:00.0"}):
            result = assess(**change)
            self.assertIn("not_currently_accepting", result.reason_codes)
            self.assertEqual(result.evaluation.jobs, ())
            self.assertEqual(result.facts.content_kind, "program")
            self.assertEqual(result.decision, "not_currently_available")

    def test_program_ended_and_future_application_are_not_scope_exclusions(self):
        for change, reason in (({"SVCOPNBGNDT": "2026-09-01", "SVCOPNENDDT": "2026-09-30"}, "program_ended"),
                               ({"RCPTBGNDT": "2026-10-02 10:00:00.0"}, "application_not_started")):
            result = assess(**change)
            self.assertEqual(result.decision, "not_currently_available")
            self.assertIn(reason, result.reason_codes)

    def test_date_only_end_not_midnight_expiration(self):
        self.assertEqual(assess(RCPTENDDT="2026-10-01").decision, "in_scope")

    def test_period_order_unknown_status_and_documents(self):
        self.assertIn("period_order_conflict", assess(SVCOPNENDDT="2026-09-03").reason_codes)
        self.assertIn("source_status_unknown", assess(SVCSTATNM="미확인상태").reason_codes)
        self.assertIn("eligibility_document_unconfirmed", assess(DTLCONT=row()["DTLCONT"] + "<p>주민등록등본 제출</p>").reason_codes)

    def test_explicit_nationality_not_default_missing(self):
        self.assertEqual(assess(USETGTINFO="한국 국적자만").decision, "out_of_scope")

    def test_jobs_and_policy_differ_from_hobby(self):
        self.assertEqual(assess(SVCNM="취업 교육 프로그램").decision, "out_of_scope")
        self.assertEqual(assess(SVCNM="사업주 운영지원").decision, "out_of_scope")
        self.assertIn("policy_eligibility_unconfirmed", assess(SVCNM="청년 지원금").reason_codes)
        self.assertEqual(assess(USETGTINFO="성인, 취업 준비생도 참여 가능").decision, "in_scope")

    def test_foreign_source_and_naive_clock_fail_closed(self):
        record = normalize_seoul_item(row())
        with self.assertRaises(ValueError):
            assess_seoul_program(record, now=datetime(2026, 10, 1))
        record.normalized_payload["source_id"] = "youthcenter_content"
        with self.assertRaises(ValueError):
            assess_seoul_program(record, now=NOW)


class PagingAndTransportTests(unittest.TestCase):
    def test_success_and_zero(self):
        for payload, n in ((envelope([row()]), 1), (envelope([]), 0), ({"RESULT": {"CODE": "INFO-200"}}, 0)):
            c = connector([Response(payload)])
            result = preview_seoul(c)
            self.assertEqual(result.status, "complete")
            self.assertEqual(len(result.records), n)

    def test_api_errors_shape_and_truncation_fail(self):
        for payload in ({"RESULT": {"CODE": "ERROR-301", "MESSAGE": "not logged"}}, [], {},
                        envelope([], 20), envelope([row()], 20), envelope([None]), envelope([row()], "1")):
            with self.subTest(payload=payload), self.assertRaises(SeoulContractError):
                connector([Response(payload)]).fetch_batch(None)

    def test_limited_preview_is_incomplete(self):
        result = preview_seoul(connector([Response(envelope([row()], 5))], page_size=1))
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.stop_reason, "page_limit")

    def test_full_page_continues_without_known_streak(self):
        c = connector([Response(envelope([row("A"), row("B"), row("C")], 4)), Response(envelope([row("D")], 4))], page_size=3, max_pages=2)
        self.assertEqual(c.ordering_capability, "untrusted")
        result = preview_seoul(c)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.pages, 2)
        self.assertEqual(len(result.records), 4)

    def test_repeated_page_duplicate_and_changed_id_fail(self):
        c = connector([Response(envelope([row("A"), row("B")], 4)), Response(envelope([row("A"), row("B")], 4))], page_size=2, max_pages=2)
        with self.assertRaisesRegex(SeoulContractError, "repeated_page"):
            preview_seoul(c)
        with self.assertRaisesRegex(SeoulContractError, "duplicate_id"):
            connector([Response(envelope([row(), row()]))]).fetch_batch(None)
        c = connector([Response(envelope([row("A"), row("B")], 4)), Response(envelope([row("A", PAYATNM="유료"), row("C")], 4))], page_size=2, max_pages=2)
        with self.assertRaisesRegex(SeoulContractError, "revision_changed"):
            preview_seoul(c)

    def test_total_drift_marks_incomplete(self):
        c = connector([Response(envelope([row("A"), row("B")], 4)), Response(envelope([row("C")], 3))], page_size=2, max_pages=2)
        self.assertEqual(preview_seoul(c).stop_reason, "listing_changed")

    def test_bad_checkpoint_and_limits(self):
        c = connector([])
        for cp in (Checkpoint.for_rest_page(2), Checkpoint({"wrong": 1})):
            with self.assertRaises(SeoulContractError):
                c.fetch_batch(cp)
        for options in ({"page_size": 0}, {"page_size": 1001}, {"max_pages": 0}, {"max_pages": True}):
            with self.assertRaises(SeoulContractError):
                connector([], **options)

    def test_path_key_redacted_in_status_headers(self):
        response = Response({}, status=403, headers={"X-Request-ID": TEST_KEY})
        output = io.StringIO()
        with redirect_stderr(output):
            try:
                connector([response]).fetch_batch(None)
            except Exception:
                output.write(traceback.format_exc())
        self.assertNotIn(TEST_KEY, output.getvalue())
        self.assertNotIn("openapi.seoul", output.getvalue())
        self.assertTrue(response.closed)

    def test_timeouts_nonjson_stream_size_and_budget(self):
        def timeout(*args, **kwargs):
            raise requests.Timeout("secret " + TEST_KEY)
        http = HttpClient(budget=1, transport=timeout)
        with self.assertRaisesRegex(Exception, "timeout"):
            SeoulReservationConnector(http, api_key_provider=lambda: TEST_KEY).fetch_batch(None)
        with self.assertRaisesRegex(Exception, "non_json"):
            connector([Response(data=b"not json")]).fetch_batch(None)
        http = HttpClient(budget=1, max_response_bytes=3, transport=lambda *args, **kwargs: Response(data=b"1234"))
        with self.assertRaises(ResponseTooLarge):
            SeoulReservationConnector(http, api_key_provider=lambda: TEST_KEY).fetch_batch(None)
        http = HttpClient(budget=1, sleep=lambda _: None, transport=lambda *args, **kwargs: Response({}, status=503))
        with self.assertRaises(HttpBudgetExhausted):
            SeoulReservationConnector(http, api_key_provider=lambda: TEST_KEY).fetch_batch(None)

    def test_credential_echo_never_becomes_payload_or_exception(self):
        for payload in (envelope([row(SVCNM=TEST_KEY)]), {"RESULT": {"CODE": "ERROR-301", "MESSAGE": TEST_KEY}}):
            with self.assertRaisesRegex(SeoulContractError, "credential_in_response") as caught:
                connector([Response(payload)]).fetch_batch(None)
            self.assertNotIn(TEST_KEY, str(caught.exception))

    def test_production_runner_does_not_register_source(self):
        from ingest.run import build_youthcenter_connectors
        from ingest.source_identity import canonical_source_id
        with self.assertRaises(ValueError):
            canonical_source_id("seoul_reservation")
        with patch("requests.get", side_effect=AssertionError("network prohibited")):
            self.assertNotIn("seoul_reservation", [c.canonical_source_id for c in build_youthcenter_connectors()])


class IndependentReviewRegressions(unittest.TestCase):
    """Nine independently reproduced findings; targeted post-review verification."""

    def test_warning_section_keeps_actual_eligibility(self):
        result = assess(DTLCONT=row()["DTLCONT"] + "<h3>4. 주의사항</h3><p>개인 신청불가. 기관 담당자만 신청 가능</p>")
        self.assertEqual(result.decision, "out_of_scope")
        self.assertTrue(any("개인 신청불가" in c for c in result.facts.conditions))

    def test_negative_online_does_not_bypass_noncapital_venue(self):
        result = assess(DTLCONT="문화 공예 체험을 진행합니다. 온라인 참여는 불가합니다.<p>장소: 부산 체험관</p><p>대상: 전국 성인</p>")
        self.assertEqual(result.facts.delivery_mode, "offline")
        self.assertIn("activity_outside_capital", result.reason_codes)

    def test_group_documents_do_not_exclude_allowed_individuals(self):
        result = assess(DTLCONT=row()["DTLCONT"] + "<p>개인과 단체 신청 가능. 단체 신청 시 고유번호증 제출</p>")
        self.assertEqual(result.decision, "in_scope")
        self.assertEqual(result.facts.application_actor, "individual_or_group")
        self.assertTrue(any("고유번호증" in c for c in result.facts.conditions))

    def test_partial_overlap_never_reports_complete(self):
        c = connector([Response(envelope([row("A"), row("B")], 4)), Response(envelope([row("B"), row("C")], 4))], page_size=2, max_pages=2)
        with self.assertRaisesRegex(SeoulContractError, "overlapping_pages"):
            preview_seoul(c)

    def test_raw_body_and_references_survive_observation(self):
        html = row()["DTLCONT"] + '<a href="https://example.test/apply">신청</a><img src="details.png">'
        record = normalize_seoul_item(row(DTLCONT=html))
        self.assertEqual(record.normalized_payload["source_body_html"], html)
        self.assertIn('src="details.png"', record.normalized_payload["source_body_html"])
        self.assertFalse(record.gate_facts)

    def test_nested_table_restores_outer_cells_and_relationship(self):
        body = parse_body("<table><tr><td>외부 시작<table><tr><td>내부 조건</td></tr></table>외부 끝</td><td>다음 조건</td></tr></table>")
        outer = body["tables"][0][0]
        self.assertEqual(len(outer), 2)
        self.assertIn("외부 끝", outer[0]["text"])
        self.assertIn("내부 조건", outer[0]["text"])
        self.assertEqual(outer[0]["nested_tables"], [1])
        self.assertEqual(outer[1]["text"], "다음 조건")

    def test_body_api_period_conflict_and_unparsed_explicit_period(self):
        result = assess(DTLCONT=row()["DTLCONT"] + "<p>접수기간: 2026년 9월 1일~2026년 9월 30일</p>")
        self.assertEqual(result.decision, "review_required")
        self.assertIn("body_api_period_conflict", result.reason_codes)
        self.assertTrue(result.facts.period_evidence)
        result = assess(DTLCONT=row()["DTLCONT"] + "<p>접수기간: 별도 공고 참고</p>")
        self.assertIn("body_period_needs_confirmation", result.reason_codes)

    def test_past_closing_statement_is_conflict_not_generic_warning(self):
        result = assess(DTLCONT=row()["DTLCONT"] + "<p>예약마감되었습니다.</p>")
        self.assertIn("source_status_conflict", result.reason_codes)
        self.assertEqual(assess(DTLCONT=row()["DTLCONT"] + "<p>예약마감될 수 있습니다.</p>").decision, "in_scope")

    def test_timestamp_start_date_only_end_same_day_is_not_reversed(self):
        result = assess(RCPTBGNDT="2026-10-01 10:00:00.0", RCPTENDDT="2026-10-01")
        self.assertEqual(result.decision, "in_scope")
        self.assertNotIn("period_order_conflict", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
