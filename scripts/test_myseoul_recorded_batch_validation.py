"""Recorded Pro responses, offline only. New translations are fake fixtures."""
import copy
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import Mock, patch

from ingest.ai_errors import AiJobError
from ingest.myseoul_ai import fact_sections, process_myseoul_job
from ingest.myseoul_content import validate_summary_period
from ingest.reclassification_ai import protected_information, process_reclassified_job
from ingest.program_ai import ProgramAIAdapter
from ingest.translation_validation import validate_translation_fidelity
from test_myseoul_ai import context as native_context
from test_myseoul_schedule_blocks import reviewed_detail
from test_reclassification_ai import context as classified_context


CASES = json.loads((Path(__file__).parent / 'testdata/myseoul_recorded_batch_responses.json').read_text(encoding='utf-8'))['cases']

# Handwritten replacements for the JSON tail only. The prefix is the recorded
# model translation, not evidence that the model generated this new body.
FAKE_PROTECTED_JA = {
    0: '''確認済みの分類・参加案内
分類：プログラム
実施方式：オフライン
申請締切：2026年10月17日
申請方法：来所,電話
費用：受講料：無料
募集人数：20名
実施日程：2026年10月24日（土）13時30分～17時00分 / 家族プログラムは9月～11月に計3回実施され、3回すべてに参加した家族にはプレゼントと修了証が提供されます。
申請期間：2026年10月1日10時00分～2026年10月17日18時00分（+09:00）
実施期間：2026年10月24日13時30分～2026年10月24日17時00分''',
    1: '''確認済みの分類・参加案内
分類：プログラム
実施方式：オフライン
申請締切：2026年10月25日
申請方法：その他（Googleフォーム）
費用：受講料：無料
募集人数：30名
実施日程：10月29日（木）～10月30日（金）13時00分～17時30分
申請期間：2026年10月8日00時00分+09:00～2026年10月25日23時50分+09:00
実施期間：2026年10月29日13時00分～2026年10月30日17時30分''',
    3: '''確認済みの分類・参加案内
分類：プログラム
実施方式：オフライン
申請締切：2026年10月21日
参加条件：子どもは接種できません。
申請方法：来所、オンライン
費用：受講料：無料
募集人数：20名
実施日程：第1回50名：2026年10月25日（日）14時00分～16時00分（予定） / 第2回50名：2026年11月8日（日）14時00分～16時00分（予定） / 第1回50名：2026年10月25日（日）14時00分～16時00分（変更の可能性あり） / 第2回50名：2026年11月8日（日）14時00分～16時00分（変更の可能性あり） / 第1回50名：2026年10月25日（日）14時00分～16時00分（日時が変更される可能性あり） / 第2回50名：2026年11月8日（日）14時00分～16時00分（日時が変更される可能性あり） / 第1回（50名）：2026年10月25日（日）14時00分～16時00分（実施予定確定） / 第2回（50名）：2026年11月8日（日）14時00分～16時00分（実施予定確定）
申請期間：2026年10月8日01時00分+09:00～2026年10月21日18時30分+09:00
実施期間：2026年10月25日14時00分～2026年10月25日16時00分''',
    4: '''確認済みの分類・参加案内
分類：プログラム
実施方式：オフライン
申請締切：2026年10月13日
申請方法：その他（Googleフォーム）
費用：受講料：無料
募集人数：20名
申請期間：2026年10月8日00時00分+09:00～2026年10月13日00時00分+09:00
実施期間：2026年10月15日10時00分～2026年10月15日11時30分''',
}

