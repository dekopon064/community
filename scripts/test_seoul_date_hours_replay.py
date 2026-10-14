"""Two retained actual failures; fake Pro/RPC only, never a live retry.

The first Japanese response is historical. The second case has no historical
Japanese response; its worker translation is explicitly synthetic. Source/job/
actor/fence IDs and title/URL are synthetic, descriptions/responses are retained.
"""
import copy
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from ingest.ai_errors import AiJobError
from ingest.ai_provider import create_provider_adapter
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job, program_input
from ingest.reclassification_ai import process_reclassified_job, classification_input, protected_sections
from ingest.rpc_errors import RpcTimeout
from ingest.seoul_content import assemble_seoul_body, validation_view
from ingest.seoul_operating_hours import facility_hours_evidence
from ingest.translation_validation import _dates_and_times, _validate_cell, validate_translation_fidelity
from test_ingest_ai_chatgpt_plan import verified_session, streamed
from test_ingest_ai_openai import response
from test_seoul_per_session_replay import recorded_case, fake_translation

FIXTURE = Path(__file__).parent/'testdata/seoul_date_hours_recorded.json'


def recorded():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def context(index, classified=False):
    _, c = recorded_case(classified)
    d = recorded()[index]
    f = copy.deepcopy(d['facts'])
    c.update(title=d['title'])
    if classified:
        c.update(body=f['description'], sourceUrl=f['official_url'])
        c['nativeConfirmedFacts']['programFacts'] = f
        c['filters'] = copy.deepcopy(d['filters'])
        c['facts'].update(delivery='offline', scope='unknown', regions=[], evidence='',
                          deadlineOn=f['periods']['RCPTENDDT']['value'][:10])
    else:
        c.update(facts=f, observedFacts=copy.deepcopy(f))
        c['filterContext']['data'] = copy.deepcopy(d['filters'])
        c.pop('activityConfirmation', None)
        # Synthetic server-confirmed location evidence; not an invented DB edit.
        c['activityConfirmation'] = {k:c[k] for k in (
            'sourceItemId','revision','factsVersion','jobId','claimedAt','leaseUntil','workerId')}
        c['activityConfirmation'].update(confirmed=True, filterVersion=c['filterContext']['filterVersion'])
    c['failurePolicy'] = {'policy':'no_retry', 'attempt':'f'*64}
    return c


def synthetic_translation(body):
    # A deterministic fake, never a replacement recorded/new Pro response.
    from ingest.region_ja_glossary import regions_in_text
    for region in sorted(regions_in_text(body),key=lambda r:len(r.ko),reverse=True):
        body = body.replace(region.ko,region.ja)
    body = re.sub(r"'26\.10\.7\.\(수\)/10\.14\.\(수\)",
                  '2026年10月7日（水）/10月14日（水）', body)
    body = body.replace('신청불가','申込不可').replace('신청할 수 없습니다','申し込めません')
    return fake_translation(body).replace('ㅇ','○')


