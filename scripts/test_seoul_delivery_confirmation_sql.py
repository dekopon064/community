"""Explicit delivery confirmation: isolated PostgreSQL, synthetic data only."""
import argparse, copy, hashlib, json, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4
from test_program_db import fixtures
from test_program_ai import bind_program_filters, providers
from test_seoul_content import synthetic_facts
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--before-fix', action='store_true')
args = parser.parse_args()
CONTAINER = 'machimoa-saved-count-sql-20261009-56ca9041'
DB = 'seoul_delivery_local_' + uuid4().hex[:12]

def docker(parts, body=None):
    r = subprocess.run(['docker', *parts], input=body.encode() if body else None, capture_output=True)
    if r.returncode: raise RuntimeError(r.stderr.decode())
    return r.stdout.decode().strip()

m = json.loads(docker(['inspect', CONTAINER]))[0]
assert m['State']['Running'] and m['HostConfig']['NetworkMode'] == 'none' and not m['HostConfig']['PortBindings']
assert m['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
assert m['Mounts'] and all(v['Type'] == 'volume' and v['Name'] == CONTAINER+'-data' for v in m['Mounts'])
assert json.loads(docker(['context', 'inspect']))[0]['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'
dump = docker(['exec', CONTAINER, 'pg_dump', '-U', 'postgres', '-d', 'seoul_contract_local_20261011_release', '--schema-only', '--schema=public', '--schema=machimoa_review'])
assert dump.count('CREATE SCHEMA public;') == 1
docker(['exec', CONTAINER, 'createdb', '-U', 'postgres', DB])

def sql(q):
    return docker(['exec', '-i', CONTAINER, 'psql', '-XqAt', '-U', 'postgres', '-d', DB, '-v', 'ON_ERROR_STOP=1'], "set statement_timeout='15s';set lock_timeout='5s';" + q)

sql(dump.replace('CREATE SCHEMA public;', '-- Empty public schema already exists.', 1))
for name in ['20261012014759_ai_queue_recheck_hold.sql', '20261012023943_ai_queue_recheck_pending_review.sql', '20261012035720_ai_queue_recheck_edit_exclude.sql']:
    sql((ROOT/'supabase/migrations'/name).read_text(encoding='utf8'))

def lit(v):
    if v is None: return 'NULL'
    if isinstance(v, int): return str(v)
    return "'" + (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)).replace("'", "''") + "'"

def scalar(q): return json.loads(sql('select to_jsonb(' + q + ');') or 'null')
def query(n, a): return 'begin;set local role service_role;select public.'+n+'('+','.join(map(lit, a))+');commit;'
def rpc(n, a): return json.loads(sql(query(n, a)))
checks = []
def ok(v, name): assert v, name; checks.append(name)
def deny(q, reason):
    try: sql(q)
    except RuntimeError as e: assert reason in str(e), str(e); checks.append('denied '+reason)
    else: raise AssertionError(reason)

for table in ['source_items', 'curation_candidates', 'processing_jobs']:
    ok(scalar('(select count(*) from machimoa_review.'+table+')') == 0, 'fresh schema, no '+table)
if not args.before_fix:
    up = (ROOT/'supabase/migrations/20261012060021_seoul_delivery_filter_confirmation.sql').read_text(encoding='utf8')
    deny("begin;alter function public.admin_program_detail(uuid) set search_path='public';"+up, 'seoul_delivery_predecessor_changed')
    sql(up)
    deny(up, 'seoul_delivery_predecessor_changed')

ACTOR = '00000000-0000-4000-8000-000000000001'
sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation');insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation');")
run = scalar("(select run_id from public.start_ingest_run('seoul_reservation',3600))")

