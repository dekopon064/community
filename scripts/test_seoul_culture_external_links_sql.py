"""Network-none PostgreSQL; schema-only local clone and synthetic rows only.

No connection strings, auth files, HTTP, AI, approvals or publication actions.
The CSV supplies link strings only; all other observation fields are synthetic.
"""
import copy
import hashlib
import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from ingest.connectors.seoul_reservation import normalize_seoul_item
from ingest.program_db import ProgramNewOnlyObservationAdapter, program_rpc_item
from ingest.seoul_links import seoul_source_link
from test_seoul_reservation import row

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = 'machimoa-saved-count-sql-20261009-56ca9041'
BASE = 'seoul_no_retry_local_6e77357f15ef'
MIGRATION = ROOT / 'supabase/migrations/20261014163727_seoul_culture_external_url_validation.sql'
FIXTURE = ROOT / 'scripts/fixtures/seoul_culture_external_links_csv.json'
ACTOR = '00000000-0000-4000-8000-000000000001'


def docker(args, body=None):
    result = subprocess.run(['docker', *args], input=body.encode('utf-8') if body else None, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8'))
    return result.stdout.decode('utf-8').strip()


def literal(value):
    if value is None:
        return 'NULL'
    if type(value) is int:
        return str(value)
    return "'" + (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)).replace("'", "''") + "'"


