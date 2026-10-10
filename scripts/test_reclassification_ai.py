"""Injected provider/RPC only; every socket/SDK connection is forbidden."""
import copy
import json
import re
import socket
import unittest
from unittest.mock import patch
from uuid import UUID
from ingest.reclassification_ai import validate_context,classification_input,protected_information,process_reclassified_job
from ingest.program_ai import ProgramAIAdapter
from run_reclassified_content_ai import main

ID='40000000-0000-4000-8000-000000000901';REV='a'*64
def context(cat='living',source='myseoul_program'):
    k=lambda v:{'status':'known','value':v};na={'status':'not_applicable','value':None}
    filters={'schema':'content-filters-v1','category':cat,**{name:copy.deepcopy(na) for name in ['topic','location','delivery','audience','spaceKind','application','schedule']}}
    if cat=='program':filters.update(topic=k('culture_experience'),delivery=k('online'),audience=k('other'),application=k({'deadlineKind':'none','start':None,'end':None,'sourceStatus':'unknown'}))
    if cat=='event':filters.update(topic=k('festival_exchange'),location=k({'scope':'specific','venues':[{'province':'11','district':None,'facility':'','address':''}]}),schedule=k({'kind':'continuous','occurrences':[{'start':{'value':'2099-10-09','precision':'day'},'end':{'value':'2099-10-09','precision':'day'}}],'recurrence':None}))
    if cat=='youth_space':filters.update(spaceKind=k('introduction'),location=k({'scope':'specific','venues':[{'province':'11','district':None,'facility':'','address':''}]}))
    return {'schema':'review-classification-ai-v1','jobId':ID,'sourceItemId':ID,'revision':REV,'classificationVersion':1,'workerId':'synthetic-worker','claimedAt':'2099-10-09T09:00:00+09:00','leaseUntil':'2099-10-09T09:05:00+09:00','source':source,'externalKey':'synthetic','sourceUrl':'https://synthetic.invalid/item','title':'합성 안내','body':'실제 콘텐츠가 아닌 합성 원문입니다.',
        'facts':{'category':cat,'productType':'living_guide' if cat=='living' else 'policy_reference' if cat=='policy' else 'event_program','scope':'nationwide','regions':[],'evidence':'합성 전국 신청 근거','foreignEligibility':'eligible' if cat=='policy' else 'unknown','delivery':'online','deadlineKind':'none' if cat in {'program','policy'} else '','deadlineOn':'','eventStart':'2099-10-09' if cat=='event' else '','eventEnd':'2099-10-09' if cat=='event' else ''},'filters':filters if cat in {'program','event','youth_space'} else None,'nativeConfirmedFacts':{'programFacts':{'conditions':['합성 보호자 동반 조건'],'fees':[{'amount':10000,'currency':'KRW','evidence':['합성 원문 비용']}],'application_methods':['합성 신청 방법']},'gateFacts':None}}

class ClassificationAITests(unittest.TestCase):
    def setUp(self):
        self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('external network forbidden'));self.network.start();self.addCleanup(self.network.stop)
    def run_job(self,c=None,mode='success',provider_mode='success'):
        c=c or context();events=[];inputs=[]
        def rpc(name,args):
            events.append((name,args))
            if name=='claim_reclassified_content_ai':return c
            if name=='finish_reclassified_content_ai':
                if mode.startswith('unknown'):raise TimeoutError()
                return {'candidateId':ID,'outcome':'inserted'}
            if name=='reclassified_content_ai_status':return {'status':'completed' if mode=='unknown_saved' else 'active','candidateId':ID if mode=='unknown_saved' else None}
            raise AssertionError('unexpected RPC')
        def ko(body,url,*,title):
            inputs.append(json.loads(body));self.assertEqual(inputs[-1]['nativeConfirmedFacts'],c['nativeConfirmedFacts']);self.assertEqual(inputs[-1]['currentClassificationFacts'],c['facts']);self.assertEqual(inputs[-1]['currentFilters'],c['filters'])
            if provider_mode=='fail':raise TimeoutError()
            return '[한 줄 요약]\n합성 안내\n[주요 내용]\n합성 본문','success','fake-model'
        def ja(title,body):
            self.assertIn(protected_information(c),body)
            return '合成案内','[要約]\n合成案内\n[主な内容]\n参加条件は原文をご確認ください。 '+ ' '.join(re.findall(r'\d[\d,]*',body)),'success','fake-model'
        result=process_reclassified_job(ProgramAIAdapter(rpc),source_item_id=ID,revision=REV,classification_version=1,worker_id='synthetic-worker',summarize_ko=ko,translate_ja=ja)
        return result,events,inputs
    def test_all_categories_and_sources_without_source_name_restriction(self):
        for cat in ['policy','program','event','youth_space','living']:
            for source in ['myseoul_program','seoul_reservation','youthcenter_policy','youthcenter_content']:
                with self.subTest(cat=cat,source=source):
                    result,events,inputs=self.run_job(context(cat,source));self.assertEqual(result.completed,1);self.assertEqual([n for n,_ in events],['claim_reclassified_content_ai','finish_reclassified_content_ai']);self.assertEqual(len(inputs),1);self.assertEqual(result.retried,0)
    def test_invalid_claim_no_provider_or_additional_write(self):
        for field,value in [('sourceItemId','40000000-0000-4000-8000-000000000902'),('revision','b'*64),('classificationVersion',2),('workerId','other'),('schema','other'),('jobId','invalid'),('nativeConfirmedFacts',{}),('leaseUntil','2099-10-09T09:00:00+09:00')]:
            with self.subTest(field=field):
                c=context();c[field]=value;result,events,inputs=self.run_job(c);self.assertEqual(result.state_unknown,1);self.assertEqual(len(events),1);self.assertEqual(inputs,[])
    def test_unknown_finish_read_only_reconciliation(self):
        for mode,completed in [('unknown',0),('unknown_saved',1)]:
            result,events,inputs=self.run_job(mode=mode);self.assertEqual(result.completed,completed);self.assertEqual(len(inputs),1);self.assertEqual([n for n,_ in events],['claim_reclassified_content_ai','finish_reclassified_content_ai','reclassified_content_ai_status']);self.assertFalse(events[-1][1]['p_close_expired']);self.assertEqual(result.retried,0)
    def test_provider_failure_does_not_retry_or_close_active_attempt(self):
        result,events,inputs=self.run_job(provider_mode='fail');self.assertEqual(result.state_unknown,1);self.assertEqual(len(inputs),1);self.assertEqual([n for n,_ in events],['claim_reclassified_content_ai','reclassified_content_ai_status']);self.assertFalse(events[-1][1]['p_close_expired'])
    def test_cli_default_no_execution(self):
        from io import StringIO
        import contextlib
        with contextlib.redirect_stdout(StringIO()) as out:
            rc=main(['--source-item-id',ID,'--revision',REV,'--classification-version','1','--project-ref','a'*20],execute=lambda _:self.fail('execution forbidden'))
        self.assertEqual(rc,0);self.assertEqual(json.loads(out.getvalue())['network_calls'],0)

if __name__=='__main__':unittest.main()
