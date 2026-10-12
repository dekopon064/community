"""Synthetic Seoul schedule display regressions, no network/DB/AI."""
import copy
import json
import socket
import unittest
from unittest.mock import patch
from ingest.ai_errors import AiJobError
from ingest.seoul_content import assemble_seoul_body
from test_seoul_recruitment_schedule import session_context, SUMMARY, TABLE
import test_seoul_recruitment_schedule as worker_fixture

PERIODS = ('접수: 2026-09-28~2026-10-29\n'
           '운영: 2026-10-02~2026-10-30\n'
           '모든 시간은 한국시간(Asia/Seoul)입니다.\n')
SUMMARY_DUPLICATE = SUMMARY.replace('[일정 안내]\n', '[일정 안내]\n'+PERIODS)

class ScheduleDisplayTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden'))
        guard.start();self.addCleanup(guard.stop)

    def test_reported_period_table_evidence_and_zone_duplicates(self):
        f=session_context()['facts'];before=copy.deepcopy(f)
        body=assemble_seoul_body(SUMMARY_DUPLICATE,f)
        self.assertIn(TABLE,body)
        self.assertNotIn('접수:',body);self.assertNotIn('운영:',body)
        self.assertEqual(body.count('신청기간:'),1);self.assertEqual(body.count('진행기간:'),1)
        self.assertNotIn('Asia/Seoul',body)
        self.assertIn('한국시간',body)
        self.assertNotIn('**진행 일정:**',body)
        self.assertEqual(f,before)
        self.assertEqual(body,assemble_seoul_body(body,f))

    def test_alias_conflicts_fail_before_any_cleanup(self):
        for bad in [SUMMARY_DUPLICATE.replace('2026-10-29','2026-10-28'),
                    SUMMARY_DUPLICATE.replace('운영: 2026-10-02','운영: 2026-10-02 01:00:00'),
                    SUMMARY_DUPLICATE.replace('2026-10-30','2027-10-30')]:
            with self.assertRaises(AiJobError):assemble_seoul_body(bad,session_context()['facts'])

    def test_partial_table_retains_only_unrepresented_source_session(self):
        partial=SUMMARY.replace('| 2026-10-30(금) | 10:00~11:30 | 14:00~15:30 |','')
        body=assemble_seoul_body(partial,session_context()['facts'])
        self.assertNotIn('- 10월 2일',body)
        self.assertIn('- 10월 30일',body)
        self.assertEqual(body,assemble_seoul_body(body,session_context()['facts']))

    def test_explicit_source_year_not_erased_by_a_yearless_table(self):
        f=session_context()['facts'];f['description']=f['description'].replace('10월','2026년 10월')
        content=SUMMARY.replace('2026-10-02','10월 2일').replace('2026-10-30','10월 30일')
        body=assemble_seoul_body(content,f)
        self.assertIn('- 2026년 10월 2일',body);self.assertIn('- 2026년 10월 30일',body)

    def test_no_table_and_unique_source_instructions_stay(self):
        f=session_context()['facts']
        no_table=SUMMARY.replace(TABLE,'운영 프로그램입니다.')
        body=assemble_seoul_body(no_table,f)
        self.assertIn('- 10월 2일',body);self.assertIn('- 10월 30일',body)
        f['description']+='\n집결 일시: 10월 2일 09:50~10:00 보호자 동반 필수'
        body=assemble_seoul_body(SUMMARY,f)
        self.assertIn('09:50~10:00 보호자 동반 필수',body)

    def test_equal_numbers_cannot_hide_swapped_or_missing_times(self):
        bad=SUMMARY.replace('| 2026-10-02(금) | 10:00~11:30 | 14:00~15:30 |',
                            '| 2026-10-02(금) | 10:00~15:30 | 14:00~11:30 |')
        with self.assertRaises(AiJobError):assemble_seoul_body(bad,session_context()['facts'])
        missing=SUMMARY.replace('| 2026-10-02(금) | 10:00~11:30 | 14:00~15:30 |',
                                '| 2026-10-02(금) | 10:00~11:30 | 오후 안내 |')
        self.assertIn('- 10월 2일',assemble_seoul_body(missing,session_context()['facts']))

    def test_qualified_period_and_opaque_zone_identifier_preserved(self):
        content=SUMMARY_DUPLICATE.replace('접수: 2026-09-28~2026-10-29',
             '접수: 2026-09-28~2026-10-29, 정원 충족 시 조기 마감')
        content=content.replace('낙엽을 관찰합니다.',
             '낙엽을 관찰합니다.\nhttps://synthetic.invalid/Asia/Seoul?zone=Asia/Seoul\n한국시간 기준으로 안내합니다.')
        body=assemble_seoul_body(content,session_context()['facts'])
        self.assertIn('정원 충족 시 조기 마감',body)
        self.assertIn('https://synthetic.invalid/Asia/Seoul?zone=Asia/Seoul',body)
        self.assertIn('한국시간 기준으로 안내합니다.',body)

    def test_application_method_alias_without_dates_is_not_a_period(self):
        content=SUMMARY.replace('[일정 안내]\n','[일정 안내]\n접수: 전화로 문의 후 신청하세요.\n')
        body=assemble_seoul_body(content,session_context()['facts'])
        self.assertIn('접수: 전화로 문의 후 신청하세요.',body)
        self.assertNotIn('신청기간: 전화',body)

    def test_normal_and_reclassified_worker_get_clean_translation_input(self):
        # Reuse the formal fake worker harness, checking its actual translation
        # input/finish output while keeping all real connections forbidden.
        test=worker_fixture.RecruitmentScheduleTests()
        for classified in (False,True):
            with patch('test_seoul_recruitment_schedule.fake_japanese', side_effect=self.clean_translation):
                test.run_fake_worker(classified,SUMMARY_DUPLICATE,False)

    def test_wrong_period_alias_stops_both_workers_before_translation_and_finish(self):
        test=worker_fixture.RecruitmentScheduleTests()
        for classified in (False,True):
            test.run_fake_worker(classified,SUMMARY_DUPLICATE.replace('2026-10-29','2026-10-28'),True)

    def test_shared_prompt_rules_are_scoped_to_seoul_and_not_duplicated(self):
        from ingest.ai_claude import (summary_system_prompt,PROGRAM_SUMMARY_SYSTEM,SUMMARY_SYSTEM,
                                     SEOUL_SCHEDULE_DISPLAY_RULES)
        native=session_context()['facts']
        self.assertEqual(summary_system_prompt('{}',True),PROGRAM_SUMMARY_SYSTEM)
        packet=json.dumps({'inputContract':'review-classification-ai-v1',
                           'nativeConfirmedFacts':{'programFacts':native}})
        for program in (False,True):
            prompt=summary_system_prompt(packet,program)
            self.assertEqual(prompt.count(SEOUL_SCHEDULE_DISPLAY_RULES.strip()),1)
        self.assertEqual(summary_system_prompt('{}'),SUMMARY_SYSTEM)
        self.assertIn('Do not print IANA',PROGRAM_SUMMARY_SYSTEM)

    def test_nonzero_seconds_and_timezone_interpretation_survive_display_cleanup(self):
        f=session_context()['facts']
        f['periods']['RCPTBGNDT'].update(value='2026-09-28T01:02:03+00:00',precision='second')
        f['periods']['RCPTENDDT'].update(value='2026-10-29T08:02:07+00:00',precision='second')
        content=SUMMARY.replace('[일정 안내]\n',
            '[일정 안내]\n접수: 2026-09-28T01:02:03+00:00 ~ 2026-10-29T08:02:07+00:00\n시간 기준: Asia/Seoul\n')
        before=copy.deepcopy(f)
        body=assemble_seoul_body(content,f)
        self.assertIn('2026-09-28 10:02:03 ~ 2026-10-29 17:02:07',body)
        self.assertNotIn('Asia/Seoul',body);self.assertNotIn('+00:00',body)
        self.assertEqual(f,before)
        with self.assertRaises(AiJobError):
            assemble_seoul_body(content.replace('08:02:07','08:02:08'),f)

    def test_equal_source_table_once_and_other_cells_not_erased(self):
        from test_seoul_content import synthetic_facts,SUMMARY as class_summary
        f=synthetic_facts()
        table='| 회차 | 일시 | 활동 |\n| --- | --- | --- |\n| 1회차 | 10월 18일 10:00~12:00 | 공예 |\n| 2회차 | 10월 25일 10:00~12:00 | 완성 |'
        f['description']='정원: 20명\n'+table
        content=class_summary.replace('[일정 안내]\n','[일정 안내]\n'+table+'\n')
        body=assemble_seoul_body(content,f)
        self.assertEqual(body.count(table),1)
        self.assertEqual(body,assemble_seoul_body(body,f))
        # A generated table with a different supported layout is retained;
        # the exact source table still supplies its original cells as evidence.
        alternate=table.replace('회차 | 일시 | 활동','회차 | 시간 | 활동')
        body=assemble_seoul_body(content.replace(table,alternate),f)
        self.assertIn(table,body);self.assertIn(alternate,body)

    def clean_translation(self,body):
        from test_seoul_content import fake_japanese
        self.assertIn(TABLE,body);self.assertNotIn('Asia/Seoul',body)
        self.assertNotIn('**진행 일정:**',body)
        self.assertEqual(body.count('신청기간:'),1)
        return fake_japanese(body)

if __name__=='__main__':unittest.main()
