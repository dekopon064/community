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
                    if mode not in ('unknown_candidate', 'ok', 'clock', 'lost_clock_receipt', 'ko_schedule'):
                        raise AiJobError('ai_schema_error')
                body, status, model=summarize(*args, **kwargs)
                if len(claims)==1 and mode=='ko_schedule':
                    body+='\n[일정 안내]\n진행 일정: 10월 3일 (토) 10:00~12:30'
                return body, status, model

            def translate_ja(self, *args):
                events.append('translation')
                title, body, status, model = translate(*args)
                if len(claims)==1 and mode in ('clock','lost_clock_receipt'):
                    body=body.replace('10:00〜11:30','10:00〜12:30')
                return title, body, status, model

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
                if mode in ('clock','lost_clock_receipt'):
                    self.assertEqual(args['p_failure_detail'], dict(stage='japanese_validation',rule='schedule_times',
                        code='ai_schema_error',reason='missing',location={'field':'content_ja'},expected=[[600,690]],actual=[[600,750]]))
                if mode in ('lost_receipt','lost_clock_receipt'):
                    raise RpcAmbiguous()
                return 'queued' if mode == 'wrong_receipt' else 'failed'
            self.assertEqual(name, 'finish_myseoul_program_ai')
            events.append('finish')
            if mode == 'unknown_candidate':
                raise RpcAmbiguous()
            return {'outcome':'inserted', 'candidateId': c['sourceItemId']}

        with patch('socket.socket.connect', side_effect=AssertionError('unexpected network')):
            worker = ExistingWorkers('synthetic', ai_context=lambda: (ProgramAIAdapter(rpc), Pro(), lambda: None))
            return worker({'kind':'ai', 'source':'all', 'limit':'all'}), events

    def test_first_failure_receipt_allows_next_candidate(self):
        result, events = self.run_case('item')
        self.assertEqual(events, ['claim','summary','fail','release','claim','summary','translation','finish'])
        self.assertEqual((result['state'], result['counts']['failed'], result['counts']['completed'],
                          result['counts']['unprocessed']), ('partial',1,1,0))

    def test_korean_failure_has_comparison_before_translation(self):
        run, events=self.run_case('ko_schedule')
        row,=run['failures']
        self.assertEqual(row['detail']['stage'],'korean_validation')
        self.assertIn('expected',row['detail'])
        self.assertIn('actual',row['detail'])
        self.assertEqual(events,['claim','summary','fail','release','claim','summary','translation','finish'])

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

    def test_observed_difference_and_batch_decision(self):
        for mode,flow,confirmed in [('clock','continued',True),('lost_clock_receipt','stopped',False)]:
            run, events=self.run_case(mode)
            row,=run['failures']
            self.assertEqual((row['flow'],row['terminationConfirmed']), (flow,confirmed))
            self.assertEqual((row['detail']['expected'],row['detail']['actual']), ([[600,690]],[[600,750]]))
            self.assertEqual(row['stopStage'], None if confirmed else 'failure_termination')
            self.assertEqual(events.count('claim'), 2 if confirmed else 1)
            self.assertEqual(events.count('fail'), 1)

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
