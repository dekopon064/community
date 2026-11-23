"""Public daytime tour wording in a synthetic, offline worker claim."""
import unittest
from unittest.mock import patch

from ingest.seoul_content import assemble_seoul_body
from ingest.ai_errors import ValidationError
from ingest.seoul_candidate_review import SeoulCandidateReview
from ingest.seoul_fact_roles import optional_section
from test_seoul_common_timetable import fixture, japanese, SUMMARY
import test_seoul_date_hours_replay as worker


FEE_LIMIT = '참 가비 : 무료 (최대 1회차 예약가능/ 1회에 2명까지 신청 가능)'
PEOPLE = '1회 신청 시, 최대 2인까지 예약할 수 있습니다.'
ONSITE = '본 행사는 원활한 운영과 사전 준비를 위해 사전 신청제로 진행되며, 현장 접수는 받지 않습니다.'
PHOTO = '행사 중 사진 촬영이 이루어지며, 신청 시 이에 동의하는 것으로 간주합니다.'
BOOKING = '선착순 사전예약제로 최대 1회차, 신청당 2명까지 예약할 수 있으며 현장 접수는 받지 않습니다.'
CONSENT = '신청하면 행사 중 사진 촬영에 동의한 것으로 봅니다.'
CONTACT = '문의: 빛모락투어 사무국 tour11201205@gmail.com'
METHOD = '\n'.join((BOOKING, CONSENT, CONTACT))
JA_BOOKING = '先着順の事前予約制で、予約は最大1回分、申込1件につき2名までです。当日の現地受付は行いません。'
JA_CONSENT = '申し込むと、イベント中の写真撮影に同意したものとみなします。'


def booking_fixture(notices):
    ctx = fixture()
    facts = ctx['facts']
    facts.update(fee_kind='free', fee_amounts=[])
    facts['conditions'] += notices
    facts['description'] += '\n🎟️ 참가 안내\n' + '\n'.join([*notices, CONTACT])
    return ctx


def summary_with(method):
    return SUMMARY.replace('예약 후 참여합니다.', method)


class ReservationCopyTests(unittest.TestCase):
    def setUp(self):
        guard = patch('socket.socket.connect', side_effect=AssertionError('offline only'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_daytime_worker_sends_clean_body_to_translation_and_candidate(self):
        ctx = booking_fixture([FEE_LIMIT, PEOPLE, ONSITE, PHOTO])
        facts = ctx['facts']
        def translate(body):
            return japanese(body.replace(BOOKING, JA_BOOKING).replace(CONSENT, JA_CONSENT))
        summary = summary_with(METHOD)
        body = assemble_seoul_body(summary, facts)
        entry = dict(title='광화문 투어', facts=facts, filters=ctx['filterContext']['data'],
                     summary=dict(content_ko=summary, facts=dict(audience='성인', geo_age_income='성인',
                                  amount_period_deadline='무료', how_to_apply='사전 예약')),
                     translation_input_ko=body, translation=dict(title_ja='歴史ツアー', content_ja=translate(body)))
        with (patch.object(worker, 'recorded', return_value=[entry]),
              patch.object(worker, 'synthetic_translation', translate)):
            for classified in (False, True):
                with self.subTest(reclassified=classified):
                    result, calls, saved, requests = worker.DateHoursReplayTests.replay(self, 0, classified)
                    self.assertEqual(result.completed, 1, calls[-1])
                    ko, ja = saved[0]['contentKo'], saved[0]['contentJa']
                    self.assertEqual(len(requests), 2)
                    self.assertEqual(requests[1]['input'][0]['content'].split('content_ko:\n', 1)[1], ko)
                    self.assertNotIn('**예약 절차:**', ko)
                    for text, phrases in [(ko, (BOOKING, CONSENT, '무료')), (ja, (JA_BOOKING, JA_CONSENT, '無料'))]:
                        for phrase in (*phrases, 'tour11201205@gmail.com'):
                            self.assertEqual(text.count(phrase), 1, text)

    def test_unknown_qualifiers_and_contacts_remain_verbatim(self):
        extra = [PEOPLE + ' 단, 단체는 별도로 신청하세요.',
                 ONSITE + ' 신청 마감은 이용일 3일 전입니다.',
                 PHOTO + ' 단, 홍보 활용은 별도 동의를 받습니다.',
                 PEOPLE + ' 변경 문의: change@example.org']
        facts = booking_fixture(extra)['facts']
        method = METHOD + '\n취소 문의: cancel@example.org'
        result = optional_section(assemble_seoul_body(summary_with(method), facts), '[신청 방법]')
        for text in [*extra, CONTACT, '취소 문의: cancel@example.org']:
            self.assertEqual(result.count(text), 1)

    def test_split_booking_sentences_and_scoped_exceptions(self):
        facts = booking_fixture([FEE_LIMIT, PEOPLE, ONSITE, PHOTO])['facts']
        method = '선착순 사전예약제입니다.\n최대 1회차, 신청당 2명까지 예약할 수 있습니다.\n현장 접수는 불가합니다.\n' + CONSENT
        body = assemble_seoul_body(summary_with(method), facts)
        self.assertNotIn('**예약 절차:**', body)
        for scoped in ('단체 신청 안내\n' + method, method + '\n단, 토요일에는 현장 접수가 가능합니다.'):
            body = assemble_seoul_body(summary_with(scoped), facts)
            self.assertIn(scoped, body)
            self.assertIn(ONSITE, body)
            self.assertIn(PHOTO, body)

    def test_partial_or_different_proofs_keep_unique_terms(self):
        facts = booking_fixture([FEE_LIMIT, PEOPLE, ONSITE, PHOTO])['facts']
        method = '신청당 최대 2명까지 예약할 수 있습니다.\n현장 접수는 받지 않습니다.\n사진 촬영 동의는 선택입니다.'
        summary = summary_with(method)
        body = assemble_seoul_body(summary, facts)
        self.assertEqual(body, assemble_seoul_body(body, facts))
        application = optional_section(body, '[신청 방법]')
        for text in (method.splitlines()[0], '현장 접수는 받지 않습니다.', '최대 1개 회차를 예약할 수 있습니다.',
                     '사전 예약제로 진행합니다.', PHOTO, '사진 촬영 동의는 선택입니다.'):
            self.assertEqual(application.count(text), 1)
        self.assertNotIn('무료', application)
        facts['fee_kind'] = 'unknown'
        qualified = summary_with(BOOKING.replace('2명까지', '3명까지') + '\n' + CONSENT)
        with self.assertRaises(ValidationError) as err:
            assemble_seoul_body(qualified, facts)
        self.assertEqual(err.exception.diagnostic['rule'], 'participant_quantity')
        application = optional_section(assemble_seoul_body(qualified, facts, review=SeoulCandidateReview(None)), '[신청 방법]')
        for text in ('3명까지', '2명까지', '무료'):
            self.assertIn(text, application)
