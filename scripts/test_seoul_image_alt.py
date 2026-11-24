"""Retained quote plus synthetic detail rows through the real new-only collection path."""
import copy
import html
import json
import sys
import unittest
from unittest.mock import patch

import test_seoul_culture_collection as culture
from ingest.connectors.seoul_reservation import normalize_seoul_item
from ingest.program_scope import assess_seoul_program
from test_seoul_reservation import NOW, row

TITLE = '더 임팩트 청년예술인과 함께하는 연말콘서트 〈2026 임팩트 온〉'
QUOTE = '본 공연은 전체관람가입니다 . 나이, 개월 수에 관계없이 모든 관람 인원 수만큼 예약해주셔야 합니다.'
# The checklist records the deposit and refund, but not their exact full sentence.
FEE = '예매보증금은 5,000원이며 공연 후 환불됩니다.'
ACTIVITY = '지역 연주자들이 여러 악기로 지역 음악을 연주합니다.'
NORMAL = '생활 문화 체험 프로그램입니다. 누구나 참여 가능합니다.'


def source(key, *alts, body='', title=TITLE):
    detail = '<p>상세내용</p><p>' + html.escape(body) + '</p>'
    detail += ''.join('<img src="poster.png" alt="' + html.escape(alt) + '">' for alt in alts)
    return row(key, SVCNM=title, USETGTINFO='제한없음', DTLCONT=detail)


def examples():
    return {
        'concert': source('S261118111439501556', QUOTE, QUOTE, FEE),
        'duplicate': source('duplicate', NORMAL, body=NORMAL),
        'decorative': source('decorative', '공연 안내 포스터 이미지입니다. 포스터를 확인해 주세요.', TITLE, TITLE + '.png'),
        'activity': source('activity', ACTIVITY),
        'cast': source('cast', QUOTE, title='연말 공연 출연자 모집'),
        'group': source('group', ACTIVITY, '학교 단체 전용입니다.'),
        'age': source('age', QUOTE, body='관람은 만 19세 이상'),
        'actor': source('actor', QUOTE, body='단체만 신청 가능'),
        'full_conflict': source('full_conflict', '만 15세 이상만 입장 가능합니다.', body=QUOTE),
        'missing_period': dict(source('missing_period', QUOTE), SVCOPNENDDT=''),
    }


def packets():
    # Use the existing fake HTTP transport and atomic RPC, including the production
    # culture selector, packing, revision fence and existing-key checks.
    case = culture.CultureCollectionTests()
    case.setUp()
    try:
        sources = examples()
        _, _, stored = case.execute(culture.pages(list(sources.values())))
        return {key: stored[item['SVCID']] for key, item in sources.items()}
    finally:
        case.doCleanups()


class AltTests(unittest.TestCase):
    def test_normalized_evidence_and_protected_source(self):
        saved = packets()
        concert = saved['concert']
        payload, facts = concert['normalized_payload'], concert['program_facts']
        self.assertEqual(payload['image_alt_evidence']['source'], 'DTLCONT.img.alt')
        self.assertEqual(payload['image_alt_evidence']['quotes'], [QUOTE, FEE])
        self.assertEqual(facts['description'].count('모든 관람'), 1)
        self.assertEqual(facts['description'].count('5,000원'), 1)
        self.assertIn('공연 후 환불', facts['description'])
        self.assertEqual(facts['target_raw'], '제한없음')
        self.assertEqual(payload['source_body_html'], examples()['concert']['DTLCONT'])
        self.assertNotIn('attachment_dependent', facts['missing'])
        self.assertEqual(facts['content_kind'], 'unknown')  # the versioned filter decision owns promotion
        self.assertTrue(payload['image_alt_evidence']['audience_booking'])
        for key in ('duplicate', 'decorative'):
            self.assertNotIn('image_alt_evidence', saved[key]['normalized_payload'])
        self.assertEqual(saved['duplicate']['program_facts']['description'], NORMAL)
        self.assertIn('attachment_dependent', saved['decorative']['program_facts']['missing'])
        self.assertFalse(saved['activity']['normalized_payload']['image_alt_evidence']['audience_booking'])
        self.assertTrue(saved['cast']['normalized_payload']['image_alt_evidence']['recruitment'])
        self.assertEqual(saved['group']['program_facts']['application_actor'], 'institution')
        for key, reason in [('age','target_conflict'),('full_conflict','target_conflict'),('actor','application_actor_conflict')]:
            self.assertIn(reason, saved[key]['program_facts']['conflicts'])
        self.assertEqual(saved['full_conflict']['program_facts']['description'], QUOTE)
        self.assertIn('period_missing_or_unparsed', saved['missing_period']['program_facts']['missing'])

    def test_reference_text_and_unusable_or_oversize_posters(self):
        reference = '자세한 내용은 아래 포스터에서 확인해 주세요.'
        audience = '전체관람가입니다. 관람객마다 예약해야 합니다.'
        def facts(*alts):
            item = source('other-source-key', *alts, body=reference, title='가족과 즐기는 실내악 연주회')
            record = normalize_seoul_item(item)
            self.assertIn(reference, record.normalized_payload['plain_text'])
            return record
        self.assertTrue(facts(audience).body_usable)
        self.assertFalse(facts('전체관람가가 아닙니다. 관람객마다 예약해야 합니다.').body_usable)
        self.assertFalse(facts('포스터').body_usable)
        self.assertFalse(facts(QUOTE + '대상' * 2500).body_usable)
        self.assertFalse(facts(ACTIVITY, '예약 가능 여부는 미정입니다.').normalized_payload['image_alt_evidence']['audience_booking'])

    def test_full_body_and_image_admission_disagree(self):
        def reasons(body, notice):
            record = normalize_seoul_item(source('test', notice, body=body))
            self.assertEqual(record.normalized_payload['program_text'], body)
            return assess_seoul_program(record, now=NOW).reason_codes
        self.assertIn('application_actor_conflict', reasons(ACTIVITY + ' 개인 신청 가능.', '단체 예약 전용'))
        self.assertIn('individual_participation_excluded', reasons(ACTIVITY, '기관 신청 전용입니다.'))
        self.assertIn('target_conflict', reasons(ACTIVITY + ' 성인 전용입니다.', '청소년만 참여 가능합니다.'))

    def test_existing_items_and_section_boundary(self):
        case = culture.CultureCollectionTests()
        case.setUp()
        try:
            original = {'revision_hash':'a'*64, 'history':['operator'], 'data':{'topic':'known'}}
            item = examples()['concert']
            result, _, stored = case.execute(culture.pages([item]), originals={item['SVCID']:copy.deepcopy(original)})
            self.assertEqual(result['existing_skipped'], 1)
            self.assertEqual(stored[item['SVCID']], original)
        finally:
            case.doCleanups()
        before_details = dict(item, DTLCONT='<img alt="'+QUOTE+'"><p>상세내용</p><img alt="포스터">')
        result = assess_seoul_program(normalize_seoul_item(before_details), now=NOW)
        self.assertIn('attachment_dependent', result.reason_codes)


if __name__ == '__main__':
    if '--before-packets' in sys.argv:
        # Restore the old parser behavior: img is an attachment marker only.
        with patch('ingest.connectors.seoul_reservation.detail_image_evidence', return_value=None):
            print(json.dumps(packets(), ensure_ascii=True))
    elif '--packets' in sys.argv:
        print(json.dumps(packets(), ensure_ascii=True))
    else:
        unittest.main()