class DateHoursReplayTests(unittest.TestCase):
    def setUp(self):
        for name in ('socket.socket.connect','socket.create_connection','socket.getaddrinfo',
                     'ingest.supabase_store.create_ingest_client','ingest.chatgpt_plan_auth.authenticate_worker'):
            guard = patch(name, side_effect=AssertionError('real connection forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def test_both_historical_failures_and_exact_response_replay(self):
        a,b = recorded(); raw = FIXTURE.read_bytes()
        self.assertEqual(_dates_and_times('2026.10.7.(수)'), [('date',2026,10,7)])
        validate_translation_fidelity(a['title'], a['translation_input_ko'],
                                     a['translation']['title_ja'], a['translation']['content_ja'])
        # Reproduce the exact former parser omission, not a new AI response.
        current = _dates_and_times
        def old(text, **kw):
            text = re.sub(r"(?:2026|'26)\.10\.\d+\.\(수\)|10\.14\.\(수\)", '', text)
            return current(text, **kw)
        with patch('ingest.translation_validation._dates_and_times', side_effect=old):
            with self.assertRaises(AiJobError):
                validate_translation_fidelity(a['title'],a['translation_input_ko'],
                                             a['translation']['title_ja'],a['translation']['content_ja'])
        with patch('ingest.seoul_operating_hours.facility_hours_evidence', return_value=[]):
            with self.assertRaises(AiJobError): assemble_seoul_body(b['summary']['content_ko'],b['facts'])
        body = assemble_seoul_body(b['summary']['content_ko'], b['facts'])
        self.assertIn('센터 운영시간인 09:00~17:00 안에서 일정을 협의',body)
        self.assertEqual(FIXTURE.read_bytes(),raw)

    def replay(self, index, classified=False, *, bad_ko=None, bad_ja=None, claim_change=None, unknown=None, skip=False):
        d = recorded()[index]; c = context(index,classified); expected = copy.deepcopy(c)
        native = c['nativeConfirmedFacts']['programFacts'] if classified else c['facts']
        summary = copy.deepcopy(d['summary'])
        if bad_ko: summary['content_ko'] = bad_ko(summary['content_ko'])
        try:
            if classified:
                app = c['filters']['application']['value']
                assembled = assemble_seoul_body(summary['content_ko'],native,reviewed=protected_sections(c),
                    periods={'application':[{'status':'ok','endpoints':[app['start'],app['end']]}]})
            else:
                assembled = assemble_seoul_body(summary['content_ko'],native)
        except AiJobError: assembled = '[한 줄 요약]\n사용되지 않는 합성 번역 입력'
        japanese = (d['translation'] if index == 0 and not classified and not bad_ko
                    and assembled == d['translation_input_ko'] else
                    {'title_ja':'合成日程案内','content_ja':synthetic_translation(assembled)})
        if bad_ja: japanese = {**japanese,'content_ja':bad_ja(japanese['content_ja'])}
        client = streamed([response(json.dumps(summary,ensure_ascii=False)),
                           response(json.dumps(japanese,ensure_ascii=False))])
        provider = create_provider_adapter('chatgpt_plan',None,client=client,plan_session=verified_session())
        self.addCleanup(provider.close)
        events, outputs = [], []
        if claim_change: claim_change(c)
        before = copy.deepcopy(c)
        def rpc(name,args):
            events.append((name,copy.deepcopy(args)))
            if name.startswith('claim_'):
                if skip: return None if classified else []
                return c if classified else [c]
            if name.startswith('finish_') or name == 'fail_seoul_ai_no_retry':
                for key, param in [('jobId','p_job_id'),('revision','p_revision'),
                                   ('workerId','p_worker_id'),('claimedAt','p_claimed_at'),('leaseUntil','p_lease_until')]:
                    self.assertEqual(args[param],c[key])
                if name == 'fail_seoul_ai_no_retry':
                    self.assertEqual(args['p_attempt'],c['failurePolicy']['attempt'])
                    if unknown == 'failure': raise RpcTimeout()
                    return 'failed'
                self.assertEqual(args.get('p_facts_version',args.get('p_classification_version')),
                                 c.get('factsVersion',c.get('classificationVersion')))
                if unknown == 'completion': raise RpcTimeout()
                outputs.append(args['p_output'])
                return {'outcome':'inserted','candidateId':c['sourceItemId']}
            raise AssertionError('unexpected RPC: '+name)
        kwargs = dict(source_item_id=expected['sourceItemId'],revision=expected['revision'],
                      worker_id=expected['workerId'],no_retry=True,
                      summarize_ko=provider.summarize_ko if classified else provider.summarize_program_ko,
                      translate_ja=provider.translate_ja)
        result = (process_reclassified_job(ProgramAIAdapter(rpc),classification_version=c['classificationVersion'],**kwargs)
                  if classified else process_seoul_program_job(ProgramAIAdapter(rpc),**kwargs))
        self.assertEqual(c,before)
        self.assertEqual(result.retried,0)
        self.assertLessEqual(len(client.calls),2)
        self.assertLessEqual(sum(n.startswith('finish_') for n,_ in events),1)
        self.assertLessEqual(sum(n=='fail_seoul_ai_no_retry' for n,_ in events),1)
        self.assertNotIn(c['failurePolicy']['attempt'],json.dumps(client.calls))
        return result,events,outputs,client.calls

    def test_general_and_reclassified_actual_summaries_reach_fake_candidates(self):
        for index in (0,1):
            for classified in (False,True):
                with self.subTest(index=index,classified=classified):
                    r,e,outputs,calls = self.replay(index,classified)
                    self.assertEqual((r.completed,r.failed,r.state_unknown),(1,0,0))
                    self.assertEqual(len(calls),2); self.assertEqual(len(outputs),1)
                    out = outputs[0]
                    self.assertEqual(calls[1]['input'][0]['content'], 'title_ko: '+out['titleKo']+'\ncontent_ko:\n'+out['contentKo'])
                    if index == 0 and not classified:
                        old=recorded()[0]
                        # Historical JA belongs to the historical KO. A changed
                        # final body needs an explicitly synthetic translation.
                        self.assertEqual(out['contentJa'], old['translation']['content_ja']
                            if out['contentKo']==old['translation_input_ko'] else synthetic_translation(out['contentKo']))
                    if index == 1:
                        for text in ('09:00~17:00 안에서 일정을 협의','설·추석','근로자의 날',
                                     '02-305-1334','2일 전까지','개인정보 동의서','주차비는 지원하지 않습니다',
                                     '별도 취소 안내가 없으면 우천 시에도 진행'):
                            self.assertIn(text,out['contentKo'])
                        self.assertIn('10명이상',out['contentKo'])

    def test_actual_translation_date_weekday_time_and_cell_changes_fail(self):
        a = recorded()[0]
        for change in (lambda s:s.replace('2026年10月7日','2027年10月7日'),
                       lambda s:s.replace('2026年10月7日','2026年10月8日'),
                       lambda s:s.replace('7日（水）','7日（木）'),
                       lambda s:s.replace('19時00分','18時00分'),
                       lambda s:s.replace('| 2026年10月7日（水） |','| |'),
                       lambda s:s.replace('各回12名','各回13名'),
                       lambda s:s.replace('申込不可','申込可能')):
            with self.subTest(change=change),self.assertRaises(AiJobError):
                validate_translation_fidelity(a['title'],a['translation_input_ko'],
                                             a['translation']['title_ja'],change(a['translation']['content_ja']))
        for classified in (False,True):
            r,e,out,calls = self.replay(0,classified,bad_ja=lambda s:s.replace('19','18'))
            self.assertEqual((r.completed,r.failed),(0,1)); self.assertEqual(len(calls),2)
            self.assertEqual(e[-1][0],'fail_seoul_ai_no_retry'); self.assertFalse(out)

    def test_wrong_hours_fixed_sessions_and_periods_terminate_before_translation(self):
        for classified in (False,True):
            for change in (
                lambda s:s.replace('09:00~17:00','08:00~17:00'),
                lambda s:s.replace('센터 운영시간인 09:00~17:00 안에서 일정을 협의합니다',
                                   '프로그램은 매일 09:00~17:00 진행합니다'),
                lambda s:s.replace('센터 운영시간인 09:00~17:00','센터 관람시간인 09:00~17:00'),
                lambda s:s.replace('센터 운영시간인 09:00~17:00 안에서 일정을 협의합니다',
                                   '신청시간: 09:00~17:00'),
                lambda s:s.replace('[일정 안내]','[일정 안내]\n진행기간: 2027-03-28 ~ 2027-12-31'),
            ):
                r,e,out,calls = self.replay(1,classified,bad_ko=change)
                self.assertEqual((r.failed,r.completed),(1,0));self.assertEqual(len(calls),1)
                self.assertEqual(e[-1][0],'fail_seoul_ai_no_retry');self.assertFalse(out)

    def test_korean_date_table_changes_cannot_borrow_source_numbers(self):
        for classified in (False,True):
            for change in (lambda s:s.replace('19:00~21:00','18:00~21:00'),
                           lambda s:s.replace('19:00~21:00','21:00~19:00'),
                           lambda s:s.replace('2026.10.7.(수)','2026.10.21.(수)'),
                           lambda s:s.replace('2026.10.7.(수)','2027.10.7.(목)'),
                           lambda s:s.replace('| 2026.10.7.(수) |','| |')):
                r,e,out,calls=self.replay(0,classified,bad_ko=change)
                self.assertEqual((r.completed,r.failed),(0,1));self.assertEqual(len(calls),1)
                self.assertEqual(e[-1][0],'fail_seoul_ai_no_retry');self.assertFalse(out)

    def test_existing_candidate_stale_claim_and_unknown_writes_do_not_retry(self):
        for classified in (False,True):
            r,e,out,calls = self.replay(1,classified,skip=True)
            self.assertEqual(len(calls),0);self.assertEqual(len(e),1);self.assertFalse(out)
            for key,value in [('revision','b'*64),('workerId','other-worker')]:
                r,e,out,calls = self.replay(1,classified,claim_change=lambda c:c.update({key:value}))
                self.assertEqual(r.state_unknown,1);self.assertEqual(len(calls),0);self.assertEqual(len(e),1)
            r,e,out,calls = self.replay(1,classified,unknown='completion')
            self.assertEqual(r.state_unknown,1);self.assertEqual(len(calls),2);self.assertFalse(out)
            r,e,out,calls = self.replay(1,classified,unknown='failure',bad_ko=lambda s:s.replace('09:00','08:00'))
            self.assertEqual(r.state_unknown,1);self.assertEqual(len(calls),1);self.assertFalse(out)

    def test_only_current_reviewed_hours_reach_both_inputs(self):
        for classified in (False,True):
            c = context(1,classified)
            f = c['nativeConfirmedFacts']['programFacts'] if classified else c['facts']
            f['description'] = '시설 안내\n시간: 합성센터 운영시간 (10시~18시)\n전화로 일정 협의 후 진행합니다.'
            if classified: c['body'] = '과거 시설 운영시간 09시~17시'
            else: c['observedFacts']['description'] = '과거 센터 운영시간 09시~17시'
            value = json.loads(classification_input(c) if classified else program_input(c))
            evidence = value['facilityHoursEvidence']
            self.assertEqual(evidence[0]['clocks'],[[10,0],[18,0]])
            self.assertNotIn('09시',json.dumps(evidence))
            self.assertEqual(validation_view(f)['facility_hours_evidence'],evidence)


class DateAndRoleCounterexamples(unittest.TestCase):
    def test_same_numbers_remain_bound_to_table_cells_and_period_roles(self):
        ko='[일정 안내]\n| 날짜 | 시간 |\n| --- | --- |\n| 2026.10.7.(수) | 19:00~21:00 |\n| 2026.10.14.(수) | 18:00~20:00 |'
        ja='[日程案内]\n| 日付 | 時間 |\n| --- | --- |\n| 2026年10月7日（水） | 19時00分~21時00分 |\n| 2026年10月14日（水） | 18時00分~20時00分 |'
        validate_translation_fidelity('합성',ko,'合成',ja)
        swapped=ja.replace('19時00分~21時00分','TEMP').replace('18時00分~20時00分','19時00分~21時00分').replace('TEMP','18時00分~20時00分')
        with self.assertRaises(AiJobError):validate_translation_fidelity('합성',ko,'合成',swapped)
        ko='신청기간: 2026.10.1. ~ 2026.10.5.\n진행기간: 2026.10.7. ~ 2026.10.14.'
        ja='申請期間: 2026年10月1日~2026年10月5日\n実施期間: 2026年10月7日~2026年10月14日'
        validate_translation_fidelity('합성',ko,'合成',ja)
        with self.assertRaises(AiJobError):
            validate_translation_fidelity('합성',ko,'合成',ja.replace('申請期間','TEMP').replace('実施期間','申請期間').replace('TEMP','実施期間'))

    def test_source_midnight_and_overnight_table_times_remain_valid(self):
        from ingest.seoul_calendar_sessions import validate_calendar_sessions
        from test_seoul_content import synthetic_facts
        for clocks in ('00:00~01:00','23:00~00:00','23:00~01:00'):
            f=synthetic_facts();f['description']='합성 야간 체험\n진행일시: 10월 18일 '+clocks
            view=validation_view(f)
            table='| 날짜 | 시간 |\n| --- | --- |\n| 2099.10.18. | '+clocks+' |'
            validate_calendar_sessions(table,view)
            a,b=clocks.split('~')
            with self.assertRaises(AiJobError):validate_calendar_sessions(table.replace(clocks,b+'~'+a),view)

    def test_date_forms_year_context_and_valid_calendar(self):
        for ko,ja in [('2026.10.7.(수)','2026年10月7日（水）'),
                      ('2026. 10. 7. (수요일)','2026年10月7日（水曜日）'),
                      ('2028.2.29.(화)','2028年2月29日（火）'),
                      ('10월 7일(수)','10月7日（水）'),
                      ('2026-10-07T10:00:00+00:00','2026年10月7日19時00分')]:
            _validate_cell(ko,ja)
        _validate_cell("'26.10.7.(수)/10.14.(수)",'2026年10月7日（水）/10月14日（水）',known_years=frozenset({2026}))
        for known in (frozenset(),frozenset({1926,2026}),frozenset({2027})):
            with self.assertRaises(AiJobError): _dates_and_times("'26.10.7.(수)",known_years=known)
        for text in ('2026.2.30.(월)','2026.13.7.','2026.10.7.(목)','2026-10-07(목)','2026년 10월 7일(목)'):
            with self.assertRaises(AiJobError):_dates_and_times(text)

    def test_numbers_and_opaque_identifiers_are_not_dates(self):
        for text in ('1회차 4개','3.14','010-2026-1007','v2026.10.7','버전 2026.10.7','2026.10.7.2'):
            self.assertEqual(_dates_and_times(text),[],text)
        _validate_cell('2회차','第2回')
        with self.assertRaises(AiJobError):_validate_cell('2회차','第3回')
        for text in ('3.14','버전 2026.10.7'):
            _validate_cell(text,text)
            with self.assertRaises(AiJobError):_validate_cell(text,text.replace('2','9').replace('3','8'))

    def test_facility_role_does_not_accept_receipt_viewing_or_unknown_hours(self):
        for source in ('시간: 09시~17시','프로그램 운영시간: 09시~17시',
                       '센터 접수시간: 09시~17시','센터 관람시간: 09시~17시',
                       '센터 운영시간: 별도 문의','센터 운영시간: 09시~17시 / 18시~20시'):
            self.assertEqual(facility_hours_evidence(source),[])
        a = facility_hours_evidence('센터는 오전 9시~오후 5시까지 운영합니다.')
        b = facility_hours_evidence('센터 운영시간: 09:00~17:00')
        self.assertEqual(a[0]['clocks'],b[0]['clocks'])


if __name__ == '__main__':
    unittest.main()
