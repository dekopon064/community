"""Synthetic detail HTML using the recorded review excerpts; offline only."""
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from ingest.myseoul_ai import myseoul_input
from ingest.myseoul_collect import ListPage
from ingest.myseoul_db import evaluate_myseoul_facts
from ingest.myseoul_scope import KST
from test_myseoul_collect import item, run
from test_myseoul_program import detail


HEADER_TARGET = '성인 외국인주민(체류자격 상관없이 누구나 가능)'
CONDITION = '체류 자격과 무관하게 누구나 신청 가능!'
WINDOW = '2026. 11. 29.(일) 14:00 ~ 16:00'
HEADER_WINDOW = '2026-11-29 14:00 ~ 2026-11-29 16:00'
NOW = datetime(2026, 11, 23, 12, tzinfo=KST)


def collect_facts(*, header_target=HEADER_TARGET, target='성인 외국인주민 20명',
                  condition=CONDITION, window=WINDOW, extra='', header_extra=''):
    html = detail(title='현직 노무사와 함께하는 산업재해 대응 교육', category='인권',
                  target=header_target, venue='양천외국인주민센터 2층 교육실',
                  application='2026-11-18 00:00 ~ 2026-11-25 00:00', operation=HEADER_WINDOW,
                  methods='기타 (https://forms.gle/tj4mwZVLARJGyXK66)', header_extra=header_extra,
                  purpose='산업재해 발생 시 당황하지 않고 대응하는 방법과 노동인권 질의응답 교육',
                  extra=f'<p>대상: {target}</p><p>{condition}</p><p>일시: {window}</p>'
                        '<p>신청방법: 링크 접속 후 신청서 작성</p>'
                        '<p><a href="https://forms.gle/F6T5ZiRLEDYtoyJRA">신청서</a></p>' + extra)
    with patch('test_myseoul_collect.detail', return_value=html):
        _, rpc, _ = run({1: ListPage(1, 1, [item(1)], True)})
    observation, = [args['p_items'][0] for name, args in rpc.calls if name == 'observe_myseoul_program']
    facts = observation['myseoul_facts']
    return facts, set(evaluate_myseoul_facts(facts, now=NOW)['reasons'])


class EligibilityScheduleTests(unittest.TestCase):
    def test_same_conditions_and_window_reach_summary_input(self):
        f, reasons = collect_facts()
        self.assertEqual(reasons, {'activity_region_unknown', 'source_fact_conflict:application_method'})
        prompt = json.loads(myseoul_input({'facts': f, 'observedFacts': f, 'factsVersion': 1}))
        current = prompt['currentFacts']
        self.assertIn(HEADER_TARGET, current['target'])
        self.assertIn('성인 외국인주민 20명', current['target'])
        self.assertIn(CONDITION, current['conditions'])
        self.assertEqual(current['capacity_raw'], ['20명'])
        header, inline = current['periods']['operation']
        self.assertEqual([header['raw'], inline['raw']], [HEADER_WINDOW, WINDOW])
        self.assertEqual(header['endpoints'], inline['endpoints'])
        self.assertEqual([e['value'] for e in inline['endpoints']],
                         ['2026-11-29T14:00:00+09:00', '2026-11-29T16:00:00+09:00'])
        self.assertEqual(current['periods']['application'][0]['endpoints'][-1]['value'],
                         '2026-11-25T00:00:00+09:00')

    def test_age_and_capacity_conflicts_retain_compared_values(self):
        for header, target in [('성인 외국인주민', '청소년 외국인주민 20명'),
                               ('성인 외국인주민 30명', '성인 외국인주민 20명')]:
            with self.subTest(header=header):
                f, reasons = collect_facts(header_target=header, target=target)
                self.assertIn('source_fact_conflict:target', reasons)
                issue = next(i for i in f['issues'] if i['code'] == 'source_fact_conflict:target')
                self.assertIn(header, issue['evidence'])
                self.assertIn(target, issue['evidence'])
        f, reasons = collect_facts(header_extra='<dl><dt>정원</dt><dd>30명</dd></dl>')
        self.assertIn('source_fact_conflict:target', reasons)
        self.assertEqual(set(f['capacity_raw']), {'20명', '30명'})

    def test_restricted_visa_stays_in_review_and_absence_is_not_unrestricted(self):
        for head, cond in [(HEADER_TARGET, '특정 체류자격만 신청 가능'),
                           ('성인 외국인주민', '신청조건: F-2 비자 소지자만 가능'),
                           (HEADER_TARGET, CONDITION + '</p><p>단, F-2 소지자만 신청 가능'),
                           ('성인 외국인주민', '체류 자격과 무관하게 신청할 수 있는 것은 아닙니다.')]:
            with self.subTest(cond=cond):
                f, reasons = collect_facts(header_target=head, condition=cond)
                self.assertIn('nationality_or_visa_unresolved', reasons)
                self.assertTrue(f['conditions'])
        f, reasons = collect_facts(header_target='성인 외국인주민', condition='')
        self.assertNotIn('nationality_or_visa_unresolved', reasons)
        self.assertFalse(any('체류' in line for line in [f['target'], *f['conditions']]))

    def test_different_end_weekday_and_missing_end(self):
        for window, conflict, unknown, endpoints in [
                (WINDOW.replace('16:00', '17:00'), True, False, 2),
                (WINDOW.replace('(일)', '(토)'), True, True, 0),
                (WINDOW.split(' ~ ')[0], False, True, 1),
                (WINDOW.replace('16:00', '13:00'), False, True, 2)]:
            with self.subTest(window=window):
                f, reasons = collect_facts(window=window)
                self.assertEqual('source_fact_conflict:operation' in reasons, conflict)
                self.assertEqual('operation_period_unknown' in reasons, unknown)
                inline = f['periods']['operation'][-1]
                self.assertEqual(inline['raw'], window)
                self.assertEqual(len(inline['endpoints']), endpoints)

    def test_separate_sessions_meeting_and_application_stay_separate(self):
        f, reasons = collect_facts(extra='<p>회차: 2회차 17:00~19:00</p><p>집결시간: 13:30</p>')
        self.assertNotIn('source_fact_conflict:operation', reasons)
        self.assertEqual(f['meeting_evidence'], ['13:30'])
        self.assertTrue(any('17:00~19:00' in line for line in f['session_evidence']))
        self.assertTrue(all('17:00' not in p['raw'] for p in f['periods']['operation']))
        _, reasons = collect_facts(window=WINDOW + ' / 2회차 17:00~19:00')
        self.assertIn('operation_period_unknown', reasons)
        _, reasons = collect_facts(window='오후반 ' + HEADER_WINDOW)
        self.assertIn('operation_period_unknown', reasons)
