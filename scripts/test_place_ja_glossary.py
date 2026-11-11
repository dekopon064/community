"""Offline name reuse and numeric protection; fake Pro/Auth/RPC only."""
import copy
import json
import socket
import unittest
from unittest.mock import patch

from ingest.ai_claude import SUMMARY_SYSTEM, SUMMARY_SCHEMA, summary_system_prompt, translation_system_prompt
from ingest.ai_errors import ValidationError
from ingest.ai_provider import create_provider_adapter
from ingest.place_ja_glossary import place_entries, numeric_name_views
from ingest.region_ja_glossary import validate_japanese_output
from ingest.translation_validation import _validate_cell, validate_translation_fidelity

# Public excerpts preserved in the 2026-11-04 first edit's before body for
# S260224104528968053. No current DB access and no real candidate identifiers.
KO_MEETING = '을지로3가역 8번 출구(지하철 2·3호선)에 출발 5분 전까지 도착해야 합니다.'
JA_LEGACY = 'ウルチロサムガ駅8番出口（地下鉄2・3号線）に出発5分前までに到着する必要があります。'
JA_PREFERRED = JA_LEGACY.replace('ウルチロサムガ駅', '乙支路3街駅')
KO_ROUTE = '을지로3가역 8번 출구 → 명보사거리 → 이순신 생가터 표지석 → 이순신 생가터 → 진양상가 공중보행로 → 중부시장 → 훈련원공원 → 하도감 터(동대문역사관1398)'
JA_ROUTE = '乙支路3街駅8番出口 → ミョンボ交差点 → 李舜臣の生家跡を示す標石 → 李舜臣の生家跡 → チニャン商街の空中歩道 → 中部市場 → フルリョヌォン公園 → 下都監跡（トンデムン歴史館1398）'


class PlaceNamesTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_registry_has_provenance_and_unambiguous_numeric_aliases(self):
        entries = place_entries()
        self.assertEqual(len({e['ko'] for e in entries}), len(entries))
        for e in entries:
            self.assertIn(e['ja'], e['accepted_ja'])
            self.assertTrue(all(s.startswith('https://') for s in e['sources']))

    def test_yisun_meeting_official_legacy_and_first_reading(self):
        for ja in (JA_LEGACY, JA_PREFERRED,
                   JA_LEGACY.replace('ウルチロサムガ駅', '乙支路3街（ウルチロサムガ）駅')):
            with self.subTest(ja=ja):
                _validate_cell(KO_MEETING, ja)

    def test_exit_line_arrival_and_station_errors_still_fail(self):
        for old, new in [('8番出口', '9番出口'), ('2・3号線', '2・4号線'),
                         ('5分前', '6分前'), ('ウルチロサムガ駅', 'ウルチロサガ駅')]:
            with self.subTest(change=new), self.assertRaises(ValidationError):
                _validate_cell(KO_MEETING, JA_LEGACY.replace(old, new))

    def test_clock_error_still_fails(self):
        ko = '을지로3가역 8번 출구, 14시30분 출발'
        _validate_cell(ko, '乙支路3街駅8番出口、14時30分出発')
        with self.assertRaises(ValidationError):
            _validate_cell(ko, '乙支路3街駅8番出口、14時出発')

    def test_other_station_reuses_verified_names(self):
        ko = '종로3가역 6번 출구, 지하철 1·3·5호선'
        for ja in ('鐘路3街駅6番出口、地下鉄1・3・5号線', 'チョンノサムガ駅6番出口、地下鉄1・3・5号線'):
            _validate_cell(ko, ja)
            with self.assertRaises(ValidationError):
                _validate_cell(ko, ja.replace('6番出口', '5番出口'))

    def test_route_distinct_stops_and_facility_identifier(self):
        self.assertEqual(len(KO_ROUTE.split(' → ')), 8)
        self.assertEqual(len(JA_ROUTE.split(' → ')), 8)
        _validate_cell(KO_ROUTE, JA_ROUTE)
        with self.assertRaises(ValidationError):
            _validate_cell(KO_ROUTE, JA_ROUTE.replace('1398', '1399'))

    def test_unlisted_names_do_not_gain_numeric_exemptions(self):
        _validate_cell('새봄공원 2번 입구', 'セボム公園2番入口')
        with self.assertRaises(ValidationError):
            _validate_cell('새봄공원 2번 입구', 'セボム公園3番入口')
        with self.assertRaises(ValidationError):
            _validate_cell('가상3역 8번 출구', 'カサンサム駅8番出口')

    def test_missing_or_reordered_names_are_not_masked(self):
        for ko, ja in [('을지로3가역 → 종로3가역', 'チョンノサムガ駅 → ウルチロサムガ駅'),
                       ('을지로3가역 → 을지로3가역', 'ウルチロサムガ駅')]:
            self.assertEqual(numeric_name_views(ko, ja), (ko, ja))
            with self.assertRaises(ValidationError):
                _validate_cell(ko, ja)

    def test_url_and_unknown_identifier_unchanged(self):
        ko = 'https://example.test/을지로3가역?id=3'
        ja = 'https://example.test/ウルチロサムガ駅?id=3'
        self.assertEqual(numeric_name_views(ko, ja), (ko, ja))
        with self.assertRaises(ValidationError):
            _validate_cell(ko, ja)
        with self.assertRaises(ValidationError):
            _validate_cell(KO_MEETING + ' B12', JA_LEGACY + ' B13')

    def test_hangul_and_region_protection_unchanged(self):
        for ja, ko in [('을지로3가역です。', '을지로3가역'), ('江南区です。', '강남구')]:
            with self.assertRaises(ValidationError):
                validate_japanese_output('案内', ja, ko)

    def test_shared_prompts_in_native_and_reclassification_paths(self):
        packets = [('', True), ('', 'myseoul')]
        for schema in ('program-scope-v1-local', 'myseoul-program-facts-v1-local'):
            packets.append((json.dumps({'inputContract':'review-classification-ai-v1',
                'nativeConfirmedFacts':{'programFacts':{'schema_version':schema}}}), False))
        for body, mode in packets:
            for prompt in (summary_system_prompt(body, mode), translation_system_prompt()):
                self.assertIn('을지로3가역 → 乙支路3街駅', prompt)
                self.assertIn('종로3가역 → 鐘路3街駅', prompt)
                self.assertIn('미등록만으로 오류로 보지 않고', prompt)
                self.assertIn('생가터와 표지석을 합치지 않고', prompt)

    def test_fake_pro_requests_for_both_sources(self):
        from test_ingest_ai_chatgpt_plan import streamed, verified_session
        from test_ingest_ai_openai import response
        ko = '[한 줄 요약]\n도보관광 안내입니다.\n\n[주요 내용]\n- ' + KO_MEETING + '\n- ' + KO_ROUTE
        ja = '[要約]\n徒歩観光のご案内です。\n\n[主な内容]\n- ' + JA_PREFERRED + '\n- ' + JA_ROUTE
        for method in ('summarize_program_ko', 'summarize_myseoul_ko'):
            with self.subTest(method=method):
                payload = {'content_ko':ko, 'facts':{k:'' for k in SUMMARY_SCHEMA['properties']['facts']['required']}}
                client = streamed([response(json.dumps(payload,ensure_ascii=False)),
                    response(json.dumps({'title_ja':'散策','content_ja':ja},ensure_ascii=False))])
                adapter = create_provider_adapter('chatgpt_plan', None, client=client, plan_session=verified_session())
                try:
                    body = getattr(adapter, method)(KO_ROUTE, None)[0]
                    translated = adapter.translate_ja('산책', body)[1]
                    validate_translation_fidelity('산책', body, '散策', translated)
                    self.assertEqual(translated, ja)
                    self.assertEqual(len(client.calls), 2)
                    for call in client.calls:
                        self.assertIn('을지로3가역 → 乙支路3街駅', call['instructions'])
                        self.assertNotIn('tools', call)
                finally:
                    adapter.close()

    def test_myseoul_fake_pro_and_rpc_completion(self):
        from test_ingest_ai_chatgpt_plan import streamed, verified_session
        from test_myseoul_gpt_pipeline import native_packet, native_client, GPTPipelineTests
        c = native_packet()
        before = copy.deepcopy(c)
        client = streamed(native_client(c).responses.results)
        def factory(**kw):
            return create_provider_adapter('chatgpt_plan', None, client=kw['client'], plan_session=verified_session())
        result, calls, adapter = GPTPipelineTests().native_run(c,client,adapter_factory=factory)
        try:
            self.assertEqual(result.completed,1)
            self.assertEqual(c,before)
            self.assertEqual([n for n,_ in calls], ['claim_myseoul_program_ai','admin_myseoul_program_detail','finish_myseoul_program_ai'])
            self.assertEqual(len(client.calls),2)
            self.assertTrue(all('Verified place/person names' in call['instructions'] for call in client.calls))
        finally:
            adapter.close()


if __name__ == '__main__':
    unittest.main()
