"""Fresh network-none SQL; synthetic observations and explicit fake AI only."""
import argparse
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
from test_program_db import fixtures
from test_seoul_content import synthetic_facts, fake_japanese
from test_reclassification_ai import context
from ingest.content_filters import extract_filter_facts
from ingest.program_ai import ProgramAIAdapter
from ingest.reclassification_ai import process_reclassified_job

ROOT = Path(__file__).resolve().parents[1]
C = 'machimoa-saved-count-sql-20261009-56ca9041'
BASE = 'foreigner_filter_local_6920059cf5c4'
ACTOR = '00000000-0000-4000-8000-000000000001'
checks = []

def docker(args, body=None):
    r = subprocess.run(['docker', *args], input=body.encode() if body else None, capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode())
    return r.stdout.decode().strip()

def lit(v):
    if v is None: return 'NULL'
    if type(v) is int: return str(v)
    return "'" + (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)).replace("'", "''") + "'"

def ok(v, label):
    assert v, label
    checks.append(label)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--before-fix', action='store_true')
    args = parser.parse_args()
    m = json.loads(docker(['inspect', C]))[0]
    assert m['State']['Running'] and m['HostConfig']['NetworkMode'] == 'none' and not m['HostConfig']['PortBindings']
    assert m['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
    assert m['Mounts'] and all(x['Type'] == 'volume' and x['Name'] == C + '-data' for x in m['Mounts'])
    assert json.loads(docker(['context', 'inspect']))[0]['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'
    db = 'event_status_local_' + uuid4().hex[:12]
    dump = docker(['exec', C, 'pg_dump', '-U', 'postgres', '-d', BASE, '--schema-only', '--schema=public', '--schema=machimoa_review'])
    assert dump.count('CREATE SCHEMA public;') == 1
    docker(['exec', C, 'createdb', '-U', 'postgres', db])
    def sql(q):
        return docker(['exec', '-i', C, 'psql', '-XqAt', '-U', 'postgres', '-d', db, '-v', 'ON_ERROR_STOP=1'],
                      "set statement_timeout='15s';set lock_timeout='5s';" + q)
    sql(dump.replace('CREATE SCHEMA public;', '-- default empty public', 1))
    def scalar(q): return json.loads(sql('select to_jsonb(' + q + ');') or 'null')
    def command(n, a): return 'begin;set local role service_role;select public.' + n + '(' + ','.join(map(lit, a)) + ');commit;'
    def rpc(n, a): return json.loads(sql(command(n, a)))
    def deny(q, error):
        try: sql(q)
        except RuntimeError as e: ok(error in str(e), 'denied ' + error)
        else: raise AssertionError('expected ' + error)
    for table in ('source_items', 'curation_candidates', 'processing_jobs'):
        ok(scalar('(select count(*) from machimoa_review.' + table + ')') == 0, 'empty ' + table)
    sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation');insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation');")
    run = scalar('(select run_id from public.start_ingest_run(\'seoul_reservation\',3600))')
    def create(raw='안내중', category='event', **updates):
        key = 'synthetic_event_' + uuid4().hex[:12]
        item = copy.deepcopy(fixtures(storage=True)[0]['item'])
        f = synthetic_facts()
        f.update(source_status='unknown', delivery_mode='unknown', activity_region='unknown',
                 residence_scope='not_stated', missing=[], conflicts=[])
        f.update(updates)
        item.update(external_key=key, revision_hash=hashlib.sha256(key.encode()).hexdigest(), program_facts=f)
        item['normalized_payload']['provider_fields'].update(SVCID=key, SVCSTATNM=raw)
        item['normalized_payload']['source_status'] = f['source_status']
        item['normalized_payload']['source_url'] = f['official_url'] = 'https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=' + key
        item['filterFacts'] = extract_filter_facts('seoul_reservation', item['normalized_payload'], f)
        sid = rpc('observe_seoul_program_new_only', [run, [item], None])[0]['id']
        d = rpc('admin_review_classification_detail', [sid])
        if not d['editable']:
            return sid, d
        c = context(category, 'seoul_reservation')
        c['facts'].update(delivery='offline', scope='unknown', evidence='')
        if category == 'program':
            c['filters']['delivery'] = {'status': 'known', 'value': 'onsite'}
            c['filters']['location'] = copy.deepcopy(context('event')['filters']['location'])
        out = rpc('admin_review_reclassify', [sid, d['revision'], d['version'], d['classificationVersion'], c['facts'], c['filters'], '', ACTOR])
        return sid, out
    def snap():
        return scalar("jsonb_build_array((select jsonb_agg(to_jsonb(s) order by id) from machimoa_review.source_items s),(select jsonb_agg(to_jsonb(f) order by source_item_id) from machimoa_review.source_item_program_facts f),(select jsonb_agg(to_jsonb(c) order by source_item_id) from machimoa_review.review_classifications c),(select jsonb_agg(to_jsonb(h) order by to_jsonb(h)::text) from machimoa_review.review_classification_history h),(select jsonb_agg(to_jsonb(j) order by id) from machimoa_review.processing_jobs j))")
    sid, before = create()
    ok(before['active'] and before['category'] == 'event', 'event classification was saved')
    ok(not before['ready'] and before['sourceReasons'] == ['source_status_unknown'], 'reported legacy reception blocker reproduced')
    print(json.dumps({'database': db, 'beforeReasons': before['sourceReasons']}, ensure_ascii=False), flush=True)
    if args.before_fix:
        assert before['ready'], 'REGRESSION: saved informational event cannot enter AI waiting'
    migration = (ROOT / 'supabase/migrations/20261012153524_seoul_reclassified_event_status.sql').read_text(encoding='utf8')
    original = snap()
    deny("begin;alter function machimoa_review.classification_reasons(uuid,jsonb) set search_path='public';" + migration,
         'seoul_event_status_predecessor_changed')
    ok(snap() == original, 'failed precondition preserves existing state')
    sql(migration)
    ok(snap() == original, 'migration leaves facts, observations, histories and queued jobs untouched')
    after = rpc('admin_review_classification_detail', [sid])
    ok(scalar('machimoa_review.classification_reasons(' + lit(sid) + ', ' + lit(after['facts']) + '::jsonb)') == [], 'informational event drops only reception unknown in current evaluation')
    ok(after['sourceReasons'] == before['sourceReasons'], 'old queued job reason remains until explicit save, not a migration backfill')
    ok(not after['ready'], 'existing queued review needs explicit normal review save')
    a = [sid, after['revision'], after['version'], after['classificationVersion'], after['facts'], after['filters'], '', ACTOR]
    saved = rpc('admin_review_reclassify', a)
    ok(saved['ready'] and saved['sourceReasons'] == [], 'formal same-category save enters AI waiting')
    ok(saved['facts'] == before['facts'] and saved['filters'] == before['filters'], 'current classification and all saved event values unchanged')
    ok(saved['classificationVersion'] == before['classificationVersion'] + 1, 'explicit save advances one classification version')
    ok(scalar('(select facts->>\'source_status\' from machimoa_review.source_item_program_facts where source_item_id=' + lit(sid) + ')') == 'unknown', 'no rewrite to open booking')
    ok(scalar('(select count(*) from machimoa_review.review_classification_history where source_item_id=' + lit(sid) + ')') == 2, 'old classification history retained')
    deny(command('admin_review_reclassify', a), 'classification_conflict')
    for raw in ('', '不明', '未登録', '안내중(취소)'):
        _, d = create(raw)
        ok(not d['ready'] and 'source_status_unknown' in d['sourceReasons'], 'unknown status stays blocked: ' + raw)
    _, d = create('안내중', 'program')
    ok(not d['ready'] and 'source_status_unknown' in d['sourceReasons'], 'program reception contract unchanged')
    for raw in ('취소', '서비스취소', '운영취소', '행사취소', '접수취소'):
        i, d = create(raw)
        ok(not d['ready'] and 'event_cancelled' in d['sourceReasons'], 'cancelled event blocked: ' + raw)
        deny(command('claim_reclassified_content_ai', [i, d['revision'], d['classificationVersion'], 'synthetic-blocked', 300]), 'classification_not_ready')
    for raw in ('종료', '서비스종료', '운영종료', '행사종료'):
        _, d = create(raw)
        ok(not d['ready'] and 'event_ended' in d['sourceReasons'], 'ended status blocked: ' + raw)
    for raw, status in [('예약마감', 'reservation_closed'), ('접수종료', 'application_closed'), ('안내중', 'application_closed')]:
        _, d = create(raw, source_status=status)
        ok(not d['ready'] and 'not_currently_accepting' in d['sourceReasons'], 'explicit native closure retained: ' + raw)
    for changes, reason in [({'conflicts': ['source_status_conflict']}, 'source_status_conflict'),
                            ({'conflicts': ['body_api_period_conflict']}, 'body_api_period_conflict'),
                            ({'conflicts': ['fee_conflict']}, 'fee_conflict'),
                            ({'application_actor': 'nationality_excluded'}, 'classification_source_excluded')]:
        _, d = create(**changes)
        ok(not d['ready'] and reason in d['sourceReasons'], 'actual conflict/restriction retained: ' + reason)
    # Current reviewed event bounds, date-only inclusive day and exact time end.
    today = scalar("to_char(statement_timestamp() at time zone 'Asia/Seoul','YYYY-MM-DD')")
    yesterday = scalar("to_char((statement_timestamp() at time zone 'Asia/Seoul')::date-1,'YYYY-MM-DD')")
    def change_dates(i, d, day, precision='day', value=None):
        facts = {**d['facts'], 'eventStart': day, 'eventEnd': day}
        filters = copy.deepcopy(d['filters'])
        filters['schedule']['value']['occurrences'] = [{'start': {'value': day if value is None else value, 'precision': precision}, 'end': {'value': day if value is None else value, 'precision': precision}}]
        return rpc('admin_review_reclassify', [i, d['revision'], d['version'], d['classificationVersion'], facts, filters, '', ACTOR])
    i, d = create(); d = change_dates(i, d, yesterday)
    ok(not d['ready'] and 'event_ended' in d['sourceReasons'], 'past reviewed date blocks despite old future native dates')
    i, d = create(); d = change_dates(i, d, today)
    ok(d['ready'], 'today date-only event is not fabricated midnight expiry')
    past = scalar("to_char((statement_timestamp()-interval '1 minute') at time zone 'Asia/Seoul','YYYY-MM-DD\"T\"HH24:MI:SS')") + '+09:00'
    i, d = create(); d = change_dates(i, d, past[:10], 'second', past)
    ok(not d['ready'] and 'event_ended' in d['sourceReasons'], 'exact reviewed end time blocks')
    # Same-value concurrent save keeps the existing CAS boundary.
    i, d = create(); barrier = Barrier(2)
    def race():
        barrier.wait()
        try: return rpc('admin_review_reclassify', [i, d['revision'], d['version'], d['classificationVersion'], d['facts'], d['filters'], '', ACTOR])
        except RuntimeError as e: return str(e)
    with ThreadPoolExecutor(max_workers=2) as pool: outcomes = list(pool.map(lambda _: race(), range(2)))
    ok(sum(isinstance(x, dict) for x in outcomes) == 1 and sum(isinstance(x, str) and 'classification_conflict' in x for x in outcomes) == 1, 'one concurrent save wins and one conflicts')
    ok(not scalar("has_function_privilege('service_role','machimoa_review.classification_reasons_before_seoul_event_status(uuid,jsonb)','EXECUTE')"), 'backup helper is private')
    ok(not scalar("has_function_privilege('anon','machimoa_review.classification_reasons(uuid,jsonb)','EXECUTE')"), 'anonymous cannot invoke classifier')
    ok(scalar('(select count(*) from machimoa_review.curation_candidates)') == 0, 'SQL checks perform no AI candidate or publication')
    # A separate fake RPC/client proves the unchanged worker preserves current
    # event facts and native status without making real claim/provider calls.
    c = context('event', 'seoul_reservation')
    c['facts'] = saved['facts']; c['filters'] = saved['filters']
    c['nativeConfirmedFacts']['programFacts'] = synthetic_facts()
    c['nativeConfirmedFacts']['programFacts']['source_status'] = 'unknown'
    c['nativeConfirmedFacts']['programFacts']['description'] = '현장 자율 참여로 진행하는 합성 공예 행사입니다.'
    events, inputs, translations = [], [], []
    def fake_rpc(name, args):
        events.append((name, args))
        if name == 'claim_reclassified_content_ai': return c
        if name == 'finish_reclassified_content_ai': return {'candidateId': c['sourceItemId'], 'outcome': 'inserted'}
        raise AssertionError('unexpected fake RPC: ' + name)
    def ko(body, url, *, title):
        inputs.append(json.loads(body))
        return '[한 줄 요약]\n합성 공예 행사 안내입니다.\n[주요 내용]\n작품을 만듭니다.', 'success', 'fake-model'
    def ja(title, body):
        translations.append(body)
        return '合成案内', fake_japanese(body), 'success', 'fake-model'
    result = process_reclassified_job(ProgramAIAdapter(fake_rpc), source_item_id=c['sourceItemId'], revision=c['revision'],
                                     classification_version=1, worker_id=c['workerId'], summarize_ko=ko, translate_ja=ja)
    ok(result.completed == 1 and result.retried == 0 and len(inputs) == len(translations) == 1, 'fake summary, translation and candidate complete once')
    ok([n for n, _ in events] == ['claim_reclassified_content_ai', 'finish_reclassified_content_ai'], 'fake claim/finish only, no retry/approval/publication')
    ok(inputs[0]['currentClassificationFacts'] == saved['facts'] and inputs[0]['currentFilters'] == saved['filters'], 'worker input retains reviewed event classification')
    ok(inputs[0]['nativeConfirmedFacts']['programFacts']['source_status'] == 'unknown', 'worker input does not invent open booking')
    down = (ROOT / 'supabase/rollback/20261012153524_seoul_reclassified_event_status_down.sql').read_text(encoding='utf8')
    before_restore = snap()
    deny("begin;alter function machimoa_review.classification_reasons(uuid,jsonb) set search_path='public';" + down,
         'seoul_event_status_successor_changed')
    ok(snap() == before_restore, 'unsafe restoration preserves all records')
    sql(down)
    ok(snap() == before_restore, 'restoration preserves all records')
    ok('source_status_unknown' in scalar('machimoa_review.classification_reasons(' + lit(sid) + ', ' + lit(saved['facts']) + '::jsonb)'), 'exact predecessor classifier restored')
    print(json.dumps({'database': db, 'checks': len(checks), 'result': 'passed', 'syntheticOnly': True, 'aiCalls': 0, 'sharedDB': False}, ensure_ascii=False))

if __name__ == '__main__':
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        main()
