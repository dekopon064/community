"""Retained two actual replies; synthetic identities, fake Pro/JA/RPC only."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ingest.ai_errors import AiJobError
from ingest.seoul_content import assemble_seoul_body, validation_view
from ingest.seoul_operating_hours import validate_facility_hours_clause
from ingest.seoul_schedule_display import _display_values
from ingest.program_ai import program_input
from ingest.reclassification_ai import classification_input
import test_seoul_date_hours_replay as date_hours_fixture
from test_seoul_date_hours_replay import context, synthetic_translation

FIXTURE=Path(__file__).parent/'testdata/seoul_hours_clause_display_recorded.json'


def recorded():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def replay_fixture():
    values=recorded()
    for d in values:
        # Historical JA is retained only for inspection. It translated the old
        # repeated/time-bearing KO, not the new assembled body. Never reuse it.
        body=assemble_seoul_body(d['summary']['content_ko'],d['facts'])
        d['translation_input_ko']=body
        d['translation']={'title_ja':'合成文化体験','content_ja':synthetic_translation(body)}
    return values


class HoursClauseDisplayTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect','socket.create_connection','socket.getaddrinfo',
                     'ingest.supabase_store.create_ingest_client','ingest.chatgpt_plan_auth.authenticate_worker'):
            guard=patch(name,side_effect=AssertionError('real connection forbidden'))
            guard.start();self.addCleanup(guard.stop)

    def replay(self,index,classified=False,**kwargs):
        with patch('test_seoul_date_hours_replay.recorded',side_effect=replay_fixture):
            return date_hours_fixture.DateHoursReplayTests.replay(self,index,classified,**kwargs)

    def test_retained_hanyang_body_before_after_and_idempotence(self):
        d=recorded()[0];raw=FIXTURE.read_bytes();facts=copy.deepcopy(d['facts'])
        self.assertIn('00:00',d['before_ko']);self.assertIn('**진행 일정:**',d['before_ko'])
        self.assertIn('- **대상:**',d['before_ko']);self.assertIn('- **참가 조건:**',d['before_ko'])
        body=assemble_seoul_body(d['summary']['content_ko'],facts)
        for duplicate in ('00:00','**진행 일정:**','- **대상:**','- **참가 조건:**'):
            self.assertNotIn(duplicate,body)
        for text in ('성인만 신청·참여 가능','이전 회차 참여자는 신청할 수 없습니다',
                     '회당 12 명','선착순으로 접수','2026.10.7.(수)','2026.10.14.(수)',
                     '18:45','흥인재','흥인지문 공원 안내판','깃발','2026-10-13 17:00'):
            self.assertIn(text,body)
        self.assertEqual(body.count('19:00~21:00'),2)
        self.assertIn('**진행기간:** 2026-10-07 ~ 2026-10-14',body)
        self.assertEqual(body,assemble_seoul_body(body,facts))
        self.assertEqual(body,assemble_seoul_body(d['before_ko'],facts))
        self.assertEqual(facts,d['facts']);self.assertEqual(FIXTURE.read_bytes(),raw)

    def test_retained_facility_clause_and_unique_instructions_survive(self):
        d=recorded()[1];facts=copy.deepcopy(d['facts']);view=validation_view(facts)
        self.assertEqual(len(view['facility_hours_evidence']),2)
        line='센터 운영시간은 09:00~17:00이며 실제 회차 시간은 별도 협의가 필요합니다.'
        self.assertTrue(validate_facility_hours_clause(line,view))
        body=assemble_seoul_body(d['summary']['content_ko'],facts)
        for text in (line,'설·추석','근로자의 날','10명이상','02-305-1334','2일 전',
                     '개인정보 동의서','사진을 촬영','안전사고 책임','주차비 지원은 없습니다',
                     '별도 취소 안내가 없으면 우천 시에도 진행','엘리베이터','전체 인원으로 예약'):
            self.assertIn(text,body)
        # Facility hours alone are not proof that midnight period endpoints are
        # display-only or that 09-17 are fixed program sessions.
        self.assertIn('**진행기간:** 2026-03-28 00:00 ~ 2026-12-31 00:00',body)
        self.assertEqual(body,assemble_seoul_body(body,facts));self.assertEqual(facts,d['facts'])

    def test_facility_sentence_order_and_time_roles(self):
        view=validation_view(recorded()[1]['facts'])
        for line in ('센터 운영시간은 09:00~17:00입니다. 실제 회차 시간은 별도 협의가 필요합니다.',
                     '실제 회차 시간은 별도 협의가 필요합니다. 센터 운영시간은 09:00~17:00입니다.',
                     '센터 운영시간은 오전 9시~오후 5시이고 실제 일정은 사전 협의합니다.'):
            self.assertTrue(validate_facility_hours_clause(line,view),line)
        for line in ('센터 운영시간은 08:00~17:00이며 실제 회차 시간은 별도 협의가 필요합니다.',
                     '센터 운영시간은 09:00~17:00입니다. 프로그램은 매일 09:00~17:00 진행합니다.',
                     '센터 운영시간은 09:00~17:00입니다. 실제 회차 시간은 09:00~17:00입니다.',
                     '센터 접수시간은 09:00~17:00입니다.', '센터 관람시간은 09:00~17:00입니다.'):
            with self.subTest(line=line),self.assertRaises(AiJobError):
                validate_facility_hours_clause(line,view)
        without=copy.deepcopy(view);without['description']='센터 운영시간: 09시~17시'
        with self.assertRaises(AiJobError):
            validate_facility_hours_clause('센터 운영시간은 09:00~17:00이며 실제 회차 시간은 별도 협의가 필요합니다.',without)

    def test_unknown_bundle_tail_and_negative_prose_are_not_dedup_proof(self):
        d=recorded()[0]
        for tail in (', 보호자 동반 필수',', 거주 증빙 제출 필수',', 예약 취소는 2일 전까지',
                     ', 선착순 접수 아님',', 재료비는 별도 납부','\n  보호자 동반 필수'):
            facts=copy.deepcopy(d['facts']);facts['conditions'][0]+=tail
            body=assemble_seoul_body(d['summary']['content_ko'],facts)
            self.assertIn(tail,body);self.assertIn('**참가 조건:**',body)
        content=d['summary']['content_ko'].replace('이전 회차 참여자는 신청할 수 없습니다','이전 회차 참여자도 신청 가능합니다')
        body=assemble_seoul_body(content,d['facts'])
        self.assertIn('이전회차 참여자 신청불가',body)
        content=d['summary']['content_ko'].replace('선착순으로 접수합니다','선착순 접수는 하지 않습니다')
        self.assertIn('**참가 조건:** 선착순 접수',assemble_seoul_body(content,d['facts']))

    def test_dot_dates_am_pm_and_changed_dates_are_not_case_constants(self):
        values=_display_values("'26.10.7.(수)/10.14.(수), 오후7시-오후9시",years=frozenset({2026}))
        self.assertEqual(values['dates'],{(10,7),(10,14)});self.assertEqual(values['times'],{(1140,1260)})
        d=recorded()[0];facts=copy.deepcopy(d['facts']);content=d['summary']['content_ko']
        replacements={'10.7.':'11.4.','10.14.':'11.11.','19:00~21:00':'17:00~19:00',
                      '오후7시-오후9시':'오후5시-오후7시','12 명':'18 명','18:45':'16:45'}
        for a,b in replacements.items():
            content=content.replace(a,b);facts['description']=facts['description'].replace(a,b)
            facts['conditions']=[v.replace(a,b) for v in facts['conditions']]
        facts['periods']['SVCOPNBGNDT']['value']='2026-11-04T00:00:00+09:00'
        facts['periods']['SVCOPNENDDT']['value']='2026-11-11T00:00:00+09:00'
        body=assemble_seoul_body(content,facts)
        self.assertNotIn('00:00',body);self.assertNotIn('**진행 일정:**',body)
        self.assertIn('회당 18 명',body);self.assertEqual(body.count('17:00~19:00'),2)

    def test_partial_tables_and_unique_schedule_notes_remain(self):
        d=recorded()[0];content=d['summary']['content_ko']
        partial=content.replace('| 2026.10.14.(수) | 19:00~21:00 | 한양도성·충신성곽마을 해설 및 원예체험 |','')
        self.assertIn('**진행 일정:**',assemble_seoul_body(partial,d['facts']))
        facts=copy.deepcopy(d['facts']);facts['description']=facts['description'].replace('오후7시-오후9시','오후7시-오후9시 보호자 동반 필수')
        self.assertIn('보호자 동반 필수',assemble_seoul_body(content,facts))

    def test_multi_day_clocks_cannot_be_covered_by_an_unbound_value_bag(self):
        from ingest.seoul_schedule_display import clean_schedule_display
        from ingest.seoul_content import reviewed_sections
        d=recorded()[0];facts=copy.deepcopy(d['facts'])
        facts['description']='운영일시: 2026.10.7.(수) 19:00~21:00 / 2026.10.9.(금) 18:00~20:00'
        facts['periods']['SVCOPNENDDT']['value']='2026-10-09T00:00:00+09:00'
        table='[일정 안내]\n| 날짜 | 시간 |\n| --- | --- |\n| 2026.10.7.(수) | 19:00~21:00 |\n| 2026.10.9.(금) | 18:00~20:00 |'
        _,sections=clean_schedule_display(table,reviewed_sections(facts),validation_view(facts))
        self.assertNotIn('**진행 일정:**',sections['[일정 안내]'])
        self.assertNotIn('00:00',sections['[일정 안내]'])
        wrong=table.replace('19:00~21:00','18:00~20:00',1)
        _,sections=clean_schedule_display(wrong,reviewed_sections(facts),validation_view(facts))
        self.assertIn('**진행 일정:**',sections['[일정 안내]'])

    def test_identical_clocks_on_separate_dates_keep_their_own_associations(self):
        from ingest.seoul_calendar_sessions import record_calendar_sessions
        d=recorded()[0];facts=copy.deepcopy(d['facts'])
        facts['description']='운영일시: 2026.10.7.(수) 19:00~21:00 / 2026.10.14.(수) 19:00~21:00'
        records=record_calendar_sessions(facts['description'],years=frozenset({2026}))
        self.assertEqual(records,[((2026,10,7),(('time',19,0),('time',21,0))),
                                  ((2026,10,14),(('time',19,0),('time',21,0)))])
        body=assemble_seoul_body(d['summary']['content_ko'],facts)
        self.assertNotIn('**진행 일정:**',body);self.assertNotIn('00:00',body)
        self.assertEqual(body.count('19:00~21:00'),2)
        bad=d['summary']['content_ko'].replace('| 2026.10.14.(수) | 19:00~21:00 |',
                                            '| 2026.10.14.(수) | 18:00~21:00 |')
        with self.assertRaises(AiJobError):assemble_seoul_body(bad,facts)

    def test_actual_midnight_overnight_day_precision_and_cutoffs_stay(self):
        d=recorded()[0];minimal='[한 줄 요약]\n합성 야간 체험입니다.\n[주요 내용]\n역사 해설과 체험입니다.'
        for clocks in ('00:00~01:00','23:00~00:00','23:00~01:00'):
            facts=copy.deepcopy(d['facts']);facts['description']="운영일시: '26.10.7.(수)/10.14.(수), "+clocks
            body=assemble_seoul_body(minimal,facts)
            self.assertIn('00:00 ~',body);self.assertIn(clocks,body)
        facts=copy.deepcopy(d['facts']);facts['periods']['RCPTENDDT']['value']='2026-10-13T00:00:00+09:00'
        body=assemble_seoul_body(d['summary']['content_ko'],facts)
        self.assertIn('2026-10-13 00:00',body);self.assertNotIn('진행기간:** 2026-10-07 00:00',body)
        facts=copy.deepcopy(d['facts']);facts['periods']['SVCOPNENDDT']['value']='2026-10-14T00:00:01+09:00'
        self.assertIn('00:00:01',assemble_seoul_body(d['summary']['content_ko'],facts))
        for k in ('SVCOPNBGNDT','SVCOPNENDDT'):
            facts['periods'][k].update(value=facts['periods'][k]['value'][:10],precision='day')
        body=assemble_seoul_body(d['summary']['content_ko'],facts)
        self.assertNotIn('00:00',body)

    def test_general_reclassified_fake_pro_translation_and_fenced_candidates(self):
        for index in (0,1):
            for classified in (False,True):
                with self.subTest(index=index,classified=classified):
                    r,events,outputs,calls=self.replay(index,classified)
                    self.assertEqual((r.completed,r.failed,r.state_unknown),(1,0,0))
                    self.assertEqual(len(calls),2);self.assertEqual(len(outputs),1)
                    out=outputs[0]
                    self.assertEqual(calls[1]['input'][0]['content'],'title_ko: '+out['titleKo']+'\ncontent_ko:\n'+out['contentKo'])
                    if index==0:
                        self.assertNotIn('00:00',out['contentKo']);self.assertNotIn('**진행 일정:**',out['contentKo'])
                    else:self.assertIn('09:00~17:00',out['contentKo'])
                    self.assertEqual(sum(n.startswith('finish_') for n,_ in events),1)

    def test_current_description_before_observations_for_both_inputs(self):
        with patch('test_seoul_date_hours_replay.recorded',side_effect=replay_fixture):
            for classified in (False,True):
                c=context(1,classified)
                if not classified:c['observedFacts']['description']='과거 관측 설명, 시간 근거 없음'
                text=classification_input(c) if classified else program_input(c)
                self.assertIn('facilityHoursEvidence',text)
                self.assertIn('09시~17시',text);self.assertIn('전화나 현장방문',text)

    def test_true_date_time_quantity_conflicts_fail_before_translation(self):
        for classified in (False,True):
            for index,change in ((0,lambda s:s.replace('2026.10.7.(수)','2026.10.8.(목)')),
                                 (0,lambda s:s.replace('19:00~21:00','18:00~21:00')),
                                 (0,lambda s:s.replace('[대상]','[대상]\n정원: 13명')),
                                 (1,lambda s:s.replace('09:00~17:00','08:00~17:00')),
                                 (1,lambda s:s.replace('센터 운영시간은 09:00~17:00이며 실제 회차 시간은 별도 협의가 필요합니다.',
                                                      '프로그램은 매일 09:00~17:00 진행합니다.'))):
                r,e,out,calls=self.replay(index,classified,bad_ko=change)
                self.assertEqual((r.completed,r.failed),(0,1));self.assertEqual(len(calls),1)
                self.assertFalse(out);self.assertEqual(e[-1][0],'fail_seoul_ai_no_retry')

    def test_existing_candidate_stale_and_unknown_results_have_no_retry(self):
        for classified in (False,True):
            r,e,out,calls=self.replay(1,classified,skip=True)
            self.assertEqual(len(calls),0);self.assertEqual(len(e),1)
            r,e,out,calls=self.replay(1,classified,claim_change=lambda c:c.update(revision='b'*64))
            self.assertEqual(r.state_unknown,1);self.assertEqual(len(calls),0)
            r,e,out,calls=self.replay(1,classified,unknown='completion')
            self.assertEqual(r.state_unknown,1);self.assertEqual(len(calls),2);self.assertFalse(out)
            r,e,out,calls=self.replay(1,classified,unknown='failure',bad_ko=lambda s:s.replace('09:00','08:00'))
            self.assertEqual(r.state_unknown,1);self.assertEqual(len(calls),1);self.assertFalse(out)


if __name__=='__main__':unittest.main()
