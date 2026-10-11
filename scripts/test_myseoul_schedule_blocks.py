"""Recorded public summary regression; synthetic identities, offline transports only."""
import copy
import json
import socket
import unittest
from unittest.mock import Mock, patch

from ingest.ai_errors import AiJobError
from ingest.myseoul_ai import fact_sections, myseoul_input, process_myseoul_job
from ingest.myseoul_content import schedule_lines, optional_period_section, validate_summary_period
from ingest.myseoul_ai_support import schedule_values
from ingest.program_ai import ProgramAIAdapter
from test_myseoul_ai import context

# Exact already completed Pro response. No live identity, credential or contact data.
RECORDED_SUMMARY = '''[한 줄 요약]
한국 기업 취업을 준비하는 외국인 유학생 및 구직자를 위한 3회 실습 중심 AI·OA 사무역량 강화교육입니다.

[대상]
한국 기업 취업을 희망하는 외국인 유학생 및 구직자 25명.

[기간·상태]
신청 기간: 2026년 10월 8일 00:00~10월 20일 23:50.
합격자 발표: 10월 21일 개별 안내.
교육 운영 범위: 2026년 10월 27일 13:00~11월 3일 17:00. 실제 수업은 10월 27일, 10월 30일, 11월 3일 총 3회이며, 회차별 시간은 별도로 명시되어 있지 않습니다.

[주요 내용]
서울글로벌센터 4층 404호(서울특별시 종로구 종로 38)에서 사무 현장에 활용할 수 있는 생성형 AI, 엑셀, 협업 도구를 실습합니다.
• 10월 27일: AI 기반 업무 자동화 및 스마트 오피스 기초
• 10월 30일: 실무 엑셀 핵심 스킬 및 AI 연계 비즈니스 문서 작성
• 11월 3일: 스마트 협업 툴 기반 프로젝트 워크플로우

[신청 방법]
안내된 QR 또는 신청 링크를 통해 구글폼을 제출하세요.
https://forms.gle/Hcn96yNTzFfKQ83TA'''

SOURCE_SCHEDULE = '''단 3번의 실습 중심 수업으로 똑똑하게 일하는 스마트 오피스 인재로 거듭날 기회!
📅 교육 일정
▪️ 장소: 서울글로벌센터 4층, 404호 (서울특별시 종로구 종로 38)
▪️ 10월 27일(화): AI 기반 업무 자동화 & 스마트 오피스 기초
▪️ 10월 30일(금): 실무 엑셀 핵심 스킬 & AI 연계 비즈니스 문서 작성
▪️ 11월 3일(화): 스마트 협업 툴 기반 프로젝트 워크플로우
📝 신청 안내
▪️ 신청 기간: 10월 8일(목) ~ 10월 20일(화)
▪️ 합격자 발표: 10월 21일(수) 개별 안내'''


def recorded_context():
    c = context()
    f = c['facts']
    f.update(description=SOURCE_SCHEDULE, session_evidence=[], meeting_evidence=[],
             target='한국 기업 취업을 희망하는 외국인 유학생 및 구직자',
             capacity_raw=['25명'], capacity_value=None, venue='', conditions=[], age=[], companion=[], language=[],
             fees=[{'component':'tuition','evidence':['무료']}],
             application_methods=['기타 (구글폼)'], application_links=['https://forms.gle/Hcn96yNTzFfKQ83TA'])
    f['periods'] = {role:[{'status':'ok','endpoints':[
        {'value':start,'precision':'minute'}, {'value':end,'precision':'minute'}]}]
        for role,start,end in [('application','2026-10-08T00:00:00+09:00','2026-10-20T23:50:00+09:00'),
                               ('operation','2026-10-27T13:00:00+09:00','2026-11-03T17:00:00+09:00')]}
    c['observedFacts'] = copy.deepcopy(f)
    return c


def reviewed_detail(c):
    # Private server confirmation is separate from unchanged public facts.
    return dict(id=c['sourceItemId'],revision=c['revision'],schema=c['schema'],profile=c['profile'],
        factsVersion=c['factsVersion'],status='resolved',aiStatus='claimed',
        source=dict(name=c['source'],title=c['title'],url=c['facts']['official_url']),
        facts=copy.deepcopy(c['facts']),observedFacts=copy.deepcopy(c['observedFacts']),
        result=dict(scope='included',quality='sufficient',public_category='program',application='open',decision='in_scope',reasons=[]))