# TOPIK translation was never called in the live batch; this entire fixture is fake.
FAKE_ONLINE_JA = '''[要約]
ヤンチョン外国人住民センターが外国人住民向けの韓国語TOPIKクラス1をオンラインで実施します。
[対象]
外国人住民
[日程案内]
申請期間：2026年9月28日10:00～2026年10月15日18:00
実施期間：2026年10月18日12:00～2026年11月8日15:00
実施日程：毎週日曜日、10月18日～11月8日、全4回、1回3時間
[主な内容]
ZOOMのオンライン授業です。この案内ではTOPIKクラス1のみ申し込めます。他のレベルのクラスは申し込めません。
費用：受講料：無料
募集人数：20名
実施方式：オンライン
[申請方法]
オンライン
申請リンク：https://forms.gle/ziWmG2CKaaD3gu2N9?fbclid=IwZXh0bgNhZW0CMTAAcGRvZgFicmlkETFEVFJMcFZQd2JsSkMyQzVac3J0YwZhcHBfaWQQMjIyMDM5MTc4ODIwMDg5MgABHr70cEf-rnl3As_hNzIezXVoHhqTilygZnkHsb50OLfr9uk7f9trtzhufH_3_aem_KNMYNkZGAKfqkzTSy-h3ZQ / https://forms.gle/ziWmG2CKaaD3gu2N9?fbclid=IwZXh0bgNhZW0CMTAAcGRvZgFicmlkETFEVFJMcFZQd2JsSkMyQzVac3J0YwZhcHBfaWQQMjIyMDM5MTc4ODIwMDg5MgABHq8GVS1LnLu_z7nM8OwPNNMlQ80BTJMkqptxFhwu3DRZYozQGfKmC3uhLjFU_aem_Oq0Pc_S-URH_10nG1sLi9Q'''


def replay_context(index):
    case = CASES[index]
    c = classified_context('program') if case['route'] == 'classified' else native_context()
    c.update(copy.deepcopy(case['context']))
    c['title'] = case['name']
    if case['route'] == 'classified':
        c['nativeConfirmedFacts']['programFacts']['source_revision'] = c['revision']
    else:
        c['facts']['source_revision'] = c['revision']
        c['observedFacts'] = copy.deepcopy(c['facts'])
    return c


