"""Recorded response + synthetic day/multi-day/weekday cases; no live IO."""
import copy
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from ingest.ai_errors import AiJobError
from ingest.seoul_content import assemble_seoul_body, validation_view, reviewed_sections
from ingest.seoul_fact_roles import public_roles, weekly_schedule, validate_weekly_schedule
from ingest.translation_validation import _quantities, _validate_cell, validate_translation_fidelity
import test_seoul_per_session_replay as worker_fixture
from test_seoul_content import SUMMARY, synthetic_facts

FIXTURE = Path(__file__).parent/'testdata/seoul_weekly_roles_recorded.json'
BASE_CASE = worker_fixture.recorded_case


def recorded():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def confirmed_case():
    """Explicit local reviewed-table fixture; never rewrite recorded observations.

    The actual API description lost empty positions. Successful replay now needs
    separately confirmed intact text, not a plausible AI-generated replacement.
    """
    data = recorded()
    table = json.loads((FIXTURE.parent/'seoul_weekly_input_recorded.json').read_text(encoding='utf-8'))['reviewed_table']
    data['facts']['description'] = re.sub(r'시간 / 요일.*?(?=▹ 해설시간)', table+'\n\n',
        data['facts']['description'], flags=re.S)
    return data


def fake_translation(body):
    """Explicit fake Japanese for new input; never a regenerated model result."""
    fixture=recorded()['fake_translation_cleaned']
    if body.strip()==fixture['content_ko'].strip():
        return fixture['content_ja']
    from test_seoul_content import fake_japanese
    body=body.replace('회차당','各回').replace('회당','各回')
    body=re.sub(r'(\d+)\s*회차',r'第\1回',body)
    body=re.sub(r'(\d+)\s*인당',r'\1人当たり',body)
    body=re.sub(r'(\d+)\s*인(?!당|분|가구)',r'\1名',body)
    for ko, ja in (('일본어', '日本語'), ('중국어', '中国語'), ('영어', '英語'), ('한국어', '韓国語')):
        body=body.replace('('+ko+')', '('+ja+')')
    for ko,ja in zip('월화수목금토일','月火水木金土日'):
        body=re.sub(r'(?<=\|)\s*'+ko+r'\s*(?=\|)', ' '+ja+' ', body)
    body=body.replace('내외','程度').replace('분','分').replace('불가합니다','できません').replace('수 없습니다','できません')
    return fake_japanese(body)


def replay_context(classified=False):
    d=confirmed_case(); legacy,c=BASE_CASE(classified)
    f=copy.deepcopy(d['facts'])
    endpoints={name:{k:v[k] for k in ('value','precision')} for name,v in f['periods'].items()}
    c.update(title=d['title'])
    if classified:
        c.update(body=f['description'],sourceUrl=f['official_url'])
        c['nativeConfirmedFacts']['programFacts']=f
        c['filters']['application']['value'].update(
            start=endpoints['RCPTBGNDT'],end=endpoints['RCPTENDDT'],sourceStatus='open')
        c['facts'].update(delivery='offline',scope='unknown',regions=[],evidence='',
                          deadlineOn=f['periods']['RCPTENDDT']['value'][:10])
    else:
        c.update(facts=f,observedFacts=copy.deepcopy(recorded()['facts']))
        c['filterContext']['data']['application']['value'].update(
            start=endpoints['RCPTBGNDT'],end=endpoints['RCPTENDDT'],sourceStatus='open')
    legacy.update(context={'facts':f},summary=d['summary'],translation=d['actual_translation'],
                  expected_translation_input={'content_ko':d['before_ko']})
    return legacy,c


class SeoulFactRolesTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect','socket.create_connection','socket.getaddrinfo',
                       'ingest.supabase_store.create_ingest_client','ingest.chatgpt_plan_auth.authenticate_worker'):
            guard=patch(target,side_effect=AssertionError('real connection forbidden'))
            guard.start();self.addCleanup(guard.stop)

    def test_recorded_failure_and_correct_actual_translation(self):
        d=recorded();before=FIXTURE.read_bytes();j=d['actual_translation']
        self.assertIn('2026-10-01 00:00 ~ 2026-10-31 00:00',d['before_ko'])
        self.assertIn('참가 조건:** 1 회차',d['before_ko'])
        with patch.dict('ingest.translation_validation._QUANTITY_UNITS',{False:r'명|세|회|가족'}):
            with self.assertRaises(AiJobError):
                _validate_cell('인원: 회차당 15 인 내외','人数：各回15人程度')
        validate_translation_fidelity(d['title'],d['before_ko'],j['title_ja'],j['content_ja'])
        self.assertEqual(FIXTURE.read_bytes(),before)

    def test_recorded_roles_cleanup_and_preserved_values(self):
        d=confirmed_case();f=d['facts'];before=copy.deepcopy(f)
        roles=public_roles(f);self.assertEqual(len(roles['booking']),1)
        self.assertEqual(len(roles['capacity']),1)
        self.assertFalse(any(re.fullmatch(r'\d+\s*회차',v) for v in roles['eligibility']))
        body=assemble_seoul_body(d['summary']['content_ko'],f)
        self.assertNotIn('00:00',body);self.assertNotIn('**진행 일정:**',body)
        self.assertNotIn('**참가 조건:**',body)
        self.assertEqual(body.count('15 인'),1)
        self.assertIn('**진행기간:** 2026-10-01 ~ 2026-10-31',body)
        self.assertIn('2026-10-30 17:30',body)
        self.assertIn('내국인은 참여할 수 없습니다',body)
        self.assertEqual(body.count('공휴일'),2)  # exclusion + possible schedule change
        self.assertIn('| 16:00 | — | 5회차(일본어) | 5회차(중국어) | 5회차(영어)',body)
        self.assertIn('02-724-0200, 0232',body);self.assertIn('예약자 신원 확인',body)
        self.assertIn('잔여 인원에 한해 현장접수',body)
        self.assertEqual(body,assemble_seoul_body(body,f));self.assertEqual(f,before)

    def test_day_and_multi_day_session_dates_activity_and_application_cutoff(self):
        for days in [('18','18'),('18','25')]:
            f=synthetic_facts()
            f['description']='합성 체험\n정원: 20명\n'+ '\n'.join(
                f'{i}회차: 10월 {day}일 10:00~12:00 활동: 공예' for i,day in enumerate(dict.fromkeys(days),1))
            for k,day in zip(('SVCOPNBGNDT','SVCOPNENDDT'),days):
                f['periods'][k].update(value=f'2099-10-{day}T00:00:00+09:00',precision='second')
            f['periods']['RCPTENDDT'].update(value='2099-10-10T00:00:00+09:00',precision='second')
            source=SUMMARY.replace('2099-10-25',f'2099-10-{days[1]}')
            body=assemble_seoul_body(source,f)
            operation=next(line for line in body.splitlines() if '**진행기간:**' in line)
            self.assertNotIn('00:00',operation)
            self.assertIn('2099-10-10 00:00',body)
            for day in set(days):self.assertIn(f'10월 {day}일 10:00~12:00 활동: 공예',body)
            self.assertEqual(body,assemble_seoul_body(body,f))

    def test_real_midnight_overnight_and_unknown_precision_evidence_are_kept(self):
        for text in ('1회차: 10월 18일 00:00~01:00','1회차: 10월 18일 23:00~00:00',
                     '1회차: 10월 18일 23:00~01:00','1회차: 10월 18일','일정 별도 안내'):
            f=synthetic_facts();f['description']='합성 체험\n'+text
            for k in ('SVCOPNBGNDT','SVCOPNENDDT'):
                f['periods'][k].update(value='2099-10-18T00:00:00+09:00',precision='second')
            minimal='[한 줄 요약]\n합성 체험입니다.\n[주요 내용]\n공예 체험입니다.'
            body=assemble_seoul_body(minimal,f)
            self.assertIn('2099-10-18 00:00 ~ 2099-10-18 00:00',body)

    def test_weekly_rows_clocks_ordinals_languages_and_dated_conflicts_block(self):
        d=confirmed_case();source=d['summary']['content_ko'];f=d['facts']
        changes=[source.replace('| 11:00 |','| 12:00 |'),
                 source.replace('5회차(일본어)','5회차(영어)'),
                 source.replace('| 14:00 | 3회차 |','| 14:00 | 4회차 |'),
                 source.replace('| 화 | 수 |','| 수 | 화 |'),
                 source.replace('| 16:00 | — | 5회차(일본어) | 5회차(중국어) | 5회차(영어) | 4회차 | 4회차 |','')]
        for changed in changes:
            with self.subTest(changed=changed),self.assertRaises(AiJobError):assemble_seoul_body(changed,f)
        for row in ('진행기간: 2027-10-01 ~ 2027-10-31','진행기간: 2026-10-01 ~ 2026-10-30',
                    '진행기간: 2026-10-01 10:00 ~ 2026-10-31 17:00'):
            with self.assertRaises(AiJobError):assemble_seoul_body(source.replace('[일정 안내]','[일정 안내]\n'+row),f)

    def test_structured_weekly_cells_cannot_shift_to_a_different_day(self):
        table='| 시간 | 화 | 목 |\n| --- | --- | --- |\n| 10:00 | 1회차 | — |\n| 14:00 | — | 2회차(일본어) |'
        validate_weekly_schedule(table,table)
        with self.assertRaises(AiJobError):validate_weekly_schedule(table.replace('1회차 | —','— | 1회차'),table)
        self.assertFalse(weekly_schedule(table).flattened)
        self.assertTrue(weekly_schedule(recorded()['facts']['description']).flattened)

    def test_new_regular_source_matrix_keeps_empty_column_positions(self):
        from ingest.connectors.seoul_reservation import parse_body
        html='<table><tr><td>시간 / 요일</td><td>화</td><td>목</td></tr><tr><td>10:00</td><td>1회차</td><td></td></tr><tr><td>14:00</td><td></td><td>2회차(일본어)</td></tr></table>'
        description=parse_body(html)['program_text']
        self.assertIn('| 10:00 | 1회차 | — |',description)
        self.assertIn('| 14:00 | — | 2회차(일본어) |',description)
        self.assertFalse(weekly_schedule(description).flattened)
        f=copy.deepcopy(recorded()['facts']);f['description']=description
        f['conditions']=description.splitlines()
        roles=public_roles(f)
        self.assertFalse(any('| 10:00 |' in v for v in roles['eligibility']))
        validate_weekly_schedule(description,description)
        with self.assertRaises(AiJobError):
            validate_weekly_schedule(description.replace('1회차 | —','— | 1회차'),description)
        # Do not invent blank positions in merged/unsupported source tables.
        self.assertNotIn('| --- |',parse_body(html.replace('<td>1회차</td>','<td colspan="2">1회차</td>'))['program_text'])

    def test_mixed_conditions_and_unknown_booking_steps_are_preserved(self):
        d=confirmed_case();f=copy.deepcopy(d['facts'])
        conditions=['일본어 가능자만 참여', '2회차 모두 참여 필수', '보호자 동반 필수',
                    '거주자만 가능', 'D-2 비자 소지자만 신청',
                    '예약 단계: 현장 신청 → 서류 제출 필수',
                    '검색 → 신청 선택 → 10,000원 납부']
        f['conditions']+=conditions
        f['description']+='\n'+'\n'.join(conditions)
        body=assemble_seoul_body(d['summary']['content_ko'],f)
        for text in conditions:self.assertIn(text,body)
        self.assertIn('예약 단계: 현장 신청 → 서류 제출 필수',body.split('[신청 방법]')[1])
        self.assertNotIn('예약 단계:',body.split('[대상]')[1].split('[일정 안내]')[0])
        self.assertIn('모집 인원',body)
        before=copy.deepcopy(f);assemble_seoul_body(body,f);self.assertEqual(f,before)

    def test_people_units_synonyms_denominators_and_normal_counterexamples(self):
        for ko,ja in [('인원: 회차당 15 인 내외','人数：各回15人程度'),
                      ('선착순 30인','先着30名'),('정원: 10~15인','定員：10～15人'),
                      ('정원: 15인 이하','定員：15人以下'),
                      ('약 15인','約15名'),('15 인 내외','15名前後'),
                      ('수강료: 1인당 10,000원','受講料：1人当たり10,000ウォン'),
                      ('음식: 2인분','食事：2人分')]:
            _validate_cell(ko,ja)
        for ja in ('人数：各回16人程度','人数：2回当たり15人程度','人数：各回15歳程度','人数：各回15人'):
            with self.assertRaises(AiJobError):_validate_cell('인원: 회차당 15 인 내외',ja)
        with self.assertRaises(AiJobError):_validate_cell('수강료: 1인당 10,000원','受講料：2人当たり10,000ウォン')
        self.assertEqual(_quantities('1인당, 2인분, 4인가구',japanese=False),{})

    def test_different_names_counts_months_and_regular_midnight_matrix(self):
        d=confirmed_case();f=copy.deepcopy(d['facts'])
        f['description']=f['description'].replace('백인제','합성').replace('15 인','23 명').replace('10:00','09:30')
        f['conditions']=[v.replace('백인제','합성').replace('15 인','23 명') for v in f['conditions']]
        for k,day in [('SVCOPNBGNDT','01'),('SVCOPNENDDT','30')]:
            f['periods'][k]['value']=f'2026-11-{day}T00:00:00+09:00'
        source=d['summary']['content_ko'].replace('백인제','합성').replace('10:00','09:30')
        body=assemble_seoul_body(source,f)
        self.assertIn('2026-11-01 ~ 2026-11-30',body);self.assertIn('23 명',body)
        self.assertIn('| 09:30 |',body);self.assertNotIn('참가 조건:** 1 회차',body)
        f['description']=f['description'].replace('09:30','00:00')
        body=assemble_seoul_body(source.replace('09:30','00:00'),f)
        self.assertIn('2026-11-01 00:00 ~ 2026-11-30 00:00',body)

    def test_json_explanation_and_real_period_conflict_stop_before_translation(self):
        original=replay_context
        for addition in ('\nJSON 출력: content_ko만 반환합니다.',
                         '\n신청기간: 2026-09-20 10:00 ~ 2026-10-30 18:00'):
            def changed(classified=False):
                data,c=original(classified)
                data['summary']={**data['summary'],'content_ko':data['summary']['content_ko']+addition}
                return data,c
            for classified in (False,True):
                with patch.object(worker_fixture,'recorded_case',side_effect=changed),patch.object(
                        worker_fixture,'fake_translation',side_effect=fake_translation):
                    result,calls,output,requests,_=worker_fixture.run_recorded(self,classified=classified)
                self.assertEqual(len(requests),1);self.assertEqual(result.completed,0);self.assertFalse(output)
                self.assertFalse(any(n.startswith('finish_') for n,_ in calls))

    def replay(self,change=None,finish_unknown=False,claim_change=None):
        original=replay_context
        outputs=[]
        for classified in (False,True):
            with patch.object(worker_fixture,'recorded_case',side_effect=original),patch.object(
                    worker_fixture,'fake_translation',side_effect=fake_translation):
                outputs.append(worker_fixture.run_recorded(self,classified=classified,change=change,
                    finish_unknown=finish_unknown,claim_change=claim_change))
        return outputs

    def test_both_workers_complete_fake_candidates_with_clean_translation_input(self):
        for result,calls,output,requests,d in self.replay():
            self.assertEqual(result.completed,1)
            self.assertEqual(len(requests),2);self.assertEqual(sum(n.startswith('finish_') for n,_ in calls),1)
            self.assertEqual(requests[1]['input'][0]['content'],'title_ko: '+output['titleKo']+'\ncontent_ko:\n'+output['contentKo'])
            self.assertNotIn('00:00',output['contentKo']);self.assertNotIn('**진행 일정:**',output['contentKo'])
            self.assertEqual(output['contentKo'].count('15 인'),1)
            self.assertEqual(output['contentKo'],recorded()['fake_translation_cleaned']['content_ko'])
            self.assertEqual(output['contentJa'],fake_translation(output['contentKo']))
            self.assertNotEqual(output['contentJa'],d['translation']['content_ja'])
            self.assertEqual(output['aiModel'],'gpt-6.1-sol')
            self.assertEqual(set(output),{'titleKo','titleJa','summaryKo','summaryJa','contentKo','contentJa','aiModel'})

    def test_bad_translation_no_candidate_and_no_extra_calls(self):
        for change in (lambda d:{**d,'content_ja':d['content_ja'].replace('15名','16名').replace('15人','16人')},
                       lambda d:{**d,'content_ja':d['content_ja'].replace('| 火 | 水 |','| 水 | 火 |')}):
            for result,calls,output,requests,_ in self.replay(change):
                self.assertEqual(result.completed,0);self.assertFalse(output)
                self.assertEqual(len(requests),2);self.assertFalse(any(n.startswith('finish_') for n,_ in calls))

    def test_stale_claim_and_unknown_finish_keep_fences_without_retry(self):
        for result,calls,output,requests,_ in self.replay(claim_change=lambda c:c.update(revision='b'*64)):
            self.assertEqual(len(requests),0);self.assertEqual(result.completed,0)
        for result,calls,output,requests,_ in self.replay(finish_unknown=True):
            self.assertEqual(result.state_unknown,1);self.assertEqual(result.completed,0)
            self.assertEqual(len(requests),2);self.assertEqual(sum(n.startswith('finish_') for n,_ in calls),1)
