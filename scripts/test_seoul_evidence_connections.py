"""Synthetic local evidence examples; no DB, provider, external content or keys."""
import copy
import json
import socket
import sys
import unittest
from unittest.mock import patch

from ingest.connectors.seoul_reservation import normalize_seoul_item
from ingest.program_scope import extract_program_facts, assess_seoul_program
from ingest.program_db import program_rpc_item
from ingest.content_filters import extract_filter_facts, field
from ingest.seoul_evidence import activity_locations, activity_text, period_days
from test_seoul_reservation import row, NOW


def packets():
    variants=[
        ('emoji','공예 문화 체험을 진행합니다.\n✅장소 : 서울시 도봉구 합성공방 (도봉구 마들로 932)',{}),
        ('spaced','* 내 용\n- 생태놀이: 열매를 찾아보자\n* 장 소: 합성생태공원 교육실',{}),
        ('table','<p>주요활동: 숲 체험</p><table><tr><th>활동</th><th>장소</th></tr><tr><td>열매 관찰</td><td>서울 도봉구 합성공원</td></tr></table>',{}),
        ('end_year','생태놀이와 열매 찾기\n운영기간: 2026.10.03.~11.03.\n장소: 서울 도봉구 합성공원',{}),
        ('actual_conflict','생태놀이와 열매 찾기\n운영기간: 2026.10.03.~11.26.\n장소: 서울 도봉구 합성공원',{}),
        ('missing','',{}),
        ('meeting','공예 문화 체험을 진행합니다.\n만나는 장소: 서울 도봉구 버스정류장',{}),
        ('ambiguous','주요활동: 생태놀이와 주민 교류 활동을 진행합니다.\n장소: 서울 도봉구 합성공원',{}),
        ('negative_venue','문화 체험을 진행합니다.\n장소: 변경 전 서울 도봉구 합성공원',{}),
    ]
    # Shape replicas of the nine restored records, not their operating rows.
    for i in range(9):
        activity=['열매를 찾아보자','나무열매 키링 만들기','생태놀이를 해보자','숲 명상과 생태해설','가을액자 만들기'][i%5]
        place='만나는 장소: 합성생태공원 교육장 앞' if i<5 else '* 장 소: 합성생태공원 교육실'
        variants.append(('restored_'+str(i),'* 내 용\n- '+activity+'\n'+place+'\n[사진 사용 및 개인정보 수집 안내]\n관련 자료는 기관 내부 자료 작성에 사용합니다.',{}))
    return [{'name':name,'item':program_rpc_item(normalize_seoul_item(row(sid='SYNTH_EVIDENCE_'+name,
                DTLCONT=body,PLACENM='합성생태공원',AREANM='도봉구',**extra)))} for name,body,extra in variants]


class EvidenceConnectionsTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('external network forbidden'))
        guard.start();self.addCleanup(guard.stop)

    def packet(self,body,**kw):
        rec=normalize_seoul_item(row(DTLCONT=body,**kw))
        return rec,program_rpc_item(rec)

    def test_label_variants_share_facts_and_filter_evidence(self):
        for line in ['✅장소: 합성생태공원 교육실','* 장 소: 합성생태공원 교육실','① 교육 장 소 : 합성생태공원 교육실','[진행 장소] 합성생태공원 교육실','□ 교육 장소\n합성생태공원 교육실']:
            with self.subTest(line=line):
                rec,p=self.packet('생태놀이와 열매 찾기를 진행합니다.\n'+line,PLACENM='합성생태공원',AREANM='도봉구')
                self.assertEqual((p['program_facts']['delivery_mode'],p['program_facts']['activity_region']),('offline','capital'))
                self.assertEqual(p['filterFacts']['data']['delivery'],field('onsite'))
                self.assertEqual(p['filterFacts']['data']['location']['value']['venues'][0]['district'],'도봉구')
                self.assertEqual(p['filterFacts']['data']['topic'],field('culture_experience'))

    def test_provider_alone_meeting_and_directions_never_become_venue(self):
        for label in ['기관 주소: 서울 도봉구 합성공원','집결장소: 서울 도봉구 공원 입구','만나는 장소: 서울 도봉구 버스정류장','장소: 미정','오시는 길: 서울 도봉구 합성공원','장소: 1번 출구에서 하차합니다.','장소: 서울 도봉구 합성공원이 아님','장소: 변경 전 서울 도봉구 합성공원']:
            _,p=self.packet('문화 체험을 진행합니다.\n'+label,PLACENM='합성공원',AREANM='도봉구')
            self.assertEqual(p['program_facts']['delivery_mode'],'unknown')
            self.assertEqual(p['filterFacts']['data']['location']['status'],'unknown')

    def test_one_matching_provider_does_not_prove_two_venues(self):
        _,p=self.packet('문화 체험을 진행합니다.\n장소: 합성생태공원\n장소: 이름만 있는 다른 시설',PLACENM='합성생태공원',AREANM='도봉구')
        self.assertEqual(p['program_facts']['activity_region'],'unknown')
        self.assertEqual(p['filterFacts']['data']['location']['status'],'unknown')
        _,p=self.packet('문화 체험을 진행합니다.\n장소: 신합성생태공원',PLACENM='합성생태공원',AREANM='도봉구')
        self.assertEqual(p['program_facts']['activity_region'],'unknown')

    def test_structured_table_uses_the_venue_column(self):
        html='<p>주요활동: 숲 체험</p><table><tr><td>제목 / 소요시간</td><td>활동 내용</td><td>장소</td></tr><tr><td>자연 속 나를 감각하기 (10분)</td><td>깊은 호흡과 걷기</td><td>서울 도봉구 합성공원 작품 앞</td></tr></table>'
        _,p=self.packet(html)
        self.assertEqual(p['program_facts']['activity_evidence'],('서울 도봉구 합성공원 작품 앞',))
        self.assertEqual(p['filterFacts']['data']['location']['value']['venues'][0]['district'],'도봉구')
        flat='제목 / 소요시간\n활동 내용\n장소\n자연 속 나를 감각하기 (10분)\n깊은 호흡과 걷기\n합성 작품 앞'
        self.assertEqual(activity_locations(flat),())

    def test_unsupported_table_spans_and_empty_location_not_invented(self):
        cell=lambda t,**kw:dict(text=t,rowspan=1,colspan=1,**kw)
        table=[[cell('내용'),cell('장소')],[cell('숲 체험'),cell('')]]
        self.assertEqual(activity_locations('',[table]),())
        table[1][1]=dict(text='서울 도봉구 합성공원',rowspan=2,colspan=1)
        self.assertEqual(activity_locations('',[table]),())
        inner=[[cell('내용'),cell('장소')],[cell('숲 체험'),cell('서울 도봉구 합성공원')]]
        outer=[[cell('안내'),cell('장소')],[cell('중첩 표',nested_tables=[1]),cell('')]]
        self.assertEqual(activity_locations('',[outer,inner]),())

    def test_main_purpose_and_unique_conditions_are_separate(self):
        body='* 내 용\n- 나무열매 키링 만들기\n* 대상: 성인\n개인 신청불가. 학교만 신청 가능\n[사진 사용 및 개인정보 수집 안내]\n관련 자료는 기관 내부 자료 작성에 사용합니다.'
        _,p=self.packet(body)
        self.assertEqual(p['program_facts']['content_kind'],'program')
        self.assertEqual(p['filterFacts']['data']['topic'],field('culture_experience'))
        self.assertIn('개인 신청불가',p['program_facts']['description'])
        self.assertEqual(p['program_facts']['application_actor'],'institution')
        self.assertNotIn('기관 내부 자료',activity_text(body))

    def test_facility_common_guide_is_not_primary_activity(self):
        _,p=self.packet('시설 안내\n공예 체험실과 곤충 전시실, 일반 관람 안내입니다.')
        self.assertEqual(p['program_facts']['content_kind'],'unknown')
        self.assertEqual(p['filterFacts']['data']['topic']['status'],'unknown')

    def test_curriculum_activities_and_privacy_education_are_not_boilerplate(self):
        _,p=self.packet('* 내 용\n1주차. 풀씨와 열매의 여행\n2주차. 풀벌레 음악회\n3주차. 가을 열매 운동회\n[사진 사용 및 개인정보 이용 동의 안내]')
        self.assertEqual(p['program_facts']['content_kind'],'program')
        self.assertEqual(p['filterFacts']['data']['topic'],field('culture_experience'))
        _,p=self.packet('주요 활동: 생활 안전 교육과 개인정보 보호 교육을 진행합니다.')
        self.assertEqual(p['filterFacts']['data']['topic'],field('daily_safety'))

    def test_main_activity_after_facility_guide_and_unrelated_unknown_metadata(self):
        for body in ['시설 안내\n곤충 전시실을 소개합니다.\n프로그램 내용: 생태놀이를 진행합니다.',
                     '생태놀이를 진행합니다.\n준비물: 미정\n운영기간: 미정']:
            _,p=self.packet(body)
            self.assertEqual(p['program_facts']['content_kind'],'program')
            self.assertEqual(p['filterFacts']['data']['topic'],field('culture_experience'))

    def test_ambiguous_negative_and_policy_remain_review(self):
        for body in ['주요 활동: 생태놀이와 주민 교류 활동을 함께 진행합니다.','주요 활동: 생태놀이는 하지 않습니다.','주요 활동: 생태놀이를 진행하지 않습니다.','주요 활동: 문화 체험을 진행하지 않습니다.','주요 활동: 확인 필요\n생태놀이를 진행합니다.']:
            _,p=self.packet(body)
            self.assertEqual(p['filterFacts']['data']['topic']['status'],'unknown')
        rec,_=self.packet('주요 활동: 가방 만들기와 주거정책 안내',SVCNM='주거정책 프로그램')
        self.assertIn('policy_eligibility_unconfirmed',assess_seoul_program(rec,now=NOW).reason_codes)

    def test_same_range_year_month_inheritance_only(self):
        for statement in ['2026.10.03.~11.03.','2026년 10월 3일 ~ 11월 3일','2026-10-03 - 2026-11-03','2026.10.3(토)～11.3(화)']:
            self.assertEqual(period_days(statement),(('2026-10-03','2026-11-03'),None))
        self.assertEqual(period_days('2026년 10월 3일~30일')[0],('2026-10-03','2026-10-30'))
        for statement in ['10월 3일~11월 3일','26년10월3일~11월3일','2026.10.3~10.5, 2026.11.1~11.3','회차 1.2 / 문의 02-1234-5678','2026.10.3~11.3 (휴관일 10.5)']:
            self.assertEqual(period_days(statement)[1],'body_period_needs_confirmation')

    def test_real_date_year_weekday_and_invalid_date_conflicts_stay(self):
        for statement,reason in [('2026.12.30~1.2','period_order_conflict'),('2026.2.30~3.1','invalid_body_date'),('2026.10.3(금)~11.3(화)','date_weekday_conflict')]:
            self.assertEqual(period_days(statement)[1],reason)
        for body,changes in [('운영기간: 2026.4.3.～11.30.',dict(SVCOPNBGNDT='2026-04-03',SVCOPNENDDT='2026-11-28')),
                             ('모집기간: 2026년 10월05일~10월18일',dict(RCPTBGNDT='2026-10-05',RCPTENDDT='2026-10-17',SVCOPNBGNDT='2026-10-05',SVCOPNENDDT='2026-10-18'))]:
            rec,_=self.packet('문화 체험을 진행합니다.\n'+body,**changes)
            self.assertIn('body_api_period_conflict',assess_seoul_program(rec,now=NOW).reason_codes)

    def test_payload_dates_conditions_and_input_are_not_rewritten(self):
        rec=normalize_seoul_item(row(DTLCONT='생태놀이를 진행합니다.\n운영기간: 2026.10.03.~11.03.\n장소: 서울 도봉구 합성공원\n거주 조건: 서울 시민만 신청 가능.'))
        original=copy.deepcopy(rec);p=program_rpc_item(rec)
        self.assertEqual(rec,original)
        self.assertEqual(p['program_facts']['periods'],rec.normalized_payload['dates'])
        self.assertFalse(p['program_facts']['missing'])
        self.assertIn('거주 조건',p['program_facts']['description'])
        self.assertEqual(p['jobs'],[])


if __name__=='__main__':
    if '--export' in sys.argv:print(json.dumps(packets(),ensure_ascii=False))
    else:unittest.main()
