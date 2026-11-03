"""Role/section regression fixtures, independent of operating IDs or network."""
import copy
import json
import socket
import sys
import unittest
from unittest.mock import patch

from ingest.connectors.seoul_reservation import normalize_seoul_item
from ingest.program_db import ProgramObservationAdapter
from ingest.program_scope import assess_seoul_program
from ingest.content_filters import extract_filter_facts, field
from ingest.seoul_evidence import activity_locations, activity_text, activity_topic, venue_filter
from ingest.seoul_review_connections import propose_connections
from test_seoul_review_evidence import review
from test_seoul_reservation import NOW, row


# Public descriptions abridged for regression testing, with synthetic IDs and dates.
TOUR = ('2) 운영구간: 명동문화공원 ~ 유네스코회관\n'
        '3) 이동경로: 해설 지점 14곳\n'
        '4) 집결장소: 명동문화공원 (명동성당 맞은편), 출발 전 도착\n'
        '공공예약에서 도보관광 검색 안내\n'
        '4. 주의사항\n도보로 이동하므로 편한 신발을 착용하세요.')
PILGRIMAGE = ('1) 집결 장소: 명동대성당 앞에서 출발\n'
              '2) 이동 경로: 주요 해설 지점 6곳\n'
              '① 명동대성당 → ② 이벽의 집터 → ③ 김범우 집터')


def tour_record(body, title='합성 도보관광 프로그램'):
    return normalize_seoul_item(row(SVCNM=title, PLACENM='명동문화공원', AREANM='중구',
                                    DTLCONT=''.join(f'<p>{line}</p>' for line in body.splitlines())))


def examples():
    bodies = [
        ('symbol', '문화 공예 체험을 진행합니다.\n￭ 운영장소: 서울 도봉구 합성교육장'),
        ('activity_place', '주요활동: 문화 공예 체험\n○ 활동 장소: 서울 도봉구 합성공방'),
        ('position', '프로그램 내용: 응급처치 교육 및 실습\n○ 위치\n: 서울 도봉구 합성교육장'),
        ('intro', '숲 해설가와 함께 숲을 탐방하는 생태 체험입니다.\n프로그램 내용: 가을 기록\n장소: 서울 도봉구 합성공원'),
        ('after_guide', '4. 주의사항\n음식물 반입 금지.\n프로그램 내용: 문화 공예 체험\n장소: 서울 도봉구 합성공방'),
        ('booth', '공예 체험을 진행합니다.\n장소: 합성역 2번 출구 일대 야외 현장 체험 부스'),
    ]
    return [(name, review(body), {}) for name, body in bodies]


class RoleSectionTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_unicode_prefixes_are_structure_not_facility_aliases(self):
        for prefix in ('￭', '🌳', '📌', '\u200b￭', '⦿', '◆'):
            with self.subTest(prefix=prefix):
                body = '문화 공예 체험\n' + prefix + ' 운영장소: 서울 도봉구 합성교육장'
                self.assertEqual(activity_locations(body), ('서울 도봉구 합성교육장',))
                self.assertEqual(venue_filter(body)['venues'][0]['district'], '도봉구')

    def test_activity_place_and_multiline_position_have_explicit_roles(self):
        for name, d, raw in examples()[1:3]:
            with self.subTest(name=name):
                p = propose_connections(d, provider_fields=raw)
                self.assertEqual(p['facts_patch']['delivery_mode'], 'offline')
                self.assertEqual(p['filters_patch']['location']['value']['venues'][0]['district'], '도봉구')
        self.assertIsNone(venue_filter('시설 안내\n위치: 서울 도봉구 합성공방\n시설에 문화 공예 체험실이 있습니다.'))
        body = '프로그램 내용: 문화 공예 체험\n장소: 서울 도봉구 합성공방\n시설 안내\n위치: 서울 송파구 관리교육실'
        self.assertEqual(activity_locations(body), ('서울 도봉구 합성공방',))
        body += '\n프로그램 내용: 응급처치 실습\n위치: 서울 강남구 합성교육장'
        self.assertEqual(activity_locations(body), ('서울 도봉구 합성공방', '서울 강남구 합성교육장'))

    def test_intro_and_activity_section_keep_the_same_program(self):
        _, d, raw = examples()[3]
        body = d['facts']['description']
        self.assertIn('숲 해설가와 함께', activity_text(body))
        self.assertIn('가을 기록', activity_text(body))
        self.assertEqual(activity_topic(body), 'culture_experience')
        self.assertEqual(propose_connections(d, provider_fields=raw)['facts_patch']['content_kind'], 'program')
        self.assertIsNone(activity_topic('문화 공예 체험과 주민 교류 활동을 함께 진행합니다.\n프로그램 내용: 문화 체험'))

    def test_explicit_program_section_can_follow_common_guide(self):
        _, d, _ = examples()[4]
        self.assertEqual(activity_topic(d['facts']['description']), 'culture_experience')
        self.assertNotIn('음식물 반입', activity_text(d['facts']['description']))
        self.assertIsNone(activity_topic('주의사항\n문화 공예 체험은 다른 시설에서 별도 운영합니다.'))

    def test_exit_is_not_always_a_meeting_point(self):
        _, d, _ = examples()[5]
        p = propose_connections(d)
        self.assertEqual(p['facts_patch']['delivery_mode'], 'offline')
        self.assertNotIn('activity_region', p['facts_patch'])
        self.assertNotIn('location', p['filters_patch'])
        for role in ('집결장소', '모임장소', '출발장소', '기관 주소'):
            with self.subTest(role=role):
                self.assertEqual(activity_locations('문화 체험\n' + role + ': 서울 도봉구 합성역 2번 출구 현장 부스'), ())
        self.assertEqual(activity_locations('문화 체험\n장소: 서울 도봉구 합성역 2번 출구 앞'), ())
        self.assertEqual(activity_locations('문화 체험\n장소: 합성역 2번 출구 현장 부스는 사용하지 않습니다.'), ())

    def test_gathering_and_actual_route_connect_to_seoul_facts_and_filter(self):
        for body in (TOUR, PILGRIMAGE, TOUR + '\n온라인 예약 후 오프라인으로 진행합니다.', TOUR + '\n온라인 참여 신청을 받습니다.',
                     TOUR + '\n온라인으로 진행하지 않습니다.'):
            with self.subTest(body=body):
                rec = tour_record(body)
                assessment = assess_seoul_program(rec, now=NOW)
                self.assertEqual(assessment.facts.delivery_mode, 'offline')
                self.assertNotIn('delivery_mode_unknown', assessment.reason_codes)
                self.assertIn('activity_location_unknown', assessment.reason_codes)
                self.assertEqual(assessment.facts.activity_evidence, ())
                calls = []
                adapter = ProgramObservationAdapter(lambda name, args: calls.append((name, args)))
                adapter.observe('local-run', [rec], None)
                name, args = calls[0]
                self.assertEqual(name, 'observe_seoul_program')
                packet = args['p_items'][0]
                self.assertEqual(packet['program_facts']['delivery_mode'], 'offline')
                self.assertEqual(packet['filterFacts']['data']['delivery'], field('onsite'))
                self.assertEqual(packet['filterFacts']['data']['location'], field())
                d = review(body)
                before = copy.deepcopy(d)
                proposal = propose_connections(d)
                self.assertEqual(proposal['facts_patch']['delivery_mode'], 'offline')
                self.assertEqual(proposal['filters_patch']['delivery'], field('onsite'))
                self.assertNotIn('location', proposal['filters_patch'])
                self.assertEqual(d, before)

    def test_incomplete_or_non_program_routes_stay_in_review(self):
        meeting = '집결장소: 서울 중구 명동문화공원'
        route = '이동경로: 명동문화공원 → 유네스코회관'
        for body in (meeting, route, meeting + '\n이동경로: 추후 안내',
                     meeting + '\n운영구간: 오전 10시 ~ 오후 12시',
                     meeting + '\n운영구간: 1구간 ~ 2구간',
                     meeting + '\n오시는 길 안내\n' + route,
                     '시설 안내\n' + meeting + '\n' + route,
                     meeting + '\n이동경로: 명동문화공원 → 명동문화공원',
                     meeting + '\n이동경로: 가상 광장 → 가상 전시관',
                     '집결장소: 미정\n' + route):
            with self.subTest(body=body):
                result = assess_seoul_program(tour_record(body), now=NOW)
                self.assertEqual(result.facts.delivery_mode, 'unknown')
                self.assertIn('delivery_mode_unknown', result.reason_codes)
                self.assertNotIn('delivery', propose_connections(review(body))['filters_patch'])

    def test_conflicting_online_and_mixed_evidence_cannot_fill_delivery_filter(self):
        for label in ('진행 방식: 온라인', '교육 방식: 혼합', '진행 방식: 온라인·현장 혼합',
                      '우천 시 온라인으로 진행합니다.', '비대면 화상 수업입니다.',
                      '온·오프라인 병행 진행', '온라인 및 현장 병행', '온라인 강의와 오프라인 활동을 함께 진행합니다.'):
            with self.subTest(label=label):
                body = label + '\n' + TOUR
                rec = tour_record(body)
                result = assess_seoul_program(rec, now=NOW)
                self.assertEqual(result.facts.delivery_mode, 'unknown')
                self.assertIn('delivery_mode_unknown', result.reason_codes)
                filters = extract_filter_facts('seoul_reservation', rec.normalized_payload, result.facts.to_payload())
                self.assertEqual(filters['data']['delivery'], field())
                proposal = propose_connections(review(body))
                self.assertNotIn('delivery_mode', proposal['facts_patch'])
                self.assertNotIn('delivery', proposal['filters_patch'])

    def test_source_title_conflict_is_also_held_in_review_preview(self):
        title = '온라인 수업 · 합성 프로그램'
        rec = tour_record(TOUR, title=title)
        self.assertEqual(assess_seoul_program(rec, now=NOW).facts.delivery_mode, 'unknown')
        detail = review(TOUR)
        detail['source']['title'] = title
        detail['facts']['conditions'].append('기존 운영자 조건')
        before = copy.deepcopy(detail)
        proposal = propose_connections(detail)
        self.assertNotIn('delivery_mode', proposal['facts_patch'])
        self.assertNotIn('delivery', proposal['filters_patch'])
        self.assertEqual(detail, before)

    def test_compound_heading_is_not_a_location(self):
        body = '문화 공예 체험\n[장소 및 시간]\n운영장소: 서울 도봉구 합성공원\n시간: 10:00'
        self.assertEqual(activity_locations(body), ('서울 도봉구 합성공원',))

    def test_known_operator_values_actual_flags_and_input_remain_unchanged(self):
        for _, d, raw in examples():
            d['facts']['conflicts'] = ['body_api_period_conflict']
            d['facts']['missing'] = ['body_period_needs_confirmation']
            d['filterInfo']['data']['audience'] = field('other')
            d['filterInfo']['origins']['topic'] = 'operator'
            before = copy.deepcopy(d)
            p = propose_connections(d, provider_fields=raw, operator_fields=['activity_region'])
            self.assertEqual(d, before)
            self.assertNotIn('topic', p['filters_patch'])
            self.assertNotIn('activity_region', p['facts_patch'])
            self.assertNotIn('body_api_period_conflict', p['resolve'])
            self.assertNotIn('body_period_needs_confirmation', p['resolve'])
            self.assertNotIn('audience', p['filters_patch'])

    def test_only_seoul_uses_the_new_section_reader(self):
        body = '숲 해설가와 함께 숲을 탐방합니다.\n프로그램 내용: 가을 기록'
        s = extract_filter_facts('seoul_reservation', {'program_text': body}, {})
        m = extract_filter_facts('myseoul_program', {'description': body}, {'public_category': 'program'})
        self.assertEqual(s['data']['topic'], field('culture_experience'))
        self.assertEqual(m['data']['topic'], field())

    def test_explicit_subject_and_activity_are_both_required(self):
        for text in ('주요 활동: 악기 연주를 배우는 수업입니다.',
                     '프로그램 내용: 그림을 직접 창작하고 배워 봅니다.',
                     '문화관광 해설을 진행하는 프로그램입니다.',
                     '활동내용: 산림 치유 프로그램을 진행합니다.'):
            self.assertEqual(activity_topic(text), 'culture_experience')
        for text in ('시설 안내\n악기 연주를 배우는 수업도 마련되어 있습니다.',
                     '준비물: 악기\n장소: 서울 도봉구 합성공방',
                     '프로그램 내용: 성악 수업은 진행하지 않습니다.',
                     '주요활동: 악기를 배우고 주민 교류 활동도 함께 합니다.',
                     '프로그램 내용: 악기를 배우지 않습니다.',
                     '활동내용: 산림 치유는 진행하지 않습니다.',
                     '프로그램 내용: 문화관광 해설을 하지 않습니다.'):
            self.assertIsNone(activity_topic(text))

    def test_district_qualified_venue_is_not_provider_area_only(self):
        text = '응급처치 교육 및 실습\n위치: 영등포구보건소 1층 합성교육장'
        raw = {'AREANM': '영등포구', 'PLACENM': '별도 제공 표기'}
        self.assertEqual(venue_filter(text, raw)['venues'][0]['district'], '영등포구')
        self.assertIsNone(venue_filter(text, {**raw, 'AREANM': '도봉구'}))
        self.assertIsNone(venue_filter('문화 체험\n장소: 합성공원', raw))
        self.assertIsNone(venue_filter('문화 체험\n장소: 중구보건소 1층 교육장', {'AREANM':'중구'}))


if __name__ == '__main__':
    if '--export' in sys.argv:
        print(json.dumps([dict(name=n, detail=d, proposal=propose_connections(d, provider_fields=r)) for n,d,r in examples()], ensure_ascii=False))
    else:
        unittest.main()
