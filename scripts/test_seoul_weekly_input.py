"""Recorded failed summary, local reviewed matrix and fake Pro/RPC only."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ingest.ai_errors import AiJobError
from ingest.program_ai import program_input
from ingest.reclassification_ai import classification_input
from ingest.seoul_content import assemble_seoul_body
from ingest.seoul_fact_roles import weekly_input_evidence, validate_weekly_schedule
from test_seoul_fact_roles import confirmed_case, recorded, replay_context, fake_translation
import test_seoul_per_session_replay as worker_fixture

FIXTURE = Path(__file__).parent/'testdata/seoul_weekly_input_recorded.json'


def latest():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


class WeeklyInputTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                       'ingest.supabase_store.create_ingest_client', 'ingest.chatgpt_plan_auth.authenticate_worker'):
            guard = patch(target, side_effect=AssertionError('real connection forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def replay(self, classified, mutate=None):
        def context(is_classified=False):
            data, c = replay_context(is_classified)
            if is_classified:
                # Raw observed source is deliberately older/incomplete. Current
                # confirmed description wins without mutating sourceText.
                c['body'] = recorded()['facts']['description']
            if mutate:
                mutate(data, c, is_classified)
            return data, c
        with patch.object(worker_fixture, 'recorded_case', side_effect=context), patch.object(
                worker_fixture, 'fake_translation', side_effect=fake_translation):
            return worker_fixture.run_recorded(self, classified=classified)

    def test_latest_actual_aggregation_fails_without_repairing_response(self):
        d = latest(); before = FIXTURE.read_bytes()
        self.assertIn('1회차 4개', d['actual_summary']['content_ko'])
        with self.assertRaises(AiJobError):
            assemble_seoul_body(d['actual_summary']['content_ko'], confirmed_case()['facts'])
        self.assertEqual(FIXTURE.read_bytes(), before)
        for classified in (False, True):
            result, calls, output, requests, _ = self.replay(classified,
                lambda data, c, _: data.update(summary=copy.deepcopy(d['actual_summary'])))
            self.assertEqual(len(requests), 1)
            self.assertEqual(result.completed, 0); self.assertFalse(output)
            self.assertFalse(any(n.startswith('finish_') for n, _ in calls))

    def test_complete_cells_reach_both_actual_request_paths_and_fake_candidates(self):
        expected = weekly_input_evidence(latest()['reviewed_table'])
        self.assertEqual(expected['rows'][0][-2:], [None, None])
        self.assertEqual(expected['rows'][-1][1:5],
                         [None, '5회차(일본어)', '5회차(중국어)', '5회차(영어)'])
        for classified in (False, True):
            result, calls, output, requests, _ = self.replay(classified)
            self.assertEqual(result.completed, 1)
            self.assertEqual(len(requests), 2)
            payload = json.loads(requests[0]['input'][0]['content'].split('\nbody:\n', 1)[1])
            self.assertEqual(payload['weeklyScheduleEvidence'], expected)
            self.assertIn('weeklyScheduleEvidence, when present', requests[0]['instructions'])
            if classified:
                self.assertEqual(payload['sourceText'], recorded()['facts']['description'])
                self.assertEqual(payload['nativeConfirmedFacts']['programFacts']['description'],
                                 confirmed_case()['facts']['description'])
            else:
                self.assertIn('description', payload['operatorSupplementedFields'])
                self.assertEqual(payload['currentFacts'], confirmed_case()['facts'])
                self.assertFalse(any('해설회차:' in line for line in payload['sessionEvidence']))
            self.assertEqual(requests[1]['input'][0]['content'],
                             'title_ko: '+output['titleKo']+'\ncontent_ko:\n'+output['contentKo'])
            validate_weekly_schedule(output['contentKo'], latest()['reviewed_table'])
            self.assertEqual(sum(n.startswith('finish_') for n, _ in calls), 1)
            self.assertEqual(output['aiModel'], 'gpt-6.1-sol')
            self.assertIn('내국인은 참여할 수 없습니다', output['contentKo'])
            self.assertIn('15 인', output['contentKo'])
            self.assertIn('잔여 인원에 한해 현장접수', output['contentKo'])

    def test_lost_empty_positions_stop_before_any_ai_request_in_both_workers(self):
        description = recorded()['facts']['description']
        with self.assertRaises(AiJobError): weekly_input_evidence(description)
        # An AI-inferred plausible matrix is also unable to prove source columns.
        with self.assertRaises(AiJobError):
            validate_weekly_schedule(latest()['reviewed_table'], description)
        for classified in (False, True):
            def missing(data, c, is_classified):
                data['context']['facts']['description'] = description
                f = c['nativeConfirmedFacts']['programFacts'] if is_classified else c['facts']
                f['description'] = description
            result, calls, output, requests, _ = self.replay(classified, missing)
            self.assertEqual(requests, []); self.assertEqual(result.completed, 0)
            self.assertFalse(output); self.assertFalse(any(n.startswith('finish_') for n, _ in calls))

    def test_weekday_omission_shift_language_and_blank_invention_block_both_workers(self):
        old = confirmed_case()['summary']['content_ko']
        changes = [old.replace('| 화 | 수 |', '| 수 | 화 |'),
                   old.replace('| 화 | 수 | 목 | 금 | 토 | 일 |', '| 화 | 수 | 목 | 금 | 토 | 월 |'),
                   old.replace('| 10:00 | 1회차 | 1회차 | 1회차 | 1회차 | — | — |',
                               '| 10:00 | — | 1회차 | 1회차 | 1회차 | 1회차 | — |'),
                   old.replace('| 10:00 | 1회차 | 1회차 | 1회차 | 1회차 | — | — |',
                               '| 10:00 | 1회차 | 1회차 | 1회차 | 1회차 | 1회차 | — |'),
                   old.replace('5회차(일본어) | 5회차(중국어)', '5회차(중국어) | 5회차(일본어)'),
                   old.replace('| 14:00 |', '| 13:00 |'),
                   old.replace('| 14:00 | 3회차 |', '| 14:00 | 2회차 |')]
        for index, changed in enumerate(changes):
            for classified in (False, True):
                with self.subTest(index=index, classified=classified):
                    result, calls, output, requests, _ = self.replay(classified,
                        lambda data, c, _: data.update(summary={**data['summary'], 'content_ko': changed}))
                    self.assertEqual(len(requests), 1); self.assertEqual(result.completed, 0)
                    self.assertFalse(output); self.assertFalse(any(n.startswith('finish_') for n, _ in calls))

    def test_normal_weekday_labels_spacing_and_empty_markers(self):
        source = latest()['reviewed_table']
        normal = source.replace('| 화 |', '| 화요일 |').replace('| 수 |', '| 수요일 |')
        normal = normal.replace('5회차(일본어)', '5 회차 ( 일본어 )')
        for empty in ('—', '–', '-', '없음'):
            validate_weekly_schedule(normal.replace('—', empty), source)
        self.assertEqual(weekly_input_evidence(source), weekly_input_evidence(source.replace('—', '없음')))

    def test_duplicate_weekdays_clocks_or_two_source_matrices_block(self):
        source = latest()['reviewed_table']
        for changed in (source.replace('| 수 |', '| 화 |'), source.replace('| 11:00 |', '| 10:00 |'),
                        source+'\n\n'+source, source.replace('| 시간 | 화 | 수 |', '| 시간 | 화 |')):
            with self.assertRaises(AiJobError): weekly_input_evidence(changed)
        for lost in ('시간 / 요일\n화\n화\n10:00\n1회차',
                     '시간 / 요일\n화\n수\n10:00',
                     '시간 / 요일\n화\n수\n10:00\n1회차\n2회차\n3회차'):
            with self.assertRaises(AiJobError): weekly_input_evidence(lost)

    def test_different_days_ordinals_languages_and_real_midnight(self):
        source = '| 시간 | 월요일 | 토요일 |\n| --- | --- | --- |\n| 00:00 | 7회차(영어) | — |\n| 09:30 | — | 8회차(한국어) |'
        expected = {'headers': ['시간', '월요일', '토요일'],
                    'rows': [['00:00', '7회차(영어)', None], ['09:30', None, '8회차(한국어)']]}
        self.assertEqual(weekly_input_evidence(source), expected)
        validate_weekly_schedule(source, source)
        with self.assertRaises(AiJobError):
            validate_weekly_schedule(source.replace('7회차(영어) | —', '— | 7회차(영어)'), source)

    def test_connector_storage_projection_preserves_empty_positions_and_language(self):
        from ingest.connectors.seoul_reservation import normalize_seoul_item
        from ingest.program_db import program_rpc_item
        from test_seoul_reservation import row
        html = '<p>합성 해설 안내입니다. 예약 확인 후 참여합니다.</p><table><tr><td>시간 / 요일</td><td>화</td><td>목</td></tr><tr><td>10:00</td><td>1회차<br>(영어)</td><td></td></tr><tr><td>14:00</td><td></td><td>2회차</td></tr></table>'
        original = row(DTLCONT=html); before = copy.deepcopy(original)
        storage = program_rpc_item(normalize_seoul_item(original))
        # Storage adapter mapping only; never invoke a DB client.
        description = storage['program_facts']['description']
        expected = {'headers': ['시간', '화', '목'],
                    'rows': [['10:00', '1회차 (영어)', None], ['14:00', None, '2회차']]}
        self.assertEqual(weekly_input_evidence(description), expected)
        self.assertEqual(original, before)

    def test_no_weekday_table_does_not_create_one_or_change_dated_schedules(self):
        for description in ('1회차: 10월 18일 10:00~12:00 공예 체험',
                            '진행기간: 10월 18일~25일\n1회차: 10월 18일\n2회차: 10월 25일',
                            '매주 일요일 10:00~12:00, 총 4회. 언어: 한국어'):
            self.assertIsNone(weekly_input_evidence(description))
            validate_weekly_schedule(description, description)

    def test_input_builders_are_pure_and_non_seoul_classification_stays_unchanged(self):
        for classified in (False, True):
            _, c = replay_context(classified); before = copy.deepcopy(c)
            first = classification_input(c) if classified else program_input(c)
            second = classification_input(c) if classified else program_input(c)
            self.assertEqual(first, second); self.assertEqual(c, before)
        from test_reclassification_ai import context
        c = context('event', 'myseoul_program')
        self.assertNotIn('weeklyScheduleEvidence', json.loads(classification_input(c)))


if __name__ == '__main__':
    unittest.main()