# Handwritten fake translation for code/JSON/candidate tests, not model quality evidence.
FAKE_JA = '''[要約]
外国人留学生と求職者を対象とした全3回のAI・OA研修です。
[対象]
韓国企業への就職を希望する外国人留学生と求職者、25名。
[期間・状況]
韓国時間（UTC+09:00）
申請期間: 2026年10月8日00:00～2026年10月20日23:50
実施期間: 2026年10月27日13:00～2026年11月3日17:00
実施日程: 10月27日(火)、10月30日(金)、11月3日(火)、全3回
合格者発表: 10月21日(水)、個別案内
[主な内容]
ソウル特別市、チョンノ区、鍾路38、ソウルグローバルセンター4階404号室でAIとエクセル、協働ツールを学びます。
受講料: 無料
[申請方法]
Googleフォーム https://forms.gle/Hcn96yNTzFfKQ83TA'''


class ScheduleBlockTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_recorded_response_accepts_heading_with_separate_date_bullets(self):
        c = recorded_context()
        before = copy.deepcopy(c)
        validate_summary_period(optional_period_section(RECORDED_SUMMARY), fact_sections(c['facts'])['[일정 안내]'], c['facts'])
        self.assertEqual(c, before)
        evidence = schedule_lines(c['facts'])
        self.assertEqual(schedule_values('\n'.join(evidence))['dates'], {(10,27),(10,30),(11,3)})
        self.assertEqual(schedule_values('\n'.join(evidence))['counts'], {3})
        self.assertNotIn('10월 21일', '\n'.join(evidence))

    def test_actual_period_session_and_count_conflicts_still_reject(self):
        c = recorded_context()
        period = optional_period_section(RECORDED_SUMMARY)
        for changed in (
            period.replace('2026년 10월 27일', '2027년 10월 27일'),
            period.replace('13:00', '14:00'),
            period.replace('11월 3일 17:00', '11월 4일 17:00'),
            period.replace('10월 30일,', '10월 31일,'),
            period.replace('총 3회', '총 4회'),
            period.replace('실제 수업은', '실제 수업은 2027년'),
        ):
            with self.subTest(changed=changed), self.assertRaises(AiJobError):
                validate_summary_period(changed, fact_sections(c['facts'])['[일정 안내]'], c['facts'])

    def test_date_list_scope_and_count_word_counterexamples(self):
        f = recorded_context()['facts']
        f['description'] = ('3번 출구, 신청은 최대 3번까지 가능합니다.\n'
            '[교육 일정]\n장소: 교육실\n• 10월 27일(화): 교육\n• 10월 30일(금): 교육\n'
            '문의\n11월 3일: 상담 창구 운영\n신청 안내\n10월 20일: 접수 마감')
        lines = schedule_lines(f)
        self.assertEqual(schedule_values('\n'.join(lines))['dates'],{(10,27),(10,30)})
        self.assertEqual(schedule_values('\n'.join(lines))['counts'],set())
        for text in ['단 3번의 실습 중심 수업', '총 2번의 교육', '3번 수업']:
            with self.subTest(text=text):
                self.assertTrue(schedule_values(text)['counts'])
        self.assertEqual(schedule_values('3번 출구, 최대 3번 신청, 3번 방문')['counts'],set())

    def test_explicit_session_evidence_wins_and_iso_bullets_remain_dates(self):
        f = recorded_context()['facts']
        f['session_evidence'] = ['10월 28일 교육 일정']
        self.assertEqual(schedule_lines(f),f['session_evidence'])
        f['session_evidence'] = []
        f['description'] = '교육 일정\n- 2026-10-27: 수업\n- 2026-10-30: 수업'
        self.assertEqual(schedule_values('\n'.join(schedule_lines(f)))['dates'],{(10,27),(10,30)})
        validate_summary_period('실제 수업: 2026-10-27, 2026-10-30',fact_sections(f)['[일정 안내]'],f)

    def test_same_number_bag_cannot_hide_date_weekday_or_clock_swap(self):
        f = recorded_context()['facts']
        f['description'] = ('교육 일정\n10월 27일(화) 13:00~14:00\n10월 30일(금) 15:00~16:00')
        canonical = fact_sections(f)['[일정 안내]']
        good = '실제 수업: 10월 27일(화) 13:00~14:00, 10월 30일(금) 15:00~16:00'
        validate_summary_period(good,canonical,f)
        for bad in ('실제 수업: 10월 27일(금) 13:00~14:00, 10월 30일(화) 15:00~16:00',
                    '실제 수업: 10월 27일(화) 15:00~16:00, 10월 30일(금) 13:00~14:00'):
            with self.subTest(bad=bad), self.assertRaises(AiJobError):
                validate_summary_period(bad,canonical,f)

    def test_iso_filter_offset_is_not_an_extra_clock_and_instant_is_preserved(self):
        f = recorded_context()['facts']
        summary = '신청 기간: 2026년 10월 8일 00:00~10월 20일 23:50'
        for canonical in (
            '신청기간: 2026-10-08T00:00:00+09:00 ~ 2026-10-20T23:50:00+09:00',
            '신청기간: 2026-10-07T15:00:00Z ~ 2026-10-20T14:50:00Z'):
            with self.subTest(canonical=canonical):
                validate_summary_period(summary,canonical,f)
                with self.assertRaises(AiJobError):
                    validate_summary_period(summary.replace('00:00','01:00'),canonical,f)

    def test_conflict_never_reaches_fake_translation_or_finish(self):
        c = recorded_context()
        before = copy.deepcopy(c)
        names = []
        def rpc(name,args):
            names.append(name)
            if name == 'claim_myseoul_program_ai': return [copy.deepcopy(c)]
            if name == 'admin_myseoul_program_detail': return reviewed_detail(c)
            if name == 'fail_myseoul_program_ai':
                self.assertEqual(args['p_error_code'],'ai_schema_error')
                return 'failed'
            raise AssertionError('candidate completion forbidden')
        for conflict in ['10월 31일,','2027년 10월 30일,']:
            with self.subTest(conflict=conflict):
                names.clear()
                ko = Mock(return_value=(RECORDED_SUMMARY.replace('10월 30일,',conflict),'success','fake-model'))
                ja = Mock()
                result = process_myseoul_job(ProgramAIAdapter(rpc),source_item_id=c['sourceItemId'],revision=c['revision'],
                    worker_id=c['workerId'],summarize_ko=ko,translate_ja=ja)
                self.assertEqual((result.completed,result.failed),(0,1))
                self.assertEqual(names[-1],'fail_myseoul_program_ai')
                ja.assert_not_called()
                self.assertEqual(c,before)

    def test_conflicting_date_in_major_content_is_also_rejected(self):
        from ingest.myseoul_ai import generate_myseoul_output
        c = recorded_context()
        for changed in ('10월 31일:', '2027년 10월 30일:'):
            ko = Mock(return_value=(RECORDED_SUMMARY.replace('10월 30일:',changed),'success','fake-model'))
            ja = Mock()
            with self.subTest(changed=changed), self.assertRaises(AiJobError):
                generate_myseoul_output(c,summarize_ko=ko,translate_ja=ja)
            ja.assert_not_called()

    def test_reclassified_path_uses_same_recorded_schedule_and_current_filters(self):
        from ingest.reclassification_ai import process_reclassified_job,protected_information
        from test_reclassification_ai import context as classified_context
        c = classified_context('program')
        native = recorded_context()['facts']
        c['nativeConfirmedFacts']['programFacts'] = native
        c['facts'].update(delivery='offline',scope='unknown',evidence='',deadlineOn='2026-10-20')
        c['filters']['delivery'] = {'status':'known','value':'onsite'}
        c['filters']['location'] = {'status':'known','value':{'scope':'specific','venues':[
            {'province':'11','district':None,'facility':'','address':''}]}}
        c['filters']['application']['value'].update(start=copy.deepcopy(native['periods']['application'][0]['endpoints'][0]),
            end=copy.deepcopy(native['periods']['application'][0]['endpoints'][1]))
        before = copy.deepcopy(c)
        calls = []
        output = {}
        def rpc(name,args):
            calls.append(name)
            if name == 'claim_reclassified_content_ai': return copy.deepcopy(c)
            if name == 'finish_reclassified_content_ai':
                self.assertEqual(args['p_classification_version'],c['classificationVersion'])
                self.assertEqual(args['p_revision'],c['revision'])
                output.update(args['p_output'])
                return {'outcome':'inserted','candidateId':c['sourceItemId']}
            return {'status':'active'}
        ko = Mock(return_value=(RECORDED_SUMMARY,'success','fake-model'))
        ja = Mock(return_value=('合成研修',FAKE_JA,'success','fake-model'))
        result = process_reclassified_job(ProgramAIAdapter(rpc),source_item_id=c['sourceItemId'],revision=c['revision'],
            classification_version=c['classificationVersion'],worker_id=c['workerId'],summarize_ko=ko,translate_ja=ja)
        self.assertEqual(result.completed,1)
        self.assertEqual(c,before)
        self.assertEqual(calls,['claim_reclassified_content_ai','finish_reclassified_content_ai'])
        self.assertEqual(json.loads(ko.call_args.args[0])['currentFilters'],c['filters'])
        self.assertIn(protected_information(c),ja.call_args.args[1])
        self.assertIn('10월 30일',output['contentKo'])
        calls.clear()
        ko.return_value = (RECORDED_SUMMARY.replace('10월 30일:', '10월 31일:'),'success','fake-model')
        ja.reset_mock()
        result = process_reclassified_job(ProgramAIAdapter(rpc),source_item_id=c['sourceItemId'],revision=c['revision'],
            classification_version=c['classificationVersion'],worker_id=c['workerId'],summarize_ko=ko,translate_ja=ja)
        self.assertEqual(result.completed,0)
        self.assertNotIn('finish_reclassified_content_ai',calls)
        ja.assert_not_called()

    def test_summary_and_fake_translation_json_contracts_remain_exact(self):
        from ingest.ai_claude import validate_summary_payload,validate_translation_payload
        summary = {'content_ko':RECORDED_SUMMARY,'facts':{k:'' for k in
            ('audience','geo_age_income','amount_period_deadline','how_to_apply')}}
        self.assertEqual(validate_summary_payload(summary),RECORDED_SUMMARY.replace('[기간·상태]', '[일정 안내]'))
        translation = {'title_ja':'合成研修','content_ja':FAKE_JA}
        self.assertEqual(validate_translation_payload(translation),('合成研修',FAKE_JA.replace('[期間・状況]', '[日程案内]')))
        with self.assertRaises(AiJobError):
            validate_translation_payload({**translation,'explanation':'extra field forbidden'})

    def test_recorded_response_reaches_fake_candidate_without_changing_context(self):
        c = recorded_context()
        before = copy.deepcopy(c)
        calls = []
        candidate = {}
        def rpc(name,args):
            calls.append(name)
            if name == 'claim_myseoul_program_ai':
                self.assertEqual(args['p_source_item_id'], c['sourceItemId'])
                self.assertEqual(args['p_revision'], c['revision'])
                return [copy.deepcopy(c)]
            if name == 'admin_myseoul_program_detail':
                self.assertEqual(args['p_id'],c['sourceItemId'])
                return reviewed_detail(c)
            if name == 'finish_myseoul_program_ai':
                for key,value in {'p_job_id':c['jobId'],'p_revision':c['revision'],
                    'p_facts_version':c['factsVersion'],'p_worker_id':c['workerId'],
                    'p_claimed_at':c['claimedAt'],'p_lease_until':c['leaseUntil']}.items():
                    self.assertEqual(args[key],value)
                candidate.update(args['p_output'])
                return {'outcome':'inserted','candidateId':c['sourceItemId']}
            if name == 'fail_myseoul_program_ai': return 'failed'
            raise AssertionError('unexpected fake RPC')
        ko = Mock(return_value=(RECORDED_SUMMARY,'success','fake-model'))
        ja = Mock(return_value=('合成研修',FAKE_JA,'success','fake-model'))
        result = process_myseoul_job(ProgramAIAdapter(rpc),source_item_id=c['sourceItemId'],revision=c['revision'],
            worker_id=c['workerId'],summarize_ko=ko,translate_ja=ja)
        self.assertEqual(result.completed,1)
        self.assertEqual(c,before)
        self.assertEqual(calls,['claim_myseoul_program_ai','admin_myseoul_program_detail','finish_myseoul_program_ai'])
        self.assertEqual((ko.call_count,ja.call_count),(1,1))
        self.assertEqual(json.loads(ko.call_args.args[0])['sessionEvidence'],schedule_lines(c['facts']))
        self.assertEqual(ja.call_args.args[1],candidate['contentKo'])
        for expected in ['10월 27일','10월 30일','11월 3일','25명','수강료: 무료']:
            self.assertIn(expected,candidate['contentKo'])


if __name__ == '__main__':
    unittest.main()
