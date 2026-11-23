"""Offline worker regression using reconstructed excerpts from the two candidates."""
import unittest
from unittest.mock import patch

from ingest.body_markdown import read_body
from ingest.myseoul_content import schedule_block, schedule_lines
from ingest.seoul_content import assemble_seoul_body
import test_seoul_date_hours_replay as worker
from test_seoul_per_session_replay import recorded_case


CLASS = [
    ('12월 2일 ~ 12월 30일 매주 수요일 14:00 ~ 15:00', '12月2日～12月30日の毎週水曜日14時～15時'),
    ('- 아뜰리에 클래스는 매주 다른 내용으로 진행되며, 한 달 동안 수강하려면 각 주차별로 총 5회 예약 해야 합니다.',
     '- アトリエクラスは毎週異なる内容で行われ、1か月間受講するには各週ごとに計5回予約する必要があります。'),
]
TOUR = [(f'- {month}월 {day}일(토) : 11시 / 12시 / 14시 / 15시',
         f'- {month}月{int(day)}日（土）：11時 / 12時 / 14時 / 15時')
        for month, day in [(11, '21'), (11, '28'), (12, '05')]]


class ScheduleMarkerTests(unittest.TestCase):
    def test_marked_and_unmarked_evidence_preserve_real_children(self):
        tree = '- 11월 21일(토) 일정\n  - 11월 21일(토) 11시\n    - 11월 21일(토) 12시'
        records = schedule_lines({'description': '진행 일정\n' + tree})
        for source in ([tree], records):
            result = schedule_block(source)
            self.assertEqual(result, '**진행 일정:**\n' + tree)
            self.assertEqual([item.indent for item in read_body(result).items], [0, 2, 4])
        padded = '진행 일정\n  - 11월 21일 일정\n  - 11월 28일 일정\n\n    - 12월 5일 일정'
        result = schedule_block(schedule_lines({'description': padded}))
        self.assertEqual([item.indent for item in read_body(result).items], [0, 0, 0])
        self.assertEqual(schedule_block(['11:00 - 12:00\n예약 필수', '-5℃ 이하']),
                         '**진행 일정:**\n- 11:00 - 12:00\n  예약 필수\n- -5℃ 이하')

    def test_general_and_reclassified_translation_inputs_and_candidates(self):
        for name, dates, rows in [('클래식 성악', ('12-02', '12-30'), CLASS),
                                  ('광화문 투어', ('11-21', '12-05'), TOUR)]:
            _, ctx = recorded_case()
            facts = ctx['facts']
            facts.update(description='진행 일정\n' + '\n'.join(ko for ko, ja in rows),
                         target_raw='성인', conditions=[], activity_evidence=[], residence_evidence=[])
            for key, day in zip(('SVCOPNBGNDT', 'SVCOPNENDDT'), dates):
                value = '2026-' + day + 'T00:00:00+09:00'
                facts['periods'][key].update(raw=value, value=value)
            summary = {'content_ko': '[한 줄 요약]\n프로그램에 참여합니다.\n[대상]\n성인\n'
                                     '[일정 안내]\n[주요 내용]\n- 준비물\n  - 필기구\n[신청 방법]\n예약 후 참여합니다.',
                       'facts': dict(audience='성인', geo_age_income='성인', amount_period_deadline='무료',
                                     how_to_apply='예약 후 참여합니다.')}
            def translate(body):
                body = body.replace('준비물', '持ち物').replace('필기구', '筆記用具')
                for ko, ja in rows:
                    body = body.replace(ko.removeprefix('- '), ja.removeprefix('- '))
                return worker.fake_translation(body)
            expected = assemble_seoul_body(summary['content_ko'], facts)
            entry = dict(title=name, facts=facts, filters=ctx['filterContext']['data'], summary=summary,
                         translation_input_ko=expected,
                         translation=dict(title_ja='日程案内', content_ja=translate(expected)))
            for classified in (False, True):
                with (self.subTest(name=name, classified=classified),
                      patch.object(worker, 'recorded', return_value=[entry]),
                      patch.object(worker, 'synthetic_translation', translate)):
                    result, calls, outputs, requests = worker.DateHoursReplayTests.replay(self, 0, classified)
                    self.assertEqual(result.completed, 1, calls[-1][0])
                    candidate, = outputs
                    self.assertIn('- 준비물\n  - 필기구', candidate['contentKo'])
                    self.assertIn('- 持ち物\n  - 筆記用具', candidate['contentJa'])
                    self.assertEqual(requests[1]['input'][0]['content'].split('content_ko:\n', 1)[1],
                                     candidate['contentKo'])
                    for lang, index in [('contentKo', 0), ('contentJa', 1)]:
                        lines = candidate[lang].splitlines()
                        for row in rows:
                            self.assertEqual(lines.count('- ' + row[index].removeprefix('- ')), 1)
                        self.assertFalse(any(line.startswith('- - ') for line in lines))
