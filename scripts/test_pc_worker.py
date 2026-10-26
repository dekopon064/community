"""Synthetic control/HTTP/Auth/Pro/RPC only. External connections are forbidden."""
import base64
import copy
import hashlib
import hmac
import http.client
import json
import socket
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from http.server import ThreadingHTTPServer

from ingest.pc_worker_bridge import PcWorkerControl,ControlError,handler,SCHEMA
from ingest.pc_worker_existing import ExistingWorkers
from ingest.pc_worker_sources import SOURCES,CATALOG

KEY='synthetic-only-credential-aaaaaaaaaaaaaaaaaaaaaaaa'
ACTOR='00000000-0000-4000-8000-000000000001'
OTHER='00000000-0000-4000-8000-000000000002'
ORIGIN='http://127.0.0.1:3295'
PROJECT='a'*20
COMMAND=dict(source='seoul_reservation',kind='collect',limit=1)


def ticket(control,operation='connect',*,actor=ACTOR,request_id=None,cmd=None,change=None,key=KEY):
    p=dict(schema=SCHEMA,operation=operation,command=cmd if operation=='run' else None,
        requestId=request_id or str(uuid4()),instance=control.instance,challenge=control.challenge,
        project=PROJECT,actor=actor,origin=ORIGIN,catalog=CATALOG,iat=1000,exp=1060)
    p.update(change or {})
    body=base64.urlsafe_b64encode(json.dumps(p,separators=(',',':')).encode()).rstrip(b'=')
    derived=hmac.digest(key.encode(),b'machimoa.pc-worker.capability.v1','sha256')
    mac=base64.urlsafe_b64encode(hmac.digest(derived,body,'sha256')).rstrip(b'=')
    return 'pcw1.'+body.decode()+'.'+mac.decode()


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.guard=patch.object(socket.socket,'connect',side_effect=AssertionError('external network forbidden'))
        self.guard.start();self.addCleanup(self.guard.stop)
        self.calls=[];self.key_reads=[];self.now=1001;self.release=threading.Event()
        def execute(cmd):
            self.calls.append(cmd);self.release.wait(2)
            return dict(state='completed',code='completed',counts={'new_saved':1})
        self.control=PcWorkerControl(project=PROJECT,origin=ORIGIN,key=lambda:self.read_key(),execute=execute,clock=lambda:self.now)
        self.addCleanup(self.cleanup)

    def cleanup(self):self.release.set();self.control.wait()
    def read_key(self):self.key_reads.append(1);return KEY
    def connect(self,actor=ACTOR,request_id=None):return self.control.connect(ticket(self.control,actor=actor,request_id=request_id))['token']

    def test_start_hello_and_connection_never_execute_or_read_auth_store(self):
        self.control.hello();self.assertEqual(self.key_reads,[])
        token=self.connect();self.assertEqual(self.control.status(token),{'busy':False,'run':None});self.assertEqual(self.calls,[])

    def test_invalid_and_expired_capabilities_fail_closed(self):
        for change in [{'exp':999},{'iat':1007,'exp':1067},{'project':'b'*20},{'instance':str(uuid4())},
            {'challenge':str(uuid4())},{'origin':'https://attacker.invalid'},{'actor':'invalid'},{'catalog':'older_catalog'},{'extra':'forbidden'}]:
            with self.subTest(change=change),self.assertRaises(ControlError):self.control.connect(ticket(self.control,change=change))
        with self.assertRaises(ControlError):self.control.connect(ticket(self.control,key='wrong-secret-aaaaaaaaaaaaaaaaaaaaaaaa'))
        self.assertEqual(self.calls,[])

    def test_unknown_command_and_additional_arguments_rejected(self):
        token=self.connect()
        for cmd in [{**COMMAND,'source':'unknown'},{**COMMAND,'kind':'publish'},{**COMMAND,'limit':2},
            {**COMMAND,'limit':True},{**COMMAND,'shell':'command'},{**COMMAND,'kind':'ai','limit':26},{**COMMAND,'kind':'ai'}]:
            with self.subTest(command=cmd),self.assertRaises(ControlError):self.control.submit(token,ticket(self.control,'run',cmd=cmd))
        self.assertEqual(self.calls,[])

    def test_one_active_job_and_same_request_deduplication(self):
        token=self.connect();identity=str(uuid4());signed=ticket(self.control,'run',request_id=identity,cmd=COMMAND)
        first=self.control.submit(token,signed);self.assertEqual(first['run']['state'],'running')
        self.control.submit(token,signed)
        with self.assertRaises(ControlError):self.control.submit(token,ticket(self.control,'run',cmd=COMMAND))
        self.release.set();self.control.wait();self.control.submit(token,signed)
        self.assertEqual(self.calls,[COMMAND]);self.assertEqual(self.control.status(token,identity)['run']['state'],'completed')
        with self.assertRaises(ControlError):self.control.submit(token,ticket(self.control,'run',request_id=identity,cmd={**COMMAND,'source':'myseoul_program'}))

    def test_actor_isolation_including_duplicate_connection_request(self):
        identity=str(uuid4());one=self.connect(request_id=identity);two=self.connect(OTHER,identity)
        self.assertNotEqual(one,two)
        signed=ticket(self.control,'run',cmd=COMMAND)
        with self.assertRaises(ControlError):self.control.submit(two,signed)
        result=self.control.submit(one,signed);self.assertIsNone(self.control.status(two)['run'])
        self.assertIsNone(self.control.status(two,result['run']['requestId'])['run'])

    def test_restart_and_connection_expiry_do_not_replay_or_mark_complete(self):
        token=self.connect();signed=ticket(self.control,'run',cmd=COMMAND)
        other=PcWorkerControl(project=PROJECT,origin=ORIGIN,key=lambda:KEY,execute=self.calls.append,clock=lambda:1001)
        with self.assertRaises(ControlError):other.connect(ticket(self.control))
        self.now=3000
        with self.assertRaises(ControlError):self.control.status(token)
        with self.assertRaises(ControlError):self.control.submit(token,signed)
        self.assertEqual(self.calls,[])

    def test_unknown_executor_result_is_not_success_and_has_no_secret(self):
        self.control.execute=lambda cmd:(_ for _ in ()).throw(RuntimeError('secret-token-do-not-echo'))
        token=self.connect();self.control.submit(token,ticket(self.control,'run',cmd=COMMAND));self.control.wait()
        status=self.control.status(token);self.assertEqual(status['run']['state'],'unknown');self.assertNotIn('secret',json.dumps(status))
        self.assertTrue(status['busy'])
        with self.assertRaises(ControlError):self.control.submit(token,ticket(self.control,'run',cmd=COMMAND))

    def test_launcher_only_prepares_control_without_credentials_or_work(self):
        import run_pc_worker
        captured=[]
        with patch('sys.argv',['run_pc_worker.py','--project-ref',PROJECT,'--app-origin',ORIGIN]),\
             patch('ingest.pc_worker_bridge.serve',side_effect=captured.append),\
             patch('run_pc_worker.os.environ',{}):
            run_pc_worker.main()
        self.assertEqual(len(captured),1);self.assertEqual(captured[0].hello()['project'],PROJECT)
        self.assertEqual(captured[0].runs,{})

    def test_exact_history_read_survives_a_newer_job(self):
        token=self.connect();self.release.set();first=str(uuid4())
        self.control.submit(token,ticket(self.control,'run',request_id=first,cmd=COMMAND));self.control.wait()
        self.control.submit(token,ticket(self.control,'run',cmd=COMMAND));self.control.wait()
        self.assertEqual(self.control.status(token,first)['run']['requestId'],first)


