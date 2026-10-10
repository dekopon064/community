"""Synthetic examples and fake Claude/RPC only; no generated-quality claims.

Contextual pairs document the intended human judgment and prove that faithful
forms are not blocked. Bad contextual forms still need model/human assessment;
only explicit structural/value errors are asserted to fail automatically.
"""
import copy
import json
import socket
import unittest
from unittest.mock import patch

from ingest.ai_claude import (
    ClaudeAdapter, CLAUDE_JOB_USD_CAP, CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS,
    SUMMARY_MAX_TOKENS, TRANSLATION_MAX_TOKENS, SUMMARY_SCHEMA,
    conservative_cost_usd, translation_system_prompt,
)
from ingest.ai_errors import AiJobError
from ingest.translation_validation import validate_translation_fidelity
from ingest.myseoul_ai import generate_myseoul_output, myseoul_input, process_myseoul_job
from ingest.program_ai import ProgramAIAdapter
from ingest.reclassification_ai import process_reclassified_job, classification_input
from test_ingest_ai_claude import FakeClient, _message
from test_myseoul_ai import context as native_context
from test_reclassification_ai import context as classified_context, ID, REV

# (Korean, acceptable Japanese alternatives, misleading Japanese example).
# These are synthetic review cases, not output produced by Claude.
CONTEXTUAL_CASES = (
    ('행사 진행 기간', ('実施期間', '開催期間'), '進行期間'),
    ('진행 상황과 사회 진행', ('進行状況と司会進行',), '実施状況と社会実施'),
    ('영어로 진행합니다.', ('英語で行われます。', '英語で実施します。'), '英語進行です。'),
    ('한국어 1반', ('韓国語クラス1', '韓国語第1クラス'), '韓国語1クラス'),
    ('중급반', ('中級クラス',), '中級班'),
    ('실습은 1개 반, 팀 편성은 2개 조입니다.', ('実習は1クラス、チーム編成は2班です。',), '実習はクラス1、チーム編成はクラス2です。'),
    ('전화 상담 후 방문 접수', ('電話相談後、窓口で申し込み', '電話で相談した後、訪問して申し込みます。'), '電話での申し込みのみ'),
    ('방문자 접수', ('訪問受付', '来訪者の受付'), '窓口での受講申し込み'),
    ('내·외국인', ('韓国人・外国人',), '内・外国人'),
    ('자격증 취득 준비반', ('資格取得準備クラス',), '資格証受取クラス'),
    ('자격증 사본을 제출하세요.', ('資格証のコピーを提出してください。',), '資格を取得してください。'),
    ('디지털 역량 강화 교육', ('デジタル能力強化教育',), 'デジタル力量進行教育'),
    ('팀을 이끄는 역량', ('チームを率いる力量', 'チームを率いる能力'), 'チームに参加する能力'),
    ('마실 물을 지참하세요.', ('飲料水を持参してください。', '飲み水を持参してください。'), '飲み物を持参してください。'),
    ('참가자들의 단체 뒷모습', ('参加者の後ろ姿',), '団体の後ろ姿'),
    ('읽고 듣는 두 활동을 모두 수행합니다.', ('読む活動と聞く活動の両方を行います。',), '読むか聞くか、どちらかを行います。'),
    ('음성을 듣는 동시에 따라 말합니다.', ('音声を聞きながら、まねして話します。',), '音声を聞くか、まねして話します。'),
    ('프로그램 안내. 일본인 참가 가능 여부는 명시되어 있지 않습니다.', ('プログラム案内。日本人の参加可否は明記されていません。',), '日本人も参加できます。'),
    ('비수도권 주민만 신청 가능. F-2 비자와 보호자 동반 필수.', ('首都圏以外の住民のみ申請可能。F-2ビザと保護者同伴が必須です。',), 'どこに住んでいても、ビザや保護者同伴なしで申請できます。'),
    ('도시 숲을 탐방하고 프리저브드 플라워 액자를 만듭니다.', ('都市の森を探訪し、プリザーブドフラワーの額縁を作ります。',), '街で生花の花束を作ります。'),
    ('전문 해설사와 외국인 주민', ('専門解説員と外国人住民',), '参加者と観光客'),
)


