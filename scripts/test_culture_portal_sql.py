"""PostgreSQL tests: only a verified local network-none disposable container."""
import copy
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
from test_culture_portal import event,assess,URL

CONTAINER='machimoa-portal-sql-local-20261112'
ROOT=Path(__file__).resolve().parents[1]
DATABASE='portal_test_'+uuid4().hex[:8]
def docker(args,body=None):
    r=subprocess.run(['docker',*args],input=body.encode('utf8') if body else None,capture_output=True)
    if r.returncode:raise RuntimeError(r.stderr.decode('utf8',errors='replace'))
    return r.stdout.decode('utf8').strip()
context=json.loads(docker(['context','inspect']))[0]
assert context['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
info=json.loads(docker(['inspect',CONTAINER]))[0]
assert info['State']['Running'] and info['HostConfig']['NetworkMode']=='none' and not info['HostConfig']['PortBindings']
assert info['Config']['Labels']['machimoa.purpose']=='portal-local-validation'
assert all(m['Type']=='volume' for m in info['Mounts']) and not info['HostConfig']['Binds']
def sql(q):return docker(['exec','-i',CONTAINER,'psql','-XqAt','-U','postgres','-d',DATABASE,'-v','ON_ERROR_STOP=1'],q)
def lit(v):return "'"+(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v)).replace("'","''")+"'"
def scalar(q):return json.loads(sql("select coalesce(to_jsonb("+q+"),'null'::jsonb);"))
def rpc(n,args):return json.loads(sql('begin;set local role service_role;select to_jsonb(public.'+n+'('+','.join(lit(v) for v in args)+'));commit;'))
checks=0
def ok(v,label):
    global checks
    if not v:raise AssertionError(label)
    checks+=1
def denied(q,reason):
    try:sql(q)
    except RuntimeError as e:ok(reason in str(e),reason);return
    raise AssertionError('expected failure '+reason)

docker(['exec',CONTAINER,'createdb','-U','postgres',DATABASE])
sql("do $$begin if not exists(select 1 from pg_roles where rolname='anon') then create role anon;create role authenticated;create role service_role bypassrls;end if;end$$;create table public.curations(id uuid primary key default gen_random_uuid(),slug text not null unique,category text,title text not null,summary text,content text not null,created_at timestamptz not null default now());alter table public.curations enable row level security;insert into public.curations(slug,title,summary,content) values('baseline-one','one','one','one'),('baseline-two','two','two','two');")
paths=sorted(p for p in (ROOT/'supabase/migrations').glob('*.sql') if '20260827022301'<=p.name<'20260903' or '20260913'<=p.name<='20261001000001_seoul_program_ai.sql' or '20261002000000'<=p.name<='20261002000300_myseoul_program_contract.sql')
for p in paths:
    try:sql(p.read_text(encoding='utf8'))
    except Exception:print('BASE FAILED',p.name);raise
    if p.name.startswith('20260827022301'):
        sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) select 'youthcenter','baseline-'||n,repeat('a',64),'candidate-'||n,'title','summary','content','{}','success' from generate_series(1,4)n;")
before=scalar("(select jsonb_agg(to_jsonb(s) order by source_id) from machimoa_review.ingest_sources s)")
sql((ROOT/'supabase/migrations/20261127045726_seoul_culture_portal_collection.sql').read_text(encoding='utf8'))
ok(scalar("(select jsonb_agg(to_jsonb(s) order by source_id) from machimoa_review.ingest_sources s where source_id<>'seoul_culture_portal')")==before,'other sources unchanged')
ok(scalar("(select not enabled and permission_status='testing_only' from machimoa_review.ingest_sources where source_id='seoul_culture_portal')"),'disabled by default')
for role in ('anon','authenticated','service_role'):
    ok(not scalar(f"has_table_privilege('{role}','machimoa_review.culture_portal_observations','SELECT,INSERT,UPDATE,DELETE')"),'no direct observation access')
    ok(scalar(f"has_function_privilege('{role}','public.observe_culture_portal_event(uuid,jsonb,jsonb)','execute')")==(role=='service_role'),'RPC permissions')
for role in ('anon','authenticated'):
    denied(f"set role {role};select public.culture_portal_collection_contract();",'permission denied')
sql("update machimoa_review.ingest_sources set enabled=true where source_id='seoul_culture_portal';")
run=scalar("(select run_id from public.start_ingest_run('seoul_culture_portal',3600))")
def observe(e):return rpc('observe_culture_portal_event',[run,e,assess(e)])
def key(e,k):
    e=copy.deepcopy(e);e['external_key']=k;e['source_url']=URL.replace('160138',k)
    e['revision_hash']=hashlib.sha256(json.dumps(e,sort_keys=True).encode()).hexdigest();return e
