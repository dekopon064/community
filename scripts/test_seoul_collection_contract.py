"""Bounded collector and explicit confirmation input; synthetic transports only."""
import copy,json,socket,unittest
from types import SimpleNamespace
from unittest.mock import patch
from ingest.program_db import ProgramNewOnlyObservationAdapter
from ingest.seoul_workflow import process_seoul_collection
from ingest.rpc_errors import RpcAmbiguous,RpcFailure
from test_seoul_reservation import row
from test_program_ai import context,ProgramAITests

CAP={'contract':'seoul-new-only-v1','maxBatch':40,'category':'문화체험'}
class SeoulCollectionContractTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden'))
        guard.start();self.addCleanup(guard.stop)
    def flow(self,rows=None,fail=None,natural=False):
        events=[]
        class Store:
            def start_ingest_run(self,*a,**kw):events.append('start');return SimpleNamespace(run_id='synthetic-run',skipped=False)
            def finish_ingest_run(self,*a,**kw):events.append(('finish',kw));return SimpleNamespace(status=kw['status'])
        def rpc(name,args):
            events.append((name,copy.deepcopy(args)))
            if name=='seoul_collection_contract':return CAP
            if name=='observe_seoul_program_new_only':
                call=sum(isinstance(v,tuple) and v[0]==name for v in events)
                if fail and call==2:raise fail
                return [dict(inputIndex=i,externalKey=v['external_key'],id='30000000-0000-4000-8000-000000000001',
                    revision=v['revision_hash'],outcome='existing_skipped' if v['external_key'].endswith('_1') else 'new_saved',
                    reviewWaiting=True,aiWaiting=False) for i,v in enumerate(args['p_items'])]
            self.fail(name)
        connector=SimpleNamespace(page_size=50,max_pages=1,http=SimpleNamespace(request_count=1))
        connector.fetch_batch=lambda cp:SimpleNamespace(items=rows or [row(sid=f'synthetic_{n}') for n in range(50)],natural_end=natural,progress={})
        result=process_seoul_collection(Store(),ProgramNewOnlyObservationAdapter(rpc),connector)
        return result,events
    def test_fifty_split_authoritative_counts_and_no_ai(self):
        result,events=self.flow()
        self.assertEqual(result['new_saved'],49);self.assertEqual(result['existing_skipped'],1)
        self.assertEqual(result['review_waiting'],49);self.assertEqual(result['ai_waiting'],0)
        writes=[e[1] for e in events if isinstance(e,tuple) and e[0]=='observe_seoul_program_new_only']
        self.assertEqual([len(a['p_items']) for a in writes],[40,10])
        self.assertEqual([a['p_next_checkpoint']['targetOffset'] for a in writes],[40,50])
        self.assertEqual(result['status'],'incomplete');self.assertEqual(result['ai_calls'],0)
        self.assertEqual(result['unprocessed'],0)
    def test_unknown_second_batch_never_finishes_or_retries(self):
        result,events=self.flow(fail=RpcAmbiguous())
        self.assertEqual(result['status'],'state_unknown');self.assertTrue(result['state_unknown'])
        self.assertEqual(result['unprocessed'],10);self.assertEqual(result['new_saved'],39)
        self.assertFalse(any(isinstance(e,tuple) and e[0]=='finish' for e in events))
        self.assertEqual(sum(isinstance(e,tuple) and e[0]=='observe_seoul_program_new_only' for e in events),2)
    def test_known_failure_preserves_acknowledged_batch(self):
        result,events=self.flow(fail=RpcFailure('rpc_failure'))
        self.assertEqual(result['status'],'failed');self.assertEqual(result['unprocessed'],10)
        self.assertEqual(events[-1][1]['batches_ok'],1)
    def test_other_category_only_empty_ack_without_ai(self):
        result,events=self.flow(rows=[row(MAXCLASSNM='교육강좌')],natural=True)
        self.assertEqual(result['new_saved'],0);self.assertEqual(result['target'],0)
        self.assertEqual(result['other_category'],1);self.assertEqual(result['status'],'complete')
        self.assertEqual(next(e[1]['p_items'] for e in events if isinstance(e,tuple) and e[0]=='observe_seoul_program_new_only'),[])
    def test_external_detail_link_is_rejected_without_discarding_other_rows(self):
        from ingest.connectors.seoul_reservation import SeoulReservationConnector
        from ingest.http_client import HttpClient
        from test_seoul_reservation import TEST_KEY,Response,envelope
        rows=[row(sid=f'synthetic_{i}') for i in range(50)]
        rows[13]=row(sid='XML-synthetic-3',SVCURL='https://example.test/tour/touristSiteView.do?tourist_cd=SYNTHETIC')
        calls=[]
        def transport(*_a,**_kw):calls.append(1);return Response(envelope(rows,100))
        c=SeoulReservationConnector(HttpClient(budget=1,max_attempts=1,transport=transport),api_key_provider=lambda:TEST_KEY)
        page=c.fetch_batch(None)
        self.assertEqual(len(calls),1);self.assertEqual(len(page.items),50)
        result,events=self.flow(rows=list(page.items))
        self.assertEqual(result['status'],'incomplete');self.assertEqual(result['reason'],'invalid_items')
        self.assertEqual(result['failed'],1);self.assertEqual(result['new_saved'],48)
        self.assertEqual(result['existing_skipped'],1);self.assertEqual(result['unprocessed'],0)
        self.assertEqual(result['item_errors'],[dict(row_index=13,stage='row_normalization',error_code='seoul_link_invalid')])
        writes=[e[1]['p_items'] for e in events if isinstance(e,tuple) and e[0]=='observe_seoul_program_new_only']
        self.assertEqual([len(items) for items in writes],[40,9])
        self.assertFalse(any(i['external_key']=='XML-synthetic-3' for items in writes for i in items))
    def test_other_category_external_link_never_enters_observation(self):
        result,events=self.flow(rows=[row(MAXCLASSNM='교육강좌',SVCURL='https://example.test/'),row(sid='valid_culture')],natural=True)
        self.assertEqual(result['other_category'],1);self.assertEqual(result['failed'],0)
        items=next(e[1]['p_items'] for e in events if isinstance(e,tuple) and e[0]=='observe_seoul_program_new_only')
        self.assertEqual([i['external_key'] for i in items],['valid_culture'])
    def test_missing_server_capability_blocks_before_run_and_http(self):
        adapter=ProgramNewOnlyObservationAdapter(lambda *_:{'contract':'old'})
        forbidden=SimpleNamespace(start_ingest_run=lambda *_a,**_k:self.fail('write forbidden'))
        connector=SimpleNamespace(page_size=50,max_pages=1,fetch_batch=lambda *_:self.fail('HTTP forbidden'))
        with self.assertRaisesRegex(ValueError,'atomic_new_only'):process_seoul_collection(forbidden,adapter,connector)
    def test_malformed_ack_is_unknown_not_success(self):
        adapter=ProgramNewOnlyObservationAdapter(lambda *_:[{'outcome':'changed'}])
        from ingest.connectors.seoul_reservation import normalize_seoul_item
        with self.assertRaises(RpcAmbiguous):adapter.observe('run',[normalize_seoul_item(row())],None)
    def test_confirmed_server_context_preserves_empty_evidence_and_candidate(self):
        c=context();c['facts']['activity_evidence']=[]
        c['activityConfirmation']={k:c[k] for k in ('sourceItemId','revision','factsVersion','jobId','claimedAt','leaseUntil','workerId')}
        c['activityConfirmation'].update(confirmed=True,filterVersion=c['filterContext']['filterVersion'])
        original=copy.deepcopy(c['facts'])
        test=ProgramAITests();result,events,_=test.run_job(c)
        self.assertEqual(result.completed,1);self.assertEqual(c['facts'],original)
        self.assertEqual([n for n,_ in events],['claim_seoul_program_ai','finish_seoul_program_ai'])
        for key,value in [('revision','f'*64),('factsVersion',999),('filterVersion',999),('confirmed',False),('jobId','30000000-0000-4000-8000-000000000003')]:
            wrong=copy.deepcopy(c);wrong['activityConfirmation'][key]=value
            result,events,_=test.run_job(wrong)
            self.assertEqual(result.state_unknown,1,key);self.assertEqual(len(events),1,key)
    def test_no_confirmation_or_real_conflict_keeps_ai_blocked(self):
        c=context();c['facts']['activity_evidence']=[]
        result,events,_=ProgramAITests().run_job(c)
        self.assertEqual(result.state_unknown,1);self.assertEqual(len(events),1)
        c['activityConfirmation']={k:c[k] for k in ('sourceItemId','revision','factsVersion','jobId','claimedAt','leaseUntil','workerId')}
        c['activityConfirmation'].update(confirmed=True,filterVersion=c['filterContext']['filterVersion'])
        c['facts']['periods']['SVCOPNENDDT']['value']='2019-01-01'
        result,events,_=ProgramAITests().run_job(c)
        self.assertEqual(result.state_unknown,1);self.assertEqual(len(events),1)

if __name__=='__main__':unittest.main()
