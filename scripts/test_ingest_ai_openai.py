"""OpenAI transport, budgets and validation with synthetic SDK responses only."""
import json
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ingest.ai_openai import (OpenAIAdapter, GPT_MODEL, GPT_JOB_USD_CAP,
    bounded_cost)
from ingest.ai_errors import AiJobError
from ingest.ai_claude import SUMMARY_MAX_TOKENS, TRANSLATION_MAX_TOKENS
from ingest.ai_provider import create_provider_adapter
from test_ingest_ai_claude import SUMMARY_JSON, TRANSLATION_JSON, HttpError


def response(text, *, reasoning=7, status='completed', model=GPT_MODEL):
    return {'status': status, 'model': model, 'service_tier': 'default',
        'output': [{'type': 'reasoning', 'summary': []}, {'type': 'message',
            'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': text}]}],
        'usage': {'input_tokens': 90, 'output_tokens': 20,
                  'output_tokens_details': {'reasoning_tokens': reasoning}}}


class FakeResponses:
    def __init__(self):
        self.requests = []
        self.counts = []
        self.input_tokens = SimpleNamespace(count=self.count)
        self.count_values = [100, 120]
        self.results = [response(SUMMARY_JSON), response(TRANSLATION_JSON)]
        self.error = None

    def count(self, **kwargs):
        self.counts.append(kwargs)
        return {'input_tokens': self.count_values[len(self.counts) - 1]}

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return self.results[len(self.requests) - 1]


class FakeClient:
    def __init__(self):
        self.max_retries = 0
        self.responses = FakeResponses()


class OpenAIContractTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def adapter(self):
        client = FakeClient()
        return OpenAIAdapter(client=client), client

    def test_two_calls_shared_schema_prompt_and_correct_model(self):
        adapter, client = self.adapter()
        self.assertEqual(adapter.summarize_myseoul_ko('현재 확인된 설명', 'https://synthetic.invalid', '합성')[2], GPT_MODEL)
        self.assertEqual(adapter.translate_ja('합성', '한국어 요약입니다.')[3], GPT_MODEL)
        self.assertEqual(len(client.responses.requests), 2)
        self.assertEqual(len(client.responses.counts), 2)
        for request, ceiling in zip(client.responses.requests, [SUMMARY_MAX_TOKENS, TRANSLATION_MAX_TOKENS]):
            self.assertEqual(request['model'], GPT_MODEL)
            self.assertEqual(request['max_output_tokens'], ceiling)
            self.assertEqual(request['reasoning'], {'effort': 'low'})
            self.assertFalse(request['store'])
            self.assertEqual(request['service_tier'], 'default')
            self.assertEqual(request['truncation'], 'disabled')
            self.assertFalse({'temperature', 'top_p', 'thinking', 'tools', 'previous_response_id'} & request.keys())
            self.assertTrue(request['text']['format']['strict'])
        self.assertIn('Contextual terminology', client.responses.requests[1]['instructions'])
        self.assertIn('title_ko: 합성', client.responses.requests[1]['input'][0]['content'])
        self.assertEqual(adapter._usage_records[0]['reasoning_tokens'], 7)
        self.assertEqual(adapter._usage_records[0]['provider'], 'openai')
        self.assertAlmostEqual(adapter._spent_cost_upper_usd, 2 * (90 * 2.5 + 20 * 10) / 1_000_000)
        with self.assertRaises(AiJobError): adapter.translate_ja('합성', '한국어 요약입니다.')
        self.assertEqual(len(client.responses.requests), 2)

    def test_factory_has_no_cross_provider_fallback(self):
        adapter = create_provider_adapter('openai', 'synthetic', client=FakeClient())
        self.assertIsInstance(adapter, OpenAIAdapter)
        client = FakeClient(); client.max_retries = 2
        with self.assertRaises(AiJobError): OpenAIAdapter(client=client)

    def test_cost_block_before_generation_and_count_bound(self):
        adapter, client = self.adapter()
        client.responses.count_values[0] = 100000
        with self.assertRaises(AiJobError) as caught: adapter.summarize_ko('合成', None)
        self.assertEqual(caught.exception.code, 'ai_blocked_cost_cap')
        self.assertEqual(client.responses.requests, [])
        adapter, client = self.adapter(); adapter.summarize_ko('合成', None)
        client.responses.count_values[1] = adapter._translation_input_bound + 1
        with self.assertRaises(AiJobError) as caught: adapter.translate_ja('합성', '한국어 요약입니다.')
        self.assertEqual(caught.exception.code, 'ai_cost_bound_breach')
        self.assertEqual(len(client.responses.requests), 1)
        self.assertEqual(GPT_JOB_USD_CAP, .10)

    def test_budget_boundary_and_missing_or_bad_usage_fail_closed(self):
        from ingest.ai_claude import CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS as reserve
        cost = lambda n: bounded_cost(n, SUMMARY_MAX_TOKENS) + bounded_cost(n + SUMMARY_MAX_TOKENS + reserve, TRANSLATION_MAX_TOKENS)
        boundary = next(n for n in range(10000) if cost(n) > .10)
        adapter, client = self.adapter(); client.responses.count_values[0] = boundary - 1
        adapter.summarize_ko('합성', None)
        adapter, client = self.adapter(); client.responses.count_values[0] = boundary
        with self.assertRaises(AiJobError): adapter.summarize_ko('합성', None)
        self.assertEqual(client.responses.requests, [])
        for usage in [None, {'input_tokens': True, 'output_tokens': 20},
                      {'input_tokens': 90, 'output_tokens': 20, 'output_tokens_details': {'reasoning_tokens': 21}}]:
            adapter, client = self.adapter(); client.responses.results[0]['usage'] = usage
            with self.assertRaises(AiJobError): adapter.summarize_ko('합성', None)
            self.assertEqual(len(client.responses.requests), 1)

    def test_incomplete_refusal_extra_json_and_reasoning_only_rejected(self):
        bad = [response(SUMMARY_JSON, status='incomplete'), response(SUMMARY_JSON, model='claude-sonnet-5')]
        refusal = response(SUMMARY_JSON)
        refusal['output'][1]['content'] = [{'type': 'refusal', 'refusal': 'private error'}]
        bad.append(refusal)
        only = response(SUMMARY_JSON); only['output'] = only['output'][:1]; bad.append(only)
        extra = json.loads(SUMMARY_JSON); extra['review'] = '잘 번역되었습니다'
        bad.append(response(json.dumps(extra)))
        bad.append(response('```json\n'+SUMMARY_JSON+'\n```'))
        for result in bad:
            with self.subTest(result=result['status']):
                adapter, client = self.adapter(); client.responses.results[0] = result
                with self.assertRaises(AiJobError): adapter.summarize_ko('합성', None)
                with self.assertRaises(AiJobError): adapter.translate_ja('합성', '본문')
                self.assertEqual(len(client.responses.requests), 1)

    def test_thinking_tokens_count_against_same_output_limit(self):
        adapter, client = self.adapter()
        result = response(SUMMARY_JSON, status='incomplete')
        result['usage']['output_tokens'] = SUMMARY_MAX_TOKENS
        result['usage']['output_tokens_details']['reasoning_tokens'] = SUMMARY_MAX_TOKENS
        client.responses.results[0] = result
        with self.assertRaises(AiJobError): adapter.summarize_ko('합성', None)
        self.assertEqual(len(client.responses.requests), 1)
        adapter, client = self.adapter()
        result = response(SUMMARY_JSON); result['usage']['output_tokens'] = SUMMARY_MAX_TOKENS + 1
        client.responses.results[0] = result
        with self.assertRaises(AiJobError) as caught: adapter.summarize_ko('합성', None)
        self.assertEqual(caught.exception.code, 'ai_cost_bound_breach')

    def test_errors_secret_safe_and_no_automatic_second_call(self):
        for status in [400, 401, 403, 404, 429, 500]:
            adapter, client = self.adapter(); client.responses.error = HttpError(status)
            with self.assertRaises(AiJobError) as caught: adapter.summarize_ko('합성', None)
            self.assertTrue(caught.exception.code.startswith('ai_http_'))
            self.assertEqual(len(client.responses.requests), 1)
        for error in [type('APITimeoutError', (Exception,), {})('secret'),
                      type('APIConnectionError', (Exception,), {})('secret')]:
            adapter, client = self.adapter(); client.responses.error = error
            with self.assertRaises(AiJobError) as caught: adapter.summarize_ko('합성', None)
            self.assertNotIn('secret', str(caught.exception))
            self.assertEqual(len(client.responses.requests), 1)

    def test_semantic_validation_is_reused_not_just_json_shape(self):
        for ko, ja in [('선착순 30명, 정원 도달 시 마감', '定員に達し次第締め切ります。'),
                       ('수강료: 10,000원; 재료비: 2,000원', '受講料: 2,000ウォン; 材料費: 10,000ウォン')]:
            adapter, client = self.adapter(); adapter.summarize_ko('합성', None)
            client.responses.results[1] = response(json.dumps({'title_ja': '合成', 'content_ja': ja}))
            with self.assertRaises(AiJobError): adapter.translate_ja('합성', ko)
        adapter, client = self.adapter(); adapter.summarize_ko('합성', None)
        client.responses.results[1] = response(json.dumps({'title_ja': '合成', 'content_ja': '先着30名。定員に達し次第締め切ります。'}))
        self.assertEqual(adapter.translate_ja('합성', '선착순 30명, 정원 도달 시 마감')[2], 'success')


if __name__ == '__main__': unittest.main()
