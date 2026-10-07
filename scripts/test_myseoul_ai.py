"""New My AI connection tests only. Synthetic fixtures and injected transports."""
import contextlib
import copy
import io
import json
import re
import sys
import unittest
from unittest.mock import Mock

from ingest.myseoul_ai import (PROFILE, SCHEMA, SOURCE, validate_context, myseoul_input,
                               fact_sections, generate_myseoul_output, process_myseoul_job)
from ingest.program_ai import ProgramAIAdapter
from ingest.ai_errors import AiJobError
from ingest.rpc_errors import RpcTimeout
from ingest.ai_claude import build_summary_create_kwargs, MYSEOUL_SUMMARY_SYSTEM, PROGRAM_SUMMARY_SYSTEM
from ingest.source_identity import canonical_source_id, curation_source_for_enqueue
from test_myseoul_db import fixtures
import run_myseoul_program_ai as cli

ID = "00000000-0000-4000-8000-000000000002"
JOB = "00000000-0000-4000-8000-000000000003"


def context(category="program"):
    packet = next(x["item"] for x in fixtures()["fixtures"] if x["name"] == ("event" if category == "event" else "paid_family"))
    f = packet["myseoul_facts"]
    f["session_evidence"] = ["10월 3일 (토) 10:00~11:30, 총 3회"]
    f["meeting_evidence"] = ["09:45 집결"]
    return {"jobId": JOB, "sourceItemId": ID, "source": SOURCE, "externalKey": packet["external_key"],
            "revision": packet["revision_hash"], "schema": SCHEMA, "profile": PROFILE,
            "factsVersion": 2, "title": packet["min_fields"]["title"], "publicCategory": category,
            "facts": f, "observedFacts": copy.deepcopy(f), "claimedAt": "2026-10-02T12:00:00+00:00",
            "leaseUntil": "2026-10-02T12:10:00+00:00", "workerId": "ingest-program-worker"}


def providers(c):
    def summarize(body, url, title=None):
        assert json.loads(body)["currentFacts"]["public_category"] == c["publicCategory"]
        return "[한 줄 요약]\n참여 프로그램입니다.\n[주요 내용]\n교육과 문화 활동입니다.\n" + "\n".join(c["facts"]["conditions"]), "success", "fake-model"
    def translate(title, body):
        assert "진행 일정:" in body and "집결 안내:" in body
        numeric = " ".join(re.findall(r"\d[\d,]*", body))
        return "家族体験", "[要約]\n体験です。\n[対象]\n保護者同伴\n[期間・状況]\n10月3日(土)10:00〜11:30、全3回、09:45集合\n[主な内容]\nソウル " + numeric + "\n[申請方法]\n公式サイト", "success", "fake-model"
    return summarize, translate


