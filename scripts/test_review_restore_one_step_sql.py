"""Restore through the real RPCs in an isolated PostgreSQL database."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from ingest.content_filters import extract_filter_facts, field
from test_myseoul_db import fixtures as myseoul_fixtures
from test_program_db import fixtures as seoul_fixtures
from test_seoul_culture_external_links_sql import CONTAINER, docker, literal

ROOT = Path(__file__).resolve().parents[1]
ACTOR = '00000000-0000-4000-8000-000000000001'
SOURCES = ('seoul_reservation', 'myseoul_program', 'youthcenter_policy', 'youthcenter_content')


def main():
    meta = json.loads(docker(['inspect', CONTAINER]))[0]
    assert meta['State']['Running'] and meta['HostConfig']['NetworkMode'] == 'none'
    assert not meta['HostConfig']['PortBindings'] and not meta['HostConfig']['Binds']
    assert meta['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
    assert all(m['Type'] == 'volume' and m['Name'] == CONTAINER + '-data' for m in meta['Mounts'])
    assert json.loads(docker(['context', 'inspect']))[0]['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'
    # Schema-only snapshot from the local Seoul review-evidence SQL rehearsal.
    schema = docker(['exec', CONTAINER, 'pg_dump', '-U', 'postgres', '-d',
                     'seoul_review_evidence_local_d27ba5c00ce6', '--schema-only',
                     '--schema=public', '--schema=machimoa_review'])
    db = 'review_restore_local_' + uuid4().hex[:12]
    docker(['exec', CONTAINER, 'createdb', '-U', 'postgres', db])

    def sql(query):
        return docker(['exec', '-i', CONTAINER, 'psql', '-XqAt', '-U', 'postgres', '-d', db,
                       '-v', 'ON_ERROR_STOP=1'],
                      "set statement_timeout='15s';set lock_timeout='5s';" + query)

    def rpc(name, *args):
        return json.loads(sql('begin;set local role service_role;select public.' +
                              name + '(' + ','.join(map(literal, args)) + ');commit;'))

    def denied(call, message):
        try:
            call()
        except RuntimeError as error:
            assert message in str(error), str(error)
        else:
            raise AssertionError('Expected ' + message)

    def current(source, sid):
        if source == 'seoul_reservation':
            return rpc('admin_program_detail', sid)
        if source == 'myseoul_program':
            return rpc('admin_myseoul_program_detail', sid)
        return rpc('admin_review_detail', 'facts', sid)

    def exclude(item):
        rpc('admin_review_exclude_reason', item['id'], item['revision'], item['version'],
            'service_not_suitable', '', ACTOR, str(uuid4()))
        return next(e for e in rpc('admin_review_trash', 0, 25)['items']
                    if e['sourceItemId'] == item['id'])

    def restore(entry, request=None):
        return rpc('admin_review_restore', entry['id'], entry['revision'], entry['version'],
                   ACTOR, request or str(uuid4()))['item']

    def create_seoul(key):
        item = copy.deepcopy(seoul_fixtures(storage=True)[0]['item'])
        f = item['program_facts']
        f['official_url'] = 'https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=' + key
        item.update(external_key=key, revision_hash=uuid4().hex * 2)
        item['normalized_payload'].update(title='합성 동작구 문화관광해설', source_url=f['official_url'])
        item['normalized_payload']['provider_fields'].update(SVCID=key)
        f.update(delivery_mode='unknown', activity_region='unknown', activity_evidence=[])
        item['filterFacts'] = extract_filter_facts('seoul_reservation', item['normalized_payload'], f)
        filters = item['filterFacts']
        for name, value in {'topic': 'culture_experience', 'audience': 'other'}.items():
            filters['data'][name] = field(value)
            filters['evidence'][name] = {'sourceField': 'payload.program_text', 'excerpt': f['description'].splitlines()[0]}
        for name in ('delivery', 'location'):
            filters['data'][name] = field()
            filters['evidence'].pop(name, None)
        sid = rpc('observe_seoul_program_new_only', runs['seoul_reservation'], [item], None)[0]['id']
        return current('seoul_reservation', sid)

    def save_filters(item):
        location = field({'scope': 'specific', 'venues': [
            {'province': '11', 'district': '동작구', 'facility': '', 'address': ''}]})
        return rpc('admin_content_filter_save', item['id'], item['revision'], item['version'],
                   item['filterInfo']['filterVersion'], {'delivery': field('onsite'), 'location': location}, ACTOR)

    def create_myseoul():
        item = next(f['item'] for f in myseoul_fixtures()['fixtures'] if f['name'] == 'missing_mode')
        sid = rpc('observe_myseoul_program', runs['myseoul_program'], [item], None)[0]['id']
        return current('myseoul_program', sid)

    def create_youth(source):
        rev = uuid4().hex * 2
        sid = json.loads(sql("insert into machimoa_review.source_items(source_id,external_key,revision_hash,first_seen_at,last_seen_at,source_created_parse_status,source_updated_parse_status,disposition,min_fields,normalized_payload,has_source_url,body_usable) values(" +
                             ','.join(map(literal, [source, uuid4().hex, rev])) +
                             ",now(),now(),'missing','missing','target','{}','{\"title\":\"합성 청년센터\",\"source_url\":\"https://example.invalid\"}',true,true) returning to_jsonb(id);"))
        sql("insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes) values(" +
            ','.join(map(literal, [sid, rev])) +
            ",'content_review','queued',now(),now(),array['user_category_unconfirmed']);")
        return current(source, sid)

    try:
        sql(schema.replace('CREATE SCHEMA public;', '-- fresh public exists', 1))
        for source in SOURCES:
            sql('insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values(' +
                ','.join(map(literal, [source, 'synthetic', 'content', 'rest', True, 'approved_noncommercial', source])) +
                ');insert into machimoa_review.source_sync_state(source_id) values(' + literal(source) + ');')
        runs = {s: json.loads(sql('select to_jsonb(run_id) from public.start_ingest_run(' + literal(s) + ',3600);'))
                for s in SOURCES[:2]}

        legacy = restore(exclude(create_seoul('SYNTH_RESTORE_LEGACY')))
        assert legacy['restoredReviewPending']
        sql(next((ROOT / 'supabase/migrations').glob('*_restore_review_in_one_step.sql')).read_text(encoding='utf8'))
        denied(lambda: save_filters({**legacy, 'version': 'f' * 64}), 'review_conflict')
        assert current('seoul_reservation', legacy['id'])['restoredReviewPending']
        save_filters(legacy)
        assert not current('seoul_reservation', legacy['id'])['restoredReviewPending']

        original = create_seoul('SYNTH_RESTORE_DONGJAK')
        entry = exclude(original)
        request = str(uuid4())
        denied(lambda: restore({**entry, 'version': '0' * 64}), 'review_conflict')
        denied(lambda: sql('set role authenticated;select public.admin_review_restore(' +
                           ','.join(map(literal, [entry['id'], entry['revision'], entry['version'], ACTOR, request])) + ');'),
               'permission denied')
        with ThreadPoolExecutor(max_workers=2) as pool:
            restored, retry = list(pool.map(lambda _: restore(entry, request), range(2)))
        assert restored == retry and restored['status'] == 'open' and not restored['restoredReviewPending']
        assert restored['facts'] == original['facts'] and restored['filterInfo'] == original['filterInfo']
        assert [x['action'] for x in restored['history']].count('restore') == 1
        denied(lambda: restore(entry), 'review_already_processed')
        save_filters(restored)
        now = current('seoul_reservation', original['id'])
        assert now['facts']['delivery_mode'] == 'offline' and now['facts']['activity_region'] == 'capital'
        assert now['filterInfo']['data']['location']['value']['venues'][0]['district'] == '동작구'
        assert restore(entry, request)['version'] == now['version']

        my = create_myseoul()
        restored = restore(exclude(my))
        assert restored['source']['name'] == 'myseoul_program' and restored['status'] == 'open'
        assert not restored['restoredReviewPending'] and restored['facts'] == my['facts']

        for source in SOURCES[2:]:
            youth = create_youth(source)
            restored = restore(exclude(youth))
            assert restored['source']['name'] == source and not restored['restoredReviewPending']
            assert restored['status'] == 'open' and restored['facts'] == youth['facts']

        ready = create_seoul('SYNTH_RESTORE_READY')
        ready_filter = save_filters(ready)
        ready = current('seoul_reservation', ready['id'])
        assert ready_filter['data']['delivery'] == field('onsite')
        assert ready['aiStatus'] == 'queued'
        ready_job = json.loads(sql("select to_jsonb(id) from machimoa_review.processing_jobs where source_item_id=" +
                                   literal(ready['id']) + " and processing_stage='ai_enrichment';"))
        # Model a stale human-review reason on a fully supported source.
        complete = create_seoul('SYNTH_RESTORE_COMPLETE')
        save_filters(complete)
        complete = current('seoul_reservation', complete['id'])
        assert complete['status'] == 'resolved' and complete['aiStatus'] == 'queued'
        complete_id = literal(complete['id'])
        sql("update machimoa_review.source_item_program_facts set result="
            + literal({'decision': 'review_required', 'disposition': 'observe_only',
                       'reasons': ['activity_location_unknown']}) +
            " where source_item_id=" + complete_id + ";"
            "update machimoa_review.processing_jobs set status='cancelled',completed_at=now() where source_item_id="
            + complete_id + " and processing_stage='ai_enrichment';"
            "insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)"
            " values(" + complete_id + "," + literal(complete['revision']) +
            ",'content_review','queued',now(),now(),array['activity_location_unknown']) "
            "on conflict(source_item_id,revision_hash,processing_stage) do update "
            "set status='queued',completed_at=null,reason_codes=excluded.reason_codes;")
        restored = restore(exclude(current('seoul_reservation', complete['id'])))
        assert restored['status'] == 'resolved' and restored['aiStatus'] == 'queued'
        assert not restored['restoredReviewPending'] and restored['facts'] == complete['facts']
        assert sql("select count(*) from machimoa_review.processing_jobs where source_item_id=" +
                   complete_id + " and processing_stage='ai_enrichment';") == '1'

        # Make a complete item visible to the official exclusion command via a
        # deliberate AI hold, then verify the hold is restored with the same job.
        view = rpc('admin_ai_queue_review_detail', ready_job)
        rpc('admin_ai_queue_request_recheck', ready_job, view['revision'], view['version'],
            str(uuid4()), '합성 별도 AI 보류', ACTOR)
        held = current('seoul_reservation', ready['id'])
        entry1, request1 = exclude(held), str(uuid4())
        restored = restore(entry1, request1)
        assert restored['status'] == 'open' and 'ai_recheck_requested' in restored['result']['reasons']
        assert rpc('admin_ai_queue_review_detail', ready_job)['recheckPending']
        assert restored['facts'] == held['facts'] and restored['filterInfo'] == held['filterInfo']

        # A later exclusion and an active claim must not be affected by an old restore.
        entry2 = exclude(restored)
        denied(lambda: restore(entry1, request1), 'review_conflict')
        sql("update machimoa_review.processing_jobs set status='claimed', claimed_at=now(), "
            "claimed_by='synthetic-worker', claim_lease_until=now()+interval '1 minute' "
            "where id=" + literal(ready_job) + ";")
        denied(lambda: restore(entry2), 'trash_processing_active')
        assert current('seoul_reservation', ready['id'])['status'] == 'excluded'

        print('Restore RPC verified for four sources, immediate filters, legacy, concurrent retry, AI readiness, and AI hold.')
    finally:
        docker(['exec', CONTAINER, 'dropdb', '-U', 'postgres', db])


if __name__ == '__main__':
    main()
