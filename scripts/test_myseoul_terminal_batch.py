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
                    if mode not in ('unknown_candidate', 'ok'):
                        raise AiJobError('ai_schema_error')
                return summarize(*args, **kwargs)

            def translate_ja(self, *args):
                events.append('translation')
                return translate(*args)

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
                if mode == 'lost_receipt':
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
