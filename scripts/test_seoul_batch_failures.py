"""Bounded multi-item worker tests; fake OAuth/Pro/RPC, real network denied."""
import copy
import json
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ingest.ai_chatgpt_plan import ChatGPTPlanAdapter
from ingest.ai_errors import AiJobError
from ingest.chatgpt_plan_protocol import ProbeError, RESOURCE, read_completed_stream
from ingest.program_ai import ProgramAIAdapter
from ingest.rpc_errors import RpcAmbiguous, RpcTimeout
from ingest.seoul_content import assemble_seoul_body
from ingest.seoul_workflow import process_seoul_queue
from test_ingest_ai_chatgpt_plan import verified_session, streamed
from test_ingest_ai_openai import response, SUMMARY_JSON
from test_seoul_fact_roles import replay_context, confirmed_case, fake_translation


class BatchFailureTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                     'ingest.supabase_store.create_ingest_client',
                     'ingest.chatgpt_plan_auth.authenticate_worker'):
            guard = patch(name, side_effect=AssertionError('real connection forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def batch(self, modes, *, no_retry=True, max_jobs=None):
        contexts, replies = [], []
        summary = confirmed_case()['summary']
        for index, mode in enumerate(modes):
            _, c = replay_context()
            c['sourceItemId'] = f'00000000-0000-4000-8000-{index+1:012d}'
            c['jobId'] = f'10000000-0000-4000-8000-{index+1:012d}'
            c['failurePolicy'] = {'policy':'no_retry', 'attempt':f'{index+1:064x}'}
            contexts.append(c)
            if mode in {'skip', 'claim_unknown', 'stale'}: continue
            if mode in {'transport','http401','quota','localbug'}:
                replies.append(None); continue
            ko = copy.deepcopy(summary)
            if mode in {'ko_schema', 'fail_unknown'}: ko = {'content_ko':'invalid'}
            if mode == 'ko_schedule': ko['content_ko'] = ko['content_ko'].replace('10:00','09:00')
            ko_response = response(json.dumps(ko, ensure_ascii=False))
            if mode == 'usage': ko_response['usage']['total_tokens'] = 99999
            replies.append(ko_response)
            if mode in {'ko_schema', 'ko_schedule', 'fail_unknown', 'usage'}: continue
            assembled = assemble_seoul_body(summary['content_ko'],c['facts'])
            ja = {'title_ja':'合成の解説', 'content_ja':fake_translation(assembled)}
            if mode == 'ja_schema': ja['content_ja'] = 'invalid'
            replies.append(response(json.dumps(ja, ensure_ascii=False)))
        client = streamed([reply if reply is not None else response(SUMMARY_JSON) for reply in replies])
        for index, reply in enumerate(replies):
            if reply is None: client.events[index] = [{'type':'response.output_text.delta','delta':'partial'}]
        if modes[0]=='quota':
            client.events[0] = [{'type':'response.failed','response':{
                'error':{'code':'subscription_sharing_usage_limit_exceeded','message':'private text'}}}]
        if modes[0] in {'http401','localbug'}:
            def broken_create(**request):
                client.calls.append(request)
                if modes[0]=='localbug': raise KeyError('private text')
                import httpx
                from openai import AuthenticationError
                raise AuthenticationError('private token',response=httpx.Response(401,
                    request=httpx.Request('POST',RESOURCE+'/responses')),body={'secret':'private token'})
            client.responses.create=broken_create
        provider = ChatGPTPlanAdapter(session=verified_session(), client=client)
        self.addCleanup(provider.close)
        originals = copy.deepcopy(contexts)
        events, claims, terminal, outputs = [], [], [], []
        by_id = {c['sourceItemId']:(i,c) for i,c in enumerate(contexts)}
        by_job = {c['jobId']:(i,c) for i,c in enumerate(contexts)}
        def rpc(name,args):
            events.append((name,copy.deepcopy(args)))
            if name == 'admin_review_ai_queue':
                return {'hasMore':False,'items':[dict(sourceName='seoul_reservation',status='queued',
                    currentRevision=True,leaseState='none',retryCount=0,nextRetryAt=None,
                    sourceItemId=c['sourceItemId'],revision=c['revision']) for c in contexts]}
            if name.startswith('claim_seoul_program_ai'):
                i,c = by_id[args['p_source_item_id']]; claims.append(i)
                if modes[i]=='skip': return []
                if modes[i]=='claim_unknown': raise RpcTimeout()
                current = copy.deepcopy(c)
                if modes[i]=='stale': current['revision'] = 'b'*64
                return [current]
            i,c = by_job[args['p_job_id']]
            self.assertEqual(args['p_claimed_at'], c['claimedAt'])
            self.assertEqual(args['p_lease_until'], c['leaseUntil'])
            self.assertEqual(args['p_worker_id'], c['workerId'])
            if name != 'fail_seoul_program_ai': self.assertEqual(args['p_revision'], c['revision'])
            if name == 'finish_seoul_program_ai':
                if modes[i]=='finish_unknown': raise RpcTimeout()
                if modes[i]=='finish_malformed': return {'outcome':'inserted'}
                self.assertEqual(args['p_facts_version'],c['factsVersion'])
                outputs.append(args['p_output'])
                return {'outcome':'inserted','candidateId':c['sourceItemId']}
            if name in {'fail_seoul_ai_no_retry','fail_seoul_program_ai'}:
                if no_retry: self.assertEqual(args['p_attempt'],c['failurePolicy']['attempt'])
                if modes[i]=='fail_unknown': raise RpcTimeout()
                terminal.append(i); return 'failed'
            raise AssertionError('unexpected RPC')
        counts = process_seoul_queue(ProgramAIAdapter(rpc),max_jobs=max_jobs or len(modes),queue_pages=1,
            summarize_ko=provider.summarize_program_ko,translate_ja=provider.translate_ja,
            worker_id=contexts[0]['workerId'],no_retry=no_retry)
        self.assertEqual(contexts,originals)
        self.assertNotIn(contexts[0]['failurePolicy']['attempt'],json.dumps(client.calls))
        self.assertEqual(counts['automatic_retries'],0); self.assertFalse(counts['publish'])
        return counts, client, events, claims, terminal, outputs, provider

    def test_collect_two_failures_then_success_with_one_pair_per_item(self):
        r,client,e,claims,terminal,outputs,_ = self.batch(['ko_schema','ja_schema','success'])
        self.assertEqual((r['completed'],r['failed'],r['state_unknown'],r['unprocessed']),(1,2,0,0))
        self.assertFalse(r['batch_stopped']); self.assertEqual(claims,[0,1,2]); self.assertEqual(terminal,[0,1])
        stages = [c['text']['format']['name'] for c in client.calls]
        self.assertEqual(stages,['machimoa_summary','machimoa_summary','machimoa_translation',
                                 'machimoa_summary','machimoa_translation'])
        self.assertEqual([i['failureScope'] for i in r['items']],['item','item',None])
        self.assertEqual(len(outputs),1)
        self.assertIn(outputs[0]['contentKo'],client.calls[-1]['input'][0]['content'])
        self.assertNotIn('fail_seoul_program_ai',[n for n,_ in e])

    def test_schedule_conflict_is_terminal_before_next_item(self):
        r,client,_,claims,terminal,outputs,_ = self.batch(['ko_schedule','success'])
        self.assertEqual((r['completed'],r['failed']),(1,1)); self.assertEqual(terminal,[0])
        self.assertEqual(claims,[0,1]); self.assertEqual(len(client.calls),3)
        self.assertEqual(r['items'][0]['failureStage'],'korean_validation'); self.assertEqual(len(outputs),1)

    def test_unknown_or_malformed_write_stops_without_replay(self):
        for mode in ('transport','finish_unknown','finish_malformed','fail_unknown','claim_unknown','stale'):
            with self.subTest(mode=mode):
                r,client,e,claims,terminal,outputs,_ = self.batch([mode,'success'])
                self.assertTrue(r['batch_stopped']); self.assertEqual(r['stop_reason'],'state_unknown')
                self.assertEqual((r['state_unknown'],r['unprocessed']),(1,1)); self.assertEqual(claims,[0])
                self.assertEqual(terminal,[]); self.assertEqual(outputs,[])
                self.assertLessEqual(len(client.calls),2)
                self.assertLessEqual(sum(n=='fail_seoul_ai_no_retry' for n,_ in e),1)

    def test_usage_contract_failure_terminates_but_stops_batch(self):
        r,client,_,claims,terminal,_,provider = self.batch(['usage','success'])
        self.assertEqual(r['stop_reason'],'common_failure'); self.assertEqual(r['failed'],1)
        self.assertEqual(r['unprocessed'],1); self.assertEqual(claims,[0]); self.assertEqual(terminal,[0])
        self.assertEqual(len(client.calls),1)
        with self.assertRaises(RpcAmbiguous): provider.release_terminated_attempt()
        self.assertEqual(len(client.calls),1)

    def test_actual_provider_errors_stop_before_second_claim(self):
        for mode,unknown in (('http401',False),('quota',False),('localbug',True)):
            with self.subTest(mode=mode):
                r,client,_,claims,terminal,outputs,_=self.batch([mode,'success'])
                self.assertEqual(claims,[0]); self.assertEqual(len(client.calls),1)
                self.assertTrue(r['batch_stopped']); self.assertEqual(r['unprocessed'],1)
                self.assertEqual(terminal,[] if unknown else [0]); self.assertEqual(outputs,[])
                self.assertEqual(r['state_unknown'],int(unknown)); self.assertEqual(r['failed'],int(not unknown))
                self.assertNotIn('private',json.dumps(r))
                if unknown:
                    self.assertEqual(r['items'][0]['diagnostic']['exceptionKind'],'local_key')

    def test_duplicate_claim_skip_does_not_generate_and_maximum_is_fixed(self):
        r,client,_,claims,terminal,outputs,_ = self.batch(['skip','success','success'],max_jobs=2)
        self.assertEqual(claims,[0,1]); self.assertEqual(len(client.calls),2)
        self.assertEqual((r['completed'],r['unavailable_skipped'],r['unprocessed']),(1,1,1))
        self.assertEqual(terminal,[]); self.assertEqual(len(outputs),1)

    def test_legacy_failure_policy_still_stops(self):
        r,client,_,claims,terminal,_,_ = self.batch(['ko_schema','success'],no_retry=False)
        self.assertTrue(r['batch_stopped']); self.assertEqual(claims,[0]); self.assertEqual(terminal,[0])
        self.assertEqual(len(client.calls),1)

    def test_common_http_failure_is_not_treated_as_content_failure(self):
        from ingest.ai_chatgpt_plan import PlanCommonFailure
        for code in ('ai_http_400','ai_http_401','ai_http_403','ai_http_404','ai_http_429',
                     'ai_call_budget','ai_cost_bound_breach','ai_or_enqueue_failed'):
            from ingest.ai_failure_policy import terminal_failure_result
            self.assertEqual(terminal_failure_result(AiJobError(code),'summary').failure_scope,'batch')
        self.assertEqual(terminal_failure_result(PlanCommonFailure('ai_schema_error'),'summary').failure_scope,'batch')


class StreamDiagnosticTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('real network forbidden'))
        guard.start();self.addCleanup(guard.stop)

    def test_transport_and_local_errors_have_secret_safe_different_causes(self):
        import httpx
        from openai import APIConnectionError
        for exc,expected in ((KeyError('secret=https://private.invalid/?key=secret'),'local_key'),
                             (TypeError('secret token'),'local_type'),
                             (APIConnectionError(request=httpx.Request('POST',RESOURCE+'/responses')),'connection')):
            def create(**kw):
                try: raise httpx.ConnectError('secret endpoint')
                except httpx.ConnectError as cause: raise exc from cause
            client=SimpleNamespace(responses=SimpleNamespace(create=create))
            with self.assertRaises(ProbeError) as raised: read_completed_stream(client,{})
            error=raised.exception
            self.assertEqual(error.code,'plan_transport_unknown')
            self.assertEqual(error.diagnostic['exceptionKind'],expected)
            self.assertEqual(error.diagnostic['causeKind'],'connection')
            self.assertEqual(error.diagnostic['phase'],'create')
            self.assertEqual(error.diagnostic['eventCount'],0)
            self.assertNotIn('secret',json.dumps(error.diagnostic)+str(error))

    def test_observer_failure_after_completion_is_not_accepted(self):
        client=streamed([response(SUMMARY_JSON)])
        def bad_observer(event):
            if event['type']=='response.completed': raise RuntimeError('secret response')
        with self.assertRaises(ProbeError) as raised:
            read_completed_stream(client,{},observe=bad_observer)
        self.assertEqual(raised.exception.diagnostic['phase'],'observe')
        self.assertEqual(raised.exception.diagnostic['eventCount'],2)
        self.assertNotIn('secret',str(raised.exception.diagnostic))

    def test_read_failure_after_delta_keeps_unknown_and_reports_stage(self):
        from contextlib import contextmanager
        @contextmanager
        def create(**kw):
            def events():
                yield {'type':'response.output_text.delta','delta':'private raw response'}
                raise TimeoutError('private endpoint')
            yield events()
        client=SimpleNamespace(responses=SimpleNamespace(create=create))
        with self.assertRaises(ProbeError) as raised: read_completed_stream(client,{})
        self.assertEqual(raised.exception.code,'plan_timeout')
        self.assertEqual(raised.exception.diagnostic['phase'],'read')
        self.assertEqual(raised.exception.diagnostic['eventCount'],1)
        self.assertFalse(raised.exception.diagnostic['completedSeen'])
        self.assertNotIn('private',json.dumps(raised.exception.diagnostic))

    def test_nested_dns_cause_is_preserved_without_secret_message(self):
        import httpx
        from openai import APIConnectionError
        def create(**kwargs):
            try:
                try: raise socket.gaierror('private hostname')
                except socket.gaierror as dns: raise httpx.ConnectError('private URL') from dns
            except httpx.ConnectError as connection:
                raise APIConnectionError(request=httpx.Request('POST',RESOURCE+'/responses')) from connection
        with self.assertRaises(ProbeError) as raised:
            read_completed_stream(SimpleNamespace(responses=SimpleNamespace(create=create)),{})
        self.assertEqual(raised.exception.diagnostic['causeChain'],['connection','dns'])
        self.assertNotIn('private',json.dumps(raised.exception.diagnostic))


if __name__=='__main__': unittest.main()