class RecordedBatchValidationTests(unittest.TestCase):
    def setUp(self):
        network = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        network.start()
        self.addCleanup(network.stop)

    def test_recorded_family_translation_timezone_is_not_a_third_clock(self):
        case = CASES[0]
        ja = case['translation']
        validate_translation_fidelity(case['name'], case['previousTranslationInput']['contentKo'], ja['title_ja'], ja['content_ja'])

    def test_recorded_online_date_period_matches_timestamp_bounds(self):
        case = CASES[2]
        f = case['context']['facts']
        validate_summary_period(case['summary']['content_ko'], fact_sections(f)['[일정 안내]'], f)

    def test_recorded_classified_protection_is_readable_not_json(self):
        for case in CASES:
            if case['route'] != 'classified':
                continue
            c = copy.deepcopy(case['context'])
            before = copy.deepcopy(c)
            text = protected_information(c)
            self.assertNotRegex(text, r'\["|\{\s*"|"evidence"|"component"')
            self.assertIn('수강료: 무료', text)
            self.assertEqual(c, before)

    def test_timezone_equivalent_instants_and_normal_clock_ranges(self):
        for ko, ja in (
            ('신청기간: 2026-10-01T01:00:00Z ~ 2026-10-17T09:00:00Z',
             '申請期間: 2026年10月1日10時00分～2026年10月17日18時00分（UTC+09:00）'),
            ('신청기간: 2026-10-01T10:00:00+09:00 ~ 2026-10-17T18:00:00+09:00',
             '申請期間: 2026-10-01T10:00:00+09:00 ~ 2026-10-17T18:00:00+09:00'),
            ('집결 시간: 10:00-17:30', '集合時間: 10時00分-17時30分'),
            ('회당 3시간', '1回180分間'),
        ):
            with self.subTest(ko=ko):
                validate_translation_fidelity('합성', ko, '合成', ja)

    def test_changed_timezone_clock_seconds_and_precision_still_fail(self):
        ko = '신청기간: 2026-10-01T10:00:00+09:00 ~ 2026-10-17T18:00:00+09:00'
        for ja in (
            '申請期間: 2026年10月1日10時00分～2026年10月17日18時00分（UTC+08:00）',
            '申請期間: 2026-10-01T10:00:00+08:00 ~ 2026-10-17T18:00:00+08:00',
            '申請期間: 2026-10-01T10:00:00+0800 ~ 2026-10-17T18:00:00+0800',
            '申請期間: 2026年10月1日11時00分～2026年10月17日18時00分',
            '申請期間: 2026年10月1日10時00分01秒～2026年10月17日18時00分',
            '申請期間: 2026年10月1日～2026年10月17日',
        ):
            with self.subTest(ja=ja), self.assertRaises(AiJobError):
                validate_translation_fidelity('합성', ko, '合成', ja)
        with self.assertRaises(AiJobError):
            validate_translation_fidelity('합성', '회당 3시간', '合成', '1回2時間')

    def test_date_and_clock_omission_is_allowed_but_conflicting_endpoints_are_not(self):
        f = CASES[2]['context']['facts']
        canonical = fact_sections(f)['[일정 안내]']
        for line in ('교육 기간: 2026년 10월 18일~11월 8일', '교육 기간: 10월 18일~11월 8일',
                     '교육 기간: 2026년 10월 18일 12:00~11월 8일',
                     '교육 기간: 2026년 10월 18일~11월 8일 15:00'):
            validate_summary_period(line, canonical, f)
        for line in (
            '교육 기간: 2027년 10월 18일~11월 8일',
            '교육 기간: 2026년 10월 19일~11월 8일',
            '교육 기간: 2026년 11월 8일~10월 18일',
            '교육 기간: 2026년 10월 18일 15:00~11월 8일',
            '교육 기간: 2026년 10월 18일~11월 8일 12:00',
            '교육 기간: 2026년 10월 18일 12:00~15:00, 11월 8일',
            '교육일시 안내 범위: 2026년 10월 18일 13:00~11월 8일 15:00',
            '교육 기간: 2026년 10월 18일~11월 8일, 총 5회',
            '교육 기간: 2026년 10월 18일~11월 8일, 총 4회, 회당 2시간',
            '신청기간: 2026년 10월 18일~11월 8일',
        ):
            with self.subTest(line=line), self.assertRaises(AiJobError):
                validate_summary_period(line, canonical, f)

    def test_fee_components_and_conditions_are_not_serialized_or_lost(self):
        c = replay_context(1)
        native = c['nativeConfirmedFacts']['programFacts']
        native['fees'] = [{'component':'tuition','evidence':['10,000원, 교재 포함']},
                          {'component':'materials','evidence':['2,000원, 환불 불가']}]
        native['conditions'] = ['F-2 비자 필수', '보호자 없이 참가 불가']
        native['residence'] = '서울 거주자만'
        before = copy.deepcopy(c)
        text = protected_information(c)
        for value in ('수강료: 10,000원, 교재 포함', '재료비: 2,000원, 환불 불가',
                      'F-2 비자 필수', '보호자 없이 참가 불가', '서울 거주자만'):
            self.assertIn(value, text)
        self.assertEqual(c, before)
        native['fees'][0]['unrecognized_condition'] = '삭제해서는 안 되는 조건'
        with self.assertRaises(ValueError):
            protected_information(c)

    def test_real_conflicts_stop_before_fake_translation_and_candidate_finish(self):
        for index, old, changed in (
            (0, '10월 17일 18:00', '10월 17일 19:00'),
            (1, '10월 30일, 각일 13:00', '10월 31일, 각일 13:00'),
            (2, '총 4회', '총 5회'),
            (2, '회당 3시간', '회당 2시간'),
            (3, '만 19세 이상', '만 19세 이하'),
            (4, '서울 거주 외국인 성인', '서울 거주 외국인 성인 999명'),
        ):
            with self.subTest(index=index, changed=changed):
                case, c = CASES[index], replay_context(index)
                summary = case['summary']['content_ko']
                self.assertIn(old, summary)
                summary = summary.replace(old, changed)
                calls = []
                def rpc(name, args):
                    calls.append(name)
                    if name == 'claim_reclassified_content_ai': return copy.deepcopy(c)
                    if name == 'claim_myseoul_program_ai': return [copy.deepcopy(c)]
                    if name == 'admin_myseoul_program_detail': return reviewed_detail(c)
                    if name == 'reclassified_content_ai_status': return {'status':'active'}
                    if name == 'fail_myseoul_program_ai': return 'failed'
                    raise AssertionError('unexpected fake completion')
                ko = Mock(return_value=(summary, 'success', 'recorded-mutated'))
                ja = Mock()
                classified = case['route'] == 'classified'
                worker = process_reclassified_job if classified else process_myseoul_job
                kwargs = {'classification_version':c['classificationVersion']} if classified else {}
                result = worker(ProgramAIAdapter(rpc), source_item_id=c['sourceItemId'], revision=c['revision'],
                    worker_id=c['workerId'], summarize_ko=ko, translate_ja=ja, **kwargs)
                self.assertEqual(result.completed, 0)
                ja.assert_not_called()
                self.assertEqual(ko.call_count, 1)
                self.assertFalse(any(name.startswith('finish_') for name in calls))

    def test_all_recorded_summaries_reach_only_fenced_fake_candidates(self):
        self.replayed_outputs = []
        for index, case in enumerate(CASES):
            with self.subTest(case=case['name']):
                c = replay_context(index)
                before = copy.deepcopy(c)
                calls, outputs = [], []
                classified = case['route'] == 'classified'
                def rpc(name, args):
                    calls.append(name)
                    if name == 'claim_reclassified_content_ai': return copy.deepcopy(c)
                    if name == 'claim_myseoul_program_ai': return [copy.deepcopy(c)]
                    if name == 'admin_myseoul_program_detail': return reviewed_detail(c)
                    if name.startswith('finish_'):
                        for key in ('jobId', 'revision', 'workerId', 'claimedAt', 'leaseUntil'):
                            sql = {'jobId':'job_id','revision':'revision','workerId':'worker_id',
                                   'claimedAt':'claimed_at','leaseUntil':'lease_until'}[key]
                            self.assertEqual(args['p_'+sql], c[key])
                        version = 'classification' if classified else 'facts'
                        self.assertEqual(args['p_'+version+'_version'], c[version+'Version'])
                        outputs.append(args['p_output'])
                        return {'outcome':'inserted', 'candidateId':c['sourceItemId']}
                    raise AssertionError('unexpected fake RPC: '+name)
                def fake_translation(title, body):
                    self.assertNotRegex(body, r'\["|\{\s*"|"evidence"|"component"')
                    if classified:
                        actual = case['translation']
                        ja = actual['content_ja'].split('確認済みの分類・参加案内', 1)[0] + FAKE_PROTECTED_JA[index]
                        title_ja = actual['title_ja']
                    else:
                        ja, title_ja = FAKE_ONLINE_JA, '日曜韓国語教室TOPIKクラス1募集'
                    validate_translation_fidelity(title, body, title_ja, ja)
                    return title_ja, ja, 'success', 'fake-translation'
                ko = Mock(return_value=(case['summary']['content_ko'], 'success', 'recorded-response'))
                ja = Mock(side_effect=fake_translation)
                worker = process_reclassified_job if classified else process_myseoul_job
                kwargs = {'classification_version':c['classificationVersion']} if classified else {}
                result = worker(ProgramAIAdapter(rpc), source_item_id=c['sourceItemId'], revision=c['revision'],
                    worker_id=c['workerId'], summarize_ko=ko, translate_ja=ja, **kwargs)
                self.assertEqual(result.completed, 1)
                self.assertEqual((ko.call_count, ja.call_count, len(outputs)), (1, 1, 1))
                self.assertEqual(c, before)
                self.assertEqual(ja.call_args.args[1], outputs[0]['contentKo'])
                self.assertFalse(any('fail' in call or 'status' in call for call in calls))
                if index == 3:
                    self.assertIn('100명', outputs[0]['contentKo'])
                    self.assertIn('20명', outputs[0]['contentKo'])
                self.replayed_outputs.append({'name':case['name'], 'output':outputs[0]})


if __name__ == '__main__':
    unittest.main()
