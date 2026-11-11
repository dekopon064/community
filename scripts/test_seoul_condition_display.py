"""Preserved Mapo source + synthetic inputs; no live Auth, Pro or RPC."""
import copy
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from ingest.seoul_condition_display import projected_conditions, covered_condition, weekly_covered
from ingest.seoul_content import assemble_seoul_body
from ingest.seoul_fact_roles import public_roles
from test_seoul_content import synthetic_facts

FIXTURE = Path(__file__).parent / 'testdata/seoul_mapo_condition_projection.json'


def case():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    facts = synthetic_facts()
    description = data['source'].split('3. 상세내용\n', 1)[1]
    # Explicit reconstruction, NOT a preserved RPC claim or original AI reply.
    facts.update(description=description, fee_kind='free', fee_amounts=[],
                 activity_evidence=[], target_raw='가족, 성인, 어르신, 청소년(실습 교육 특성상 초등학생의 경우 고학년이상만 접수가능합니다.)',
                 conditions=[line for line in description.splitlines()
                             if re.search(r'대상|동반|거주|연령|학년|만\s*\d+세|국적|증빙|등본|제출|언어|일본어|회차|가구당|신청|불가|제외|전용|조건|기간', line)])
    for name in facts['periods']:
        value = '2025-01-01' if name.endswith('BGNDT') else '2026-12-31'
        facts['periods'][name] = {'value': value, 'precision': 'day', 'status': 'ok', 'raw': value}
    # Test response derived from a stored candidate; not claimed to be raw AI.
    summary = re.sub(r'(?m)^- \*\*[^\n]+\n?', '', data['candidateKo'])
    return data, facts, summary


class ConditionDisplayTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                       'ingest.supabase_store.create_ingest_client', 'ingest.chatgpt_plan_auth.authenticate_worker'):
            guard = patch(target, side_effect=AssertionError('live access forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def test_mapo_continuation_and_roles_preserve_stored_facts(self):
        _, facts, _ = case()
        before = copy.deepcopy(facts)
        roles = public_roles(facts)
        self.assertTrue(any('개별연락 후 다른 교육일정 안내' in v for v in roles['schedule']))
        self.assertTrue(any('가능 시간' in v for v in roles['schedule']))
        self.assertFalse(any('신청' in v for v in roles['eligibility']))
        self.assertNotIn('교육대상', roles['eligibility'])
        self.assertEqual(facts, before)

    def test_mapo_final_body_no_fragment_or_wrong_section(self):
        _, facts, summary = case()
        before = copy.deepcopy(facts)
        body = assemble_seoul_body(summary, facts)
        target = body.split('[대상]')[1].split('[일정 안내]')[0]
        self.assertNotIn('참가 조건', target)
        self.assertNotIn('명단', target)
        self.assertNotRegex(body, r'개별연락 후\s*\n')
        self.assertNotIn('**예약 절차:**', body)
        self.assertNotIn('**진행 일정:** 교육신청', body)
        self.assertEqual(body.count('고학년'), 1)
        for token in ('고학년', '5명 이상', '5명 이하', '16명', '3일 전', '10명 이상',
                      '2일 전', '1주 전', '90%', '당일 변경은 불가'):
            self.assertIn(token, body)
        self.assertEqual(body, assemble_seoul_body(body, facts))
        self.assertEqual(facts, before)

    def test_source_boundary_and_ambiguous_occurrence(self):
        for tail in ('\n- 보호자 동반 필수', '\n\n다른 일정 안내', '\n장소: 서울',
                     '\n| 날짜 | 시간 |', '\nhttps://example.org/info'):
            f = {'conditions': ['전날 연락 후'], 'description': '전날 연락 후' + tail}
            self.assertEqual(projected_conditions(f), ['전날 연락 후'])
        f = {'conditions': ['전날 연락 후'], 'description': '전날 연락 후\n다른 일정 안내\n전날 연락 후\n환불'}
        self.assertEqual(projected_conditions(f), ['전날 연락 후'])

    def test_operator_values_and_unique_restrictions_are_never_replaced(self):
        _, f, _ = case()
        f['conditions'] = ['운영자 확인: 보호자 동반 필수', '서울 거주자만 신청',
                           '일본어 가능자만 신청', '신청자는 18세 이상', '신청: 환불 불가, 증빙 제출 필수']
        before = copy.deepcopy(f)
        roles = public_roles(f)
        for value in f['conditions']:
            self.assertIn(value, roles['eligibility'])
        self.assertEqual(f, before)

    def test_equivalence_requires_entire_rule_not_number_bag(self):
        self.assertTrue(covered_condition('반드시 사전 예약 및 문의 후 교육신청 바랍니다.', '사전 예약·문의 후 신청하세요.'))
        for text in ('사전 예약·문의 후 신청할 필요 없습니다.', '사전 예약·문의 후 신청하세요. 단, 단체만 해당합니다.',
                     '보호자 동반 필수 아님', '단체는 5명, 개인은 10명입니다.'):
            self.assertFalse(covered_condition('보호자 동반 필수', text))
        self.assertFalse(covered_condition('단체 10명 이상 전화 신청 필수', '단체 10명 이상 전화 신청 필수 아님'))
        self.assertFalse(covered_condition('반드시 사전 예약 및 문의 후 교육신청 바랍니다.',
                                          '사전 예약·문의 후 신청하세요. 단, 단체만 해당합니다.'))

    def test_weekday_coverage_binds_each_day_and_time(self):
        _, f, summary = case()
        from ingest.seoul_fact_roles import optional_section
        body = optional_section(summary, '[일정 안내]')
        schedule = public_roles(f)['schedule']
        self.assertTrue(weekly_covered(schedule[0], body))
        self.assertTrue(weekly_covered(schedule[1], body))
        for changed in (body.replace('화·목·금', '화·목·일'),
                        body.replace('10:00~11:30', '14:00~16:00').replace('| 수 | 14:00~16:00', '| 수 | 10:00~11:30'),
                        body.replace('10:00~11:30', '10:00~12:30')):
            self.assertFalse(weekly_covered(schedule[1], changed))
        self.assertFalse(weekly_covered(schedule[0], body.replace('공휴일을 제외한 일정입니다.', '공휴일도 진행합니다.')))
        self.assertFalse(weekly_covered(schedule[1] + ' 보호자 동반 필수', body))

    def test_changed_numbers_contacts_and_qualifiers_are_not_deduplicated(self):
        _, f, summary = case()
        from ingest.seoul_fact_roles import optional_section
        method = optional_section(summary, '[신청 방법]')
        phone = next(v for v in projected_conditions(f) if v.startswith('10명 이상의'))
        roster = next(v for v in projected_conditions(f) if v.startswith('단체신청시'))
        self.assertTrue(covered_condition(phone, method))
        self.assertTrue(covered_condition(roster, method))
        for value in (phone.replace('10명', '11명'), phone.replace('9129', '9128'), phone + ' 보호자 동반 필수',
                      roster.replace('kimgh9216', 'different'), roster + ' 증빙 제출 필수'):
            self.assertFalse(covered_condition(value, method))

    def test_no_model_prose_still_retains_complete_unique_evidence(self):
        _, f, _ = case()
        summary = '[한 줄 요약]\n심폐소생술 교육입니다.\n[주요 내용]\n응급처치를 배웁니다.'
        body = assemble_seoul_body(summary, f)
        self.assertIn('개별연락 후 다른 교육일정 안내', body)
        for value in ('16명', '3일 전', '10명', '9129', '생년월일', '2일전', '금요일'):
            self.assertIn(value, body)
        self.assertEqual(body, assemble_seoul_body(body, f))

    def test_legacy_candidate_reassembly_is_local_and_idempotent(self):
        data, f, _ = case()
        for name in f['periods']:
            value = f['periods'][name]['value'] + 'T00:00:00+09:00'
            f['periods'][name] = {'value': value, 'precision': 'minute', 'status': 'ok', 'raw': value}
        # The production candidate is never fetched or written by this test.
        body = assemble_seoul_body(data['candidateKo'], f)
        self.assertNotIn('**참가 조건:**', body)
        self.assertNotRegex(body, r'개별연락 후\s*\n')
        self.assertEqual(body, assemble_seoul_body(body, f))

    def test_both_workers_fake_pro_and_rpc_preserve_fences_and_calls(self):
        import test_seoul_per_session_replay as replay
        original = replay.recorded_case
        def connected(classified=False):
            data, ctx = original(classified)
            native = ctx['nativeConfirmedFacts']['programFacts'] if classified else ctx['facts']
            native['conditions'].append('교육희망일에 신청인원이 5명 이하의 경우 교육장운영상 교육진행이 어려우며 교육진행불가시 전날 개별연락 후')
            native['description'] += '\n' + native['conditions'][-1] + '\n다른 교육일정 안내'
            data['context']['facts'] = copy.deepcopy(native)
            data['summary']['content_ko'] += '\n'
            return data, ctx
        for classified in (False, True):
            with self.subTest(classified=classified), patch.object(replay, 'recorded_case', side_effect=connected):
                result, calls, output, requests, _ = replay.run_recorded(self, classified=classified)
                self.assertEqual(result.completed, 1)
                self.assertEqual(len(requests), 2)
                self.assertEqual(sum(n.startswith('finish_') for n, _ in calls), 1)
                self.assertIn('개별연락 후 다른 교육일정 안내', output['contentKo'])
                self.assertNotIn('**참가 조건:** 교육희망일', output['contentKo'])
                self.assertIn('publicConditionRoles', requests[0]['input'][0]['content'])
                self.assertIn(output['contentKo'], requests[1]['input'][0]['content'])


if __name__ == '__main__':
    unittest.main()