e=event(alt='시간 11:00~19:00');r=observe(e);sid=r['sourceItemId']
ok(r['outcome']=='new_review','new review created')
ok(scalar(f"(select count(*) from machimoa_review.processing_jobs where source_item_id={lit(sid)} and processing_stage='ai_enrichment')")==0,'no AI queue')
d=rpc('admin_review_detail',['facts',sid]);ok(d['aiStatus']=='blocked','admin blocked');ok(d['collectionReview']['issues'][0]['code'].startswith('portal_'),'diagnostics in normal admin path')
ok('주변관광지' not in d['source']['body'],'no nearby pollution')
ok(observe(e)['outcome']=='unchanged','same revision deduplicated')
ok(scalar('(select count(*) from machimoa_review.culture_portal_observations)')==1,'no repeated history')
source_before=scalar(f"(select to_jsonb(s) from machimoa_review.source_items s where id={lit(sid)})")
changed=event(fee='10,000원');r=observe(changed);ok(r['outcome']=='change_review','source changes recorded')
ok(scalar(f"(select to_jsonb(s) from machimoa_review.source_items s where id={lit(sid)})")==source_before,'existing values and revision preserved')
d2=rpc('admin_review_detail',['facts',sid]);ok(d2['version']!=d['version'],'new observation invalidates stale admin version')
denied('select machimoa_review.admin_review_lock(\'facts\','+lit(sid)+','+lit(d['revision'])+','+lit(d['version'])+",'00000000-0000-4000-8000-000000000001');",'review_conflict')
ok(scalar('(select count(*) from machimoa_review.culture_portal_observations)')==2,'both observations preserved')
base=key(event(),'160151')
# Existing source uses exactly the same canonical official detail, different query order.
sql("insert into machimoa_review.source_items(source_id,external_key,revision_hash,first_seen_at,last_seen_at,source_created_parse_status,source_updated_parse_status,disposition,min_fields,normalized_payload) values('myseoul_program','synthetic-existing',repeat('a',64),now(),now(),'missing','missing','observe_only',"+lit(dict(title=base['title'],source_url=base['source_url'].replace('?cultcode=160151&menuNo=200010','?menuNo=200010&cultcode=160151')))+"::jsonb,'{}');")
ok(observe(base)['outcome']=='duplicate_skipped','same official URL skipped across sources')
ok(scalar("(select count(*) from machimoa_review.source_items where source_id='seoul_culture_portal' and external_key='160151')")==0,'no duplicate source item')
conflicting=key(event(alt='시간 11:00~19:00'),'160151')
ok(observe(conflicting)['outcome']=='new_review','same official ID with conflicting evidence retained')
ok(scalar("machimoa_review.culture_portal_identity('https://culture.seoul.go.kr/culture/culture/cultureEvent/view.do?cultcode=1&cultcode=2')") is None,'ambiguous identity not exact duplicate')
# Equal title+place, no exact identity => review, never auto merge.
possible=key(event(),'160152')
sql("insert into machimoa_review.source_items(source_id,external_key,revision_hash,first_seen_at,last_seen_at,source_created_parse_status,source_updated_parse_status,disposition,min_fields,normalized_payload) values('myseoul_program','synthetic-suspected',repeat('b',64),now(),now(),'missing','missing','observe_only',"+lit(dict(title=possible['title']))+"::jsonb,"+lit(dict(venue='서울 구로구 잔디광장'))+"::jsonb);")
suspect=observe(possible);ok(suspect['outcome']=='new_review','possible overlap retained');ok(any(m['kind']=='possible_overlap' for m in suspect['matches']),'suspect comparison recorded')
ok('portal_duplicate_suspected' in rpc('admin_review_detail',['facts',suspect['sourceItemId']])['reasons'],'review reason visible')
# Changed observations must not restore an operator-excluded item or its completed jobs.
sql(f"update machimoa_review.source_items set disposition='non_target' where id={lit(sid)};update machimoa_review.processing_jobs set status='cancelled' where source_item_id={lit(sid)};")
held=scalar(f"(select to_jsonb(s) from machimoa_review.source_items s where id={lit(sid)})")
held_result=observe(event(fee='20,000원'))
ok(held_result['reviewQueued'] is False,'held change not counted as ready review')
ok(scalar(f"(select to_jsonb(s) from machimoa_review.source_items s where id={lit(sid)})")==held,'operator exclusion preserved')
ok(scalar(f"(select count(*) from machimoa_review.processing_jobs where source_item_id={lit(sid)} and status='queued')")==0,'no decision reopened')
out=key(event(body='상설 시설 이용 안내. 특별 프로그램은 없습니다.'),'160153')
ok(observe(out)['outcome']=='scope_excluded','explicit facility-only excluded with observation')
ok(rpc('record_culture_portal_fetch_failure',[run,URL,'detail_unavailable'])=='recorded','individual HTTP failure recorded')
parallel=key(event(),'160170')
with ThreadPoolExecutor(max_workers=4) as pool:
    parallel_results=list(pool.map(lambda _:observe(parallel),range(4)))
ok(sum(r['outcome']=='new_review' for r in parallel_results)==1,'concurrent duplicate creates once')
ok(sum(r['outcome']=='unchanged' for r in parallel_results)==3,'other concurrent calls unchanged')
ok(scalar("(select count(*) from machimoa_review.culture_portal_observations where external_key='160170')")==1,'atomic history deduplication')
for field in ('title','external_key','description','tables'):
    malformed={**key(event(),'160180'),field:None}
    denied('select public.observe_culture_portal_event('+lit(run)+','+lit(malformed)+','+lit(assess(event()))+');','portal_observation_invalid')
denied('select public.observe_culture_portal_event('+lit(run)+','+lit({**event(),'source_url':'http://localhost'})+','+lit(assess(event()))+');','portal_observation_invalid')
sql("update machimoa_review.source_sync_state set lease_expires_at=now()-interval '1 second' where source_id='seoul_culture_portal';")
denied('select public.observe_culture_portal_event('+lit(run)+','+lit(event())+','+lit(assess(event()))+');','portal_run_unavailable')
ok(scalar('(select count(*) from machimoa_review.curation_candidates)')==4,'no candidates created')
# Export synthetic DTO for the real browser component test, not product data.
(ROOT/'scripts/fixtures/culture_portal/admin-synthetic.json').write_text(json.dumps(rpc('admin_review_detail',['facts',suspect['sourceItemId']]),ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(dict(checks=checks,isolated=True,production_access=False)))
