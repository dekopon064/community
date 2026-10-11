"""Offline regression from the actual synthetic Pro summary; Japanese is a fake fixture."""
import copy
import json
import socket
import sys
import unittest
from unittest.mock import patch
from ingest.ai_errors import AiJobError
from ingest.body_markdown import read_body
from ingest.myseoul_content import deduplicate_summary_venue
from ingest.myseoul_ai import generate_myseoul_output
from test_body_markdown_pipeline import synthetic_context, run_fixture

SOURCE = '이 안내는 실제 기관·모집 정보가 아닌 합성 시험 자료입니다.\n성인과 어린이 가족이 문서 작성과 제출을 실습합니다. 보호자 동반 필수이며 선착순 30명입니다.\n신청기간: 2026년 10월 1일 ~ 10월 2일\n진행기간: 2026년 10월 3일 ~ 10월 10일\n교육 일정\n1회차: 10월 3일 10:00~11:30 / 활동: 문서 작성\n2회차: 10월 10일 14:00~15:30 / 활동: 문서 제출\n실습 순서\n1. 문서를 작성합니다.\n2. 작성한 문서를 제출합니다.\n준비물: 마실 물\n장소: 서울 합성 교육실\n수강료: 10,000원 / 재료비: 2,000원 (별도)\n온라인 신청: https://synthetic.invalid/apply?id=1\n'

ACTUAL_SUMMARY = {'content_ko': '[한 줄 요약]\n성인과 어린이 가족이 문서 작성과 제출을 실습하는 합성 시험용 프로그램입니다.\n\n[대상]\n- 성인과 어린이 가족\n- **보호자 동반 필수**\n- 선착순 30명\n\n[일정 안내]\n- 신청기간: 2026년 10월 1일~10월 2일\n- 진행기간: 2026년 10월 3일~10월 10일\n\n| 회차 | 일시 | 활동 |\n| --- | --- | --- |\n| 1회차 | 10월 3일 10:00~11:30 | 문서 작성 |\n| 2회차 | 10월 10일 14:00~15:30 | 문서 제출 |\n\n[주요 내용]\n이 안내는 **실제 기관·모집 정보가 아닌 합성 시험 자료**입니다. 가족이 함께 문서를 작성하고 제출하는 과정을 실습합니다.\n\n실습 순서\n1. 문서를 작성합니다.\n2. 작성한 문서를 제출합니다.\n\n- 준비물: 마실 물\n- 장소: 서울 합성 교육실\n\n[신청 방법]\n온라인 신청: https://synthetic.invalid/apply?id=1', 'facts': {'audience': '성인과 어린이 가족. 보호자 동반 필수. 선착순 30명.', 'geo_age_income': '장소: 서울 합성 교육실.', 'amount_period_deadline': '수강료: 10,000원. 재료비: 2,000원 별도. 신청기간: 2026년 10월 1일~10월 2일. 진행기간: 2026년 10월 3일~10월 10일. 실제 교육 일정: 1회차 10월 3일 10:00~11:30 문서 작성, 2회차 10월 10일 14:00~15:30 문서 제출.', 'how_to_apply': '온라인 신청: https://synthetic.invalid/apply?id=1'}}

OLD_BODY = '[한 줄 요약]\n\n성인과 어린이 가족이 문서 작성과 제출을 실습하는 합성 시험용 프로그램입니다.\n\n[대상]\n\n성인과 어린이 가족\n\n[일정 안내]\n\n- **신청기간:** 2026-10-01 ~ 2026-10-02\n- **진행기간:** 2026-10-03 ~ 2026-10-10\n- **진행 일정:** 1회차: 10월 3일 10:00~11:30 / 2회차: 10월 10일 14:00~15:30\n\n[주요 내용]\n\n이 안내는 **실제 기관·모집 정보가 아닌 합성 시험 자료**입니다. 가족이 함께 문서를 작성하고 제출하는 과정을 실습합니다.\n\n실습 순서\n1. 문서를 작성합니다.\n2. 작성한 문서를 제출합니다.\n\n- 준비물: 마실 물\n- 장소: 서울 합성 교육실\n- **참가 조건:** 보호자 동반 필수\n\n- **장소:** 서울 합성 교육실\n- **비용:** 수강료: 10,000원; 재료비: 2,000원\n- **모집 인원:** 선착순 30명\n\n[신청 방법]\n\n온라인 신청\n- **신청 링크:** https://synthetic.invalid/apply?id=1'

