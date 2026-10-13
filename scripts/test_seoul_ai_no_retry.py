"""Actual workers with fake Pro/auth/RPC only; all real connections fail."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from ingest.ai_errors import AiJobError
from ingest.ai_provider import create_provider_adapter
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job
from ingest.reclassification_ai import process_reclassified_job
from ingest.rpc_errors import RpcTimeout
from ingest.seoul_content import assemble_seoul_body
from ingest.seoul_workflow import process_seoul_queue
from test_seoul_fact_roles import replay_context, confirmed_case, fake_translation
from test_ingest_ai_chatgpt_plan import verified_session, streamed
from test_ingest_ai_openai import response
from test_reclassification_ai import context as other_source_context


class NoRetryTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                     'ingest.supabase_store.create_ingest_client', 'ingest.chatgpt_plan_auth.authenticate_worker'):
            guard = patch(name, side_effect=AssertionError('real connection forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def replay(self, classified=False, mode='success', no_retry=True):
        _, c = replay_context(classified)
        c['failurePolicy'] = {'policy': 'no_retry', 'attempt': 'f'*64}
        original = copy.deepcopy(c)
        summary = copy.deepcopy(confirmed_case()['summary'])
        native = c['nativeConfirmedFacts']['programFacts'] if classified else c['facts']
        assembled = assemble_seoul_body(summary['content_ko'], native)
        japanese = {'title_ja': '合成の解説', 'content_ja': fake_translation(assembled)}
        if mode == 'ko_error': summary = {'content_ko': 'invalid'}
        if mode == 'ko_validation': summary['content_ko'] = summary['content_ko'].replace('10:00', '09:00')
        if mode == 'ja_error': japanese = {'title_ja': '合成', 'content_ja': 'invalid'}
        client = streamed([response(json.dumps(summary, ensure_ascii=False)),
                           response(json.dumps(japanese, ensure_ascii=False))])
        provider = create_provider_adapter('chatgpt_plan', None, client=client, plan_session=verified_session())
        events, calls = [], []
        def ko(body, url, title):
            calls.append('summary')
            if mode == 'ko_unknown': raise TimeoutError('secret transport text')
            return provider.summarize_program_ko(body, url, title=title)
        def ja(title, body):
            calls.append('translation')
            self.assertIn('| 10:00 |', body)
            return provider.translate_ja(title, body)
        def rpc(name, args):
            events.append((name, copy.deepcopy(args)))
            if name in {'claim_seoul_program_ai_no_retry', 'claim_seoul_program_ai'}:
                return [c]
            if name in {'claim_seoul_reclassified_ai_no_retry', 'claim_reclassified_content_ai'}:
                return c
            if name.startswith('finish_'):
                if mode == 'finish_unknown': raise RpcTimeout()
                if mode == 'finish_malformed': return {'outcome': 'inserted'}
                return {'outcome': 'inserted', 'candidateId': c['sourceItemId']}
            if name == 'fail_seoul_ai_no_retry':
                if mode == 'fail_unknown': raise RpcTimeout()
                self.assertEqual(args['p_attempt'], c['failurePolicy']['attempt'])
                self.assertEqual(args['p_revision'], c['revision'])
                return 'failed'
            if name == 'fail_seoul_program_ai': return 'queued'
            if name == 'reclassified_content_ai_status': return {'status': 'active', 'candidateId': None}
            raise AssertionError(name)
        if mode == 'fail_unknown':
            def ko(body, url, title):
                calls.append('summary'); raise AiJobError('ai_schema_error')
        try:
            kwargs = dict(source_item_id=c['sourceItemId'], revision=c['revision'],
                          worker_id=c['workerId'], summarize_ko=ko, translate_ja=ja, no_retry=no_retry)
            if classified:
                result = process_reclassified_job(ProgramAIAdapter(rpc), classification_version=c['classificationVersion'], **kwargs)
            else:
                result = process_seoul_program_job(ProgramAIAdapter(rpc), **kwargs)
            self.assertEqual(c, original, 'worker preserves current facts/claim input')
            self.assertLessEqual(len(client.calls), 2)
            self.assertTrue(all(x['model'] == 'gpt-6.1-sol' for x in client.calls))
            self.assertNotIn(c['failurePolicy']['attempt'], json.dumps(client.calls))
            return result, events, calls, len(client.calls)
        finally:
            provider.close()

    def test_fake_pro_success_uses_existing_fenced_completion(self):
        for classified in (False, True):
            r, e, calls, count = self.replay(classified)
            self.assertEqual((r.completed, r.failed, r.retried), (1, 0, 0))
            self.assertEqual(calls, ['summary', 'translation']); self.assertEqual(count, 2)
            self.assertEqual(len(e), 2); self.assertTrue(e[0][0].endswith('no_retry'))
            self.assertTrue(e[1][0].startswith('finish_'))

    def test_known_summary_failure_no_translation_or_candidate(self):
        for classified in (False, True):
            r, e, calls, count = self.replay(classified, 'ko_error')
            self.assertEqual((r.failed, r.retried, r.completed), (1, 0, 0))
            self.assertEqual(r.failure_scope, 'item')
            self.assertEqual(r.failure_stage, 'summary')
            self.assertEqual(calls, ['summary']); self.assertEqual(count, 1)
            self.assertEqual([x[0] for x in e][1:], ['fail_seoul_ai_no_retry'])

    def test_schedule_validation_failure_before_translation(self):
        for classified in (False, True):
            r, e, calls, count = self.replay(classified, 'ko_validation')
            self.assertEqual((r.failed, r.retried, r.completed), (1, 0, 0))
            self.assertEqual(r.failure_scope, 'item')
            self.assertEqual(r.failure_stage, 'korean_validation')
            self.assertEqual(calls, ['summary']); self.assertEqual(count, 1)
            self.assertEqual(e[-1][0], 'fail_seoul_ai_no_retry')

    def test_known_translation_failure_is_terminal(self):
        for classified in (False, True):
            r, e, calls, count = self.replay(classified, 'ja_error')
            self.assertEqual((r.failed, r.retried, r.completed), (1, 0, 0))
            self.assertEqual(r.failure_scope, 'item')
            self.assertEqual(calls, ['summary', 'translation']); self.assertEqual(count, 2)
            self.assertEqual(e[-1][0], 'fail_seoul_ai_no_retry')

    def test_unknown_response_never_becomes_failed_or_retried(self):
        for classified in (False, True):
            for mode in ('ko_unknown', 'finish_unknown', 'finish_malformed', 'fail_unknown'):
                r, e, calls, count = self.replay(classified, mode)
                self.assertEqual((r.state_unknown, r.retried, r.failed), (1, 0, 0))
                self.assertEqual(r.failure_scope, 'batch')
                self.assertNotIn('fail_seoul_program_ai', [n for n, _ in e])
                self.assertEqual(sum(n == 'fail_seoul_ai_no_retry' for n, _ in e), int(mode == 'fail_unknown'))
                self.assertEqual(sum(n.startswith('finish_') for n, _ in e), int(mode.startswith('finish')))
                self.assertLessEqual(calls.count('summary'), 1); self.assertLessEqual(calls.count('translation'), 1)

    def test_default_behaviors_remain(self):
        r, e, _, _ = self.replay(False, 'ko_error', no_retry=False)
        self.assertEqual(r.retried, 1); self.assertEqual(e[-1][0], 'fail_seoul_program_ai')
        r, e, _, _ = self.replay(True, 'ko_error', no_retry=False)
        self.assertEqual(r.state_unknown, 1); self.assertEqual(e[-1][0], 'reclassified_content_ai_status')

    def test_missing_policy_or_other_source_cannot_call_provider(self):
        for classified in (False, True):
            for policy in (None, {'policy': 'existing', 'attempt': 'f'*64}, {'policy': 'no_retry', 'attempt': 'bad'}):
                _, c = replay_context(classified); c['failurePolicy'] = policy
                events = []
                def rpc(name, args): events.append(name); return c if classified else [c]
                def forbidden(*a, **k): raise AssertionError('provider not authorized')
                kwargs = dict(source_item_id=c['sourceItemId'], revision=c['revision'], worker_id=c['workerId'],
                              summarize_ko=forbidden, translate_ja=forbidden, no_retry=True)
                r = process_reclassified_job(ProgramAIAdapter(rpc), classification_version=c['classificationVersion'], **kwargs) if classified else process_seoul_program_job(ProgramAIAdapter(rpc), **kwargs)
                self.assertEqual(r.state_unknown, 1); self.assertEqual(len(events), 1)
        c = other_source_context(); c['failurePolicy'] = {'policy': 'no_retry', 'attempt': 'f'*64}
        r = process_reclassified_job(ProgramAIAdapter(lambda n, a: c), source_item_id=c['sourceItemId'],
            revision=c['revision'], classification_version=1, worker_id=c['workerId'],
            summarize_ko=forbidden, translate_ja=forbidden, no_retry=True)
        self.assertEqual(r.state_unknown, 1)

    def test_cli_explicit_option_and_validation_only(self):
        from run_seoul_program_ai import main as normal
        from run_reclassified_content_ai import main as classified
        base = ['--project-ref', 'a'*20, '--source-item-id', '00000000-0000-4000-8000-000000000002', '--revision', 'a'*64]
        for entry, args in ((normal, base), (classified, base+['--classification-version', '1'])):
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(entry(args+['--no-retry']), 0)
            value = json.loads(out.getvalue()); self.assertEqual(value['failure_policy'], 'no_retry')
            self.assertEqual(value['network_calls'], 0)
            seen = []
            def execute(args):
                from ingest.ai_worker import AiWorkerResult
                seen.append(args.no_retry); return AiWorkerResult(status='processed', claimed=1, failed=1)
            with redirect_stdout(io.StringIO()): self.assertEqual(entry(args+['--execute', '--no-retry'], execute=execute), 1)
            self.assertEqual(seen, [True])

    def test_bounded_queue_continues_after_acknowledged_item_failure(self):
        _, c = replay_context(); c['failurePolicy'] = {'policy': 'no_retry', 'attempt': 'f'*64}
        item = dict(sourceName='seoul_reservation', status='queued', currentRevision=True, leaseState='none',
                    retryCount=0, nextRetryAt=None, sourceItemId=c['sourceItemId'], revision=c['revision'])
        second = {**item, 'sourceItemId': '00000000-0000-4000-8000-000000000004'}
        events = []
        def rpc(n, a):
            events.append(n)
            if n == 'admin_review_ai_queue': return {'items': [item, second], 'hasMore': False}
            if n == 'claim_seoul_program_ai_no_retry':
                current=copy.deepcopy(c);current['sourceItemId']=a['p_source_item_id'];return [current]
            if n == 'fail_seoul_ai_no_retry': return 'failed'
            raise AssertionError(n)
        def fail(*a, **k): raise AiJobError('ai_schema_error')
        r = process_seoul_queue(ProgramAIAdapter(rpc), max_jobs=2, queue_pages=1,
            summarize_ko=fail, translate_ja=fail, worker_id=c['workerId'], no_retry=True)
        self.assertEqual((r['failed'], r['unprocessed']), (2, 0))
        self.assertFalse(r['batch_stopped'])
        self.assertEqual(events, ['admin_review_ai_queue', 'claim_seoul_program_ai_no_retry',
            'fail_seoul_ai_no_retry', 'claim_seoul_program_ai_no_retry', 'fail_seoul_ai_no_retry'])


if __name__ == '__main__': unittest.main()
