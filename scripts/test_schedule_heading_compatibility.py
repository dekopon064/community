"""Synthetic headings across provider validation and fenced workers; no network."""
import copy
import json
import socket
import unittest
from unittest.mock import Mock, patch
from ingest.body_sections import normalize_schedule_heading, KO_SECTION_HEADERS
from ingest.ai_worker import extract_summary_section
from ingest.ai_errors import AiJobError
from ingest.myseoul_content import optional_period_section, validate_summary_period
from ingest.myseoul_ai import fact_sections, process_myseoul_job
from ingest.program_ai import ProgramAIAdapter
from ingest.reclassification_ai import process_reclassified_job
from ingest.translation_validation import validate_translation_fidelity
from ingest.ai_claude import SUMMARY_SCHEMA
from ingest.ai_openai import OpenAIAdapter
from ingest.ai_chatgpt_plan import ChatGPTPlanAdapter
from test_ingest_translation_fidelity import adapter_for
from test_ingest_ai_openai import FakeClient, response
from test_ingest_ai_chatgpt_plan import streamed, verified_session
from test_myseoul_schedule_blocks import recorded_context, reviewed_detail, FAKE_JA
from test_myseoul_announcement_continuity import RECORDED_SUMMARY
from test_reclassification_ai import context as classified_context, ID, REV

KO='[한 줄 요약]\n합성 안내\n[일정 안내]\n신청기간: 10월 1일 ~ 10월 2일\n[주요 내용]\n합성 설명'
JA='[要約]\n合成案内\n[日程案内]\n申請期間: 10月1日～10月2日\n[主な内容]\n合成本文'

class HeadingCompatibilityTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden'))
        guard.start();self.addCleanup(guard.stop)

    def test_aliases_exact_body_precision_and_idempotence(self):
        for locale,new,old,body in [('ko','[일정 안내]','[기간·상태]',KO),('ja','[日程案内]','[期間・状況]',JA)]:
            for marker in (old,new):
                for newline in ('\n','\r\n'):
                    value=body.replace(new,marker).replace('\n',newline)
                    result=normalize_schedule_heading(value,locale)
                    self.assertEqual(result,body.replace('\n',newline))
                    self.assertEqual(normalize_schedule_heading(result,locale),result)
        self.assertEqual(extract_summary_section(KO.replace('일정 안내','기간·상태'),'[한 줄 요약]',KO_SECTION_HEADERS),'합성 안내')

    def test_prose_links_and_code_fences_not_rewritten(self):
        for value in ('본문에서 [기간·상태]를 언급', '[기간·상태](https://synthetic.invalid)',
                      '```text\n[기간·상태]\n```', '~~~text\n[기간·상태]\n~~~', '[기간·상태]라는 문장'):
            self.assertEqual(normalize_schedule_heading(value,'ko'),value)

    def test_duplicate_semantic_sections_fail_and_empty_stays_invalid(self):
        for locale,body,marker in [('ko',KO,'[기간·상태]'),('ja',JA,'[期間・状況]')]:
            with self.assertRaises(AiJobError):normalize_schedule_heading(body+'\n'+marker+'\n중복',locale)
        from ingest.myseoul_ai_support import section_body
        with self.assertRaises(AiJobError):section_body('[일정 안내]\n[주요 내용]\n설명','[일정 안내]',KO_SECTION_HEADERS)

    def test_translation_alias_pairs_and_conflicts(self):
        for kh in ('일정 안내','기간·상태'):
            for jh in ('日程案内','期間・状況'):
                validate_translation_fidelity('합성',KO.replace('일정 안내',kh),'合成',JA.replace('日程案内',jh))
        for bad in (JA.replace('[日程案内]\n',''),JA.replace('10月2日','10月3日'),JA+'\n[期間・状況]\n重複'):
            with self.assertRaises(AiJobError):validate_translation_fidelity('합성',KO,'合成',bad)

    def test_existing_schedule_conflict_check_handles_both_headings(self):
        c=recorded_context();f=c['facts']
        for heading in ('기간·상태','일정 안내'):
            body=RECORDED_SUMMARY.replace('기간·상태',heading)
            self.assertTrue(optional_period_section(body))
            validate_summary_period(body,fact_sections(f)['[일정 안내]'],f)
            with self.assertRaises(AiJobError):validate_summary_period(body.replace('10월 30일','10월 31일'),fact_sections(f)['[일정 안내]'],f)

    def test_all_three_providers_share_normalization_and_json_contract(self):
        oldko=KO.replace('일정 안내','기간·상태');oldja=JA.replace('日程案内','期間・状況')
        payload={'content_ko':oldko,'facts':{k:'' for k in SUMMARY_SCHEMA['properties']['facts']['required']}}
        jp={'title_ja':'合成','content_ja':oldja}
        responses=[response(json.dumps(payload,ensure_ascii=False)),response(json.dumps(jp,ensure_ascii=False))]
        claude,cl=adapter_for(oldko,oldja,title_ja='合成')
        oc=FakeClient();oc.responses.results=responses
        pc=streamed(responses);plan=ChatGPTPlanAdapter(client=pc,session=verified_session())
        for adapter in (claude,OpenAIAdapter(client=oc),plan):
            try:
                ko,status,_=adapter.summarize_ko('합성 원문','https://synthetic.invalid')
                self.assertEqual((ko,status),(KO,'success'))
                self.assertEqual(adapter.translate_ja('합성',ko)[1],JA)
            finally:
                if hasattr(adapter,'close'):adapter.close()
        self.assertEqual(len(cl.messages.create_calls),2)
        self.assertEqual(len(oc.responses.requests),2)
        self.assertEqual(len(pc.calls),2)
        self.assertIn('[일정 안내]',oc.responses.requests[1]['input'][0]['content'])
        self.assertEqual(pc.max_retries,0)

    def test_native_worker_translates_new_heading_and_preserves_fence_facts(self):
        c=recorded_context();before=copy.deepcopy(c);events=[];translated=[]
        def rpc(name,args):
            events.append((name,args))
            if name=='claim_myseoul_program_ai':return [copy.deepcopy(c)]
            if name=='admin_myseoul_program_detail':return reviewed_detail(c)
            if name=='finish_myseoul_program_ai':return {'candidateId':c['sourceItemId'],'outcome':'inserted'}
            raise AssertionError('unexpected RPC')
        def ja(title,body):
            translated.append(body);return '合成研修',FAKE_JA,'success','fake'
        result=process_myseoul_job(ProgramAIAdapter(rpc),source_item_id=c['sourceItemId'],revision=c['revision'],worker_id=c['workerId'],
            summarize_ko=Mock(return_value=(RECORDED_SUMMARY,'success','fake')),translate_ja=ja)
        self.assertEqual(result.completed,1)
        output=events[-1][1]['p_output']
        self.assertIn('[일정 안내]',translated[0]);self.assertNotIn('[기간·상태]',translated[0])
        self.assertIn('[日程案内]',output['contentJa']);self.assertEqual(c,before)
        self.assertEqual(events[-1][1]['p_facts_version'],c['factsVersion'])

    def test_reclassified_worker_normalizes_before_translation_and_completion(self):
        c=classified_context();before=copy.deepcopy(c);events=[];inputs=[]
        def rpc(name,args):
            events.append((name,args))
            if name=='claim_reclassified_content_ai':return copy.deepcopy(c)
            if name=='finish_reclassified_content_ai':return {'candidateId':ID,'outcome':'inserted'}
            raise AssertionError('unexpected RPC')
        def ja(title,body):
            inputs.append(body)
            import re
            return '合成',JA+'\n'+ ' '.join(re.findall(r'\d[\d,]*',body)),'success','fake'
        result=process_reclassified_job(ProgramAIAdapter(rpc),source_item_id=ID,revision=REV,classification_version=1,worker_id='synthetic-worker',
            summarize_ko=Mock(return_value=(KO.replace('일정 안내','기간·상태'),'success','fake')),translate_ja=ja)
        self.assertEqual(result.completed,1)
        self.assertIn('[일정 안내]',inputs[0]);self.assertEqual(c,before)
        self.assertEqual(events[-1][1]['p_classification_version'],1)

    def test_duplicate_heading_stops_translation_and_candidate_completion(self):
        c=recorded_context();events=[]
        def rpc(name,args):
            events.append(name)
            if name=='claim_myseoul_program_ai':return [copy.deepcopy(c)]
            if name=='admin_myseoul_program_detail':return reviewed_detail(c)
            if name=='fail_myseoul_program_ai':return 'failed'
            raise AssertionError('unexpected RPC')
        ja=Mock()
        result=process_myseoul_job(ProgramAIAdapter(rpc),source_item_id=c['sourceItemId'],revision=c['revision'],worker_id=c['workerId'],
            summarize_ko=Mock(return_value=(RECORDED_SUMMARY+'\n[일정 안내]\n중복 일정','success','fake')),translate_ja=ja)
        self.assertEqual((result.completed,result.failed),(0,1))
        ja.assert_not_called();self.assertNotIn('finish_myseoul_program_ai',events)

if __name__=='__main__':unittest.main()
