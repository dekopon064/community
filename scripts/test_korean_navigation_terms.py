"""Source-backed literals, fake Pro/Auth/RPC only; no external connections."""
import copy
import unittest
from unittest.mock import patch

from ingest.ai_errors import ValidationError
from ingest.korean_navigation_terms import checked_navigation_texts, navigation_literals
from ingest.region_ja_glossary import validate_japanese_output


class NavigationTermsTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'socket.create_connection', 'socket.getaddrinfo',
                       'ingest.supabase_store.create_ingest_client', 'ingest.chatgpt_plan_auth.authenticate_worker'):
            guard = patch(target, side_effect=AssertionError('live access forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def test_preserved_edit_examples_and_menu_selection(self):
        # Existing Nov 4/5 editorial evidence; no claim of regenerated AI output.
        for ko, ja in [
            ('‘도보관광’을 검색하세요.', '「도보관광」（徒歩観光）を検索してください。'),
            ('‘심폐소생술 교육신청’ 탭을 클릭하세요.', '「심폐소생술 교육신청」タブを選択してください。'),
            ('예약 항목 ‘한옥의 아침 : 건축 이야기’를 선택하세요.', '予約項目「한옥의 아침 : 건축 이야기」を選択してください。'),
            ('‘한옥의 아침’을 선택하세요.', '「한옥의 아침」を選択してください。'),
            ('검색어: "홍건익가옥"', '検索語：「홍건익가옥」'),
        ]:
            with self.subTest(ko=ko):
                source = '[신청 방법]\n' + ko
                target = '[申請方法]\n' + ja
                validate_japanese_output('体験', target, source)
                self.assertEqual(checked_navigation_texts(source, target)[2], [])

    def test_missing_translated_or_changed_search_input_is_reported(self):
        source = '[신청 방법]\n‘도보관광’을 검색하세요.'
        for target in ['「徒歩観光」を検索してください。', '案内をご覧ください。',
                       '「도보 관광」を検索してください。', '도보관광を検索してください。']:
            with self.subTest(target=target), self.assertRaises(ValidationError):
                validate_japanese_output('体験', '[申請方法]\n' + target, source)

    def test_alternative_search_inputs_and_booking_item(self):
        source = '[신청 방법]\n‘백인제’ 또는 ‘백인제가옥’을 검색한 뒤 ‘2026 백인제가옥 전시해설 예약’에서 원하는 날짜와 회차를 선택하세요.'
        target = '[申請方法]\n「백인제」または「백인제가옥」を検索し、「2026 백인제가옥 전시해설 예약」で希望する日付と回を選択してください。'
        self.assertEqual(len(navigation_literals(source)), 3)
        validate_japanese_output('体験', target, source)
        with self.assertRaises(ValidationError):
            validate_japanese_output('体験', target.replace('「백인제」または', ''), source)

    def test_only_literal_is_exempt_not_title_or_surrounding_prose(self):
        source = '[신청 방법]\n‘도보관광’을 검색하세요.'
        good = '[申請方法]\n「도보관광」を検索してください。'
        for title, body in [('도보관광', good), ('体験', good + '\n보호자 동반 필수'),
                            ('体験', good + '\n「아무 검색어」を検索してください。'),
                            ('体験', good + '\n대상은 누구나입니다.')]:
            with self.subTest(body=body), self.assertRaises(ValidationError):
                validate_japanese_output(title, body, source)

    def test_ordinary_quotes_and_wrong_sections_never_authorize_hangul(self):
        for source in ['[대상]\n‘보호자 동반 필수’입니다.\n[신청 방법]\n예약하세요.',
                       '[주요 내용]\n‘서울 산책’ 프로그램입니다.',
                       '[대상]\n‘도보관광’을 검색하세요.\n[신청 방법]\n예약하세요.',
                       '[신청 방법]\n`검색어: "도보관광"`']:
            self.assertEqual(navigation_literals(source), [])
        with self.assertRaises(ValidationError):
            validate_japanese_output('体験', '[対象]\n「도보관광」を検索してください。\n[申請方法]\n予約します。',
                                     '[신청 방법]\n‘도보관광’을 검색하세요.')

    def test_region_glossary_still_applies_to_prose(self):
        source = '[신청 방법]\n‘서울특별시 예약’ 메뉴를 선택하세요.'
        target = '[申請方法]\n「서울특별시 예약」メニューを選択してください。'
        validate_japanese_output('体験', target, source)
        with self.assertRaises(ValidationError) as caught:
            validate_japanese_output('体験', target, '서울특별시에서 진행합니다.\n' + source)
        self.assertEqual(caught.exception.diagnostic['rule'], 'region_glossary')
        validate_japanese_output('体験', 'ソウル特別市で実施します。\n' + target,
                                 '서울특별시에서 진행합니다.\n' + source)

    def test_normal_japanese_unchanged_and_currency_guard_preserved(self):
        validate_japanese_output('体験', 'どなたでも申し込めます。', '누구나 신청할 수 있습니다.')
        with self.assertRaises(ValidationError) as caught:
            validate_japanese_output('体験', '[申請方法]\n「도보관광」を検索してください。料金は100円です。',
                                     '[신청 방법]\n‘도보관광’을 검색하세요.')
        self.assertEqual(caught.exception.diagnostic['rule'], 'translation_currency')

    def test_both_workers_pro_requests_and_rpc_preserve_literal_and_fences(self):
        import test_seoul_per_session_replay as replay
        original_case, translate = replay.recorded_case, replay.fake_translation
        ko = '‘도보관광’을 검색하세요.'
        ja = '「도보관광」（徒歩観光）を検索してください。'
        def case(classified=False):
            data, ctx = original_case(classified)
            native = ctx['nativeConfirmedFacts']['programFacts'] if classified else ctx['facts']
            native['description'] += '\n' + ko
            data['context']['facts'] = copy.deepcopy(native)
            data['summary']['content_ko'] += '\n' + ko
            return data, ctx
        def translated(body):
            return translate(body.replace(ko, '')) + '\n' + ja
        for classified in (False, True):
            with self.subTest(classified=classified), patch.object(replay, 'recorded_case', side_effect=case), \
                    patch.object(replay, 'fake_translation', side_effect=translated):
                result, calls, output, requests, _ = replay.run_recorded(self, classified=classified)
                self.assertEqual(result.completed, 1)
                self.assertEqual(len(requests), 2)
                self.assertIn(ko, output['contentKo'])
                self.assertIn(ja, output['contentJa'])
                self.assertIn(output['contentKo'], requests[1]['input'][0]['content'])
                self.assertIn('exact quoted Korean search input', requests[1]['instructions'])
                self.assertEqual(sum(name.startswith('finish_') for name, _ in calls), 1)


if __name__ == '__main__':
    unittest.main()
