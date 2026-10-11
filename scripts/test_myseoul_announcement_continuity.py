"""Recorded completed summary, synthetic identities, zero live transports."""
import copy
import json
import socket
import unittest
from unittest.mock import Mock, patch

from ingest.ai_errors import AiJobError
from ingest.myseoul_ai import generate_myseoul_output, process_myseoul_job, fact_sections
from ingest.myseoul_content import schedule_lines, announcement_lines, validate_summary_period
from ingest.program_ai import ProgramAIAdapter
from ingest.reclassification_ai import process_reclassified_job, protected_information
from test_myseoul_schedule_blocks import recorded_context, reviewed_detail, FAKE_JA

# Exact summary from the most recent completed Pro response; no live identity.
RECORDED_SUMMARY = '''[한 줄 요약]
한국 기업 취업을 준비하는 외국인 유학생과 구직자를 위한 생성형 AI·엑셀·협업 툴 실습 교육입니다.

[대상]
한국 기업 취업을 희망하는 외국인 유학생 및 구직자 25명.

[기간·상태]
신청 기간: 2026년 10월 8일 00:00~10월 20일 23:50.
합격자 발표: 10월 21일 개별 안내.
교육 기간: 2026년 10월 27일 13:00~11월 3일 17:00으로 안내되어 있으며, 실제 수업은 10월 27일, 10월 30일, 11월 3일 총 3회 진행됩니다.

[주요 내용]
사무 현장에서 활용할 수 있는 AI·OA 역량을 실습 중심으로 익힙니다. 10월 27일에는 AI 기반 업무 자동화와 스마트 오피스 기초, 10월 30일에는 실무 엑셀 핵심 스킬과 AI 연계 비즈니스 문서 작성, 11월 3일에는 스마트 협업 툴 기반 프로젝트 워크플로우를 배웁니다.
교육 장소는 서울글로벌센터 4층 404호(서울특별시 종로구 종로 38)입니다.

[신청 방법]
안내된 QR 또는 신청 링크를 통해 구글폼을 제출합니다.
https://forms.gle/Hcn96yNTzFfKQ83TA'''


