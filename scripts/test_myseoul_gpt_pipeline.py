"""Full injected SDK -> reviewed Korean -> Japanese -> fenced candidate path."""
import copy
import json
import re
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ingest.ai_claude import SUMMARY_SCHEMA
from ingest.ai_openai import OpenAIAdapter, GPT_MODEL
from ingest.myseoul_ai import process_myseoul_job, fact_sections
from ingest.program_ai import ProgramAIAdapter
from ingest.reclassification_ai import process_reclassified_job, protected_information
from ingest.rpc_errors import RpcTimeout
from test_ingest_ai_openai import FakeClient, response
from test_myseoul_ai import context as native_context, ID as NATIVE_ID, JOB
from test_reclassification_ai import context as classified_context, ID, REV
from test_ingest_translation_fidelity import CONTEXTUAL_CASES


def summary_response(content):
    return response(json.dumps({'content_ko': content,
        'facts': {k: '' for k in SUMMARY_SCHEMA['properties']['facts']['required']}}, ensure_ascii=False))


def japanese_dates(text):
    # Fixture construction only, never used by the product to repair an output.
    return re.sub(r'(\d{4})-(\d{2})-(\d{2})',
        lambda m: f'{int(m[1])}年{int(m[2])}月{int(m[3])}日', text)


def native_packet():
    c = native_context()
    c['facts'].update(target='보호자 동반', conditions=['업무 효율을 173% 올려주는 활용 교육'],
        age=[], companion=[], language=[], residence='', qualification_note='',
        capacity_raw=['선착순 25명'], capacity_value=25, venue='',
        fees=[{'component': 'tuition', 'evidence': ['무료']},
              {'component': 'admission', 'evidence': ['3,000원']}],
        session_evidence=[], meeting_evidence=[], application_methods=['방문 신청'],
        description='합성 이미지에서 확인한 설명입니다.\n교육 일정: 10월 3일(토), 10월 10일(토), 10월 17일(토), 총 3회')
    # Venue is privately confirmed on the server, without inserting fake quotes.
    c['facts']['activity_region'] = 'capital'
    return c


def native_client(c):
    client = FakeClient()
    ko = '[한 줄 요약]\n합성 교육입니다.\n[주요 내용]\n선착순 25명 교육입니다.'
    ranges = japanese_dates(fact_sections(c['facts'])['[일정 안내]'].split('\n\n**진행 일정:**')[0])
    ranges = ranges.replace('신청기간:', '- **申請期間:**').replace('진행기간:', '- **実施期間:**')
    ja = ('[要約]\n合成教育です。\n[対象]\n保護者同伴\n[期間・状況]\n' + ranges +
          '\n\n**実施日程:**\n- 10月3日(土)、10月10日(土)、10月17日(土)、全3回\n[主な内容]\n'
          '先着25名。\n- **費用:** 受講料: 無料; 入場料: 3,000ウォン\n- **募集人数:** 先着25名\n[申請方法]\n窓口申込')
    client.responses.results = [summary_response(ko), response(json.dumps({'title_ja': '合成教育', 'content_ja': ja}))]
    return client


class GPTPipelineTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        guard.start(); self.addCleanup(guard.stop)

    def native_run(self, c, client, mode='success', *, adapter_factory=OpenAIAdapter):
        calls = []
        def rpc(name, args):
            calls.append((name, args))
            if name == 'claim_myseoul_program_ai': return [c]
            if name == 'admin_myseoul_program_detail':
                return {'id': c['sourceItemId'], 'revision': c['revision'], 'schema': c['schema'],
                    'profile': c['profile'], 'factsVersion': c['factsVersion'], 'status': 'resolved',
                    'aiStatus': 'claimed', 'source': {'name': c['source'], 'title': c['title'], 'url': c['facts']['official_url']},
                    'facts': c['facts'], 'observedFacts': c['observedFacts'],
                    'result': {'scope': 'included', 'quality': 'sufficient', 'public_category': 'program',
                               'application': 'open', 'decision': 'in_scope', 'reasons': []}}
            if name == 'finish_myseoul_program_ai':
                if mode == 'unknown': raise RpcTimeout()
                return {'outcome': 'inserted', 'candidateId': JOB}
            if name == 'fail_myseoul_program_ai': return 'failed'
            raise AssertionError(name)
        adapter = adapter_factory(client=client)
        result = process_myseoul_job(ProgramAIAdapter(rpc), source_item_id=NATIVE_ID,
            revision=c['revision'], summarize_ko=adapter.summarize_myseoul_ko,
            translate_ja=adapter.translate_ja, worker_id=c['workerId'])
        return result, calls, adapter

    def test_native_candidate_preserves_capacity_sessions_image_and_fence(self):
        c = native_packet(); before = copy.deepcopy(c); client = native_client(c)
        result, calls, adapter = self.native_run(c, client)
        self.assertEqual(result.completed, 1)
        self.assertEqual(c, before)
        output = calls[-1][1]['p_output']
        self.assertEqual(output['aiModel'], GPT_MODEL)
        self.assertIn('10월 10일', output['contentKo'])
        self.assertIn('총 3회', output['contentKo'])
        self.assertIn('선착순 25명', output['contentKo'])
        self.assertNotIn('173%', output['contentKo'])
        packet = json.loads(client.responses.requests[0]['input'][0]['content'].split('body:\n', 1)[1])
        self.assertEqual(packet['currentFacts']['description'], c['facts']['description'])
        self.assertEqual(packet['currentFacts']['capacity_value'], 25)
        self.assertIn('description', packet['operatorSupplementedFields'])
        self.assertEqual(client.responses.requests[1]['input'][0]['content'],
            f"title_ko: {c['title']}\ncontent_ko:\n{output['contentKo']}")
        fence = calls[-1][1]
        for param, key in [('p_revision','revision'), ('p_facts_version','factsVersion'),
                           ('p_claimed_at','claimedAt'), ('p_lease_until','leaseUntil'), ('p_worker_id','workerId')]:
            self.assertEqual(fence[param], c[key])
        self.assertEqual(len(client.responses.requests), 2)
        self.assertEqual(len(adapter._usage_records), 2)

    def test_bad_translation_never_finishes_and_unknown_finish_never_rewrites(self):
        c = native_packet(); client = native_client(c)
        client.responses.results[1]['output'][1]['content'][0]['text'] = json.dumps(
            {'title_ja': '合成', 'content_ja': '[要約]\n合成\n[対象]\n対象\n[期間・状況]\n期間\n[主な内容]\n25歳\n[申請方法]\n公式'})
        result, calls, _ = self.native_run(c, client)
        self.assertEqual(result.completed, 0)
        self.assertFalse(any(n.startswith('finish_') for n, _ in calls))
        self.assertEqual(len(client.responses.requests), 2)
        client = native_client(c); result, calls, _ = self.native_run(c, client, 'unknown')
        self.assertEqual(result.state_unknown, 1)
        self.assertEqual(sum(n.startswith('finish_') for n, _ in calls), 1)
        self.assertFalse(any(n.startswith('fail_') for n, _ in calls))
        self.assertEqual(len(client.responses.requests), 2)

    def test_stale_claim_never_calls_gpt(self):
        for key, value in [('sourceItemId', JOB), ('revision', 'b'*64), ('factsVersion', True)]:
            c = native_packet(); c[key] = value; client = native_client(c)
            result, calls, _ = self.native_run(c, client)
            self.assertEqual(result.state_unknown, 1)
            self.assertEqual(client.responses.requests, [])
            self.assertEqual(len(calls), 1)

    def test_reclassified_categories_share_prompt_and_image_supplement(self):
        for category in ['program', 'event', 'youth_space', 'policy', 'living']:
            c = classified_context(category); c['body'] = ''
            c['nativeConfirmedFacts']['programFacts'] = {'description': '합성 이미지 보완 설명',
                'capacity_raw': ['선착순 25명'], 'session_evidence': ['10월 3일, 10월 10일, 총 2회'],
                'conditions': ['보호자 동반']}
            # Handwritten Japanese fixture matching public section placement.
            ja = ('[要約]\n合成\n[対象]\n- **参加対象の根拠:** 合成の全国対象\n'
                  '- **参加条件:** 保護者同伴\n- **募集人数:** 先着25名\n[日程案内]')
            if category == 'policy': ja += '\n- **申請締切:** 締切なし'
            if category == 'event': ja += '\n- **開催期間:** 2099年10月9日～2099年10月9日'
            ja += '\n- **実施日程:** 10月3日、10月10日、全2回'
            if category == 'program': ja += '\n- **申請期間:** 2099年10月1日～2099年10月15日'
            ja += '\n[主な内容]\n合成活動\n- **実施方式:** オンライン'
            client = FakeClient(); client.responses.results = [summary_response('[한 줄 요약]\n합성\n[주요 내용]\n합성 활동'),
                response(json.dumps({'title_ja': '合成', 'content_ja': ja}))]
            calls = []
            def rpc(name, args):
                calls.append((name, args))
                if name == 'claim_reclassified_content_ai': return c
                if name == 'finish_reclassified_content_ai': return {'outcome': 'inserted', 'candidateId': ID}
                return {'status': 'active'}
            adapter = OpenAIAdapter(client=client)
            result = process_reclassified_job(ProgramAIAdapter(rpc), source_item_id=ID, revision=REV,
                classification_version=1, worker_id='synthetic-worker', summarize_ko=adapter.summarize_ko,
                translate_ja=adapter.translate_ja)
            self.assertEqual(result.completed, 1, category)
            output = calls[-1][1]['p_output']
            self.assertEqual(output['aiModel'], GPT_MODEL)
            from test_reclassification_ai import assert_public_facts
            assert_public_facts(self, c, output['contentKo'])
            self.assertIn('합성 이미지 보완 설명', client.responses.requests[0]['input'][0]['content'])
            self.assertIn('Contextual terminology', client.responses.requests[1]['instructions'])
            self.assertEqual(len(client.responses.requests), 2)

    def test_contextual_counterexamples_remain_accepted_by_gpt_adapter(self):
        for ko, alternatives, misleading in CONTEXTUAL_CASES:
            for ja in alternatives:
                client = FakeClient(); client.responses.results = [summary_response('[한 줄 요약]\n합성'),
                    response(json.dumps({'title_ja': '合成', 'content_ja': ja}))]
                adapter = OpenAIAdapter(client=client); adapter.summarize_ko('합성', None)
                self.assertEqual(adapter.translate_ja('합성', ko)[1], ja)
                # Misleading contextual wording requires model/human evaluation;
                # do not pretend fake generation proves it cannot occur.

    def test_installed_official_sdk_serializes_without_network(self):
        import httpx
        from openai import OpenAI
        events = []
        def handle(request):
            payload = json.loads(request.content); events.append((request.url.path, payload))
            if request.url.path.endswith('/input_tokens'):
                return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 100})
            text = json.dumps({'content_ko': '합성', 'facts': {k: '' for k in SUMMARY_SCHEMA['properties']['facts']['required']}})
            if payload['text']['format']['name'].endswith('translation'):
                text = json.dumps({'title_ja': '合成', 'content_ja': '合成'})
            result = response(text); result.update(id='synthetic-response', object='response', created_at=0)
            result['output'][1]['id'] = 'synthetic-message'
            result['output'][1]['content'][0]['annotations'] = []
            result['usage'].update(total_tokens=110, input_tokens_details={'cached_tokens': 0})
            return httpx.Response(200, json=result)
        with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
            client = OpenAI(api_key='synthetic-not-a-key', max_retries=0, http_client=transport)
            adapter = OpenAIAdapter(client=client)
            adapter.summarize_ko('합성', None); adapter.translate_ja('합성', '합성')
        self.assertEqual([path for path, _ in events], ['/v1/responses/input_tokens', '/v1/responses',
                                                       '/v1/responses/input_tokens', '/v1/responses'])

    def test_native_and_classified_entrypoints_construct_selected_provider_only(self):
        import run_myseoul_program_ai as native_cli
        import run_reclassified_content_ai as classified_cli
        fake = OpenAIAdapter(client=FakeClient())
        args = SimpleNamespace(project_ref='a'*20, source_item_id=ID, revision=REV, classification_version=1)
        env = {'SUPABASE_URL': 'https://'+'a'*20+'.supabase.co', 'SUPABASE_SERVICE_KEY': 'synthetic-service',
               'AI_PROVIDER': 'openai', 'OPENAI_API_KEY': 'synthetic-openai', 'ANTHROPIC_API_KEY': 'unused'}
        with patch.dict('os.environ', env, clear=True):
            with patch('ingest.ai_provider.create_provider_adapter', return_value=fake) as factory:
                with patch('ingest.supabase_store.create_ingest_client', return_value=object()):
                    with patch('ingest.program_ai.ProgramAIAdapter.from_supabase', return_value=object()):
                        with patch('ingest.myseoul_ai.process_myseoul_job', return_value='native') as native:
                            with patch('ingest.reclassification_ai.process_reclassified_job', return_value='classified') as classified:
                                self.assertEqual(native_cli.execute_target(args), 'native')
                                self.assertEqual(classified_cli.execute_target(args), 'classified')
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(factory.call_args.args, ('openai', 'synthetic-openai'))
        self.assertEqual(native.call_args.kwargs['summarize_ko'].__self__, fake)
        self.assertEqual(classified.call_args.kwargs['translate_ja'].__self__, fake)

    def test_common_cli_selects_gpt_without_loading_anthropic(self):
        import run_ingest_architecture as cli
        fake = OpenAIAdapter(client=FakeClient())
        with patch('run_ingest_architecture.create_provider_adapter', return_value=fake) as factory:
            with patch('run_ingest_architecture._load_anthropic_ai_helpers') as anthropic:
                helpers = cli._load_ai_helpers('openai', 'synthetic-openai')
        factory.assert_called_once_with('openai', 'synthetic-openai')
        anthropic.assert_not_called()
        self.assertEqual(helpers['summarize_ko'].__self__, fake)
        self.assertEqual(helpers['translate_ja'].__self__, fake)


if __name__ == '__main__': unittest.main()
