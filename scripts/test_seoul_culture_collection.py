"""Culture full-range collection: synthetic HTTP + atomic in-memory RPC only."""
import copy
import io
import json
import os
import socket
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from ingest.connectors.seoul_reservation import (
    CULTURE_SERVICE, SeoulCultureConnector, SeoulContractError,
    normalize_seoul_item, read_culture_collection,
)
from ingest.http_client import HttpClient
from ingest.program_db import ProgramNewOnlyObservationAdapter, program_rpc_item, new_only_payload_bytes
from ingest.rpc_errors import RpcAmbiguous, RpcFailure
from ingest.seoul_diagnostics import diagnose_culture_read
from ingest.seoul_workflow import plan_collection, process_seoul_collection
from test_seoul_reservation import row, envelope, Response, TEST_KEY

CAP = {'contract': 'seoul-new-only-v1', 'maxBatch': 40, 'category': '문화체험'}


def rows(n):
    return [row(sid=f'culture_{i:04d}') for i in range(n)]


def pages(items):
    return [Response(envelope(items[i:i + 1000], len(items), CULTURE_SERVICE))
            for i in range(0, len(items), 1000)] or [Response(envelope([], 0, CULTURE_SERVICE))]


class CultureCollectionTests(unittest.TestCase):
    def setUp(self):
        for guard in (
            patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')),
            patch('requests.get', side_effect=AssertionError('real HTTP forbidden')),
            patch('ingest.supabase_store.create_ingest_client', side_effect=AssertionError('DB forbidden')),
            patch('ingest.ai_provider.create_provider_adapter', side_effect=AssertionError('AI forbidden')),
        ):
            guard.start()
            self.addCleanup(guard.stop)

    def reader(self, responses, events=None):
        events = [] if events is None else events
        pending = iter(responses)
        def transport(url, **kwargs):
            self.assertFalse(kwargs['allow_redirects'])
            path = url.split('/json/', 1)[1]
            events.append(('HTTP', path))
            return next(pending)
        return SeoulCultureConnector(HttpClient(budget=2, max_attempts=1, transport=transport),
                                     api_key_provider=lambda: TEST_KEY), events

    def execute(self, responses, *, originals=None, failure=None, contract=CAP, raced=None, through_cli=False):
        stored = copy.deepcopy(originals or {})
        before = copy.deepcopy(stored)
        events = []
        connector, _ = self.reader(responses, events)
        def rpc(name, args):
            events.append((name, copy.deepcopy(args)))
            if name == 'seoul_collection_contract':
                return contract
            self.assertEqual(name, 'observe_seoul_program_new_only')
            if failure:
                raise failure
            if raced:
                stored.update(copy.deepcopy(raced))  # Concurrent insert before atomic key check.
            result = []
            for i, item in enumerate(args['p_items']):
                key = item['external_key']
                existing = key in stored
                if not existing:
                    stored[key] = copy.deepcopy(item)
                result.append(dict(inputIndex=i, externalKey=key,
                    id='30000000-0000-4000-8000-000000000001',
                    revision=stored[key].get('revision_hash', 'a' * 64),
                    outcome='existing_skipped' if existing else 'new_saved',
                    reviewWaiting=True, aiWaiting=False))
            return result
        store = SimpleNamespace(
            start_ingest_run=lambda *_a, **_k: (events.append(('start', None)) or SimpleNamespace(skipped=False, run_id='fake-run')),
            finish_ingest_run=lambda *_a, **kw: events.append(('finish', kw)),
        )
        if through_cli:
            from run_seoul_program_collection import main
            with patch.dict(os.environ, {'SUPABASE_URL': 'https://' + 'a' * 20 + '.supabase.co',
                                         'SUPABASE_SERVICE_KEY': 'synthetic-only'}, clear=True), \
                    patch('ingest.supabase_store.create_ingest_client', return_value='fake-client'), \
                    patch('ingest.supabase_store.SupabaseIngestStore', return_value=store), \
                    patch('ingest.supabase_store._rpc_data', side_effect=lambda _client, name, args: rpc(name, args)), \
                    patch('ingest.connectors.seoul_reservation.SeoulCultureConnector', return_value=connector), \
                    redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['--execute', '--project-ref', 'a' * 20]), 0)
            result = json.loads(output.getvalue())
        else:
            result = process_seoul_collection(store, ProgramNewOnlyObservationAdapter(rpc), connector)
        self.assertEqual({key: stored[key] for key in before}, before)
        return result, events, stored

    def test_full_read_boundaries_and_no_unnecessary_second_request(self):
        for n in (0, 1, 999, 1000, 1001, 1098, 2000):
            with self.subTest(n=n):
                c, events = self.reader(pages(rows(n)))
                result = read_culture_collection(c)
                self.assertTrue(result.natural_end)
                self.assertEqual(len(result.items), n)
                self.assertEqual(result.progress['total_count'], n)
                self.assertEqual(c.http.request_count, 1 if n <= 1000 else 2)
                self.assertEqual(events[0], ('HTTP', CULTURE_SERVICE + '/1/1000/'))
                if n > 1000:
                    self.assertEqual(events[1], ('HTTP', CULTURE_SERVICE + '/1001/2000/'))

    def test_global_sort_including_second_page_before_first_write(self):
        items = rows(1001)
        items[-1]['RCPTBGNDT'] = '2026-12-04 20:00:00.0'
        items[-1]['SVCSTATNM'] = '안내중'
        items[-1]['USETGTINFO'] = '청년, 가족'
        old = {'culture_0000': {'revision_hash': 'b' * 64, 'facts': {'verified': True},
                               'candidate': {'version': 7}, 'history': ['preserved']}}
        original = copy.deepcopy(items)
        result, events, stored = self.execute(pages(items), originals=old)
        writes = [args for name, args in events if name == 'observe_seoul_program_new_only']
        self.assertEqual([n for n, _ in events][:4], ['seoul_collection_contract', 'start', 'HTTP', 'HTTP'])
        sent = [item for args in writes for item in args['p_items']]
        self.assertEqual(sent[0]['external_key'], 'culture_1000')
        self.assertEqual([i['external_key'] for i in sent[1:]], sorted(i['SVCID'] for i in items[:-1]))
        self.assertTrue(all(len(a['p_items']) <= 40 for a in writes))
        self.assertEqual([a['p_next_checkpoint']['targetOffset'] for a in writes], list(range(40, 1001, 40)) + [1001])
        self.assertTrue(all(a['p_next_checkpoint']['page'] == 2 and a['p_next_checkpoint']['scanned'] == 1001 for a in writes))
        self.assertEqual((result['scanned'], result['new_saved'], result['existing_skipped']), (1001, 1000, 1))
        self.assertEqual((result['status'], result['unprocessed'], result['ai_calls']), ('complete', 0, 0))
        self.assertEqual(stored['culture_1000']['normalized_payload']['provider_fields']['SVCSTATNM'], '안내중')
        self.assertEqual(items, original)

    def test_state_and_audience_labels_not_body_or_parenthetical_text(self):
        items = [row(sid='ok_family', USETGTINFO='성인, 가족'),
                 row(sid='ok_youth', USETGTINFO='청년, 어르신'),
                 row(sid='ok_all', USETGTINFO='제한없음, 어린이', SVCSTATNM='안내중'),
                 row(sid='family', USETGTINFO='가족'),
                 row(sid='child', USETGTINFO='유아(성인 보호자 동반)'),
                 row(sid='missing', USETGTINFO=''), row(sid='unknown', USETGTINFO='미등록'),
                 row(sid='closed', SVCSTATNM='접수종료'), row(sid='full', SVCSTATNM='예약마감'),
                 row(sid='paused', SVCSTATNM='예약일시중지'), row(sid='blank_state', SVCSTATNM=''),
                 row(sid='other', MAXCLASSNM='교육강좌')]
        result, events, stored = self.execute(pages(items))
        self.assertEqual(set(stored), {'ok_family', 'ok_youth', 'ok_all'})
        self.assertEqual((result['scanned'], result['culture_count'], result['target']), (12, 11, 3))
        self.assertEqual((result['audience_excluded'], result['status_excluded'], result['other_category']), (4, 4, 1))
        self.assertEqual(result['new_saved'], 3)
        self.assertEqual(result['ai_calls'], 0)

    def test_date_precision_numeric_order_tie_and_unparseable_dates(self):
        items = [row(sid='a', RCPTBGNDT='2026-10-02'), row(sid='b', RCPTBGNDT='2026-10-02 00:00:00.0'),
                 row(sid='late', RCPTBGNDT='2026-10-02 09:00:00'), row(sid='early', RCPTBGNDT='2026-09-30'),
                 row(sid='missing', RCPTBGNDT=''), row(sid='bad', RCPTBGNDT='not-a-date'),
                 row(sid='old_bad', RCPTBGNDT='', SVCURL='invalid')]
        original = copy.deepcopy(items)
        plan = plan_collection(items, existing_keys=frozenset({'old_bad'}), natural_end=True)
        records = [r for batch in plan.batches for r in batch]
        self.assertEqual([r.external_key for r in records], ['late', 'a', 'b', 'early'])
        self.assertEqual(records[1].normalized_payload['dates']['RCPTBGNDT']['value'], '2026-10-02')
        self.assertEqual(records[1].normalized_payload['dates']['RCPTBGNDT']['precision'], 'day')
        self.assertEqual((plan.counters['failed'], plan.counters['existing_skipped']), (2, 1))
        self.assertTrue(all(e['error_code'] == 'seoul_reception_start_invalid' for e in plan.counters['item_errors']))
        self.assertEqual(items, original)
        reversed_plan = plan_collection(list(reversed(items)), existing_keys=frozenset({'old_bad'}), natural_end=True)
        self.assertEqual([r.external_key for b in reversed_plan.batches for r in b], ['late', 'a', 'b', 'early'])

    def test_over_2000_stops_after_one_read_and_never_stores_prefix(self):
        result, events, _ = self.execute([Response(envelope(rows(1000), 2001, CULTURE_SERVICE))])
        self.assertEqual(result['diagnostic']['error_code'], 'seoul_culture_range_exceeded')
        self.assertEqual(result['request_count'], 1)
        self.assertFalse(any(n == 'observe_seoul_program_new_only' for n, _ in events))

    def test_drift_overlap_revision_change_bad_shape_or_second_read_failure_never_stores(self):
        first = rows(1000)
        cases = [
            (Response(envelope([row(sid='new')], 1001, CULTURE_SERVICE)), first, 1002, 'seoul_listing_changed'),
            (Response(envelope([copy.deepcopy(first[0])], 1001, CULTURE_SERVICE)), first, 1001, 'seoul_repeated_page'),
            (Response(envelope([row(sid='culture_0000', SVCNM='changed')], 1001, CULTURE_SERVICE)), first, 1001, 'seoul_repeated_page'),
            (Response(envelope([], 1001, CULTURE_SERVICE)), first, 1001, 'seoul_page_shape_invalid'),
            (Response(data=b'not json'), first, 1001, 'invalid_json'),
            (Response({}, status=503), first, 1001, 'http_status_error'),
        ]
        for second, initial, total, expected in cases:
            with self.subTest(expected=expected):
                result, events, _ = self.execute([Response(envelope(initial, total, CULTURE_SERVICE)), second])
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['diagnostic']['error_code'], expected)
                self.assertEqual(result['request_count'], 2)
                self.assertFalse(any(n == 'observe_seoul_program_new_only' for n, _ in events))

    def test_partial_overlap_and_revision_drift_cannot_save_disjoint_suffix(self):
        first = rows(1000)
        for changed in (False, True):
            with self.subTest(changed=changed):
                repeated = copy.deepcopy(first[0])
                if changed:
                    repeated['SVCNM'] = 'changed'
                second = [repeated, row(sid='new')]
                result, events, _ = self.execute([
                    Response(envelope(first, 1002, CULTURE_SERVICE)),
                    Response(envelope(second, 1002, CULTURE_SERVICE)),
                ])
                self.assertEqual(result['diagnostic']['error_code'],
                    'seoul_revision_changed_during_scan' if changed else 'seoul_overlapping_pages')
                self.assertEqual(result['scanned'], 1000)
                self.assertFalse(any(n == 'observe_seoul_program_new_only' for n, _ in events))

    def test_existing_rpc_byte_limit_packs_large_descriptions_without_truncation(self):
        description = '<p>상세내용</p><p>' + '고유 안내 조건. ' * 7000 + '</p>'
        items = [row(sid=f'large_{i}', DTLCONT=description) for i in range(3)]
        plan = plan_collection(items, existing_keys=frozenset(), natural_end=True)
        self.assertGreater(len(plan.batches), 1)
        self.assertEqual(plan.counters['new_planned'], 3)
        for batch in plan.batches:
            self.assertLessEqual(new_only_payload_bytes([program_rpc_item(r) for r in batch]), 1_000_000)
            self.assertTrue(all(r.normalized_payload['source_body_html'] == description for r in batch))
        oversized = row(DTLCONT='<p>상세내용</p><p>' + '조건. ' * 40000 + '</p>')
        plan = plan_collection([oversized], existing_keys=frozenset(), natural_end=True)
        self.assertEqual(plan.counters['failed'], 1)
        self.assertEqual(plan.counters['item_errors'][0]['error_code'], 'seoul_store_item_too_large')

    def test_duplicate_in_excluded_rows_still_invalidates_scan(self):
        result, events, _ = self.execute(pages([row(sid='duplicate', USETGTINFO='가족')] * 2))
        self.assertEqual(result['diagnostic']['error_code'], 'seoul_duplicate_id_in_page')
        self.assertFalse(any(n == 'observe_seoul_program_new_only' for n, _ in events))

    def test_wrong_service_or_failed_first_request_has_no_fallback_or_retry(self):
        for response in (Response(envelope([row()])), Response({}, status=503), Response({}, status=302)):
            with self.subTest(status=response.status_code):
                result, events, _ = self.execute([response])
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['request_count'], 1)
                self.assertFalse(any(n == 'observe_seoul_program_new_only' for n, _ in events))

    def test_limits_and_contract_prevent_http_or_run(self):
        for budget, attempts in ((3, 1), (2, 3)):
            c = SeoulCultureConnector(HttpClient(budget=budget, max_attempts=attempts,
                transport=lambda *_a, **_k: self.fail('HTTP forbidden')))
            with self.assertRaises(SeoulContractError):
                process_seoul_collection(None, None, c)
        with self.assertRaisesRegex(ValueError, 'atomic_new_only'):
            self.execute([], contract={'contract': 'old'})

    def test_atomic_concurrent_existing_identity_preserves_different_revision_and_candidate(self):
        raced = {'TEST01': {'revision_hash': 'f' * 64, 'version': 8, 'candidate': 'keep', 'facts': {'keep': True}}}
        result, _, stored = self.execute(pages([row(SVCNM='changed source')]), raced=raced)
        self.assertEqual((result['new_saved'], result['existing_skipped']), (0, 1))
        self.assertEqual(stored, raced)

    def test_unknown_write_no_retry_or_finish_and_lease_failure_no_more_batches(self):
        for failure, status, finish in ((RpcAmbiguous(), 'state_unknown', False),
                                        (RpcFailure('lease_lost'), 'failed', True)):
            result, events, _ = self.execute(pages(rows(41)), failure=failure)
            self.assertEqual(result['status'], status)
            self.assertEqual(sum(n == 'observe_seoul_program_new_only' for n, _ in events), 1)
            self.assertEqual(any(n == 'finish' for n, _ in events), finish)
            self.assertEqual(result['unprocessed'], 41)

    def test_all_filtered_still_single_empty_ack_and_no_ai(self):
        result, events, _ = self.execute(pages([row(USETGTINFO='가족')]))
        writes = [a for n, a in events if n == 'observe_seoul_program_new_only']
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['p_items'], [])
        self.assertEqual((result['status'], result['new_saved'], result['ai_calls']), ('complete', 0, 0))

    def test_adapter_cannot_bypass_status_filter(self):
        adapter = ProgramNewOnlyObservationAdapter(lambda *_a: self.fail('RPC forbidden'))
        with self.assertRaisesRegex(ValueError, 'status_not_selected'):
            adapter.observe('fake', [normalize_seoul_item(row(SVCSTATNM='접수종료'))], None)

    def test_collection_cli_uses_culture_reader_and_authoritative_new_only_rpc(self):
        result, events, stored = self.execute(pages([row()]), through_cli=True)
        self.assertEqual((result['new_saved'], result['request_count'], result['ai_calls']), (1, 1, 0))
        self.assertEqual(set(stored), {'TEST01'})
        self.assertEqual(next(value for name, value in events if name == 'HTTP'), CULTURE_SERVICE + '/1/1000/')
        self.assertFalse(any(n.startswith(('claim', 'approve', 'publish')) for n, _ in events))

    def test_adapter_rejects_oversized_batch_before_rpc(self):
        description = '<p>상세내용</p><p>' + '고유 안내 조건. ' * 7000 + '</p>'
        records = [normalize_seoul_item(row(sid=f'large_{i}', DTLCONT=description)) for i in range(3)]
        adapter = ProgramNewOnlyObservationAdapter(lambda *_a: self.fail('RPC forbidden'))
        with self.assertRaisesRegex(ValueError, 'batch_bytes_invalid'):
            adapter.observe('fake', records, None)

    def test_read_only_diagnostic_and_default_cli_never_start_storage_or_ai(self):
        c, _ = self.reader(pages(rows(1001)))
        result = diagnose_culture_read(c)
        self.assertEqual((result['scanned'], result['request_count'], result['writes'], result['ai_calls']), (1001, 2, 0, 0))
        from run_seoul_program_collection import main
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([]), 0)
        policy = json.loads(output.getvalue())
        self.assertEqual((policy['api_service'], policy['max_scan_items'], policy['http_attempt_budget']), (CULTURE_SERVICE, 2000, 2))
        self.assertEqual(policy['status_any_of'], ['안내중', '접수중'])
        self.assertEqual(policy['ordering'], 'RCPTBGNDT_desc_then_SVCID')
        self.assertTrue(policy['full_range_required'])
        self.assertEqual(policy['network_calls'], 0)


if __name__ == '__main__':
    unittest.main()
