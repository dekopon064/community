"""Synthetic storage/facts tests; no live site, environment or provider reads.

--fixtures exports bounded synthetic packets for server/isolated SQL tests.
"""
from __future__ import annotations
import copy
import json
import sys
import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from uuid import UUID

from ingest.connectors.myseoul_program import normalize_detail, MySeoulProgramConnector
from ingest.myseoul_db import SCHEMA, MySeoulObservationAdapter, evaluate_myseoul_facts, myseoul_facts, myseoul_rpc_item
from ingest.myseoul_scope import KST, assess_myseoul
from test_myseoul_program import detail, url

NOW = datetime(2026, 10, 2, 15, tzinfo=KST)

def sample(**options):
    defaults = dict(application="2020-01-01 10:00 ~ 2099-10-15 18:00", operation="2026-10-03 ~ 2099-10-17")
    defaults.update(options)
    return normalize_detail(detail(**defaults), url())

def observation_response(records, outcomes=None):
    outcomes = outcomes or ["new"] * len(records)
    return [{"id": str(UUID(int=i + 1)), "outcome": outcome, "revision": record.revision_hash}
            for i, (record, outcome) in enumerate(zip(records, outcomes))]


def fixtures():
    cases = {
        "personal": {}, "paid_family": {"target":"성인과 어린이 가족", "tuition":"무료", "extra":"<p>입장료: 3,000원</p><p>조건: 보호자 동반 필수</p>"},
        "employment": {"title":"취업 안전 교육", "purpose":"외국인 주민 취업 지원과 안전 교육 수업", "category":"교육"},
        "event": {"title":"관용의 날 기념행사", "purpose":"외국인 주민이 함께하는 기념행사와 공연입니다.", "category":"교류"},
        "institution": {"target":"학교만 신청 가능, 개인 신청 불가"},
        "noncapital": {"venue":"부산 체험관"},
        "online": {"mode":"온라인", "target":"전국 외국인 주민", "venue":""},
        "online_noncapital": {"mode":"온라인", "target":"부산 거주자만", "venue":""},
        "missing_mode": {"venue":"", "mode":""},
        "two_conflicts": {"extra":"<p>신청방법: 방문 접수</p><p>수강료: 5,000원</p>"},
        "unsupported": {"operation":"2026년 10월 14일 오전 9:00~11:30"},
        "complex_fee": {"extra":"<p>참가비: 3,000원 (입장료와 재료비)</p>"},
        "visa": {"target":"서울 거주 외국인 성인 D-2 비자 필수"},
        "closed": {"status":"신청마감"},
    }
    out=[]
    for n,(name,options) in enumerate(cases.items()):
        # Different canonical IDs, never title-based merging.
        program=f"{n+1:032X}"
        params={"application":"2020-01-01 10:00 ~ 2099-10-15 18:00", "operation":"2026-10-03 ~ 2099-10-17", **options}
        r=normalize_detail(detail(**params),url(program=program))
        item=myseoul_rpc_item(r,now=NOW)
        out.append({"name":name,"item":item,"expected":evaluate_myseoul_facts(item["myseoul_facts"],now=NOW)})
    return {"now":NOW.isoformat(),"fixtures":out}

