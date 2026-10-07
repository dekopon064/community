"""Synthetic retained text and injected RPC/provider only. No env or network."""
import copy
import contextlib
import io
import json
import socket
import subprocess
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from ingest.content_filters import (SCHEMA, empty_filters, field, validate_filters,
    extract_filter_facts, expand_recurrence, missing_filters, validate_claim_filter, confirmed_filter_values)
from ingest.models import ClaimedJob
from ingest.supabase_store import SupabaseIngestStore, _v4_proposal_record
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job
from ingest.myseoul_ai import process_myseoul_job
from ingest.ai_worker import process_ai_jobs, WORKER_ID
from ingest.rpc_errors import RpcAmbiguous, RpcTimeout
from test_youthcenter_selection import FakeClient
from test_myseoul_ai import context as my_context, providers as my_providers
from test_program_ai import context as seoul_context, providers as seoul_providers
from test_youthcenter_selection import content, normalize, CONTENT, POLICY, PageHttp, TODAY, NO_SLEEP
from ingest.connectors.youthcenter_content import YouthcenterContentConnector
from ingest.orchestrator import run_connector

ID = "00000000-0000-4000-8000-000000000002"
JOB = "00000000-0000-4000-8000-000000000003"
REV = "a" * 64


def ready(category="program"):
    d = empty_filters(category)
    if category == "program":
        d.update(topic=field("language_learning"), delivery=field("online"), audience=field("other"),
                 location=field(status="not_applicable"), application=field({"deadlineKind": "fixed", "start": None,
                 "end": {"value": "2020-10-01", "precision": "day"}, "sourceStatus": "closed"}))
    elif category == "event":
        d.update(topic=field("culture_arts"), location=field({"scope": "nationwide", "venues": []}),
                 schedule=field({"kind": "occurrences", "occurrences": [{"start": {"value": "2020-10-01", "precision": "day"},
                 "end": {"value": "2020-10-01", "precision": "day"}}], "recurrence": None}))
    else:
        d.update(spaceKind=field("news"), location=field(status="not_applicable"))
    return d


def ctx(category="program", worker=WORKER_ID):
    now = datetime.now(timezone.utc)
    return {"schema": SCHEMA, "filterVersion": 2, "data": ready(category),
            "claimedAt": now.isoformat(), "leaseUntil": (now + timedelta(seconds=600)).isoformat(), "workerId": worker}


def bind_filters(c):
    category = c.get("publicCategory", "program")
    c["filterContext"] = ctx(category, worker=c["workerId"])
    d = c["filterContext"]["data"]
    if category == "program":
        for k, v in confirmed_filter_values(c["facts"]).items(): d[k] = field(v)
        if d["delivery"] != field("online"):
            d["location"] = field({"scope": "specific", "venues": [{"province": "11", "district": "영등포구", "facility": "합성", "address": "서울 영등포구"}]})
    else:
        ends = c["facts"]["periods"]["operation"][0]["endpoints"]
        d["schedule"] = field({"kind": "continuous", "occurrences": [{"start": ends[0], "end": ends[-1]}], "recurrence": None})
    for k in ("claimedAt", "leaseUntil"): c[k] = c["filterContext"][k]
    return c


def temporal_context(source, state):
    c = my_context() if source == "my" else seoul_context()
    f = c["facts"]
    if source == "my":
        if state == "closed":
            f["source_status"] = ["신청마감"]
        elif state == "ended":
            f["periods"]["operation"][0].update(raw="2020-01-01 ~ 2020-01-02")
            for endpoint, value in zip(f["periods"]["operation"][0]["endpoints"],
                                       ("2020-01-01", "2020-01-02")):
                endpoint.update(value=value, precision="day")
        elif state == "not_started":
            f["periods"]["application"][0]["endpoints"][0]["value"] = "2098-01-01T10:00:00+09:00"
    else:
        if state == "closed":
            f["source_status"] = "application_closed"
        elif state == "reservation_closed":
            f["source_status"] = "reservation_closed"
        elif state == "ended":
            for key, value in (("SVCOPNBGNDT", "2020-01-01"), ("SVCOPNENDDT", "2020-01-02")):
                f["periods"][key].update(raw=value, value=value)
        elif state == "not_started":
            f["periods"]["RCPTBGNDT"].update(raw="2035-01-01", value="2035-01-01")
    c["observedFacts"] = copy.deepcopy(f)
    return c

def confirmed_temporal_context(state):
    c = temporal_context("my", state)
    from ingest.myseoul_db import evaluate_myseoul_facts
    server_result = evaluate_myseoul_facts(c["facts"], now=datetime.now().astimezone())
    c["facts"]["activity_evidence"] = []
    # A fake protected server evaluation simulates an administrator venue
    # audit outside facts; no quotation or client confirmation flag is added.
    d = {"id": c["sourceItemId"], "revision": c["revision"], "factsVersion": c["factsVersion"],
         "schema": c["schema"], "profile": c["profile"], "status": "resolved", "aiStatus": "claimed",
         "source": {"name": c["source"], "title": c["title"], "url": c["facts"]["official_url"]},
         "facts": copy.deepcopy(c["facts"]), "observedFacts": copy.deepcopy(c["observedFacts"]),
         "result": server_result}
    return c, d


class NoNetwork(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))
        self.guard.start()
        self.addCleanup(self.guard.stop)


