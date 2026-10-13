"""Recorded responses through real validation/worker and fake Pro/RPC only.

Text is from the permitted prior call; no response is regenerated here. All
identity/fence values are synthetic, and sockets/auth/DB construction are blocked.
"""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from ingest.ai_errors import AiJobError
from ingest.ai_provider import create_provider_adapter
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job
from ingest.reclassification_ai import process_reclassified_job
from ingest.translation_validation import validate_translation_fidelity
from test_ingest_ai_chatgpt_plan import verified_session, streamed
from test_ingest_ai_openai import response
from test_reclassification_ai import context as classified_context

FIXTURE = Path(__file__).parent / 'testdata/seoul_per_session_recorded.json'


def recorded_case(classified=False):
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    c = copy.deepcopy(data['context'])
    now = datetime.now(timezone.utc)
    c.update(claimedAt=now.isoformat(), leaseUntil=(now + timedelta(seconds=600)).isoformat())
    for key in ('claimedAt', 'leaseUntil', 'workerId'):
        c['filterContext'][key] = c[key]
        if c.get('activityConfirmation'):
            c['activityConfirmation'][key] = c[key]
    if classified:
        native = c
        c = classified_context('program', 'seoul_reservation')
        c.update(sourceItemId=native['sourceItemId'], jobId=native['jobId'], revision=native['revision'],
                 workerId=native['workerId'], claimedAt=native['claimedAt'], leaseUntil=native['leaseUntil'],
                 title=native['title'], body=native['facts']['description'], sourceUrl=native['facts']['official_url'])
        c['filters'] = copy.deepcopy(native['filterContext']['data'])
        c['facts'].update(delivery='offline', scope='unknown', regions=[], evidence='',
                          deadlineOn=c['filters']['application']['value']['end']['value'][:10])
        c['nativeConfirmedFacts']['programFacts'] = copy.deepcopy(native['facts'])
    return data, c


def run_recorded(test, *, classified=False, change=None, finish_unknown=False, claim_change=None):
    data, c = recorded_case(classified)
    expected = copy.deepcopy(c)
    if claim_change:
        claim_change(c)
    before = copy.deepcopy(c)
    japanese = copy.deepcopy(data['translation'])
    if change:
        japanese = change(japanese)
    client = streamed([response(json.dumps(data['summary'], ensure_ascii=False)),
                       response(json.dumps(japanese, ensure_ascii=False))])
    with patch('ingest.chatgpt_plan_auth.authenticate_worker', side_effect=AssertionError('real auth forbidden')):
        provider = create_provider_adapter('chatgpt_plan', None, client=client, plan_session=verified_session())
    calls, output = [], {}
    def rpc(name, args):
        calls.append((name, copy.deepcopy(args)))
        if name == ('claim_reclassified_content_ai' if classified else 'claim_seoul_program_ai'):
            return c if classified else [c]
        if name == ('finish_reclassified_content_ai' if classified else 'finish_seoul_program_ai'):
            test.assertEqual(args['p_revision'], c['revision'])
            for key in ('claimedAt', 'leaseUntil', 'workerId', 'jobId'):
                param = {'claimedAt': 'p_claimed_at', 'leaseUntil': 'p_lease_until',
                         'workerId': 'p_worker_id', 'jobId': 'p_job_id'}[key]
                test.assertEqual(args[param], c[key])
            test.assertEqual(args.get('p_classification_version', args.get('p_facts_version')),
                             c.get('classificationVersion', c.get('factsVersion')))
            if finish_unknown:
                raise TimeoutError('synthetic unknown completion')
            output.update(args['p_output'])
            return {'candidateId': c['sourceItemId'], 'outcome': 'inserted'}
        if name == 'fail_seoul_program_ai':
            return 'failed'  # Fake terminal failure only, never a queued retry.
        if name == 'reclassified_content_ai_status':
            test.assertFalse(args['p_close_expired'])
            return {'status': 'active'}
        raise AssertionError(name)
    try:
        kwargs = dict(source_item_id=expected['sourceItemId'], revision=expected['revision'], worker_id=expected['workerId'],
                      summarize_ko=provider.summarize_ko if classified else provider.summarize_program_ko,
                      translate_ja=provider.translate_ja)
        result = (process_reclassified_job(ProgramAIAdapter(rpc), classification_version=expected['classificationVersion'], **kwargs)
                  if classified else process_seoul_program_job(ProgramAIAdapter(rpc), **kwargs))
        test.assertEqual(c, before)
        test.assertEqual(result.retried, 0)
        test.assertLessEqual(len(client.calls), 2)
        return result, calls, output, client.calls, data
    finally:
        provider.close()


class RecordedPerSessionTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                       'ingest.supabase_store.create_ingest_client', 'ingest.chatgpt_plan_auth.authenticate_worker'):
            guard = patch(target, side_effect=AssertionError('real connection forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def test_prior_misread_is_reproduced_without_changing_recorded_output(self):
        data, _ = recorded_case()
        source = data['expected_translation_input']
        target = data['translation']
        raw = FIXTURE.read_bytes()
        # Reintroduce exactly the erroneous interpretation: count the 1回
        # denominator as an ordinary total. No prompt hash/text-only proof.
        with patch('ingest.translation_validation._without_per_session', side_effect=lambda text, **kwargs: text):
            with self.assertRaises(AiJobError):
                validate_translation_fidelity(source['title_ko'], source['content_ko'], target['title_ja'], target['content_ja'])
        validate_translation_fidelity(source['title_ko'], source['content_ko'], target['title_ja'], target['content_ja'])
        self.assertEqual(FIXTURE.read_bytes(), raw)

    def test_recorded_pair_reaches_normal_and_reclassified_fake_candidate(self):
        for classified in (False, True):
            with self.subTest(classified=classified):
                result, calls, output, requests, data = run_recorded(self, classified=classified)
                self.assertEqual(result.completed, 1)
                self.assertEqual([n for n, _ in calls], ['claim_reclassified_content_ai', 'finish_reclassified_content_ai']
                                 if classified else ['claim_seoul_program_ai', 'finish_seoul_program_ai'])
                self.assertEqual(output['contentKo'], data['expected_translation_input']['content_ko'])
                self.assertEqual(output['contentJa'], data['translation']['content_ja'])
                self.assertEqual(output['titleJa'], data['translation']['title_ja'])
                self.assertEqual(set(output), {'titleKo', 'titleJa', 'summaryKo', 'summaryJa', 'contentKo', 'contentJa', 'aiModel'})
                self.assertEqual(output['aiModel'], 'gpt-6.1-sol')
                self.assertEqual(len(requests), 2)
                self.assertEqual(requests[1]['input'][0]['content'],
                                 'title_ko: '+output['titleKo']+'\ncontent_ko:\n'+output['contentKo'])
                for request in requests:
                    self.assertEqual(request['model'], 'gpt-6.1-sol')
                    self.assertTrue(request['text']['format']['strict'])
                    self.assertFalse(request['store'])
                self.assertIn('5일 전까지', output['contentKo'])
                self.assertIn('2일 전까지', output['contentKo'])
                self.assertIn('9家族', output['contentJa'])

    def test_wrong_session_denominator_capacity_family_date_or_condition_never_finishes(self):
        changes = [
            lambda d: {**d, 'content_ja': d['content_ja'].replace('1回につき', '2回につき')},
            lambda d: {**d, 'content_ja': d['content_ja'].replace('20名', '21名')},
            lambda d: {**d, 'content_ja': d['content_ja'].replace('9家族', '8家族')},
            lambda d: {**d, 'content_ja': d['content_ja'].replace('10月31日（土）14時00分', '10月31日（土）13時00分')},
            lambda d: {**d, 'content_ja': d['content_ja'].replace('翌月の予約はできません', '翌月の予約もできます')},
        ]
        for classified in (False, True):
            for change in changes:
                with self.subTest(classified=classified, change=changes.index(change)):
                    result, calls, output, requests, _ = run_recorded(self, classified=classified, change=change)
                    self.assertEqual(result.completed, 0)
                    self.assertEqual(output, {})
                    self.assertEqual(len(requests), 2)
                    self.assertFalse(any(n.startswith('finish_') for n, _ in calls))

    def test_mismatched_claim_stops_before_provider_and_completion(self):
        for classified in (False, True):
            for key, value in [('revision', 'b'*64), ('workerId', 'other'), ('sourceItemId', '40000000-0000-4000-8000-000000000999')]:
                result, calls, output, requests, _ = run_recorded(self, classified=classified,
                    claim_change=lambda c: c.update({key: value}))
                self.assertEqual(result.completed, 0)
                self.assertEqual(requests, [])
                self.assertEqual(output, {})
                self.assertEqual(len(calls), 1)

    def test_unknown_finish_does_not_retry_completion_or_provider(self):
        for classified in (False, True):
            result, calls, output, requests, _ = run_recorded(self, classified=classified, finish_unknown=True)
            self.assertEqual(result.completed, 0)
            self.assertEqual(result.state_unknown, 1)
            self.assertEqual(sum(n.startswith('finish_') for n, _ in calls), 1)
            self.assertEqual(len(requests), 2)
            self.assertEqual(output, {})


if __name__ == '__main__':
    unittest.main()