def create(key, **updates):
    v = copy.deepcopy(fixtures(storage=True)[0]['item'])
    v['external_key'] = key; v['revision_hash'] = hashlib.sha256(key.encode()).hexdigest()
    v['program_facts'] = synthetic_facts()
    v['program_facts']['missing'] = []; v['program_facts']['conflicts'] = []
    v['program_facts']['periods']['RCPTBGNDT']['value'] = '2020-01-01'
    v['program_facts']['activity_evidence'] = []
    v['program_facts'].update(updates)
    v['normalized_payload']['provider_fields']['SVCID'] = key
    v['normalized_payload']['source_url'] = v['program_facts']['official_url'] = 'https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id='+key
    from ingest.content_filters import empty_filters
    v['filterFacts'] = {'data':empty_filters('program'), 'evidence':{}}
    i = rpc('observe_seoul_program_new_only', [run, [v], None])[0]['id']
    d = rpc('admin_program_detail', [i])
    f = copy.deepcopy(d['facts']); f['delivery_mode'] = f['delivery_mode'] if f['delivery_mode'] in ('offline','hybrid') else 'offline'; f['activity_region'] = 'capital'
    holder = {'facts': f, 'workerId':'synthetic'}; bind_program_filters(holder)
    data = holder['filterContext']['data']
    rpc('admin_content_filter_save', [i, d['revision'], d['version'], d['filterInfo']['filterVersion'], {k:x for k,x in data.items() if k not in ('schema', 'category')}, ACTOR])
    return i, rpc('admin_program_detail', [i]), v

def confirm_args(i, d):
    return [i, d['revision'], d['version'], d['factsVersion'], d['filterInfo']['filterVersion'], {k:d['filterInfo']['data'][k] for k in ('location', 'delivery')}, '합성 원문에서 온라인 예약과 현장 진행을 구분해 대조했습니다.', ACTOR]

def snapshot(i):
    return scalar("(select jsonb_build_object('source',to_jsonb(s),'facts',(select to_jsonb(f) from machimoa_review.source_item_program_facts f where f.source_item_id=s.id),'filter',(select to_jsonb(f) from machimoa_review.source_item_content_filters f where f.source_item_id=s.id),'events',(select jsonb_agg(to_jsonb(e)) from machimoa_review.admin_review_events e where e.source_item_id=s.id)) from machimoa_review.source_items s where s.id="+lit(i)+")")

i, d, observed = create('synthetic_delivery', delivery_mode='unknown', activity_region='unknown', missing=['delivery_mode_unknown'])
ok(d['facts']['delivery_mode'] == 'unknown' and not d['activityReview']['confirmed'], 'filter save alone never confirms facts')
ok(d['activityReview']['pending'], 'delivery unknown can explicitly confirm existing onsite/capital filters')
before = snapshot(i)
for changed, message in [(1, 'source_revision_conflict'), (2, 'program_version_conflict'), (3, 'program_version_conflict'), (4, 'content_filter_input_changed')]:
    a = confirm_args(i, d); a[changed] = 'f'*64 if changed < 3 else 999
    deny(query('admin_program_activity_confirm', a), message)
ok(snapshot(i) == before, 'stale commands preserve every stored value/history')
sql("create function public.delivery_test_fail() returns trigger language plpgsql as $$begin raise exception 'synthetic_audit_failure';end$$;create trigger delivery_test_fail before insert on machimoa_review.seoul_activity_confirmations for each row execute function public.delivery_test_fail();")
deny(query('admin_program_activity_confirm', confirm_args(i, d)), 'synthetic_audit_failure')
ok(snapshot(i) == before, 'audit failure atomically rolls back fact/filter/history changes')
sql('drop trigger delivery_test_fail on machimoa_review.seoul_activity_confirmations;drop function public.delivery_test_fail();')
barrier = Barrier(2)
def confirm_once():
    barrier.wait()
    try: return rpc('admin_program_activity_confirm', confirm_args(i, d))
    except RuntimeError as e: assert 'program_version_conflict' in str(e); return 'conflict'