class ExtractionTests(NoNetwork):
    def extract(self, text, source="seoul_reservation", facts=None):
        key = "program_text" if source == "seoul_reservation" else "plain_text"
        return extract_filter_facts(source, {key: text}, facts)["data"]

    def test_topic_priorities_and_conflicts(self):
        for text, topic in (("취업 지원 목적의 한국어 교육", "employment_career"),
                ("취업 목적 없는 생활 안전 교육", "daily_safety"), ("컴퓨터 기초 학습", "language_learning"),
                ("AI 도구 활용 학습", "language_learning"), ("공예 체험", "culture_experience"),
                ("주민 교류 활동", "community_exchange"), ("공예 체험과 주민 교류 활동", None),
                ("취업지원센터 기관 소개", None), ("자격증 정보", None), ("분야: 기타", "other")):
            with self.subTest(text=text):
                self.assertEqual(self.extract(text)["topic"], field(topic))

    def test_title_and_category_are_not_topic_evidence(self):
        m = extract_filter_facts("seoul_reservation", {"title": "취업 교육", "source_category": "문화", "program_text": "정보 부족"})
        self.assertEqual(m["data"]["topic"], field())
        self.assertEqual(m["evidence"], {})

    def test_primary_activity_not_incidental_employment(self):
        d = self.extract("목적: 공예 체험\n기타: 취업 준비에 대한 이야기도 잠시 나눕니다.")
        self.assertEqual(d["topic"], field("culture_experience"))

    def test_children_guardians_family_and_missing_age(self):
        for target, expected in (("어린이와 보호자 동반", "children"), ("만 6~12세", "children"),
                ("가족, 어린이와 보호자", "other"), ("전 연령", "other"), ("성인, 어린이 참여 가능", None),
                ("", None), ("2015년 출생자", None), ("어린이 제외", None), ("청년", "other")):
            with self.subTest(target=target):
                self.assertEqual(self.extract("공예 체험", facts={"target_raw": target})["audience"], field(expected))

    def test_explicit_structured_age_upper_bound_and_conflict(self):
        payload = {"description": "공예 체험"}
        for target, age, expected in (("외국인", "만 6~12세", "children"), ("외국인", "만 12세 이하", "children"),
                ("전 연령", "만 6~12세", None), ("외국인", "2015년 출생", None)):
            d = extract_filter_facts("myseoul_program", payload, {"public_category": "program", "target": target, "age": [age]})
            self.assertEqual(d["data"]["audience"], field(expected))
            if expected: self.assertEqual(d["evidence"]["audience"], {"sourceField": "facts.age", "excerpt": age})

    def test_actual_locations_multiple_provinces_and_gyeonggi_district(self):
        d = self.extract("장소: 경기도 수원시 장안구 합성 시설; 서울 영등포구 합성 센터")
        venues = d["location"]["value"]["venues"]
        self.assertEqual([v["district"] for v in venues], ["수원시", "영등포구"])
        self.assertIn("장안구", venues[0]["address"])
        self.assertEqual(self.extract("장소: 인천 제물포구 시설")["location"]["value"]["venues"][0]["province"], "28")

    def test_seoul_reuses_retained_structured_activity_places(self):
        facts = {"activity_evidence": ("서울 영등포구 합성 시설", "경기도 수원시 영통구 합성 시설")}
        before = copy.deepcopy(facts)
        packet = extract_filter_facts("seoul_reservation", {"program_text": "공예 체험"}, facts)
        self.assertEqual([v["district"] for v in packet["data"]["location"]["value"]["venues"]], ["영등포구", "수원시"])
        proof = packet["evidence"]["location"]
        self.assertEqual(proof["sourceField"], "facts.activity_evidence")
        self.assertEqual(proof["excerpt"], json.dumps(facts["activity_evidence"], ensure_ascii=False))
        self.assertEqual(facts, before)

    def test_residence_institution_meeting_and_capital_not_venues(self):
        for text in ("대상: 서울 영등포구 거주자", "기관 주소: 서울 영등포구", "집결장소: 서울 영등포구",
                     "장소: 수도권", "장소: 부산 시설, 전국 신청 가능", "장소: 서울 영등포구 거주자"):
            with self.subTest(text=text):
                self.assertEqual(self.extract(text)["location"], field())
        self.assertEqual(self.extract("장소: 서울문화센터")["location"], field())

    def test_online_exemption_and_nationwide_use_not_eligibility(self):
        self.assertEqual(self.extract("공예 체험", facts={"delivery_mode": "online"})["location"], field(status="not_applicable"))
        self.assertEqual(self.extract("장소: 실제 이용 지역: 전국")["location"], field({"scope": "nationwide", "venues": []}))
        self.assertEqual(self.extract("전국 신청 가능")["location"], field())

    def test_youth_categories_are_body_proposals_not_source_category(self):
        for text, category in (("한국어 교육을 진행. 신청 가능.", "program"), ("현장 공연을 개최. 방문 가능.", "event"),
                ("청년공간 소개. 시설 이용 가능.", "youth_space"), ("청년공간 소식. 방문 가능.", "youth_space")):
            metadata = extract_filter_facts(CONTENT, {"plain_text": text})
            self.assertEqual(metadata["data"]["category"], category)
        for text in ("안내", "청년공간 소개. 한국어 교육을 진행.", "온라인 강연 개최. 온라인 참여"):
            self.assertIsNone(extract_filter_facts(CONTENT, {"plain_text": text, "pstTtl": "문화 행사", "pstSeNm": "청년공간"}))
        self.assertIsNone(extract_filter_facts(POLICY, {"plain_text": "한국어 교육을 진행"}))

    def test_space_news_exempts_region_introduction_does_not(self):
        news = self.extract("청년공간 활동 후기. 방문 가능.", CONTENT)
        intro = self.extract("청년공간 소개. 시설 이용 가능.", CONTENT)
        self.assertEqual(news["spaceKind"], field("news"))
        self.assertEqual(news["location"], field(status="not_applicable"))
        self.assertEqual(intro["location"], field())

    def test_application_dates_left_for_server_confirmed_facts(self):
        d = self.extract("한국어 교육을 진행\n신청 기간: 2026-10-01 ~ 2026-10-31\n등록일: 2026-09-01", CONTENT)
        self.assertEqual(d["application"], field())
        # Observation keeps application unknown; SQL reuses confirmed dates
        # and preserves the separately reviewed start under the follow-up contract.
        self.assertIn("application", missing_filters(d))

    def test_full_year_recurrence_and_exceptions_not_continuous(self):
        d = self.extract("현장 축제를 개최\n행사 일정: 2026-10-01 ~ 2026-10-31 매주 토요일 제외일: 2026-10-10", CONTENT)
        schedule = d["schedule"]["value"]
        self.assertEqual(schedule["kind"], "occurrences")
        self.assertEqual([v["start"]["value"] for v in schedule["occurrences"]], ["2026-10-03", "2026-10-17", "2026-10-24", "2026-10-31"])
        self.assertEqual(schedule["occurrences"][0]["end"]["precision"], "day")

    def test_continuous_disjoint_and_unsupported_schedules(self):
        for value, kind, count in (("2026-10-01 ~ 2026-10-31", "continuous", 1),
                ("2026-10-03, 2026-10-17", "occurrences", 2),
                ("2026-10-03 10:00 ~ 2026-10-03 11:00", "continuous", 1)):
            d = self.extract("현장 축제를 개최\n행사 일정: " + value, CONTENT)
            self.assertEqual(d["schedule"]["value"]["kind"], kind)
            self.assertEqual(len(d["schedule"]["value"]["occurrences"]), count)
        for value in ("10월 매주 토요일", "2026-10-01 ~ 2026-10-31 매주 토요일 제외일: 2026-10-09", "2026-10-03 10:00~11:00", "2026-10-17, 2026-10-03", "2026-10-03, 2026-10-03", "상시"):
            self.assertEqual(self.extract("현장 축제를 개최\n행사 일정: " + value, CONTENT)["schedule"], field())

    def test_evidence_is_existing_retained_text_input_and_revision_unchanged(self):
        original = normalize(CONTENT, content("한국어 교육을 진행\n진행 방식: 온라인\n대상: 어린이\n전국 거주자 신청 가능."))
        before = copy.deepcopy(original)
        proposed = _v4_proposal_record(original, source_id=CONTENT)
        packet = proposed.to_rpc_item()
        self.assertEqual(original, before)
        self.assertEqual(proposed.revision_hash, before.revision_hash)
        self.assertNotIn("filterFacts", packet["normalized_payload"])
        metadata = packet["filterFacts"]
        self.assertEqual(set(metadata), {"data", "evidence"})
        for reference in metadata["evidence"].values():
            self.assertTrue(reference["sourceField"].startswith("payload."))
            self.assertIn(reference["excerpt"], before.normalized_payload[reference["sourceField"][8:]])

    def test_raw_text_change_changes_existing_revision_not_parser_metadata(self):
        a = normalize(CONTENT, content("한국어 교육을 진행"))
        b = normalize(CONTENT, content("주민 교류 활동 교육을 진행"))
        self.assertNotEqual(a.revision_hash, b.revision_hash)
        self.assertNotEqual(_v4_proposal_record(a, source_id=CONTENT).filter_facts, _v4_proposal_record(b, source_id=CONTENT).filter_facts)


