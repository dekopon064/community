"""CSV link replay (not current API bodies), synthetic API and fenced RPC only."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_seoul_culture_collection as collection
from ingest.connectors.seoul_reservation import (
    SeoulContractError, SeoulCultureConnector, SeoulReservationConnector,
    normalize_seoul_item, SOURCE_FIELDS, CULTURE_SERVICE,
)
from ingest.program_db import program_rpc_item
from ingest.program_db import ProgramNewOnlyObservationAdapter
from ingest.seoul_links import seoul_source_link
from ingest.rpc_errors import RpcAmbiguous, RpcFailure
from test_seoul_reservation import row, Response, envelope

FIXTURE = Path(__file__).parent / 'fixtures/seoul_culture_external_links_csv.json'
MIGRATION = Path(__file__).parents[1] / 'supabase/migrations/20261014163727_seoul_culture_external_url_validation.sql'


class CultureExternalLinkTests(unittest.TestCase):
    # Reuse the existing bounded collection's guarded fake dependencies.
    setUp = collection.CultureCollectionTests.setUp
    reader = collection.CultureCollectionTests.reader

    def execute(self, *args, server_external=True, **kwargs):
        # Model the protected server URL predicate too, rather than accepting
        # every client payload. Both current-server rejection and the proposed
        # extended predicate are tested; no real database is connected.
        class CheckedAdapter(ProgramNewOnlyObservationAdapter):
            def __init__(adapter_self, rpc):
                def checked_rpc(name, params):
                    if name == 'observe_seoul_program_new_only':
                        for item in params['p_items']:
                            url = item['program_facts']['official_url']
                            try:
                                link = seoul_source_link(url, item['external_key'], culture_external=server_external)
                            except ValueError:
                                raise RpcFailure('invalid_official_url') from None
                            if url and link['url'] != url:
                                raise RpcFailure('invalid_official_url')
                    return rpc(name, params)
                super().__init__(checked_rpc)
        with patch.object(collection, 'ProgramNewOnlyObservationAdapter', CheckedAdapter), \
                patch('ingest.program_db.ProgramNewOnlyObservationAdapter', CheckedAdapter):
            return collection.CultureCollectionTests.execute(self, *args, **kwargs)

    def csv_links(self):
        fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.assertEqual(fixture['provenance']['kind'], 'user_csv_snapshot')
        self.assertTrue(fixture['provenance']['not_current_api_response'])
        self.assertTrue(fixture['provenance']['synthetic_other_fields'])
        self.assertEqual(len(fixture['links']), 18)
        return fixture['links']

    def csv_rows(self):
        return [row(sid=x['svc_id'], SVCNM=x['title'], SVCURL=x['svc_url']) for x in self.csv_links()]

    def normalize(self, url, sid='synthetic'):
        return normalize_seoul_item(row(sid=sid, SVCURL=url), culture_external_links=True)

    def test_all_eighteen_csv_links_have_a_separate_type_and_unchanged_raw_revision(self):
        items = self.csv_rows()
        before = copy.deepcopy(items)
        for item in items:
            with self.subTest(sid=item['SVCID']):
                record = normalize_seoul_item(item, culture_external_links=True)
                link = record.normalized_payload['source_link']
                self.assertEqual(link['kind'], 'culture_external')
                self.assertEqual(link['original'], item['SVCURL'])
                self.assertEqual(record.normalized_payload['provider_fields']['SVCURL'], item['SVCURL'])
                raw = {k: '' if item.get(k) is None else str(item[k]).strip() for k in SOURCE_FIELDS}
                expected = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True,
                    separators=(',', ':')).encode('utf-8')).hexdigest()
                self.assertEqual(record.revision_hash, expected)
                self.assertEqual(record.external_key, item['SVCID'])
        self.assertEqual(items, before)

    def test_the_two_csv_html_ampersands_change_only_the_usable_query_separators(self):
        escaped = [x for x in self.csv_links() if '&amp;' in x['svc_url']]
        self.assertEqual(len(escaped), 2)
        expected = {
            'XML-gangseo6082-6': 'https://www.kctg.or.kr/tour/touristSiteView.do?page_no=&tourist_cd=TOURIST_ID00011576',
            'XML-animal6804': 'https://culture.gangseo.seoul.kr/gsfc/education/view.do?eduSn=178&menuNo=800042',
        }
        for x in escaped:
            record = self.normalize(x['svc_url'], x['svc_id'])
            payload = program_rpc_item(record)
            self.assertEqual(payload['program_facts']['official_url'], expected[x['svc_id']])
            self.assertEqual(payload['normalized_payload']['source_url'], expected[x['svc_id']])
            self.assertTrue(payload['normalized_payload']['source_link']['ampersand_decoded'])
            self.assertEqual(payload['normalized_payload']['source_link']['original'], x['svc_url'])
            self.assertEqual(payload['normalized_payload']['provider_fields']['SVCURL'], x['svc_url'])

    def test_bare_ampersands_percent_values_and_raw_whitespace_are_not_rewritten(self):
        url = 'https://culture.gangseo.seoul.kr/gsfc/education/view.do?eduSn=178&menuNo=800042'
        record = self.normalize('  ' + url + '  ')
        self.assertEqual(record.normalized_payload['source_url'], url)
        self.assertEqual(record.normalized_payload['source_link']['original'], '  ' + url + '  ')
        self.assertFalse(record.normalized_payload['source_link']['ampersand_decoded'])
        percent = 'https://kctg.or.kr/tour/touristSiteView.do?tourist_cd=TOURIST%5FID00011134'
        self.assertEqual(self.normalize(percent).normalized_payload['source_url'], percent)

    def test_ampersands_decode_once_and_never_hide_a_raw_revision_change(self):
        prefix = 'https://culture.gangseo.seoul.kr/gsfc/education/view.do?eduSn=178'
        records = []
        for separator in ('&', '&amp;', '&#38;', '&#x26;'):
            record = self.normalize(prefix + separator + 'menuNo=800042')
            records.append(record)
            self.assertEqual(record.normalized_payload['source_url'], prefix + '&menuNo=800042')
        self.assertEqual(len({x.revision_hash for x in records}), 4)
        with self.assertRaisesRegex(SeoulContractError, '^seoul_link_invalid$'):
            self.normalize(prefix + '&amp;amp;menuNo=800042')

    def test_legacy_connector_stays_strict_while_culture_observation_enables_external_type(self):
        legacy, culture = SeoulReservationConnector(), SeoulCultureConnector()
        for item in self.csv_rows():
            with self.assertRaisesRegex(SeoulContractError, '^seoul_link_invalid$'):
                normalize_seoul_item(item)
            with self.assertRaises(SeoulContractError):
                legacy.to_observation(item, permission_status='testing_only', enabled=False)
            record = culture.to_observation(item, permission_status='testing_only', enabled=False)
            self.assertEqual(record.normalized_payload['source_link']['kind'], 'culture_external')

    def test_own_detail_identity_and_missing_url_contract_stay_separate(self):
        normal = normalize_seoul_item(row(), culture_external_links=True)
        self.assertEqual(normal.normalized_payload['source_link']['kind'], 'reservation_detail')
        self.assertEqual(normal.normalized_payload['source_url'], row()['SVCURL'])
        self.assertEqual(normal.revision_hash, normalize_seoul_item(row()).revision_hash)
        missing = self.normalize('')
        self.assertFalse(missing.has_source_url)
        self.assertIsNone(missing.normalized_payload['source_url'])
        self.assertEqual(missing.normalized_payload['source_link']['kind'], 'missing')
        for url in (row()['SVCURL'].replace('TEST01', 'OTHER'),
                    row()['SVCURL'] + '&redirect=https://evil.test', row()['SVCURL'] + '#other'):
            with self.assertRaises(SeoulContractError):
                self.normalize(url, 'TEST01')

    def test_external_origin_route_and_query_validation_rejects_unsafe_or_unsupported_values(self):
        base = 'https://culture.gangseo.seoul.kr/gsfc/education/view.do'
        bad = [
            'javascript:alert(1)', 'data:text/html,hello', '//culture.gangseo.seoul.kr/gsfc/education/view.do?eduSn=1',
            'https://evil.test/gsfc/education/view.do?eduSn=1',
            'https://culture.gangseo.seoul.kr.evil.test/gsfc/education/view.do?eduSn=1',
            'https://culture.gangseo.seoul.kr@evil.test/gsfc/education/view.do?eduSn=1',
            'https://evil.test@culture.gangseo.seoul.kr/gsfc/education/view.do?eduSn=1',
            'https://culture.gangseo.seoul.kr:443/gsfc/education/view.do?eduSn=1',
            'https://127.0.0.1/gsfc/education/view.do?eduSn=1',
            'http://culture.gangseo.seoul.kr/gsfc/education/view.do?eduSn=1',
            base.replace('/view.do', '/unknown.do') + '?eduSn=1',
            base + '?menuNo=1', base + '?eduSn=', base + '?eduSn=1&eduSn=2',
            base + '?eduSn=1&menuNo=2&redirect=https://evil.test',
            base + '?eduSn=1&amp;redirect=', base + '?eduSn=1#next',
            base + '?eduSn=1%0A', base + '?eduSn=1\\bad', base + '?eduSn=1\n',
            base + '?eduSn=1\x00', base + '?eduSn=1&' + 'x' * 2048,
        ]
        for url in bad:
            with self.subTest(url=url):
                with self.assertRaisesRegex(SeoulContractError, '^seoul_link_invalid$'):
                    self.normalize(url)

    def test_each_institution_requires_its_own_query_shape_not_a_seoul_svcid(self):
        for url in (
            'https://kctg.or.kr/tour/touristSiteView.do?tourist_cd=&page_no=1',
            'https://kctg.or.kr/tour/touristSiteView.do?tourist_cd=T1&page_no=bad',
            'https://firesafety.eseoul.go.kr/multi/main.do?redirect=evil',
            'https://umppa.seoul.go.kr/icare/user/chilProgrm/orgideaExprnCtzn/BD_selectOrgideaExprnCtzn.do?q_progrmSn=1',
        ):
            with self.assertRaises(SeoulContractError):
                self.normalize(url)

    def test_fake_api_and_rpc_store_csv_links_and_preserve_existing_values_and_candidates(self):
        items = self.csv_rows()
        old = {items[0]['SVCID']: dict(revision_hash='b' * 64,
            facts={'official_url': 'https://original.test', 'version': 3},
            filters={'version': 5}, candidate={'body': 'keep', 'version': 7},
            snapshot={'fence': 'keep'}, history=['preserved'])}
        result, events, stored = self.execute(collection.pages(items), originals=old)
        self.assertEqual((result['target'], result['new_saved'], result['existing_skipped']), (18, 17, 1))
        self.assertEqual((result['status'], result['failed'], result['ai_calls']), ('complete', 0, 0))
        self.assertEqual(stored[items[0]['SVCID']], old[items[0]['SVCID']])
        for item in items[1:]:
            payload = stored[item['SVCID']]
            self.assertEqual(payload['normalized_payload']['source_link']['original'], item['SVCURL'])
            self.assertEqual(payload['normalized_payload']['provider_fields']['SVCURL'], item['SVCURL'])
            self.assertEqual(payload['program_facts']['official_url'], payload['normalized_payload']['source_url'])
            self.assertEqual((payload['jobs'], payload['relationships']), ([], []))

    def test_current_server_predicate_still_rejects_external_links_until_server_change(self):
        result, events, stored = self.execute(collection.pages(self.csv_rows()), server_external=False)
        self.assertEqual((result['status'], result['new_saved'], result['ai_calls']), ('failed', 0, 0))
        self.assertEqual(stored, {})
        self.assertEqual(sum(n == 'finish' for n, _ in events), 1)

    def test_server_migration_changes_only_the_original_url_predicate_and_retains_acl_guards(self):
        base = (Path(__file__).parents[1] / 'supabase/migrations/20261001000000_seoul_program_contract.sql').read_text(encoding='utf-8')
        draft = MIGRATION.read_text(encoding='utf-8')
        old_check = draft.split('$old$', 2)[1]
        self.assertEqual(base.count(old_check), 1)
        self.assertIn('execute replace(definition,old_check,new_check)', draft)
        self.assertIn('proacl is not distinct from old_acl', draft)
        self.assertIn('proconfig=old_config', draft)
        self.assertIn('seoul_program_url_prerequisite_changed', draft)
        self.assertNotIn('grant ', draft.lower())
        for blocked in ('insert into ', 'update machimoa_review.', 'delete from ', 'alter table ', 'create policy '):
            self.assertNotIn(blocked, draft.lower())
        for x in self.csv_links():
            from urllib.parse import urlsplit
            u = urlsplit(x['svc_url'])
            self.assertIn(u.netloc + u.path, draft)

    def test_two_pages_cli_sort_batch_limit_and_new_only_rpc_share_the_link_classifier(self):
        items = collection.rows(1001)
        for i, item in enumerate(self.csv_rows()):
            items[i + 11] = item
        items[-1]['RCPTBGNDT'] = '2026-12-04 20:00:00.0'
        items[-1]['USETGTINFO'] = '청년, 가족'
        before = copy.deepcopy(items)
        result, events, stored = self.execute(collection.pages(items), through_cli=True)
        self.assertEqual((result['request_count'], result['new_saved'], result['failed'], result['ai_calls']), (2, 1001, 0, 0))
        self.assertEqual(items, before)
        self.assertEqual(sum(x['normalized_payload']['source_link']['kind'] == 'culture_external'
                             for x in stored.values()), 18)
        writes = [a for n, a in events if n == 'observe_seoul_program_new_only']
        self.assertTrue(all(len(x['p_items']) <= 40 for x in writes))
        self.assertEqual(writes[0]['p_items'][0]['external_key'], 'culture_1000')
        self.assertEqual([n for n, _ in events][:4], ['seoul_collection_contract', 'start', 'HTTP', 'HTTP'])

    def test_invalid_links_ids_and_excluded_targets_do_not_stop_normal_items(self):
        valid = self.csv_rows()[0]
        bad_url = row(sid='bad_url', SVCURL='https://evil.test/?private=synthetic')
        bad_id = row(sid='bad?identity', SVCURL=valid['SVCURL'])
        family = row(sid='family', SVCURL=valid['SVCURL'], USETGTINFO='가족, 어린이')
        closed = row(sid='closed', SVCURL=valid['SVCURL'], SVCSTATNM='접수종료')
        result, events, stored = self.execute(collection.pages([valid, bad_url, bad_id, family, closed]))
        self.assertEqual(set(stored), {valid['SVCID']})
        self.assertEqual((result['failed'], result['invalid_id_count'], result['status_excluded'], result['audience_excluded']), (2, 1, 1, 1))
        self.assertEqual([x['error_code'] for x in result['item_errors']], ['seoul_link_invalid', 'seoul_id_invalid'])
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual((result['status'], result['reason']), ('incomplete', 'invalid_items'))

    def test_existing_id_with_changed_external_url_is_atomically_skipped(self):
        item = self.csv_rows()[0]
        item['SVCURL'] = 'https://kctg.or.kr/tour/touristSiteView.do?tourist_cd=DIFFERENT123'
        old = {item['SVCID']: dict(revision_hash='c' * 64, facts={'version': 2}, candidate={'version': 9})}
        result, _, stored = self.execute(collection.pages([item]), originals=old)
        self.assertEqual((result['new_saved'], result['existing_skipped']), (0, 1))
        self.assertEqual(stored, old)

    def test_raw_url_revision_drift_or_duplicate_page_never_stores_a_prefix(self):
        first = collection.rows(1000)
        first[899] = self.csv_rows()[0]
        changed = copy.deepcopy(first[899])
        changed['SVCURL'] = changed['SVCURL'].replace('&amp;', '&')
        result, events, stored = self.execute([
            Response(envelope(first, 1002, CULTURE_SERVICE)),
            Response(envelope([changed, row(sid='new')], 1002, CULTURE_SERVICE)),
        ])
        self.assertEqual(result['diagnostic']['error_code'], 'seoul_revision_changed_during_scan')
        self.assertEqual(stored, {})
        self.assertFalse(any(n == 'observe_seoul_program_new_only' for n, _ in events))

    def test_rpc_ambiguity_never_retries_or_finishes_and_known_failure_is_not_success(self):
        for failure in (RpcAmbiguous(), RpcFailure('rpc_failure')):
            with self.subTest(error=type(failure).__name__):
                result, events, stored = self.execute(collection.pages(self.csv_rows()), failure=failure)
                self.assertEqual(sum(n == 'observe_seoul_program_new_only' for n, _ in events), 1)
                self.assertEqual(result['ai_calls'], 0)
                self.assertEqual(stored, {})
                if isinstance(failure, RpcAmbiguous):
                    self.assertEqual(result['status'], 'state_unknown')
                    self.assertFalse(any(n == 'finish' for n, _ in events))
                else:
                    self.assertEqual(result['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
