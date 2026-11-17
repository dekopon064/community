"""The real all-button dispatcher, MySeoul worker and validators; only fake RPC and Pro."""
import copy
import unittest
from uuid import UUID
from unittest.mock import patch

from ingest.ai_errors import AiJobError
from ingest.pc_worker_existing import ExistingWorkers
from ingest.program_ai import ProgramAIAdapter
from ingest.rpc_errors import RpcAmbiguous
from test_myseoul_ai import context, providers


class MySeoulTerminalBatch(unittest.TestCase):
    def run_case(self, mode):
        first = context()
        second = copy.deepcopy(first)
        second.update(sourceItemId=str(UUID(int=41)), jobId=str(UUID(int=42)))
        packets = {c['sourceItemId']: c for c in (first, second)}
        rows = [dict(jobId=c['jobId'], sourceItemId=c['sourceItemId'], revision=c['revision'],
                     sourceName=c['source'], status='queued', currentRevision=True, leaseState='none',
                     retryCount=0, nextRetryAt=None) for c in packets.values()]
        events = []
        claims = {}
        summarize, translate = providers(first)

        class Pro:
            def summarize_myseoul_ko(self, *args, **kwargs):
                events.append('summary')
                if len(claims) == 1:
                    if mode == 'unknown_ai':
                        raise RpcAmbiguous()
                    if mode in ('auth', 'quota'):
                        raise AiJobError('ai_http_401' if mode == 'auth' else 'ai_http_429')
                    if mode not in ('unknown_candidate', 'ok', 'clock', 'lost_clock_receipt', 'ko_schedule', 'draft', 'lost_draft', 'no_evidence'):
                        raise AiJobError('ai_schema_error')
                body, status, model=summarize(*args, **kwargs)
                if len(claims)==1 and mode=='ko_schedule':
                    body+='\n[일정 안내]\n진행 일정: 10월 3일 (토) 10:00~12:30'
                return body, status, model

            def translate_ja(self, *args):
                events.append('translation')
                title, body, status, model = translate(*args)
                if len(claims)==1 and mode in ('clock','lost_clock_receipt','no_evidence'):
                    body=body.replace('10:00〜11:30','10:00〜12:30')
                if len(claims)==1 and mode in ('draft','lost_draft'):
                    body = '[対象]\n合成テキスト'  # Japanese summary and required sections missing
                return title, body, status, model

            def suggest_program_review(self, *, output, source, issues):
                events.append('suggest')
                if mode == 'ko_schedule':
                    return {'findings': []}
                index = next(i for i, v in enumerate(issues, 1) if v['rule']=='schedule_times')
                return {'findings':[dict(issue=index, decision='change', field='contentJa',
                    before='12:30', after='11:30', evidence='missing source excerpt' if mode=='no_evidence'
                    else '10월 3일 (토) 10:00~11:30, 총 3회')]}

            def release_terminated_attempt(self):
                events.append('release')

        def rpc(name, args):
            if name == 'admin_review_ai_queue':
                return {'hasMore': False, 'items': rows}
            if name == 'claim_myseoul_program_ai_no_retry':
                c = dict(packets[args['p_source_item_id']], workerId=args['p_worker_id'])
                if mode != 'missing_policy':
                    c['failurePolicy'] = {'policy':'no_retry', 'attempt':'b'*64}
                claims[c['jobId']] = c
                events.append('claim')
                return [c]
            c = claims[args['p_job_id']]
            for field, key in [('p_revision','revision'), ('p_worker_id','workerId'),
                               ('p_claimed_at','claimedAt'), ('p_lease_until','leaseUntil')]:
                self.assertEqual(args[field], c[key])
            if name == 'fail_myseoul_ai_no_retry':
                self.assertEqual(args['p_attempt'], c['failurePolicy']['attempt'])
                events.append('fail')
                if mode in ('lost_receipt','lost_clock_receipt'):
                    raise RpcAmbiguous()
                return 'queued' if mode == 'wrong_receipt' else 'failed'
            if name == 'fail_program_ai_with_draft':
                self.assertEqual(args['p_source'], c['source'])
                self.assertEqual(args['p_attempt'], c['failurePolicy']['attempt'])
                self.assertEqual(args['p_failure_detail']['stage'], 'japanese_validation')
                self.assertEqual(set(args['p_draft']), {'ko','ja','jaTitle'})
                self.assertIn('[주요 내용]', args['p_draft']['ko'])
                self.assertIn('合成テキスト', args['p_draft']['ja'])
                events.append('draft+fail')
                if mode=='lost_draft':
                    raise RpcAmbiguous()
                return 'failed'
            if name == 'finish_program_ai_candidate_review':
                self.assertEqual(args['p_source'], c['source'])
                self.assertEqual(args['p_facts_version'], c['factsVersion'])
                issues=args['p_review']['issues']
                if mode=='ko_schedule':
                    self.assertTrue(any(i['stage']=='korean_validation' for i in issues))
                else:
                    issue=next(i for i in issues if i['rule']=='schedule_times')
                    self.assertEqual((issue['expected'],issue['actual']), ([[600,690]],[[600,750]]))
                    if mode=='no_evidence':
                        self.assertEqual(issue['reviewOutcome'],'evidence_not_matched')
                        self.assertNotIn('after',issue)
                    else:
                        self.assertEqual((issue['before'],issue['after']),('12:30','11:30'))
                        self.assertIn(issue['evidence'],args['p_review']['source'])
                    self.assertIn('12:30',args['p_output']['contentJa'])
                events.append('review')
                if mode=='lost_clock_receipt':
                    raise RpcAmbiguous()
                return {'outcome':'inserted', 'candidateId': c['sourceItemId']}
            self.assertEqual(name, 'finish_myseoul_program_ai')
            events.append('finish')
            if mode == 'unknown_candidate':
                raise RpcAmbiguous()
            return {'outcome':'inserted', 'candidateId': c['sourceItemId']}

        with patch('socket.socket.connect', side_effect=AssertionError('unexpected network')):
            worker = ExistingWorkers('synthetic', ai_context=lambda: (ProgramAIAdapter(rpc), Pro(), lambda: None))
            return worker({'kind':'ai', 'source':'all', 'limit':'all'}), events

    def test_pro_stream_retains_completed_fields_before_schema_validation(self):
        import json
        from ingest.ai_provider import create_provider_adapter
        from ingest.myseoul_ai import process_myseoul_job
        from test_ingest_ai_chatgpt_plan import streamed, verified_session
        from test_ingest_ai_openai import response

        for incomplete in (False, True):
            with self.subTest(incomplete=incomplete):
                c = context()
                c['failurePolicy'] = {'policy':'no_retry', 'attempt':'c'*64}
                ko = '[한 줄 요약]\n체험 안내입니다.\n[주요 내용]\n문화 체험입니다.'
                summary = {'content_ko':ko, 'facts':dict.fromkeys(
                    ('audience','geo_age_income','amount_period_deadline','how_to_apply'),'공식 안내')}
                _, translate = providers(c)
                _, ja, _, _ = translate(c['title'],'진행 일정: 집결 안내: 3회')
                ja = ja.replace('11:30','12:30')
                translation = {'content_ja':ja}
                if not incomplete:
                    translation['title_ja']='家族体験'
                responses=[summary, translation]
                if not incomplete:
                    responses.append({'findings':[]})
                client=streamed([response(json.dumps(value, ensure_ascii=False)) for value in responses])
                pro=create_provider_adapter('chatgpt_plan', None, client=client, plan_session=verified_session())
                self.addCleanup(pro.close)
                calls=[]
                def rpc(name,args):
                    calls.append((name,args))
                    if name.startswith('claim_'):
                        return [c]
                    if name=='fail_program_ai_with_draft':
                        return 'failed'
                    if name=='finish_program_ai_candidate_review':
                        return {'candidateId':c['sourceItemId'],'outcome':'inserted'}
                    raise AssertionError(name)
                with patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
                    result=process_myseoul_job(ProgramAIAdapter(rpc), source_item_id=c['sourceItemId'],
                        revision=c['revision'],worker_id=c['workerId'],no_retry=True,
                        summarize_ko=pro.summarize_myseoul_ko,translate_ja=pro.translate_ja)
                self.assertEqual(len(calls),2)
                name,args=calls[-1]
                if incomplete:
                    self.assertEqual((name,result.termination_confirmed,len(client.calls)),
                                     ('fail_program_ai_with_draft',True,2))
                    self.assertEqual(args['p_draft']['ja'],ja)
                    self.assertEqual(set(args['p_draft']),{'ko','ja'})
                else:
                    self.assertEqual((name,result.completed,len(client.calls)),
                                     ('finish_program_ai_candidate_review',1,3))
                    self.assertIn('schedule_times',[issue['rule'] for issue in args['p_review']['issues']])

    def test_first_failure_receipt_allows_next_candidate(self):
        result, events = self.run_case('item')
        self.assertEqual(events, ['claim','summary','fail','release','claim','summary','translation','finish'])
        self.assertEqual((result['state'], result['counts']['failed'], result['counts']['completed'],
                          result['counts']['unprocessed']), ('partial',1,1,0))

    def test_advisory_outputs_can_continue_after_candidate_receipt(self):
        for mode in ('clock','ko_schedule','no_evidence'):
            with self.subTest(mode=mode):
                run, events=self.run_case(mode)
                self.assertEqual(run['counts']['completed'], 2)
                self.assertEqual(events,['claim','summary','translation','suggest','review',
                                         'claim','summary','translation','finish'])

    def test_authenticated_bridge_keeps_only_safe_diagnostics(self):
        from ingest.pc_worker_bridge import PcWorkerControl
        from test_pc_worker import PROJECT, ORIGIN, ACTOR, KEY, ticket
        run,_=self.run_case('lost_clock_receipt')
        command={'source':'all','kind':'ai','limit':'all'}
        control=PcWorkerControl(project=PROJECT,origin=ORIGIN,key=lambda:KEY,execute=lambda cmd:run,clock=lambda:1001)
        token=control.connect(ticket(control,actor=ACTOR))['token']
        control.submit(token,ticket(control,'run',cmd=command));control.wait()
        status=control.status(token)
        self.assertTrue(status['busy'])
        self.assertEqual(status['run']['failures'],run['failures'])

    def test_private_draft_and_terminal_receipt_are_one_write(self):
        for mode,confirmed in [('draft', True), ('lost_draft', False)]:
            run, events=self.run_case(mode)
            row,=run['failures']
            self.assertEqual((row['flow'],row['terminationConfirmed']),
                             ('continued' if confirmed else 'stopped', confirmed))
            self.assertEqual(events.count('claim'), 2 if confirmed else 1)
            self.assertEqual(events.count('draft+fail'), 1)
            self.assertNotIn('suggest',events)
            self.assertNotIn('合成テキスト', str(run))
        run, events=self.run_case('lost_clock_receipt')
        self.assertEqual(events, ['claim','summary','translation','suggest','review'])
        self.assertEqual(run['failures'][0]['stopStage'], 'candidate_completion')

    def test_stop_without_another_claim_or_write(self):
        for mode, code, events in [
                ('lost_receipt','state_unknown',['claim','summary','fail']),
                ('wrong_receipt','state_unknown',['claim','summary','fail']),
                ('auth','common_failure',['claim','summary','fail']),
                ('quota','common_failure',['claim','summary','fail']),
                ('unknown_ai','state_unknown',['claim','summary']),
                ('unknown_candidate','state_unknown',['claim','summary','translation','finish']),
                ('missing_policy','state_unknown',['claim'])]:
            with self.subTest(mode=mode):
                result, actual = self.run_case(mode)
                self.assertEqual((result['code'], result['counts']['unprocessed'], actual), (code,1,events))
                row,=result['failures']
                self.assertEqual(row['flow'],'stopped')
                self.assertEqual(row['terminationConfirmed'],mode in ('auth','quota'))
                self.assertEqual(row['stopStage'],{'unknown_candidate':'candidate_completion','missing_policy':'claim',
                    'lost_receipt':'failure_termination','wrong_receipt':'failure_termination'}.get(mode,'summary'))
