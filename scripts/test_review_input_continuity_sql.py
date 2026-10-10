"""Narrow synthetic continuity checks in an explicitly prepared isolated DB only."""
import argparse
import copy
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4
from test_myseoul_db import fixtures

args = argparse.ArgumentParser()
args.add_argument('--database', required=True)
args.add_argument('--phase',choices=['all','data','place'],default='all')
a = args.parse_args()
assert a.database.startswith('review_continuity_') and a.database.replace('_', '').isalnum()
container = 'machimoa-saved-count-sql-20261009-56ca9041'

def docker(parts, body=None):
    r = subprocess.run(['docker', *parts], input=body.encode() if body else None, capture_output=True)
    if r.returncode:
        raise RuntimeError(r.stderr.decode())
    return r.stdout.decode().strip()

meta = json.loads(docker(['inspect', container]))[0]
assert meta['State']['Running'] and meta['HostConfig']['NetworkMode'] == 'none'
assert not meta['HostConfig']['PortBindings']
assert meta['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
assert all(m['Type'] == 'volume' and m['Name'] == container + '-data' for m in meta['Mounts'])
assert json.loads(docker(['context', 'inspect']))[0]['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'

def sql(q):
    return docker(['exec', '-i', container, 'psql', '-XqAt', '-U', 'postgres', '-d', a.database,
                   '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=verbose'], q)

def lit(x):
    if x is None:
        return 'NULL'
    if isinstance(x, bool):
        return str(x).lower()
    if isinstance(x, int):
        return str(x)
    return "'" + (x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)).replace("'", "''") + "'"

def value(q):
    return json.loads(sql('select to_jsonb(' + q + ');') or 'null')

def rpc(name, values):
    return json.loads(sql('begin;set local role service_role;select public.' + name + '(' + ','.join(map(lit, values)) + ');commit;'))

checks = 0
def ok(v):
    global checks
    assert v
    checks += 1

def deny(q, code):
    global checks
    try:
        sql(q)
    except RuntimeError as e:
        assert code in str(e), str(e)
        checks += 1
    else:
        raise AssertionError('expected ' + code)

root = Path(__file__).resolve().parents[1]
up = (root / 'supabase/migrations/20261010095636_review_input_continuity.sql').read_text(encoding='utf-8')
down = (root / 'supabase/rollback/20261010095636_review_input_continuity_down.sql').read_text(encoding='utf-8')
if a.phase == 'all':
    ok(value('(select not dirty from machimoa_review.review_continuity_install where singleton)'))
    deny("begin;alter table machimoa_review.review_classifications disable trigger review_continuity_dirty;" + down, 'continuity_successor_trigger_changed')
    ok(value("(select tgenabled='O' from pg_trigger where tgrelid='machimoa_review.review_classifications'::regclass and tgname='review_continuity_dirty')"))
    deny("begin;alter function machimoa_review.classification_draft(uuid,text) set search_path='public';" + down, 'continuity_successor_changed')
    sql(down)
    ok(value("to_regprocedure('machimoa_review.classification_draft(uuid,text)') is null"))
    deny("begin;alter function machimoa_review.classification_initial(uuid) set search_path='public';" + up, 'continuity_predecessor_changed')
    ok(value("to_regclass('machimoa_review.review_continuity_install') is null"))
    sql(up)
    for role in ('anon', 'authenticated', 'service_role'):
        ok(not value("has_table_privilege('" + role + "','machimoa_review.review_continuity_install','select')"))
        ok(not value("has_function_privilege('" + role + "','machimoa_review.classification_draft(uuid,text)','execute')"))
    ok(value("(select relrowsecurity from pg_class where oid='machimoa_review.review_continuity_install'::regclass)"))
    # Two connections: rollback must wait for the writer, then see the committed dirty flag.
    writer = subprocess.Popen(['docker', 'exec', '-i', container, 'psql', '-XqAt', '-U', 'postgres', '-d', a.database, '-v', 'ON_ERROR_STOP=1'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    writer.stdin.write(b"begin;update machimoa_review.review_classifications set classification_version=classification_version where false;select 'writer-ready';\n")
    writer.stdin.flush()
    assert writer.stdout.readline().strip() == b'writer-ready'
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(deny, down, 'continuity_records_present')
        deadline = monotonic() + 15
        waiting = False
        while monotonic() < deadline:
            waiting = value("exists(select 1 from pg_locks where relation='machimoa_review.review_classifications'::regclass and not granted)")
            if waiting:
                break
            sleep(.1)
        writer.stdin.write(b'commit;\n')
        writer.stdin.flush()
        writer.stdin.close()
        assert writer.wait(timeout=15) == 0
        future.result(timeout=15)
    ok(waiting)
    ok(value("to_regprocedure('machimoa_review.classification_draft(uuid,text)') is not null"))

actor = '00000000-0000-4000-8000-000000000001'
sql("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='myseoul_program';")
run = value("(select active_run_id from machimoa_review.source_sync_state where source_id='myseoul_program' and lease_expires_at>clock_timestamp())")
if not run:
    run = value("(select run_id from public.start_ingest_run('myseoul_program',3600))")
base = next(x['item'] for x in fixtures()['fixtures'] if x['name'] == 'online')

def observe(scope='unknown', evidence=None):
    p = copy.deepcopy(base)
    old = p['external_key'].split(':')[-1]
    p = json.loads(json.dumps(p).replace(old, uuid4().hex.upper()))
    p['revision_hash'] = uuid4().hex * 2
    f = p['myseoul_facts']
    f.update(source_revision=p['revision_hash'], residence_scope=scope, residence='', residence_evidence=evidence or [], public_category='unknown')
    f['issues'] = [v for v in f['issues'] if v['code'] != 'online_residence_unknown'] + [{'code': 'online_residence_unknown', 'field': 'residence', 'evidence': []}]
    for key in list(p):
        if key.startswith('filter'):
            p.pop(key)
    return rpc('observe_myseoul_program', [run, [p], None])[0]['id']

detail = lambda sid: rpc('admin_review_classification_detail', [sid])
if a.phase != 'place':
    for scope in ('unknown', 'nationwide'):
        sid = observe(scope)
        native = rpc('admin_myseoul_program_detail', [sid])
        original = copy.deepcopy(native['facts'])
        d = detail(sid)
        ok(not d['active'] and not d['facts']['evidence'])
        ok(set(d['drafts']) == {'policy', 'program', 'event', 'youth_space', 'living'})
        program, event = d['drafts']['program'], d['drafts']['event']
        ok(program['filters']['application']['value']['start']['value'].startswith('2020-01-01'))
        ok(program['filters']['application']['value']['end']['value'].startswith('2099-10-15'))
        ok(event['filters']['schedule']['value']['occurrences'][0]['start']['value'] == '2026-10-03')
        ok(event['facts']['eventEnd'] == '2099-10-17' and not event['facts']['deadlineOn'])
        before = value('(select to_jsonb(s) from machimoa_review.source_items s where id=' + lit(sid) + ')')
        confirmed = rpc('admin_myseoul_residence_confirm', [sid, native['revision'], native['version'], False, '', '', [], actor, str(uuid4())])
        assert confirmed['observedFacts'] == native['observedFacts']
        ok(all(confirmed['facts'][k] == original[k] for k in ('residence_scope','residence','residence_evidence','official_url','source_revision')))
        d = detail(sid)
        ok(d['facts']['scope'] == 'nationwide' and d['facts']['evidence'].startswith('운영자 판단:'))
        # Only missing filter fields are completed; dates and original facts remain unchanged.
        draft = d['drafts']['program']
        draft['filters']['topic'] = {'status': 'known', 'value': 'language_learning'}
        draft['filters']['audience'] = {'status': 'known', 'value': 'other'}
        draft['facts']['delivery'] = 'online'
        args = [sid, d['revision'], d['version'], d['classificationVersion'], draft['facts'], draft['filters'], '운영자 확인: 합성 원문의 분류와 필수값을 확인했습니다.', actor]
        saved = rpc('admin_review_reclassify', args)
        ok(saved['ready'] and saved['category'] == 'program' and saved['classificationVersion'] == 1)
        ok(rpc('admin_myseoul_program_detail', [sid])['observedFacts'] == native['observedFacts'])
        after = value('(select to_jsonb(s) from machimoa_review.source_items s where id=' + lit(sid) + ')')
        for key in ('id', 'external_key', 'source_id', 'revision_hash'):
            ok(before[key] == after[key])
        deny('begin;set local role service_role;select public.admin_review_reclassify(' + ','.join(map(lit, args)) + ');commit;', 'PT409')
        bad = copy.deepcopy(draft['filters'])
        bad['application']['value']['start'] = None
        deny('begin;set local role service_role;select public.admin_review_reclassify(' + ','.join(map(lit, [sid, saved['revision'], saved['version'], 1, draft['facts'], bad, args[-2], actor])) + ');commit;', 'PT422')
        job = rpc('claim_reclassified_content_ai', [sid, saved['revision'], 1, 'synthetic-continuity', 300])
        ok(job['facts']['category'] == 'program' and job['facts']['evidence'].startswith('운영자 판단:'))
        from ingest.reclassification_ai import validate_context, classification_input
        context = validate_context(job, sid, saved['revision'], 1, 'synthetic-continuity')
        ok('운영자 판단:' in classification_input(context))
        output = {'titleKo': '합성', 'summaryKo': '합성 요약', 'contentKo': '합성 본문', 'titleJa': '合成', 'summaryJa': '合成概要', 'contentJa': '合成本文', 'aiModel': 'synthetic-only'}
        finished = rpc('finish_reclassified_content_ai', [job['jobId'], job['revision'], job['classificationVersion'], job['claimedAt'], job['leaseUntil'], job['workerId'], output])
        ok(finished['outcome'] == 'inserted')
        candidate = rpc('admin_review_detail', ['candidates', finished['candidateId']])
        ok(candidate['category'] == 'program')
        # Same stable source item changes draft, stale candidate cannot publish.
        new = detail(sid)
        living = new['drafts']['living']['facts']
        living['delivery'] = 'online'
        changed = rpc('admin_review_reclassify', [sid, new['revision'], new['version'], 1, living, None, args[-2], actor])
        ok(changed['id'] == sid and changed['category'] == 'living')
        deny('begin;set local role service_role;select public.admin_review_publish(' + ','.join(map(lit, [candidate['id'], candidate['revision'], candidate['version'], actor])) + ');commit;', 'PT409')

# Exact existing scoped confirmation: a valid venue need not contain an address.
from test_myseoul_db import sample, NOW
from ingest.myseoul_db import myseoul_rpc_item
p = myseoul_rpc_item(sample(venue='합성글로벌센터'), now=NOW)
old = p['external_key'].split(':')[-1]
p = json.loads(json.dumps(p).replace(old, uuid4().hex.upper()))
p['revision_hash'] = uuid4().hex * 2
f = p['myseoul_facts']
f.update(source_revision=p['revision_hash'], activity_region='capital')
f['issues'] = [x for x in f['issues'] if x['code'] != 'activity_region_unknown'] + [{'code':'activity_region_unknown','field':'venue','evidence':[]}]
sid = rpc('observe_myseoul_program',[run,[p],None])[0]['id']
native = rpc('admin_myseoul_program_detail',[sid])
ok('activity_region_unknown' in native['result']['reasons'])
confirmed = rpc('admin_myseoul_program_save_v2',[sid,native['revision'],native['version'],{k:native['facts'][k] for k in ('delivery_mode','activity_region','venue')},actor])
ok('activity_region_unknown' not in confirmed['result']['reasons'])
ok(confirmed['observedFacts'] == native['observedFacts'])
ok(confirmed['facts']['venue'] == '합성글로벌센터')
fd = rpc('admin_content_filter_detail',[sid])
location = {'status':'known','value':{'scope':'specific','venues':[{'province':'11','district':None,'facility':'','address':''}]}}
saved = rpc('admin_content_filter_save',[sid,fd['revision'],fd['version'],fd['filterVersion'],{'location':location},actor])
ok(saved['data']['location'] == location)
ok('activity_region_unknown' not in rpc('admin_myseoul_program_detail',[sid])['result']['reasons'])
deny(down, 'continuity_records_present')
ok(value("to_regprocedure('machimoa_review.classification_draft(uuid,text)') is not null"))
print(json.dumps({'checks': checks, 'database': a.database, 'actualProviderCalls': 0, 'productionAccess': False, 'result': 'passed'}))
