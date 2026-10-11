"""Synthetic public-body continuity; socket connections are forbidden."""
import copy
import re
import socket
import unittest
from datetime import datetime
from unittest.mock import patch
from ingest.ai_errors import AiJobError
from ingest.program_ai import program_input
from ingest.seoul_content import assemble_seoul_body, public_date, reviewed_sections, reception_status
from test_program_ai import context


def synthetic_facts():
    f = copy.deepcopy(context()['facts'])
    f.update(target_raw='성인', conditions=['보호자 동반 필수', '재료비는 환불되지 않습니다.'],
             activity_evidence=['서울 합성 체험관'], residence_evidence=[],
             fee_amounts=['수강료: 10,000원', '재료비: 2,000원'])
    f['description']='공예 작품을 만드는 합성 문화체험입니다.\n정원: 20명\n진행 일정\n1회차: 10월 18일 10:00~12:00 공예\n2회차: 10월 25일 10:00~12:00 완성'
    for key,value in zip(f['periods'], ['2099-10-01','2099-10-10','2099-10-18','2099-10-25']):
        f['periods'][key]={'value':value,'precision':'day','status':'ok','raw':value}
    return f


SUMMARY='[한 줄 요약]\n공예 작품을 만드는 체험입니다.\n[대상]\n성인\n[일정 안내]\n진행기간: 2099-10-18 ~ 2099-10-25\n[주요 내용]\n작품을 만듭니다.\n수강료는 10,000원이며, 재료비 2,000원이 별도로 있습니다.\n[신청 방법]\n예약 후 문의는 02-1234-5678로 연락해 주세요.'


def fake_japanese(body):
    """Explicit test translation, no AI quality claim; preserve row structure."""
    replacements={'한 줄 요약':'要約','일정 안내':'日程案内','주요 내용':'主な内容','신청 방법':'申請方法',
        '신청기간':'申請期間','진행기간':'実施期間','신청 기간':'申請期間','운영 기간':'実施期間',
        '개최 기간':'開催期間','신청 마감':'申請締切','정해진 마감 없음':'締切なし',
        '수강료':'受講料','재료비':'材料費','입장료':'入場料','비용':'費用','정원':'定員','원':'ウォン','명':'名','세':'歳','시간':'時間',
        '회차':'回','회':'回','년':'年','월':'月','일':'日','필수':'必須','불가':'不可','금지':'禁止',
        '무료':'無料','대상':'対象','진행 방식':'実施方式','접수 상태':'受付状況','참가 조건':'参加条件'}
    for source,target in replacements.items():
        body=body.replace(source,target)
    return re.sub(r'[가-힣]+', '案内', body)


class SeoulContentTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden'))
        guard.start();self.addCleanup(guard.stop)
    def test_reported_appendix_status_iso_and_fee_failure(self):
        f=synthetic_facts();body=assemble_seoul_body(SUMMARY,f)
        self.assertNotIn('확인한 참여 안내',body)
        self.assertNotIn('수강료는',body)
        self.assertEqual(body.count('10,000원'),1);self.assertEqual(body.count('2,000원'),1)
        method=body.split('[신청 방법]')[1]
        self.assertIn('02-1234-5678',method);self.assertNotIn('진행기간',method)
        self.assertIn('보호자 동반 필수',body);self.assertIn('환불되지',body)
        self.assertIn('20명',body);self.assertIn('2회차',body)
        self.assertNotIn('거주 제한 없음',body);self.assertNotIn('+09:00',body)
        self.assertEqual(body,assemble_seoul_body(body,f))
    def test_real_period_conflict_and_cost_roles_blocked(self):
        for bad in [SUMMARY.replace('2099-10-25','2099-10-26'),
                    SUMMARY.replace('수강료는 10,000원이며, 재료비 2,000원','수강료는 2,000원이며, 재료비 10,000원'),
                    SUMMARY.replace('10,000원','10,000엔')]:
            with self.subTest(bad=bad),self.assertRaises(AiJobError):assemble_seoul_body(bad,synthetic_facts())
    def test_year_omission_and_promotional_numbers(self):
        f=synthetic_facts();f['conditions']+=['업무 효율 200%를 높입니다.']
        body=assemble_seoul_body(SUMMARY.replace('2099-10-18 ~ 2099-10-25','10월 18일 ~ 10월 25일'),f)
        self.assertNotIn('200%',body)
        self.assertIn('2099-10-18',body)
    def test_qualified_cost_sentences_are_not_deleted(self):
        for text in ['재료비 2,000원은 환불되지 않습니다.',
                     '수강료는 10,000원이며 보호자 동반이 필요합니다.',
                     '수강료는 1인당 10,000원입니다.',
                     '수강료는 10,000원이며 교재가 포함됩니다.',
                     '재료비는 현금으로만 납부합니다.']:
            body=assemble_seoul_body(SUMMARY.replace('수강료는 10,000원이며, 재료비 2,000원이 별도로 있습니다.',text),synthetic_facts())
            self.assertIn(text,body)
    def test_timezone_precision_and_actual_status(self):
        self.assertEqual(public_date({'value':'2099-10-01','precision':'day'}),'2099-10-01')
        self.assertEqual(public_date({'value':'2099-10-01T01:02:03+00:00','precision':'second'}),'2099-10-01 10:02:03')
        f=synthetic_facts()
        for day,status in [('2099-09-30','신청 시작 전'),('2099-10-01','접수 중'),('2099-10-11','접수 마감'),('2099-10-26','운영 종료')]:
            self.assertEqual(reception_status(f,datetime.fromisoformat(day+'T12:00:00+09:00')),status)
        f['source_status']='reservation_closed'
        self.assertEqual(reception_status(f,datetime.fromisoformat('2099-10-02T12:00:00+09:00')),'예약 마감')
    def test_current_operator_data_only_in_input(self):
        c=context();c['facts']=synthetic_facts();c['observedFacts']['description']='OLD_PRIVATE_SENTINEL'
        body=program_input(c)
        self.assertIn('20명',body);self.assertIn('sessionEvidence',body)
        self.assertNotIn('OLD_PRIVATE_SENTINEL',body)

    def test_whole_body_timezone_dates_and_second_precision_preserved(self):
        f=synthetic_facts()
        for key,day in [('RCPTBGNDT','01'),('RCPTENDDT','10')]:
            f['periods'][key]={'raw':'synthetic','value':f'2099-10-{day}T01:02:03+00:00',
                'precision':'second','status':'ok'}
        before=copy.deepcopy(f)
        body=assemble_seoul_body(SUMMARY,f)
        self.assertIn('2099-10-01 10:02:03 ~ 2099-10-10 10:02:03',body)
        self.assertNotIn('+00:00',body);self.assertEqual(f,before)
    def test_table_rows_dates_activities_survive_and_swapped_sessions_fail(self):
        f=synthetic_facts()
        table='| 회차 | 일시 | 활동 |\n| --- | --- | --- |\n| 1회차 | 10월 18일 10:00~12:00 | 공예 |\n| 2회차 | 10월 25일 10:00~12:00 | 완성 |'
        f['description']='합성 문화 체험\n정원: 20명\n'+table
        body=assemble_seoul_body(SUMMARY,f)
        self.assertIn(table,body);self.assertEqual(body.count('| 1회차 |'),1)
        with self.assertRaises(AiJobError):
            assemble_seoul_body(SUMMARY.replace('진행기간: 2099-10-18 ~ 2099-10-25',table.replace('1회차 | 10월 18일','1회차 | 10월 25일')),f)
    def test_supported_api_table_is_current_description_not_html(self):
        from ingest.connectors.seoul_reservation import parse_body
        source='<p>합성 문화체험</p><table><tr><th>회차</th><th>일시</th><th>활동</th></tr><tr><td>1회차</td><td>10월 18일 10:00~12:00</td><td>공예</td></tr></table>'
        parsed=parse_body(source)
        self.assertIn('| 회차 | 일시 | 활동 |',parsed['program_text'])
        self.assertIn('| --- | --- | --- |',parsed['program_text'])
        self.assertNotIn('<table>',parsed['program_text'])
        self.assertEqual(parsed['tables'][0][1][2]['text'],'공예')
    def test_output_instruction_fails_but_json_class_stays(self):
        with self.assertRaises(AiJobError):assemble_seoul_body(SUMMARY+'\nJSON 출력: content_ko만 반환합니다.',synthetic_facts())
        self.assertIn('JSON 작성 교육',assemble_seoul_body(SUMMARY.replace('작품을 만듭니다.','JSON 작성 교육을 합니다.'),synthetic_facts()))

    def test_reclassified_current_application_precision_not_raw_iso(self):
        from test_reclassification_ai import context as classified_context
        from ingest.reclassification_ai import protected_sections
        c=classified_context('program','seoul_reservation')
        c['nativeConfirmedFacts']['programFacts']=synthetic_facts()
        c['filters']['application']['value'].update(
            start={'value':'2099-10-01T01:00:00+00:00','precision':'minute'},
            end={'value':'2099-10-10T08:00:00+00:00','precision':'minute'})
        sections=protected_sections(c)
        self.assertIn('2099-10-01 10:00 ~ 2099-10-10 17:00',sections['[일정 안내]'])
        self.assertIn('진행기간:',sections['[일정 안내]'])
        self.assertNotIn('+00:00',sections['[일정 안내]'])
        self.assertNotIn('신청기간:',sections['[신청 방법]'])
        self.assertIn('온라인',sections['[주요 내용]'])
        self.assertEqual(c['nativeConfirmedFacts']['programFacts']['delivery_mode'],'offline')
        application=c['filters']['application']['value']
        overrides={'application':[{'status':'ok','endpoints':[application['start'],application['end']]}]}
        source=SUMMARY.replace('진행기간:', '신청기간: 2099-10-01 10:00 ~ 2099-10-10 17:00\n진행기간:')
        body=assemble_seoul_body(source,c['nativeConfirmedFacts']['programFacts'],reviewed=sections,periods=overrides)
        self.assertIn('2099-10-10 17:00',body)
        with self.assertRaises(AiJobError):
            assemble_seoul_body(source.replace('2099-10-10 17:00','2099-10-11 17:00'),
                c['nativeConfirmedFacts']['programFacts'],reviewed=sections,periods=overrides)


if __name__=='__main__':unittest.main()