OLD_JA = '[要約]\n\n大人と子どもの家族が文書の作成と提出を実習する、合成テスト用プログラムです。\n\n[対象]\n\n大人と子どもの家族\n\n[日程案内]\n\n- **申請期間:** 2026年10月1日～2026年10月2日\n- **実施期間:** 2026年10月3日～2026年10月10日\n- **実施日程:** 第1回: 10月3日 10時00分～11時30分 / 第2回: 10月10日 14時00分～15時30分\n\n[主な内容]\n\nこの案内は**実際の機関・募集情報ではなく、合成テスト資料**です。家族で一緒に文書を作成し、提出する過程を実習します。\n\n実習の順序\n1. 文書を作成します。\n2. 作成した文書を提出します。\n\n- 持ち物: 飲料水\n- 場所: ソウル合成教育室\n- **参加条件:** 保護者の同伴が必須です\n\n- **場所:** ソウル合成教育室\n- **費用:** 受講料: 10,000ウォン; 材料費: 2,000ウォン\n- **募集人数:** 先着30名\n\n[申請方法]\n\nオンライン申請\n- **申請リンク:** https://synthetic.invalid/apply?id=1'

TABLE = "| 회차 | 일시 | 활동 |\n| --- | --- | --- |\n| 1회차 | 10월 3일 10:00~11:30 | 문서 작성 |\n| 2회차 | 10월 10일 14:00~15:30 | 문서 제출 |"
# Handwritten Japanese fixture, never a new model response.
JA_TABLE = "| 回 | 日時 | 活動 |\n| --- | --- | --- |\n| 第1回 | 10月3日 10時00分～11時30分 | 文書の作成 |\n| 第2回 | 10月10日 14時00分～15時30分 | 文書の提出 |"
FAKE_JA = (OLD_JA.replace("\n\n[主な内容]", "\n\n" + JA_TABLE + "\n\n[主な内容]")
    .replace("- 場所: ソウル合成教育室\n", "")
    .replace("- **実施日程:** 第1回: 10月3日 10時00分～11時30分 / 第2回: 10月10日 14時00分～15時30分",
             "**実施日程:**\n- 第1回: 10月3日 10時00分～11時30分\n- 第2回: 10月10日 14時00分～15時30分"))


def replay_context():
    c = synthetic_context()
    c['facts']['description'] = SOURCE
    return c