class MySeoulStorageTests(unittest.TestCase):
    def test_original_facts_are_unchanged(self):
        r=sample(); before=copy.deepcopy(r.normalized_payload)
        f=myseoul_facts(r,now=NOW)
        self.assertEqual(r.normalized_payload,before)
        self.assertEqual(f["schema_version"],SCHEMA)
        self.assertEqual(f["parser_version"],"myseoul-html-v2-local")
        self.assertEqual(f["revision_contract"],"myseoul-semantic-v2")

    def test_no_ai_or_legacy_source(self):
        self.assertEqual(MySeoulProgramConnector.source_kind,"content")
        item=myseoul_rpc_item(sample(),now=NOW)
        self.assertEqual(item["jobs"],[]);self.assertEqual(item["relationships"],[])
        self.assertEqual(item["disposition"],"observe_only")
        self.assertEqual(item["source_updated_at"],None)
        record=sample();rpc=Mock(return_value=observation_response([record]));a=MySeoulObservationAdapter(rpc)
        a.observe("synthetic-run",[record],None)
        self.assertEqual(rpc.call_args.args[0],"observe_myseoul_program")

    def test_observe_packages_existing_contract_and_returns_all_outcomes(self):
        records = [normalize_detail(detail(title=f"합성 프로그램 {i}"), url(program=f"{i:032X}"))
                   for i in range(1, 4)]
        checkpoint = {"page_num": 2}
        result = observation_response(records, ["new", "changed", "unchanged"])
        before = copy.deepcopy((records, checkpoint, result))
        expected = [myseoul_rpc_item(record, now=NOW) for record in records]
        rpc = Mock(return_value=result)
        with patch("ingest.myseoul_db.datetime") as clock:
            clock.now.return_value = NOW
            actual = MySeoulObservationAdapter(rpc).observe("synthetic-run", records, checkpoint)
        rpc.assert_called_once_with("observe_myseoul_program", {
            "p_run_id": "synthetic-run", "p_items": expected, "p_next_checkpoint": checkpoint})
        self.assertIs(actual, result)
        self.assertEqual((records, checkpoint, result), before)
        for record, packet in zip(records, rpc.call_args.args[1]["p_items"]):
            self.assertIsNot(packet["normalized_payload"], record.normalized_payload)
            self.assertIsNot(packet["min_fields"], record.min_fields)
            self.assertEqual(packet["jobs"], [])
            self.assertEqual(packet["relationships"], [])

    def test_observe_rejects_invalid_response_without_retry_or_mutation(self):
        record = sample()
        valid = observation_response([record])[0]
        cases = [None, {}, (), [], [valid, valid], [None], ["row"], [[]], [{}]]
        # Required values are limited to fields actually returned by the RPC.
        cases += [[{key: value for key, value in valid.items() if key != missing}]
                  for missing in ("id", "outcome", "revision")]
        cases += [[{**valid, field: value}] for field, values in (
            ("id", (None, 1, [], "", "not-a-uuid")),
            ("outcome", (None, 1, [], {}, "", "unsupported")),
            ("revision", (None, 1, [], "", "0" * 64)),
        ) for value in values]
        for response in cases:
            with self.subTest(response=response):
                before = copy.deepcopy((record, response))
                rpc = Mock(return_value=response)
                with self.assertRaisesRegex(RuntimeError, "^myseoul_observation_response_invalid$"):
                    MySeoulObservationAdapter(rpc).observe("synthetic-run", [record], None)
                rpc.assert_called_once()
                self.assertEqual((record, response), before)

    def test_observe_checks_each_batch_revision(self):
        records = [sample(), normalize_detail(detail(title="다른 합성 프로그램"), url(program=f"{2:032X}"))]
        response = observation_response(records)
        self.assertNotEqual(records[0].revision_hash, records[1].revision_hash)
        for result in (response[:1], response + response[:1], list(reversed(response))):
            with self.subTest(result=result):
                rpc = Mock(return_value=result)
                with self.assertRaisesRegex(RuntimeError, "^myseoul_observation_response_invalid$"):
                    MySeoulObservationAdapter(rpc).observe("synthetic-run", records, None)
                rpc.assert_called_once()

    def test_observe_timeout_is_unknown_and_never_retried(self):
        rpc = Mock(side_effect=TimeoutError("PRIVATE_SENTINEL"))
        with self.assertRaisesRegex(RuntimeError, "^myseoul_observation_failed$") as caught:
            MySeoulObservationAdapter(rpc).observe("synthetic-run", [sample()], None)
        rpc.assert_called_once()
        self.assertIsNone(caught.exception.__cause__)

    def test_rpc_input_copy_is_isolated_from_observation(self):
        record = sample()
        before = copy.deepcopy(record)
        def rpc(name, args):
            self.assertEqual(name, "observe_myseoul_program")
            packet = args["p_items"][0]
            packet["normalized_payload"]["description"] = "fake transport mutation"
            packet["min_fields"].clear()
            packet["myseoul_facts"].clear()
            return observation_response([record])
        MySeoulObservationAdapter(rpc).observe("synthetic-run", [record], None)
        self.assertEqual(record, before)

    def test_source_and_parser_mismatch(self):
        for key,value in [("source_language","en"),("parser_version","different"),("revision_contract","other")]:
            r=sample();r.normalized_payload[key]=value
            with self.assertRaises(ValueError):myseoul_rpc_item(r,now=NOW)

    def test_batch_limits_and_transport_redaction(self):
        a=MySeoulObservationAdapter(Mock(side_effect=RuntimeError("SECRET")))
        for rows in [[],[sample()]*41]:
            with self.assertRaises(ValueError):a.observe("run",rows,None)
        with self.assertRaisesRegex(RuntimeError,"^myseoul_observation_failed$"):a.observe("run",[sample()],None)
        with self.assertRaisesRegex(RuntimeError,"^myseoul_finish_failed$"):a.finish("run",{},requests=1,batches=1)

    def test_extraction_and_stored_decisions_match(self):
        for options in [{},{"target":"가족, 성인과 어린이"},{"tuition":"5,000원"},{"mode":"온라인","target":"전국 외국인 주민"},
                        {"target":"학교만 신청 가능, 개인 신청 불가"},{"venue":"부산 체험관"},{"venue":"","mode":""},
                        {"status":"신청마감"},{"purpose":"외국인 취업 지원 교육 수업", "title":"취업 지원 교육"}]:
            r=sample(**options);local=assess_myseoul(r,now=NOW);stored=evaluate_myseoul_facts(myseoul_facts(r,now=NOW),now=NOW)
            self.assertEqual(stored["scope"],local.scope)
            self.assertEqual(stored["application"],local.application)
            self.assertEqual(stored["quality"],local.quality)
            self.assertEqual(stored["decision"],{"include":"in_scope","review":"review_required","exclude":"out_of_scope" if local.scope=="excluded" else "not_currently_available"}[local.decision])

    def test_conflicts_are_field_specific(self):
        f=myseoul_facts(sample(extra="<p>신청방법: 방문 접수</p><p>수강료: 3,000원</p>"),now=NOW)
        self.assertEqual({x["code"] for x in f["issues"]},{"source_fact_conflict:application_method","source_fact_conflict:tuition"})

    def test_date_day_inclusive_and_minute(self):
        f=myseoul_facts(sample(application="2026-10-01 ~ 2026-10-02"),now=NOW)
        self.assertEqual(evaluate_myseoul_facts(f,now=datetime(2026,10,2,23,59,tzinfo=KST))["application"],"open")
        self.assertEqual(evaluate_myseoul_facts(f,now=datetime(2026,10,3,0,tzinfo=KST))["application"],"closed")
        self.assertEqual(myseoul_facts(sample(),now=NOW)["periods"]["application"][0]["endpoints"][0]["precision"],"minute")

    def test_current_facts_control_reevaluation(self):
        f=myseoul_facts(sample(venue="",mode=""),now=NOW)
        f.update(venue="서울 실제 개최 장소",delivery_mode="offline",activity_region="capital",activity_evidence=["공식 안내 서울 개최"])
        f["issues"]=[]
        self.assertEqual(evaluate_myseoul_facts(f,now=NOW)["decision"],"in_scope")
        self.assertEqual(evaluate_myseoul_facts(f,now=NOW)["ai_status"],"blocked")

    def test_temporal_conflict_matches_extraction_unknown(self):
        r=sample(extra="<p>신청기간: 2020-01-01 10:00 ~ 2099-10-16 18:00</p>")
        original=assess_myseoul(r,now=NOW)
        result=evaluate_myseoul_facts(myseoul_facts(r,now=NOW),now=NOW)
        self.assertEqual(original.application,"unknown")
        self.assertEqual(result["application"],original.application)
        self.assertEqual(result["quality"],original.quality)

    def test_cosmetic_changes_do_not_clear_conflict(self):
        f=myseoul_facts(sample(),now=NOW)
        f["fees"]=[{"component":"tuition","evidence":["무료","5,000원 (표기 정리)"]}]
        self.assertIn("source_fact_conflict:tuition",evaluate_myseoul_facts(f,now=NOW)["reasons"])
        f["fees"]=[{"component":"admission","evidence":["3,000원","3,000원 (입장료)"]}]
        self.assertEqual(evaluate_myseoul_facts(f,now=NOW)["decision"],"in_scope")

if __name__ == "__main__":
    if "--fixtures" in sys.argv:print(json.dumps(fixtures(),ensure_ascii=False))
    else:unittest.main()
