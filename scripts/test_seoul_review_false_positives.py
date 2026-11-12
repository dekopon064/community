"""Preserved Seongbuk output + contrary cases. No network, auth or DB."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ingest.ai_errors import ValidationError, AiJobError
from ingest.region_ja_glossary import validate_japanese_output
from ingest.translation_validation import _dates_and_times, _validate_cell
from ingest.seoul_candidate_review import SeoulCandidateReview

FIXTURE = json.loads((Path(__file__).parent / 'testdata/seongbuk_review_context.json').read_text(encoding='utf-8'))


class ReviewFalsePositiveTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo'):
            guard = patch(name, side_effect=AssertionError('network forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def test_preserved_nine_diagnostics_do_not_recur(self):
        before = copy.deepcopy(FIXTURE)
        review = SeoulCandidateReview(None)
        review.check_japanese(FIXTURE['current']['titleKo'], FIXTURE['original']['ko'],
                              FIXTURE['current']['titleJa'], FIXTURE['original']['ja'])
        self.assertEqual(review.issues, [])
        self.assertEqual(len(FIXTURE['review']['issues']), 9)
        self.assertEqual(before, FIXTURE)

    def test_yen_words_and_real_money(self):
        for text in ('円滑な運営', '円満な解決', '円形の広場', '100ウォン'):
            validate_japanese_output('案内', text, '안내')
        for text in ('100円', '１００円', '千円', '￥100', '¥100', '費用：円', '日本円', '円建て'):
            with self.subTest(text=text), self.assertRaises(ValidationError) as caught:
                validate_japanese_output('案内', '一行\n' + text, '안내')
            self.assertEqual(caught.exception.diagnostic['location'], {'field': 'body', 'line': 2})
        with self.assertRaises(ValidationError) as caught:
            validate_japanese_output('100円', '案内', '안내')
        self.assertEqual(caught.exception.diagnostic['location']['field'], 'title')

    def test_clock_equivalence_and_real_mismatch(self):
        for ko, ja in [('수 14~16시, 일 10~12시', '水曜日14時～16時、日曜日10時～12時'),
                       ('오후 2~4시', '14時～16時'), ('10:30~12시', '10時30分～12時')]:
            _validate_cell(ko, ja)
        for ja in ('14時～17時', '16時～14時', '16時'):
            with self.subTest(ja=ja), self.assertRaises(ValidationError):
                _validate_cell('14~16시', ja)
        self.assertEqual(_dates_and_times('1~2시간'), [])
        with self.assertRaises(ValidationError):
            _dates_and_times('25~26시')

    def test_short_dates_keep_year_and_weekday_guards(self):
        _validate_cell('2026. 3. 24.( 화 ) ~ 11. 26.( 목 )', '2026年3月24日（火）～11月26日（木）')
        for ja in ('2026年3月24日～11月27日', '2026年3月24日', '2026年3月24日～11月26日（金）'):
            with self.subTest(ja=ja), self.assertRaises(ValidationError):
                _validate_cell('2026. 3. 24.( 화 ) ~ 11. 26.( 목 )', ja)
        self.assertEqual(_dates_and_times('버전 11.26'), [])
        self.assertEqual(_dates_and_times('11. 26.( 목 )'), [('date', None, 11, 26)])
        with self.assertRaises(ValidationError):
            _dates_and_times('2026. 2. 30.( 월 )')

    def test_exclusive_quantity_does_not_accept_inclusive_or_negated(self):
        for ja in ('3人に満たない', '3名に満たない', '3人未満'):
            _validate_cell('3인 미만', ja)
        for ja in ('3人以下', '3人以上', '4人に満たない', '3人に満たないわけではない'):
            with self.subTest(ja=ja), self.assertRaises(ValidationError):
                _validate_cell('3인 미만', ja)

    def prepare(self, rows):
        review = SeoulCandidateReview(lambda **kwargs: {'findings': rows})
        output = dict(FIXTURE['current'], contentKo='[한 줄 요약]\n탐방 안내\n[일정 안내]\n| 요일 | 시간 |\n|---|---|\n| 수요일 | 14~16시 |',
                      contentJa='[要約]\n探訪案内\n[日程案内]\n| 曜日 | 時間 |\n|---|---|\n| 水曜日 | 14時～17時 |')
        review.stage = 'japanese_validation'
        review.record(ValidationError('cell_date_time', 'mismatch',
                      location={'field': 'body', 'table': 1, 'row': 1, 'column': 2},
                      expected=('time', 16, 0), actual=('time', 17, 0)))
        return review.propose(output, '운영 시간: 14~16시'), output

    def test_context_is_captured_without_expanding_error_logs(self):
        review, _ = self.prepare([])
        issue = review['issues'][0]
        self.assertEqual(issue['context'], {'field': 'contentJa', 'candidate': '14時～17時', 'reference': '14~16시'})
        self.assertEqual(issue['evidence'], '14~16시')
        self.assertEqual(issue['reviewOutcome'], 'no_finding')
        self.assertNotIn('context', ValidationError('clock', 'mismatch').diagnostic)

    def test_ai_outcomes_are_explicit_not_generic_claims(self):
        base = dict(issue=1, decision='change', field='contentJa', before='14時～17時', after='14時～16時', evidence='14~16시')
        cases = [({}, 'change'), ({'decision':'equivalent'}, 'equivalent'),
                 ({'decision':'needs_review','evidence':''}, 'ai_needs_review'),
                 ({'evidence':'없는 인용'}, 'evidence_not_matched'),
                 ({'before':'없는 문장'}, 'unsafe_patch')]
        for patch_data, outcome in cases:
            with self.subTest(outcome=outcome):
                result, original = self.prepare([{**base, **patch_data}])
                self.assertEqual(result['issues'][0]['reviewOutcome'], outcome)
                self.assertIn('17時', original['contentJa'])  # proposal never edits candidate
        result, _ = self.prepare([base, base])
        self.assertEqual(result['issues'][0]['reviewOutcome'], 'duplicate_finding')

    def test_unknown_and_common_failures_still_propagate(self):
        def fail(**kwargs):
            raise AiJobError('ai_http_429')
        review = SeoulCandidateReview(fail)
        review.record(ValidationError('clock','mismatch'))
        with self.assertRaises(AiJobError):
            review.propose(FIXTURE['current'], '원문')

    def test_currency_context_does_not_claim_korean_same_line_as_evidence(self):
        review = SeoulCandidateReview(lambda **kwargs: {'findings': []})
        review.stage = 'japanese_validation'
        review.record(ValidationError('translation_currency','unexpected_yen',location={'field':'body','line':2}))
        result = review.propose(dict(FIXTURE['current'],contentJa='案内\n料金100円',contentKo='일정\n엉뚱한 문장'), '엉뚱한 문장')
        self.assertEqual(result['issues'][0]['context']['candidate'], '料金100円')
        self.assertNotIn('reference', result['issues'][0]['context'])
        self.assertNotIn('evidence', result['issues'][0])


if __name__ == '__main__':
    unittest.main()
