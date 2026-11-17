"""Exercise the collection packet without network, database or AI calls."""
import unittest
from unittest.mock import Mock

from ingest.connectors.seoul_reservation import normalize_seoul_item
from ingest.program_db import ProgramNewOnlyObservationAdapter
from ingest.seoul_venue_directory import VENUES
from test_collection_filter_evidence import seoul
from test_seoul_reservation import row


class SeoulVenueDirectoryTests(unittest.TestCase):
    def packet(self, body, title="서울 문화 답사", place="", district=""):
        return seoul(title, "내용: 문화유산 도보답사 프로그램입니다.\n" + body, place, district)

    def assert_review(self, packet):
        self.assertEqual(packet["program_facts"]["activity_region"], "unknown")
        data = packet["filterFacts"]
        self.assertEqual(data["data"]["location"]["status"], "unknown")
        self.assertNotIn("location", data["evidence"])

    def test_address_for_declared_venue_without_provider_district(self):
        for name, venue in VENUES.items():
            with self.subTest(name=name):
                quote = "개최 장소: " + name
                packet = self.packet("위치: " + name + "\n" + quote)
                facts = packet["filterFacts"]
                self.assertEqual(facts["data"]["location"]["value"]["venues"], [
                    dict(province="11", district=venue.district, facility=name, address=venue.address)])
                self.assertEqual(facts["evidence"]["location"],
                                 dict(sourceField="payload.program_text", excerpt=quote))
                self.assertEqual(packet["program_facts"]["activity_region"], "capital")

    def test_selected_session_and_meeting_wording(self):
        quote = "2회차 집결장소: 덕수궁 대한문 앞 출발 *출발 5분 전까지 도착요망"
        body = "1회차 집결장소: 경복궁 광화문 앞\n" + quote
        packet = self.packet(body, title="궁궐답사 2회차")
        facts = packet["filterFacts"]
        self.assertEqual(facts["data"]["location"]["value"]["venues"][0]["facility"], "덕수궁 대한문 앞")
        self.assertEqual(facts["evidence"]["location"]["excerpt"], quote)
        self.assertIn(body, packet["program_facts"]["description"])
        self.assertEqual(tuple(packet["program_facts"]["activity_evidence"]), (quote,))
        self.assert_review(self.packet(body))
        self.assert_review(self.packet(body, title="궁궐답사 3회차"))
        self.assert_review(self.packet(body, title="궁궐답사 1·2회차"))
        packet = self.packet("회차별 집결지 상이\n" + body, title="궁궐답사 2회차")
        self.assertEqual(packet["filterFacts"]["evidence"]["location"]["excerpt"], quote)

    def test_actual_activity_sentence_and_specific_point(self):
        quote = "서울공예박물관 교육실에서 교육을 진행합니다."
        packet = self.packet("개최지: 서울공예박물관\n" + quote)
        self.assertEqual(packet["filterFacts"]["evidence"]["location"]["excerpt"], quote)

    def test_split_meeting_label_and_separate_directions(self):
        quote = "집결 장소:\n창경궁 홍화문 앞"
        packet = self.packet(quote + "\n찾아오시는 길\n장소: 경복궁역")
        self.assertEqual(packet["filterFacts"]["evidence"]["location"]["excerpt"], quote)
        self.assertEqual(packet["filterFacts"]["data"]["location"]["value"]["venues"][0]["facility"],
                         "창경궁 홍화문 앞")

    def test_unbound_title_station_directions_and_itinerary(self):
        for body in ("신청일에 맞춰 오세요.", "교통편: 경복궁역 2번 출구",
                     "오시는 길\n장소: 경복궁", "대중교통 이용 안내\n장소: 경복궁",
                     "찾아오시는 길\n집결장소: 경복궁", "장소: 경복궁역", "집결장소: 경복궁 역 1번 출구",
                     "위치: 경복궁", "기관 주소: 경복궁", "집결지: 경복궁 정문 맞은편",
                     "탐방코스: 경복궁 → 창덕궁", "장소: 경복궁 → 창덕궁",
                     "집결지: 경복궁\n또는 다른 장소", "집결지: 경복궁\n장소는 추후 안내",
                     "집결지: 경복궁 정문 앞\n출발지: 다른 장소", "집결지: 경복궁\n회차별 장소 상이",
                     "지난 회차\n장소: 경복궁", "예시\n집결지: 경복궁", "[A코스]\n집결지: 경복궁",
                     "장소: 경복궁\n우천 시 집결지: 창덕궁"):
            with self.subTest(body=body):
                self.assert_review(self.packet(body, "경복궁 답사", "경복궁", "종로구"))

    def test_provider_or_meeting_conflicts(self):
        for place, district in (("경복궁", "중구"), ("창덕궁", "종로구"), ("경복궁역", "종로구")):
            with self.subTest(place=place, district=district):
                self.assert_review(self.packet("집결지: 경복궁", place=place, district=district))
        self.assert_review(self.packet("집결지: 창덕궁 돈화문 앞\n출발지: 창덕궁 매표소 앞"))

    def test_online_stays_not_applicable(self):
        packet = seoul("비대면 수업", "온라인 수업으로 교육을 진행합니다.\n장소: 경복궁", "", "")
        self.assertEqual(packet["filterFacts"]["data"]["location"]["status"], "not_applicable")

    def test_new_only_rpc_keeps_revision_and_original_meeting(self):
        body = "프로그램 내용: 전시 해설\n집결장소: 서울공예박물관 입구 앞"
        item = normalize_seoul_item(row(DTLCONT=body, PLACENM="", AREANM=""))
        rpc = Mock(return_value=[dict(inputIndex=0, externalKey=item.external_key,
                                     id="00000000-0000-4000-8000-000000000001", revision=item.revision_hash,
                                     outcome="existing_skipped")])
        result = ProgramNewOnlyObservationAdapter(rpc).observe("test-run", [item], None)
        self.assertEqual(result[0]["outcome"], "existing_skipped")
        endpoint, args = rpc.call_args.args
        self.assertEqual((rpc.call_count, endpoint), (1, "observe_seoul_program_new_only"))
        packet, = args["p_items"]
        self.assertEqual(packet["jobs"], [])
        self.assertEqual(packet["program_facts"]["description"], body)
        self.assertEqual(packet["filterFacts"]["evidence"]["location"]["excerpt"], body.splitlines()[1])
