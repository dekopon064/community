"""Verified synthetic OAuth -> existing workers -> fake RPC. No DB/network."""
import copy
import io
import json
import socket
import time
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode, parse_qs, urlsplit

from ingest.ai_chatgpt_plan import ChatGPTPlanAdapter, plan_request
from ingest.ai_claude import (SUMMARY_SYSTEM, MYSEOUL_SUMMARY_SYSTEM, PROGRAM_SUMMARY_SYSTEM,
    SUMMARY_MAX_TOKENS, TRANSLATION_MAX_TOKENS)
from ingest.ai_errors import AiJobError
from ingest.ai_openai import GPT_MODEL
from ingest.ai_provider import (PROVIDER_CHATGPT_PLAN, ProviderError, require_configured_provider,
    create_provider_adapter, provider_validation_limits)
from ingest.chatgpt_plan_auth import PlanSession, authenticate_worker
from ingest.chatgpt_plan_protocol import ProbeError, AuthorizationAttempt, RESOURCE, TOKEN, JWKS, DISCOVERY
from ingest.program_ai import ProgramAIAdapter
from ingest.reclassification_ai import process_reclassified_job, protected_information
from ingest.rpc_errors import RpcAmbiguous
import test_chatgpt_plan_probe as pro_fixture
from test_chatgpt_plan_probe import FakeClient
from test_ingest_ai_openai import SUMMARY_JSON, TRANSLATION_JSON, response
import test_myseoul_gpt_pipeline as gpt_fixture
from test_myseoul_gpt_pipeline import native_packet, native_client, summary_response
from test_reclassification_ai import context as classified_context, ID, REV
import test_ingest_ai_worker as worker_fixture
from ingest.ai_worker import process_ai_jobs


def grant_fixture():
    grant, keys, encode, identity, access = pro_fixture.ProProbeTests().grant()
    expiry = int(time.time()) + 3600
    grant['id_token'] = encode({**identity, 'exp':expiry})
    grant['access_token'] = encode({**access, 'exp':expiry})
    return grant, keys


def verified_session():
    grant, keys = grant_fixture()
    return PlanSession.from_grant(grant, client_id='oaiapp_synthetic', nonce='nonce',
        keys=keys, catalog={'models':[{'slug':GPT_MODEL,'visibility':'list'}]})


def streamed(responses):
    events = []
    for completed in responses:
        done = {'type':'response.output_item.done', 'output_index':1, 'item':completed['output'][1]}
        events.append([done, {'type':'response.completed','response':{**completed,'output':[]}}])
    return FakeClient(events)


class PlanWorkerTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def adapter(self, client=None):
        session = verified_session()
        client = client or streamed([response(SUMMARY_JSON), response(TRANSLATION_JSON)])
        adapter = create_provider_adapter('chatgpt_plan', None, client=client, plan_session=session)
        self.addCleanup(adapter.close)
        return adapter, client, session

    def test_explicit_plan_selection_never_reads_api_keys_or_authenticates(self):
        class Env(dict):
            def get(self, key, *args):
                if key in {'OPENAI_API_KEY','ANTHROPIC_API_KEY','ACCESS_TOKEN'}:
                    raise AssertionError('credential access')
                return super().get(key, *args)
        with patch('ingest.chatgpt_plan_auth.authenticate_worker') as login:
            self.assertEqual(require_configured_provider(Env(AI_PROVIDER='chatgpt_plan')),
                             (PROVIDER_CHATGPT_PLAN, None))
        login.assert_not_called()
        with self.assertRaises(ProviderError):
            create_provider_adapter('chatgpt_plan', 'synthetic-paid-key', client=FakeClient())

    def test_session_requires_verified_identity_permission_model_and_expiry(self):
        with self.assertRaises(ProbeError):
            PlanSession('synthetic-unverified', time.time()+3600, object())
        grant, keys = grant_fixture()
        args = dict(client_id='oaiapp_synthetic', nonce='nonce', keys=keys)
        for overrides in ({'nonce':'wrong'}, {'catalog':{'models':[]}}):
            with self.assertRaises(ProbeError):
                PlanSession.from_grant(grant, **{**args,
                    'catalog':{'models':[{'slug':GPT_MODEL,'visibility':'list'}]}, **overrides})
        adapter, client, session = self.adapter()
        self.assertNotIn(session.access_token(), repr(session))
        session.expires_at = time.time() + 200
        with self.assertRaises(AiJobError) as error:
            adapter.summarize_ko('synthetic', None)
        self.assertEqual(error.exception.code, 'ai_http_401')
        self.assertEqual(client.calls, [])

    def test_no_renewable_session_or_noninteractive_login(self):
        attempt = AuthorizationAttempt('urn:uuid:00000000-0000-4000-8000-000000000001',
            'http://127.0.0.1:1234/auth/callback', renewable=False)
        self.assertNotIn('offline_access', parse_qs(urlsplit(attempt.url).query)['scope'][0])
        with patch('ingest.chatgpt_plan_auth.sys.stdin.isatty', return_value=False):
            with self.assertRaises(ProbeError) as error:
                authenticate_worker()
        self.assertEqual(error.exception.code, 'chatgpt_plan_login_requires_terminal')

    def test_all_summary_interfaces_and_shared_translation_rules(self):
        for method, instructions in [('summarize_ko',SUMMARY_SYSTEM),
                                     ('summarize_program_ko',PROGRAM_SUMMARY_SYSTEM),
                                     ('summarize_myseoul_ko',MYSEOUL_SUMMARY_SYSTEM)]:
            adapter, client, _ = self.adapter()
            self.assertEqual(getattr(adapter,method)('synthetic',None)[2], GPT_MODEL)
            self.assertEqual(adapter.translate_ja('합성','한국어 요약입니다.')[3], GPT_MODEL)
            self.assertEqual(client.calls[0]['instructions'], instructions)
            self.assertIn('Contextual terminology', client.calls[1]['instructions'])
            for request in client.calls:
                self.assertFalse({'max_output_tokens','truncation','service_tier','tools'} & request.keys())
                self.assertTrue(request['stream'])
                self.assertFalse(request['store'])
                self.assertTrue(request['text']['format']['strict'])
            self.assertEqual(adapter._usage_records[0]['billing'], 'chatgpt_plan')
            self.assertIsNone(adapter._usage_records[0]['cost_upper_usd'])
            self.assertNotIn('attribution', json.dumps(adapter._usage_records))

    def test_generation_budget_resets_for_new_jobs_but_no_repeated_stage_in_a_pair(self):
        client = streamed([response(SUMMARY_JSON),response(TRANSLATION_JSON)] * 2)
        adapter, _, _ = self.adapter(client)
        for body in ('synthetic-same-text','synthetic-same-text'):
            adapter.summarize_ko(body,None)
            with self.assertRaises(AiJobError):
                adapter.summarize_ko(body,None)
            adapter.translate_ja('합성','한국어 요약입니다.')
            self.assertEqual(adapter._create_calls,2)
            with self.assertRaises(AiJobError):
                adapter.translate_ja('합성','한국어 요약입니다.')
        self.assertEqual(len(client.calls),4)

    def test_expired_session_between_stages_never_calls_translation(self):
        adapter, client, session = self.adapter()
        adapter.summarize_ko('synthetic',None)
        session.expires_at = 0
        with self.assertRaises(AiJobError):
            adapter.translate_ja('합성','한국어 요약입니다.')
        self.assertEqual(len(client.calls),1)

    def test_injected_sdk_client_cannot_replace_oauth_with_paid_key_or_endpoint(self):
        for changes in ({'api_key':'synthetic-paid-key'},
                        {'base_url':'https://synthetic.invalid/v1'},
                        {'max_retries':2},
                        {'default_headers':{'Authorization':'Bearer synthetic-paid-key'}}):
            session = verified_session()
            client = FakeClient()
            for key,value in changes.items():
                setattr(client,key,value)
            with self.assertRaises(AiJobError):
                create_provider_adapter('chatgpt_plan',None,client=client,plan_session=session)
            self.assertEqual(client.calls,[])
            with self.assertRaises(ProbeError):
                session.access_token()

    def test_usage_over_limit_includes_reasoning_and_does_not_expand_budget(self):
        for stage, limit in [('summary',SUMMARY_MAX_TOKENS), ('translation',TRANSLATION_MAX_TOKENS)]:
            replies = [response(SUMMARY_JSON), response(TRANSLATION_JSON)]
            reply = replies[0 if stage=='summary' else 1]
            reply['usage']['output_tokens'] = limit + 1
            adapter, client, _ = self.adapter(streamed(replies))
            with self.assertRaises(AiJobError) as error:
                adapter.summarize_ko('synthetic',None)
                if stage == 'translation':
                    adapter.translate_ja('합성','한국어 요약입니다.')
            self.assertEqual(error.exception.code,'ai_cost_bound_breach')
            self.assertEqual(len(client.calls),1 if stage=='summary' else 2)
        with patch.dict('os.environ', {'AI_PROVIDER':'chatgpt_plan'}, clear=True):
            self.assertIsNone(provider_validation_limits()['usd_cap'])

    def test_native_myseoul_fenced_candidate_and_unknown_finish(self):
        for mode in ('success','unknown'):
            c = native_packet()
            before = copy.deepcopy(c)
            client = streamed(native_client(c).responses.results)
            result, calls, adapter = gpt_fixture.GPTPipelineTests().native_run(c,client,mode,
                adapter_factory=lambda **kw:self.adapter(kw['client'])[0])
            self.assertEqual(result.completed, 1 if mode=='success' else 0)
            self.assertEqual(result.state_unknown, 0 if mode=='success' else 1)
            self.assertEqual(c,before)
            self.assertEqual(len(client.calls),2)
            self.assertEqual(sum(n.startswith('finish_') for n,_ in calls),1)
            self.assertFalse(any(n.startswith('fail_') for n,_ in calls))
            output = calls[-1][1]['p_output']
            self.assertEqual(output['aiModel'],GPT_MODEL)
            self.assertIn('총 3회',output['contentKo'])
            self.assertIn('선착순 25명',output['contentKo'])
            self.assertNotIn('173%',output['contentKo'])
            packet = json.loads(client.calls[0]['input'][0]['content'].split('body:\n',1)[1])
            self.assertEqual(packet['currentFacts']['description'],c['facts']['description'])
            self.assertIn(output['contentKo'],client.calls[1]['input'][0]['content'])
            self.assertEqual(c['factsVersion'],calls[-1][1]['p_facts_version'])

    def test_omitted_session_year_reaches_translation_and_fenced_candidate(self):
        c = native_packet()
        c['facts']['periods']['operation'] = [{'status':'ok','endpoints':[
            {'value':'2027-02-03','precision':'day'}, {'value':'2027-02-17','precision':'day'}]}]
        c['facts']['session_evidence'] = ['2월 3일, 2월 10일, 2월 17일 09:30~11:00, 총 3회']
        before = copy.deepcopy(c)
        ko = ('[한 줄 요약]\n합성 교육입니다.\n[기간·상태]\n'
            '운영 기간: 2027년 2월 3일~2월 17일\n'
            '실제 수업: 2027년 2월 3일, 2월 10일, 2월 17일 각 09:30~11:00, 총 3회\n'
            '[주요 내용]\n선착순 25명 교육입니다.')
        replies = native_client(c).responses.results
        replies[0] = summary_response(ko)
        payload = json.loads(replies[1]['output'][1]['content'][0]['text'])
        payload['content_ja'] = payload['content_ja'].replace(
            '10月3日(土)、10月10日(土)、10月17日(土)、全3回',
            '2月3日、2月10日、2月17日、09:30～11:00、全3回')
        replies[1] = response(json.dumps(payload))
        client = streamed(replies)
        result, calls, adapter = gpt_fixture.GPTPipelineTests().native_run(c,client,
            adapter_factory=lambda **kw:self.adapter(kw['client'])[0])
        self.assertEqual(result.completed,1)
        self.assertEqual(result.failed,0)
        self.assertEqual(c,before)
        self.assertEqual(len(client.calls),2)
        self.assertEqual([n for n,_ in calls],['claim_myseoul_program_ai',
            'admin_myseoul_program_detail','finish_myseoul_program_ai'])
        output = calls[-1][1]['p_output']
        self.assertIn(c['facts']['session_evidence'][0],output['contentKo'])
        self.assertIn(output['contentKo'],client.calls[1]['input'][0]['content'])
        self.assertEqual(output['aiModel'],GPT_MODEL)
        self.assertEqual(set(output),{'titleKo','titleJa','summaryKo','summaryJa','contentKo','contentJa','aiModel'})
        for parameter,key in [('p_revision','revision'),('p_facts_version','factsVersion'),
                              ('p_claimed_at','claimedAt'),('p_lease_until','leaseUntil'),('p_worker_id','workerId')]:
            self.assertEqual(calls[-1][1][parameter],c[key])
        self.assertTrue(all(record['billing']=='chatgpt_plan' for record in adapter._usage_records))

    def test_fee_prose_deduplication_preserves_roles_through_plan_candidate(self):
        c = native_packet()
        c['facts']['fees'] = [{'component':'tuition','evidence':['10,000원']},
                              {'component':'materials','evidence':['2,000원']}]
        before = copy.deepcopy(c)
        replies = native_client(c).responses.results
        replies[0] = summary_response('[한 줄 요약]\n합성 교육입니다.\n[주요 내용]\n'
            '선착순 25명 교육입니다. 수강료는 10,000원이며, 재료비는 별도로 2,000원입니다.')
        payload = json.loads(replies[1]['output'][1]['content'][0]['text'])
        payload['content_ja'] = payload['content_ja'].replace('受講料: 無料; 入場料: 3,000ウォン',
            '受講料: 10,000ウォン; 材料費: 2,000ウォン')
        replies[1] = response(json.dumps(payload))
        client = streamed(replies)
        result, calls, adapter = gpt_fixture.GPTPipelineTests().native_run(c,client,
            adapter_factory=lambda **kw:self.adapter(kw['client'])[0])
        self.assertEqual(result.completed,1)
        self.assertEqual(c,before)
        self.assertEqual(len(client.calls),2)
        output = calls[-1][1]['p_output']
        self.assertEqual(output['contentKo'].count('수강료'),1)
        self.assertEqual(output['contentKo'].count('재료비'),1)
        self.assertEqual(output['contentJa'].count('受講料'),1)
        self.assertEqual(output['contentJa'].count('材料費'),1)
        self.assertIn('비용: 수강료: 10,000원; 재료비: 2,000원',output['contentKo'])
        self.assertIn(output['contentKo'],client.calls[1]['input'][0]['content'])
        self.assertEqual(output['aiModel'],GPT_MODEL)
        self.assertTrue(all(record['billing']=='chatgpt_plan' for record in adapter._usage_records))
        self.assertEqual(calls[-1][0],'finish_myseoul_program_ai')
        self.assertEqual(calls[-1][1]['p_revision'],c['revision'])
        self.assertEqual(calls[-1][1]['p_facts_version'],c['factsVersion'])

    def test_conflicting_session_year_or_time_stops_before_plan_translation(self):
        for schedule in ('2028년 10월 3일, 총 3회', '10월 3일 09:30~12:00, 총 3회'):
            c = native_packet()
            c['facts']['session_evidence'] = ['10월 3일, 10월 10일, 10월 17일 09:30~11:00, 총 3회']
            before = copy.deepcopy(c)
            ko = '[한 줄 요약]\n합성 교육\n[기간·상태]\n실제 수업: '+schedule+'\n[주요 내용]\n합성 활동'
            client = streamed([summary_response(ko)])
            with self.subTest(schedule=schedule):
                result, calls, _ = gpt_fixture.GPTPipelineTests().native_run(c,client,
                    adapter_factory=lambda **kw:self.adapter(kw['client'])[0])
                self.assertEqual(result.failed,1)
                self.assertEqual(result.completed,0)
                self.assertEqual(len(client.calls),1)
                self.assertEqual(c,before)
                self.assertFalse(any(n.startswith('finish_') for n,_ in calls))
                self.assertEqual(calls[-1][1]['p_error_code'],'ai_schema_error')

    def test_native_stale_claim_never_generates(self):
        c = native_packet()
        c['revision'] = 'b'*64
        # Deliberately mismatch the requested revision through a malformed item.
        c['sourceItemId'] = '00000000-0000-4000-8000-000000000099'
        client = streamed(native_client(c).responses.results)
        result, _, _ = gpt_fixture.GPTPipelineTests().native_run(c,client,
            adapter_factory=lambda **kw:self.adapter(kw['client'])[0])
        self.assertEqual(result.state_unknown,1)
        self.assertEqual(client.calls,[])

    def test_unknown_stream_preserves_fence_without_fail_write_or_automatic_replay(self):
        client = FakeClient([[{'type':'response.output_text.delta','delta':SUMMARY_JSON}]])
        result, calls, adapter = gpt_fixture.GPTPipelineTests().native_run(native_packet(), client,
            adapter_factory=lambda **kw:self.adapter(kw['client'])[0])
        self.assertEqual(result.state_unknown,1)
        self.assertFalse(any(n.startswith(('finish_','fail_')) for n,_ in calls))
        with self.assertRaises(RpcAmbiguous):
            adapter.summarize_ko('new-job',None)
        self.assertEqual(len(client.calls),1)

    def test_schema_or_fidelity_failure_does_not_complete_candidate(self):
        c = native_packet()
        for bad in ('{"content_ko":"extra"}', 'not json'):
            client = streamed([response(bad)])
            result, calls, _ = gpt_fixture.GPTPipelineTests().native_run(c,client,
                adapter_factory=lambda **kw:self.adapter(kw['client'])[0])
            self.assertEqual(result.failed,1)
            self.assertFalse(any(n.startswith('finish_') for n,_ in calls))
            self.assertEqual(len(client.calls),1)
        replies = native_client(c).responses.results
        replies[1] = response(json.dumps({'title_ja':'合成','content_ja':'[要約]\n合成\n[主な内容]\n先着250名'}))
        result, calls, _ = gpt_fixture.GPTPipelineTests().native_run(c,streamed(replies),
            adapter_factory=lambda **kw:self.adapter(kw['client'])[0])
        self.assertEqual(result.failed,1)
        self.assertFalse(any(n.startswith('finish_') for n,_ in calls))

    def test_reclassified_categories_preserve_contract_and_do_not_publish(self):
        for category in ('program','event','youth_space','policy','living'):
            c = classified_context(category)
            ja = '[要約]\n合成\n[主な内容]\n合成活動\n保護者同伴条件\n費用: 10,000ウォン'
            if category == 'program':
                ja += '\n申請締切: 2099年10月15日\n申請期間: 2099年10月1日～2099年10月15日'
            if category == 'event':
                ja += '\n開催期間: 2099年10月9日～2099年10月9日'
            client = streamed([summary_response('[한 줄 요약]\n합성\n[주요 내용]\n합성 활동'),
                response(json.dumps({'title_ja':'合成','content_ja':ja}))])
            adapter, _, _ = self.adapter(client)
            calls = []
            def rpc(name,args):
                calls.append((name,args))
                if name=='claim_reclassified_content_ai':
                    return c
                if name=='finish_reclassified_content_ai':
                    return {'outcome':'inserted','candidateId':ID}
                raise AssertionError(name)
            result = process_reclassified_job(ProgramAIAdapter(rpc), source_item_id=ID,
                revision=REV, classification_version=1, worker_id='synthetic-worker',
                summarize_ko=adapter.summarize_ko, translate_ja=adapter.translate_ja)
            self.assertEqual(result.completed,1,category)
            output = calls[-1][1]['p_output']
            self.assertEqual(output['aiModel'],GPT_MODEL)
            self.assertIn(protected_information(c),output['contentKo'])
            self.assertEqual(len(client.calls),2)
            self.assertEqual(c['classificationVersion'],calls[-1][1]['p_classification_version'])
            self.assertEqual(set(output),{'titleKo','summaryKo','contentKo','titleJa','summaryJa','contentJa','aiModel'})

    def test_installed_sdk_uses_oauth_resource_stream_and_never_token_count_route(self):
        import httpx
        from openai import OpenAI
        session = verified_session()
        calls = []
        def handle(request):
            self.assertEqual(str(request.url),RESOURCE+'/responses')
            self.assertEqual(request.headers['Authorization'],'Bearer '+session.access_token())
            payload = json.loads(request.content)
            calls.append(payload)
            result = response(SUMMARY_JSON if len(calls)==1 else TRANSLATION_JSON)
            result['usage']['total_tokens'] = 110
            events = streamed([result]).events[0]
            return httpx.Response(200,headers={'Content-Type':'text/event-stream'},
                text=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events)+'data: [DONE]\n\n')
        with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
            with OpenAI(api_key=session.access_token(),base_url=RESOURCE,max_retries=0,
                        http_client=transport) as client:
                adapter = ChatGPTPlanAdapter(session=session,client=client)
                adapter.summarize_myseoul_ko('synthetic',None)
                adapter.translate_ja('합성','한국어 요약입니다.')
        self.assertEqual(len(calls),2)
        self.assertTrue(all(c['stream'] and not c['store'] for c in calls))
        adapter.close()
        with self.assertRaises(ProbeError):
            session.access_token()

    def test_cli_helpers_authenticate_before_db_and_clear_session_on_failure(self):
        import run_ingest_architecture as cli
        adapter, _, session = self.adapter()
        events = []
        def login():
            events.append('auth')
            return session
        def construct(*args,**kwargs):
            self.assertEqual(events,['auth'])
            events.append('db-factory')
            raise RuntimeError('synthetic construction failure')
        with patch.dict('os.environ',{'AI_PROVIDER':'chatgpt_plan','SUPABASE_URL':'synthetic',
                                     'SUPABASE_SERVICE_KEY':'synthetic'},clear=True):
            with patch('ingest.chatgpt_plan_auth.authenticate_worker',side_effect=login):
                with patch('ingest.ai_chatgpt_plan.ChatGPTPlanAdapter',return_value=adapter):
                    with patch.object(cli,'create_ingest_client',side_effect=construct):
                        with patch('sys.stderr',io.StringIO()):
                            self.assertEqual(cli.main(['--ai-only','--ai-limit','1','--execute']),1)
        self.assertEqual(events,['auth','db-factory'])
        with self.assertRaises(ProbeError):
            session.access_token()

    def test_target_entrypoints_use_plan_factory_and_clear_session_without_real_rpc(self):
        import run_myseoul_program_ai as native
        import run_reclassified_content_ai as classified
        import run_seoul_program_ai as seoul
        from ingest.ai_worker import AiWorkerResult
        for cli, module, method in [(native,'ingest.myseoul_ai','process_myseoul_job'),
                                   (classified,'ingest.reclassification_ai','process_reclassified_job'),
                                   (seoul,'ingest.program_ai','process_seoul_program_job')]:
            adapter, _, session = self.adapter()
            args = SimpleNamespace(project_ref='a'*20,source_item_id=ID,revision=REV,classification_version=1)
            with patch.dict('os.environ',{'AI_PROVIDER':'chatgpt_plan',
                'SUPABASE_URL':'https://'+'a'*20+'.supabase.co','SUPABASE_SERVICE_KEY':'synthetic'},clear=True):
                with patch('ingest.ai_provider.create_provider_adapter',return_value=adapter) as factory:
                    with patch('ingest.supabase_store.create_ingest_client',return_value=object()):
                        with patch(module+'.'+method,return_value=AiWorkerResult(status='processed')) as worker:
                            cli.execute_target(args)
            factory.assert_called_once_with('chatgpt_plan',None)
            self.assertIs(worker.call_args.kwargs['translate_ja'].__self__,adapter)
            with self.assertRaises(ProbeError):
                session.access_token()

    def test_generic_worker_uses_plan_for_two_synthetic_jobs_and_stops_unknown_completion(self):
        for unknown in (False,True):
            store = worker_fixture.SpyStore()
            worker_fixture._seed(store,2)
            ko = summary_response('[한 줄 요약]\n합성 안내입니다.\n[주요 내용]\n합성 내용입니다.')
            ja = response(json.dumps({'title_ja':'合成案内',
                'content_ja':'[要約]\n合成案内です。\n[主な内容]\n合成内容です。'}))
            client = streamed([ko,ja,ko,ja])
            if unknown:
                client.events[0] = [{'type':'response.output_text.delta','delta':SUMMARY_JSON}]
            adapter, _, _ = self.adapter(client)
            candidates = []
            def enqueue(_client, params):
                candidates.append(params)
                return {'outcome':'inserted','candidate_id':ID}
            result = process_ai_jobs(store,limit=2,**worker_fixture._ai_deps(
                summarize_ko=adapter.summarize_ko,translate_ja=adapter.translate_ja,enqueue=enqueue))
            self.assertEqual(result.completed,0 if unknown else 2)
            self.assertEqual(result.state_unknown,1 if unknown else 0)
            self.assertEqual(len(client.calls),1 if unknown else 4)
            self.assertEqual(len(store.fail_calls),0)
            for candidate in candidates:
                self.assertEqual(candidate['p_ai_model'],GPT_MODEL)
                self.assertEqual(candidate['p_ai_status_ja'],'success')
                self.assertNotIn('facts',candidate)

    def test_plan_usage_limit_and_http_errors_never_fall_back_or_resend(self):
        for code in ('subscription_sharing_usage_limit_exceeded',
                     'subscription_sharing_usage_unavailable','subscription_sharing_user_not_eligible'):
            for event in ({'type':'response.failed','response':{'error':{'code':code}}},
                          {'type':'error','code':code,'message':'synthetic private marker'}):
                client = FakeClient([[event]])
                adapter, _, _ = self.adapter(client)
                with self.assertRaises(AiJobError) as raised:
                    adapter.summarize_ko('synthetic',None)
                self.assertNotIn('private marker',str(raised.exception))
                with self.assertRaises(RpcAmbiguous):
                    adapter.summarize_ko('other synthetic',None)
                self.assertEqual(len(client.calls),1)

    def test_owned_sdk_construction_pins_oauth_resource_timeout_and_clears_credentials(self):
        import httpx
        from openai import OpenAI as OfficialClient
        session = verified_session()
        def handle(request):
            text = SUMMARY_JSON
            event = {'type':'response.completed','response':response(text)}
            event['response']['usage']['total_tokens'] = 110
            return httpx.Response(200,headers={'Content-Type':'text/event-stream'},
                text='event: response.completed\ndata: '+json.dumps(event)+'\n\ndata: [DONE]\n\n')
        with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
            def sdk_factory(**params):
                return OfficialClient(http_client=transport,**params)
            with patch('openai.OpenAI',side_effect=sdk_factory) as constructor:
                adapter = create_provider_adapter('chatgpt_plan',None,plan_session=session)
                owned = adapter._client
                self.assertEqual(constructor.call_args.kwargs['base_url'],RESOURCE)
                self.assertEqual(constructor.call_args.kwargs['api_key'],session.access_token())
                self.assertEqual(constructor.call_args.kwargs['max_retries'],0)
                self.assertEqual(constructor.call_args.kwargs['timeout'],120)
                adapter.summarize_ko('synthetic',None)
                adapter.close()
                self.assertEqual(owned.api_key,'')
                self.assertTrue(owned.is_closed())
                with self.assertRaises(ProbeError):
                    session.access_token()

    def test_login_uses_same_verified_account_grant_catalog_without_inference_or_secret_files(self):
        import ingest.chatgpt_plan_auth as auth
        for denied in (False,True):
            grant, keys, encode, identity, access = pro_fixture.ProProbeTests().grant()
            expiry = int(time.time()) + 3600
            attempts, http_calls, replies = [], [], []
            def make_attempt(*args,**kwargs):
                attempt = AuthorizationAttempt(*args,**kwargs)
                attempts.append(attempt)
                return attempt
            class Server:
                server_port = 1234
                def __init__(self, address, handler):
                    self.handler = handler
                    self.address = address
                def __enter__(self):
                    return self
                def __exit__(self,*args):
                    pass
                def handle_request(self):
                    # Native HTTP is replaced; exercise the real callback handler.
                    fake = SimpleNamespace(headers={'Host':'127.0.0.1:1234'},
                        path='/auth/callback?' + urlencode({'state':attempts[-1].state,
                            'code':'synthetic-code','client_id':'oaiapp_synthetic'}),
                        reply=lambda *args:replies.append(args))
                    self.handler.do_GET(fake)
            class HTTP:
                def __enter__(self):
                    return self
                def __exit__(self,*args):
                    pass
                def get(self,url,**kwargs):
                    http_calls.append(('GET',url))
                    if url == DISCOVERY:
                        data = {'issuer':auth.validate_discovery.__globals__['ISSUER'],
                            'authorization_endpoint':auth.validate_discovery.__globals__['AUTHORIZE'],
                            'token_endpoint':TOKEN,'jwks_uri':JWKS}
                    elif url == JWKS:
                        data = keys
                    elif url == RESOURCE+'/models':
                        self_token = grant['access_token']
                        if kwargs['headers']['Authorization'] != 'Bearer '+self_token:
                            raise AssertionError('account mismatch')
                        data = {'models':[{'slug':GPT_MODEL,'visibility':'list'}]}
                    else:
                        raise AssertionError('unexpected route')
                    if kwargs['allow_redirects'] is not False:
                        raise AssertionError('redirect enabled')
                    return SimpleNamespace(status_code=200,json=lambda:copy.deepcopy(data))
                def post(self,url,**kwargs):
                    http_calls.append(('POST',url))
                    if url != TOKEN or kwargs['data']['client_id'] != 'oaiapp_synthetic':
                        raise AssertionError('unexpected token exchange')
                    grant['id_token'] = encode({**identity,'exp':expiry,'nonce':attempts[-1].nonce})
                    grant['access_token'] = encode({**access,'exp':expiry})
                    if denied:
                        grant['scope'] = 'openid'
                    return SimpleNamespace(status_code=200,json=lambda:copy.deepcopy(grant))
            cache_root = Path(__file__).resolve().parent / '__pycache__'
            with tempfile.TemporaryDirectory(dir=cache_root) as folder:
                self.assertTrue(Path(folder).resolve().is_relative_to(cache_root.resolve()))
                with patch.object(auth.sys.stdin,'isatty',return_value=True):
                    with patch.object(auth.tempfile,'gettempdir',return_value=folder):
                        with patch.object(auth,'HTTPServer',Server):
                            with patch.object(auth,'AuthorizationAttempt',side_effect=make_attempt):
                                with patch('requests.Session',HTTP):
                                    with redirect_stdout(io.StringIO()) as out:
                                        if denied:
                                            with self.assertRaises(ProbeError):
                                                authenticate_worker()
                                        else:
                                            selected = authenticate_worker()
                                            self.assertEqual(selected.access_token(),grant['access_token'])
                                            selected.clear()
                metadata = json.loads((Path(folder)/'machimoa-chatgpt-plan-probe'/'registration.json').read_text())
                self.assertEqual(set(metadata),{'host_id'} if denied else {'host_id','client_id'})
                self.assertNotIn(grant['access_token'],out.getvalue())
                self.assertNotIn('synthetic-code',out.getvalue())
            self.assertEqual(http_calls,[('GET',DISCOVERY),('POST',TOKEN),('GET',JWKS)] +
                ([] if denied else [('GET',RESOURCE+'/models')]))
            self.assertEqual(replies[0][0],200)


if __name__ == '__main__':
    unittest.main()