class ActualSummaryRegressionTests(unittest.TestCase):
    def assemble(self, ko=None):
        c = replay_context()
        before = copy.deepcopy(c)
        inputs = []
        def translate(title, body):
            inputs.append(body)
            return '合成文書実習プログラム', FAKE_JA, 'success', 'fake-model'
        output = generate_myseoul_output(c,
            summarize_ko=lambda *a, **kw: (ko or ACTUAL_SUMMARY['content_ko'], 'success', 'fake-model'),
            translate_ja=translate)
        self.assertEqual(c, before)
        return output, inputs

    def test_actual_period_table_survives_assembly(self):
        output, inputs = self.assemble()
        self.assertIn(TABLE, output['contentKo'])
        self.assertEqual(inputs, [output['contentKo']])
        self.assertLess(output['contentKo'].index(TABLE), output['contentKo'].index('[주요 내용]'))

    def test_actual_bare_venue_is_not_duplicated(self):
        output, _ = self.assemble()
        self.assertEqual(output['contentKo'].count('서울 합성 교육실'), 1)
        self.assertIn('- **장소:** 서울 합성 교육실', output['contentKo'])

    def test_real_summary_fake_translation_and_rpc_complete_with_fences(self):
        c, result, calls, client, candidates = run_fixture(ko=ACTUAL_SUMMARY['content_ko'],
            ja=FAKE_JA, fixture_context=replay_context(), summary_facts=ACTUAL_SUMMARY['facts'])
        self.assertEqual(result.completed, 1)
        self.assertEqual(len(client.calls), 2)  # Injected responses, no live calls.
        self.assertEqual(len(candidates), 1)
        out = candidates[0]
        self.assertIn(TABLE, out['contentKo'])
        self.assertEqual(read_body(out['contentKo']).tables[0].rows,
                         read_body(TABLE).tables[0].rows)
        self.assertEqual(out['contentKo'].count('서울 합성 교육실'), 1)
        self.assertEqual(out['contentJa'].count('ソウル合成教育室'), 1)
        self.assertEqual(out['contentJa'].strip(), FAKE_JA.strip())
        self.assertIn(out['contentKo'], client.calls[1]['input'][0]['content'])
        request = client.calls[0]['input'][0]['content']
        self.assertEqual(json.loads(request[request.index('{'):])['currentFacts']['description'], SOURCE)
        self.assertEqual(c, replay_context())
        for parameter, key in (('p_revision','revision'), ('p_facts_version','factsVersion'),
                               ('p_claimed_at','claimedAt'), ('p_lease_until','leaseUntil')):
            self.assertEqual(calls[-1][1][parameter], c[key])

    def test_session_conflicts_stop_before_translation_and_finish(self):
        wrong = [
            TABLE.replace('14:00~15:30', '10:00~11:30'),
            TABLE.replace('10월 10일', '10월 9일'),
            TABLE.replace('10월 10일', '2027년 10월 10일'),
            TABLE.replace('| 1회차 |', '| 2회차 |', 1),
            TABLE.replace('문서 작성 |', '문서 제출 |', 1),
            '\n'.join(TABLE.splitlines()[:2] + TABLE.splitlines()[2:][::-1]),
            TABLE + '\n' + TABLE.splitlines()[2],
            TABLE.replace('10:00~11:30', '11:30~10:00'),
        ]
        for table in wrong:
            with self.subTest(table=table):
                _, result, calls, client, candidates = run_fixture(
                    ko=ACTUAL_SUMMARY['content_ko'].replace(TABLE, table), ja=FAKE_JA,
                    fixture_context=replay_context())
                self.assertEqual(result.failed, 1)
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(candidates, [])
                self.assertFalse(any(name.startswith('finish_') for name, _ in calls))

    def test_omitted_table_row_does_not_erase_reviewed_session(self):
        table = '\n'.join(TABLE.splitlines()[:-1])
        out, _ = self.assemble(ACTUAL_SUMMARY['content_ko'].replace(TABLE, table))
        self.assertIn('2회차: 10월 10일 14:00~15:30', out['contentKo'])
        self.assertIn(table, out['contentKo'])

    def test_split_columns_bare_numbers_and_day_precision_are_preserved(self):
        c = replay_context()
        c['facts']['session_evidence'] = [text.replace('회차:', '차:') for text in c['facts']['session_evidence']]
        for table in (
            '| 회차 | 날짜 | 시간 | 활동 |\n| --- | --- | --- | --- |\n'
            '| 1 | 10월 3일 | 10:00~11:30 | 문서 작성 |\n'
            '| 2 | 10월 10일 | 14:00~15:30 | 문서 제출 |',
            '| 회차 | 수업일 | 활동 |\n| --- | --- | --- |\n'
            '| 1차 | 10월 3일 | 문서 작성 |\n| 2차 | 10월 10일 | 문서 제출 |'):
            with self.subTest(table=table):
                before = copy.deepcopy(c)
                out = generate_myseoul_output(c,
                    summarize_ko=lambda *a, **kw:(ACTUAL_SUMMARY['content_ko'].replace(TABLE, table), 'success', 'fake'),
                    translate_ja=lambda *a:('合成', FAKE_JA, 'success', 'fake'))
                self.assertIn(table, out['contentKo'])
                self.assertIn('2차: 10월 10일 14:00~15:30', out['contentKo'])
                self.assertEqual(c, before)

    def test_activity_only_table_cannot_bypass_labeled_source_activities(self):
        table = '| 회차 | 활동 |\n| --- | --- |\n| 1회차 | 문서 제출 |\n| 2회차 | 문서 작성 |'
        with self.assertRaises(AiJobError):
            self.assemble(ACTUAL_SUMMARY['content_ko'].replace(TABLE, table))

    def test_wrong_or_missing_translation_table_never_finishes(self):
        for ja in (OLD_JA, FAKE_JA.replace(JA_TABLE, ''),
                   FAKE_JA.replace('第1回 | 10月3日', '第1回 | 10月10日'),
                   FAKE_JA.replace('14時00分～15時30分 |', '10時00分～11時30分 |')):
            with self.subTest(ja=ja):
                _, result, calls, client, candidates = run_fixture(ko=ACTUAL_SUMMARY['content_ko'],
                    ja=ja, fixture_context=replay_context())
                self.assertEqual(result.failed, 1)
                self.assertEqual(len(client.calls), 2)
                self.assertEqual(candidates, [])

    def test_venue_cleanup_keeps_qualified_prose_tables_and_other_values(self):
        venue = '서울 합성 교육실'
        for line in ('- 장소: '+venue, '- **장소:** '+venue, '장소: 서울  합성 교육실'):
            self.assertEqual(deduplicate_summary_venue(line, venue), '')
        for text in ('장소: 서울 합성 교육실, 보호자 동반 필수',
                     '장소: 서울 합성 교육실 (지하철 이용)',
                     '서울 합성 교육실에서 집결한 뒤 이동합니다.',
                     '장소: 다른 교육실', '| 장소 | 안내 |\n| --- | --- |\n| 서울 합성 교육실 | 보호자 동반 필수 |'):
            self.assertEqual(deduplicate_summary_venue(text, venue), text)
            self.assertEqual(deduplicate_summary_venue(text, ''), text)
        result = deduplicate_summary_venue('실습 안내\n- 장소: '+venue+'\n- 준비물: 물', venue)
        self.assertEqual(deduplicate_summary_venue(result, venue), result)

    def test_unknown_finish_keeps_existing_no_retry_contract(self):
        _, result, calls, client, candidates = run_fixture(ko=ACTUAL_SUMMARY['content_ko'],
            ja=FAKE_JA, fixture_context=replay_context(), unknown=True)
        self.assertEqual(result.state_unknown, 1)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(sum(name.startswith('finish_') for name, _ in calls), 1)

    def test_reclassified_myseoul_keeps_table_and_uses_same_conflict_guard(self):
        from ingest.reclassification_ai import process_reclassified_job, protected_information
        from ingest.program_ai import ProgramAIAdapter
        from test_reclassification_ai import context as classified_context
        c = classified_context('program')
        native = replay_context()['facts']
        c['nativeConfirmedFacts']['programFacts'] = native
        c['facts'].update(deadlineOn='2026-10-02')
        c['filters']['application']['value'].update(
            start=copy.deepcopy(native['periods']['application'][0]['endpoints'][0]),
            end=copy.deepcopy(native['periods']['application'][0]['endpoints'][1]))
        before = copy.deepcopy(c)
        for ko in (ACTUAL_SUMMARY['content_ko'], ACTUAL_SUMMARY['content_ko'].replace('14:00~15:30 |', '10:00~11:30 |')):
            calls, translated = [], []
            def rpc(name, args):
                calls.append((name, copy.deepcopy(args)))
                if name == 'claim_reclassified_content_ai': return copy.deepcopy(c)
                if name == 'finish_reclassified_content_ai': return {'outcome':'inserted', 'candidateId':c['sourceItemId']}
                return {'status':'active'}
            def ja(title, body):
                translated.append(body)
                self.assertIn(TABLE, body)
                from test_reclassification_ai import assert_public_facts
                assert_public_facts(self, c, body)
                return '合成案内', '''[要約]
大人と子どもの家族が文書の作成と提出を実習する、合成テスト用プログラムです。

[対象]
- 大人と子どもの家族
- **保護者同伴が必須**
- 先着30名

[日程案内]
- 申請期間: 2026年10月1日～10月2日
- 実施期間: 2026年10月3日～10月10日

''' + JA_TABLE + '''

[主な内容]
この案内は**実際の機関・募集情報ではなく、合成テスト資料**です。家族で一緒に文書を作成し、提出する過程を実習します。

実習の順序
1. 文書を作成します。
2. 作成した文書を提出します。

- 持ち物: 飲料水
- 場所: ソウル合成教育室

[申請方法]
オンライン申請: https://synthetic.invalid/apply?id=1

確認済みの分類・参加案内
- **分類:** プログラム
- **実施方式:** オンライン
- **参加対象の根拠:** 合成の全国申請の根拠
- **申請締切:** 2026年10月2日
- **参加条件:** 保護者の同伴が必須です
- **申請方法:** オンライン申請
- **費用:** 受講料: 10,000ウォン; 材料費: 2,000ウォン
- **募集人数:** 先着30名
- **実施日程:** 第1回: 10月3日10時00分～11時30分 / 第2回: 10月10日14時00分～15時30分
- **申請期間:** 2026年10月1日～2026年10月2日
- **実施期間:** 2026年10月3日～2026年10月10日
''', 'success', 'fake'
            with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
                result = process_reclassified_job(ProgramAIAdapter(rpc), source_item_id=c['sourceItemId'],
                    revision=c['revision'], classification_version=c['classificationVersion'], worker_id=c['workerId'],
                    summarize_ko=lambda *a, **kw:(ko, 'success', 'fake'), translate_ja=ja)
            if ko == ACTUAL_SUMMARY['content_ko']:
                self.assertEqual(result.completed, 1)
                self.assertEqual(len(translated), 1)
                self.assertEqual(calls[-1][1]['p_classification_version'], c['classificationVersion'])
            else:
                self.assertEqual(translated, [])
                self.assertFalse(any(name.startswith('finish_') for name, _ in calls))
            self.assertEqual(c, before)


if __name__ == '__main__':
    if '--fixture' in sys.argv:
        c, result, calls, client, candidates = run_fixture(ko=ACTUAL_SUMMARY['content_ko'],
            ja=FAKE_JA, fixture_context=replay_context(), summary_facts=ACTUAL_SUMMARY['facts'])
        if result.completed != 1: raise RuntimeError('offline replay candidate did not complete')
        print(json.dumps({'syntheticOnly':True, 'source':SOURCE, 'facts':c['facts'], 'output':candidates[0],
            'calls':len(client.calls), 'fence':calls[-1][1], 'translation':'handwritten fake fixture'}, ensure_ascii=False))
    else:
        unittest.main()
