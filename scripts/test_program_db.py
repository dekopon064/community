"""Synthetic inputs only. JSON export feeds the isolated SQL parity test."""
import json
import sys
import unittest
from dataclasses import replace
from ingest.connectors.seoul_reservation import normalize_seoul_item
from ingest.program_db import ProgramObservationAdapter, program_rpc_item
from ingest.program_scope import assess_seoul_program, assess_program_facts, extract_program_facts
from test_seoul_reservation import row, NOW


def fixtures(storage=False):
    body = row()["DTLCONT"]
    variants = [({}, "personal"), ({"PAYATNM": "유료", "USETGTINFO": "가족, 어린이와 보호자", "DTLCONT": body + "<p>보호자 동반 필수. 참가비: 10,000원</p>"}, "family_paid"),
                ({"DTLCONT": body + "<p>개인 신청불가. 학교만 신청 가능</p>"}, "school"),
                ({"DTLCONT": body + "<p>개인/단체 신청 가능. 단체 고유번호증 제출</p>"}, "group_docs"),
                ({"DTLCONT": "<p>공예 문화 체험 프로그램으로 주민들과 함께 작품을 만듭니다.</p>"}, "missing_venue"),
                ({"DTLCONT": body + "<p>현재 예약마감</p>"}, "status_conflict"),
                ({"SVCSTATNM": "예약마감"}, "closed"), ({"USETGTINFO": "내국인만"}, "nationality"),
                ({"DTLCONT": "<p>온라인 문화체험 Zoom 수업</p><p>대상: 전국 거주자</p>"}, "online"),
                ({"DTLCONT": "<p>온·오프라인 혼합 문화체험</p><p>장소: 부산 체험관</p><p>대상: 전국 거주자</p>"}, "hybrid_bus"),
                ({"RCPTENDDT": "2026-10-01"}, "date_only"),
                ({"SVCNM": "취업 교육 프로그램"}, "employment"),
                ({"RCPTENDDT": ""}, "missing_date"),
                ({"DTLCONT": body + "<p>일시: 2026년 10월 3일(금)</p>"}, "weekday"),
                ({"SVCOPNBGNDT": "2026-09-01", "SVCOPNENDDT": "2026-09-30"}, "ended"),
                ({"RCPTBGNDT": "2026-10-02"}, "future"),
                ({"SVCURL": ""}, "missing_url")]
    out = []
    for changes, name in variants:
        fields = row(sid=name, **changes)
        if storage:
            fields.update(RCPTBGNDT="2020-01-01", RCPTENDDT="2036-12-31", SVCOPNBGNDT="2020-01-01", SVCOPNENDDT="2036-12-31")
        rec = normalize_seoul_item(fields)
        assessed = assess_seoul_program(rec, now=NOW)
        out.append({"name": name, "item": program_rpc_item(rec), "expected": {
            "decision": assessed.decision, "disposition": assessed.evaluation.disposition, "reasons": list(assessed.reason_codes)}})
    return out


def review_fixtures():
    rec = normalize_seoul_item(row())
    original = extract_program_facts(rec)
    variants = [dict(activity_region="not_applicable", activity_evidence=()),
                dict(activity_evidence=()),
                dict(delivery_mode="online", activity_region="not_applicable", residence_scope="not_stated"),
                dict(delivery_mode="online", residence_scope="nationwide", residence_evidence=()),
                dict(fee_kind="free", fee_amounts=("10,000원",))]
    out = []
    for changes in variants:
        facts = replace(original, **changes)
        result = assess_program_facts(facts, rec.normalized_payload["dates"], now=NOW)
        payload = facts.to_payload()
        payload["periods"] = rec.normalized_payload["dates"]
        out.append({"facts": payload, "expected": {"decision": result.decision, "disposition": result.evaluation.disposition, "reasons": list(result.reason_codes)}})
    return out


class ProgramDBTests(unittest.TestCase):
    def test_review_fix_semantic_region_and_evidence_are_rederived(self):
        rec = normalize_seoul_item(row())
        facts = extract_program_facts(rec)
        for changes, reason in (({"activity_region": "not_applicable", "activity_evidence": ()}, "activity_location_unknown"),
                                ({"activity_evidence": ()}, "activity_location_unknown"),
                                ({"delivery_mode": "online", "activity_region": "not_applicable", "residence_scope": "not_stated"}, "residence_scope_unknown"),
                                ({"delivery_mode": "online", "residence_scope": "nationwide", "residence_evidence": ()}, "residence_scope_unknown")):
            result = assess_program_facts(replace(facts, **changes), rec.normalized_payload["dates"], now=NOW)
            self.assertEqual(result.decision, "review_required")
            self.assertIn(reason, result.reason_codes)

    def test_review_fix_institution_individual_conflicts_survive(self):
        for text in ("학교만 신청 가능", "학교 전용", "기관 전용"):
            rec = normalize_seoul_item(row(DTLCONT=row()["DTLCONT"] + f"<p>{text}. 개인 신청 가능</p>"))
            result = assess_seoul_program(rec, now=NOW)
            self.assertEqual(result.decision, "review_required")
            self.assertIn("application_actor_conflict", result.reason_codes)

    def test_review_fix_missing_periods_and_day_end(self):
        rec = normalize_seoul_item(row(RCPTBGNDT="2026-10-01 10:00:00", RCPTENDDT="2026-10-01"))
        result = assess_seoul_program(rec, now=NOW)
        self.assertEqual(result.decision, "in_scope")
        dates = dict(rec.normalized_payload["dates"])
        dates["SVCOPNENDDT"] = {"status": "missing", "value": None, "precision": None, "raw": None}
        self.assertIn("period_missing_or_unparsed", assess_program_facts(result.facts, dates, now=NOW).reason_codes)

    def test_payload_preserves_original_and_does_not_trust_python_job_decision(self):
        packet = program_rpc_item(normalize_seoul_item(row()))
        self.assertEqual(packet["jobs"], [])
        self.assertIn("source_body_html", packet["normalized_payload"])
        self.assertIn("RCPTENDDT", packet["program_facts"]["periods"])
        self.assertNotIn("gate_facts", packet)

    def test_rpc_is_explicit_injected_transport_and_errors_are_safe(self):
        calls = []
        adapter = ProgramObservationAdapter(lambda name, args: calls.append((name, args)))
        adapter.observe("local-run", [normalize_seoul_item(row())], {"row": 2})
        self.assertEqual(calls[0][0], "observe_seoul_program")
        with self.assertRaises(ValueError): adapter.observe("run", [], None)
        def fail(*args): raise RuntimeError("DO_NOT_EXPOSE_CREDENTIAL")
        with self.assertRaisesRegex(RuntimeError, "^program_observation_failed$"):
            ProgramObservationAdapter(fail).observe("run", [normalize_seoul_item(row())], None)


if __name__ == "__main__":
    if "--fixtures" in sys.argv:
        print(json.dumps({"now": NOW.isoformat(), "fixtures": fixtures(), "storageFixtures": fixtures(storage=True), "reviewFixtures": review_fixtures()}, ensure_ascii=False))
    else: unittest.main()