with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: confirm_once(), range(2)))
ok(results.count('conflict') == 1, 'one concurrent confirmation accepted; stale request rejected')
saved = next(r for r in results if isinstance(r, dict))
expected = copy.deepcopy(d['facts']); expected.update(delivery_mode='offline', activity_region='capital', missing=[])
ok(saved['facts'] == expected, 'only confirmed mode/region and their missing flag change')
ok(saved['filterInfo']['data'] == d['filterInfo']['data'], 'all existing filter values unchanged')
ok(saved['observedFacts'] == observed['program_facts'], 'raw observed facts never rewritten')
ok(saved['facts']['activity_evidence'] == [], 'no invented facility or source quotation')
ok(saved['factsVersion'] == d['factsVersion']+1 and saved['filterInfo']['filterVersion'] == d['filterInfo']['filterVersion']+1 and saved['version'] != d['version'], 'facts/filter/version fence advances')
ok(saved['activityReview']['confirmed'] and not saved['activityReview']['pending'] and saved['aiStatus'] == 'queued', 'server reassesses and only resolved item enters AI waiting')
event = scalar('(select changed_fields from machimoa_review.admin_review_events where source_item_id='+lit(i)+' order by id desc limit 1)')
ok(event == ['confirmed:activity_region', 'confirmed:delivery_mode'], 'formal confirmation audit records both facts')
ok(scalar('(select count(*) from machimoa_review.seoul_activity_confirmations where source_item_id='+lit(i)+')') == 1, 'confirmation history inserted once')
mi, md, _ = create('synthetic_same_mixed', delivery_mode='hybrid', activity_region='capital', activity_evidence=['합성 수도권 현장 진행'], missing=['delivery_mode_unknown'])
ok(md['activityReview']['pending'] and md['filterInfo']['data']['delivery']['value']=='mixed', 'known mixed value still supports explicit recheck without re-entry')
ms = rpc('admin_program_activity_confirm', confirm_args(mi, md))
ok(ms['facts']['delivery_mode']=='hybrid' and ms['filterInfo']['data']==md['filterInfo']['data'], 'same mixed fact/filter values preserved')
ok('delivery_mode_unknown' not in ms['result']['reasons'] and ms['aiStatus']=='queued', 'explicit same-value confirmation clears only the missing flag')
claim = rpc('claim_seoul_program_ai', [i, saved['revision'], 'synthetic-delivery-worker', 600])[0]
ok(claim['activityConfirmation']['confirmed'] and claim['facts']['delivery_mode'] == 'offline', 'worker receives bound confirmation and current facts')
ko, ja, calls = providers(claim); writes = []
def fake_rpc(name, values):
    writes.append(name)
    if name == 'claim_seoul_program_ai': return [claim]
    if name == 'finish_seoul_program_ai': return {'candidateId': str(uuid4()), 'outcome': 'inserted'}
    raise AssertionError(name)
result = process_seoul_program_job(ProgramAIAdapter(fake_rpc), source_item_id=i, revision=saved['revision'], worker_id='synthetic-delivery-worker', summarize_ko=ko, translate_ja=ja)
ok(result.completed == 1 and writes == ['claim_seoul_program_ai', 'finish_seoul_program_ai'], 'fake summary/translation/candidate keeps worker fences; no real AI')
deny(query('admin_program_activity_confirm', confirm_args(i, rpc('admin_program_detail', [i]))), 'program_confirmation_boundary')

for reason in ['period_order_conflict', 'fee_conflict', 'application_actor_conflict']:
    ci, cd, _ = create('synthetic_'+reason, delivery_mode='unknown', activity_region='unknown', conflicts=[reason])
    cs = rpc('admin_program_activity_confirm', confirm_args(ci, cd))
    ok(reason in cs['result']['reasons'] and cs['facts']['conflicts'] == [reason], 'real conflict preserved: '+reason)
    ok(rpc('claim_seoul_program_ai', [ci, cs['revision'], 'synthetic-blocked', 600]) == [], 'unresolved conflict cannot claim AI: '+reason)
