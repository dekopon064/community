"""Preserved public excerpts + synthetic contexts/responses; all external IO blocked."""
import copy
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from ingest.seoul_candidate_review import SeoulCandidateReview
from ingest.seoul_condition_display import covered_condition, projected_conditions
from ingest.seoul_condition_layout import project_layout
from ingest.seoul_content import assemble_seoul_body
from ingest.seoul_fact_roles import optional_section, public_roles
from test_seoul_content import synthetic_facts


DATA = json.loads((Path(__file__).parent / 'testdata/seoul_condition_layout.json').read_text(encoding='utf-8'))
CASES = {row['case']: row for row in DATA['cases']}


def fixture(name):
    row = CASES[name]
    facts = synthetic_facts()
    facts.update(description=row['source'], conditions=copy.deepcopy(row['conditions']),
                 target_raw='성인' if name in ('hong', 'seonyudo') else '제한없음',
                 activity_evidence=[], residence_evidence=[],
                 fee_kind='paid' if name == 'hong' else 'free',
                 fee_amounts=['1만 원'] if name == 'hong' else [])
    if name == 'hanok':
        # Explicit synthetic confirmed input matching the preserved operator
        # condition. Keep the original contradictory source in the fixture.
        facts['description'] = facts['description'].replace('2026. 9. 12.(토) - 12. 31.(토)',
                                                           '2026. 9. 12.(토) - 12. 31.')
    # Reconstructed from saved candidate labels, NOT an operational RPC claim.
    for label, pair in (('신청기간', ('RCPTBGNDT', 'RCPTENDDT')), ('진행기간', ('SVCOPNBGNDT', 'SVCOPNENDDT'))):
        match = re.search(r'\*\*' + label + r':\*\* ([^\n]+)', row['candidateKo'])
        for field, value in zip(pair, match[1].split(' ~ ')):
            value = value.replace(' ', 'T') + ':00+09:00'
            facts['periods'][field] = dict(value=value, precision='minute', status='ok', raw=value)
    return facts, row['candidateKo']


class ConditionLayoutTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                     'ingest.supabase_store.create_ingest_client', 'ingest.chatgpt_plan_auth.authenticate_worker'):
            guard = patch(name, side_effect=AssertionError('live IO forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def render(self, name):
        facts, before = fixture(name)
        saved = copy.deepcopy(facts)
        review = SeoulCandidateReview(None)
        body = assemble_seoul_body(before, facts, review=review)
        self.assertEqual(facts, saved)
        self.assertEqual(body, assemble_seoul_body(body, facts, review=SeoulCandidateReview(None)))
        return body, public_roles(facts), review

    def test_hong_source_number_removed_booking_not_eligibility(self):
        body, roles, _ = self.render('hong')
        self.assertEqual(len(roles['booking']), 2)
        self.assertEqual(roles['eligibility'], [])
        self.assertNotIn('참가 조건', optional_section(body, '[대상]'))
        for text in ('24시간', '48시간', '1만원', '자동 취소', '다음 대기자', '전액 환불', '이후에는 환불되지', '별도 문의'):
            self.assertEqual(body.count(text), 1, text)
        self.assertNotRegex(body, r'(?:참가 조건|예약 절차):\*\* [45]\. ')

    def test_seonyudo_parking_is_not_participant_eligibility(self):
        body, roles, _ = self.render('seonyudo')
        audience = optional_section(body, '[대상]')
        self.assertNotIn('주차', audience)
        self.assertNotIn('신청기간', audience)
        self.assertIn('15명', audience)
        self.assertEqual(body.count('보행상 장애'), 1)
        self.assertNotIn('보행 상 장애', body)
        self.assertIn('참여 전일 13시 전까지', body)
        self.assertIn('-12도 미만', body)
        self.assertEqual(len(roles['activity']), 1)

    def test_gwanghwamun_roles_keep_limits_exceptions_and_table(self):
        body, roles, review = self.render('gwanghwamun')
        audience = optional_section(body, '[대상]')
        for token in ('19:00', '회차별 운영시간', '신청 및 참여 안내', '사진 촬영', '현장 접수'):
            self.assertNotIn(token, audience)
        for token in ('14세', '19세', '30명'):
            self.assertIn(token, audience)
        self.assertEqual(audience.count('14세'), 1)
        self.assertEqual(body.count('사진 촬영'), 1)
        for token in ('최대 1개 회차', '2명까지', '19:30~19:50', '영어', '12월 4일(금) : 19시, 20일',
                      '시간당 10mm 이상', '오전 11시 이전'):
            self.assertIn(token, body)
        # Do not "repair" the contradictory source 20일 or onsite-method fact.
        self.assertIn('현장 접수는 없습니다', body)
        self.assertIn('신청 방법:** 현장 접수', body)
        self.assertEqual(len([v for v in roles['eligibility'] if '동반' in v]), 1)
        self.assertNotIn('⏰ 회차별 운영시간', projected_conditions(fixture('gwanghwamun')[0]))

    def test_hanok_routes_keep_course_context_and_unique_conditions(self):
        body, roles, _ = self.render('hanok')
        target = optional_section(body, '[대상]')
        self.assertNotIn('이상범가옥', target)
        self.assertNotIn('참가신청', target)
        self.assertNotIn('개인정보', target)
        self.assertIn('초등학교 3학년 이상', target)
        main = optional_section(body, '[주요 내용]')
        for token in ('웃대 남서부', '웃대 남동부', '12.12(토)', '출입불가'):
            self.assertIn(token, main)
        for token in ('12회차', '12명', '4명', '15명', '전화통화는 불가', '사업 종료 시 폐기', '추후 신청이 제한'):
            self.assertIn(token, body)
        self.assertEqual(len([v for v in roles['activity'] if v.startswith('답사 코스')]), 2)
        self.assertEqual(body.count('추후 신청이 제한'), 1)
        self.assertEqual(body.count('사업 종료 시 폐기'), 1)

    def test_source_number_scope_and_non_source_operator_values(self):
        values = ['1. 신청 후 먼저 결제하세요.', '2. 다음 단계에서 증빙 제출',
                  '12회차 답사는 남서부 지역입니다.', '4.5km 도보', '11.28(토) 11~13시',
                  '4. 프로그램 참여가 어려울 시, 위 3번 항을 확인하세요.']
        for value in values:
            self.assertEqual(project_layout(value, [value]), [value])
        value = CASES['hong']['conditions'][0]
        self.assertEqual(project_layout(value, []), [value])
        self.assertEqual(project_layout(value, [value, value]), [value])
        self.assertEqual(project_layout(value, [value, '취소는 4번 항을 참고하세요.']), [value])
        self.assertFalse(project_layout(value, [value])[0].startswith('4.'))

    def test_attached_unique_qualifier_keeps_parent_line(self):
        from ingest.seoul_condition_display import clean_projected_duplicates
        from ingest.seoul_content import reviewed_sections
        facts, body = fixture('hong')
        source = CASES['hong']['conditions'][0]
        parent = '- **참가 조건:** ' + source
        body = body.replace(parent, parent + '\n  단, 단체는 증빙 제출 필수')
        content, _ = clean_projected_duplicates(body, reviewed_sections(facts), facts)
        self.assertIn(parent + '\n  단, 단체는 증빙 제출 필수', content)

    def test_booking_equivalence_requires_every_qualifier_and_value(self):
        f, body = fixture('hong')
        method = optional_section(body, '[신청 방법]')
        payment, refund = projected_conditions(f)
        self.assertTrue(covered_condition(payment, method))
        self.assertTrue(covered_condition(refund, method))
        for value in (payment.replace('24시간', '48시간'), payment.replace('1만원', '2만원'),
                      payment.replace('자동 취소', '취소하지 않음'), payment + ' 단, 단체는 제외.',
                      refund.replace('48시간', '24시간'), refund.replace('홍건익가옥', '다른 시설'),
                      refund + ' 증빙 제출 필수'):
            self.assertFalse(covered_condition(value, method), value)
        self.assertFalse(covered_condition(refund, method.replace('반드시 별도 문의', '문의하지 않아도 됩니다')))

    def test_parking_requires_source_context_and_all_restrictions(self):
        value = CASES['seonyudo']['conditions'][-1]
        self.assertEqual(project_layout(value, [value]), [value])
        projected = project_layout(value, ['- 주차 : 장애인주차만 가능', value])[0]
        proof = '공원 내 주차는 장애인 전용 주차구역 주차(가능) 표지 부착 차량에 보행상 장애가 있는 사람이 탑승한 경우에만 가능합니다.'
        self.assertTrue(covered_condition(projected, proof))
        for changed in (proof.replace('경우에만', '경우에도'), proof.replace('사람이 탑승한', '사람이 탑승하지 않은'),
                        proof.replace('표지 부착 ', '')):
            self.assertFalse(covered_condition(projected, changed))

    def test_absent_summary_preserves_booking_and_activity_evidence(self):
        for name in CASES:
            with self.subTest(name=name):
                facts, _ = fixture(name)
                body = assemble_seoul_body('[한 줄 요약]\n합성 요약입니다.\n[주요 내용]\n공식 프로그램입니다.',
                                           facts, review=SeoulCandidateReview(None))
                roles = public_roles(facts)
                for value in roles['booking']:
                    self.assertIn(value, optional_section(body, '[신청 방법]'))
                for value in roles['activity']:
                    self.assertIn(value, optional_section(body, '[주요 내용]'))

    def test_wrong_values_negation_and_unique_qualifiers_are_not_coverage(self):
        source = CASES['gwanghwamun']['conditions'][12]
        proof = '만 14세 이하는 만 19세 이상 성인이 예약하고 동반해야 참여할 수 있습니다.'
        self.assertTrue(covered_condition(source, proof))
        for changed in (proof.replace('19세', '18세'), proof.replace('동반해야', '동반하지 않아도'),
                        proof.replace('예약하고 ', ''), proof + ' 단, 단체는 제외합니다.'):
            self.assertFalse(covered_condition(source, changed))
        f, _ = fixture('hanok')
        original = copy.deepcopy(f)
        f['conditions'] += ['운영자 확인: 보호자 동반 필수', '서울 거주자만 신청', '신청: 환불 불가, 증빙 제출 필수']
        for text in f['conditions'][-3:]:
            self.assertIn(text, public_roles(f)['eligibility'])
        self.assertEqual(original['description'], f['description'])

    def test_original_calendar_conflict_is_not_silently_fixed(self):
        from ingest.ai_errors import ValidationError
        facts, body = fixture('hanok')
        facts['description'] = CASES['hanok']['source']
        with self.assertRaises(ValidationError) as caught:
            assemble_seoul_body(body, facts)
        self.assertEqual(caught.exception.diagnostic['rule'], 'calendar_weekday')

    def test_fake_workers_both_routes_receive_projection_and_translate_once(self):
        import test_seoul_per_session_replay as replay
        original = replay.recorded_case
        translate = replay.fake_translation
        snippets = {
            'hong': CASES['hong']['conditions'][1],
            'seonyudo': '- 주차 : 장애인주차만 가능\n' + CASES['seonyudo']['conditions'][-1],
            'gwanghwamun': CASES['gwanghwamun']['conditions'][-1],
            'hanok': CASES['hanok']['conditions'][-2],
        }
        for name, source in snippets.items():
            for classified in (False, True):
                def connected(is_classified=False):
                    data, ctx = original(is_classified)
                    f = ctx['nativeConfirmedFacts']['programFacts'] if is_classified else ctx['facts']
                    f['description'] += '\n' + source
                    f['conditions'].append(source.splitlines()[-1])
                    data['context']['facts'] = copy.deepcopy(f)
                    return data, ctx
                # The old fake replaces 시 before 시간, losing duration units.
                # Preserve the unit in the synthetic reply; production parsing
                # must continue to reject an actually missing 48-hour deadline.
                with self.subTest(name=name, classified=classified), patch.object(replay, 'recorded_case', side_effect=connected), patch.object(
                        replay, 'fake_translation', side_effect=lambda body: translate(body.replace('시간', '時間'))):
                    result, calls, output, requests, _ = replay.run_recorded(self, classified=classified)
                    self.assertEqual(result.completed, 1)
                    self.assertEqual(len(requests), 2)
                    self.assertEqual(sum(n.startswith('finish_') for n, _ in calls), 1)
                    self.assertIn('publicConditionRoles', requests[0]['input'][0]['content'])
                    self.assertIn(output['contentKo'], requests[1]['input'][0]['content'])
                    self.assertNotIn('참가 조건:** ' + source.splitlines()[-1], output['contentKo'])
                    self.assertNotRegex(output['contentKo'], r'예약 절차:\*\* 5\. ')
                    self.assertTrue(output['contentJa'])


if __name__ == '__main__':
    unittest.main()
