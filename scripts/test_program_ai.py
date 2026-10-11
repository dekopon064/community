"""Synthetic current facts and fake RPC/provider only. No network or environment."""
import copy
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job, program_input, protected_facts
from ingest.ai_worker import process_ai_jobs
from ingest.ai_worker import _process_one
from ingest.models import ClaimedJob
from ingest.ai_claude import build_summary_create_kwargs, SUMMARY_SYSTEM, PROGRAM_SUMMARY_SYSTEM
from ingest.ai_errors import AiJobError
from ingest.rpc_errors import RpcTimeout
from test_program_db import fixtures

ID = "00000000-0000-4000-8000-000000000002"
JOB = "00000000-0000-4000-8000-000000000003"
REV = "a" * 64


def bind_program_filters(c):
    from ingest.content_filters import SCHEMA,empty_filters,field,confirmed_filter_values
    data=empty_filters('program')
    data.update(topic=field('culture_experience'),audience=field('other'),
        location=field({'scope':'specific','venues':[{'province':'11','district':'종로구','facility':'','address':''}]}))
    for key,value in confirmed_filter_values(c['facts']).items():data[key]=field(value)
    now=datetime.now(timezone.utc)
    c.update(claimedAt=now.isoformat(),leaseUntil=(now+timedelta(seconds=600)).isoformat())
    c['filterContext']={'schema':SCHEMA,'filterVersion':2,'data':data,
        **{key:c[key] for key in ('claimedAt','leaseUntil','workerId')}}
    return c


def context():
    f = json.loads(json.dumps(fixtures(storage=True)[1]["item"]["program_facts"]))
    return bind_program_filters({"jobId": JOB, "sourceItemId": ID, "source": "seoul_reservation", "externalKey": "family_paid", "revision": REV,
        "schema": "program-scope-v1-local", "profile": "program_capital_v1_local", "factsVersion": 2,
        "title": "성인 공예 체험", "apiCategory": "문화체험", "facts": f, "observedFacts": copy.deepcopy(f),
        "workerId": "ingest-program-worker"})


def providers(c):
    calls = []
    def summarize(body, url, title=None):
        calls.append(json.loads(body))
        assert url == c["facts"]["official_url"] and title == c["title"]
        return "[한 줄 요약]\n家族 체험\n[주요 내용]\n공예 프로그램", "success", "fake-model"
    def translate(title, body):
        # Explicit synthetic Japanese output, NOT real translation quality evidence.
        from ingest.seoul_content import reviewed_sections
        from test_seoul_content import fake_japanese
        for value in reviewed_sections(c['facts']).values():
            if value:assert value in body
        return "家族体験", fake_japanese(body), "success", "fake-model"
    return summarize, translate, calls


