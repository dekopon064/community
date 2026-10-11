"""Recorded SYNTHETIC Pro response replay. No auth, provider, DB or network.

The summary below was generated before this fix. The Japanese replay fixture
is explicitly edited test data, not a new model response or quality evaluation.
"""
import copy
import json
import socket
import unittest
from unittest.mock import patch

from ingest.ai_claude import (ClaudeAdapter, MYSEOUL_FEE_RULES, MYSEOUL_SUMMARY_SYSTEM,
    SUMMARY_SYSTEM, SUMMARY_SCHEMA, SUMMARY_MAX_TOKENS, TRANSLATION_MAX_TOKENS,
    CLAUDE_JOB_USD_CAP, CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS, conservative_cost_usd)
from ingest.ai_openai import OpenAIAdapter, bounded_cost, GPT_JOB_USD_CAP
from ingest.ai_provider import create_provider_adapter
from ingest.ai_errors import AiJobError
from ingest.body_sections import normalize_schedule_heading
from ingest.body_markdown import comparison_text
from ingest.chatgpt_plan_probe import synthetic_context
from ingest.myseoul_ai import myseoul_input
from ingest.reclassification_ai import classification_input, process_reclassified_job
from ingest.program_ai import ProgramAIAdapter
from test_myseoul_ai import context
from test_reclassification_ai import context as classified_context, ID, REV
import test_myseoul_gpt_pipeline as gpt_fixture
from test_ingest_ai_openai import FakeClient, response
from test_ingest_ai_claude import FakeClient as ClaudeClient, _message
from test_ingest_ai_chatgpt_plan import streamed, verified_session


FEE_SENTENCE = '수강료는 10,000원이며, 재료비 2,000원이 별도로 있습니다.'
RECORDED_SUMMARY = {
    'content_ko': '[한 줄 요약]\n합성 디지털 사무 교육 1반은 성남시에 거주하는 18세 이상 F-2 비자 소지 외국인 주민을 위한 온라인 디지털 사무 도구 실습 교육입니다.\n\n'
        '[대상]\n성남시 주민인 18세 이상 외국인 주민 중 F-2 비자 소지자만 신청할 수 있습니다. 영어로 진행하며, 선착순 25명으로 정원 도달 시 마감됩니다.\n\n'
        '[기간·상태]\n신청 기간: 2027년 1월 5일~1월 12일\n운영 기간: 2027년 2월 3일~2월 17일\n실제 수업: 2월 3일, 2월 10일, 2월 17일 각 09:30~11:00, 총 3회\n\n'
        '[주요 내용]\n디지털 사무 도구를 읽고 듣고 따라 말하며 실습하는 온라인 교육입니다. 안내에는 업무 효율을 173% 올려주는 교육으로 소개되어 있습니다. '
        + FEE_SENTENCE + ' 마실 물을 준비하세요.\n\n[신청 방법]\n전화 상담 후 방문 접수합니다.',
    'facts': {
        'audience': '18세 이상 외국인 주민. 영어로 진행. 선착순 25명이며 정원 도달 시 마감.',
        'geo_age_income': '성남시 주민만 신청 가능. 18세 이상, F-2 비자 소지자만 신청 가능.',
        'amount_period_deadline': '수강료 10,000원, 재료비 2,000원 별도. 신청 기간 2027년 1월 5일~1월 12일. 운영 기간 2027년 2월 3일~2월 17일. 실제 수업은 2월 3일·10일·17일 각 09:30~11:00, 총 3회. 정원 도달 시 마감.',
        'how_to_apply': '전화 상담 후 방문 접수.',
    },
}
RECORDED_TRANSLATION = {
    'title_ja': '合成デジタル事務教育クラス1',
    'content_ja': '[要約]\n合成デジタル事務教育クラス1は、ソンナム市に居住する18歳以上のF-2ビザを持つ外国人住民のための、オンラインのデジタル事務ツール実習教育です。\n'
        '[対象]\n18歳以上の外国人住民\n[期間・状況]\n申請期間：2027年1月5日～2027年1月12日\n実施期間：2027年2月3日～2027年2月17日\n実施日程：2月3日、2月10日、2月17日 9時30分～11時00分、全3回\n'
        '[主な内容]\nデジタル事務ツールについて読み、聞き、復唱しながら実習するオンライン教育です。案内では、業務効率を173%向上させる教育として紹介されています。受講料は10,000ウォンで、材料費2,000ウォンが別途かかります。飲み水を準備してください。\n'
        '参加条件：ソンナム市の住民のみ申請可能 / F-2ビザ所持者のみ申請可能 / 先着25名、定員に達し次第締め切ります / 英語で行われます\n'
        '費用：受講料：10,000ウォン；材料費：2,000ウォン\n募集人数：先着25名\n実施方式：オンライン\n[申請方法]\n電話相談後、窓口で申請を受け付けます。\n申請リンク：https://synthetic.invalid/apply?a=1',
}


