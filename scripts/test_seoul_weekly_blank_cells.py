"""Recorded bare blank cells; fake Pro/auth/translation/RPC, no live IO."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ingest.ai_errors import AiJobError
from ingest.body_markdown import read_body
from ingest.program_ai import program_input
from ingest.reclassification_ai import classification_input
from ingest.seoul_fact_roles import weekly_input_evidence, validate_weekly_schedule
from test_seoul_fact_roles import confirmed_case, replay_context, fake_translation
import test_seoul_ai_no_retry as no_retry_fixture
import test_seoul_per_session_replay as worker_fixture

FIXTURE = Path(__file__).parent / 'testdata/seoul_weekly_blank_cells_recorded.json'


def bare_table():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))['reviewed_table']


def bare_case():
    data = confirmed_case()
    old = json.loads((FIXTURE.parent / 'seoul_weekly_input_recorded.json').read_text(encoding='utf-8'))['reviewed_table']
    data['facts']['description'] = data['facts']['description'].replace(old, bare_table())
    summary_table = read_body(data['summary']['content_ko']).tables[0].markdown
    data['summary']['content_ko'] = data['summary']['content_ko'].replace(summary_table, bare_table())
    assert bare_table() in data['facts']['description']
    assert bare_table() in data['summary']['content_ko']
    return data


def bare_context(classified=False):
    data, c = replay_context(classified)
    replacement = bare_case()
    facts = c['nativeConfirmedFacts']['programFacts'] if classified else c['facts']
    facts['description'] = replacement['facts']['description']
    data['context']['facts'] = copy.deepcopy(facts)
    data['summary'] = replacement['summary']
    # Deliberately retain the older flattened source/observations. Only current
    # reviewed description is authoritative, including in reclassification.
    return data, c


class BlankCellTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                       'ingest.supabase_store.create_ingest_client', 'ingest.chatgpt_plan_auth.authenticate_worker'):
            guard = patch(target, side_effect=AssertionError('real connection forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def replay(self, classified=False, summary_change=None, translation_change=None):
        def context(is_classified=False):
            data, c = bare_context(is_classified)
            if summary_change:
                data['summary']['content_ko'] = summary_change(data['summary']['content_ko'])
            return data, c
        with patch.object(worker_fixture, 'recorded_case', side_effect=context), patch.object(
                worker_fixture, 'fake_translation', side_effect=fake_translation):
            return worker_fixture.run_recorded(self, classified=classified, change=translation_change)

    def test_exact_recorded_blank_positions_reach_both_input_builders_without_mutation(self):
        expected = {'headers': ['시간', '화', '수', '목', '금', '토', '일'], 'rows': [
            ['10:00', '1회차', '1회차', '1회차', '1회차', None, None],
            ['11:00', '2회차', '2회차', '2회차', '2회차', '1회차', '1회차'],
            ['14:00', '3회차', '3회차', '3회차', '3회차', '2회차', '2회차'],
            ['15:00', '4회차', '4회차', '4회차', '4회차', '3회차', '3회차'],
            ['16:00', None, '5회차(일본어)', '5회차(중국어)', '5회차(영어)', '4회차', '4회차']]}
        before = FIXTURE.read_bytes()
        self.assertEqual(weekly_input_evidence(bare_table()), expected)
        self.assertEqual(read_body(bare_table()).tables[0].markdown, bare_table())
        for classified in (False, True):
            _, c = bare_context(classified); original = copy.deepcopy(c)
            payload = json.loads(classification_input(c) if classified else program_input(c))
            self.assertEqual(payload['weeklyScheduleEvidence'], expected)
            self.assertEqual(c, original)
            for _ in range(2):
                self.assertEqual(weekly_input_evidence(bare_table()), expected)
        self.assertEqual(FIXTURE.read_bytes(), before)

    def test_bare_cells_reach_fake_pro_translation_and_fenced_candidate_both_workers(self):
        for classified in (False, True):
            with self.subTest(classified=classified):
                result, calls, output, requests, _ = self.replay(classified)
                self.assertEqual(result.completed, 1)
                self.assertEqual(len(requests), 2)
                payload = json.loads(requests[0]['input'][0]['content'].split('\nbody:\n', 1)[1])
                self.assertEqual(payload['weeklyScheduleEvidence'], weekly_input_evidence(bare_table()))
                self.assertIn(bare_table(), output['contentKo'])
                self.assertEqual(requests[1]['input'][0]['content'],
                                 'title_ko: '+output['titleKo']+'\ncontent_ko:\n'+output['contentKo'])
                self.assertEqual(output['contentJa'], fake_translation(output['contentKo']))
                self.assertEqual(sum(n.startswith('finish_') for n, _ in calls), 1)
                self.assertEqual(sum(n.startswith('fail_') for n, _ in calls), 0)

    def test_bare_cells_also_reach_no_retry_completion(self):
        with patch.object(no_retry_fixture, 'replay_context', side_effect=bare_context), patch.object(
                no_retry_fixture, 'confirmed_case', side_effect=bare_case):
            for classified in (False, True):
                result, calls, stages, count = no_retry_fixture.NoRetryTests.replay(self, classified)
                self.assertEqual((result.completed, result.failed, result.retried), (1, 0, 0))
                self.assertEqual(stages, ['summary', 'translation']); self.assertEqual(count, 2)
                self.assertTrue(calls[0][0].endswith('no_retry'))
                self.assertTrue(calls[-1][0].startswith('finish_'))

    def test_blank_invention_terminates_no_retry_attempt_once(self):
        def bad_translation(body):
            return fake_translation(body).replace('| | |', '| 中止 | |', 1)
        with patch.object(no_retry_fixture, 'replay_context', side_effect=bare_context), patch.object(
                no_retry_fixture, 'confirmed_case', side_effect=bare_case), patch.object(
                no_retry_fixture, 'fake_translation', side_effect=bad_translation):
            for classified in (False, True):
                result, calls, stages, count = no_retry_fixture.NoRetryTests.replay(self, classified)
                self.assertEqual((result.failed, result.retried, result.completed), (1, 0, 0))
                self.assertEqual(stages, ['summary', 'translation']); self.assertEqual(count, 2)
                self.assertEqual(calls[-1][0], 'fail_seoul_ai_no_retry')
                self.assertEqual(sum(n == 'fail_seoul_ai_no_retry' for n, _ in calls), 1)
                self.assertFalse(any(n.startswith('finish_') for n, _ in calls))

    def test_width_header_time_duplicates_and_flattening_remain_invalid(self):
        source = bare_table()
        changes = [source.replace('| | |', '| |', 1), source.replace('| | |', '| | | |', 1),
                   source.replace('| 화 |', '| |', 1), source.replace('| 10:00 |', '| |'),
                   source.replace('| 10:00 |', '| 25:00 |'),
                   source.replace('| 수 |', '| 화 |'), source.replace('| 11:00 |', '| 10:00 |')]
        for index, bad in enumerate(changes):
            with self.subTest(index=index), self.assertRaises(AiJobError): weekly_input_evidence(bad)
        _, original = replay_context()
        with self.assertRaises(AiJobError): weekly_input_evidence(original['observedFacts']['description'])

    def test_filled_blank_shifted_or_missing_session_language_and_clock_block_before_translation(self):
        mutations = [
            lambda s: s.replace('| | |', '| 1회차 | |', 1),
            lambda s: s.replace('| 16:00 | | 5회차(일본어)', '| 16:00 | 5회차(일본어) |'),
            lambda s: s.replace('| 14:00 | 3회차 |', '| 14:00 | |'),
            lambda s: s.replace('5회차(일본어) | 5회차(중국어)', '5회차(중국어) | 5회차(일본어)'),
            lambda s: s.replace('5회차(일본어)', '5회차'),
            lambda s: s.replace('| 14:00 |', '| 13:00 |'),
            lambda s: s.replace('| 화 | 수 |', '| 수 | 화 |')]
        for classified in (False, True):
            for index, mutation in enumerate(mutations):
                with self.subTest(classified=classified, index=index):
                    result, calls, output, requests, _ = self.replay(classified, summary_change=mutation)
                    self.assertEqual(len(requests), 1); self.assertEqual(result.completed, 0)
                    self.assertFalse(output); self.assertFalse(any(n.startswith('finish_') for n, _ in calls))

    def test_translation_cannot_fill_blanks_even_with_nonnumeric_prose_or_move_languages(self):
        mutations = [lambda s: s.replace('| | |', '| 中止 | |', 1),
                     lambda s: s.replace('| | |', '| なし | |', 1),
                     lambda s: s.replace('第5回(日本語)', '第5回'),
                     lambda s: s.replace('第5回(日本語) | 第5回(中国語)', '第5回(中国語) | 第5回(日本語)')]
        for classified in (False, True):
            for index, mutation in enumerate(mutations):
                with self.subTest(classified=classified, index=index):
                    def change(d):
                        text = mutation(d['content_ja'])
                        self.assertNotEqual(text, d['content_ja'])
                        return {**d, 'content_ja': text}
                    result, calls, output, requests, _ = self.replay(classified, translation_change=change)
                    self.assertEqual(len(requests), 2); self.assertEqual(result.completed, 0)
                    self.assertFalse(output); self.assertFalse(any(n.startswith('finish_') for n, _ in calls))

    def test_outer_delimiters_spacing_escaped_content_and_real_midnight(self):
        source = '| 시간 | 월요일 | 토요일 |\n| --- | --- | --- |\n| 00:00 | 7회차(영어) | |\n| 09:30 | | 8회차(한국어) |'
        self.assertEqual(weekly_input_evidence(source)['rows'],
                         [['00:00', '7회차(영어)', None], ['09:30', None, '8회차(한국어)']])
        validate_weekly_schedule(source, source)
        # Optional outer delimiters with nonempty final cells stay supported.
        # A trailing empty cell needs its explicit column delimiter; don't
        # guess a missing column from the width of a different row.
        complete = source.replace('7회차(영어) | |', '7회차(영어) | 8회차(한국어) |')
        unwrapped = '\n'.join(line[1:-1] for line in complete.splitlines())
        self.assertEqual(weekly_input_evidence(unwrapped), weekly_input_evidence(complete))
        for marker in ('—', '–', '-', '없음'):
            marked = source.replace('| |', '| '+marker+' |')
            validate_weekly_schedule(marked, source)
        escaped = source.replace('7회차(영어)', r'7회차(영어) \\| 추가')
        self.assertEqual(len(read_body(escaped).tables[0].rows[0]), 3)
        self.assertEqual(read_body(escaped).tables[0].rows[0][-1], '')

    def test_other_table_required_values_are_not_relaxed(self):
        for source in ('| 회차 | 날짜 | 시간 |\n| --- | --- | --- |\n| 1회차 | | 10:00 |',
                       '| 항목 | 값 |\n| --- | --- |\n| 비용 | |'):
            with self.assertRaises(AiJobError): read_body(source)

    def test_japanese_weekday_labels_and_time_synonyms_preserve_actual_blank_cells(self):
        from ingest.translation_validation import validate_translation_fidelity
        source = '| 시간 | 수요일 | 금요일 |\n| --- | --- | --- |\n| 16:00 | 5회차(일본어) | |'
        for label in ('時間', '時刻', '時間 / 曜日'):
            target = f'| {label} | 水曜日 | 金曜日 |\n| --- | --- | --- |\n| 16:00 | 第5回(日本語) | |'
            validate_translation_fidelity('합성', source, '合成', target)
            self.assertEqual(read_body(target).tables[0].rows[0][-1], '')


if __name__ == '__main__': unittest.main()
