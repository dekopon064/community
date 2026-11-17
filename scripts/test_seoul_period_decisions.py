"""Source-shaped examples through the normal Seoul collector, with no network."""
import unittest
from test_seoul_evidence_connections import normalize_seoul_item, program_rpc_item, row

ANNUAL = '1. 운영 기간 및 요일\n운영 기간: 연중(1월~12월)\n운영 요일: 화요일~금요일\n휴관일: 매주 월요일, 법정 공휴일'
TOUR = '운영기간: 2026년 11월 16일 14:00-16:00 / 2026년 11월 23일 14:00-16:00 (해당 일자 중 택 1)'
DANCE = '운영기간: 2026년 11월 7일(토) ~ 11월 28일(토), 매주 토요일 클래스당 총 4회'


def facts(body, **changes):
    dates = dict(RCPTBGNDT='2026-11-09', RCPTENDDT='2026-12-30', SVCOPNBGNDT='2026-11-10', SVCOPNENDDT='2026-12-31')
    return program_rpc_item(normalize_seoul_item(row(DTLCONT=body, **(dates | changes))))['program_facts']


class PeriodDecisions(unittest.TestCase):
    def test_annual_operations_and_booking_window_coexist(self):
        f = facts(ANNUAL)
        self.assertNotIn('body_period_needs_confirmation', f['missing'])
        self.assertIn('연중(1월~12월)', f['period_evidence'])
        self.assertIn('화요일~금요일', f['description'])
        self.assertEqual(f['periods']['SVCOPNBGNDT']['value'][:10], '2026-11-10')

    def test_actual_session_schedules_remain_actionable(self):
        for body in (TOUR, DANCE):
            with self.subTest(body=body):
                f = facts(body)
                self.assertIn('body_period_needs_confirmation', f['missing'])
                self.assertIn(body.split(': ', 1)[1], f['period_evidence'])

    def test_annual_does_not_hide_missing_reversed_or_conflicting_facts(self):
        self.assertIn('period_missing_or_unparsed', facts(ANNUAL, RCPTENDDT='')['missing'])
        self.assertIn('period_order_conflict', facts(ANNUAL, SVCOPNENDDT='2026-11-01')['conflicts'])
        self.assertIn('date_weekday_conflict', facts(ANNUAL+'\n2026년 11월 16일(금)')['conflicts'])
        self.assertIn('body_period_needs_confirmation', facts(ANNUAL+'\n신청기간: 연중')['missing'])
        self.assertIn('body_period_needs_confirmation', facts('운영기간: 연중 일부 회차 제외')['missing'])
        self.assertIn('body_api_period_conflict', facts(ANNUAL+'\n운영기간: 2026년 11월 1일 ~ 12월 31일')['conflicts'])


if __name__ == '__main__':
    unittest.main()
