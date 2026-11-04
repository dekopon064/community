"""Preserved failure excerpts + explicitly synthetic context/Pro/RPC; no live IO."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ingest.ai_errors import ValidationError
from ingest.ai_provider import create_provider_adapter
from ingest.chatgpt_plan_protocol import ProbeError, read_completed_stream
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job
from ingest.reclassification_ai import assemble_reclassified_seoul, process_reclassified_job
from ingest.rpc_errors import RpcTimeout
from ingest.seoul_candidate_review import SeoulCandidateReview
from ingest.seoul_content import assemble_seoul_body
from test_ingest_ai_chatgpt_plan import streamed, verified_session
from test_ingest_ai_openai import response
from test_seoul_content import fake_japanese
from test_seoul_fact_roles import confirmed_case, replay_context

CASES = json.loads((Path(__file__).parent / 'testdata/seoul_fee_clock_failure_excerpts.json').read_text(encoding='utf-8'))['cases']


def fixture(case, classified=False):
    _, ctx = replay_context(classified)
    ctx['failurePolicy'] = {'policy': 'no_retry', 'attempt': 'f' * 64}
    facts = ctx['nativeConfirmedFacts']['programFacts'] if classified else ctx['facts']
    facts.update(description='합성 프로그램 설명\n' + case['source'], conditions=[],
                 fee_kind=case['fee_kind'], fee_amounts=[])
    if classified:
        ctx['body'] = facts['description']
    summary = copy.deepcopy(confirmed_case()['summary'])
    summary['content_ko'] = ('[한 줄 요약]\n합성 프로그램입니다.\n[주요 내용]\n체험 프로그램입니다.\n'
                             '[일정 안내]\n공식 일정 안내입니다.\n[신청 방법]\n인터넷 예약을 이용하세요.')
    summary['content_ko'] = summary['content_ko'].replace('[' + case['section'] + ']',
        '[' + case['section'] + ']\n' + case['response'])
    return ctx, facts, summary


class FeeClockReviewTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                     'ingest.supabase_store.create_ingest_client', 'ingest.chatgpt_plan_auth.authenticate_worker'):
            guard = patch(name, side_effect=AssertionError('real IO forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def worker(self, case, classified=False, mode='equivalent'):
        ctx, facts, summary = fixture(case, classified)
        before = copy.deepcopy(ctx)
        if mode in ('missing_summary', 'failure_unknown'):
            del summary['facts']['audience']
        if mode == 'bad_markdown':
            summary['content_ko'] += '\n<script>not public</script>'
        client = streamed([])
        client.events.clear()  # FakeClient otherwise supplies its default sample.
        provider = create_provider_adapter('chatgpt_plan', None, client=client, plan_session=verified_session())
        self.addCleanup(provider.close)
        requests, rpc_calls = [], []

        def stream(client, request):
            name = request['text']['format']['name']
            requests.append(name)
            if name == 'machimoa_summary':
                payload = summary
            elif name == 'machimoa_translation':
                content = request['input'][0]['content'].split('content_ko:\n', 1)[1]
                self.assertIn(case['response'], content)
                payload = {'title_ja': '合成プログラム', 'content_ja': fake_japanese(content)}
                if mode == 'missing_translation':
                    del payload['title_ja']
            else:
                self.assertEqual(name, 'machimoa_seoul_candidate_review')
                packet = json.loads(request['input'][0]['content'])
                self.assertIn(case['source'], packet['officialSource'])
                self.assertNotIn(ctx['failurePolicy']['attempt'], json.dumps(packet))
                issue = next(i for i in packet['issues'] if i['stage'] == 'korean_validation' and i['rule'] == case['rule'])
                if mode == 'auth':
                    raise ProbeError('plan_http_401')
                if mode == 'quota':
                    raise ProbeError('subscription_sharing_usage_limit_exceeded')
                if mode == 'response_unknown':
                    raise ProbeError('stream_missing_completed')
                decision = mode if mode in ('change', 'needs_review') else 'equivalent'
                payload = {'findings': [dict(issue=issue['issue'], decision=decision,
                    evidence=case['source'].splitlines()[0], field='contentKo',
                    before=case['response'], after=case.get('corrected', case['response']))]}
            client.events.append(streamed([response(json.dumps(payload, ensure_ascii=False))]).events[0])
            return read_completed_stream(client, request)

        def rpc(name, args):
            rpc_calls.append((name, copy.deepcopy(args)))
            if name.startswith('claim_'):
                claim = copy.deepcopy(ctx)
                if mode == 'stale':
                    claim['revision'] = 'b' * 64
                if mode == 'forbidden':
                    raise PermissionError('synthetic permission refusal')
                if mode == 'existing':
                    return None if classified else []
                return claim if classified else [claim]
            if name == 'reclassified_content_ai_status':
                return {'status': 'active'}
            for key, param in [('jobId', 'p_job_id'), ('claimedAt', 'p_claimed_at'),
                               ('leaseUntil', 'p_lease_until'), ('workerId', 'p_worker_id')]:
                self.assertEqual(args[param], ctx[key])
            if name == 'finish_seoul_ai_candidate_review':
                self.assertEqual(args['p_revision'], ctx['revision'])
                self.assertEqual(args['p_input_version'], ctx['classificationVersion' if classified else 'factsVersion'])
                self.assertEqual(args['p_mode'], 'classification' if classified else 'program')
                if mode == 'save_unknown':
                    raise RpcTimeout()
                return {'candidateId': ctx['sourceItemId'], 'outcome': 'inserted'}
            if name.startswith('fail_'):
                self.assertEqual(args['p_attempt'], ctx['failurePolicy']['attempt'])
                if mode == 'failure_unknown':
                    raise RpcTimeout()
                return 'failed'
            raise AssertionError(name)

        kwargs = dict(source_item_id=ctx['sourceItemId'], revision=ctx['revision'], worker_id=ctx['workerId'],
            summarize_ko=provider.summarize_program_ko, translate_ja=provider.translate_ja, no_retry=True)
        with patch('ingest.ai_chatgpt_plan.read_completed_stream', side_effect=stream):
            if classified:
                result = process_reclassified_job(ProgramAIAdapter(rpc), classification_version=ctx['classificationVersion'], **kwargs)
            else:
                result = process_seoul_program_job(ProgramAIAdapter(rpc), **kwargs)
        self.assertEqual(ctx, before)
        return result, requests, rpc_calls

    def test_four_preserved_excerpts_reproduce_strict_failure(self):
        for case in CASES:
            for classified in (False, True):
                with self.subTest(case=case['name'], classified=classified):
                    ctx, facts, summary = fixture(case, classified)
                    with self.assertRaises(ValidationError) as raised:
                        if classified:
                            assemble_reclassified_seoul(summary['content_ko'], ctx)
                        else:
                            assemble_seoul_body(summary['content_ko'], facts)
                    self.assertEqual(raised.exception.diagnostic['rule'], case['rule'])

    def test_all_four_reach_private_candidate_through_both_real_workers(self):
        for case in CASES:
            for classified in (False, True):
                with self.subTest(case=case['name'], classified=classified):
                    result, requests, calls = self.worker(case, classified)
                    self.assertEqual((result.completed, result.failed), (1, 0), result)
                    self.assertEqual(requests, ['machimoa_summary', 'machimoa_translation', 'machimoa_seoul_candidate_review'])
                    args = next(args for name, args in calls if name == 'finish_seoul_ai_candidate_review')
                    self.assertIn(case['response'], args['p_output']['contentKo'])
                    issues = [i for i in args['p_review']['issues'] if i['rule'] == case['rule']]
                    self.assertTrue(issues)
                    self.assertTrue(any(i['disposition'] == 'equivalent' for i in issues))
                    self.assertFalse(any('before' in i for i in issues))
                    self.assertFalse(any(name.startswith('fail_') for name, _ in calls))

    def test_real_fee_difference_gets_change_proposal_without_overwriting_candidate(self):
        case = dict(CASES[1], response='입장료 2,000원은 개인 부담입니다.', corrected='입장료 1,000원은 개인 부담입니다.')
        for classified in (False, True):
            result, _, calls = self.worker(case, classified, 'change')
            self.assertEqual(result.completed, 1)
            args = next(args for name, args in calls if name == 'finish_seoul_ai_candidate_review')
            change = next(i for i in args['p_review']['issues'] if i['disposition'] == 'change')
            self.assertEqual((change['before'], change['after']), (case['response'], case['corrected']))
            self.assertEqual(change['actual'], [['2000'], False])
            self.assertIn(case['response'], args['p_output']['contentKo'])

    def test_unsupported_clock_is_flagged_not_normalized_or_accepted(self):
        case = dict(CASES[3], response=CASES[3]['response'].replace('24:00', '25:00'))
        result, _, calls = self.worker(case, mode='needs_review')
        self.assertEqual(result.completed, 1)
        args = next(args for name, args in calls if name == 'finish_seoul_ai_candidate_review')
        self.assertIn('25:00', args['p_output']['contentKo'])
        self.assertTrue(any(i['rule'] == 'clock' and i['actual'][0] == 25 and i['disposition'] == 'needs_review'
                            for i in args['p_review']['issues']))

    def test_missing_required_output_still_terminates_and_retains_private_draft(self):
        for mode, count in [('missing_summary', 1), ('missing_translation', 2), ('bad_markdown', 1)]:
            for classified in (False, True):
                result, requests, calls = self.worker(CASES[1], classified, mode)
                self.assertEqual((result.failed, len(requests)), (1, count), (mode, result))
                self.assertTrue(result.termination_confirmed)
                self.assertEqual(calls[-1][0], 'fail_seoul_ai_with_draft')

    def test_claim_protection_and_existing_candidate_skip_make_no_ai_call(self):
        for mode in ('stale', 'forbidden', 'existing'):
            for classified in (False, True):
                result, requests, calls = self.worker(CASES[0], classified, mode)
                self.assertEqual(requests, [])
                self.assertEqual(len(calls), 1)
                self.assertEqual(result.completed, 0)

    def test_common_and_unknown_errors_do_not_fall_through_to_candidate(self):
        for mode in ('auth', 'quota', 'response_unknown', 'save_unknown'):
            for classified in (False, True):
                result, requests, calls = self.worker(CASES[0], classified, mode)
                self.assertEqual(result.completed, 0)
                self.assertEqual(len(requests), 3)
                if mode in ('auth', 'quota'):
                    self.assertEqual(result.failure_scope, 'batch')
                    self.assertTrue(result.termination_confirmed)
                else:
                    self.assertEqual(result.state_unknown, 1)
                    self.assertFalse(any(name.startswith('fail_') for name, _ in calls))
                self.assertLessEqual(sum(name.startswith('finish_') for name, _ in calls), 1)

    def test_batch_continues_only_after_confirmed_item_completion(self):
        from ingest.seoul_workflow import process_ready_targets
        for mode in ('equivalent', 'missing_summary', 'auth', 'quota', 'response_unknown', 'save_unknown', 'failure_unknown'):
            counts = dict(completed=0, failed=0, unavailable_skipped=0, state_unknown=0, unprocessed=0)
            targets = [dict(sourceItemId=str(i), revision='a' * 64) for i in range(2)]
            visited = []
            def process(item):
                visited.append(item['sourceItemId'])
                result, _, calls = self.worker(CASES[0], mode=mode if len(visited) == 1 else 'equivalent')
                if mode == 'missing_summary' and len(visited) == 1:
                    self.assertTrue(result.termination_confirmed)
                    self.assertEqual(calls[-1][0], 'fail_seoul_ai_with_draft')
                return result
            result = process_ready_targets(targets, counts, process, policy_for=lambda _: (True, None, None))
            stops = mode not in ('equivalent', 'missing_summary')
            self.assertEqual(result['batch_stopped'], stops)
            self.assertEqual(result['unprocessed'], int(stops))
            self.assertEqual(len(visited), 1 if stops else 2)

    def test_fee_diagnostic_keeps_both_comparison_values_without_raw_text(self):
        from ingest.myseoul_content import validate_summary_fees
        with self.assertRaises(ValidationError) as raised:
            validate_summary_fees('입장료 2,000원입니다. PRIVATE_SENTINEL', '입장료: 1,000원')
        diagnostic = raised.exception.diagnostic
        self.assertEqual(diagnostic['expected'], [['1000'], False])
        self.assertEqual(diagnostic['actual'], [['2000'], False])
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(diagnostic))

    def test_cleanup_never_swallows_structural_or_common_errors(self):
        _, facts, summary = fixture(CASES[0])
        common = ValidationError('reviewed_fee', 'missing_or_mismatched')
        common.failure_scope = 'batch'
        for error in (ValidationError('reviewed_section', 'missing_or_mismatched'), common,
                      RpcTimeout(), RuntimeError('synthetic internal failure')):
            review = SeoulCandidateReview(None)
            with patch('ingest.seoul_content.deduplicate_summary_fees', side_effect=error):
                with self.assertRaises(type(error)) as raised:
                    assemble_seoul_body(summary['content_ko'], facts, review=review)
            self.assertIs(raised.exception, error)


if __name__ == '__main__':
    unittest.main()
