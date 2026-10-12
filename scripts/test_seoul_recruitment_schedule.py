"""Source-scoped session evidence; fake providers/RPC and no socket access."""
import copy
import json
import socket
import unittest
from unittest.mock import patch

from ingest.ai_errors import AiJobError
from ingest.myseoul_content import schedule_lines
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job, program_input
from ingest.reclassification_ai import process_reclassified_job
from ingest.seoul_content import assemble_seoul_body, validation_view
from test_program_ai import context, bind_program_filters
from test_reclassification_ai import context as classified_context
from test_seoul_content import fake_japanese


SOURCE = '❐ 모집 일시 : 10월 2, 30일 (금) 오전 10:00 ~ 11:30 / 오후 14:00 ~ 15:30'
TABLE = ('| 날짜 | 오전 | 오후 |\n|---|---|---|\n'
         '| 2026-10-02(금) | 10:00~11:30 | 14:00~15:30 |\n'
         '| 2026-10-30(금) | 10:00~11:30 | 14:00~15:30 |')
SUMMARY = ('[한 줄 요약]\n합성 숲 체험입니다.\n[대상]\n성인\n'
           '[일정 안내]\n' + TABLE + '\n[주요 내용]\n낙엽을 관찰합니다.\n'
           '[신청 방법]\n인터넷으로 예약합니다.')


def session_context():
    c = context()
    c['title'] = '합성 숲 체험'
    c['facts'].update(description=SOURCE, conditions=[], target_raw='성인',
                      fee_kind='free', fee_amounts=[], residence_evidence=[])
    for key, value in zip(c['facts']['periods'],
                          ['2026-09-28', '2026-10-29', '2026-10-02', '2026-10-30']):
        c['facts']['periods'][key] = dict(raw=value, value=value, precision='day', status='ok')
    c['observedFacts'] = copy.deepcopy(c['facts'])
    return bind_program_filters(c)


class RecruitmentScheduleTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_reported_grouped_days_and_both_clock_ranges(self):
        f = session_context()['facts']
        before = copy.deepcopy(f)
        body = assemble_seoul_body(SUMMARY, f)
        self.assertIn(TABLE, body)
        evidence = schedule_lines(validation_view(f))
        self.assertEqual(len(evidence), 2)
        for day, line in zip((2, 30), evidence):
            self.assertIn(f'10월 {day}일', line)
            self.assertIn('오전 10:00 ~ 11:30 / 오후 14:00 ~ 15:30', line)
        self.assertEqual(f, before)
        self.assertEqual(body, assemble_seoul_body(body, f))

    def test_real_date_year_weekday_and_time_conflicts_still_fail(self):
        for old, new in [('2026-10-02', '2026-10-03'), ('2026-10-30', '2027-10-30'),
                         ('(금)', '(토)'), ('10:00~11:30', '10:00~12:30'),
                         ('14:00~15:30', '13:00~15:30')]:
            with self.subTest(new=new), self.assertRaises(AiJobError):
                assemble_seoul_body(SUMMARY.replace(old, new, 1), session_context()['facts'])

    def test_application_labels_ranges_and_ambiguous_dates_are_not_sessions(self):
        for text in [SOURCE.replace('모집 일시', label) for label in
                     ('모집 기간', '접수 일시', '신청 일시', '모집 마감')]+[
                         '모집 일시: 9월 28일 ~ 10월 29일 10:00 ~ 17:00',
                         '모집 일시: 10월 10일 10:00 ~ 11:30',
                         '모집 일시: 10월 2, 31일 10:00 ~ 11:30']:
            f = session_context()['facts']; f['description'] = text
            with self.subTest(text=text):
                self.assertEqual(schedule_lines(validation_view(f)), [])
                with self.assertRaises(AiJobError): assemble_seoul_body(SUMMARY, f)

    def test_preserves_other_schedule_evidence_and_does_not_change_myseoul(self):
        f = session_context()['facts']
        f['description'] += '\n집결 일시: 10월 2일 09:50~10:00'
        self.assertEqual(len(schedule_lines(validation_view(f))), 3)
        self.assertEqual(schedule_lines({'description': SOURCE}), [])
        data = json.loads(program_input({**session_context(), 'facts': f}))
        self.assertEqual(data['sessionEvidence'], schedule_lines(validation_view(f)))
        self.assertEqual(data['currentFacts'], f)

    def test_other_list_sizes_explicit_year_and_separators(self):
        for listed in ('2일, 30일', '2·16·30일', '30, 2일', '2、30일'):
            f = session_context()['facts']
            f['description'] = SOURCE.replace('10월 2, 30일', '2026년 10월 '+listed)
            before = copy.deepcopy(f)
            body = assemble_seoul_body(SUMMARY, f)
            self.assertIn(TABLE, body)
            self.assertEqual(f, before)
            self.assertEqual(len(schedule_lines(validation_view(f))), 3 if '16' in listed else 2)

    def test_omitted_year_does_not_override_explicit_source_year_or_current_bounds(self):
        f = session_context()['facts']
        f['description'] = SOURCE.replace('10월', '2027년 10월')
        with self.assertRaises(AiJobError): assemble_seoul_body(SUMMARY, f)
        f = session_context()['facts']
        periods = {'operation': [{'status':'ok', 'endpoints':[
            {'value':'2026-10-03','precision':'day'}, {'value':'2026-10-30','precision':'day'}]}]}
        with self.assertRaises(AiJobError): assemble_seoul_body(SUMMARY, f, periods=periods)
        omitted = SUMMARY.replace('2026-10-02', '10월 2일').replace('2026-10-30', '10월 30일')
        self.assertIn('10월 2일', assemble_seoul_body(omitted, f))

    def test_single_session_after_application_but_not_overlapping_recruitment(self):
        f = session_context()['facts']
        f['periods']['SVCOPNENDDT'] = copy.deepcopy(f['periods']['SVCOPNBGNDT'])
        f['description'] = SOURCE.replace('2, 30일', '2일')
        self.assertEqual(schedule_lines(validation_view(f)), [])
        f['periods']['RCPTENDDT'].update(value='2026-10-01', raw='2026-10-01')
        self.assertEqual(len(schedule_lines(validation_view(f))), 1)

    def test_mixed_promotional_prose_or_independent_dates_stay_uninferred(self):
        for tail in (' 함께 즐겨요!', ' / 10월 30일 09:00~10:00', ' / 30일 09:00~10:00'):
            f = session_context()['facts']; f['description'] = SOURCE+tail
            self.assertEqual(schedule_lines(validation_view(f)), [])

    def test_general_and_reclassified_candidate_connection_and_conflict_stop(self):
        for classified in (False, True):
            for bad in (False, True):
                with self.subTest(classified=classified, bad=bad):
                    self.run_fake_worker(classified, SUMMARY.replace('10:00~11:30', '09:00~11:30', 1)
                                         if bad else SUMMARY, bad)

    def run_fake_worker(self, classified, summary, bad):
        c = session_context()
        if classified:
            native = c['facts']
            c = classified_context('program', 'seoul_reservation')
            c.update(title='합성 숲 체험', body=native['description'])
            c['facts'].update(delivery='offline', deadlineOn='2026-10-29')
            c['filters'] = session_context()['filterContext']['data']
            c['nativeConfirmedFacts']['programFacts'] = native
        original = copy.deepcopy(c)
        events, calls, translated = [], [], []
        def rpc(name, args):
            events.append((name, args))
            if name.startswith('claim_'): return c if classified else [c]
            if name.startswith('finish_'): return {'candidateId': c['sourceItemId'], 'outcome': 'inserted'}
            if name == 'fail_seoul_program_ai': return 'failed'
            if name == 'reclassified_content_ai_status': return []
            raise AssertionError(name)
        def summarize(body, url, title=None):
            calls.append('summary')
            request = json.loads(body)
            if not classified: self.assertEqual(len(request['sessionEvidence']), 2)
            return summary, 'success', 'fake-model'
        def translate(title, body):
            calls.append('translation'); translated.append(body)
            self.assertIn(TABLE, body)
            return '合成体験', fake_japanese(body), 'success', 'fake-model'
        kwargs = dict(source_item_id=c['sourceItemId'], revision=c['revision'], worker_id=c['workerId'],
                      summarize_ko=summarize, translate_ja=translate)
        result = (process_reclassified_job(ProgramAIAdapter(rpc), classification_version=c['classificationVersion'], **kwargs)
                  if classified else process_seoul_program_job(ProgramAIAdapter(rpc), **kwargs))
        self.assertEqual(c, original)
        self.assertEqual(calls, ['summary'] if bad else ['summary', 'translation'])
        self.assertEqual(result.completed, 0 if bad else 1)
        finishes = [args for name, args in events if name.startswith('finish_')]
        self.assertEqual(len(finishes), 0 if bad else 1)
        if finishes:
            self.assertEqual(finishes[0]['p_revision'], c['revision'])
            for name in ('claimedAt', 'leaseUntil', 'workerId'):
                self.assertEqual(finishes[0][{'claimedAt':'p_claimed_at','leaseUntil':'p_lease_until','workerId':'p_worker_id'}[name]], c[name])
            self.assertEqual(finishes[0]['p_output']['contentKo'], translated[0])
            self.assertEqual(finishes[0].get('p_classification_version') if classified else finishes[0]['p_facts_version'],
                             c['classificationVersion'] if classified else c['factsVersion'])


if __name__ == '__main__': unittest.main()
