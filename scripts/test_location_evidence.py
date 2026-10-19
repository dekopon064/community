"""Synthetic counterparts of observed failure classes; no production data/IO."""
import copy
import unittest
from unittest.mock import patch
from ingest.location_evidence import (source_link,quote_link,facility_name,
    verified_quote,url_identity,page_location_link,source_region_conflict)
import test_location_plan_research as fixture
ITEM,EVIDENCE,URL,completed=fixture.ITEM,fixture.EVIDENCE,fixture.URL,fixture.completed

LINK_CASES=[
    ('title venue','[합성물빛공원] 체험','신청 안내','합성물빛공원',True,'title'),
    ('meeting wins','[합성물빛공원] 체험','만나는 장소: 합성달빛공원 앞\n활동 장소: 합성물빛공원','합성물빛공원',False,'meeting'),
    ('explicit venue wins','[합성물빛공원] 체험','개최 장소: 합성달빛공원','합성물빛공원',False,'venue'),
    ('unknown meeting','합성 체험','만나는 장소는 별도 안내\n활동 장소: 합성물빛공원','합성물빛공원',False,'meeting_not_explicit'),
    ('multiple meeting','합성','집결지: 합성물빛공원\n집결지: 합성달빛공원','합성물빛공원',False,'meeting_multiple'),
    ('punctuation','합성','만남장소: 합성물빛공원 1층(교육실)','합성물빛공원 1층 교육실',True,'meeting'),
    ('containment','합성','장소: 합성물빛공원 內 합성센터 회의실','합성물빛공원 합성센터 회의실',True,'venue'),
    ('room conflict','합성','장소: 합성물빛공원 3교육실','합성물빛공원 2교육실',False,'venue'),
    ('exit conflict','합성','출발장소: 합성역 3번출구','합성역 6번출구',False,'meeting'),
    ('invented room','합성','장소: 합성물빛공원','합성물빛공원 2교육실',False,'venue'),
    ('wrong entrance','합성','장소: 합성물빛공원 정문','합성물빛공원 후문',False,'venue'),
    ('nonvenue','합성','기관 주소: 합성물빛공원','합성물빛공원',False,'description'),
    ('pickup','합성','수령장소: 합성물빛공원','합성물빛공원',False,'description'),
    ('parking','합성','주차장 위치: 합성물빛공원','합성물빛공원',False,'description'),
    ('description venue','합성','합성물빛공원 체험 안내','합성물빛공원',True,'description'),
    ('numbered meeting','합성','4) 집결장소: 합성물빛공원 앞','합성물빛공원 앞',True,'meeting'),
]


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.net=patch('socket.create_connection',side_effect=AssertionError('network forbidden'));self.net.start();self.addCleanup(self.net.stop)
        self.fx=fixture.LocationResearchTests('test_common_reuse_real_factory_pro_search_and_verified_page')
        self.fx.setUp();self.addCleanup(self.fx.doCleanups)

    def test_source_cases_and_qualifiers(self):
        for name,title,description,place,expected,role in LINK_CASES:
            with self.subTest(name=name):self.assertEqual(source_link(title,description,place),(expected,role))

    def test_facility_keeps_named_parent_but_not_generic_room(self):
        self.assertEqual(facility_name('합성물빛공원 1층 교육실 앞'),'합성물빛공원')
        self.assertEqual(facility_name('합성도시건축전시관 B2 소통방'),'합성도시건축전시관')
        self.assertTrue(quote_link('합성물빛공원 1층 교육실 앞','합성물빛공원\n서울특별시 강동구 합성길','서울','강동구'))
        self.assertFalse(quote_link('다른공원 앞','합성물빛공원\n서울특별시 강동구 합성길','서울','강동구'))
        self.assertEqual(facility_name('합성극장 앞'),'합성극장')
        self.assertFalse(quote_link('교육실','교육실 서울특별시 강동구 합성길','서울','강동구'))

    def test_quote_explanation_separated_without_touching_actual_response(self):
        original='공식 페이지에서 “합성물빛공원” 및 “서울특별시 강동구 합성길”로 안내합니다.'
        page='합성물빛공원\n시설 이용 안내\n위치 : 서울특별시 강동구 합성길'
        e={**EVIDENCE,'excerpt':original};value=completed({'status':'suggested','evidence':e});before=copy.deepcopy(value)
        a,client=self.fx.adapter([value],fetcher=lambda url:page)
        result=a.investigate(ITEM)
        self.assertEqual(result['status'],'suggested');self.assertEqual(result['evidence']['excerpt'],'합성물빛공원\n서울특별시 강동구 합성길')
        self.assertIn(original,a.last_diagnostic['proposed']);self.assertTrue(a.last_diagnostic['official']['explanation'])
        self.assertEqual(value,before);self.assertEqual(len(client.calls),1)
        self.assertEqual(self.fx.owner.login_calls,[]);self.assertEqual(self.fx.owner.posts(),[])

    def test_legacy_field_labels_are_format_not_address_facts(self):
        q,_,parts=verified_quote('장소: 합성물빛공원 / 주소: 서울특별시 강동구 합성길','합성물빛공원\n지도 주소 서울특별시 강동구 합성길')
        self.assertEqual(q,'합성물빛공원\n서울특별시 강동구 합성길');self.assertEqual(len(parts),2)

    def test_invented_quote_or_extra_address_never_dropped(self):
        page='합성물빛공원 위치 서울특별시 강동구 합성길'
        for quote in ['“합성물빛공원” “서울특별시 종로구 다른길”','장소: 합성물빛공원 / 주소: 서울특별시 종로구 다른길','“합성물빛공원 위치 서울특별시 강동구 합성길”이고 서울 종로구에 있습니다.']:
            with self.subTest(quote=quote):self.assertIsNone(verified_quote(quote,page)[0])

    def test_parent_facility_name_and_current_meeting_room_are_connected(self):
        item={**ITEM,'description':'만나는 장소: 합성물빛공원 1층 교육실 앞'}
        e={**EVIDENCE,'place':'합성물빛공원 1층 교육실 앞','excerpt':'위치: 서울특별시 강동구 합성길'}
        a,_=self.fx.adapter([completed({'status':'suggested','evidence':e})],fetcher=lambda url:'합성물빛공원\n위치: 서울특별시 강동구 합성길')
        self.assertEqual(a.investigate(item)['status'],'suggested')
        self.assertEqual(item['description'],'만나는 장소: 합성물빛공원 1층 교육실 앞')

    def test_title_venue_does_not_override_current_meeting(self):
        item={**ITEM,'title':'[합성물빛공원] 체험','description':'만나는 장소: 합성달빛공원 앞'}
        a,_=self.fx.adapter();self.assertEqual(a.investigate(item)['status'],'error');self.assertEqual(self.fx.reads,[])

    def test_current_address_conflict_not_overridden_by_new_quote(self):
        item={**ITEM,'description':'만나는 장소: 서울 종로구 합성물빛공원 교육장 앞'}
        a,_=self.fx.adapter();self.assertEqual(a.investigate(item)['status'],'error')
        self.assertEqual(a.last_diagnostic['code'],'research_source_region_conflict');self.assertEqual(self.fx.reads,[])

    def test_ambiguous_status_is_not_converted_into_a_suggestion(self):
        a,_=self.fx.adapter([completed({'status':'ambiguous','evidence':EVIDENCE})])
        self.assertEqual(a.investigate(ITEM)['status'],'error');self.assertEqual(a.last_diagnostic['code'],'research_unexpected_evidence')

    def test_wrong_exit_and_unrelated_facility_address_fail(self):
        item={'title':'합성 역 안내','description':'출발장소: 합성역 6번출구'}
        self.assertFalse(source_link(item['title'],item['description'],'합성역 3번출구')[0])
        self.assertFalse(quote_link('합성역 6번출구','합성역 3,4번 출구 서울특별시 강동구 합성길','서울','강동구'))
        self.assertTrue(quote_link('합성역 3번출구','합성역 3,4번 출구 서울특별시 강동구 합성길','서울','강동구'))
        page='합성물빛공원\n주소 서울특별시 강동구 합성길\n다른공원\n주소 서울특별시 종로구 다른길'
        self.assertFalse(page_location_link(ITEM,'합성물빛공원 앞','합성물빛공원\n서울특별시 종로구 다른길',page,'서울','종로구'))

    def test_shared_footer_is_not_facility_address(self):
        page='합성물빛공원\n체험 설명\n이메일 무단수집거부 서울특별시청 04524 서울특별시 종로구 합성길'
        self.assertFalse(page_location_link(ITEM,'합성물빛공원 앞','합성물빛공원\n서울특별시 종로구 합성길',page,'서울','종로구'))
        self.assertFalse(quote_link('합성물빛공원 앞','합성물빛공원 서울특별시 강동구 합성길\n서울특별시 종로구 다른길','서울','강동구'))

    def test_same_program_title_does_not_link_other_venue_or_multiple_maps(self):
        item={'title':'합성 프로그램','description':'만나는 장소: 합성물빛공원 앞'}
        page='합성 프로그램\nLocation다른공원\n합성물빛공원 경유\n지도 주소 서울특별시 강동구 합성길'
        self.assertFalse(page_location_link(item,'합성물빛공원 앞','합성물빛공원\n서울특별시 강동구 합성길',page,'서울','강동구'))

    def test_url_comparison_only_decodes_safe_equivalent_characters(self):
        self.assertEqual(url_identity(URL+'/%28sample%29#part'),url_identity(URL+'/(sample)'))
        for left,right in [('a%26b','a&b'),('a%2Fb','a/b'),('x=1&x=2','x=2&x=1'),('a%2eb','a.b'),('a+b','a%20b')]:
            self.assertNotEqual(url_identity(URL+'/'+left),url_identity(URL+'/'+right))

    def test_equivalent_search_url_keeps_original_url_in_real_adapter(self):
        original='https://parks.seoul.go.kr/synthetic/(sample)?a=1&b=2'
        encoded='https://parks.seoul.go.kr/synthetic/%28sample%29?a=1&b=2'
        e={**EVIDENCE,'url':original};value=completed({'status':'suggested','evidence':e})
        value['output'][1]['action']['sources'][0]['url']=encoded
        value['output'][2]['content'][0]['annotations'][0]['url']=encoded
        a,_=self.fx.adapter([value]);result=a.investigate(ITEM)
        self.assertEqual(result['status'],'suggested');self.assertEqual(result['evidence']['url'],original)
        self.assertEqual(self.fx.reads,[original])

    def test_reserved_url_separator_is_not_treated_as_equivalent(self):
        value=completed();value['output'][1]['action']['sources'][0]['url']=URL.replace('&','%26')
        value['output'][2]['content'][0]['annotations'][0]['url']=URL.replace('&','%26')
        a,_=self.fx.adapter([value]);self.assertEqual(a.investigate(ITEM)['status'],'error')
        self.assertEqual(a.last_diagnostic['code'],'research_url_not_in_search_sources');self.assertEqual(self.fx.reads,[])

    def test_conflicting_explicit_quote_cannot_be_saved_by_supplement(self):
        e={**EVIDENCE,'excerpt':'“합성물빛공원” “서울특별시 종로구 없는길”'}
        a,_=self.fx.adapter([completed({'status':'suggested','evidence':e})])
        self.assertEqual(a.investigate(ITEM)['status'],'error');self.assertEqual(a.last_diagnostic['code'],'research_quote_not_in_page')


if __name__=='__main__':unittest.main()