def edited_translation_fixture():
    # Handwritten fixture for today's list structure, not a new AI response.
    value = copy.deepcopy(RECORDED_TRANSLATION)
    value['content_ja'] = '''[要約]
合成デジタル事務教育クラス1は、ソンナム市に居住する18歳以上のF-2ビザを持つ外国人住民のための、オンラインのデジタル事務ツール実習教育です。
[対象]
18歳以上の外国人住民
[日程案内]
- **申請期間:** 2027年1月5日～2027年1月12日
- **実施期間:** 2027年2月3日～2027年2月17日

**実施日程:**
- 2月3日、2月10日、2月17日 9時30分～11時00分、全3回
[主な内容]
デジタル事務ツールについて読み、聞き、復唱しながら実習するオンライン教育です。案内では、業務効率を173%向上させる教育として紹介されています。飲み水を準備してください。
- **参加条件:** ソンナム市の住民のみ申請可能 / F-2ビザ所持者のみ申請可能 / 先着25名、定員に達し次第締め切ります / 英語で行われます
- **費用:** 受講料: 10,000ウォン; 材料費: 2,000ウォン
- **募集人数:** 先着25名
- **実施方式:** オンライン
[申請方法]
電話相談後、窓口で申請を受け付けます。
- **申請リンク:** https://synthetic.invalid/apply?a=1'''
    return value


def edited_classified_translation_fixture():
    # Handwritten fixture for distributed public facts, never a model response.
    value = copy.deepcopy(RECORDED_TRANSLATION)
    value['content_ja'] = '''[要約]
合成デジタル事務教育クラス1は、ソンナム市に居住する18歳以上のF-2ビザを持つ外国人住民のための、オンラインのデジタル事務ツール実習教育です。
[対象]
ソンナム市に居住する18歳以上のF-2ビザ所持外国人住民のみ申請可能です。英語で行われ、先着25名で定員に達し次第締め切ります。

18歳以上の外国人住民
- **参加対象の根拠:** 合成の全国申請条件
- **参加条件:** ソンナム市の住民のみ申請可能 / F-2ビザ所持者のみ申請可能 / 先着25名、定員に達し次第締め切ります
- **居住条件:** ソンナム市の住民のみ申請可能
- **募集人数:** 先着25名
- **参加条件:** 英語で行われます
[日程案内]
申請期間: 2027年1月5日～1月12日
実施期間: 2027年2月3日～2月17日
実際の授業: 2月3日、2月10日、2月17日 各9時30分～11時00分、全3回

**実施日程:**
- 2月3日、2月10日、2月17日 9時30分～11時00分、全3回
- **申請期間:** 2027年1月5日～2027年1月12日
- **実施期間:** 2027年2月3日～2027年2月17日
[主な内容]
デジタル事務ツールについて読み、聞き、復唱しながら実習するオンライン教育です。案内では、業務効率を173%向上させる教育として紹介されています。飲み水を準備してください。
- **実施方式:** オンライン
- **費用:** 受講料: 10,000ウォン; 材料費: 2,000ウォン
[申請方法]
電話相談後、窓口で申請を受け付けます。
- **申請方法:** 電話相談後、窓口で申請
- **申請リンク:** https://synthetic.invalid/apply?a=1'''
    return value


def recorded_packet():
    c = context()
    synthetic = synthetic_context()
    c['title'] = synthetic['title']
    c['facts'].update(copy.deepcopy(synthetic['facts']))
    c['facts']['official_url'] = ('https://global.seoul.go.kr/hmpg/ecpr/prgm/prgmDetail.do?'
        'cntr_no='+'0'*32+'&prgrm_no='+'0'*32+'&lang=ko')
    c['facts']['residence_scope'] = 'capital'
    c['facts']['residence_evidence'] = ['성남시 주민만 신청 가능']
    c['observedFacts'] = copy.deepcopy(c['facts'])
    c['observedFacts'].update(description='', capacity_raw=[], capacity_value=None)
    return c


class RecordedFeeReplayTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def plan_pair(self, summary=None, translation=None):
        client = streamed([response(json.dumps(summary or RECORDED_SUMMARY, ensure_ascii=False)),
                           response(json.dumps(translation or edited_translation_fixture(), ensure_ascii=False))])
        adapter = create_provider_adapter('chatgpt_plan', None, client=client, plan_session=verified_session())
        self.addCleanup(adapter.close)
        return adapter, client

    def native(self, c, adapter, client):
        return gpt_fixture.GPTPipelineTests().native_run(c, client, adapter_factory=lambda **_:adapter)

    def classified(self, adapter):
        c = classified_context('program')
        c['title'] = recorded_packet()['title']
        c['nativeConfirmedFacts']['programFacts'] = recorded_packet()['facts']
        c['body'] = ''
        c['facts']['deadlineOn'] = '2027-01-12'
        value = c['filters']['application']['value']
        value['start']['value'] = '2027-01-05'
        value['end']['value'] = '2027-01-12'
        before = copy.deepcopy(c)
        calls = []
        def rpc(name, args):
            calls.append((name, args))
            if name == 'claim_reclassified_content_ai': return copy.deepcopy(c)
            if name == 'finish_reclassified_content_ai': return {'outcome':'inserted','candidateId':ID}
            if name == 'reclassified_content_ai_status': return {'status':'active'}
            raise AssertionError(name)
        result = process_reclassified_job(ProgramAIAdapter(rpc), source_item_id=ID, revision=REV,
            classification_version=1, worker_id='synthetic-worker', summarize_ko=adapter.summarize_ko,
            translate_ja=adapter.translate_ja)
        self.assertEqual(c, before)
        return result, calls, c

    def test_recorded_summary_to_native_plan_request_and_fenced_fake_candidate(self):
        c = recorded_packet()
        before = copy.deepcopy(c)
        adapter, client = self.plan_pair()
        result, calls, _ = self.native(c, adapter, client)
        self.assertEqual(result.completed, 1)
        self.assertEqual(c, before)
        output = calls[-1][1]['p_output']
        plain = comparison_text(output['contentKo'])
        for label in ('수강료','재료비'):
            self.assertEqual(output['contentKo'].count(label), 1)
        for label in ('受講料','材料費'):
            self.assertEqual(output['contentJa'].count(label), 1)
        self.assertNotIn(FEE_SENTENCE, output['contentKo'])
        for protected in ('성남시 주민만 신청 가능','F-2 비자 소지자만 신청 가능','18세 이상',
                          '선착순 25명','정원 도달 시 마감','영어로 진행','마실 물을 준비하세요.',
                          '신청기간: 2027-01-05 ~ 2027-01-12','진행기간: 2027-02-03 ~ 2027-02-17',
                          '2월 3일, 2월 10일, 2월 17일 09:30~11:00, 총 3회',
                          '비용: 수강료: 10,000원; 재료비: 2,000원'):
            self.assertIn(protected, plain)
        self.assertIn(output['contentKo'], client.calls[1]['input'][0]['content'])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0]['instructions'], MYSEOUL_SUMMARY_SYSTEM)
        self.assertEqual(set(RECORDED_SUMMARY['facts']), set(SUMMARY_SCHEMA['properties']['facts']['required']))
        self.assertIn('수강료 10,000원, 재료비 2,000원', RECORDED_SUMMARY['facts']['amount_period_deadline'])
        self.assertEqual(set(output), {'titleKo','titleJa','summaryKo','summaryJa','contentKo','contentJa','aiModel'})
        for parameter,key in [('p_revision','revision'),('p_facts_version','factsVersion'),
                              ('p_claimed_at','claimedAt'),('p_lease_until','leaseUntil'),('p_worker_id','workerId')]:
            self.assertEqual(calls[-1][1][parameter], c[key])

    def test_reclassified_replay_uses_same_fee_rules_and_preserves_fence(self):
        adapter, client = self.plan_pair(translation=edited_classified_translation_fixture())
        result, calls, c = self.classified(adapter)
        self.assertEqual(result.completed, 1)
        output = calls[-1][1]['p_output']
        self.assertNotIn(FEE_SENTENCE, output['contentKo'])
        self.assertIn('수강료: 10,000원; 재료비: 2,000원', output['contentKo'])
        self.assertNotRegex(output['contentKo'], r'"component"|"evidence"|\["|\{\s*"')
        self.assertIn('총 3회', output['contentKo'])
        self.assertIn('성남시 주민만 신청 가능', output['contentKo'])
        self.assertIn(output['contentKo'], client.calls[1]['input'][0]['content'])
        self.assertIn(MYSEOUL_FEE_RULES, client.calls[0]['instructions'])
        for parameter,key in [('p_revision','revision'),('p_classification_version','classificationVersion'),
                              ('p_claimed_at','claimedAt'),('p_lease_until','leaseUntil'),('p_worker_id','workerId')]:
            self.assertEqual(calls[-1][1][parameter], c[key])

    def test_unfixed_cleanup_is_blocked_before_translation_in_both_workers(self):
        for classified in (False, True):
            adapter, client = self.plan_pair()
            target = 'ingest.myseoul_content' if classified else 'ingest.myseoul_ai'
            with self.subTest(classified=classified), patch(target+'.deduplicate_summary_fees',
                    side_effect=lambda main, _:main):
                if classified:
                    result, calls, _ = self.classified(adapter)
                    self.assertEqual(result.state_unknown, 1)  # Existing reclassification failure contract.
                else:
                    result, calls, _ = self.native(recorded_packet(), adapter, client)
                    self.assertEqual(result.failed, 1)
                    self.assertEqual(calls[-1][1]['p_error_code'], 'ai_schema_error')
            self.assertEqual(result.completed, 0)
            self.assertEqual(len(client.calls), 1)
            self.assertFalse(any(name.startswith('finish_') for name,_ in calls))

    def test_fee_only_summary_or_currency_conflict_never_completes(self):
        for old,new in ((RECORDED_SUMMARY['content_ko'].splitlines()[1], '수강료는 10,000원입니다.'),
                        ('재료비 2,000원', '재료비 2,000엔'),
                        ('수강료는 10,000원이며, 재료비 2,000원', '수강료는 2,000원이며, 재료비 10,000원')):
            payload = copy.deepcopy(RECORDED_SUMMARY)
            payload['content_ko'] = payload['content_ko'].replace(old, new)
            adapter, client = self.plan_pair(summary=payload)
            result, calls, _ = self.native(recorded_packet(), adapter, client)
            self.assertEqual(result.failed, 1)
            self.assertEqual(result.completed, 0)
            self.assertEqual(len(client.calls), 1)
            self.assertFalse(any(name.startswith('finish_') for name,_ in calls))

    def test_old_japanese_response_is_distinct_from_the_edited_test_fixture(self):
        before = copy.deepcopy(RECORDED_TRANSLATION)
        edited = edited_translation_fixture()
        for label in ('受講料','材料費'):
            self.assertEqual(RECORDED_TRANSLATION['content_ja'].count(label), 2)
            self.assertEqual(edited['content_ja'].count(label), 1)
        self.assertEqual(RECORDED_TRANSLATION, before)
        self.assertEqual(set(edited), {'title_ja','content_ja'})

    def test_all_transports_share_rules_and_count_the_actual_updated_request(self):
        c = recorded_packet()
        classified = classified_context('program')
        classified['nativeConfirmedFacts']['programFacts'] = c['facts']
        for body, native in ((myseoul_input(c), True), (classification_input(classified), False)):
            for transport in ('claude','openai','plan'):
                with self.subTest(transport=transport, native=native):
                    if transport == 'claude':
                        client = ClaudeClient()
                        client.messages.messages[0] = _message(json.dumps(RECORDED_SUMMARY))
                        adapter = ClaudeAdapter(api_key='synthetic-unused', client=client)
                    elif transport == 'openai':
                        client = FakeClient()
                        client.responses.results[0] = response(json.dumps(RECORDED_SUMMARY))
                        adapter = OpenAIAdapter(client=client)
                    else:
                        adapter, client = self.plan_pair()
                    method = adapter.summarize_myseoul_ko if native else adapter.summarize_ko
                    # Keep the recorded raw response unchanged, while respecting
                    # the already deployed legacy-heading normalization.
                    self.assertEqual(method(body, 'https://synthetic.invalid', '합성')[0],
                                     normalize_schedule_heading(RECORDED_SUMMARY['content_ko'], 'ko'))
                    if transport == 'claude':
                        request = client.messages.create_calls[0]
                        instructions = request['system']
                        self.assertEqual(client.messages.count_calls[0]['system'], instructions)
                        self.assertEqual(request['max_tokens'], SUMMARY_MAX_TOKENS)
                    elif transport == 'openai':
                        request = client.responses.requests[0]
                        instructions = request['instructions']
                        self.assertEqual(client.responses.counts[0]['instructions'], instructions)
                        self.assertEqual(request['max_output_tokens'], SUMMARY_MAX_TOKENS)
                    else:
                        instructions = client.calls[0]['instructions']
                    self.assertEqual(instructions.count(MYSEOUL_FEE_RULES), 1)

    def test_other_sources_keep_base_prompt_and_existing_budget_still_blocks(self):
        for body in ('ordinary non-JSON source', classification_input(classified_context('program'))):
            adapter, client = self.plan_pair()
            adapter.summarize_ko(body, None)
            self.assertEqual(client.calls[0]['instructions'], SUMMARY_SYSTEM)
        # Bytes are a conservative diagnostic bound, not a token counter result.
        # It need not fit every provider's budget; an overflow must block creation.
        input_bound = 1136 + len(MYSEOUL_FEE_RULES.encode('utf-8')) + 2  # Joining newlines too.
        translation_bound = input_bound + SUMMARY_MAX_TOKENS + CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS
        self.assertLessEqual(conservative_cost_usd(input_bound, SUMMARY_MAX_TOKENS)
            + conservative_cost_usd(translation_bound, TRANSLATION_MAX_TOKENS), CLAUDE_JOB_USD_CAP)
        self.assertGreater(bounded_cost(input_bound, SUMMARY_MAX_TOKENS)
            + bounded_cost(translation_bound, TRANSLATION_MAX_TOKENS), GPT_JOB_USD_CAP)
        client = FakeClient()
        client.responses.count_values[0] = input_bound
        adapter = OpenAIAdapter(client=client)
        with self.assertRaises(AiJobError) as failure:
            adapter.summarize_myseoul_ko(myseoul_input(recorded_packet()), None)
        self.assertEqual(failure.exception.code, 'ai_blocked_cost_cap')
        self.assertEqual(client.responses.requests, [])
        self.assertEqual(len(client.responses.counts), 1)
        for factory, client in ((ClaudeAdapter, ClaudeClient()), (OpenAIAdapter, FakeClient())):
            if factory is ClaudeAdapter:
                client.messages.count_values[0] = 100000
                adapter = factory(api_key='synthetic-unused', client=client)
            else:
                client.responses.count_values[0] = 100000
                adapter = factory(client=client)
            with self.assertRaises(AiJobError) as failure:
                adapter.summarize_myseoul_ko(myseoul_input(recorded_packet()), None)
            self.assertEqual(failure.exception.code, 'ai_blocked_cost_cap')
            self.assertFalse(client.messages.create_calls if factory is ClaudeAdapter else client.responses.requests)

    def test_current_myseoul_request_token_boundary_protects_both_paid_providers(self):
        self.assertEqual(GPT_JOB_USD_CAP, .10)
        self.assertEqual(CLAUDE_JOB_USD_CAP, .10)
        reserve = SUMMARY_MAX_TOKENS + CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS
        for factory, cost in ((ClaudeAdapter, conservative_cost_usd), (OpenAIAdapter, bounded_cost)):
            total = lambda n: cost(n, SUMMARY_MAX_TOKENS) + cost(n + reserve, TRANSLATION_MAX_TOKENS)
            boundary = next(n for n in range(100000) if total(n) > .10)
            self.assertLessEqual(total(boundary - 1), .10)
            self.assertGreater(total(boundary), .10)
            for tokens, blocked in ((boundary - 1, False), (boundary, True), (boundary + 1, True)):
                with self.subTest(provider=factory.__name__, tokens=tokens):
                    if factory is ClaudeAdapter:
                        client = ClaudeClient()
                        client.messages.count_values[0] = tokens
                        client.messages.messages[0] = _message(json.dumps(RECORDED_SUMMARY))
                        adapter = factory(api_key='synthetic-unused', client=client)
                        counts, creates = client.messages.count_calls, client.messages.create_calls
                    else:
                        client = FakeClient()
                        client.responses.count_values[0] = tokens
                        client.responses.results[0] = response(json.dumps(RECORDED_SUMMARY))
                        adapter = factory(client=client)
                        counts, creates = client.responses.counts, client.responses.requests
                    if blocked:
                        with self.assertRaises(AiJobError) as failure:
                            adapter.summarize_myseoul_ko(myseoul_input(recorded_packet()), None)
                        self.assertEqual(failure.exception.code, 'ai_blocked_cost_cap')
                        self.assertEqual(creates, [])
                    else:
                        adapter.summarize_myseoul_ko(myseoul_input(recorded_packet()), None)
                        self.assertEqual(len(creates), 1)
                    self.assertEqual(len(counts), 1)
                    self.assertIn(MYSEOUL_FEE_RULES, counts[0]['system'] if factory is ClaudeAdapter else counts[0]['instructions'])


if __name__ == '__main__':
    unittest.main()
