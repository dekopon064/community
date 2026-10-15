"""Synthetic review evidence and parser counterexamples; no remote dependencies."""
import copy
import json
import socket
import unittest
from unittest.mock import patch

from ingest.content_filters import field, extract_filter_facts
from ingest.seoul_evidence import activity_locations, activity_text, venue_filter, activity_topic
from ingest.seoul_review_connections import propose_connections, same_period_supported
from plan_seoul_review_connections import plan_rows
from test_seoul_review_connections import ui_detail


PROVIDER={'PLACENM':'합성목재체험장','AREANM':'도봉구','PAYATNM':'무료','USETGTINFO':'성인'}


def review(body, *, missing=('topic','delivery','location')):
    d=ui_detail();d['facts']['description']=body;d['facts']['missing']=[];d['facts']['conflicts']=[];d['facts']['period_evidence']=[]
    for k in ('content_kind','delivery_mode','activity_region'):d['facts'][k]='unknown'
    d['facts']['activity_evidence']=[];d['facts']['conditions']=['개인별 예약 필수; 운영자 확인 조건 보존']
    for k in missing:d['filterInfo']['data'][k]=field()
    d['filterInfo']['missing']=list(missing);d['filterInfo']['origins']={k:'automatic' for k in missing}
    d['result'].update(reasons=['program_purpose_unconfirmed','delivery_mode_unknown'])
    d['source']['body']=body;d['observedFacts']=copy.deepcopy(d['facts'])
    return d


def examples():
    return [
        ('narrative',review('합성목재체험장에서는 시민을 위한 목공체험을 운영합니다.\n자연물 만들기 체험입니다.'),PROVIDER),
        ('label',review('주요활동: 문화 공예 체험\n♣ 교육장소: 서울 도봉구 합성공방'),{}),
        ('partial',review('주요활동: 노르딕워킹으로 숲길을 걷습니다.\n집결장소: 서울 도봉구 합성역 1번 출구'),PROVIDER),
        ('negative',review('주요활동: 공예 체험은 진행하지 않습니다.\n기관 주소: 서울 도봉구 합성공방'),PROVIDER),
    ]


class ReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('external connection forbidden'))
        guard.start();self.addCleanup(guard.stop)

    def test_narrative_location_and_all_known_fields_are_preserved(self):
        _,d,raw=examples()[0];before=copy.deepcopy(d);p=propose_connections(d,provider_fields=raw)
        self.assertEqual(p['facts_patch'],{'content_kind':'program','delivery_mode':'offline','activity_region':'capital'})
        self.assertEqual(p['filters_patch']['location']['value']['venues'][0]['district'],'도봉구')
        self.assertEqual(p['filters_patch']['topic'],field('culture_experience'));self.assertEqual(d,before)
        d['facts']['content_kind']='policy_finance';d['filterInfo']['data']['topic']=field('other')
        p=propose_connections(d,provider_fields=raw)
        self.assertNotIn('content_kind',p['facts_patch']);self.assertNotIn('topic',p['filters_patch'])

    def test_structural_bullet_variants_and_district_identity(self):
        for prefix in ('♠','♣','📍','❍','◎','►','⦁'):
            b='문화 공예 체험을 진행합니다.\n'+prefix+' 운영장소: 도봉구 합성로 5, 합성공방'
            with self.subTest(prefix=prefix):
                self.assertEqual(venue_filter(b,PROVIDER)['venues'][0]['province'],'11')
                self.assertIsNone(venue_filter(b,{**PROVIDER,'AREANM':'강서구'}))
        self.assertIsNone(venue_filter('문화 체험\n기관 주소: 서울 도봉구 합성공방',PROVIDER))

    def test_table_header_and_inline_activity_do_not_erase_main_description(self):
        intro='가드닝을 통해 식물을 가꾸는 정원 실습입니다.'
        b=intro+'\n날짜\n시간\n내용\n참가비\n10.10\n10:00\n화분\n무료'
        self.assertIn(intro,activity_text(b));self.assertEqual(activity_topic(b),'culture_experience')
        b='프로그램 내용:\n- 점심 산책\n대상: 성인 / 내용: 자연물 만다라 만들기\n준비물: 미정'
        self.assertIn('만다라 만들기',activity_text(b));self.assertEqual(activity_topic(b),'culture_experience')

    def test_conditional_cancellation_is_not_activity_denial(self):
        b='심폐소생술 교육을 진행합니다.\n신청인원 5명 이하의 경우 교육진행불가시 전날 연락합니다.'
        self.assertEqual(activity_topic(b),'daily_safety')
        for b in ('주요활동: 문화 체험을 진행하지 않습니다.','주요활동: 확인 필요\n자연물 만들기',
                  '시설 안내\n목공 체험실을 소개합니다.','주요활동: 문화 공예 체험과 주민 교류 활동',
                  '문화 체험과 주민 교류 활동을 함께 합니다.',
                  '신청인원 5명 이하 교육진행불가. 문화 체험은 하지 않습니다.',
                  '기상 악화 시 교육 취소. 공예 체험은 아님.',
                  '주요활동: 가죽 공예 체험과 주거정책 안내'):
            with self.subTest(body=b):self.assertIsNone(activity_topic(b))

    def test_current_role_replaces_unbound_legacy_meeting_quote_only_in_preview(self):
        d=review('주요활동: 목공 체험\n집결장소: 서울 도봉구 합성공방')
        d['facts'].update(content_kind='program',delivery_mode='offline',activity_region='capital',activity_evidence=['서울 도봉구 합성공방'])
        old=copy.deepcopy(d);p=propose_connections(d,provider_fields=PROVIDER)
        self.assertNotIn('location',p['filters_patch']);self.assertEqual(d,old)
        self.assertIsNone(venue_filter('주요활동: 문화 체험\n장소: 합성공방\n장소: 다른 시설',PROVIDER))

    def test_repeated_venue_does_not_expand_the_exact_evidence_to_entire_body(self):
        body='문화 공예 체험\n장소: 서울 도봉구 합성공방\n'+('예약 조건과 안전 안내를 보존합니다.\n'*100)+'서울 도봉구 합성공방 문의'
        packet=extract_filter_facts('seoul_reservation',{'program_text':body},{})
        self.assertEqual(packet['data']['location']['status'],'known')
        self.assertEqual(packet['evidence']['location']['excerpt'],'서울 도봉구 합성공방')
        for text,value in [('장소: 실제 이용 지역: 전국',{'scope':'nationwide','venues':[]}),
                           ('장소: 실제 이용 지역: 전국\n장소: 서울 도봉구 합성공방',None)]:
            self.assertEqual(venue_filter(text),value)

    def test_operator_unknown_is_a_review_candidate_not_an_automatic_write(self):
        _,d,raw=examples()[0];d['filterInfo']['origins']['topic']='operator'
        p=propose_connections(d,provider_fields=raw)
        self.assertNotIn('topic',p['filters_patch']);self.assertIn('operator:topic',p['held'])
        self.assertEqual(p['operator_review']['topic']['value'],field('culture_experience'))
        d['filterInfo']['data']['topic']=field('daily_safety')
        self.assertNotIn('topic',propose_connections(d,provider_fields=raw).get('operator_review',{}))
        d['filterInfo']['origins']['location']='operator';d['facts']['activity_region']='noncapital'
        self.assertNotIn('location',propose_connections(d,provider_fields=raw).get('operator_review',{}))

    def test_partial_reasons_and_actual_flags_are_not_removed(self):
        _,d,raw=examples()[2];d['facts']['conflicts']=['body_api_period_conflict'];before=copy.deepcopy(d)
        p=propose_connections(d,provider_fields=raw)
        self.assertEqual(p['facts_patch']['delivery_mode'],'offline');self.assertNotIn('activity_region',p['facts_patch'])
        self.assertIn('location',p['remaining_filters']);self.assertNotIn('body_api_period_conflict',p['resolve']);self.assertEqual(d,before)

    def test_period_single_day_and_explicit_hour_range_have_narrow_proofs(self):
        from test_seoul_review_connections import detail
        d=detail();f=d['facts'];f['description']='접수기간: 2026년 9월 28일 10시 ~ 10월 27일 13시';f['period_evidence']=[f['description'].split(': ',1)[1]]
        self.assertTrue(same_period_supported(f));old=copy.deepcopy(f)
        f['periods']['RCPTENDDT']['value']='2026-10-27T14:00:00+09:00';self.assertFalse(same_period_supported(f))
        f=old;f['description']='운영기간: 2026.10.03';f['period_evidence']=['2026.10.03']
        for key in ('SVCOPNBGNDT','SVCOPNENDDT'):f['periods'][key].update(value='2026-10-03',precision='day')
        self.assertTrue(same_period_supported(f))
        f['description']='접수기간: 2026.10.03';self.assertFalse(same_period_supported(f))
        f['description']='운영기간: 2026.2.30';f['period_evidence']=['2026.2.30'];self.assertFalse(same_period_supported(f))

    def test_stale_provider_context_and_active_work_remain_blocked(self):
        _,d,raw=examples()[0];r={'id':d['id'],'detail':d,'context':{'revision':'f'*64,'description':d['facts']['description'],'provider_fields':raw}}
        p=plan_rows([r])['plans'][0];self.assertNotIn('activity_region',p['facts_patch']);self.assertNotIn('location',p['filters_patch'])
        for status in ('claimed','completed'):
            d['aiStatus']=status;self.assertFalse(propose_connections(d,provider_fields=raw)['facts_patch'])

    def test_other_source_topic_extraction_is_unchanged(self):
        body='주요 활동: 자연물 만다라 만들기'
        seoul=extract_filter_facts('seoul_reservation',{'program_text':body},{})
        my=extract_filter_facts('myseoul_program',{'description':body},{'public_category':'program'})
        self.assertEqual(seoul['data']['topic'],field('culture_experience'));self.assertEqual(my['data']['topic'],field())


if __name__=='__main__':
    import sys
    if '--export' in sys.argv:print(json.dumps(examples(),ensure_ascii=False))
    else:unittest.main()
