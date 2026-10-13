"""Synthetic API, verified fake Pro grant and fake RPC; no real I/O."""
import copy
import io
import json
import socket
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from ingest.ai_provider import create_provider_adapter
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job
from ingest.reclassification_ai import process_reclassified_job
from ingest.seoul_content import assemble_seoul_body
from ingest.seoul_workflow import plan_collection,process_seoul_queue,require_new_only_collection_contract
from test_seoul_reservation import row
from test_program_ai import context,ID,REV,bind_program_filters
from test_seoul_content import synthetic_facts,SUMMARY,fake_japanese
from test_ingest_ai_chatgpt_plan import verified_session,streamed
from test_ingest_ai_openai import response
from test_reclassification_ai import context as classified_context

TABLE_DESCRIPTION='합성 공예 체험\n정원: 20명\n| 회차 | 일시 | 활동 |\n| --- | --- | --- |\n| 1회차 | 10월 18일 10:00~12:00 | 공예 |\n| 2회차 | 10월 25일 10:00~12:00 | 완성 |'


class SeoulWorkflowTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden'))
        guard.start();self.addCleanup(guard.stop)
    def test_fifty_targets_partitioned_to_existing_forty_contract(self):
        plan=plan_collection([row(sid=f'culture_{i}') for i in range(50)],existing_keys=frozenset(),natural_end=False)
        self.assertEqual([len(v) for v in plan.batches],[40,10])
        self.assertEqual(plan.counters['scanned'],50)
        self.assertEqual(plan.counters['new_saved'],0);self.assertIsNone(plan.counters['ai_waiting'])
        self.assertEqual(plan.counters['ai_calls'],0)
        self.assertEqual(plan.counters['coverage'],'bounded_page_only')
    def test_category_existing_even_changed_and_invalid_rows(self):
        rows=[row(sid='old',SVCNM='CHANGED'),row(sid='new'),row(sid='class',MAXCLASSNM='교육강좌'),row(sid='bad',SVCURL='invalid')]
        original=copy.deepcopy(rows)
        plan=plan_collection(rows,existing_keys=frozenset({'old'}),natural_end=True)
        self.assertEqual([v.external_key for batch in plan.batches for v in batch],['new'])
        for key,value in [('scanned',4),('target',3),('existing_skipped',1),('other_category',1),('failed',1)]:
            self.assertEqual(plan.counters[key],value)
        self.assertEqual(rows,original)
        with self.assertRaises(ValueError):plan_collection(rows*20,existing_keys=frozenset(),natural_end=False)
    def test_collection_execution_stops_before_any_credentials_run_or_write(self):
        with self.assertRaisesRegex(ValueError,'atomic_new_only'):require_new_only_collection_contract()
        from run_seoul_program_collection import main
        with redirect_stdout(io.StringIO()) as output:self.assertEqual(main([]),0)
        self.assertEqual(json.loads(output.getvalue())['network_calls'],0)
        with redirect_stdout(io.StringIO()) as output:self.assertEqual(main(['--execute']),1)
        self.assertIn('explicit_project_ref_required',output.getvalue())
    def run_worker(self, *, classified=False, bad_summary=None, bad_translation=None, unknown=False, table=False):
        c=context();c['facts']=synthetic_facts();c['observedFacts']=copy.deepcopy(c['facts']);bind_program_filters(c)
        if classified:
            c=classified_context('program','seoul_reservation')
            c['nativeConfirmedFacts']['programFacts']=synthetic_facts()
            c['filters']['application']['value'].update(start={'value':'2099-10-01','precision':'day'},end={'value':'2099-10-10','precision':'day'})
            c['facts']['deadlineOn']='2099-10-10'
        source=c['facts'] if not classified else c['nativeConfirmedFacts']['programFacts']
        summary_body=SUMMARY
        if table:
            source['description']=TABLE_DESCRIPTION
            summary_body=SUMMARY.replace('작품을 만듭니다.','작품을 만듭니다.\n\n1. 공예\n2. 완성\n')
        if classified:
            from ingest.reclassification_ai import protected_sections
            final=assemble_seoul_body(summary_body,source,reviewed=protected_sections(c))
        else:final=assemble_seoul_body(summary_body,source)
        summary=json.dumps({'content_ko':bad_summary or summary_body,'facts':dict.fromkeys(['audience','geo_age_income','amount_period_deadline','how_to_apply'],'')})
        ja=json.dumps({'title_ja':'合成案内','content_ja':bad_translation or fake_japanese(final)})
        client=streamed([response(summary),response(ja)])
        adapter=create_provider_adapter('chatgpt_plan',None,client=client,plan_session=verified_session())
        self.addCleanup(adapter.close);events=[]
        def rpc(name,args):
            events.append((name,copy.deepcopy(args)))
            if name.startswith('claim_'):return c if classified else [c]
            if name.startswith('finish_'):
                if unknown:raise TimeoutError()
                return {'candidateId':ID,'outcome':'inserted'}
            if name=='fail_seoul_program_ai':return 'failed'
            if name=='reclassified_content_ai_status':return {'status':'active'}
            raise AssertionError(name)
        if classified:
            result=process_reclassified_job(ProgramAIAdapter(rpc),source_item_id=c['sourceItemId'],revision=REV,
                classification_version=1,worker_id=c['workerId'],summarize_ko=adapter.summarize_program_ko,translate_ja=adapter.translate_ja)
        else:
            result=process_seoul_program_job(ProgramAIAdapter(rpc),source_item_id=ID,revision=REV,
                summarize_ko=adapter.summarize_program_ko,translate_ja=adapter.translate_ja)
        return result,events,client
    def test_native_and_reclassified_pro_candidate_fences_final_translation_input(self):
        for classified in [False,True]:
            with self.subTest(classified=classified):
                result,events,client=self.run_worker(classified=classified)
                self.assertEqual(result.completed,1,[n for n,_ in events])
                self.assertEqual(len(client.calls),2)
                output=events[-1][1]['p_output']
                self.assertIn(output['contentKo'],client.calls[1]['input'][0]['content'])
                self.assertIn('**모집 인원:** 20명',output['contentKo']);self.assertIn('2회차',output['contentKo'])
                self.assertNotIn('확인한 참여 안내',output['contentKo'])
                self.assertEqual(events[-1][1]['p_revision'],REV)
                self.assertIn('Contextual terminology',client.calls[1]['instructions'])
                self.assertTrue(all(c['stream'] for c in client.calls))
                self.assertNotIn('max_output_tokens',client.calls[0])
    def test_bad_summary_stops_before_translation_and_bad_translation_before_finish(self):
        for bad in [SUMMARY.replace('2099-10-25','2098-10-25'),SUMMARY.replace('10,000원','99,000원')]:
            result,events,client=self.run_worker(bad_summary=bad)
            self.assertEqual(result.completed,0);self.assertEqual(len(client.calls),1)
            self.assertFalse(any(name.startswith('finish_') for name,_ in events))
        result,events,client=self.run_worker(bad_translation='[要約]\n合成\n[主な内容]\n体験')
        self.assertEqual(result.completed,0);self.assertEqual(len(client.calls),2)
        self.assertFalse(any(name.startswith('finish_') for name,_ in events))
    def test_ambiguous_completion_never_second_write(self):
        result,events,client=self.run_worker(unknown=True)
        self.assertEqual(result.state_unknown,1);self.assertEqual(len(client.calls),2)
        self.assertEqual([name for name,_ in events],['claim_seoul_program_ai','finish_seoul_program_ai'])

    def test_two_selected_items_use_one_pair_each_with_same_fake_pro_client(self):
        c=context();c['facts']=synthetic_facts();bind_program_filters(c)
        final=assemble_seoul_body(SUMMARY,c['facts'])
        summary=json.dumps({'content_ko':SUMMARY,'facts':dict.fromkeys(['audience','geo_age_income','amount_period_deadline','how_to_apply'],'')})
        ja=json.dumps({'title_ja':'合成案内','content_ja':fake_japanese(final)})
        client=streamed([response(summary),response(ja),response(summary),response(ja)])
        provider=create_provider_adapter('chatgpt_plan',None,client=client,plan_session=verified_session())
        self.addCleanup(provider.close)
        ids=[ID,'00000000-0000-4000-8000-000000000007'];events=[]
        def rpc(name,args):
            events.append(name)
            if name=='admin_review_ai_queue':return {'hasMore':False,'items':[
                dict(sourceItemId=id,revision=REV,sourceName='seoul_reservation',status='queued',
                     currentRevision=True,leaseState='none',retryCount=0,nextRetryAt=None) for id in ids]}
            if name=='claim_seoul_program_ai':
                next=copy.deepcopy(c);next['sourceItemId']=args['p_source_item_id'];return [next]
            if name=='finish_seoul_program_ai':return {'candidateId':ID,'outcome':'inserted'}
            raise AssertionError(name)
        counts=process_seoul_queue(ProgramAIAdapter(rpc),max_jobs=2,queue_pages=1,
            summarize_ko=provider.summarize_program_ko,translate_ja=provider.translate_ja,worker_id=c['workerId'])
        self.assertEqual(counts['completed'],2);self.assertEqual(len(client.calls),4)
        self.assertEqual(events,['admin_review_ai_queue','claim_seoul_program_ai','finish_seoul_program_ai',
                                 'claim_seoul_program_ai','finish_seoul_program_ai'])
    def test_bounded_queue_skips_other_sources_retries_candidates_and_stops_unknown(self):
        item=dict(sourceItemId=ID,revision=REV,sourceName='seoul_reservation',currentRevision=True,
                  status='queued',leaseState='none',retryCount=0,nextRetryAt=None)
        entries=[{**item,'sourceName':'myseoul_program'}, {**item,'retryCount':1},item,
                 {**item,'sourceItemId':'00000000-0000-4000-8000-000000000007'}]
        events=[]
        def rpc(name,args):
            events.append(name)
            if name=='admin_review_ai_queue':return {'items':entries,'hasMore':False}
            if name=='claim_seoul_program_ai':return []
            raise AssertionError(name)
        def forbidden(*a,**kw):self.fail('provider should not be called')
        counts=process_seoul_queue(ProgramAIAdapter(rpc),max_jobs=1,queue_pages=1,
            summarize_ko=forbidden,translate_ja=forbidden,worker_id='fake')
        self.assertEqual(counts['other_source'],1);self.assertEqual(counts['state_skipped'],1)
        self.assertEqual(counts['selected'],1);self.assertEqual(counts['unprocessed'],1)
        self.assertEqual(counts['unavailable_skipped'],1)
        self.assertEqual(events,['admin_review_ai_queue','claim_seoul_program_ai'])
        def unknown(name,args):
            if name=='admin_review_ai_queue':return {'items':entries,'hasMore':False}
            raise TimeoutError()
        counts=process_seoul_queue(ProgramAIAdapter(unknown),max_jobs=2,queue_pages=1,
            summarize_ko=forbidden,translate_ja=forbidden,worker_id='fake')
        self.assertEqual(counts['state_unknown'],1);self.assertEqual(counts['unprocessed'],1)
    def test_cli_never_unbounded_or_implicit_execute(self):
        from run_seoul_program_ai import main
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--max-jobs','2','--queue-pages','1','--project-ref','a'*20],execute=lambda _:self.fail('execution forbidden')),0)
        self.assertEqual(json.loads(output.getvalue())['target_count'],2)
        for args in [[],['--max-jobs','2'],['--max-jobs','0','--queue-pages','1']]:
            with redirect_stdout(io.StringIO()),patch('sys.stderr',io.StringIO()),self.assertRaises(SystemExit):main(['--project-ref','a'*20,*args])

    def test_manual_cli_never_switches_to_paid_provider(self):
        import os
        from argparse import Namespace
        from run_seoul_program_ai import execute_target,execute_queue
        args=Namespace(project_ref='a'*20,source_item_id=ID,revision=REV,max_jobs=1,queue_pages=1)
        with patch.dict(os.environ,{'SUPABASE_URL':'https://'+'a'*20+'.supabase.co',
            'SUPABASE_SERVICE_KEY':'synthetic-not-a-credential'},clear=True),\
            patch('ingest.ai_provider.require_configured_provider',return_value=('anthropic','fake')),\
            patch('ingest.ai_provider.create_provider_adapter',side_effect=AssertionError('provider forbidden')),\
            patch('ingest.supabase_store.create_ingest_client',side_effect=AssertionError('DB forbidden')):
            for execute in (execute_target,execute_queue):
                with self.assertRaisesRegex(ValueError,'explicit_chatgpt_plan_required'):execute(args)

    def test_reclassified_unknown_topic_blocked_without_provider(self):
        c=classified_context('program','seoul_reservation')
        c['filters']['topic']={'status':'unknown','value':None}
        def forbidden(*a,**kw):self.fail('provider forbidden')
        calls=[]
        def rpc(name,args):calls.append(name);return c
        result=process_reclassified_job(ProgramAIAdapter(rpc),source_item_id=ID,revision=REV,
            classification_version=1,worker_id=c['workerId'],summarize_ko=forbidden,translate_ja=forbidden)
        self.assertEqual(result.state_unknown,1);self.assertEqual(calls,['claim_reclassified_content_ai'])


if __name__=='__main__':
    import sys
    if '--fixture' in sys.argv:
        with patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')):
            test=SeoulWorkflowTests();result,events,client=test.run_worker(table=True)
            test.doCleanups()
            assert result.completed==1
            print(json.dumps(dict(syntheticOnly=True,fakeGenerationStages=2,source=TABLE_DESCRIPTION,
                output=events[-1][1]['p_output']),ensure_ascii=False))
    else:unittest.main()