hi, hd, _ = create('synthetic_hold', delivery_mode='offline', activity_region='capital', activity_evidence=['합성 서울 개최지'])
hj = scalar("(select id from machimoa_review.processing_jobs where source_item_id="+lit(hi)+" and processing_stage='ai_enrichment')")
hq = rpc('admin_ai_queue_review_detail', [hj])
rpc('admin_ai_queue_request_recheck', [hj, hq['revision'], hq['version'], ACTOR, '', str(uuid4())])
hd = rpc('admin_program_detail', [hi])
hold_filters = copy.deepcopy(hd['filterInfo']['data'])
sql('begin;set local role service_role;select public.admin_program_save('+','.join(map(lit,[hi, hd['revision'], hd['version'], {'delivery_mode':'unknown','activity_region':'unknown'}]))+",'{}'::text[],'합성 진행 방식 재검토',"+lit(ACTOR)+');commit;')
hd = rpc('admin_program_detail', [hi])
rpc('admin_content_filter_save', [hi, hd['revision'], hd['version'], hd['filterInfo']['filterVersion'], {k:hold_filters[k] for k in ('delivery','location')}, ACTOR])
hs = rpc('admin_program_activity_confirm', confirm_args(hi, rpc('admin_program_detail', [hi])))
ok('ai_recheck_requested' in hs['result']['reasons'] and hs['aiStatus'] != 'queued', 'explicit venue confirmation never releases deliberate AI hold')
ok(rpc('claim_seoul_program_ai', [hi, hs['revision'], 'synthetic-held', 600]) == [], 'held item still cannot claim AI')
ni, nd, _ = create('synthetic_online_filter', delivery_mode='unknown', activity_region='unknown')
rpc('admin_content_filter_save', [ni, nd['revision'], nd['version'], nd['filterInfo']['filterVersion'], {'delivery':{'status':'known','value':'online'}, 'location':{'status':'not_applicable','value':None}}, ACTOR])
nd = rpc('admin_program_detail', [ni])
ok(not nd['activityReview']['pending'] and not nd['activityReview']['confirmed'], 'online filter keeps ordinary fact review; never capital confirmation')
deny(query('admin_program_activity_confirm', confirm_args(ni, nd)), 'program_confirmation_not_pending')
bad = confirm_args(ni, nd); bad[5]['delivery'] = {'status':'known','value':'onsite'}
deny(query('admin_program_activity_confirm', bad), 'program_confirmation_not_pending')
ui, ud, _ = create('synthetic_unknown_filter', delivery_mode='unknown', activity_region='unknown')
rpc('admin_content_filter_save', [ui, ud['revision'], ud['version'], ud['filterInfo']['filterVersion'], {'location':{'status':'unknown','value':None}}, ACTOR])
ud = rpc('admin_program_detail', [ui])
ok(not ud['activityReview']['pending'], 'absent public region cannot grant explicit confirmation capability')
pi, pd, _ = create('synthetic_existing_candidate', delivery_mode='unknown', activity_region='unknown')
sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,content,raw_payload,ai_status) values('seoul_reservation','synthetic_existing_candidate',"+lit(pd['revision'])+",'synthetic-delivery-candidate','합성 후보','기존 본문','{}','success');")
old_candidate = scalar("(select to_jsonb(c) from machimoa_review.curation_candidates c where source_item_id='synthetic_existing_candidate')")
deny(query('admin_program_activity_confirm', confirm_args(pi, rpc('admin_program_detail', [pi]))), 'program_confirmation_boundary')
ok(scalar("(select to_jsonb(c) from machimoa_review.curation_candidates c where source_item_id='synthetic_existing_candidate')") == old_candidate, 'existing candidate fully preserved')
for sig in ['admin_program_detail(uuid)', 'admin_program_activity_confirm(uuid,text,text,bigint,bigint,jsonb,text,uuid)']:
    for role in ['anon', 'authenticated', 'service_role']:
        ok(scalar("has_function_privilege("+lit(role)+",'public."+sig+"','execute')") == (role == 'service_role'), role+' ACL '+sig)
(ROOT/'scripts/__pycache__/seoul_delivery_fixture.json').write_text(json.dumps({'before':d, 'after':saved}, ensure_ascii=False), encoding='utf8')
print(json.dumps({'result':'passed', 'checks':len(checks), 'database':DB, 'sharedDBAccess':False, 'actualProviderCalls':0}, ensure_ascii=False))