class ProgramAITests(unittest.TestCase):
    def run_job(self, c=None, rpc_override=None, summarize=None, translate=None):
        c = c or context(); events = []
        ko, ja, calls = providers(c)
        def rpc(name, args):
            events.append((name, args))
            if rpc_override:
                value = rpc_override(name, args)
                if value is not None:
                    return value
            if name == "claim_seoul_program_ai": return [c]
            if name == "finish_seoul_program_ai": return {"candidateId": ID, "outcome": "inserted"}
            if name == "fail_seoul_program_ai": return "queued"
            raise AssertionError(name)
        result = process_seoul_program_job(ProgramAIAdapter(rpc), source_item_id=ID, revision=REV,
            summarize_ko=summarize or ko, translate_ja=translate or ja)
        return result, events, calls

    def test_current_facts_and_atomic_completion_no_legacy_calls(self):
        c = context(); c["facts"]["description"] = "운영자가 공식 자료를 확인하여 보완한 문화체험 프로그램 설명입니다."
        result, events, inputs = self.run_job(c)
        self.assertEqual(result.completed, 1)
        self.assertEqual([e[0] for e in events], ["claim_seoul_program_ai", "finish_seoul_program_ai"])
        self.assertIn("description", inputs[0]["operatorSupplementedFields"])
        self.assertNotIn("source_body_html", json.dumps(events, ensure_ascii=False))
        self.assertNotIn("observedFacts", events[-1][1]["p_output"])
        self.assertIn("보호자", events[-1][1]["p_output"]["contentKo"])
        self.assertEqual(events[-1][1]["p_facts_version"], 2)

    def test_no_jobs_does_not_call_provider(self):
        result, events, inputs = self.run_job(rpc_override=lambda n,a: [] if n.startswith("claim") else None)
        self.assertEqual(result.status, "ai_no_jobs"); self.assertFalse(inputs)

    def test_wrong_target_schema_profile_or_category_fails_closed(self):
        for k,v in [("sourceItemId", JOB),("schema","gate-facts-v1"),("profile","capital_v1"),("apiCategory","교육"),("factsVersion",True)]:
            c=context();c[k]=v
            result,events,inputs=self.run_job(c)
            self.assertEqual(result.state_unknown,1);self.assertEqual(len(events),1);self.assertFalse(inputs)

    def test_missing_conflicting_facts_are_not_sent(self):
        for key in ("missing","conflicts"):
            c=context();c["facts"][key]=["unresolved"]
            result,events,inputs=self.run_job(c)
            self.assertEqual(result.state_unknown,1);self.assertFalse(inputs)

    def test_absent_or_incomplete_filter_snapshot_never_calls_provider(self):
        for missing in [True,False]:
            c=context()
            if missing:c.pop('filterContext')
            else:c['filterContext']['data']['topic']={'status':'unknown','value':None}
            result,events,inputs=self.run_job(c)
            self.assertEqual(result.state_unknown,1);self.assertFalse(inputs)
            self.assertEqual(len(events),1)

    def test_program_prompt_and_legacy_prompt_separate(self):
        old=build_summary_create_kwargs(title="t",body="b",source_url=None)
        new=build_summary_create_kwargs(title="t",body="b",source_url=None,program=True)
        self.assertEqual(old["system"],SUMMARY_SYSTEM);self.assertEqual(new["system"],PROGRAM_SUMMARY_SYSTEM)
        self.assertIn("participation",new["system"])

    def test_bound_provider_uses_program_prompt_path(self):
        c=context();ko,ja,_=providers(c)
        class Provider:
            def summarize_ko(self,*args,**kwargs):raise AssertionError('legacy prompt used')
            def summarize_program_ko(self,*args,**kwargs):return ko(*args,**kwargs)
        result,_,_=self.run_job(summarize=Provider().summarize_ko)
        self.assertEqual(result.completed,1)

    def test_provider_failure_uses_attempt_fenced_retry(self):
        def fail(*a,**kw): raise AiJobError("ai_blocked_cost_cap")
        c=context();result,events,_=self.run_job(c,summarize=fail)
        self.assertEqual(result.retried,1);self.assertEqual(events[-1][0],"fail_seoul_program_ai")
        self.assertEqual(events[-1][1]["p_claimed_at"],c["claimedAt"])

    def test_numeric_omission_is_failed_before_storage(self):
        result,events,_=self.run_job(translate=lambda *a:("体験","[要約]\n体験\n[主な内容]\n参加","success","fake"))
        self.assertEqual(result.retried,1);self.assertNotIn("finish_seoul_program_ai",[e[0] for e in events])

    def test_ambiguous_finish_does_not_retry_fail_or_complete(self):
        def rpc(n,a):
            if n=="finish_seoul_program_ai":raise RpcTimeout()
        result,events,_=self.run_job(rpc_override=rpc)
        self.assertEqual(result.state_unknown,1);self.assertEqual(len(events),2)

    def test_malformed_finish_reply_does_not_mutate_job_again(self):
        for reply in [{"outcome":"inserted"},{"outcome":"duplicate","candidateId":"not-a-uuid"}]:
            result,events,_=self.run_job(rpc_override=lambda n,a: reply if n=='finish_seoul_program_ai' else None)
            self.assertEqual(result.state_unknown,1);self.assertEqual(len(events),2)

    def test_secret_transport_error_is_not_returned(self):
        def rpc(n,a):raise RuntimeError("SECRET_SENTINEL URL_WITH_KEY")
        result,_,_=self.run_job(rpc_override=rpc)
        self.assertNotIn("SECRET",str(result));self.assertEqual(result.state_unknown,1)

    def test_existing_worker_explicit_branch_does_not_touch_legacy_store(self):
        c=context();ko,ja,_=providers(c)
        def rpc(n,a):return [c] if n.startswith("claim") else {"candidateId":ID,"outcome":"inserted"}
        result=process_ai_jobs(object(),program_adapter=ProgramAIAdapter(rpc),limit=1,target_source_item_id=ID,
            target_revision_hash=REV,summarize_ko=ko,translate_ja=ja)
        self.assertEqual(result.completed,1)
        self.assertEqual(process_ai_jobs(object(),program_adapter=ProgramAIAdapter(rpc),limit=5).state_unknown,1)

    def test_seoul_cannot_enter_legacy_payload_path(self):
        job=ClaimedJob(JOB,ID,"seoul_reservation","test",REV,"ai_enrichment","seoul_reservation",{},"target")
        def forbidden(*a,**kw):raise AssertionError('legacy provider called')
        with self.assertRaises(AiJobError):
            _process_one(job,supabase=None,summarize_ko=forbidden,translate_ja=forbidden,enqueue=forbidden,revision_precheck=forbidden)


if __name__ == "__main__":
    if "--packet" in sys.argv:
        c=json.load(sys.stdin);ko,ja,_=providers(c);captured={}
        def rpc(n,a):
            if n=="claim_seoul_program_ai":return [c]
            if n=="finish_seoul_program_ai":captured.update(a);return {"candidateId":ID,"outcome":"inserted"}
            raise AssertionError(n)
        result=process_seoul_program_job(ProgramAIAdapter(rpc),source_item_id=c["sourceItemId"],revision=c["revision"],summarize_ko=ko,translate_ja=ja)
        if result.completed!=1:raise AssertionError("synthetic pipeline did not complete")
        print(json.dumps(captured,ensure_ascii=False))
    else:unittest.main()