class AnnouncementContinuityTests(unittest.TestCase):
    def setUp(self):
        network = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        network.start()
        self.addCleanup(network.stop)

    def test_recorded_announcement_reaches_translation_input(self):
        c = recorded_context()
        before = copy.deepcopy(c)
        ja = Mock(return_value=('合成研修', FAKE_JA+'\n合格者発表：10月21日（水）個別案内', 'success', 'fake-translation'))
        output = generate_myseoul_output(c, summarize_ko=Mock(return_value=(RECORDED_SUMMARY, 'success', 'recorded-response')),
                                        translate_ja=ja)
        self.assertIn('합격자 발표: 10월 21일(수) 개별 안내', output['contentKo'])
        self.assertEqual(ja.call_args.args[1], output['contentKo'])
        self.assertEqual(c, before)

    def test_omitted_announcement_is_restored_from_current_facts_not_observed_source(self):
        c = recorded_context()
        c['facts']['description'] = c['facts']['description'].replace('10월 21일(수)', '10월 22일(목)')
        summary = RECORDED_SUMMARY.replace('합격자 발표: 10월 21일 개별 안내.\n', '')
        before = copy.deepcopy(c)
        ja = Mock(return_value=('合成研修', FAKE_JA.replace('21日(水)', '22日(木)'), 'success', 'fake-translation'))
        output = generate_myseoul_output(c, summarize_ko=Mock(return_value=(summary, 'success', 'recorded-response')),
                                        translate_ja=ja)
        self.assertIn('합격자 발표: 10월 22일(목) 개별 안내', output['contentKo'])
        self.assertNotIn('10월 21일', output['contentKo'])
        self.assertEqual(c, before)

    def test_unavailable_notice_does_not_create_new_announcement(self):
        f = recorded_context()['facts']
        f['description'] = '교육 안내\n10월 21일 방문 상담\n합격자 발표 여부는 원문을 확인하세요.'
        self.assertEqual(announcement_lines(f), [])
        self.assertNotIn('발표', fact_sections(f)['[일정 안내]'])
        with self.assertRaises(AiJobError):
            validate_summary_period(RECORDED_SUMMARY, fact_sections(f)['[일정 안내]'], f)

    def test_notice_in_activity_is_not_repeated_after_source_notice_is_added(self):
        c = recorded_context()
        summary = RECORDED_SUMMARY.replace('교육 장소는', '합격자 발표: 10월 21일 개별 안내.\n교육 장소는')
        output = generate_myseoul_output(c, summarize_ko=Mock(return_value=(summary, 'success', 'recorded-response')),
            translate_ja=Mock(return_value=('合成研修', FAKE_JA, 'success', 'fake-translation')))
        self.assertEqual(output['contentKo'].count('합격자 발표:'), 1)

    def test_missing_notice_date_in_fake_translation_cannot_complete_candidate(self):
        c = recorded_context()
        calls = []
        def rpc(name, args):
            calls.append(name)
            if name == 'claim_myseoul_program_ai': return [copy.deepcopy(c)]
            if name == 'admin_myseoul_program_detail': return reviewed_detail(c)
            if name == 'fail_myseoul_program_ai': return 'failed'
            raise AssertionError('candidate completion forbidden')
        ja = Mock(return_value=('合成研修', FAKE_JA.replace('合格者発表: 10月21日(水)、個別案内\n', ''),
                                'success', 'fake-translation'))
        result = process_myseoul_job(ProgramAIAdapter(rpc), source_item_id=c['sourceItemId'], revision=c['revision'],
            worker_id=c['workerId'], summarize_ko=Mock(return_value=(RECORDED_SUMMARY, 'success', 'recorded-response')),
            translate_ja=ja)
        self.assertEqual((result.completed, result.failed), (0, 1))
        self.assertNotIn('finish_myseoul_program_ai', calls)

    def test_notice_precision_channels_and_labels_are_preserved(self):
        f = recorded_context()['facts']
        notices = ['합격자 발표: 2026년 10월 21일(수) 10:30 개별 문자 안내 예정',
                   '선정자 발표: 10월 22일 홈페이지 공개', '결과 발표: 별도 안내']
        f['description'] = '\n'.join('▪️ '+line for line in notices)
        before = copy.deepcopy(f)
        self.assertEqual(announcement_lines(f), notices)
        validate_summary_period('\n'.join(notices), fact_sections(f)['[일정 안내]'], f)
        self.assertEqual(f, before)

    def test_real_announcement_and_same_clause_period_conflicts_stop_before_translation(self):
        c = recorded_context()
        for summary in (
            RECORDED_SUMMARY.replace('발표: 10월 21일', '발표: 10월 22일'),
            RECORDED_SUMMARY.replace('발표: 10월 21일', '발표: 2027년 10월 21일'),
            RECORDED_SUMMARY.replace('발표: 10월 21일', '발표: 10월 21일(금)'),
            RECORDED_SUMMARY.replace('발표: 10월 21일', '발표: 10월 21일 10:30'),
            RECORDED_SUMMARY.replace('개별 안내', '홈페이지 공개'),
            RECORDED_SUMMARY.replace('교육 기간: 2026년 10월 27일 13:00', '교육 기간: 2026년 10월 27일 14:00'),
            RECORDED_SUMMARY.replace('실제 수업은 10월 27일, 10월 30일', '실제 수업은 10월 27일, 10월 31일'),
        ):
            ja = Mock()
            with self.subTest(summary=summary), self.assertRaises(AiJobError):
                generate_myseoul_output(c, summarize_ko=Mock(return_value=(summary, 'success', 'recorded-response')),
                                        translate_ja=ja)
            ja.assert_not_called()

    def test_clear_count_copy_is_normalized_but_mixed_schedule_and_conditions_are_kept(self):
        mixed = ['총 3회 교육으로 거듭날 기회! 노트북 지참 필수.',
                 '총 3회 교육으로 거듭날 기회! 10월 27일(화) 13:00~14:00',
                 '총 3회 교육으로 거듭날 기회! 보호자 동반이 필요합니다.',
                 '총 3회 교육으로 거듭날 기회! 1회 2시간 진행.',
                 '총 3회 교육 예정, 거듭날 기회!', '총 3회 교육, 거듭날 기회! 수강료 무료']
        f = recorded_context()['facts']
        f['description'] = '\n'.join(mixed)
        self.assertEqual(schedule_lines(f), mixed)
        # Explicit session evidence wins; dates and conditions aren't scrubbed.
        f['session_evidence'] = ['단 3번의 실습 중심 수업으로 거듭날 기회!', *mixed]
        before = copy.deepcopy(f)
        self.assertEqual(schedule_lines(f), ['총 3회', *mixed])
        self.assertEqual(f, before)

    def test_recorded_response_reaches_fenced_fake_native_candidate(self):
        c = recorded_context()
        before = copy.deepcopy(c)
        calls = []
        output = {}
        def rpc(name, args):
            calls.append(name)
            if name == 'claim_myseoul_program_ai': return [copy.deepcopy(c)]
            if name == 'admin_myseoul_program_detail': return reviewed_detail(c)
            if name == 'finish_myseoul_program_ai':
                for key, value in {'p_job_id':c['jobId'], 'p_revision':c['revision'],
                    'p_facts_version':c['factsVersion'], 'p_worker_id':c['workerId'],
                    'p_claimed_at':c['claimedAt'], 'p_lease_until':c['leaseUntil']}.items():
                    self.assertEqual(args[key], value)
                output.update(args['p_output'])
                return {'outcome':'inserted', 'candidateId':c['sourceItemId']}
            raise AssertionError('unexpected fake RPC')
        ko = Mock(return_value=(RECORDED_SUMMARY, 'success', 'recorded-response'))
        ja = Mock(return_value=('合成研修', FAKE_JA, 'success', 'fake-translation'))
        result = process_myseoul_job(ProgramAIAdapter(rpc), source_item_id=c['sourceItemId'], revision=c['revision'],
            worker_id=c['workerId'], summarize_ko=ko, translate_ja=ja)
        self.assertEqual(result.completed, 1)
        self.assertEqual(calls, ['claim_myseoul_program_ai','admin_myseoul_program_detail','finish_myseoul_program_ai'])
        self.assertEqual((ko.call_count, ja.call_count), (1, 1))
        self.assertEqual(json.loads(ko.call_args.args[0])['currentFacts']['description'], c['facts']['description'])
        self.assertIn('合格者発表: 10月21日(水)、個別案内', output['contentJa'])
        self.assertIn('合格者発表', ja.return_value[1])
        self.assertIn('합격자 발표: 10월 21일(수) 개별 안내', output['contentKo'])
        self.assertEqual(output['contentKo'].count('합격자 발표:'), 1)
        self.assertNotIn('거듭날 기회', output['contentKo'])
        self.assertEqual(ja.call_args.args[1], output['contentKo'])
        self.assertEqual(c, before)

    def test_reclassified_candidate_uses_same_notice_and_clean_schedule(self):
        from test_reclassification_ai import context as classified_context
        c = classified_context('program')
        native = recorded_context()['facts']
        c['nativeConfirmedFacts']['programFacts'] = native
        c['facts'].update(delivery='offline', scope='unknown', evidence='', deadlineOn='2026-10-20')
        c['filters']['delivery'] = {'status':'known', 'value':'onsite'}
        c['filters']['location'] = {'status':'known', 'value':{'scope':'specific','venues':[
            {'province':'11','district':None,'facility':'','address':''}]}}
        c['filters']['application']['value'].update(start=copy.deepcopy(native['periods']['application'][0]['endpoints'][0]),
            end=copy.deepcopy(native['periods']['application'][0]['endpoints'][1]))
        before = copy.deepcopy(c)
        calls = []
        output = {}
        def rpc(name, args):
            calls.append(name)
            if name == 'claim_reclassified_content_ai': return copy.deepcopy(c)
            if name == 'finish_reclassified_content_ai':
                for key, value in {'p_job_id':c['jobId'], 'p_revision':c['revision'],
                    'p_classification_version':c['classificationVersion'], 'p_worker_id':c['workerId'],
                    'p_claimed_at':c['claimedAt'], 'p_lease_until':c['leaseUntil']}.items():
                    self.assertEqual(args[key], value)
                output.update(args['p_output'])
                return {'outcome':'inserted', 'candidateId':c['sourceItemId']}
            raise AssertionError('unexpected fake RPC')
        ko = Mock(return_value=(RECORDED_SUMMARY, 'success', 'recorded-response'))
        ja = Mock(return_value=('合成研修', FAKE_JA, 'success', 'fake-translation'))
        result = process_reclassified_job(ProgramAIAdapter(rpc), source_item_id=c['sourceItemId'], revision=c['revision'],
            classification_version=c['classificationVersion'], worker_id=c['workerId'], summarize_ko=ko, translate_ja=ja)
        self.assertEqual(result.completed, 1)
        self.assertEqual(calls, ['claim_reclassified_content_ai','finish_reclassified_content_ai'])
        self.assertIn('합격자 발표: 10월 21일(수) 개별 안내', output['contentKo'])
        self.assertNotIn('거듭날 기회', output['contentKo'])
        self.assertEqual(output['contentKo'].count('합격자 발표:'), 1)
        self.assertEqual(ja.call_args.args[1], output['contentKo'])
        self.assertEqual(json.loads(ko.call_args.args[0])['currentFilters'], c['filters'])
        self.assertEqual(c, before)
        native['session_evidence'] = ['단 3번의 실습 중심 수업으로 거듭날 기회!']
        self.assertNotIn('거듭날 기회', protected_information(c))

    def test_recorded_count_retains_fact_without_promotional_sentence(self):
        f = recorded_context()['facts']
        before = copy.deepcopy(f)
        lines = schedule_lines(f)
        self.assertIn('총 3회', lines)
        self.assertNotIn('거듭날 기회', '\n'.join(lines))
        for day in ['10월 27일(화)', '10월 30일(금)', '11월 3일(화)']:
            self.assertIn(day, '\n'.join(lines))
        self.assertEqual(f, before)


if __name__ == '__main__':
    unittest.main()
