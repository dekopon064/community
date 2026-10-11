"""Schedule record boundaries, offline worker/RPC regressions only."""
import copy
import json
import socket
import unittest
from unittest.mock import Mock, patch

from ingest.myseoul_ai import fact_sections, process_myseoul_job
from ingest.myseoul_content import schedule_lines, schedule_block, normalize_summary_schedule
from ingest.program_ai import ProgramAIAdapter
from ingest.reclassification_ai import protected_information, process_reclassified_job
from ingest.translation_validation import validate_translation_fidelity
from test_body_markdown_pipeline import synthetic_context, KO, JA
from test_myseoul_schedule_blocks import reviewed_detail
from test_reclassification_ai import context as classified_context

TITLE = '<일요일 한국어교실_토픽 1반 모집 안내>'
INVITATION = '양천외국인주민센터 일요일 한국어교실 토픽 1반 신청 안내드립니다!'
PERIOD = '■ 운영기간 : 10월 18일 ~ 11월 8일 / 매주 일요일(4회), 3시간'


def context():
    c = synthetic_context()
    c['facts']['session_evidence'] = [
        '<토요일 문서 실습 모집 안내>', '토요일 문서 실습 신청 안내드립니다!',
        '1회차: 10월 3일 10:00~11:30 / 문서 작성',
        '2회차: 10월 10일 14:00~15:30 / 문서 제출',
    ]
    return c


def reclassified_context():
    c = classified_context('program')
    native = context()['facts']
    c['nativeConfirmedFacts']['programFacts'] = native
    c['facts'].update(delivery='offline', scope='unknown', evidence='', deadlineOn='2026-10-02')
    c['filters']['delivery'] = {'status':'known', 'value':'onsite'}
    c['filters']['location'] = {'status':'known', 'value':{'scope':'specific', 'venues':[
        {'province':'11', 'district':None, 'facility':'', 'address':''}]}}
    c['filters']['application']['value'].update(
        start=copy.deepcopy(native['periods']['application'][0]['endpoints'][0]),
        end=copy.deepcopy(native['periods']['application'][0]['endpoints'][1]))
    return c