class SchemaTests(NoNetwork):
    def test_python_values_and_districts_match_latest_build_parser(self):
        from pathlib import Path
        from ingest.content_filters import DISTRICTS
        root = Path(__file__).resolve().parents[1]
        if not (root / "node_modules/typescript").is_dir():
            self.skipTest("Build parser parity requires the existing TypeScript installation")
        values = [ready(c) for c in ("program", "event", "youth_space")]
        values += [extract_filter_facts(CONTENT, {"plain_text": t})["data"] for t in (
            "한국어 교육을 진행\n진행 방식: 온라인\n대상: 어린이",
            "현장 축제를 개최\n행사 일정: 2026-10-01 ~ 2026-10-31 매주 토요일 제외일: 2026-10-10",
            "청년공간 소식. 시설 이용 가능.")]
        script = """
const fs=require('node:fs'),ts=require('typescript'),vm=require('node:vm');
const code=ts.transpileModule(fs.readFileSync('app/lib/contentFilters.ts','utf8'),
 {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const sandbox={exports:{}};vm.runInNewContext(code,sandbox);
const p=JSON.parse(fs.readFileSync(0,'utf8')),api=sandbox.exports;
for(const [province,values] of Object.entries(p.districts))
 if(JSON.stringify([...values].sort())!==JSON.stringify([...api.districtChoices[province]].sort()))throw Error('district contract changed');
for(const d of p.values){const parsed=api.parseContentFilters(d);
 if(JSON.stringify(parsed)!==JSON.stringify(d))throw Error('parser changed data');}
console.log('Build parser parity: '+p.values.length);
"""
        result = subprocess.run(["node", "-e", script], cwd=root, input=json.dumps({"values": values, "districts": DISTRICTS}),
                                text=True, encoding="utf-8", capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Build parser parity: 6", result.stdout)

    def test_exact_enums_types_keys_and_unknown_other_na(self):
        for category in ("program", "event", "youth_space"):
            self.assertEqual(validate_filters(ready(category)), ready(category))
        for key, value in (("schema", "v2"), ("topic", field("unknown")), ("topic", field(status="not_applicable")),
                ("audience", {"status": "unknown", "value": "other"}), ("delivery", field("offline")), ("unexpected", 1)):
            d = ready(); d[key] = value
            with self.subTest(key=key, value=value), self.assertRaises((ValueError, TypeError)):
                validate_filters(d)
        self.assertNotEqual(field("other"), field())

    def test_date_precision_day_inclusive_no_midnight_and_real_calendar(self):
        d = ready("event"); self.assertEqual(validate_filters(d), d)
        for value in ("2026-02-30", "2026-10-01T00:00:00Z", "2026-10-01T00:00:00+09:00"):
            bad = copy.deepcopy(d); bad["schedule"]["value"]["occurrences"][0]["start"]["value"] = value
            with self.assertRaises(ValueError): validate_filters(bad)

    def test_claim_snapshot_version_fence_and_expired_lease(self):
        c = ctx(); self.assertEqual(validate_claim_filter(c, worker=WORKER_ID), c)
        for key, value in (("schema", "bad"), ("filterVersion", True), ("filterVersion", 0),
                ("workerId", "other"), ("leaseUntil", c["claimedAt"]), ("claimedAt", "2026-10-01"),
                ("data", empty_filters("program")), ("revision", REV)):
            bad = copy.deepcopy(c); bad[key] = value
            with self.subTest(key=key), self.assertRaises((ValueError, TypeError)):
                validate_claim_filter(bad, worker=WORKER_ID)
        with self.assertRaises(ValueError): validate_claim_filter(c, worker=WORKER_ID, fence={**c, "claimedAt": "2020-01-01"})


class AIConnectionTests(NoNetwork):
    def test_reviewed_temporal_states_with_filter_snapshot_keep_actual_facts(self):
        for source in ("my", "seoul"):
            for state in ("open", "not_started", "closed", "ended"):
                c = bind_filters(temporal_context(source, state))
                before = copy.deepcopy(c)
                ko, ja = (my_providers(c) if source == "my" else seoul_providers(c))[:2]
                calls = []
                def rpc(name, args):
                    calls.append((name, copy.deepcopy(args)))
                    return [copy.deepcopy(c)] if name.startswith("claim_") else {"candidateId": ID, "outcome": "inserted"}
                fn = process_myseoul_job if source == "my" else process_seoul_program_job
                result = fn(ProgramAIAdapter(rpc), source_item_id=ID, revision=c["revision"], summarize_ko=ko, translate_ja=ja)
                self.assertEqual(result.completed, 1, (source, state))
                self.assertEqual(len(calls), 2)
                self.assertEqual(c, before)

    def test_my_server_place_confirmation_matches_filter_and_facts_versions(self):
        for state in ("open", "not_started", "closed", "ended"):
            for mutate in (None, "filter_version", "snapshot", "facts_version", "revision", "missing"):
                c, detail = confirmed_temporal_context(state)
                bind_filters(c)
                detail["filterInfo"] = {"schema": SCHEMA, "revision": c["revision"], "filterVersion": 2,
                                        "data": copy.deepcopy(c["filterContext"]["data"]), "missing": []}
                if mutate == "filter_version": detail["filterInfo"]["filterVersion"] = 1
                if mutate == "snapshot": detail["filterInfo"]["data"]["topic"] = field("other")
                if mutate == "facts_version": detail["factsVersion"] -= 1
                if mutate == "revision": detail["filterInfo"]["revision"] = REV
                if mutate == "missing": detail["filterInfo"]["missing"] = ["topic"]
                before = copy.deepcopy((c, detail))
                ko, ja = my_providers(c)
                calls = []
                def rpc(name, args):
                    calls.append(name)
                    if name.startswith("claim_"): return [copy.deepcopy(c)]
                    if name == "admin_myseoul_program_detail": return copy.deepcopy(detail)
                    return {"candidateId": ID, "outcome": "inserted"}
                result = process_myseoul_job(ProgramAIAdapter(rpc), source_item_id=ID, revision=c["revision"], summarize_ko=ko, translate_ja=ja)
                self.assertEqual(result.completed, int(mutate is None), (state, mutate))
                self.assertEqual(calls, ["claim_myseoul_program_ai", "admin_myseoul_program_detail"] + (["finish_myseoul_program_ai"] if mutate is None else []))
                self.assertEqual((c, detail), before)

    def test_current_program_dates_delivery_and_review_must_match_snapshot(self):
        for source in ("my", "seoul"):
            for mutation in ("delivery", "start", "status", "review"):
                c = my_context() if source == "my" else seoul_context()
                if source == "my": c["facts"]["source_status"] = ["신청중"]
                bind_filters(c)
                if mutation == "delivery": c["filterContext"]["data"]["delivery"] = field("mixed")
                if mutation == "start": c["filterContext"]["data"]["application"]["value"]["start"] = None
                if mutation == "status": c["filterContext"]["data"]["application"]["value"]["sourceStatus"] = "closed"
                if mutation == "review":
                    c["facts"]["issues" if source == "my" else "missing"] = [{"code": "target_missing", "field": "target", "evidence": []}] if source == "my" else ["target_missing"]
                provider = Mock(side_effect=AssertionError("blocked")); rpc = Mock(return_value=[c])
                fn = process_myseoul_job if source == "my" else process_seoul_program_job
                result = fn(ProgramAIAdapter(rpc), source_item_id=ID, revision=c["revision"], summarize_ko=provider, translate_ja=provider)
                self.assertEqual(result.state_unknown, 1)
                provider.assert_not_called(); self.assertEqual(rpc.call_count, 1)

    def test_my_seoul_general_fenced_completion_keeps_metadata_out_of_provider(self):
        for source in ("my", "seoul"):
            c = my_context() if source == "my" else seoul_context()
            bind_filters(c)
            before = copy.deepcopy(c)
            base = my_providers(c) if source == "my" else seoul_providers(c)
            ko, ja = base[:2]
            summaries = []
            def summarize(body, url, title=None):
                summaries.append(body)
                self.assertNotIn("filterContext", body)
                self.assertNotIn("content-filters-v1", body)
                return ko(body, url, title=title)
            calls = []
            def rpc(name, args):
                calls.append((name, copy.deepcopy(args)))
                return [copy.deepcopy(c)] if name.startswith("claim_") else {"candidateId": ID, "outcome": "inserted"}
            fn = process_myseoul_job if source == "my" else process_seoul_program_job
            result = fn(ProgramAIAdapter(rpc), source_item_id=ID, revision=c["revision"], summarize_ko=summarize, translate_ja=ja)
            self.assertEqual(result.completed, 1)
            self.assertEqual(len(summaries), 1)
            self.assertEqual([n for n, _ in calls], [f"claim_{'myseoul' if source == 'my' else 'seoul'}_program_ai", f"finish_{'myseoul' if source == 'my' else 'seoul'}_program_ai"])
            self.assertEqual(calls[-1][1]["p_facts_version"], c["factsVersion"])
            self.assertEqual(calls[-1][1]["p_claimed_at"], c["claimedAt"])
            self.assertEqual(c, before)

    def test_my_seoul_bad_context_never_calls_provider_or_fail(self):
        for source in ("my", "seoul"):
            for mutation in ("unknown", "worker", "fence", "version", "revision", "schema"):
                c = my_context() if source == "my" else seoul_context()
                bind_filters(c)
                if mutation == "unknown": c["filterContext"]["data"] = empty_filters("program")
                if mutation == "worker": c["filterContext"]["workerId"] = "wrong"
                if mutation == "fence": c["filterContext"]["claimedAt"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                if mutation == "version": c["filterContext"]["filterVersion"] = True
                if mutation == "revision": c["revision"] = "b" * 64
                if mutation == "schema": c["schema"] = "bad"
                rpc = Mock(return_value=[c]); provider = Mock(side_effect=AssertionError())
                fn = process_myseoul_job if source == "my" else process_seoul_program_job
                result = fn(ProgramAIAdapter(rpc), source_item_id=ID, revision=my_context()["revision"] if source == "my" else REV, summarize_ko=provider, translate_ja=provider)
                self.assertEqual(result.state_unknown, 1)
                self.assertEqual(rpc.call_count, 1); provider.assert_not_called()

    def generic(self, context=None, finish_error=None, finish_reply=None, provider_error=None, payload_override=None,
                fail_error=None, fail_reply="failed", ko_override=None, ja_error=None):
        context = context or ctx()
        row = {"job_id": JOB, "source_item_id": ID, "source_id": CONTENT, "external_key": "1:1",
               "revision_hash": REV, "processing_stage": "ai_enrichment", "curation_source": "youthcenter_content",
               "normalized_payload": {"pstTtl": "합성 교육", "plain_text": "확정된 원문", "content_filter_context": context}, "disposition": "target"}
        if payload_override is not None:
            row["normalized_payload"].update(payload_override)
        calls = []
        def finish(params):
            calls.append(copy.deepcopy(params))
            if finish_error: raise finish_error
            return finish_reply if finish_reply is not None else {"candidateId": ID, "outcome": "inserted"}
        def fail(params):
            if fail_error: raise fail_error
            return fail_reply
        client = FakeClient({"claim_processing_jobs": lambda _: [copy.deepcopy(row)],
                             "finish_content_filter_ai": finish, "fail_content_filter_ai": fail})
        ko = Mock(side_effect=provider_error) if provider_error else Mock(return_value=("\n".join(h + "\n확인된 합성 내용" for h in ("[한 줄 요약]", "[대상]", "[기간·상태]", "[주요 내용]", "[신청 방법]")), "success", "fake-model"))
        if ko_override is not None:
            ko.return_value = ko_override
        ja = Mock(return_value=("合成", "\n".join(h + "\n合成内容" for h in ("[要約]", "[対象]", "[期間・状況]", "[主な内容]", "[申請方法]")), "success", "fake-model"))
        if ja_error is not None:
            ja.side_effect = ja_error
        enqueue = Mock(side_effect=AssertionError("legacy bypass"))
        precheck = Mock(side_effect=AssertionError("snapshot bypass"))
        before = copy.deepcopy(row)
        result = process_ai_jobs(SupabaseIngestStore(client), supabase=object(), summarize_ko=ko,
                                translate_ja=ja, enqueue=enqueue, revision_precheck=precheck, limit=1)
        self.assertEqual(row, before)
        enqueue.assert_not_called(); precheck.assert_not_called()
        return result, client, ko, ja, calls

    def test_generic_new_contract_atomic_finish_and_closed_snapshot(self):
        result, client, ko, ja, calls = self.generic()
        self.assertEqual((result.completed, result.failed, result.retried), (1, 0, 0))
        self.assertEqual([n for n, _ in client.calls], ["claim_processing_jobs", "finish_content_filter_ai"])
        self.assertEqual(ko.call_count, 1); self.assertEqual(ja.call_count, 1)
        self.assertEqual(calls[0]["p_filter_version"], 2)
        self.assertEqual(set(calls[0]["p_output"]), {"aiModel", "titleKo", "titleJa", "summaryKo", "summaryJa", "contentKo", "contentJa"})
        self.assertEqual(ko.call_args.args[0], "확정된 원문")

    def test_reviewed_generic_application_start_remains_in_captured_snapshot(self):
        context = ctx()
        context["data"]["application"]["value"]["start"] = {"value": "2020-09-01", "precision": "day"}
        before = copy.deepcopy(context)
        result, client, ko, ja, calls = self.generic(context)
        self.assertEqual(result.completed, 1)
        self.assertEqual(context, before)
        self.assertEqual(ko.call_args.args[0], "확정된 원문")
        self.assertNotIn("start", calls[0])

    def test_postgrest_clear_error_and_connection_loss_stay_distinct(self):
        class ApiFailure(Exception):
            def __init__(self, message):
                self.message = message
        for error, failed in ((ApiFailure("review_invalid_input"), 1),
                              (ApiFailure("content_filter_fence_lost"), 0),
                              (ApiFailure("private unrecognized response"), 0), (TimeoutError(), 0)):
            result, client, ko, ja, calls = self.generic(finish_error=error)
            self.assertEqual(result.failed, failed)
            self.assertEqual(result.state_unknown, 1 - failed)
            self.assertEqual(len(client.calls), 3 if failed else 2)

    def test_generic_invalid_claim_no_state_mutation_or_provider(self):
        for key, value in (("filterVersion", True), ("workerId", "wrong"), ("data", empty_filters("program")), ("schema", "bad"),
                           ("leaseUntil", (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())):
            c = ctx(); c[key] = value
            result, client, ko, ja, calls = self.generic(c)
            self.assertEqual(result.status, "ai_state_unknown")
            self.assertEqual([n for n, _ in client.calls], ["claim_processing_jobs"])
            ko.assert_not_called(); ja.assert_not_called(); self.assertEqual(calls, [])

    def test_generic_write_unknown_failure_and_lease_loss_not_repeated(self):
        from ingest.store import LeaseLost
        for error in (RpcTimeout(), RpcAmbiguous(), LeaseLost()):
            result, client, ko, ja, calls = self.generic(finish_error=error)
            self.assertEqual((result.completed, result.state_unknown), (0, 1))
            self.assertEqual(len(calls), 1); self.assertEqual(ko.call_count, 1); self.assertEqual(ja.call_count, 1)
            self.assertEqual(len(client.calls), 2)
        for reply in ({}, {"candidateId": "bad", "outcome": "inserted"}, {"candidateId": ID, "outcome": "duplicate"}):
            result, client, ko, ja, calls = self.generic(finish_reply=reply)
            self.assertEqual(result.state_unknown, 1); self.assertEqual(len(client.calls), 2)

    def test_generic_provider_budget_failure_uses_fenced_fail_once(self):
        from ingest.ai_errors import AiJobError
        context = ctx()
        result, client, ko, ja, calls = self.generic(context, provider_error=AiJobError("ai_call_budget"))
        self.assertEqual((result.failed, result.state_unknown, result.retried), (1, 0, 0))
        self.assertEqual(ko.call_count, 1); ja.assert_not_called()
        self.assertEqual([name for name, _ in client.calls], ["claim_processing_jobs", "fail_content_filter_ai"])
        self.assertEqual(client.calls[-1][1], {"p_job_id": JOB, "p_revision": REV, "p_filter_version": 2,
            "p_claimed_at": context["claimedAt"], "p_lease_until": context["leaseUntil"],
            "p_worker_id": WORKER_ID, "p_error_code": "ai_call_budget"})
        self.assertEqual(calls, [])

    def test_provider_refusal_translation_failure_and_bad_format_fail_once(self):
        from ingest.ai_errors import AiJobError
        for kwargs, code in (({"provider_error": AiJobError("ai_refusal")}, "ai_refusal"),
                             ({"ja_error": AiJobError("ai_timeout")}, "ai_timeout"),
                             ({"ko_override": ("잘못된 형식", "success", "fake")}, "ai_schema_error"),
                             ({"provider_error": RuntimeError("private response")}, "ai_or_enqueue_failed")):
            result, client, ko, ja, calls = self.generic(**kwargs)
            self.assertEqual((result.failed, result.retried), (1, 0))
            self.assertEqual(client.calls[-1][0], "fail_content_filter_ai")
            self.assertEqual(client.calls[-1][1]["p_error_code"], code)
            self.assertLessEqual(ja.call_count, 1); self.assertEqual(ko.call_count, 1)
            self.assertEqual(calls, [])

    def test_clear_finish_failure_fails_but_fence_identity_changes_do_not(self):
        from ingest.rpc_errors import RpcFailure
        class ApiFailure(Exception):
            def __init__(self, message): self.message = message
        for code in ("review_invalid_input", "program_candidate_unavailable", "rpc_failure"):
            error = RpcFailure(code) if code == "rpc_failure" else ApiFailure(code)
            result, client, ko, ja, calls = self.generic(finish_error=error)
            self.assertEqual(result.failed, 1)
            self.assertEqual([n for n, _ in client.calls], ["claim_processing_jobs", "finish_content_filter_ai", "fail_content_filter_ai"])
            self.assertEqual(ko.call_count, 1); self.assertEqual(ja.call_count, 1)
        for code in ("content_filter_fence_lost", "content_filter_identity_changed", "content_filter_input_changed", "lease_lost"):
            result, client, ko, ja, calls = self.generic(finish_error=ApiFailure(code))
            self.assertEqual((result.failed, result.state_unknown), (0, 1))
            self.assertEqual(len(client.calls), 2)

    def test_fail_reply_unknown_or_lost_never_repeats(self):
        from ingest.ai_errors import AiJobError
        from ingest.rpc_errors import RpcFailure
        for kwargs in ({"fail_error": RpcTimeout()}, {"fail_error": RpcAmbiguous()},
                       {"fail_error": RpcFailure("content_filter_fence_lost")},
                       {"fail_reply": "queued"}, {"fail_reply": ["failed"]}, {"fail_reply": None}):
            result, client, ko, ja, calls = self.generic(provider_error=AiJobError("ai_refusal"), **kwargs)
            self.assertEqual((result.failed, result.state_unknown, result.retried), (0, 1, 0))
            self.assertEqual([n for n, _ in client.calls], ["claim_processing_jobs", "fail_content_filter_ai"])
            self.assertEqual(ko.call_count, 1); ja.assert_not_called()

    def test_lease_expires_during_provider_no_failure_write(self):
        from ingest.ai_errors import AiJobError
        clock = Mock(wraps=datetime)
        clock.now.return_value = datetime.now(timezone.utc)
        def expired(*args, **kwargs):
            clock.now.return_value += timedelta(hours=2)
            raise AiJobError("ai_timeout")
        with patch("ingest.content_filters.datetime", clock):
            result, client, ko, ja, calls = self.generic(provider_error=expired)
        self.assertEqual((result.failed, result.state_unknown), (0, 1))
        self.assertEqual([n for n, _ in client.calls], ["claim_processing_jobs"])
        self.assertEqual(ko.call_count, 1); ja.assert_not_called()

    def test_failure_adapter_rejects_snapshot_or_unsafe_code_before_rpc(self):
        captured = ctx()
        job = ClaimedJob(JOB, ID, CONTENT, "1:1", REV, "ai_enrichment", "youthcenter_content",
                         {"content_filter_context": captured}, "target")
        client = FakeClient({})
        adapter = SupabaseIngestStore(client)
        changed = copy.deepcopy(captured); changed["filterVersion"] += 1
        with self.assertRaises(RpcAmbiguous):
            adapter.fail_content_filter_ai(job, context=changed, error_code="ai_refusal")
        with self.assertRaises(ValueError):
            adapter.fail_content_filter_ai(job, context=captured, error_code="private response")
        self.assertEqual(client.calls, [])

    def test_generic_invalid_basic_input_never_calls_provider_or_writes(self):
        for payload in ({"plain_text": ""}, {"plain_text": []}, {"pstTtl": ""}, {"pstTtl": 123}):
            result, client, ko, ja, calls = self.generic(payload_override=payload)
            self.assertEqual(result.state_unknown, 1)
            self.assertEqual([name for name, _ in client.calls], ["claim_processing_jobs"])
            ko.assert_not_called(); ja.assert_not_called()
            self.assertEqual(calls, [])

    def test_finish_cannot_replace_captured_filter_snapshot(self):
        captured = ctx()
        job = ClaimedJob(JOB, ID, CONTENT, "1:1", REV, "ai_enrichment", "youthcenter_content",
                         {"content_filter_context": captured}, "target")
        changed = copy.deepcopy(captured)
        changed["data"]["topic"] = field("other")
        client = FakeClient({})
        with self.assertRaises(RpcAmbiguous):
            SupabaseIngestStore(client).finish_content_filter_ai(job, context=changed, output={})
        self.assertEqual(client.calls, [])
        self.assertEqual(job.normalized_payload["content_filter_context"], captured)

    def test_validation_only_cli_no_transport_or_provider(self):
        import run_myseoul_program_ai as my
        import run_seoul_program_ai as seoul
        for cli in (my, seoul):
            execute = Mock(side_effect=AssertionError("not allowed"))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["--source-item-id", ID, "--revision", REV, "--project-ref", "a" * 20], execute=execute), 0)
            execute.assert_not_called()
        import run_ingest_architecture as common
        with patch.object(common, "create_ingest_client", side_effect=AssertionError("no DB")) as db, patch.object(common, "_load_ai_helpers", side_effect=AssertionError("no provider")) as provider, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(common.main(["--source", CONTENT]), 0)
        db.assert_not_called(); provider.assert_not_called()


class CollectorConnectionTests(NoNetwork):
    def test_deferred_category_sidecar_is_separate_and_source_specific(self):
        unknown = normalize(CONTENT, content("방문 가능. 전국 거주자 이용 가능. 시설 이용 안내를 제공합니다."))
        before = copy.deepcopy(unknown)
        packet = _v4_proposal_record(unknown, source_id=CONTENT).to_rpc_item()
        self.assertEqual(packet["filterContract"], SCHEMA)
        self.assertNotIn("filterFacts", packet)
        self.assertNotIn("filterContract", packet["normalized_payload"])
        self.assertEqual(packet["revision_hash"], unknown.revision_hash)
        self.assertEqual(unknown, before)
        self.assertNotIn("filterContract", unknown.to_rpc_item())  # Legacy packet stays opt-out.
        self.assertNotIn("filterContract", _v4_proposal_record(unknown, source_id=POLICY).to_rpc_item())

    def test_my_unknown_category_intent_does_not_guess_new_or_register_legacy(self):
        from test_myseoul_db import sample
        from ingest.myseoul_db import MySeoulObservationAdapter
        record = sample(title="안내", category="기타", purpose="지역 주민에게 소식을 제공합니다.")
        before = copy.deepcopy(record)
        for outcome in ("new", "unchanged"):
            calls = []
            def rpc(name, params):
                calls.append((name, copy.deepcopy(params)))
                return [{"id": ID, "outcome": outcome, "revision": record.revision_hash}]
            result = MySeoulObservationAdapter(rpc).observe(ID, [record], None)
            self.assertEqual(result[0]["outcome"], outcome)
            self.assertEqual([n for n, _ in calls], ["observe_myseoul_program"])
            packet = calls[0][1]["p_items"][0]
            self.assertEqual(packet["filterContract"], SCHEMA)
            self.assertNotIn("filterFacts", packet)
            self.assertEqual(packet["myseoul_facts"]["public_category"], "unknown")
            self.assertNotIn("filterContract", packet["myseoul_facts"])
        self.assertEqual(record, before)

    def test_my_general_collector_sends_filter_metadata_separately(self):
        from test_myseoul_collect import run, ListPage, item
        result, rpc, _ = run({1: ListPage(1, 1, [item(1)], True)})
        packet = next(args["p_items"][0] for name, args in rpc.calls if name == "observe_myseoul_program")
        self.assertEqual(packet["filterFacts"]["data"]["schema"], SCHEMA)
        self.assertEqual(packet["filterContract"], SCHEMA)
        self.assertNotIn("filterFacts", packet["normalized_payload"])
        self.assertNotIn("filterFacts", packet["myseoul_facts"])
        self.assertEqual(result["summary"]["processed"], 1)
        self.assertFalse(any("_ai" in name for name, _ in rpc.calls))

    def test_seoul_existing_observation_adapter_keeps_source_facts_and_revision(self):
        from ingest.connectors.seoul_reservation import normalize_seoul_item
        from ingest.program_db import ProgramObservationAdapter
        from test_seoul_reservation import row
        record = normalize_seoul_item(row())
        original = copy.deepcopy(record)
        calls = []
        ProgramObservationAdapter(lambda n, a: calls.append((n, a))).observe("synthetic-run", [record], None)
        name, params = calls[0]
        self.assertEqual(name, "observe_seoul_program")
        packet = params["p_items"][0]
        self.assertEqual(packet["filterFacts"]["data"]["category"], "program")
        self.assertEqual(packet["filterContract"], SCHEMA)
        self.assertNotIn("filterFacts", packet["program_facts"])
        self.assertNotIn("filterFacts", packet["normalized_payload"])
        self.assertEqual(packet["revision_hash"], record.revision_hash)
        self.assertEqual(record, original)

    def test_general_collector_excludes_then_sends_metadata_to_v4(self):
        rows = [content("취업 직무설명회 참가 신청 가능. 전국 거주자 신청 가능.", key="denied"),
                content("현장 공연을 개최. 전국 거주자 신청 가능. 방문 가능.\n장소: 서울 영등포구 합성 센터", key="kept"),
                content("전국 거주자 방문 가능. 시설 이용 안내를 제공합니다.", key="unknown-category")]
        client = FakeClient({
            "get_ingest_source": lambda _: [{"source_id": CONTENT, "enabled": True, "permission_status": "approved_noncommercial", "legacy_curation_source": "youthcenter_content"}],
            "start_ingest_run": lambda _: [{"run_id": ID, "bootstrap_complete": True, "committed_checkpoint": None, "skipped": False, "skip_reason": None}],
            "upsert_source_observations_v4": lambda p: [{"input_index": i, "external_key": r["external_key"], "outcome": "new", "duplicate_in_batch": False} for i, r in enumerate(p["p_items"])],
            "finish_ingest_run": lambda p: [{"status": p["p_status"], "stop_reason": p["p_stop_reason"]}],
        })
        http = PageHttp([rows])
        result = run_connector(YouthcenterContentConnector(http=http, api_key_provider=lambda: "synthetic"), SupabaseIngestStore(client), sleep=NO_SLEEP, discovered_on=TODAY)
        self.assertEqual(result.status, "complete")
        packet = next(p for name, p in client.calls if name == "upsert_source_observations_v4")
        self.assertEqual(len(packet["p_items"]), 2)
        self.assertEqual(packet["p_items"][0]["filterFacts"]["data"]["category"], "event")
        self.assertEqual(packet["p_items"][0]["filterContract"], SCHEMA)
        self.assertEqual(packet["p_items"][1]["filterContract"], SCHEMA)
        self.assertNotIn("filterFacts", packet["p_items"][1])
        self.assertEqual(result.selection_counts.get("exclude"), 1)
        self.assertEqual(http.request_count, 1)
        self.assertNotIn("claim_processing_jobs", [n for n, _ in client.calls])


if __name__ == "__main__":
    unittest.main()
