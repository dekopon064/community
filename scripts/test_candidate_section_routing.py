"""Offline worker projections from quoted source lines; no operational jobs."""
import copy
import unittest
from unittest.mock import Mock, patch

from ingest.myseoul_ai import generate_myseoul_output
from ingest.ai_errors import ValidationError
from ingest.seoul_condition_display import covered_condition
from ingest.seoul_content import assemble_seoul_body, validation_view
from ingest.seoul_fact_roles import optional_section, public_roles
from ingest.seoul_schedule_display import _timed_session_rows
from test_myseoul_ai import context, providers
from test_seoul_content import SUMMARY, synthetic_facts
from test_seoul_content import fake_japanese
import test_program_ai as program_fixture


class CandidateSections(unittest.TestCase):
    def setUp(self):
        guard = patch('socket.socket.connect', side_effect=AssertionError('offline'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_museum_conditions_land_once_in_their_destination(self):
        f = synthetic_facts()
        capacity = '참여 인원 : 회차별 15 명 이내 운영 ( 온라인 예약 10 명 / 현장 접수 5 명 )'
        cancel = '해설 예정 시각부터 10 분간 참여자가 없으면 해당 회차 해설은 취소됩니다 .'
        closed = '휴 관 일 : 매주 월요일 ( 공휴일 제외 ), 1 월 1 일'
        booking = '영어, 중국어, 일본어 해설 가능하오니 개인 및 단체는 안내데스크에 신청하세요. (02-1234-5678)'
        rule = '전시 해설의 녹취는 불가합니다 .'
        eligible = '외국어 해설에는 내국인이 참여할 수 없습니다.'
        f['conditions'] = [capacity, cancel, closed, rule, booking, eligible]
        f['description'] += '\n' + '\n'.join(f['conditions'])
        before = copy.deepcopy(f)
        summary = SUMMARY.replace('[대상]', '[대상]\n- **참가 조건:** ' + capacity).replace(
            '[일정 안내]', '[일정 안내]\n예정 시각부터 10분간 참여자가 없으면 해당 회차는 취소됩니다.\n'
            '매주 월요일(공휴일 제외)과 1월 1일은 휴관합니다.').replace(
            '작품을 만듭니다.', '해설 녹취는 불가하며, 직원 안내에 협조해 주세요.')
        out = assemble_seoul_body(summary, f)
        self.assertEqual(public_roles(f)['eligibility'], [eligible])
        self.assertIn(eligible, optional_section(out, '[대상]'))
        self.assertEqual(optional_section(out, '[일정 안내]').count('참여자가'), 1)
        self.assertEqual(out.count('공휴일'), 1)
        self.assertEqual(out.count('녹취'), 1)
        method = optional_section(out, '[신청 방법]')
        self.assertIn('온라인 예약 10 명 / 현장 접수 5 명', method)
        self.assertIn(booking, method)
        self.assertEqual(before, f)
        changed = summary.replace('예정 시각부터 10분간', '예정 시각부터 20분간')
        with self.assertRaises(ValidationError):
            assemble_seoul_body(changed, f)
        self.assertFalse(covered_condition(rule, '해설 녹취는 불가하며, 사전 허가를 받으면 가능합니다.'))

    def test_garden_hours_distinct_from_capacity_and_tour_times(self):
        f = synthetic_facts()
        f['description'] = ('예약인원\n회당 예약인원 최대 15명\n전시관 및 정원 관람시간\n'
                            '전시관 : 09:30 ~ 17:30\n정원 : 09:30 ~ 20:30\n'
                            '해설대상\n초등학교 3학년 이상 (가족 동반 가능)\n'
                            '주차\n불가 (주차장이 없으므로 대중교통을 이용해주기 바랍니다.) 4. 주의사항')
        f['conditions'] = f['description'].splitlines()[-4:-2] + [f['description'].splitlines()[-1]]
        summary = SUMMARY.replace('[대상]', '[대상]\n- **모집 인원:** 09:30 ~ 20:30').replace(
            '[일정 안내]', '[일정 안내]\n- 예약 인원: 회당 최대 15명')
        out = assemble_seoul_body(summary, f)
        self.assertEqual(validation_view(f)['capacity_raw'], ['회당 예약인원 최대 15명'])
        self.assertIn('최대 15명', optional_section(out, '[신청 방법]'))
        self.assertEqual(out.count('15명'), 1)
        for end in ('17:30', '20:30'):
            self.assertEqual(out.count(end), 1)
            self.assertIn(end, optional_section(out, '[일정 안내]'))
        self.assertNotIn('해설대상', out)
        self.assertNotIn('4. 주의사항', out)
        self.assertIn('가족 동반 가능', optional_section(out, '[대상]'))
        self.assertIn('주차장이 없으므로', optional_section(out, '[주요 내용]'))
        self.assertEqual(out, assemble_seoul_body(out, f))
        with self.assertRaises(ValidationError):
            assemble_seoul_body(out.replace('정원 관람시간: 09:30 ~ 20:30', '정원 관람시간: 09:30 ~ 17:30'), f)
        f['description'] += '\n정원: 20명 (접수 09:30부터)'
        self.assertIn('정원: 20명 (접수 09:30부터)', validation_view(f)['capacity_raw'])
        f['description'] += '\n모집 인원: 선착순 마감. 단, 단체는 별도 문의'
        self.assertIn('모집 인원: 선착순 마감. 단, 단체는 별도 문의', validation_view(f)['capacity_raw'])

    def test_fake_worker_translates_garden_hours_in_schedule(self):
        c = program_fixture.context()
        c['facts']['description'] += '\n전시관 및 정원 관람시간\n전시관 : 09:30 ~ 17:30\n정원 : 09:30 ~ 20:30\n회당 예약인원 최대 15명'
        def translate(title, body):
            ja = fake_japanese(body.replace('정원 관람시간', '庭園の観覧時間').replace('예약 인원', '予約人数')
                               .replace('회당 최대', '各回最大'))
            return '見学', ja, 'success', 'fake'
        translator = Mock(side_effect=translate)
        result, calls, inputs = program_fixture.ProgramAITests().run_job(c, translate=translator)
        self.assertEqual(result.completed, 1)
        self.assertFalse(any('20:30' in line for line in inputs[0]['capacityEvidence']))
        self.assertIn('정원 관람시간: 09:30 ~ 20:30', inputs[0]['viewingHoursEvidence'])
        out = calls[-1][1]['p_output']
        self.assertEqual(translator.call_args.args[1], out['contentKo'])
        schedule = out['contentJa'].split('[日程案内]')[1].split('[主な内容]')[0]
        self.assertIn('庭園の観覧時間: 09:30 ~ 20:30', schedule)
        self.assertEqual(out['contentJa'].count('20:30'), 1)

    def test_different_deadlines_and_exceptions_are_not_merged(self):
        f = synthetic_facts()
        f['conditions'] = ['프로그램 예약 후 사전 취소 없이 당일 불참시 (NO-SHOW) 다음 달 예약이 불가합니다.',
                           '프로그램 예약 후 사전 취소 없이 당일 불참시 같은 달 예약이 불가합니다. 단, 진단서 제출 시 제외.']
        f['description'] += '\n' + '\n'.join(f['conditions'])
        out = assemble_seoul_body(SUMMARY, f)
        for v in f['conditions']:
            self.assertEqual(out.count(v), 1)
            self.assertIn(v, optional_section(out, '[신청 방법]'))

    def test_myseoul_translation_receives_eligibility_and_capacity_once(self):
        c = context()
        rule = '성인 외국인주민은 체류자격과 관계없이 신청할 수 있습니다.'
        link = 'https://synthetic.invalid/apply?session=2'
        c['facts'].update(target='성인 외국인주민 (정원 20명)', capacity_raw=['20명'], conditions=[rule],
                          application_methods=['온라인 신청서 작성'], application_links=[link])
        ko, ja = providers(c)
        def summary(*args, **kwargs):
            body, status, model = ko(*args, **kwargs)
            return body + '\n[신청 방법]\n[온라인 신청서]('+link+')를 작성해 신청해 주세요.', status, model
        translate = Mock(side_effect=ja)
        out = generate_myseoul_output(c, summarize_ko=summary, translate_ja=translate)
        body = out['contentKo']
        self.assertEqual(body.count(link), 1)
        self.assertEqual(body, translate.call_args.args[1])
        self.assertEqual(body.count(rule), 1)
        self.assertIn(rule, optional_section(body, '[대상]'))
        self.assertIn('20명', optional_section(body, '[주요 내용]'))
        self.assertNotIn('20명', optional_section(body, '[대상]'))

    def test_session_table_requires_same_number_and_time_and_keeps_duration(self):
        table = '| 회차 | 진행 시간 |\n|---|---|\n| 1회차 | 11:00~11:40 |\n| 2회차 | 15:00~15:40 |'
        rows = ['* 1회차 - 11:00 ~ 11:40 (약 40분)', '* 2회차 - 15:00 ~ 15:40 (약 40분)']
        self.assertEqual(list(_timed_session_rows(table, rows).values()),
                         ['1회차 소요 시간: 약 40분', '2회차 소요 시간: 약 40분'])
        for alternative in (table.replace('15:40', '15:50'), table.replace('2회차', '5회차')):
            self.assertFalse(_timed_session_rows(alternative, rows))
        self.assertFalse(_timed_session_rows(table, [rows[0], rows[1]+' (일요일 제외)']))
        f = synthetic_facts()
        f.update(description='합성 전시 해설\n' + '\n'.join(rows), conditions=rows)
        out = assemble_seoul_body(SUMMARY.replace('[일정 안내]', '[일정 안내]\n'+table), f)
        self.assertIn(table, out)
        self.assertEqual(out.count('11:40'), 1)
        self.assertEqual(out.count('15:40'), 1)
        for i in (1, 2):
            self.assertIn(f'{i}회차 소요 시간: 약 40분', out)
