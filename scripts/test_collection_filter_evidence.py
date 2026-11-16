"""Offline replicas of provider descriptions, through the normal collection packets."""
import unittest

from ingest.connectors.seoul_reservation import normalize_seoul_item
from ingest.connectors.myseoul_program import normalize_detail
from ingest.program_db import program_rpc_item
from ingest.myseoul_db import myseoul_rpc_item
from test_seoul_reservation import row
from test_myseoul_program import detail, url, NOW


def seoul(title, body, place, district):
    return program_rpc_item(normalize_seoul_item(row(
        SVCNM=title, DTLCONT=body, PLACENM=place, AREANM=district)))


def myseoul(body, **fields):
    opts = dict(body=body, venue='', mode='')
    opts.update(fields)
    return myseoul_rpc_item(normalize_detail(detail(**opts), url()), now=NOW)


class CollectionFilterEvidenceTests(unittest.TestCase):
    def test_insa_address_and_room_refer_to_same_facility(self):
        body = ('인사도시유적전시관 전시 해설 운영\n'
                '○ 위 치 : 서울특별시 종로구 종로 11 길 18 G1 서울 지하 1 층 인사도시유적전시관\n'
                '○ 장 소 : G1 서울 빌딩 지하 1 층 인사도시유적전시관 입구 안내데스크 앞')
        packet = seoul('인사도시유적전시관 전시해설', body, '인사도시유적전시관', '종로구')
        filters = packet['filterFacts']
        self.assertEqual(packet['program_facts']['activity_region'], 'capital')
        self.assertEqual(filters['data']['location']['value']['venues'][0]['district'], '종로구')
        self.assertIn(filters['evidence']['location']['excerpt'], body)
        self.assertIn('종로구', filters['evidence']['location']['excerpt'])
        self.assertEqual(filters['data']['delivery']['value'], 'onsite')
        self.assertEqual(filters['data']['topic']['value'], 'culture_experience')
        changed = body.replace('G1 서울 빌딩', '부산 빌딩')
        self.assertEqual(seoul('전시 해설', changed, '인사도시유적전시관', '종로구')
                         ['filterFacts']['data']['location']['status'], 'unknown')

    def test_deoksugung_notice_only_proves_delivery(self):
        body = '4. 주의사항\n▸ 도보답사로 진행하므로, 편안한 복장과 운동화를 착용하시기 바랍니다.\n온라인 예약'
        def filters(extra):
            return seoul('궁궐역사문화답사(덕수궁)', body+extra, '덕수궁', '')['filterFacts']['data']
        self.assertEqual(filters('')['delivery']['value'], 'onsite')
        for field in ('location', 'topic'):
            self.assertEqual(filters('')[field]['status'], 'unknown')
        for conflict in ('\n온라인 수업', '\n진행방식: 혼합'):
            self.assertEqual(filters(conflict)['delivery']['status'], 'unknown')

    def test_hanyang_meeting_points_are_not_one_district(self):
        packet = seoul('서울한양도성 스탬프투어 무료해설', '주의사항\n집결지로 도착해 주세요.\n'
                       '1코스 백악, 2코스 낙산, 3코스 목멱, 4코스 인왕',
                       '창의문, 혜화문, 광희문, 숭례문 (회차별 상이)', '종로구')
        self.assertEqual(packet['filterFacts']['data']['location']['status'], 'unknown')
        self.assertEqual(packet['program_facts']['activity_region'], 'unknown')

    def test_myseoul_booking_venue_and_unique_activity(self):
        body = ('<p>내용: 공예 체험 수업</p><p>운영 장소: 서울특별시 용산구 이촌 체험관</p>'
                '<p>신청 방법: 온라인 예약</p>')
        result = myseoul(body)
        data = result['filterFacts']['data']
        self.assertEqual(result['myseoul_facts']['delivery_mode'], 'offline')
        self.assertEqual(data['location']['value']['venues'][0]['district'], '용산구')
        self.assertEqual(data['topic']['value'], 'culture_experience')
        mixed = body.replace('공예 체험 수업', '공예 체험과 안전 교육 수업')
        self.assertEqual(myseoul(mixed)['filterFacts']['data']['topic']['status'], 'unknown')
        conflict = myseoul(body, venue='서울특별시 종로구 다른 교육장')
        self.assertEqual(conflict['filterFacts']['data']['location']['status'], 'unknown')

    def test_myseoul_directions_do_not_prove_onsite_class(self):
        for text in ('집결장소: 서울 종로구 덕수궁','기관 주소: 서울 종로구 교육센터'):
            packet = myseoul('<p>내용: 공예 체험 수업</p><p>'+text+'</p><p>온라인 신청</p>')
            for key in ('delivery', 'location'):
                self.assertEqual(packet['filterFacts']['data'][key]['status'], 'unknown')

    def test_myseoul_walk_conflict_and_undecided_venue(self):
        body = '<p>내용: 공예 체험 수업</p><p>도보답사로 진행합니다.</p><p>온라인 예약</p>'
        self.assertEqual(myseoul(body)['filterFacts']['data']['delivery']['value'], 'onsite')
        conflict = myseoul(body + '<p>진행 방식: 온라인</p>')
        self.assertEqual(conflict['filterFacts']['data']['delivery']['status'], 'unknown')
        vague = myseoul('<p>내용: 공예 체험 수업</p>', venue='서울 용산구 또는 기타 장소, 미정')
        for key in ('location', 'delivery'):
            self.assertEqual(vague['filterFacts']['data'][key]['status'], 'unknown')
