"""Bilingual review candidates through the real worker with fake Pro and RPC."""
import copy
import json
import unittest
from unittest.mock import patch

from ingest.ai_provider import create_provider_adapter
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job
from ingest.reclassification_ai import assemble_reclassified_seoul, process_reclassified_job
from ingest.rpc_errors import RpcTimeout
from ingest.seoul_content import assemble_seoul_body
from test_ingest_ai_chatgpt_plan import streamed, verified_session
from test_ingest_ai_openai import response
from test_seoul_fact_roles import confirmed_case, fake_translation, replay_context


class CandidateReviewTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                     'ingest.supabase_store.create_ingest_client', 'ingest.chatgpt_plan_auth.authenticate_worker'):
            guard = patch(name, side_effect=AssertionError('real connection forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def run_worker(self, mode, classified=False):
        _, ctx = replay_context(classified)
        ctx['failurePolicy'] = {'policy': 'no_retry', 'attempt': 'f'*64}
        native = ctx['nativeConfirmedFacts']['programFacts'] if classified else ctx['facts']
        native['description'] += '\n합성 원문 근거: 시작 10:00'
        summary = copy.deepcopy(confirmed_case()['summary'])
        ko = (assemble_reclassified_seoul(summary['content_ko'], ctx) if classified
              else assemble_seoul_body(summary['content_ko'], native))
        ja = fake_translation(ko)
        if mode not in {'normal', 'missing'}:
            ja = ja.replace('| 10:00 |', '| 10:30 |', 1)
            self.assertIn('| 10:30 |', ja)
        translation = {'title_ja': '合成の解説', 'content_ja': ja}
        if mode == 'missing':
            del translation['title_ja']

        outcome = {'decision': 'change', 'field': 'contentJa', 'before': '| 10:30 |',
                   'after': '| 10:00 |', 'evidence': '합성 원문 근거: 시작 10:00'}
        if mode == 'equivalent':
            outcome['decision'] = 'equivalent'
        if mode == 'no_evidence':
            outcome['evidence'] = '없는 근거'
        client = streamed([response(json.dumps(summary, ensure_ascii=False)),
                           response(json.dumps(translation, ensure_ascii=False))])
        if mode == 'correction_unknown':
            client.events.append([])
        provider = create_provider_adapter('chatgpt_plan', None, client=client, plan_session=verified_session())
        self.addCleanup(provider.close)
        rpc_calls = []

        from ingest.chatgpt_plan_protocol import ProbeError, read_completed_stream

        def stream(client, request):
            if request['text']['format']['name'] == 'machimoa_seoul_candidate_review':
                packet = json.loads(request['input'][0]['content'])
                issue = next(i for i in packet['issues'] if i.get('location', {}).get('table') == 1)
                self.assertEqual(issue['expected'], ['time', 10, 0])
                self.assertNotIn('failurePolicy', packet)
                self.assertIn('합성 원문 근거: 시작 10:00', packet['officialSource'])
                if mode == 'usage_limit':
                    raise ProbeError('subscription_sharing_usage_limit_exceeded')
                if mode != 'correction_unknown':
                    proposal = response(json.dumps({'findings': [dict(outcome, issue=issue['issue'])]}, ensure_ascii=False))
                    client.events.append(streamed([proposal]).events[0])
            return read_completed_stream(client, request)

        def rpc(name, args):
            rpc_calls.append((name, args))
            if name.startswith('claim_'):
                return ctx if classified else [ctx]
            if name.startswith('finish_'):
                if mode == 'save_unknown':
                    raise RpcTimeout()
                return {'candidateId': ctx['sourceItemId'], 'outcome': 'inserted'}
            if name.startswith('fail_'):
                return 'failed'
            if name == 'reclassified_content_ai_status':
                return {'status': 'active'}
            raise AssertionError(name)

        kwargs = dict(source_item_id=ctx['sourceItemId'], revision=ctx['revision'], worker_id=ctx['workerId'],
                      summarize_ko=provider.summarize_program_ko, translate_ja=provider.translate_ja, no_retry=True)
        with patch('ingest.ai_chatgpt_plan.read_completed_stream', side_effect=stream):
            if classified:
                result = process_reclassified_job(ProgramAIAdapter(rpc), classification_version=ctx['classificationVersion'], **kwargs)
            else:
                result = process_seoul_program_job(ProgramAIAdapter(rpc), **kwargs)
        return result, rpc_calls, client.calls

    def test_normal_and_review_candidates_through_both_workers(self):
        for classified in (False, True):
            with self.subTest(classified=classified):
                result, rpc, calls = self.run_worker('normal', classified)
                self.assertEqual(result.completed, 1)
                self.assertEqual(len(calls), 2)
                self.assertIn(rpc[1][0], ('finish_seoul_program_ai', 'finish_reclassified_content_ai'))
                result, rpc, calls = self.run_worker('change', classified)
                self.assertEqual(result.completed, 1)
                self.assertEqual(len(calls), 3)
                name, args = rpc[1]
                self.assertEqual(name, 'finish_seoul_ai_candidate_review')
                self.assertEqual(args['p_mode'], 'classification' if classified else 'program')
                self.assertIn('| 10:30 |', args['p_output']['contentJa'])
                review = args['p_review']
                changed = [i for i in review['issues'] if i['disposition'] == 'change']
                self.assertEqual(len(changed), 1)
                self.assertEqual(changed[0]['after'], '| 10:00 |')

    def test_equivalent_and_unsupported_findings_keep_the_original(self):
        for mode, status in [('equivalent', 'equivalent'), ('no_evidence', 'needs_review')]:
            result, rpc, calls = self.run_worker(mode)
            self.assertEqual((result.completed, len(calls)), (1, 3))
            issue = rpc[1][1]['p_review']['issues'][0]
            self.assertEqual(issue['disposition'], status)
            self.assertNotIn('before', issue)

    def test_missing_required_result_stays_a_private_draft(self):
        result, rpc, calls = self.run_worker('missing')
        self.assertEqual((result.failed, len(calls)), (1, 2))
        self.assertTrue(result.termination_confirmed)
        self.assertEqual(rpc[1][0], 'fail_seoul_ai_with_draft')

    def test_unknown_pro_or_save_response_never_creates_a_second_write(self):
        result, rpc, calls = self.run_worker('correction_unknown')
        self.assertEqual((result.state_unknown, len(calls), len(rpc)), (1, 3, 1))
        for classified in (False, True):
            result, rpc, calls = self.run_worker('save_unknown', classified)
            self.assertEqual((result.state_unknown, len(calls), len(rpc)), (1, 3, 2))

    def test_pro_usage_limit_during_correction_stops_the_batch(self):
        for classified in (False, True):
            result, rpc, calls = self.run_worker('usage_limit', classified)
            self.assertEqual((result.error_code, result.failure_scope), ('ai_http_429', 'batch'))
            self.assertTrue(result.termination_confirmed)
            self.assertEqual(len(calls), 2)  # The synthetic quota refusal happens before opening a third stream.
            self.assertEqual(rpc[1][0], 'fail_seoul_ai_no_retry')
            self.assertEqual(len(rpc), 2)