def adapter_for(ko, ja, *, title_ja='合成案内'):
    client = FakeClient()
    client.messages.messages = [
        _message(json.dumps({'content_ko': ko, 'facts': {key: '' for key in SUMMARY_SCHEMA['properties']['facts']['required']}}, ensure_ascii=False)),
        _message(json.dumps({'title_ja': title_ja, 'content_ja': ja}, ensure_ascii=False)),
    ]
    return ClaudeAdapter(client=client), client


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_contextual_good_forms_are_not_blanket_banned(self):
        for ko, alternatives, bad in CONTEXTUAL_CASES:
            for ja in alternatives:
                with self.subTest(ko=ko, ja=ja):
                    adapter, client = adapter_for(ko, ja)
                    adapter.summarize_ko('합성 원문', 'https://synthetic.invalid')
                    self.assertEqual(adapter.translate_ja('합성 안내', ko)[1], ja)
                    self.assertEqual(len(client.messages.create_calls), 2)
                    self.assertNotEqual(ja, bad)

    def test_contextual_bad_examples_remain_explicit_model_review_cases(self):
        # No false claim that a regex can understand water, noun compounds,
        # mandatory alternatives or implicit eligibility. The review corpus
        # contains both sides, but fake output cannot prove model improvement.
        for ko, _, bad in CONTEXTUAL_CASES:
            with self.subTest(ko=ko):
                validate_translation_fidelity('합성 안내', ko, '合成案内', bad)

    def test_explicit_bad_values_fail_even_with_same_numbers_elsewhere(self):
        cases = (
            ('선착순 30명, 정원 도달 시 마감', '定員に達し次第締め切り。30日開催。'),
            ('선착순 30명, 정원 도달 시 마감', '定員30名。定員に達し次第締め切り。'),
            ('30명, 10회', '10名、30回'),
            ('18세 이상', '18歳以下'),
            ('18세 미만', '18歳以上'),
            ('10만원', '10,000ウォン'),
            ('신청기간: 2099-10-01 ~ 2099-10-02\n진행기간: 2099-11-01 ~ 2099-11-02', '申請期間: 2099年11月1日～2099年11月2日\n実施期間: 2099年10月1日～2099年10月2日'),
            ('신청기간: 2099-10-01 ~ 2099-10-02', '申請期間: 2099年10月2日～2099年10月1日'),
            ('신청기간: 10월 1일 ~ 10월 2일', '申請期間: 2099年10月1日～2099年10月2日'),
            ('신청기간: 2099-10-01 ~ 2099-10-02', '申請期間: 2099年10月1日0時00分～2099年10月2日0時00分'),
            ('집결 안내: 09:45', '集合案内: 10時00分。活動は09時45分に開始。'),
            ('수강료: 1,000원; 입장료: 3,000원', '受講料: 3,000ウォン; 入場料: 1,000ウォン'),
            ('비용: 수강료: 무료; 입장료: 3,000원', '費用: 受講料: 3,000ウォン; 入場料: 無料'),
            ('입장료: 3,000원', '入場料: 無料（3,000ウォン）'),
            ('신청 링크: https://synthetic.invalid/apply?course=1&lang=ko', '申請リンク: https://synthetic.invalid/apply?course=2&lang=ko'),
        )
        for ko, bad in cases:
            with self.subTest(ko=ko), self.assertRaises(AiJobError) as caught:
                validate_translation_fidelity('합성 안내', ko, '合成案内', bad)
            self.assertEqual(caught.exception.code, 'ai_schema_error')

    def test_correct_units_roles_synonyms_and_precision_pass(self):
        cases = (
            ('선착순 30명, 정원 도달 시 마감', '先着順で30人。定員に達し次第、締め切ります。'),
            ('선착순 30명', '定員30名（先着順）'),
            ('18세 이상, 10명, 3회', '18歳以上、10人、3回'),
            ('18세~39세', '18～39歳'),
            ('18세 이상 39세 이하', '18～39歳'),
            ('10만원, 20만 원, 1천원, 1,000원', '100,000ウォン、200,000ウォン、1,000ウォン、1,000ウォン'),
            ('신청 기간: 2099-10-01 ~ 2099-10-02', '申込受付期間：2099年10月1日～10月2日'),
            ('진행기간: 2099-11-01 10:00 ~ 2099-11-02 18:00', '開催期間: 2099年11月1日10時00分～2099年11月2日18時00分'),
            ('신청기간: 10월 1일 ~ 10월 2일', '応募期間: 10月1日～10月2日'),
            ('집결 안내: 09:45', '集合時間: 9時45分'),
            ('집결 시간: 18:00', '集合時間: 午後6時'),
            ('집결 시간: 10시', '集合時間: 10時'),
            ('수강료: 1천원; 입장료: 3,000원', '授業料: 1,000ウォン; 入場料: 3,000ウォン'),
            ('비용: 수강료: 무료; 재료비: 1,000원', '費用: 受講料: 無償; 材料費: 1,000ウォン'),
            ('신청 링크: https://synthetic.invalid/apply?id=Ａ1', '申請リンク: https://synthetic.invalid/apply?id=Ａ1'),
            ('신청 링크: https://synthetic.invalid/apply?id=1', '申請リンク: https://synthetic.invalid/apply?id=1。'),
        )
        for ko, ja in cases:
            with self.subTest(ko=ko):
                validate_translation_fidelity('합성 안내', ko, '合成案内', ja)

    def test_title_values_cannot_be_hidden_in_body(self):
        with self.assertRaises(AiJobError):
            validate_translation_fidelity('30명 모집', '합성 안내', '募集', '30名。合成案内')

    def test_sections_missing_extra_duplicate_or_reordered_fail(self):
        ko = '[한 줄 요약]\n합성 요약\n[주요 내용]\n합성 본문'
        for bad in ('[要約]\n案内', '[要約]\n案内\n[対象]\n対象\n[主な内容]\n本文',
                    '[主な内容]\n本文\n[要約]\n案内', '[要約]\n案内\n[要約]\n案内\n[主な内容]\n本文',
                    '全体的に良い翻訳です。\n[要約]\n案内\n[主な内容]\n本文'):
            with self.subTest(bad=bad), self.assertRaises(AiJobError):
                validate_translation_fidelity('합성', ko, '合成', bad)

    def test_extra_explanations_and_code_fences_are_not_json_contract(self):
        ko = '합성 본문'
        for output in ({'title_ja': '合成', 'content_ja': '本文', 'changes': ['修正']},
                       '```json\n{"title_ja":"合成","content_ja":"本文"}\n```',
                       '全体的に良い翻訳です。'):
            adapter, client = adapter_for(ko, '本文')
            text = json.dumps(output) if isinstance(output, dict) else output
            client.messages.messages[1] = _message(text)
            adapter.summarize_ko('合成', None)
            with self.subTest(output=output), self.assertRaises(AiJobError):
                adapter.translate_ja('합성', ko)
            self.assertEqual(len(client.messages.create_calls), 2)

    def test_prompt_growth_keeps_existing_cost_and_call_limits(self):
        self.assertEqual(CLAUDE_JOB_USD_CAP, .10)
        def cost(n):
            return conservative_cost_usd(n, SUMMARY_MAX_TOKENS) + conservative_cost_usd(n + SUMMARY_MAX_TOKENS + CLAUDE_TRANSLATION_INPUT_RESERVE_TOKENS, TRANSLATION_MAX_TOKENS)
        boundary = next(n for n in range(10000) if cost(n) > .10)
        adapter, client = adapter_for('합성', '合成')
        client.messages.count_values = [boundary, 120]
        with self.assertRaises(AiJobError) as caught:
            adapter.summarize_ko('합성', None)
        self.assertEqual(caught.exception.code, 'ai_blocked_cost_cap')
        self.assertEqual(client.messages.create_calls, [])
        adapter, client = adapter_for('합성', '合成')
        client.messages.count_values = [boundary - 1, 120]
        adapter.summarize_ko('합성', None)
        adapter.translate_ja('합성', '합성')
        self.assertEqual(len(client.messages.count_calls), 2)
        self.assertEqual(len(client.messages.create_calls), 2)

    def test_native_complete_reviewed_body_uses_shared_request_and_no_mutation(self):
        c = native_context()
        f = c['facts']
        f.update(target='보호자 동반', conditions=[], age=[], companion=[], language=[], residence='',
                 qualification_note='', venue='', fees=[], session_evidence=[], meeting_evidence=[],
                 application_methods=['방문 신청'], application_links=[])
        f['periods'] = {'application': [], 'operation': []}
        f['description'] = '합성 이미지에서 검토자가 보완한 설명'
        c['observedFacts']['description'] = ''
        before = copy.deepcopy(c)
        ja = '[要約]\n合成案内\n[対象]\n保護者同伴\n[期間・状況]\n申請期間: 公式案内確認\n実施期間: 公式案内確認\n[主な内容]\n画像で確認した活動\n[申請方法]\n窓口申込'
        adapter, client = adapter_for('[한 줄 요약]\n합성 요약\n[주요 내용]\n검토자가 확인한 활동', ja)
        output = generate_myseoul_output(c, summarize_ko=adapter.summarize_ko, translate_ja=adapter.translate_ja)
        self.assertEqual(output['contentJa'], ja)
        self.assertEqual(client.messages.create_calls[1]['messages'][0]['content'], f"title_ko: {c['title']}\ncontent_ko:\n{output['contentKo']}")
        data = json.loads(myseoul_input(c))
        self.assertEqual(data['currentFacts']['description'], f['description'])
        self.assertIn('description', data['operatorSupplementedFields'])
        self.assertEqual(c, before)
        self.assertEqual(client.messages.create_calls[1]['system'], translation_system_prompt())

    def test_reclassified_image_supplement_and_candidate_fence_use_shared_translation(self):
        for category in ('program', 'event', 'youth_space', 'policy', 'living'):
            with self.subTest(category=category):
                c = classified_context(category)
                c['body'] = ''
                c['nativeConfirmedFacts']['programFacts'] = {'description': '합성 이미지 보완 설명', 'conditions': ['보호자 동반']}
                before = copy.deepcopy(c)
                ja = '[要約]\n合成案内\n[主な内容]\n合成活動\n確認した分類・参加案内\n保護者同伴'
                if category == 'program': ja += '\n申請締切: 2099年10月15日'
                if category == 'event': ja += '\n開催期間: 2099年10月9日～2099年10月9日'
                adapter, client = adapter_for('[한 줄 요약]\n합성 안내\n[주요 내용]\n합성 활동', ja)
                calls = []
                def rpc(name, args):
                    calls.append((name, args))
                    if name == 'claim_reclassified_content_ai': return c
                    if name == 'finish_reclassified_content_ai': return {'outcome': 'inserted', 'candidateId': ID}
                    self.fail(name)
                result = process_reclassified_job(ProgramAIAdapter(rpc), source_item_id=ID, revision=REV, classification_version=1,
                    worker_id='synthetic-worker', summarize_ko=adapter.summarize_ko, translate_ja=adapter.translate_ja)
                self.assertEqual(result.completed, 1)
                self.assertEqual(json.loads(classification_input(c))['operatorSupplementedText'], '합성 이미지 보완 설명')
                self.assertEqual(c, before)
                finished = calls[-1][1]
                self.assertEqual(finished['p_revision'], REV)
                self.assertEqual(finished['p_classification_version'], 1)
                self.assertEqual(finished['p_claimed_at'], c['claimedAt'])
                self.assertEqual(finished['p_lease_until'], c['leaseUntil'])
                self.assertEqual(client.messages.create_calls[1]['system'], translation_system_prompt())
                self.assertEqual(client.messages.create_calls[1]['messages'][0]['content'], f"title_ko: {c['title']}\ncontent_ko:\n{finished['p_output']['contentKo']}")

    def test_invalid_translation_never_finishes_reclassified_candidate_or_retries_provider(self):
        c = classified_context('program')
        c['nativeConfirmedFacts']['programFacts'] = {}
        ja = '[要約]\n合成案内\n[主な内容]\n30日'
        adapter, client = adapter_for('[한 줄 요약]\n합성 안내\n[주요 내용]\n선착순 30명', ja)
        calls = []
        def rpc(name, args):
            calls.append((name, args))
            if name == 'claim_reclassified_content_ai': return c
            if name == 'reclassified_content_ai_status': return {'status': 'active'}
            self.fail('invalid output must not finish')
        result = process_reclassified_job(ProgramAIAdapter(rpc), source_item_id=ID, revision=REV, classification_version=1,
            worker_id='synthetic-worker', summarize_ko=adapter.summarize_ko, translate_ja=adapter.translate_ja)
        self.assertEqual(result.completed, 0)
        self.assertEqual(result.state_unknown, 1)
        self.assertEqual([name for name, _ in calls], ['claim_reclassified_content_ai', 'reclassified_content_ai_status'])
        self.assertFalse(calls[-1][1]['p_close_expired'])
        self.assertEqual(len(client.messages.create_calls), 2)

    def test_invalid_native_translation_uses_existing_fenced_failure_path(self):
        c = native_context()
        ko = '[한 줄 요약]\n합성 안내\n[주요 내용]\n합성 활동\n' + '\n'.join(c['facts']['conditions'])
        adapter, client = adapter_for(ko, '[要約]\n合成案内\n[主な内容]\n本文')
        calls = []
        def rpc(name, args):
            calls.append((name, args))
            if name == 'claim_myseoul_program_ai': return [c]
            if name == 'fail_myseoul_program_ai': return 'failed'
            self.fail('invalid native output must not finish')
        result = process_myseoul_job(ProgramAIAdapter(rpc), source_item_id=c['sourceItemId'],
            revision=c['revision'], worker_id=c['workerId'], summarize_ko=adapter.summarize_ko, translate_ja=adapter.translate_ja)
        self.assertEqual(result.completed, 0)
        self.assertEqual(result.failed, 1)
        self.assertEqual([name for name, _ in calls], ['claim_myseoul_program_ai', 'fail_myseoul_program_ai'])
        self.assertEqual(calls[-1][1]['p_error_code'], 'ai_schema_error')
        self.assertEqual(calls[-1][1]['p_claimed_at'], c['claimedAt'])
        self.assertEqual(calls[-1][1]['p_lease_until'], c['leaseUntil'])
        self.assertEqual(len(client.messages.create_calls), 2)


if __name__ == '__main__':
    unittest.main()