class ExistingWorkerTests(unittest.TestCase):
    def setUp(self):
        self.guard=patch.object(socket.socket,'connect',side_effect=AssertionError('real endpoint forbidden'))
        self.guard.start();self.addCleanup(self.guard.stop)

    def test_collection_dispatch_never_authenticates_or_calls_ai(self):
        calls=[]
        worker=ExistingWorkers(PROJECT,collect=lambda source:calls.append(source) or {'status':'complete','new_saved':2},ai_context=lambda:(_ for _ in ()).throw(AssertionError('AI forbidden')))
        for source in ['seoul_reservation','myseoul_program']:
            result=worker({**COMMAND,'source':source});self.assertEqual(result['state'],'completed')
        self.assertEqual(calls,['seoul_reservation','myseoul_program'])

    def test_all_collects_catalog_order_once_with_per_source_results(self):
        calls=[]
        worker=ExistingWorkers(PROJECT,collect=lambda source:calls.append(source) or {'status':'complete','new_saved':2},ai_context=lambda:(_ for _ in ()).throw(AssertionError('AI forbidden')))
        control=PcWorkerControl(project=PROJECT,origin=ORIGIN,key=lambda:KEY,execute=worker,clock=lambda:1001)
        token=control.connect(ticket(control))['token'];signed=ticket(control,'run',cmd={**COMMAND,'source':'all'})
        control.submit(token,signed);control.wait();control.submit(token,signed)
        result=control.status(token)['run']
        self.assertEqual(calls,list(SOURCES));self.assertEqual(result['counts']['completed_sources'],len(SOURCES))
        self.assertEqual([r['source'] for r in result['sourceResults']],list(SOURCES));self.assertEqual(result['state'],'completed')

    def test_all_collection_stops_on_unknown_failed_or_incomplete_without_repeating(self):
        for status,state in [('state_unknown','unknown'),('failed','failed'),('incomplete','stopped')]:
            calls=[]
            worker=ExistingWorkers(PROJECT,collect=lambda source:calls.append(source) or {'status':status})
            result=worker({**COMMAND,'source':'all'})
            self.assertEqual(result['state'],state);self.assertEqual(calls,[next(iter(SOURCES))]);self.assertEqual(result['counts']['unprocessed_sources'],1)
        calls=[]
        def collect(source):
            calls.append(source)
            if len(calls)==2:raise RuntimeError('private response do not echo')
            return {'status':'complete','new_saved':2}
        result=ExistingWorkers(PROJECT,collect=collect)({**COMMAND,'source':'all'})
        self.assertEqual(result['state'],'unknown');self.assertEqual(result['counts']['new_saved'],2)
        self.assertEqual(result['sourceResults'][0]['state'],'completed');self.assertNotIn('private',json.dumps(result))

    def test_unconnected_catalog_handler_fails_closed_before_any_work(self):
        calls=[]
        with patch.dict(SOURCES,{'future_source':dict(id='future_source',label='합성 수집원',collector='unconnected',ai='unconnected',collectionHint='합성')}):
            result=ExistingWorkers(PROJECT,collect=calls.append)({**COMMAND,'source':'all'})
        self.assertEqual(result['code'],'contract_unavailable');self.assertEqual(calls,[])

    def test_seoul_uses_shared_batch_existing_no_retry_job_and_closes_provider(self):
        from ingest.program_ai import ProgramAIAdapter
        target=dict(sourceName='seoul_reservation',status='queued',currentRevision=True,leaseState='none',retryCount=0,nextRetryAt=None,sourceItemId=str(uuid4()),revision='a'*64)
        provider=SimpleNamespace(summarize_program_ko=object(),translate_ja=object());closed=[]
        adapter=ProgramAIAdapter(lambda name,args:{'hasMore':False,'items':[target]})
        worker=ExistingWorkers(PROJECT,ai_context=lambda:(adapter,provider,lambda:closed.append(1)))
        row=SimpleNamespace(completed=1,failed=0,retried=0,state_unknown=0,status='processed')
        with patch('ingest.program_ai.process_seoul_program_job',return_value=row) as batch:
            result=worker(dict(source='all',kind='ai',limit=5))
        self.assertEqual(result['state'],'completed');self.assertEqual(closed,[1]);self.assertEqual(batch.call_args.args,(adapter,))
        self.assertEqual(batch.call_args.kwargs['no_retry'],True);self.assertEqual(batch.call_args.kwargs['source_item_id'],target['sourceItemId'])

    def test_exact_collection_entrypoints_and_partial_myseoul_counts(self):
        worker=ExistingWorkers(PROJECT)
        def seoul(args):
            self.assertEqual(args,['--project-ref',PROJECT,'--execute']);print(json.dumps({'status':'complete','new_saved':2,'existing_skipped':3}));return 0
        with patch('run_seoul_program_collection.main',side_effect=seoul):
            self.assertEqual(worker(COMMAND)['counts']['new_saved'],2)
        with patch('run_myseoul_collect.execute_collection',return_value={'status':'incomplete','requests':12,'summary':{'new':7,'known':2,'processed':5,'pending_remaining':2}}) as collect:
            result=worker({**COMMAND,'source':'myseoul_program'})
            self.assertEqual(collect.call_args.args[0].project_ref,PROJECT)
            self.assertEqual(result['state'],'stopped');self.assertEqual(result['counts']['new'],7);self.assertEqual(result['counts']['processed'],5)

    def test_auth_failure_precedes_queue_claim_and_never_opens_login(self):
        from ingest.chatgpt_plan_protocol import ProbeError
        worker=ExistingWorkers(PROJECT,ai_context=lambda:(_ for _ in ()).throw(ProbeError('chatgpt_plan_reauthentication_required')))
        with patch('ingest.seoul_workflow.process_seoul_queue') as batch:
            result=worker(dict(source='all',kind='ai',limit=1))
        self.assertEqual(result['state'],'auth_required');batch.assert_not_called()

    def test_common_auth_factory_is_reuse_only_before_db_and_uses_no_api_fallback(self):
        calls=[];provider=object();session=object()
        class Manager:
            def acquire(self,**kwargs):calls.append(('acquire',kwargs));return session
        with patch('ingest.ai_provider.require_ai_provider',return_value='chatgpt_plan'),\
             patch('ingest.chatgpt_plan_sessions.PlanSessionManager',return_value=Manager()),\
             patch('ingest.ai_provider.create_provider_adapter',side_effect=lambda *a,**kw:calls.append(('provider',kw)) or provider),\
             patch('ingest.ai_provider.close_provider_adapter'),\
             patch('ingest.supabase_store.create_ingest_client',side_effect=lambda *a:calls.append(('db',None)) or object()),\
             patch('ingest.pc_worker_existing.os.environ',{'SUPABASE_URL':f'https://{PROJECT}.supabase.co','SUPABASE_SERVICE_KEY':KEY}):
            context=ExistingWorkers(PROJECT)._ai_context();context[2]()
        self.assertEqual(calls[0],('acquire',{'allow_login':False}));self.assertEqual(calls[1],('provider',{'plan_session':session}));self.assertEqual(calls[2][0],'db')

    def test_other_provider_is_rejected_before_any_key_auth_or_db_access(self):
        with patch('ingest.ai_provider.require_ai_provider',return_value='openai'),\
             patch('ingest.ai_provider.require_provider_key',side_effect=AssertionError('API key read forbidden')) as key,\
             patch('ingest.chatgpt_plan_auth.authenticate_worker',side_effect=AssertionError('real auth forbidden')) as auth,\
             patch('ingest.supabase_store.create_ingest_client',side_effect=AssertionError('DB forbidden')) as db:
            result=ExistingWorkers(PROJECT)(dict(source='all',kind='ai',limit=1))
        self.assertEqual(result['code'],'contract_unavailable');key.assert_not_called();auth.assert_not_called();db.assert_not_called()

    def test_myseoul_actual_pro_adapter_and_fenced_rpc_candidate_without_real_ai(self):
        from ingest.program_ai import ProgramAIAdapter
        from ingest.ai_chatgpt_plan import ChatGPTPlanAdapter
        from test_ingest_ai_chatgpt_plan import verified_session,streamed
        from test_myseoul_gpt_pipeline import native_packet,native_client
        c=native_packet();before=copy.deepcopy(c);client=streamed(native_client(c).responses.results);calls=[];claimed={}
        def rpc(name,args):
            calls.append((name,args))
            if name=='admin_review_ai_queue':return {'hasMore':False,'items':[dict(sourceName='myseoul_program',status='queued',currentRevision=True,leaseState='none',retryCount=0,nextRetryAt=None,sourceItemId=c['sourceItemId'],revision=c['revision'])]}
            if name=='claim_myseoul_program_ai':claimed.update(copy.deepcopy(c));claimed['workerId']=args['p_worker_id'];return [claimed]
            if name=='admin_myseoul_program_detail':return dict(id=c['sourceItemId'],revision=c['revision'],schema=c['schema'],profile=c['profile'],factsVersion=c['factsVersion'],status='resolved',aiStatus='claimed',source={'name':c['source'],'title':c['title'],'url':c['facts']['official_url']},facts=c['facts'],observedFacts=c['observedFacts'],result={'scope':'included','quality':'sufficient','public_category':'program','application':'open','decision':'in_scope','reasons':[]})
            if name=='finish_myseoul_program_ai':
                self.assertEqual(args['p_worker_id'],claimed['workerId']);self.assertEqual(args['p_facts_version'],c['factsVersion']);return {'outcome':'inserted','candidateId':str(uuid4())}
            raise AssertionError(name)
        provider=ChatGPTPlanAdapter(session=verified_session(),client=client)
        worker=ExistingWorkers(PROJECT,ai_context=lambda:(ProgramAIAdapter(rpc),provider,provider.close))
        result=worker(dict(source='all',kind='ai',limit=1))
        self.assertEqual(result['state'],'completed');self.assertEqual(result['counts']['completed'],1)
        self.assertEqual(len(client.calls),2);self.assertEqual(c,before)
        self.assertEqual(sum(name.startswith('finish_') for name,_ in calls),1)
        self.assertFalse(any('publish' in name or 'approve' in name for name,_ in calls))

    def test_mixed_queue_uses_one_shared_pro_context_and_total_item_limit(self):
        from ingest.program_ai import ProgramAIAdapter
        from ingest.ai_chatgpt_plan import ChatGPTPlanAdapter
        from test_ingest_ai_chatgpt_plan import verified_session,streamed
        from test_ingest_ai_openai import response
        from test_seoul_fact_roles import replay_context,confirmed_case,fake_translation
        from ingest.seoul_content import assemble_seoul_body
        from test_myseoul_gpt_pipeline import native_packet,native_client
        for limit in (1,2,'all'):
            expected=2 if limit=='all' else limit
            _,seoul=replay_context();seoul['failurePolicy']={'policy':'no_retry','attempt':'a'*64}
            my=native_packet();my['sourceItemId']=str(uuid4());my['jobId']=str(uuid4())
            contexts=[seoul,my];originals=copy.deepcopy(contexts);summary=confirmed_case()['summary']
            ko=assemble_seoul_body(summary['content_ko'],seoul['facts'])
            replies=[response(json.dumps(summary,ensure_ascii=False)),response(json.dumps({'title_ja':'合成の解説','content_ja':fake_translation(ko)},ensure_ascii=False)),*native_client(my).responses.results]
            client=streamed(replies);calls=[];claimed={};closed=[]
            def rpc(name,args):
                calls.append(name)
                if name=='admin_review_ai_queue':return {'hasMore':False,'items':[dict(jobId=c['jobId'],sourceName=source,status='queued',currentRevision=True,leaseState='none',retryCount=0,nextRetryAt=None,sourceItemId=c['sourceItemId'],revision=c['revision']) for source,c in zip(SOURCES,contexts)]}
                if name.startswith('claim_'):
                    c=seoul if 'seoul_program' in name and 'myseoul' not in name else my
                    current=copy.deepcopy(c);current['workerId']=args['p_worker_id']
                    for key in ('filterContext','activityConfirmation'):
                        if isinstance(current.get(key),dict):current[key]['workerId']=args['p_worker_id']
                    claimed[current['jobId']]=current;return [current]
                if name=='admin_myseoul_program_detail':return dict(id=my['sourceItemId'],revision=my['revision'],schema=my['schema'],profile=my['profile'],factsVersion=my['factsVersion'],status='resolved',aiStatus='claimed',source={'name':my['source'],'title':my['title'],'url':my['facts']['official_url']},facts=my['facts'],observedFacts=my['observedFacts'],result={'scope':'included','quality':'sufficient','public_category':'program','application':'open','decision':'in_scope','reasons':[]})
                if name.startswith('finish_'):
                    c=claimed[args['p_job_id']];self.assertEqual(args['p_worker_id'],c['workerId']);self.assertEqual(args['p_facts_version'],c['factsVersion']);self.assertEqual(args['p_revision'],c['revision'])
                    return {'outcome':'inserted','candidateId':c['sourceItemId']}
                raise AssertionError(name)
            provider=ChatGPTPlanAdapter(session=verified_session(),client=client)
            def close():closed.append(1);provider.close()
            worker=ExistingWorkers(PROJECT,ai_context=lambda:(ProgramAIAdapter(rpc),provider,close))
            result=worker(dict(source='all',kind='ai',limit=limit))
            self.assertEqual(result['state'],'completed',msg=(limit,calls,len(client.calls),result));self.assertEqual(result['counts']['completed'],expected)
            self.assertEqual(len(client.calls),expected*2);self.assertEqual(calls.count('admin_review_ai_queue'),2 if limit=='all' else 1)
            self.assertEqual(sum(n.startswith('finish_') for n in calls),expected);self.assertEqual(closed,[1]);self.assertEqual(contexts,originals)

    def test_mixed_failure_policy_keeps_terminal_continue_and_global_stop(self):
        from ingest.program_ai import ProgramAIAdapter
        rows=[dict(sourceName=source,status='queued',currentRevision=True,leaseState='none',retryCount=0,nextRetryAt=None,sourceItemId=str(uuid4()),revision='a'*64) for source in SOURCES]
        def result(**change):return SimpleNamespace(**dict(completed=0,failed=0,retried=0,state_unknown=0,status='processed',failure_scope=None)|change)
        class Provider:
            def __init__(self):self.released=0
            def summarize_program_ko(self,*a):raise AssertionError('fake job does not call AI')
            summarize_myseoul_ko=summarize_program_ko
            def translate_ja(self,*a):raise AssertionError('fake job does not call AI')
            def release_terminated_attempt(self):self.released+=1
        cases=[(result(failed=1,failure_scope='item'),result(completed=1),2,'partial'),
               (result(failed=1,failure_scope='common'),result(completed=1),1,'stopped'),
               (result(state_unknown=1,status='ai_state_unknown'),result(completed=1),1,'unknown')]
        for seoul,my,expected,state in cases:
            calls=[];provider=Provider();adapter=ProgramAIAdapter(lambda name,args:{'items':rows,'hasMore':False})
            with patch('ingest.program_ai.process_seoul_program_job',side_effect=lambda *a,**k:calls.append('seoul') or seoul),\
                 patch('ingest.myseoul_ai.process_myseoul_job',side_effect=lambda *a,**k:calls.append('my') or my):
                out=ExistingWorkers(PROJECT,ai_context=lambda:(adapter,provider,lambda:None))(dict(source='all',kind='ai',limit=2))
            self.assertEqual(out['state'],state);self.assertEqual(len(calls),expected);self.assertEqual(provider.released,int(expected==2))
        # My Seoul+'s existing retry registration stops before another source/job.
        adapter=ProgramAIAdapter(lambda name,args:{'items':list(reversed(rows)),'hasMore':False});provider=Provider()
        with patch('ingest.myseoul_ai.process_myseoul_job',return_value=result(retried=1)),\
             patch('ingest.program_ai.process_seoul_program_job',side_effect=AssertionError('must stop')):
            out=ExistingWorkers(PROJECT,ai_context=lambda:(adapter,provider,lambda:None))(dict(source='all',kind='ai',limit=2))
        self.assertEqual(out['code'],'retry_registered');self.assertEqual(out['counts']['unprocessed'],1)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.control=PcWorkerControl(project=PROJECT,origin=ORIGIN,key=lambda:KEY,
            execute=lambda cmd:dict(state='completed',code='completed',counts={}),clock=lambda:1001)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.control));self.port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        original=socket.socket.connect
        def loopback(sock,address):
            if address[0]!='127.0.0.1':raise AssertionError('external network forbidden')
            return original(sock,address)
        self.guard=patch.object(socket.socket,'connect',loopback);self.guard.start();self.addCleanup(self.guard.stop)
        self.addCleanup(self.cleanup)

    def cleanup(self):self.server.shutdown();self.server.server_close();self.control.wait();self.thread.join()
    def request(self,path,method='GET',body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        conn.request(method,path,body,{'Origin':ORIGIN,**(headers or {})});res=conn.getresponse();data=res.read();out=(res.status,dict(res.getheaders()),json.loads(data));conn.close();return out

    def test_host_origin_cors_and_read_auth(self):
        status,headers,_=self.request('/hello');self.assertEqual(status,200);self.assertEqual(headers['Access-Control-Allow-Origin'],ORIGIN)
        self.assertNotIn('*',headers['Access-Control-Allow-Origin']);self.assertEqual(headers['Cache-Control'],'no-store')
        for headers in [{'Origin':'https://attacker.invalid'},{'Host':'attacker.invalid'}]:
            status,out,_=self.request('/hello',headers=headers);self.assertEqual(status,403);self.assertNotIn('Access-Control-Allow-Origin',out)
        self.assertEqual(self.request('/status')[0],401)

    def test_preflight_and_unsafe_bodies(self):
        status,headers,_=self.request('/run','OPTIONS',headers={'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization, content-type'})
        self.assertEqual(status,200);self.assertEqual(headers['Access-Control-Allow-Private-Network'],'true')
        self.assertEqual(self.request('/run','POST','{}',{'Content-Type':'text/plain'})[0],422)
        self.assertEqual(self.request('/run','POST','x'*13000,{'Content-Type':'application/json'})[0],422)
        self.assertEqual(self.request('/hello?url=https://attacker.invalid')[0],404)


if __name__=='__main__':unittest.main()