def main():
    metadata = json.loads(docker(['inspect', CONTAINER]))[0]
    assert metadata['State']['Running'] and metadata['HostConfig']['NetworkMode'] == 'none'
    assert not metadata['HostConfig']['PortBindings'] and not metadata['HostConfig']['Binds']
    assert metadata['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
    assert metadata['Mounts'] and all(x['Type'] == 'volume' and x['Name'] == CONTAINER + '-data' for x in metadata['Mounts'])
    assert json.loads(docker(['context', 'inspect']))[0]['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'
    db = 'seoul_external_url_local_' + uuid4().hex[:12]
    schema = docker(['exec', CONTAINER, 'pg_dump', '-U', 'postgres', '-d', BASE,
                     '--schema-only', '--schema=public', '--schema=machimoa_review'])
    assert schema.count('CREATE SCHEMA public;') == 1
    docker(['exec', CONTAINER, 'createdb', '-U', 'postgres', db])

    def sql(statement):
        return docker(['exec', '-i', CONTAINER, 'psql', '-XqAt', '-U', 'postgres', '-d', db, '-v', 'ON_ERROR_STOP=1'],
                      "set statement_timeout='15s';set lock_timeout='5s';" + statement)

    def scalar(expression):
        return json.loads(sql('select to_jsonb(' + expression + ');') or 'null')

    def rpc(name, args):
        return scalar_rpc(name, ','.join(literal(v) for v in args))

    def scalar_rpc(name, args):
        result = sql('begin;set local role service_role;select public.' + name + '(' + args + ');commit;')
        return json.loads(result)

    sql(schema.replace('CREATE SCHEMA public;', '-- fresh public schema', 1))
    checks = []

    def ok(condition, label):
        assert condition, label
        checks.append(label)

    def denied(statement, reason):
        try:
            sql(statement)
        except RuntimeError as exc:
            assert reason in str(exc), str(exc)
            checks.append('denied: ' + reason)
        else:
            raise AssertionError(reason)

    def data_snapshot():
        # Include every private table plus the synthetic published-content table.
        names = scalar("(select jsonb_agg(quote_ident(n.nspname)||'.'||quote_ident(c.relname) order by n.nspname,c.relname)"
                       " from pg_class c join pg_namespace n on n.oid=c.relnamespace"
                       " where c.relkind='r' and (n.nspname='machimoa_review' or n.nspname='public' and c.relname='curations'))")
        values = ','.join('(' + literal(name) + ", (select coalesce(jsonb_agg(md5(to_jsonb(t)::text)"
                          " order by md5(to_jsonb(t)::text)),'[]') from " + name + ' t))' for name in names)
        return scalar('(select jsonb_object_agg(k,v) from (values ' + values + ') snapshot(k,v))')

    def function_snapshot():
        return scalar("(select jsonb_object_agg(p.oid::regprocedure::text,jsonb_build_object("
                      "'definition',pg_get_functiondef(p.oid),'owner',p.proowner,'acl',p.proacl,"
                      "'config',p.proconfig,'definer',p.prosecdef,'volatility',p.provolatile,'body',p.prosrc))"
                      " from pg_proc p join pg_namespace n on n.oid=p.pronamespace"
                      " where n.nspname in ('public','machimoa_review'))")

    fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
    assert fixture['provenance']['not_current_api_response'] and fixture['provenance']['synthetic_other_fields']
    records = [normalize_seoul_item(row(sid=x['svc_id'], SVCNM=x['title'], SVCURL=x['svc_url']),
                                   culture_external_links=True) for x in fixture['links']]
    canonical = normalize_seoul_item(row(sid='SYNTH_existing', DTLCONT='<p>합성 원문</p>'))
    canonical_packet = program_rpc_item(canonical)
    ok(scalar("(select count(*) from machimoa_review.source_items)") == 0, 'fresh schema has no observations')
    ok(scalar("(select count(*) from machimoa_review.curation_candidates)") == 0, 'fresh schema has no candidates')
    scalar('machimoa_review.program_validate(' + literal(canonical_packet['program_facts']) + ')')
    for record in records:
        denied('select machimoa_review.program_validate(' + literal(program_rpc_item(record)['program_facts']) + ');', 'invalid_official_url')
    ok(len(records) == 18, 'CSV 18 links reproduced against actual old server predicate')

    # Synthetic existing observation and an operator edit use formal RPCs.
    sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source)"
        " values('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation');"
        "insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation');")
    run = scalar("(select run_id from public.start_ingest_run('seoul_reservation',3600))")
    call_counts = {}

    def transport(name, params):
        assert name in ('seoul_collection_contract', 'observe_seoul_program_new_only')
        call_counts[name] = call_counts.get(name, 0) + 1
        return scalar_rpc(name, ','.join(key + '=>' + literal(v) for key, v in params.items()))

    adapter = ProgramNewOnlyObservationAdapter(transport)
    adapter.require_contract()
    observed = adapter.observe(run, [canonical], {'synthetic': True})[0]
    detail_before_edit = rpc('admin_program_detail', [observed['id']])
    detail = rpc('admin_program_save', [observed['id'], detail_before_edit['revision'], detail_before_edit['version'],
                 {'description': '합성 운영자가 확인한 프로그램 설명입니다. 기존 원문과는 별도 검토값입니다.'},
                 '{program_description_missing}', '', ACTOR])
    ok(detail['factsVersion'] > detail_before_edit['factsVersion'], 'formal edit records synthetic fact version/history')
    sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status)"
        " values('seoul_reservation','SYNTH_existing'," + literal(canonical.revision_hash) + ",'synthetic-external-url-existing','keep-title','keep-summary','keep-body',"
        "'{\"synthetic\":true,\"title_ja\":\"保持\",\"content_ja\":\"保持した本文\"}','success');")
    state_before = data_snapshot()
    functions_before = function_snapshot()
    original_body = scalar("(select prosrc from pg_proc where oid='machimoa_review.program_validate(jsonb)'::regprocedure)")
    original_def = scalar("pg_get_functiondef('machimoa_review.program_validate(jsonb)'::regprocedure)")
    migration = MIGRATION.read_text(encoding='utf-8')

    # Unknown predecessor must reject and roll back both helpers and DDL.
    for alteration in (
        "alter function machimoa_review.program_validate(jsonb) set search_path='public';",
        "alter function machimoa_review.program_validate(jsonb) volatile;",
        original_def.replace("if p->>'official_url'<>'' and", "if p->>'official_url'<>'' and true and", 1) + ';\n',
    ):
        denied('begin;\n' + alteration + '\n' + migration, 'seoul_program_url_prerequisite_changed')
        ok(function_snapshot() == functions_before, 'predecessor failure rolls back all function changes')
        ok(data_snapshot() == state_before, 'predecessor failure preserves all synthetic values/history')
    denied('begin;set local role service_role;' + migration, 'permission denied')
    ok(function_snapshot() == functions_before, 'non-owner migration has no partial helper installation')

    sql(migration)
    after_functions = function_snapshot()
    existing_changes = [k for k in functions_before if after_functions.get(k) != functions_before[k]]
    ok(existing_changes == ['machimoa_review.program_validate(jsonb)'], 'only existing URL validator changed')
    old = migration.split('$old$', 2)[1]
    new = migration.split('$new$', 2)[1]
    ok(scalar("(select prosrc from pg_proc where oid='machimoa_review.program_validate(jsonb)'::regprocedure)") ==
       original_body.replace(old, new), 'all non-URL validation clauses byte-for-byte preserved')
    previous = functions_before['machimoa_review.program_validate(jsonb)']
    current = after_functions['machimoa_review.program_validate(jsonb)']
    ok(all(current[k] == previous[k] for k in ('owner', 'acl', 'config', 'definer', 'volatility')),
       'original owner ACL search_path security and immutability preserved')
    ok(data_snapshot() == state_before, 'migration preserves every original table row including versions candidates history')
    for name in ('seoul_external_query_value(text)', 'seoul_program_url_valid(text)'):
        for role in ('anon', 'authenticated', 'service_role'):
            ok(not scalar("has_function_privilege(" + literal(role) + ",'machimoa_review." + name + "','execute')"),
               role + ' cannot directly execute private helper ' + name)
        props = after_functions['machimoa_review.' + name]
        ok(not props['definer'] and props['config'] == ['search_path=""'], 'helper is invoker and empty search_path')
    for role in ('anon', 'authenticated'):
        denied('set role ' + role + ";select machimoa_review.seoul_program_url_valid('https://evil.test');", 'permission denied')

    # Actual PostgreSQL validates completed client packets, including ampersands.
    for record in records:
        packet = program_rpc_item(record)
        usable = packet['program_facts']['official_url']
        ok(scalar('machimoa_review.seoul_program_url_valid(' + literal(usable) + ')') is True,
           'SQL accepts CSV usable link ' + record.external_key)
        scalar('machimoa_review.program_validate(' + literal(packet['program_facts']) + ')')
        if '&amp;' in packet['normalized_payload']['source_link']['original']:
            ok(scalar('machimoa_review.seoul_program_url_valid(' + literal(packet['normalized_payload']['source_link']['original']) + ')') is False,
               'SQL refuses raw HTML separator while original snapshot keeps it')

    base_url = 'https://culture.gangseo.seoul.kr/gsfc/education/view.do'
    parity_urls = [
        base_url+'?eduSn=1', base_url+'?menuNo=2&eduSn=1',
        base_url+'?eduSn=%31', base_url+'?eduSn=1&menuNo=2',
        base_url+'?eduSn=', base_url+'?eduSn=1&eduSn=2', base_url+'?eduSn=1&',
        base_url+'?eduSn=1&redirect=https://evil.test', base_url+'?%65duSn=1',
        base_url+'?eduSn=1%0A', base_url+'?eduSn=%', base_url+'?eduSn=%252f',
        base_url+'?eduSn=1#next', base_url+'?eduSn=1\\bad',
        base_url+'?eduSn=1+2', base_url+'?eduSn='+('1'*33),
        base_url.replace('https://','http://')+'?eduSn=1',
        base_url.replace('culture.gangseo.seoul.kr','127.0.0.1')+'?eduSn=1',
        base_url.replace('culture.gangseo.seoul.kr','culture.gangseo.seoul.kr.evil.test')+'?eduSn=1',
        base_url.replace('culture.gangseo.seoul.kr','evil.test@culture.gangseo.seoul.kr')+'?eduSn=1',
        base_url.replace('culture.gangseo.seoul.kr','culture.gangseo.seoul.kr:443')+'?eduSn=1',
        'https://kctg.or.kr/tour/touristSiteView.do?tourist_cd=T%5F1&page_no=',
        'https://firesafety.eseoul.go.kr/multi/main.do',
        'https://firesafety.eseoul.go.kr/multi/main.do?',
        'https://firesafety.eseoul.go.kr/multi/main.do?redirect=1',
        'https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=SYNTH_existing',
        'javascript:alert(1)', 'data:text/html,synth',
    ]
    for url in parity_urls:
        try:
            accepted = seoul_source_link(url, 'SYNTH_existing', culture_external=True)['url'] == url
        except ValueError:
            accepted = False
        ok(scalar('machimoa_review.seoul_program_url_valid(' + literal(url) + ')') is accepted, 'Python SQL structural parity ' + url)
    # Other facts validation stays strict independently of the new URL type.
    facts = program_rpc_item(records[0])['program_facts']
    for patch_value in ({'fee_kind':'invented'}, {'delivery_mode':'invented'}, {'extra':'unsupported'}):
        invalid = dict(facts, **patch_value)
        denied('select machimoa_review.program_validate(' + literal(invalid) + ');', 'invalid_program_')

    saved = adapter.observe(run, records, {'synthetic': True, 'targetOffset': 18})
    ok(all(x['outcome'] == 'new_saved' for x in saved), 'actual fenced new-only RPC stores all 18 synthetic CSV observations')
    for record in records:
        stored = scalar("(select normalized_payload from machimoa_review.source_items where source_id='seoul_reservation' and external_key=" + literal(record.external_key) + ")")
        ok(stored['source_link']['original'] == record.normalized_payload['source_link']['original'], 'raw URL preserved ' + record.external_key)
        ok(stored['source_url'] == record.normalized_payload['source_url'], 'usable URL preserved ' + record.external_key)
    state_after_insert = data_snapshot()
    changed = normalize_seoul_item(row(sid='SYNTH_existing', SVCURL=records[0].normalized_payload['source_url'],
                                      DTLCONT='<p>상세내용</p><p>합성 변경된 설명입니다.</p>'), culture_external_links=True)
    result = adapter.observe(run, [changed], {'synthetic': True, 'targetOffset': 19})
    ok(result[0]['outcome'] == 'existing_skipped', 'existing ID with changed revision URL and body is skipped')
    # Only ingest-run/checkpoint bookkeeping may change for the empty logical insert.
    unchanged_tables = ('machimoa_review.source_items', 'machimoa_review.source_item_program_facts',
                        'machimoa_review.source_item_content_filters', 'machimoa_review.processing_jobs',
                        'machimoa_review.curation_candidates')
    state_after_duplicate = data_snapshot()
    ok(all(state_after_duplicate[k] == state_after_insert[k] for k in unchanged_tables),
       'duplicate retains original facts filters jobs candidates and all versions')
    denied("select * from public.admin_program_save(" + ','.join(literal(v) for v in
           [observed['id'], detail_before_edit['revision'], detail_before_edit['version'],
            {'description':'합성 오래된 수정 요청입니다. 현재 설명을 덮어쓰면 안 됩니다.'}, '{}', '', ACTOR]) + ");", 'program_version_conflict')
    ok(rpc('admin_program_detail',[observed['id']])['factsVersion'] == detail['factsVersion'], 'stale editor cannot overwrite fact version')
    ok(scalar("(select count(*) from machimoa_review.curation_candidates)") == 1, 'no extra candidates generated')
    for role in ('anon', 'authenticated'):
        denied('set role ' + role + ";select public.observe_seoul_program_new_only("
               + literal(run) + ",'[]',null);", 'permission denied')
    rendezvous = Barrier(2)
    def concurrent_insert(index):
        record = normalize_seoul_item(row(sid='SYNTH_race', SVCURL=records[0].normalized_payload['source_url'],
            SVCNM='합성 동시 저장 ' + str(index)), culture_external_links=True)
        rendezvous.wait(timeout=10)
        return adapter.observe(run, [record], {'synthetic': True, 'concurrent': True})[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent = list(pool.map(concurrent_insert, range(2)))
    ok(sorted(x['outcome'] for x in concurrent) == ['existing_skipped','new_saved'], 'concurrent same-ID inserts store exactly once')
    ok(scalar("(select count(*) from machimoa_review.source_items where external_key='SYNTH_race')") == 1,
       'concurrent same-ID insert has one row and retained first revision')
    ok(scalar("(select count(*) from machimoa_review.curation_candidates)") == 1, 'concurrent inserts never regenerate existing candidate')
    # No broad helper exposure or policy/RLS changes are introduced.
    sql("select * from public.finish_ingest_run(" + literal(run) + ",'complete','natural_end',0,false,3);")
    output = dict(database=db, base=BASE, checks=len(checks), csv_links=18, sql_new_saved=18,
                  existing_skipped=1, concurrent_new_saved=1, concurrent_existing_skipped=1,
                  network='none', production_access=0, real_collection=0,
                  ai_calls=0, approvals=0, publications=0, migration=MIGRATION.name)
    (ROOT/'scripts/__pycache__/seoul_external_url_sql_result.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(output))


if __name__ == '__main__':
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')), \
         patch('ingest.supabase_store.create_ingest_client', side_effect=AssertionError('production DB forbidden')), \
         patch('ingest.ai_provider.create_provider_adapter', side_effect=AssertionError('AI forbidden')):
        main()