class SchedulePresentationTests(unittest.TestCase):
    def setUp(self):
        network = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        network.start()
        self.addCleanup(network.stop)

    def test_reported_source_separator_survives_without_title_or_invitation(self):
        f = {'session_evidence':[TITLE, INVITATION, PERIOD]}
        before = copy.deepcopy(f)
        self.assertEqual(schedule_lines(f), [PERIOD])
        self.assertEqual(f, before)

    def test_mixed_dates_times_counts_durations_and_conditions_are_not_deleted(self):
        lines = [
            '<10월 18일 모집 안내>', '10:00 수업 신청 안내드립니다!',
            '총 4회 교육 신청 안내드립니다!', '3시간 수업 신청 안내드립니다!',
            '매주 일요일 수업 신청 안내드립니다!', '보호자 동반 필수. 신청 안내드립니다!',
            '수강료 무료. 신청 안내드립니다!', '신청 마감 후 수업 안내드립니다!',
            '30명 수업 신청 안내드립니다!', '18살부터 신청 안내드립니다!',
            '참가 불가 대상은 신청할 수 없습니다. 신청 안내드립니다!',
            '일요일 한국어교실', '문의: https://synthetic.invalid/a/b?q=1/2',
        ]
        self.assertEqual(schedule_lines({'session_evidence':lines}), lines)

    def test_operation_period_fallback_keeps_original_delimiter_and_duration(self):
        f = {'description':'\n'.join([TITLE, INVITATION, PERIOD, '많은 관심과 참여 부탁드립니다!'])}
        self.assertEqual(schedule_lines(f), [PERIOD])

    def test_native_and_reclassified_schedule_records_are_bullets_not_joined(self):
        for text in (fact_sections(context()['facts'])['[일정 안내]'],
                     protected_information(reclassified_context())):
            self.assertNotIn('모집 안내', text)
            self.assertNotIn('신청 안내드립니다', text)
            self.assertIn('- 1회차: 10월 3일 10:00~11:30 / 문서 작성\n'
                          '- 2회차: 10월 10일 14:00~15:30 / 문서 제출', text)
            self.assertNotIn('문서 작성 / 2회차', text)

    def test_description_fallback_uses_same_record_boundaries(self):
        c = reclassified_context()
        native = c['nativeConfirmedFacts']['programFacts']
        native['session_evidence'] = []
        native['description'] = ('교육 일정\n10월 3일 10:00~11:30 / 문서 작성\n'
                                 '10월 10일 14:00~15:30 / 문서 제출')
        for text in (fact_sections(native)['[일정 안내]'], protected_information(c)):
            self.assertIn('- 10월 3일 10:00~11:30 / 문서 작성\n'
                          '- 10월 10일 14:00~15:30 / 문서 제출', text)

    def test_original_slash_pipes_urls_and_multiline_record_are_not_reinterpreted(self):
        records = ['1회차: 10월 3일 10:00~11:30 / AI/OA 실습',
                   '2회차: 10월 10일 14:00~15:30 · 문서 작성\n문서 제출; 준비물: 노트북',
                   '문의: https://synthetic.invalid/a/b?day=3/10&x=1|2']
        expected = ('**진행 일정:**\n- '+records[0]+'\n- '+records[1].replace('\n','\n  ')
                    +'\n- '+records[2])
        self.assertEqual(schedule_block(records), expected)
        self.assertEqual(schedule_lines({'session_evidence':records}), records)

    def test_legacy_serialization_repair_is_exact_scoped_and_idempotent(self):
        f = {'session_evidence':[TITLE, INVITATION, PERIOD]}
        old = '[한 줄 요약]\n일요일 수업입니다.\n[일정 안내]\n진행 일정: '+' / '.join(f['session_evidence'])
        old += '\n[주요 내용]\n'+INVITATION+'\n읽기/말하기 활동입니다.'
        new = normalize_summary_schedule(old, f)
        self.assertIn(schedule_block([PERIOD]), new)
        self.assertEqual(new, normalize_summary_schedule(new, f))
        self.assertIn('[주요 내용]\n'+INVITATION, new)
        self.assertIn('읽기/말하기', new)
        # A mixed record or unknown join is not split at arbitrary slash positions.
        unknown = '[일정 안내]\n진행 일정: '+PERIOD+' / 보호자 동반 필수'
        self.assertIn(PERIOD+' / 보호자 동반 필수', normalize_summary_schedule(unknown, f))

    def test_standalone_titles_are_removed_only_in_schedule_not_activity_or_tables(self):
        f = {'session_evidence':[TITLE, INVITATION, PERIOD]}
        table = '| 회차 | 활동 |\n| --- | --- |\n| 1회 | 신청 안내드립니다! |'
        content = '[일정 안내]\n'+TITLE+'\n'+INVITATION+'\n'+PERIOD+'\n'+table+'\n[주요 내용]\n'+TITLE
        updated = normalize_summary_schedule(content, f)
        self.assertEqual(updated.count(TITLE), 1)
        self.assertNotIn(INVITATION, updated)
        self.assertIn(table, updated)
        self.assertIn(PERIOD, updated)

    def run_worker(self, reclassified=False, summary=KO):
        c = reclassified_context() if reclassified else context()
        before = copy.deepcopy(c)
        calls, candidates = [], []
        def rpc(name, args):
            calls.append((name, copy.deepcopy(args)))
            if name == 'claim_myseoul_program_ai': return [copy.deepcopy(c)]
            if name == 'admin_myseoul_program_detail': return reviewed_detail(c)
            if name == 'claim_reclassified_content_ai': return copy.deepcopy(c)
            if name in {'finish_myseoul_program_ai','finish_reclassified_content_ai'}:
                candidates.append(args['p_output'])
                return {'outcome':'inserted', 'candidateId':c['sourceItemId']}
            if name == 'fail_myseoul_program_ai': return 'failed'
            if name == 'reclassified_content_ai_status': return {'status':'active'}
            raise AssertionError(name)
        ko = Mock(return_value=(summary, 'success', 'fake-model'))
        ja = Mock(return_value=('合成文書実習', JA, 'success', 'fake-model'))
        args = dict(source_item_id=c['sourceItemId'], revision=c['revision'], worker_id=c['workerId'],
                    summarize_ko=ko, translate_ja=ja)
        if reclassified:
            result = process_reclassified_job(ProgramAIAdapter(rpc), **args,
                                              classification_version=c['classificationVersion'])
        else:
            result = process_myseoul_job(ProgramAIAdapter(rpc), **args)
        self.assertEqual(c, before)
        return c, result, calls, candidates, ko, ja

    def test_both_fenced_fake_candidates_receive_clean_complete_translation_input(self):
        for reclassified in (False, True):
            with self.subTest(reclassified=reclassified):
                c, result, calls, candidates, ko, ja = self.run_worker(reclassified)
                self.assertEqual(result.completed, 1)
                self.assertEqual((ko.call_count, ja.call_count), (1, 1))
                body = candidates[0]['contentKo']
                self.assertNotIn('모집 안내', body)
                self.assertNotIn('신청 안내드립니다', body)
                self.assertIn('/ 문서 작성\n- 2회차:', body)
                self.assertEqual(ja.call_args.args[1], body)
                request = json.loads(ko.call_args.args[0])
                facts = request['nativeConfirmedFacts']['programFacts'] if reclassified else request['currentFacts']
                native = c['nativeConfirmedFacts']['programFacts'] if reclassified else c['facts']
                self.assertEqual(facts['session_evidence'], native['session_evidence'])
                fence = calls[-1][1]
                for field in ('revision','workerId','claimedAt','leaseUntil'):
                    param = {'workerId':'worker_id','claimedAt':'claimed_at','leaseUntil':'lease_until'}.get(field,field)
                    self.assertEqual(fence['p_'+param], c[field])
                version = 'classificationVersion' if reclassified else 'factsVersion'
                self.assertEqual(fence['p_classification_version' if reclassified else 'p_facts_version'], c[version])

    def test_exact_old_join_in_summary_cannot_reintroduce_titles_in_either_worker(self):
        old = '진행 일정: '+' / '.join(context()['facts']['session_evidence'])
        summary = KO.replace('[주요 내용]', '[일정 안내]\n'+old+'\n\n[주요 내용]')
        for reclassified in (False, True):
            with self.subTest(reclassified=reclassified):
                _, result, _, candidates, _, ja = self.run_worker(reclassified, summary)
                self.assertEqual(result.completed, 1)
                self.assertNotIn('모집 안내', candidates[0]['contentKo'])
                self.assertNotIn('신청 안내드립니다', candidates[0]['contentKo'])
                self.assertNotIn('문서 작성 / 2회차', ja.call_args.args[1])

    def test_schedule_conflicts_still_stop_both_workers_before_translation_and_completion(self):
        for reclassified in (False, True):
            for summary in (KO.replace('10월 10일', '10월 11일'),
                            KO.replace('14:00~15:30','10:00~11:30'),
                            KO.replace('| 2회 |','| 3회 |')):
                with self.subTest(reclassified=reclassified, summary=summary):
                    _, result, calls, candidates, ko, ja = self.run_worker(reclassified, summary)
                    self.assertEqual(result.completed, 0)
                    self.assertEqual(candidates, [])
                    ja.assert_not_called()
                    self.assertFalse(any(name.startswith('finish_') for name, _ in calls))

    def test_reported_topik_recorded_summary_reaches_fake_candidate_without_source_titles(self):
        # Local recorded response only; its identities are injected into fake RPC.
        from test_myseoul_recorded_batch_validation import replay_context, CASES
        c = replay_context(2)
        before = copy.deepcopy(c)
        output, calls = [], []
        fake_ja = '''[要約]
外国人住民のためのTOPIKクラス1のオンライン韓国語授業です。
[対象]
外国人住民
[日程案内]
- **申請期間:** 2026年9月28日10:00～2026年10月15日18:00
- **実施期間:** 2026年10月18日12:00～2026年11月8日15:00

**実施日程:**
- ■ 運営期間 : 10月18日～11月8日 / 毎週日曜日（4回）、3時間
[主な内容]
ZOOMのオンライン授業です。TOPIKクラス1のみ申し込めます。他のレベルの授業は申し込めません。
- **費用:** 受講料: 無料
- **募集人数:** 20名
- **実施方式:** オンライン
[申請方法]
オンライン
- **申請リンク:** https://forms.gle/ziWmG2CKaaD3gu2N9'''
        def translate(title, body):
            validate_translation_fidelity(title, body, '日曜韓国語教室TOPIKクラス1募集', fake_ja)
            return '日曜韓国語教室TOPIKクラス1募集', fake_ja, 'success', 'fake-translation'
        def rpc(name, args):
            calls.append(name)
            if name == 'claim_myseoul_program_ai': return [copy.deepcopy(c)]
            if name == 'admin_myseoul_program_detail': return reviewed_detail(c)
            if name == 'finish_myseoul_program_ai':
                output.append(args['p_output'])
                return {'outcome':'inserted', 'candidateId':c['sourceItemId']}
            raise AssertionError(name)
        ko = Mock(return_value=(CASES[2]['summary']['content_ko'], 'success', 'recorded-response'))
        ja = Mock(side_effect=translate)
        result = process_myseoul_job(ProgramAIAdapter(rpc), source_item_id=c['sourceItemId'],
            revision=c['revision'], worker_id=c['workerId'], summarize_ko=ko, translate_ja=ja)
        self.assertEqual(result.completed, 1)
        self.assertEqual((ko.call_count, ja.call_count), (1, 1))
        self.assertEqual(calls, ['claim_myseoul_program_ai','admin_myseoul_program_detail','finish_myseoul_program_ai'])
        self.assertIn(schedule_block([PERIOD]), output[0]['contentKo'])
        self.assertNotIn(TITLE, output[0]['contentKo'])
        self.assertNotIn(INVITATION, output[0]['contentKo'])
        self.assertEqual(output[0]['contentJa'], fake_ja)
        self.assertEqual(ja.call_args.args[1], output[0]['contentKo'])
        self.assertEqual(c, before)


if __name__ == '__main__':
    unittest.main()
