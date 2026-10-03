"""Report-derived SYNTHETIC HTML, NOT captured fixtures. No network/DB/AI.

Markup tests validate the local parser contract; actual site parity is pending.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from unittest.mock import patch

import requests

from ingest.connectors.myseoul_program import (
    DETAIL_PATH, HOME, MySeoulContractError, MySeoulProgramConnector,
    detail_identity, discover_home, normalize_detail,
)
from ingest.http_client import HttpBudgetExhausted, HttpClient, HttpRequestFailed, HttpStatusError, ResponseTooLarge
from ingest.models import Checkpoint
from ingest.myseoul_scope import KST, assess_myseoul, parse_period

CENTER = "30E1281B51FF476FB48B60B83D2581C1"
PROGRAM = "5CC31B97491B0114E063C0A8A022C964"
NOW = datetime(2026, 10, 2, 15, tzinfo=KST)


def url(program=PROGRAM, center=CENTER, language="ko"):
    return f"https://global.seoul.go.kr{DETAIL_PATH}?prgrm_no={program}&cntr_no={center}&lang={language}"


def home(*links, empty=False, outside=""):
    anchors = "".join(f'<a href="{link}">같은 제목</a>' for link in links)
    if empty:
        anchors = "<p>등록된 프로그램이 없습니다</p>"
    return '<html><body><section><h2>센터 소식</h2>' + outside + '</section><section><h2>교육 프로그램</h2><div>' + anchors + '</div></section></body></html>'


def observed_home(*links, empty=False, outside=""):
    """Synthetic markup using observed classes, NOT the original homepage HTML."""
    anchors = "".join(f'<a href="{link}"><h3>교육 카드</h3></a>' for link in links)
    if empty:
        anchors = "<p>등록된 교육 프로그램이 없습니다</p>"
    return (f'<html><body><section><h2>센터 소식</h2>{outside}</section>'
            '<div class="edu-program"><div class="ep-head"><span class="ep-label">교육 프로그램</span>'
            '<h2>누구나 쉽고 편하게 참여하는 다양한 교육</h2></div>'
            '<div class="ep-control"><a class="ep-more" href="/hmpg/ecpr/prgm/prgmListPage.do">'
            '<span class="hide">교육 프로그램</span></a></div>'
            f'<div class="cards">{anchors}</div></div></body></html>')


def detail(*, title="성인 문화 체험 수업", category="체험", target="성인", venue="서울 용산가족공원",
           mode="오프라인", purpose="성인이 참여하는 공예 체험 수업을 진행합니다.",
           status="접수중", application="2026-10-01 10:00 ~ 2026-10-15 18:00",
           operation="2026-10-03 ~ 2026-10-17", tuition="무료", methods="인터넷 예약",
           extra="", header_extra="", outside="", body=None):
    fields = [("구분", category), ("대상", target), ("교육장소", venue), ("진행방식", mode),
              ("신청기간", application), ("운영기간", operation), ("수강료", tuition),
              ("모집상태", status), ("신청방법", methods)]
    header = "".join(f"<dt>{key}</dt><dd>{value}</dd>" for key, value in fields if value)
    content = body if body is not None else f"<p>내용: {purpose}</p>{extra}"
    return f'<html><body>{outside}<div class="board_detail"><div class="title_box program-tit">{title}</div><ul class="program-cate"><li>{category}</li></ul><div class="program-detail"><dl>{header}</dl>{header_extra}</div><div class="program-content">{content}</div></div><form>만족도 폼</form><footer>챗봇 메뉴</footer></body></html>'


def assess(**options):
    return assess_myseoul(normalize_detail(detail(**options), url()), now=NOW)


def observed_detail(**options):
    """Small synthetic em/span layout observed in TWO detail reads, not HTML capture."""
    import re
    html = detail(**options)
    title = options.get("title", "성인 문화 체험 수업")
    category = options.get("category", "체험")
    html = html.replace(f'class="title_box program-tit">{title}</div>',
        'class="title_box program-tit"><span class="cate-st4 cate1">신청중</span>'
        f'<div><p class="txt-26 txt-over2 fw-600">{title}</p>'
        f'<ul class="program-cate"><li>{category}</li></ul></div></div>')
    html = html.replace(f'<ul class="program-cate"><li>{category}</li></ul><div class="program-detail">',
                        '<div class="program-detail">')
    html = re.sub(r'<dt>(.*?)</dt><dd>(.*?)</dd>',
                  r'<div class="item"><em>\1</em><span>\2</span></div>', html, flags=re.S)
    html = html.replace('<dl>', '<div class="program-detail-rg"><div class="pg-det-list">')
    return html.replace('</dl>', '</div></div>')


class ObservedMetadataTests(unittest.TestCase):
    def test_title_status_category_separate_no_word_removal(self):
        record = normalize_detail(observed_detail(title="신청중인 친구를 위한 체험 수업"), url())
        p = record.normalized_payload
        self.assertEqual(p["title"], "신청중인 친구를 위한 체험 수업")
        self.assertEqual(p["source_category"], "체험")
        self.assertIn({"field": "status", "label": "모집 배지", "value": "신청중", "origin": "header"}, p["labelled_evidence"])
        self.assertEqual(p["parser_version"], "myseoul-html-v2-local")
        self.assertEqual(p["revision_contract"], "myseoul-semantic-v2")

    def test_observed_header_em_span_and_whitespace_periods(self):
        html = observed_detail(application="2026-10-01 10:00\n ~\n2026-10-15 18:00")
        html = html.replace('<em>대상</em>', '<em>신청자격</em>')
        r = assess_myseoul(normalize_detail(html, url()), now=NOW)
        self.assertEqual(r.facts["target"], "성인")
        self.assertEqual(r.facts["periods"]["application"][0]["endpoints"][1]["precision"], "minute")
        self.assertEqual(r.decision, "include", r.reason_codes)
        self.assertTrue(all(e["origin"] == "header" for e in r.facts["evidence"] if e["field"] == "application"))

    def test_metadata_malformed_duplicate_missing_container_fail_closed(self):
        html = observed_detail()
        cases = [html.replace('<em>대상</em>', '<b>대상</b>'),
                 html.replace('<em>대상</em>', '<em>수강료</em>'),
                 html.replace('class="item"', 'class="changed"', 1),
                 html.replace('class="pg-det-list"', 'class="pg-det-list"></div><div class="pg-det-list"'),
                 html.replace('<p class="txt-26 txt-over2 fw-600">', '<p class="changed">'),
                 html.replace('<span class="cate-st4 cate1">신청중</span>', ''),
                 html.replace('<p class="txt-26', '<p class="txt-26">추가 제목</p><p class="txt-26', 1),
                 html.replace('class="program-detail"', 'class="changed"')]
        for bad in cases:
            with self.subTest(bad=bad[:100]), self.assertRaises(MySeoulContractError):
                normalize_detail(bad, url())

    def test_missing_header_value_stays_missing_not_filled_from_home(self):
        html = observed_detail(target="")
        r = assess_myseoul(normalize_detail(html, url()), now=NOW)
        self.assertIn("target_missing", r.reason_codes)
        self.assertEqual(r.decision, "review")

    def test_admission_and_free_tuition_separate_no_false_conflict(self):
        html = observed_detail(extra='<p>참가비: 3,000원 (입장료)</p>')
        r = assess_myseoul(normalize_detail(html, url()), now=NOW)
        self.assertEqual(r.facts["fees"], [
            {"component": "tuition", "evidence": ["무료"]},
            {"component": "admission", "evidence": ["3,000원 (입장료)"]}])
        self.assertEqual(r.facts["conflicts"], [])
        self.assertEqual(r.decision, "include", r.reason_codes)

    def test_materials_named_in_value_and_real_admission_conflict(self):
        r = assess_myseoul(normalize_detail(observed_detail(extra='<p>참가비: 별도 부담 (재료비)</p>'), url()), now=NOW)
        self.assertEqual(r.facts["fees"][1]["component"], "materials")
        html = observed_detail(header_extra='<p>입장료: 3,000원</p>', extra='<p>입장료: 5,000원</p>')
        # Put the synthetic additional labelled value into the canonical list.
        html = html.replace('</div></div><p>입장료: 3,000원</p>', '<div class="item"><em>입장료</em><span>3,000원</span></div></div></div>')
        r = assess_myseoul(normalize_detail(html, url()), now=NOW)
        self.assertTrue(any(c["field"] == "admission" for c in r.facts["conflicts"]))
        self.assertEqual(r.decision, "review")

    def test_unknown_amount_not_invented(self):
        r = assess_myseoul(normalize_detail(observed_detail(tuition="추후 안내"), url()), now=NOW)
        self.assertIn("fee_unknown", r.reason_codes)
        self.assertEqual(r.facts["fees"][0]["evidence"], ["추후 안내"])

    def test_review_equivalent_statuses_do_not_conflict(self):
        for status in ("신청중", "접수중", "모집중"):
            r = assess_myseoul(normalize_detail(observed_detail(extra=f'<p>모집상태: {status}</p>'), url()), now=NOW)
            self.assertEqual(r.decision, "include", r.reason_codes)
            self.assertFalse(r.facts["conflicts"])

    def test_review_same_fee_amount_annotation_and_actual_difference(self):
        for body_value, conflict in (("3,000원 (입장료)", False), ("3000원", False), ("5,000원 (입장료)", True)):
            label = "입장료" if body_value == "3000원" else "참가비"
            html = observed_detail(extra=f'<p>{label}: {body_value}</p>')
            html = html.replace('<div class="item"><em>수강료</em>', '<div class="item"><em>입장료</em><span>3,000원</span></div><div class="item"><em>수강료</em>')
            r = assess_myseoul(normalize_detail(html, url()), now=NOW)
            self.assertEqual(any(c["field"] == "admission" for c in r.facts["conflicts"]), conflict)
            self.assertEqual(r.decision, "review" if conflict else "include", r.reason_codes)

    def test_review_composite_fee_not_invented_as_tuition(self):
        r = assess_myseoul(normalize_detail(observed_detail(extra='<p>참가비: 3,000원 (입장료 및 재료비)</p>'), url()), now=NOW)
        self.assertIn("fee_components_unresolved", r.reason_codes)
        self.assertEqual(r.facts["fees"][-1], {"component": "extra_fee", "evidence": ["3,000원 (입장료 및 재료비)"]})
        self.assertEqual(r.decision, "review")

    def test_badge_does_not_override_end_date_or_conflicting_status(self):
        r = assess_myseoul(normalize_detail(observed_detail(application="2026-09-01 ~ 2026-09-30"), url()), now=NOW)
        self.assertEqual(r.application, "closed")
        r = assess_myseoul(normalize_detail(observed_detail(extra='<p>모집상태: 신청마감</p>'), url()), now=NOW)
        self.assertEqual(r.application, "unknown")
        self.assertEqual(r.decision, "review")
        self.assertEqual(assess(status="신청마감").application, "closed")

    def test_explicit_body_date_not_dropped_unsupported_meridiem_review(self):
        r = assess_myseoul(normalize_detail(observed_detail(extra='<div><strong>일시:</strong> 2026년 10월 3일(토) 오전 9:00 ~ 11:30</div>'), url()), now=NOW)
        self.assertIn("operation_period_unknown", r.reason_codes)
        self.assertEqual(r.facts["periods"]["operation"][-1]["status"], "unparsed")
        self.assertIn("오전 9:00", r.facts["periods"]["operation"][-1]["raw"])
        self.assertEqual(r.decision, "review")

    def test_body_application_link_method_and_survey_guidance_preserved(self):
        html = observed_detail(extra='<div>신청: <a href="https://forms.gle/example">https://forms.gle/example</a></div><p>참여 후 만족도 조사에 응답해주세요.</p><form>공통 만족도 조사 폼</form>')
        r = normalize_detail(html, url())
        self.assertIn('참여 후 만족도 조사', r.normalized_payload["description"])
        self.assertNotIn('공통 만족도 조사 폼', r.normalized_payload["description"])
        self.assertIn('https://forms.gle/example', assess_myseoul(r, now=NOW).facts["application_methods"])


class Response:
    def __init__(self, html="", status=200, content_type="text/html; charset=UTF-8", data=None):
        self.data = data if data is not None else html.encode()
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.closed = False

    def iter_content(self, chunk_size):
        for i in range(0, len(self.data), 64):
            yield self.data[i:i + 64]

    def close(self):
        self.closed = True


def connector(responses, *, budget=9, limit=8, max_bytes=1_000_000):
    pending = iter(responses)
    calls = []
    def transport(*args, **kwargs):
        calls.append((args, kwargs))
        return next(pending)
    client = HttpClient(budget=budget, transport=transport, max_response_bytes=max_bytes)
    return MySeoulProgramConnector(client, detail_limit=limit), calls


class DiscoveryTests(unittest.TestCase):
    def test_observed_span_title_ignores_more_label_and_other_regions(self):
        found = discover_home(observed_home(url(language="en"), url(), url("A" * 32),
                              outside=f'<a href="{url("B" * 32)}">센터 공지</a>'
                                      '<span class="ep-label">교육 프로그램</span>'))
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0]["discovered_languages"], ["en", "ko"])
        self.assertNotIn("B" * 32, [f["program_id"] for f in found])
        self.assertTrue(all("lang=ko" in f["url"] for f in found))

    def test_observed_identity_order_case_dedup_and_distinct_centers(self):
        relative = f'{DETAIL_PATH}?lang=ko&cntr_no={CENTER.lower()}&prgrm_no={PROGRAM.lower()}'
        found = discover_home(observed_home(relative, url(), url(center="B" * 32)))
        self.assertEqual(len(found), 2)

    def test_observed_empty_and_unreadable_are_distinct(self):
        self.assertEqual(discover_home(observed_home(empty=True)), ())
        with self.assertRaisesRegex(MySeoulContractError, "education_links_not_readable"):
            discover_home(observed_home())

    def test_observed_missing_changed_duplicate_title_fails_without_fallback(self):
        cases = [observed_home(url()).replace('class="ep-label"', 'class="changed"'),
                 observed_home(url()).replace('class="ep-head"', 'class="changed"'),
                 observed_home(url()).replace('class="ep-label">교육 프로그램', 'class="ep-label">센터 소식'),
                 observed_home(url()).replace('<span class="ep-label">', '<span class="ep-label">교육 프로그램</span><span class="ep-label">'),
                 observed_home(url()).replace('<div class="ep-head">', '<div class="ep-head"></div><div class="ep-head">')]
        for html in cases:
            with self.subTest(html=html), self.assertRaises(MySeoulContractError):
                discover_home(html)

    def test_observed_duplicate_containers_or_other_education_block_fails(self):
        for html in (observed_home(url()) + observed_home(url("A" * 32)), observed_home(url()) + home(url())):
            with self.assertRaises(MySeoulContractError):
                discover_home(html)

    def test_observed_wrong_parent_and_unscoped_label_fail(self):
        wrong_head = observed_home(url()).replace('<div class="ep-head">', '<div><div class="ep-head">').replace('</h2></div>', '</h2></div></div>')
        wrong_label = observed_home(url()).replace('<span class="ep-label">', '<div><span class="ep-label">').replace('교육 프로그램</span>', '교육 프로그램</span></div>', 1)
        for html in (wrong_head, wrong_label, '<div><span class="ep-label">교육 프로그램</span>' + f'<a href="{url()}">교육</a></div>'):
            with self.assertRaises(MySeoulContractError):
                discover_home(html)

    def test_observed_scope_keeps_detail_url_validation(self):
        for href in (url().replace("global.seoul.go.kr", "evil.test"), url() + "&token=secret",
                     url().replace("https:", "http:"), url() + "&prgrm_no=" + PROGRAM):
            with self.subTest(href=href), self.assertRaises(MySeoulContractError):
                discover_home(observed_home(href))

    def test_local_source_not_registered_in_existing_runner(self):
        from ingest.source_identity import canonical_source_id
        from ingest.run import build_youthcenter_connectors
        with self.assertRaises(ValueError):
            canonical_source_id("myseoul_program")
        with patch("requests.get", side_effect=AssertionError("network prohibited")):
            self.assertNotIn("myseoul_program", [c.canonical_source_id for c in build_youthcenter_connectors()])

    def test_only_education_section_and_ko_canonical(self):
        found = discover_home(home(url(language="en"), url(), outside=f'<a href="{url("A" * 32)}">뉴스</a>'))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["external_key"], f"{CENTER}:{PROGRAM}")
        self.assertEqual(found[0]["discovered_languages"], ["en", "ko"])
        self.assertIn("lang=ko", found[0]["url"])

    def test_relative_query_order_case_duplicates_distinct_ids(self):
        relative = f'{DETAIL_PATH}?lang=ko&cntr_no={CENTER.lower()}&prgrm_no={PROGRAM.lower()}'
        found = discover_home(home(relative, url(), url("A" * 32), url(center="B" * 32)))
        self.assertEqual(len(found), 3)

    def test_changed_template_not_empty_success(self):
        for html in ("<p>로그인</p>", home(), "<section><h2>교육 프로그램</h2><a>읽을 수 없는 동적 링크</a></section>"):
            with self.subTest(html=html), self.assertRaises(MySeoulContractError):
                discover_home(html)
        self.assertEqual(discover_home(home(empty=True)), ())

    def test_unrelated_boundary_and_ambiguous_sections_fail(self):
        for html in (f'<div><h2>교육 프로그램</h2><h2>센터 소식</h2><a href="{url()}">뉴스</a></div>', home(url()) + home(url())):
            with self.assertRaises(MySeoulContractError):
                discover_home(html)

    def test_untrusted_href_and_duplicate_query_rejected(self):
        candidates = [url().replace("global.seoul.go.kr", "evil.test"), url() + "&token=secret",
                      url() + "&prgrm_no=" + PROGRAM, url() + "#x", url().replace("https:", "http:"),
                      url().replace(PROGRAM, "bad"), url().replace("lang=ko", "lang=unknown")]
        for href in candidates:
            with self.subTest(href=href), self.assertRaises(MySeoulContractError):
                discover_home(home(href))


class TransportTests(unittest.TestCase):
    def test_observed_home_respects_request_limit_and_scoped_completion(self):
        conn, calls = connector([Response(observed_home(url(), url("A" * 32))), Response(detail())], budget=2)
        result = conn.fetch_batch(None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.progress["discovered"], 2)
        self.assertEqual(result.progress["omitted"], 1)
        self.assertFalse(result.natural_end)
        self.assertFalse(result.progress["source_complete"])
        conn, calls = connector([Response(observed_home(url())), Response(detail())], budget=2)
        result = conn.fetch_batch(None)
        self.assertTrue(result.progress["homepage_scope_complete"])
        self.assertFalse(result.progress["source_complete"])
        self.assertFalse(any(kwargs["allow_redirects"] for _, kwargs in calls))

    def test_scope_complete_not_whole_source_complete(self):
        conn, calls = connector([Response(home(url())), Response(detail())])
        result = conn.fetch_batch(None)
        self.assertTrue(result.natural_end)
        self.assertTrue(result.progress["homepage_scope_complete"])
        self.assertFalse(result.progress["source_complete"])
        self.assertEqual(conn.ordering_capability, "untrusted")
        self.assertEqual(result.meta.request_count_delta, 2)
        record = conn.to_observation(result.items[0], permission_status="testing_only", enabled=False)
        self.assertEqual(record.jobs, ())
        self.assertEqual(record.disposition, "observe_only")
        for args, kwargs in calls:
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(kwargs["timeout"], 15)
            self.assertTrue(args[0].startswith("https://global.seoul.go.kr/"))

    def test_details_and_request_limits_distinguish_incomplete(self):
        for budget, limit in ((2, 8), (9, 1), (1, 8)):
            conn, calls = connector([Response(home(url(), url("A" * 32))), Response(detail())], budget=budget, limit=limit)
            result = conn.fetch_batch(None)
            self.assertFalse(result.natural_end)
            self.assertFalse(result.progress["homepage_scope_complete"])
            self.assertEqual(result.progress["omitted"], 2 - len(result.items))
            self.assertLessEqual(len(calls), budget)
            self.assertLessEqual(len(result.items), limit)

    def test_actual_empty_scope(self):
        conn, calls = connector([Response(home(empty=True))])
        result = conn.fetch_batch(None)
        self.assertEqual(len(calls), 1)
        self.assertTrue(result.natural_end)
        self.assertEqual(result.items, ())

    def test_no_retry_status_and_redirect(self):
        for status in (302, 401, 403, 429, 500, 503):
            response = Response(status=status)
            conn, calls = connector([response])
            with self.subTest(status=status), self.assertRaises((HttpRequestFailed, HttpStatusError)):
                conn.fetch_batch(None)
            self.assertEqual(len(calls), 1)
            self.assertTrue(response.closed)

    def test_detail_redirect_is_not_followed(self):
        conn, calls = connector([Response(home(url())), Response(status=302)])
        with self.assertRaises(HttpRequestFailed):
            conn.fetch_batch(None)
        self.assertEqual(len(calls), 2)

    def test_timeout_and_sensitive_exception_sanitized(self):
        for error in (requests.Timeout("secret-url-token"), requests.RequestException("secret-url-token"), RuntimeError("secret-url-token")):
            client = HttpClient(budget=1, transport=lambda *a, **k: (_ for _ in ()).throw(error))
            stream = io.StringIO()
            with redirect_stdout(stream), redirect_stderr(stream), self.assertRaises(HttpRequestFailed) as raised:
                MySeoulProgramConnector(client).fetch_batch(None)
            self.assertNotIn("secret-url-token", str(raised.exception))
            self.assertEqual(stream.getvalue(), "")

    def test_wrong_mime_encoding_size_and_budget(self):
        cases = [(Response(home(url()), content_type="application/json"), HttpRequestFailed, 1_000_000),
                 (Response(data=b"\xff"), MySeoulContractError, 1_000_000),
                 (Response("X" * 200), ResponseTooLarge, 100)]
        for response, error, max_bytes in cases:
            conn, _ = connector([response], max_bytes=max_bytes)
            with self.assertRaises(error):
                conn.fetch_batch(None)
        client = HttpClient(budget=1, request_count=1)
        with self.assertRaises(HttpBudgetExhausted):
            MySeoulProgramConnector(client).fetch_batch(None)

    def test_checkpoint_and_invalid_config(self):
        conn, _ = connector([])
        with self.assertRaises(MySeoulContractError):
            conn.fetch_batch(Checkpoint.for_rest_page(2))
        for budget, limit in ((22, 8), (0, 8), (3, 0), (3, 21)):
            with self.assertRaises(MySeoulContractError):
                MySeoulProgramConnector(HttpClient(budget=budget), detail_limit=limit)


class NormalizationTests(unittest.TestCase):
    def test_boundaries_fields_language_and_missing_publication_dates(self):
        record = normalize_detail(detail(extra="<p>진행언어: 한국어</p><p>연령: 만 20세 이상</p>", outside="<nav>공통 안내</nav>"), url())
        payload = record.normalized_payload
        self.assertEqual(payload["source_language"], "ko")
        self.assertIsNone(record.source_created_at)
        self.assertIsNone(record.source_updated_at)
        self.assertNotIn("만족도", payload["description"])
        self.assertNotIn("챗봇", payload["description"])
        self.assertNotIn("공통 안내", payload["description"])
        self.assertEqual(record.jobs, ())
        self.assertIsNone(record.gate_facts)

    def test_table_lists_and_spans_preserved_nonexecuting(self):
        record = normalize_detail(detail(extra='<table><tr><th rowspan="2">반</th><th>일정</th></tr><tr><td>초급: 수요일 16:00</td></tr></table><ul><li>보호자 동반 필수</li><li>신청 1인당 2명</li></ul><script>alert("token")</script>'), url())
        payload = record.normalized_payload
        self.assertEqual(payload["tables"][0][0][0]["rowspan"], 2)
        self.assertIn("초급: 수요일 16:00", payload["description"])
        self.assertIn("보호자 동반 필수", payload["conditions"])
        self.assertNotIn("alert", payload["description"])
        self.assertNotIn("<", payload["description"])

    def test_list_label_pairs_supported(self):
        html = detail(header_extra='<ul><li><span>집결시간</span><em>08:45</em></li></ul>')
        result = assess_myseoul(normalize_detail(html, url()), now=NOW)
        self.assertEqual(result.facts["meeting_evidence"], ("08:45",))

    def test_semantic_revision_ignores_surroundings_views_widgets_versions(self):
        one = normalize_detail(detail(outside="조회수 1"), url())
        two = normalize_detail(detail(outside='<p>조회수 200</p><select>Google Translate</select>'), url())
        self.assertEqual(one.revision_hash, two.revision_hash)
        changed = normalize_detail(detail(extra="<p>참여조건: 보호자 동반 필수</p>"), url())
        self.assertNotEqual(one.revision_hash, changed.revision_hash)
        with patch("ingest.connectors.myseoul_program.PARSER_VERSION", "other-parser"):
            different_parser = normalize_detail(detail(), url())
        self.assertEqual(one.revision_hash, different_parser.revision_hash)

    def test_status_period_fee_changes_revision(self):
        base = normalize_detail(detail(), url()).revision_hash
        for options in ({"status": "접수종료"}, {"operation": "2026-10-03 ~ 2026-10-18"}, {"tuition": "10,000원"}):
            self.assertNotEqual(base, normalize_detail(detail(**options), url()).revision_hash)

    def test_apply_links_retained_but_not_fetched_and_sensitive_omitted(self):
        html = detail(extra='<a href="https://forms.gle/example">신청 폼</a><a href="https://example.test/?token=secret">신청</a><a href="https://example.test/file.pdf">신청 안내</a><img src="https://images.test/x.png"><p>문의: 02-1234-5678 public@example.test</p>')
        conn, calls = connector([Response(home(url())), Response(html)])
        record = conn.fetch_batch(None).items[0]["record"]
        self.assertEqual(len(calls), 2)
        self.assertEqual(record.normalized_payload["application_links"], ["https://forms.gle/example"])
        self.assertTrue(record.attachment_present)
        rendered = str(record.normalized_payload)
        for secret in ("secret", "02-1234-5678", "public@example.test", "images.test"):
            self.assertNotIn(secret, rendered)

    def test_image_only_short_body_insufficient_not_guessed(self):
        result = assess(body='<img src="x.png"><p>포스터 참조</p>')
        self.assertIn("description_missing", result.reason_codes)
        self.assertEqual(result.decision, "review")

    def test_detail_template_missing_or_foreign_language_fails(self):
        for html, location in (("로그인 필요", url()), (detail(), url(language="en")), (detail().replace("program-content", "changed-content"), url())):
            with self.assertRaises(MySeoulContractError):
                normalize_detail(html, location)


class ScopeTests(unittest.TestCase):
    def test_review_regression_canonical_alias_conflicts(self):
        for extra in ("<p>교육일시: 2026-10-04 ~ 2026-10-18</p>", "<p>참가비: 30,000원</p>"):
            result = assess(extra=extra)
            self.assertEqual(result.decision, "review", result.reason_codes)
            self.assertIn("source_fact_conflict", result.reason_codes)

    def test_review_regression_unparsed_second_clock_not_early_end(self):
        self.assertEqual(parse_period("2026-10-03 10:00~11:30")["status"], "unparsed")
        result = assess(operation="2026-10-02 10:00~16:00")
        self.assertEqual(result.decision, "review")
        self.assertIn("operation_period_unknown", result.reason_codes)
        self.assertNotIn("operation_ended", result.reason_codes)

    def test_review_regression_remote_mode_and_unknown_no_venue_fallback(self):
        for mode in ("비대면", "Zoom", "줌"):
            result = assess(mode=mode, extra="<p>거주조건: 전국</p>")
            self.assertEqual(result.facts["delivery_mode"], "online")
            self.assertEqual(result.decision, "include", result.reason_codes)
        unknown = assess(mode="별도 확인")
        self.assertEqual(unknown.facts["delivery_mode"], "unknown")
        self.assertEqual(unknown.decision, "review")

    def test_include_adult_family_paid_no_nationality_review(self):
        for options in ({}, {"target": "어린이와 보호자", "tuition": "20,000원", "extra": "<p>동반조건: 보호자 필수</p>"}, {"target": "성인 외국인", "tuition": "무료"}):
            with self.subTest(options=options):
                result = assess(**options)
                self.assertEqual(result.decision, "include", result.reason_codes)
                self.assertEqual(result.scope, "included")
                self.assertEqual(result.application, "open")
                self.assertEqual(result.public_category, "program")
                self.assertFalse(result.db_connected)

    def test_employment_and_industry_allowed_only_here(self):
        for title, purpose in (("외국인 취업지원 수업", "내용: 외국인 취업지원 교육을 진행합니다."), ("VR 산업 안전교육", "산업 현장 안전교육을 VR 체험으로 진행합니다.")):
            result = assess(title=title, category="교육", purpose=purpose, target="성인 외국인")
            self.assertEqual(result.decision, "include", result.reason_codes)
        # Existing Seoul evaluator remains unchanged and still excludes employment.
        from test_seoul_reservation import row
        from ingest.connectors.seoul_reservation import normalize_seoul_item
        from ingest.program_scope import assess_seoul_program
        old = assess_seoul_program(normalize_seoul_item(row(SVCNM="취업 지원 교육")), now=NOW)
        self.assertEqual(old.decision, "out_of_scope")

    def test_fees_component_not_conflict(self):
        result = assess(extra="<p>재료비: 23,000원</p><p>입장료: 3,000원</p>")
        self.assertEqual(result.decision, "include", result.reason_codes)
        self.assertEqual([f["component"] for f in result.facts["fees"]], ["tuition", "materials", "admission"])
        self.assertEqual(result.facts["conflicts"], [])

    def test_program_event_and_composite(self):
        event = assess(title="관용의 날 기념행사", category="교류", purpose="누구나 참여하는 관용의 날 기념행사를 진행합니다.")
        self.assertEqual(event.public_category, "event")
        self.assertEqual(event.decision, "include", event.reason_codes)
        composite = assess(title="문화 축제와 체험 수업", purpose="축제 공연과 체험 수업을 함께 운영합니다.")
        self.assertIsNone(composite.public_category)
        self.assertIn("category_unresolved", composite.reason_codes)
        no_purpose = assess(title="체험 수업", body="<p>기관 공지사항입니다. 자세한 사항은 첨부를 참고하십시오.</p>")
        self.assertIsNone(no_purpose.public_category)

    def test_institution_only_vs_individual_and_collaboration(self):
        for text in ("개인 신청 불가", "학교만 신청 가능", "기관 담당자만 신청 가능"):
            result = assess(extra=f"<p>참여조건: {text}</p>")
            self.assertEqual(result.decision, "exclude")
            self.assertIn("institution_only", result.reason_codes)
        result = assess(extra="<p>협조기관: 지역 학교</p><p>참여조건: 개인 신청 가능, 단체는 증빙 서류 제출</p>")
        self.assertEqual(result.decision, "include", result.reason_codes)
        internal = assess(purpose="기관 내부 운영 담당자 행정교육입니다.")
        self.assertEqual(internal.scope, "excluded")

    def test_capital_noncapital_and_organizer_address_not_venue(self):
        for venue in ("서울시청 8층", "경기도 수원 문화회관", "인천 시민공원"):
            self.assertEqual(assess(venue=venue).decision, "include")
        self.assertEqual(assess(venue="부산 문화회관").scope, "excluded")
        unknown = assess(venue="", extra="<p>운영기관: 서울 교육센터</p>")
        self.assertNotEqual(unknown.decision, "include")
        mixed = assess(venue="부산 문화회관", mode="온라인·오프라인 혼합")
        self.assertEqual(mixed.scope, "excluded")

    def test_online_scopes_and_multicourse_not_all_mixed(self):
        for residence in ("전국", "지역 제한 없음", "서울 거주자"):
            result = assess(mode="온라인", venue="", extra=f"<p>거주조건: {residence}</p>")
            self.assertEqual(result.decision, "include", result.reason_codes)
        noncapital = assess(mode="온라인", venue="", extra="<p>거주조건: 부산 거주자만</p>")
        self.assertEqual(noncapital.scope, "excluded")
        unknown = assess(mode="온라인", venue="", target="성인")
        self.assertIn("online_residence_unknown", unknown.reason_codes)
        multiple = assess(mode="초급 온라인 / 중급 현장", extra="<p>초급반: 온라인 수업</p><p>중급반: 현장 수업</p>")
        self.assertEqual(multiple.facts["delivery_mode"], "course_unresolved")
        self.assertIn("course_modes_unresolved", multiple.reason_codes)

    def test_known_eligibility_and_nationality_vs_unconfirmed_visa(self):
        for target, code in (("한국 국적자만", "explicit_japanese_ineligible"), ("내국인만", "explicit_japanese_ineligible"), ("중국 국적자만", "explicit_other_nationality_only")):
            result = assess(target=target)
            self.assertEqual(result.decision, "exclude")
            self.assertIn(code, result.reason_codes)
        visa = assess(target="성인 외국인 F-6 체류자격")
        self.assertIn("nationality_or_visa_unresolved", visa.reason_codes)
        self.assertEqual(assess(target="일본 국적자만").decision, "include")
        self.assertNotIn("국적", " ".join(assess().reason_codes))

    def test_additional_recruitment_and_operation_start_not_closed(self):
        result = assess(operation="2026-09-14 ~ 2026-11-25", status="추가 모집중")
        self.assertEqual(result.application, "open")
        self.assertEqual(result.decision, "include", result.reason_codes)

    def test_application_closed_separate_from_operation(self):
        result = assess(status="접수종료")
        self.assertEqual(result.scope, "included")
        self.assertEqual(result.application, "closed")
        self.assertEqual(result.decision, "exclude")
        ended = assess(operation="2026-09-01 ~ 2026-09-30")
        self.assertEqual(ended.application, "ended")
        future = assess(application="2026-10-03 ~ 2026-10-15")
        self.assertEqual(future.application, "not_started")

    def test_period_precision_end_inclusive_and_bad_dates(self):
        record = normalize_detail(detail(application="2026-10-01 ~ 2026-10-02"), url())
        late = assess_myseoul(record, now=datetime(2026, 10, 2, 23, 59, tzinfo=KST))
        self.assertEqual(late.application, "open")
        after = assess_myseoul(record, now=datetime(2026, 10, 3, tzinfo=KST))
        self.assertEqual(after.application, "closed")
        self.assertEqual(parse_period("2026-02-30 ~ 2026-10-02")["status"], "unparsed")
        self.assertEqual(parse_period("10월 3·10·17일, 토요일 10:00~11:30")["status"], "unparsed")
        self.assertEqual(parse_period("2026-10-03, 2026-10-10")["status"], "unparsed")
        with self.assertRaises(MySeoulContractError):
            assess_myseoul(record, now=datetime(2026, 10, 2))

    def test_same_label_conflict_requires_review(self):
        for extra in ("<p>운영기간: 2026-10-03 ~ 2026-10-18</p>", "<p>수강료: 30,000원</p>"):
            result = assess(extra=extra)
            self.assertIn("source_fact_conflict", result.reason_codes)
            self.assertEqual(result.decision, "review")
        result = assess(extra="<p>모집상태: 예약마감</p>")
        self.assertEqual(result.application, "unknown")

    def test_overall_class_meeting_and_session_evidence_distinct(self):
        extra = "<p>초급반: 2026-10-03 ~ 2026-10-17, 매주 토요일 10:00~11:30, 총 3회</p><p>집결시간: 09:45</p><p>집결장소: 서울 공원 정문</p>"
        result = assess(extra=extra)
        self.assertEqual(result.decision, "include", result.reason_codes)
        self.assertIn("09:45", result.facts["meeting_evidence"])
        self.assertTrue(any("총 3회" in line for line in result.facts["session_evidence"]))
        self.assertEqual(result.facts["conflicts"], [])

    def test_zero_capacity_not_no_recruitment_and_form_url_not_required(self):
        result = assess(extra="<p>정원: 0명</p><p>참여조건: 선착순 조기 마감 가능</p>", methods="QR을 통한 온라인 신청")
        self.assertEqual(result.decision, "include", result.reason_codes)
        self.assertEqual(result.facts["capacity_raw"], ("0명",))
        self.assertIsNone(result.facts["capacity_value"])
        self.assertEqual(result.facts["application_links"], [])
        self.assertTrue(result.facts["early_close_evidence"])

    def test_source_and_schema_reject_other_payloads(self):
        from ingest.connectors.seoul_reservation import normalize_seoul_item
        from test_seoul_reservation import row
        with self.assertRaises(MySeoulContractError):
            assess_myseoul(normalize_seoul_item(row()), now=NOW)


if __name__ == "__main__":
    unittest.main()