class MyAITests(unittest.TestCase):
    def test_exact_source_schema_profile_and_current_facts(self):
        c = context(); self.assertIs(validate_context(c, ID, c["revision"], c["workerId"]), c)
        for key, value in [("source", "seoul_reservation"), ("schema", "gate-facts-v1"), ("profile", "capital_v1"), ("sourceItemId", JOB), ("factsVersion", True), ("publicCategory", "event")]:
            bad = copy.deepcopy(c); bad[key] = value
            with self.assertRaises(AiJobError): validate_context(bad, ID, c["revision"], c["workerId"])

    def test_current_operator_facts_not_original_diagnostics(self):
        c = context(); c["observedFacts"]["description"] = "old"
        c["facts"]["conflicts"] = [{"field": "application_method", "header": ["old"], "body": ["old"], "labels": []}]
        packet = json.loads(myseoul_input(c))
        self.assertIn("description", packet["operatorSupplementedFields"])
        self.assertNotIn("conflicts", packet["currentFacts"])
        self.assertNotIn("observedFacts", packet)
        self.assertEqual(packet["currentFacts"]["fees"], c["facts"]["fees"])
        self.assertIn("periods", packet["currentFacts"])

    def test_schedule_components_and_program_event(self):
        for category in ("program", "event"):
            c = context(category); before = copy.deepcopy(c)
            ko, ja = providers(c); out = generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
            self.assertIn(c["facts"]["session_evidence"][0], out["contentKo"])
            self.assertIn("09:45 집결", out["contentKo"])
            self.assertNotIn("+09:00", out["contentKo"])
            self.assertEqual(c, before)
        fee_text = fact_sections(context()["facts"])["activity"]
        self.assertIn("수강료: 무료", fee_text); self.assertIn("입장료: 3,000원", fee_text)

    def test_translation_omission_fails_without_retry(self):
        c = context(); ko, _ = providers(c)
        ja = Mock(return_value=("家族体験", "[要約]\n体験\n[対象]\n大人\n[期間・状況]\n期間\n[主な内容]\n体験\n[申請方法]\n公式サイト", "success", "fake"))
        with self.assertRaises(AiJobError): generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
        self.assertEqual(ja.call_count, 1)

    def test_period_numbers_do_not_replace_participant_limit(self):
        c = context(); c["facts"]["conditions"] = ["회차당 10명"]
        ko = Mock(return_value=("[한 줄 요약]\n체험입니다.\n[주요 내용]\n체험 활동입니다.", "success", "fake"))
        ja = Mock()
        with self.assertRaises(AiJobError): generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
        ja.assert_not_called()

    def test_gate_allows_reviewed_closed_but_rejects_unresolved_or_excluded(self):
        c = context(); c["facts"]["source_status"] = ["신청마감"]
        before = copy.deepcopy(c)
        self.assertEqual(validate_context(c, ID, c["revision"], c["workerId"]), c)
        self.assertEqual(c, before)
        for change in ({"source_status": ["申請終了", "신청마감"]}, {"issues": [{"code": "target_missing"}]}, {"application_actor": "institution_only"}, {"activity_region": "noncapital"}):
            c = context(); c["facts"].update(change)
            with self.assertRaises(AiJobError): validate_context(c, ID, c["revision"], c["workerId"])

    def test_shared_worker_transport_exact_rpcs_and_fence(self):
        c = context(); ko, ja = providers(c); calls = []
        def rpc(name, args):
            calls.append((name, args))
            return [c] if name.startswith("claim_") else {"outcome": "inserted", "candidateId": JOB}
        r = process_myseoul_job(ProgramAIAdapter(rpc), source_item_id=ID, revision=c["revision"], summarize_ko=ko, translate_ja=ja)
        self.assertEqual(r.completed, 1)
        self.assertEqual([x[0] for x in calls], ["claim_myseoul_program_ai", "finish_myseoul_program_ai"])
        self.assertEqual(calls[1][1]["p_claimed_at"], c["claimedAt"])
        self.assertEqual(calls[1][1]["p_facts_version"], 2)

    def test_ambiguous_finish_not_retried_or_failed(self):
        c = context(); ko, ja = providers(c); calls = []
        def rpc(name, args):
            calls.append(name)
            if name.startswith("claim_"): return [c]
            raise RpcTimeout()
        r = process_myseoul_job(ProgramAIAdapter(rpc), source_item_id=ID, revision=c["revision"], summarize_ko=ko, translate_ja=ja)
        self.assertEqual(r.state_unknown, 1); self.assertEqual(len(calls), 2)

    def test_identity_and_prompt_keep_other_source_behavior(self):
        self.assertEqual(canonical_source_id(SOURCE), SOURCE); self.assertEqual(curation_source_for_enqueue(SOURCE), SOURCE)
        with self.assertRaises(ValueError): canonical_source_id("unknown")
        self.assertEqual(build_summary_create_kwargs(title="", body="", source_url=None, program="myseoul")["system"], MYSEOUL_SUMMARY_SYSTEM)
        self.assertEqual(build_summary_create_kwargs(title="", body="", source_url=None, program=True)["system"], PROGRAM_SUMMARY_SYSTEM)

    def test_cli_validation_only_no_network(self):
        args = ["--source-item-id", ID, "--revision", context()["revision"], "--project-ref", "abcdefghijklmnopqrst"]
        out = io.StringIO(); callback = Mock()
        with contextlib.redirect_stdout(out): self.assertEqual(cli.main(args, execute=callback), 0)
        callback.assert_not_called(); self.assertIn('"network_calls": 0', out.getvalue())


if __name__ == "__main__":
    if "--context-check" in sys.argv:
        c = json.load(sys.stdin)
        validate_context(c, c["sourceItemId"], c["revision"], c["workerId"])
        ko, ja = providers(c)
        out = generate_myseoul_output(c, summarize_ko=ko, translate_ja=ja)
        print(json.dumps({"source": c["source"], "category": c["publicCategory"], "outputFields": sorted(out), "providerCalls": 0}))
    elif "--fixtures" in sys.argv:
        packets = [next(x["item"] for x in fixtures()["fixtures"] if x["name"] == name) for name in ["paid_family", "event"]]
        for p, c in zip(packets, [context(), context("event")]):
            p["myseoul_facts"] = c["facts"]
        print(json.dumps({"packets": packets, "contexts": [context(), context("event")], "outputs": [generate_myseoul_output(c, summarize_ko=providers(c)[0], translate_ja=providers(c)[1]) for c in [context(), context("event")]]}, ensure_ascii=False))
    else:
        unittest.main()
