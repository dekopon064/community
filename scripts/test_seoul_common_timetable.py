"""Reconstructed daytime tour and retained, differing nighttime tour. Offline only."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ingest.body_markdown import read_body
from ingest.ai_errors import ValidationError
from ingest.seoul_common_timetable import common_timetable, source_schedule
from ingest.seoul_content import assemble_seoul_body, validation_view
from ingest.seoul_candidate_review import SeoulCandidateReview
from test_seoul_per_session_replay import recorded_case
import test_seoul_date_hours_replay as worker


DAYS = ('11월 21일(토)', '11월 28일(토)', '12월 05일(토)')
SLOTS = ('1회차 - 11:00 ~ 11:50 (접수시간: 10:30 ~ 10:50)',
         '2회차 - 12:00 ~ 12:50 (접수시간: 11:30 ~ 11:50)',
         '3회차 - 14:00 ~ 14:50 (접수시간: 13:30 ~ 13:50)',
         '5회차 - 15:00 ~ 15:50 (접수시간: 14:30 ~ 14:50)')
NOTE = '해당 회차 시작(출발)후에는 참여가 불가능합니다.'
OVERVIEW = '\n'.join('- ' + day + ' : 11시 / 12시 / 14시 / 15시' for day in DAYS)
DETAILS = ['📅 ' + day + '\n' + '\n'.join(SLOTS) for day in DAYS]
HEAD = '📅 운영일시 : 2026년 ' + ', '.join(DAYS) + '\n' + OVERVIEW + '\n※ ' + NOTE
SOURCE = HEAD + '\n⏰ 회차별 운영시간\n' + '\n'.join(DETAILS)
SUMMARY = '[한 줄 요약]\n역사 해설 프로그램입니다.\n[대상]\n성인\n[일정 안내]\n[주요 내용]\n해설을 듣습니다.\n[신청 방법]\n예약 후 참여합니다.'
TABLE = '| 회차 | 당일 접수 시간 | 진행 시간 |\n| --- | --- | --- |\n' + '\n'.join(
    f'| {n}회차 | {a}~{b} | {c}~{d} |' for n,a,b,c,d in
    [(1,'10:30','10:50','11:00','11:50'),(2,'11:30','11:50','12:00','12:50'),
     (3,'13:30','13:50','14:00','14:50'),(5,'14:30','14:50','15:00','15:50')])


def fixture():
    _, ctx = recorded_case()
    f = ctx['facts']
    f.update(description=SOURCE, target_raw='성인', conditions=[NOTE,*SLOTS],
             activity_evidence=[], residence_evidence=[])
    for key, day in [('SVCOPNBGNDT', '11-21'), ('SVCOPNENDDT', '12-05')]:
        value = '2026-' + day + 'T00:00:00+09:00'
        f['periods'][key].update(value=value, raw=value)
    return ctx


def japanese(body):
    for ko, ja in [('운영일', '開催日'), ('진행 시간', '実施時間'), ('당일 접수 시간', '当日の受付時間'),
                   (NOTE, '該当回の出発後は参加できません。'), ('회차', '回'), ('(토)', '（土）')]:
        body = body.replace(ko, ja)
    return worker.fake_translation(body)


class CommonTimetableTests(unittest.TestCase):
    def test_worker_routes(self):
        ctx = fixture()
        facts = ctx['facts']
        pristine = copy.deepcopy(facts)
        body = assemble_seoul_body(SUMMARY, facts)
        self.assertEqual(body.count(TABLE), 1, body)
        self.assertEqual(body.count(NOTE), 1)
        self.assertEqual(assemble_seoul_body(body, facts), body)
        summary = dict(content_ko=SUMMARY, facts=dict(audience='성인',geo_age_income='성인',
                       amount_period_deadline='무료', how_to_apply='예약 후 참여합니다.'))
        entry = dict(title='광화문 빛모락 투어', facts=facts, filters=ctx['filterContext']['data'],
                     summary=summary, translation_input_ko=body,
                     translation=dict(title_ja='歴史ツアー',content_ja=japanese(body)))
        for classified in (False, True):
            with (self.subTest(classified=classified), patch.object(worker,'recorded',return_value=[entry]),
                  patch.object(worker,'synthetic_translation',japanese),
                  patch('socket.socket.connect',side_effect=AssertionError('offline only'))):
                result, calls, saved, requests = worker.DateHoursReplayTests.replay(self,0,classified)
                self.assertEqual(result.completed, 1, calls[-1][0])
                candidate, = saved
                self.assertEqual(requests[1]['input'][0]['content'].split('content_ko:\n',1)[1], candidate['contentKo'])
                for key, expected, note, days in [
                    ('contentKo', TABLE, NOTE, '11월 21일(토), 11월 28일(토), 12월 5일(토)'),
                    ('contentJa', japanese(TABLE), japanese(NOTE), japanese('11월 21일(토), 11월 28일(토), 12월 5일(토)'))]:
                    text = candidate[key]
                    self.assertEqual(len(read_body(text).tables), 1)
                    for token in (expected, note, days, '14:30', '15:50'):
                        self.assertEqual(text.count(token), 1, text)
        self.assertEqual(facts, pristine)

    def test_unproven_or_different_days_stay_separate(self):
        f = fixture()['facts']
        cases = [
            SOURCE.replace(DETAILS[1], DETAILS[1].replace(SLOTS[0], '')),
            SOURCE.replace(DETAILS[1], DETAILS[1].replace('10:30', '10:35')),
            SOURCE.replace(DETAILS[1], DETAILS[1].replace('15:50','15:45')),
            SOURCE.replace(DETAILS[1], DETAILS[1].replace('5회차','4회차')),
            SOURCE.replace(DETAILS[1], DETAILS[1] + '\n영어 투어로 진행'),
            SOURCE.replace(DETAILS[1], DETAILS[1] + '\n' + NOTE),
            SOURCE + '\n⏰ 장소 및 운영코스\n※ 11월 28일은 별도 코스로 운영',
            SOURCE + '\n⏰ 장소 및 운영코스\n※ 11/28만 집결지 변경',
            SOURCE.replace(DETAILS[1], ''),
            SOURCE.replace('14시 / 15시', '14시 / 15시 (총 5회차)', 1),
            HEAD + '\n⏰ 회차별 운영시간\n' + '\n'.join(SLOTS),
        ]
        retained = json.loads((Path(__file__).parent/'testdata/seoul_condition_layout.json').read_text(encoding='utf8'))
        night = next(item['source'] for item in retained['cases'] if '야간 문화투어' in item['title'])
        f['periods']['SVCOPNBGNDT']['value'] = '2026-11-20T00:00:00+09:00'
        cases.append(night)
        for source in cases:
            changed = {**f,'description':source}
            view = validation_view(changed)
            with self.subTest(source=source[-110:]):
                self.assertIsNone(source_schedule(view))
                old_review, review = SeoulCandidateReview(None), SeoulCandidateReview(None)
                with patch('ingest.seoul_content.source_schedule', return_value=None):
                    baseline = assemble_seoul_body(SUMMARY, changed, review=old_review)
                self.assertEqual(assemble_seoul_body(SUMMARY, changed, review=review), baseline)
                self.assertEqual(review.issues, old_review.issues)

    def test_calendar_weekday_conflict_still_reported(self):
        facts = fixture()['facts']
        facts['description'] = SOURCE.replace(DAYS[2], '12월 05일(일)')
        self.assertIsNone(source_schedule(validation_view(facts)))
        with self.assertRaises(ValidationError) as error:
            assemble_seoul_body(SUMMARY, facts)
        self.assertEqual(error.exception.diagnostic['rule'], 'calendar_weekday')

    def test_separately_confirmed_exception_blocks_grouping(self):
        facts = fixture()['facts']
        facts['conditions'].append('11월 28일에는 영어 해설로 진행합니다.')
        self.assertNotIn(TABLE, assemble_seoul_body(SUMMARY, facts))

    def test_different_day_exception_reaches_japanese_with_its_date(self):
        ctx = fixture()
        f = ctx['facts']
        exception = '11월 28일(토)은 영어 해설입니다.'
        f['description'] += '\n⏰ 장소 및 운영코스\n' + exception
        summary = dict(content_ko=SUMMARY.replace('[일정 안내]', '[일정 안내]\n' + exception),
                       facts=dict(audience='성인', geo_age_income='성인', amount_period_deadline='무료',
                                  how_to_apply='예약 후 참여합니다.'))
        ko = assemble_seoul_body(summary['content_ko'], f)
        ja_note = '11月28日（土）は英語での解説です。'
        def translate(body):
            return japanese(body.replace(exception, ja_note))
        entry = dict(title='광화문 투어', facts=f, filters=ctx['filterContext']['data'], summary=summary,
                     translation_input_ko=ko, translation=dict(title_ja='歴史ツアー', content_ja=translate(ko)))
        with (patch.object(worker, 'recorded', return_value=[entry]),
              patch.object(worker, 'synthetic_translation', translate),
              patch('socket.socket.connect', side_effect=AssertionError('offline only'))):
            for classified in (False, True):
                result, _, outputs, _ = worker.DateHoursReplayTests.replay(self, 0, classified)
                self.assertEqual(result.completed, 1)
                candidate, = outputs
                for key, phrase in [('contentKo', exception), ('contentJa', ja_note)]:
                    self.assertIn(phrase, candidate[key])
                    self.assertFalse(read_body(candidate[key]).tables)

    def test_identical_dated_table_compacted_after_cell_comparison(self):
        f = fixture()['facts']
        expanded = '| 날짜 | 회차 | 당일 접수 시간 | 투어 진행 시간 |\n| --- | --- | --- | --- |\n' + '\n'.join(
            '| ' + day + ' ' + row for day in DAYS for row in TABLE.splitlines()[2:])
        summary = SUMMARY.replace('[일정 안내]', '[일정 안내]\n' + expanded)
        body = assemble_seoul_body(summary, f)
        self.assertEqual(len(read_body(body).tables), 1)
        self.assertEqual(body.count(TABLE), 1)
        source = source_schedule(validation_view(f))
        for changed in (expanded.replace('10:30','10:35',1), expanded.replace(DAYS[1],DAYS[0],1)):
            before = summary.replace(expanded, changed)
            self.assertEqual(common_timetable(before, source), before)

    def test_explicit_common_scope_and_identical_scoped_notes(self):
        f = fixture()['facts']
        for details in ('⏰ 회차별 운영시간 (전체 운영일 공통)\n' + '\n'.join(SLOTS),
                        '⏰ 회차별 운영시간\n' + '\n'.join(day + '\n' + NOTE for day in DETAILS)):
            f['description'] = HEAD.replace('14시 / 15시', '14시 / 15시 (총 4회차)') + '\n' + details + '\n⏰ 장소 및 운영코스\n문의 02-1234-5678'
            body = assemble_seoul_body(SUMMARY, f)
            self.assertEqual(body.count(TABLE), 1)
            self.assertEqual(body.count(NOTE), 1)

    def test_conflicting_or_annotated_summary_table_is_not_erased(self):
        view = validation_view(fixture()['facts'])
        for table in [TABLE.replace('14:30', '14:35'), TABLE.replace('5회차', '5회차 (영어)')]:
            body = '[일정 안내]\n' + table + '\n[주요 내용]\n해설'
            self.assertEqual(common_timetable(body, source_schedule(view)), body)
