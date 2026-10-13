"""Recorded successful Pro response; local assembly and fake worker replay only."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ingest.ai_errors import AiJobError
from ingest.seoul_content import assemble_seoul_body
from ingest.seoul_fact_roles import clean_role_repetitions, optional_section, validate_weekly_schedule
from ingest.seoul_fact_roles import nationality_rule, recurrence_rule
from ingest.translation_validation import validate_translation_fidelity
from test_seoul_fact_roles import replay_context, fake_translation
import test_seoul_per_session_replay as worker_fixture
import test_seoul_ai_no_retry as no_retry_fixture

FIXTURE = Path(__file__).parent/'testdata/seoul_role_repetitions_recorded.json'


def recorded():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def current_context(classified=False):
    data, c = replay_context(classified)
    d = recorded(); facts = copy.deepcopy(d['facts'])
    if classified:
        c['nativeConfirmedFacts']['programFacts'] = facts
        c['filters'] = copy.deepcopy(d['filters'])
    else:
        c.update(facts=facts, observedFacts=copy.deepcopy(d['observed_facts']), factsVersion=d['facts_version'])
        c['filterContext'].update(data=copy.deepcopy(d['filters']), filterVersion=d['filter_version'])
    data.update(context={'facts':facts}, summary=d['summary'], translation=d['actual_translation'],
                expected_translation_input={'content_ko':d['before_ko']})
    return data, c


class RepetitionTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                     'ingest.supabase_store.create_ingest_client', 'ingest.chatgpt_plan_auth.authenticate_worker'):
            guard = patch(name, side_effect=AssertionError('real connection forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def test_actual_response_reproduces_and_removes_only_redundant_confirmed_rows(self):
        d = recorded(); before = copy.deepcopy(d); raw = FIXTURE.read_bytes()
        old = d['before_ko']
        self.assertIn('- **대상:** 제한없음', old)
        self.assertIn('- **참가 조건:**', old)
        self.assertIn('**진행 일정:**', old)
        self.assertIn('- **신청 방법:** 현장 접수 / 인터넷 예약', old)
        new = assemble_seoul_body(d['summary']['content_ko'], d['facts'])
        for duplicate in ('- **대상:** 제한없음', '- **참가 조건:**', '**진행 일정:**',
                          '- **신청 방법:** 현장 접수 / 인터넷 예약'):
            self.assertNotIn(duplicate, new)
        # Generated prose is not rewritten to manufacture equivalence. Only
        # redundant canonical rows are omitted; additional guidance survives.
        for heading in ('[대상]', '[신청 방법]'):
            self.assertIn(optional_section(d['summary']['content_ko'], heading), optional_section(new, heading))
        self.assertIn('운영 현황에 따라 평일·주말(공휴일 포함) 해설 횟수가 조정될 수 있습니다.', new)
        self.assertIn('모집 인원:** 회차당 15 인 내외', new)
        self.assertIn('예약시간을 엄수', new)
        self.assertIn('잔여 인원에 한해 현장접수', new)
        self.assertIn('02-724-0200, 0232', new)
        self.assertIn('음식물', new); self.assertIn('전자담배', new)
        validate_weekly_schedule(new, d['facts']['description'])
        self.assertNotIn('00:00', new); self.assertNotIn('Asia/Seoul', new)
        self.assertEqual(d, before); self.assertEqual(FIXTURE.read_bytes(), raw)

    def test_both_workers_translate_the_cleaned_body_then_complete_fake_candidate(self):
        with patch.object(worker_fixture, 'recorded_case', side_effect=current_context), patch.object(
                worker_fixture, 'fake_translation', side_effect=fake_translation):
            for classified in (False, True):
                result, calls, output, requests, _ = worker_fixture.run_recorded(self, classified=classified)
                self.assertEqual(result.completed, 1); self.assertEqual(len(requests), 2)
                self.assertNotIn('**참가 조건:**', output['contentKo'])
                self.assertNotIn('**진행 일정:**', output['contentKo'])
                self.assertNotIn('- **신청 방법:**', output['contentKo'])
                self.assertEqual(requests[1]['input'][0]['content'],
                                 'title_ko: '+output['titleKo']+'\ncontent_ko:\n'+output['contentKo'])
                self.assertEqual(sum(n.startswith('finish_') for n, _ in calls), 1)
                validate_translation_fidelity(output['titleKo'], output['contentKo'], output['titleJa'], output['contentJa'])

    def test_no_retry_fake_pro_and_fenced_completion_use_current_inputs(self):
        def current_case():
            d=recorded();d['summary']=copy.deepcopy(d['summary']);return d
        with patch.object(no_retry_fixture, 'replay_context', side_effect=current_context), patch.object(
                no_retry_fixture, 'confirmed_case', side_effect=current_case):
            for classified in (False, True):
                result, calls, stages, count=no_retry_fixture.NoRetryTests.replay(self, classified)
                self.assertEqual((result.completed,result.failed,result.retried),(1,0,0))
                self.assertEqual(stages,['summary','translation']);self.assertEqual(count,2)
                self.assertTrue(calls[0][0].endswith('no_retry'))
                self.assertTrue(calls[-1][0].startswith('finish_'))

    def test_cleaning_is_idempotent_and_only_canonical_duplicates_disappear(self):
        d=recorded();new=assemble_seoul_body(d['summary']['content_ko'],d['facts'])
        self.assertEqual(assemble_seoul_body(new,d['facts']),new)
        # The already-generated candidate text is local evidence only, never a
        # write to the operational candidate. It too must clean consistently.
        self.assertEqual(assemble_seoul_body(d['before_ko'],d['facts']),new)

    def test_normal_sentence_variants_and_scope_locality(self):
        foreign='해설은 외국인 관람객 대상으로 운영하므로 내국인 참여가 불가합니다.'
        self.assertEqual(nationality_rule(foreign),('foreign','korean_denied'))
        self.assertEqual(nationality_rule('외국인 관람객 대상 해설로 내국인은 참가할 수 없습니다.'),nationality_rule(foreign))
        for preface in ('일반 대상은 “누구나”로 안내되어 있으나, ', '원문 안내는 "제한없음"이나, '):
            self.assertEqual(nationality_rule(preface+foreign),nationality_rule(foreign))
        self.assertEqual(recurrence_rule('해설시간: 수~토요일 (일요일, 공휴일 제외)'),
                         recurrence_rule('수~토요일 진행하며 일요일·공휴일은 제외합니다.'))
        for qualified in (foreign+' D-2 비자 소지자만 신청합니다.',
                          '외국인 20세 이상 대상 해설로 내국인은 참가할 수 없습니다.',
                          '내국인도 참가할 수 있습니다.'):
            self.assertIsNone(nationality_rule(qualified))
        # Summary and main-content mentions are not same-role coverage.
        d=recorded();source=d['summary']['content_ko']
        changed=source.replace(optional_section(source,'[대상]'),'공식 안내를 확인하세요.')
        changed=changed.replace('[주요 내용]','[주요 내용]\n'+foreign)
        self.assertIn('**참가 조건:**',assemble_seoul_body(changed,d['facts']))

    def test_unmatched_or_qualified_source_rows_and_continuations_are_preserved(self):
        d=recorded();facts=d['facts'];source=d['summary']['content_ko']
        from ingest.seoul_content import reviewed_sections
        sections=reviewed_sections(facts)
        qualified=['참가 조건: D-2 비자 소지자만 참여 필수',
                   '참가 조건: 외국인 20세 이상이며 보호자 동반 필수',
                   '참가 조건: 거주자만 가능 · 증빙 제출 필수']
        sections['[대상]']+='\n'+'\n'.join(qualified)
        sections['[일정 안내]']+='\n해설은 약 40분이며화~일요일에운영합니다(월요일,공휴일제외).'
        sections['[신청 방법]']+='\n  접수 후 신원증빙을 제출하세요.\n문의: 02-1234-5678\nhttps://synthetic.invalid/reserve?id=8'
        before=copy.deepcopy(sections)
        _,cleaned=clean_role_repetitions(source,sections,facts)
        for line in qualified:self.assertIn(line,cleaned['[대상]'])
        self.assertIn('약 40분',cleaned['[일정 안내]'])
        self.assertIn('**신청 방법:**',cleaned['[신청 방법]'])
        self.assertIn('신원증빙',cleaned['[신청 방법]'])
        self.assertIn('02-1234-5678',cleaned['[신청 방법]'])
        self.assertIn('https://synthetic.invalid/reserve?id=8',cleaned['[신청 방법]'])
        self.assertEqual(sections,before)
        # An attached qualifier prevents removal of its parent fact row.
        attached=reviewed_sections(facts)
        attached['[대상]']=attached['[대상]'].replace('불가합니다 .','불가합니다 .\n  보호자 동반 필수')
        _,cleaned=clean_role_repetitions(source,attached,facts)
        self.assertIn('**참가 조건:**',cleaned['[대상]'])
        self.assertIn('보호자 동반 필수',cleaned['[대상]'])

    def test_method_kinds_require_all_proofs_and_contacts_never_prove_phone_application(self):
        from ingest.seoul_fact_roles import _application_methods_covered
        source=optional_section(recorded()['summary']['content_ko'],'[신청 방법]')
        self.assertTrue(_application_methods_covered(['internet','onsite'],source))
        self.assertFalse(_application_methods_covered(['internet','onsite','phone'],source))
        self.assertTrue(_application_methods_covered(['internet','onsite','phone'],source+'\n전화 신청 가능합니다.'))
        for negated in ('현장접수는 불가합니다.', '현장접수할 수 없습니다.', '현장접수하지 마세요.',
                        '현장접수는 현재 불가합니다.'):
            self.assertFalse(_application_methods_covered(['internet','onsite'],source+'\n'+negated))
        self.assertFalse(_application_methods_covered(['internet'],'신청 링크: https://synthetic.invalid/'))
        self.assertFalse(_application_methods_covered(['onsite'],'문의: 방문 상담 가능합니다.'))
        self.assertFalse(_application_methods_covered(['onsite'],'현장접수 관련 소식입니다.'))
        # Missing one method must retain the complete authoritative list.
        d=recorded();facts=copy.deepcopy(d['facts']);facts['application_methods'].append('phone')
        from ingest.seoul_content import reviewed_sections
        _,cleaned=clean_role_repetitions(d['summary']['content_ko'],reviewed_sections(facts),facts)
        self.assertIn('전화 신청',cleaned['[신청 방법]'])

    def test_weekday_mismatch_missing_exceptions_and_unique_schedule_keep_source(self):
        d=recorded();source=d['summary']['content_ko']
        old='화~일요일 운영하며 월요일·공휴일은 제외합니다.'
        for changed in ('수~토요일 운영하며 일요일·공휴일은 제외합니다.',
                        '화~일요일 운영합니다.', '공휴일을 포함해 화~일요일 운영합니다.'):
            from ingest.seoul_content import reviewed_sections
            _,sections=clean_role_repetitions(source.replace(old,changed),reviewed_sections(d['facts']),d['facts'])
            self.assertIn('해설시간 : 화 ~ 일요일',sections['[일정 안내]'])

    def test_a_canonical_row_cannot_be_its_own_coverage_proof(self):
        from ingest.seoul_content import reviewed_sections
        d=recorded();sections=reviewed_sections(d['facts']);before=copy.deepcopy(sections)
        body='\n\n'.join(header+'\n'+value for header,value in sections.items())
        cleaned_content,cleaned=clean_role_repetitions(body,sections,d['facts'])
        self.assertEqual(cleaned,sections);self.assertEqual(sections,before)
        self.assertEqual(cleaned_content,body)

    def test_conflicting_table_period_or_capacity_stops_before_translation_both_workers(self):
        changes=[lambda s:s.replace('5회차(일본어)','5회차(영어)'),
                 lambda s:s.replace('| 10:00 |','| 09:00 |'),
                 lambda s:s.replace('[일정 안내]','[일정 안내]\n진행기간: 2027-10-01 ~ 2027-10-31'),
                 lambda s:s.replace('[대상]','[대상]\n모집 인원: 회차당 16 인 내외')]
        for classified in (False,True):
            for index,change in enumerate(changes):
                def bad(c=False):
                    data,context=current_context(c);data['summary']['content_ko']=change(data['summary']['content_ko']);return data,context
                with self.subTest(classified=classified,index=index),patch.object(worker_fixture,'recorded_case',side_effect=bad),patch.object(
                        worker_fixture,'fake_translation',side_effect=fake_translation):
                    result,calls,output,requests,_=worker_fixture.run_recorded(self,classified=classified)
                    self.assertEqual(len(requests),1);self.assertEqual(result.completed,0)
                    self.assertFalse(output);self.assertFalse(any(n.startswith('finish_') for n,_ in calls))


if __name__ == '__main__': unittest.main()
