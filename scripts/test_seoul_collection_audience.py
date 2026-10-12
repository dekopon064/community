"""Collection audience policy: synthetic API and in-memory RPC only."""
import copy
import io
import json
import socket
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from ingest.seoul_audience import collection_audience
from ingest.seoul_workflow import plan_collection, process_seoul_collection
from ingest.program_db import ProgramNewOnlyObservationAdapter
from ingest.connectors.seoul_reservation import normalize_seoul_item, SeoulReservationConnector
from ingest.http_client import HttpClient
from ingest.seoul_diagnostics import diagnose_read
from ingest.rpc_errors import RpcAmbiguous
from test_seoul_reservation import row, Response, envelope, TEST_KEY


def page_rows():
    values = (['성인'] * 10 + ['제한없음'] * 5 + ['청년'] * 3
              + ['성인, 어린이(초등4학년 이상)'] * 2 + ['가족'] * 15
              + ['성인, 가족(학부모 1인, 자녀 1인)'] * 5
              + ['어린이(성인 보호자 동반)'] * 5 + ['', None, '미성인'])
    result = [row(sid=f'audience_{i}', USETGTINFO=v) for i, v in enumerate(values)]
    result += [row(sid=f'other_{i}', MAXCLASSNM='교육강좌') for i in range(2)]
    assert len(result) == 50
    return result


class SeoulCollectionAudienceTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_allowed_labels_and_conditions(self):
        for value in ('제한없음', ' 성인 ', '청년', '성인(자녀는 동석불가)',
                      '제한없음(유아4세 이상)', '청년（만19~39세）',
                      '성인(조건(확인 필요))', '성인, 청소년, 초등학생(4학년이상)',
                      '어린이 / 성인', '초등학생·청년', '성인, 미등록 대상'):
            with self.subTest(value=value):
                self.assertTrue(collection_audience(value).selected)

    def test_other_labels_do_not_override_any_allowed_label(self):
        for value in ('성인, 가족', '가족, 청년', '제한없음·가족（어린이 동반）',
                      '어린이, 성인', '청년, 어르신', '장애인, 청년'):
            with self.subTest(value=value):
                result = collection_audience(value)
                self.assertTrue(result.selected)
                self.assertEqual(result.reason, 'audience_selected')

    def test_nonselected_labels_alone_are_not_collected(self):
        for value in ('가족', '가족(학부모 1인, 자녀 1인)', '어린이, 가족', '어르신'):
            with self.subTest(value=value):
                self.assertFalse(collection_audience(value).selected)

    def test_parenthetical_words_are_conditions_not_selected_labels(self):
        for value in ('유아(성인 보호자 동반)', '가족(청년 부모)',
                      '초등학생(성인, 청년 동반 가능)', '기타(제한없음)'):
            with self.subTest(value=value):
                self.assertFalse(collection_audience(value).selected)
        # A family word in a condition does not manufacture a family target.
        self.assertTrue(collection_audience('성인(가족을 위한 부모교육)').selected)

    def test_missing_unknown_nonstring_and_substring_never_selected(self):
        for value in (None, '', '  ', [], {}, 3, True, 'RA08', '미성인',
                      '성인만', '성인 보호자', '청년가족', '제한없음 아님',
                      '성인(미완성', '성인)오류(', '성인,,청년', '성인（잘못된 괄호)',
                      '성인(설명) 임의 문장', '성인(설명) 청년(설명)'):
            with self.subTest(value=value):
                self.assertFalse(collection_audience(value).selected)

    def test_body_and_title_never_grant_collection_eligibility(self):
        rejected = row(USETGTINFO='어린이', SVCNM='성인 청년 합성 제목',
                       DTLCONT='<p>제한없음 성인 청년이라는 본문 안내</p>')
        plan = plan_collection([rejected], existing_keys=frozenset(), natural_end=True)
        self.assertEqual(plan.counters['target'], 0)
        self.assertEqual(plan.counters['audience_excluded'], 1)
        self.assertFalse(plan.batches)

    def test_collection_label_does_not_erase_nationality_restriction(self):
        value = '성인(내국인만)'
        plan = plan_collection([row(USETGTINFO=value)], existing_keys=frozenset(), natural_end=True)
        self.assertEqual(plan.counters['target'], 1)
        from ingest.program_db import program_rpc_item
        facts = program_rpc_item(plan.batches[0][0])['program_facts']
        self.assertEqual(facts['target_raw'], value)
        self.assertEqual(facts['application_actor'], 'nationality_excluded')

    def test_fifty_scan_separates_audience_and_eligible_existing_duplicates(self):
        rows = page_rows()
        before = copy.deepcopy(rows)
        # Nine known identities in the scanned page; only three are eligible.
        existing = frozenset([f'audience_{i}' for i in (0, 1, 2, 20, 21, 22, 23, 24)] + ['other_0'])
        plan = plan_collection(rows, existing_keys=existing, natural_end=False)
        for key, value in [('scanned', 50), ('culture_count', 48), ('target', 25),
                           ('audience_excluded', 23), ('other_category', 2),
                           ('existing_skipped', 3), ('new_planned', 22), ('ai_calls', 0)]:
            self.assertEqual(plan.counters[key], value, key)
        self.assertEqual(plan.counters['audience_excluded_by_reason'],
                         {'audience_not_selected': 21, 'audience_missing': 2})
        self.assertEqual(len(plan.counters['audience_exclusions']), 23)
        self.assertEqual([len(batch) for batch in plan.batches], [22])
        self.assertEqual(rows, before)
        self.assertEqual(plan.counters['coverage'], 'bounded_page_only')

    def test_all_fifty_eligible_keep_forty_ten_batch_limit(self):
        plan = plan_collection([row(sid=f'allowed_{i}', USETGTINFO='청년') for i in range(50)],
                               existing_keys=frozenset(), natural_end=False)
        self.assertEqual([len(batch) for batch in plan.batches], [40, 10])
        self.assertEqual(plan.counters['audience_excluded'], 0)
        with self.assertRaises(ValueError):
            plan_collection([row()] * 51, existing_keys=frozenset(), natural_end=False)

    def run_collection(self, rows, *, ambiguous=False):
        events, calls = [], []
        originals = {f'audience_{i}': {'history': ['yesterday'], 'candidate': 'preserved', 'revision': 'old'}
                     for i in range(3)}
        stored = copy.deepcopy(originals)
        def rpc(name, args):
            events.append((name, copy.deepcopy(args)))
            if name == 'seoul_collection_contract':
                return {'contract': 'seoul-new-only-v1', 'maxBatch': 40, 'category': '문화체험'}
            self.assertEqual(name, 'observe_seoul_program_new_only')
            if ambiguous:
                raise RpcAmbiguous()
            result = []
            for i, item in enumerate(args['p_items']):
                key = item['external_key']
                existing = key in stored
                if not existing:
                    stored[key] = copy.deepcopy(item)
                result.append(dict(inputIndex=i, externalKey=key,
                    id='30000000-0000-4000-8000-000000000001', revision=item['revision_hash'],
                    outcome='existing_skipped' if existing else 'new_saved', reviewWaiting=True, aiWaiting=False))
            return result
        store = SimpleNamespace(
            start_ingest_run=lambda *_a, **_k:SimpleNamespace(skipped=False, run_id='synthetic-run'),
            finish_ingest_run=lambda *_a, **kw:events.append(('finish', kw)))
        def transport(*_a, **_kw):
            calls.append(1)
            return Response(envelope(rows, 100))
        connector = SeoulReservationConnector(HttpClient(budget=1, max_attempts=1, transport=transport),
            api_key_provider=lambda:TEST_KEY, page_size=50, max_pages=1)
        result = process_seoul_collection(store, ProgramNewOnlyObservationAdapter(rpc), connector)
        self.assertEqual(len(calls), 1)
        self.assertEqual({k:stored[k] for k in originals}, originals)
        return result, events, stored

    def test_actual_collection_path_filters_before_fake_rpc_and_preserves_facts(self):
        rows = page_rows()
        rows[3]['USETGTINFO'] = '성인(자녀는 동석불가)'
        result, events, stored = self.run_collection(rows)
        self.assertEqual(result['scanned'], 50)
        self.assertEqual(result['target'], 25)
        self.assertEqual(result['audience_excluded'], 23)
        self.assertEqual(result['existing_skipped'], 3)
        self.assertEqual(result['new_saved'], 22)
        self.assertEqual(result['review_waiting'], 22)
        self.assertEqual(result['unprocessed'], 0)
        self.assertEqual(result['ai_calls'], 0)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['reason'], 'page_limit')
        self.assertEqual(stored['audience_3']['program_facts']['target_raw'], rows[3]['USETGTINFO'])
        self.assertEqual(stored['audience_3']['normalized_payload']['provider_fields']['USETGTINFO'], rows[3]['USETGTINFO'])
        writes = [args for name, args in events if name == 'observe_seoul_program_new_only']
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['p_next_checkpoint']['scanned'], 50)
        self.assertEqual(writes[0]['p_next_checkpoint']['targetOffset'], 25)
        self.assertFalse(any(name.startswith(('claim', 'publish', 'approve')) for name, _ in events))

    def test_all_excluded_page_only_acknowledges_bounded_scan(self):
        result, events, _ = self.run_collection([row(sid=f'family_{i}', USETGTINFO='가족') for i in range(50)])
        self.assertEqual(result['new_saved'], 0)
        self.assertEqual(result['audience_excluded'], 50)
        self.assertEqual(result['unprocessed'], 0)
        self.assertEqual(next(a['p_items'] for n, a in events if n == 'observe_seoul_program_new_only'), [])
        self.assertEqual(result['status'], 'incomplete')

    def test_existing_now_family_is_preserved_without_refresh_or_deletion(self):
        rows = page_rows()
        for i in range(3):
            rows[i]['USETGTINFO'] = '가족'
        result, events, stored = self.run_collection(rows)
        self.assertEqual(result['existing_skipped'], 0)
        self.assertEqual(result['target'], 22)
        self.assertEqual(result['new_saved'], 22)
        sent = [v['external_key'] for n, a in events if n == 'observe_seoul_program_new_only' for v in a['p_items']]
        self.assertTrue(all(f'audience_{i}' not in sent for i in range(3)))
        self.assertEqual(stored['audience_0']['candidate'], 'preserved')

    def test_unknown_write_never_retries_or_finishes_run(self):
        result, events, _ = self.run_collection(page_rows(), ambiguous=True)
        self.assertEqual(result['status'], 'state_unknown')
        self.assertEqual(result['unprocessed'], 25)
        self.assertEqual(sum(n == 'observe_seoul_program_new_only' for n, _ in events), 1)
        self.assertFalse(any(n == 'finish' for n, _ in events))

    def test_new_only_adapter_cannot_bypass_audience_selection(self):
        adapter = ProgramNewOnlyObservationAdapter(lambda *_:self.fail('RPC forbidden'))
        for value in ('가족', '어린이, 가족', '어린이', ''):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'audience_not_selected'):
                adapter.observe('fake', [normalize_seoul_item(row(USETGTINFO=value))], None)

    def test_diagnostic_reports_scan_culture_and_selected_separately(self):
        connector = SeoulReservationConnector(HttpClient(budget=1, max_attempts=1,
            transport=lambda *_a, **_kw:Response(envelope(page_rows(), 100))), api_key_provider=lambda:TEST_KEY)
        result = diagnose_read(connector)
        self.assertEqual(result['scanned'], 50)
        self.assertEqual(result['culture_count'], 48)
        self.assertEqual(result['target_count'], 25)
        self.assertEqual(result['audience_excluded'], 23)
        self.assertEqual(result['valid_target_count'], 25)
        self.assertEqual(result['request_count'], 1)
        self.assertEqual(result['writes'], 0)
        self.assertEqual(result['ai_calls'], 0)

    def test_validation_only_cli_documents_policy_without_execution(self):
        from run_seoul_program_collection import main
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['audience_any_of'], ['제한없음', '성인', '청년'])
        self.assertNotIn('audience_exclude', result)
        self.assertEqual((result['page_size'], result['max_pages'], result['store_batch_size']), (50, 1, 40))
        self.assertEqual(result['network_calls'], 0)


if __name__ == '__main__':
    unittest.main()
