"""Ordinary filter save links reviewed Seoul facts; isolated synthetic PostgreSQL."""
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
sql((ROOT/'supabase/migrations/20261012060021_seoul_delivery_filter_confirmation.sql').read_text(encoding='utf8'))

ACTOR = '00000000-0000-4000-8000-000000000001'
sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation');insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation');")
run = scalar("(select run_id from public.start_ingest_run('seoul_reservation',3600))")

def create(key, filter_mode=None, **updates):
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
    f = copy.deepcopy(d['facts']); f['delivery_mode'] = filter_mode or (f['delivery_mode'] if f['delivery_mode'] in ('offline','hybrid') else 'offline'); f['activity_region'] = 'not_applicable' if f['delivery_mode']=='online' else 'capital'
    holder = {'facts': f, 'workerId':'synthetic'}; bind_program_filters(holder)
    data = holder['filterContext']['data']
    if f['delivery_mode']=='online':data['location']={'status':'not_applicable','value':None}
    rpc('admin_content_filter_save', [i, d['revision'], d['version'], d['filterInfo']['filterVersion'], {k:x for k,x in data.items() if k not in ('schema', 'category')}, ACTOR])
    return i, rpc('admin_program_detail', [i]), v

def save_args(i, d, patch=None):
    return [i, d['revision'], d['version'], d['filterInfo']['filterVersion'], patch or {k:d['filterInfo']['data'][k] for k in ('location','delivery')}, ACTOR]

def snapshot(i):
    return scalar("(select jsonb_build_object('source',to_jsonb(s),'facts',(select to_jsonb(f) from machimoa_review.source_item_program_facts f where f.source_item_id=s.id),'filter',(select to_jsonb(f) from machimoa_review.source_item_content_filters f where f.source_item_id=s.id),'events',(select jsonb_agg(to_jsonb(e)) from machimoa_review.admin_review_events e where e.source_item_id=s.id),'edits',(select jsonb_agg(to_jsonb(e)) from machimoa_review.content_filter_edits e where e.source_item_id=s.id),'confirmations',(select jsonb_agg(to_jsonb(e)) from machimoa_review.seoul_activity_confirmations e where e.source_item_id=s.id),'jobs',(select jsonb_agg(to_jsonb(j)) from machimoa_review.processing_jobs j where j.source_item_id=s.id)) from machimoa_review.source_items s where s.id="+lit(i)+")")

# Reproduce an already reviewed, blocked record BEFORE the new migration.
i, d, observed = create('synthetic_legacy_blocked', delivery_mode='unknown', activity_region='unknown', missing=['delivery_mode_unknown'])
ok(d['facts']['delivery_mode']=='unknown' and d['filterInfo']['origins']['delivery']=='operator', 'legacy reviewed filters were not linked to actual facts')
before = snapshot(i)
if args.before_fix:
    rpc('admin_content_filter_save', save_args(i,d))
    ok(rpc('admin_program_detail',[i])['facts']['delivery_mode']=='offline', 'ordinary filter save must link the saved delivery fact')
else:
    up=(ROOT/'supabase/migrations/20261012071136_seoul_filter_fact_sync.sql').read_text(encoding='utf8')
    deny("begin;alter function public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid) set search_path='public';"+up,'seoul_filter_sync_predecessor_changed')
    sql(up)
    deny(up,'seoul_filter_sync_predecessor_changed')
    ok(snapshot(i)==before, 'migration performs no backfill or content/history writes')
    d=rpc('admin_program_detail',[i])
    ok(not d['activityReview']['pending'] and d['facts']['delivery_mode']=='unknown', 'GET advertises no extra confirmation and performs no rejudgement')
    for role in ['anon','authenticated','service_role']:
        ok(not scalar("has_function_privilege("+lit(role)+",'public.admin_program_activity_confirm(uuid,text,text,bigint,bigint,jsonb,text,uuid)','execute')"),role+' cannot use retired extra confirmation route')

for changed,message in [(1,'review_conflict'),(2,'review_conflict'),(3,'content_filter_input_changed')]:
    a=save_args(i,d);a[changed]='f'*64 if changed<3 else 999
    deny(query('admin_content_filter_save',a),message)
ok(snapshot(i)==before, 'stale saves preserve values, jobs and all histories')
sql("create function public.link_test_fail() returns trigger language plpgsql as $$begin raise exception 'synthetic_audit_failure';end$$;create trigger link_test_fail before insert on machimoa_review.seoul_activity_confirmations for each row execute function public.link_test_fail();")
deny(query('admin_content_filter_save',save_args(i,d)),'synthetic_audit_failure')
ok(snapshot(i)==before, 'filter/fact/event/confirmation/job changes roll back together on audit failure')
sql('drop trigger link_test_fail on machimoa_review.seoul_activity_confirmations;drop function public.link_test_fail();')
barrier=Barrier(2)
def save_once():
    barrier.wait()
    try:return rpc('admin_content_filter_save',save_args(i,d))
    except RuntimeError as e:assert 'review_conflict' in str(e);return 'conflict'
with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:save_once(),range(2)))
ok(results.count('conflict')==1,'one ordinary save succeeds; concurrent stale save rejected')
result=next(x for x in results if isinstance(x,dict));saved=rpc('admin_program_detail',[i])
expected=copy.deepcopy(d['facts']);expected.update(delivery_mode='offline',activity_region='capital',missing=[])
ok(saved['facts']==expected,'only linked mode/region and resolved missing flags change')
ok(saved['filterInfo']['data']==d['filterInfo']['data'],'same existing filter values preserved')
ok(saved['observedFacts']==observed['program_facts'],'observed facts are never rewritten')
ok(saved['facts']['activity_evidence']==[],'no invented quote/facility/address')
ok(saved['factsVersion']==d['factsVersion']+1 and result['filterVersion']==d['filterInfo']['filterVersion']+1,'one fact and one filter version advancement in one save')
ok(saved['aiStatus']=='queued' and saved['activityReview']['confirmed'] and not saved['activityReview']['pending'],'server reassesses without extra memo or check click')
event=scalar('(select to_jsonb(e) from machimoa_review.admin_review_events e where source_item_id='+lit(i)+' order by id desc limit 1)')
ok(event['actor']==ACTOR and event['note']=='필터 저장값을 사실 판정에 연결했습니다.' and event['changed_fields']==['linked:delivery_mode','linked:activity_region'],'automatic system audit records actor and actual linking action')
ok(scalar('(select count(*) from machimoa_review.seoul_activity_confirmations where source_item_id='+lit(i)+')')==1,'prior history retained and exactly one new confirmation added')
deny(query('admin_content_filter_save',save_args(i,d)),'review_conflict')
claim=rpc('claim_seoul_program_ai',[i,saved['revision'],'synthetic-linked-worker',600])[0]
ok(claim['activityConfirmation']['confirmed'] and claim['facts']['delivery_mode']=='offline','worker receives current facts and exact confirmation/filter binding')
ko,ja,calls=providers(claim);writes=[]
def fake_rpc(name,values):
    writes.append(name)
    if name=='claim_seoul_program_ai':return [claim]
    if name=='finish_seoul_program_ai':return {'candidateId':str(uuid4()),'outcome':'inserted'}
    raise AssertionError(name)
processed=process_seoul_program_job(ProgramAIAdapter(fake_rpc),source_item_id=i,revision=saved['revision'],worker_id='synthetic-linked-worker',summarize_ko=ko,translate_ja=ja)
ok(processed.completed==1 and writes==['claim_seoul_program_ai','finish_seoul_program_ai'],'fake summary/translation/candidate uses the normal worker without retries')
claimed_before=snapshot(i)
deny(query('admin_content_filter_save',save_args(i,rpc('admin_program_detail',[i]))),'review_conflict')
ok(snapshot(i)==claimed_before,'claimed job and candidate fences preserve all values')

# Future records now resolve in their first ordinary filter save.
for mode in ['unknown','offline','hybrid']:
    ni,nd,nv=create('synthetic_new_'+mode,delivery_mode=mode,activity_region='unknown',missing=['delivery_mode_unknown'])
    ok(nd['facts']['delivery_mode']==('offline' if mode=='unknown' else mode) and nd['facts']['activity_region']=='capital','new ordinary save links '+mode)
    ok(nd['aiStatus']=='queued' and nd['filterInfo']['filterVersion']==2 and nd['factsVersion']==2,'new item requires only one save '+mode)
for reason in ['period_order_conflict','fee_conflict','application_actor_conflict']:
    ci,cd,_=create('synthetic_'+reason,delivery_mode='unknown',activity_region='unknown',conflicts=[reason])
    ok(reason in cd['result']['reasons'] and cd['facts']['conflicts']==[reason],'other conflict retained: '+reason)
    ok(rpc('claim_seoul_program_ai',[ci,cd['revision'],'synthetic-blocked',600])==[],'remaining conflict prevents AI: '+reason)
hi,hd,_=create('synthetic_hold',delivery_mode='unknown',activity_region='unknown')
hj=scalar('(select id from machimoa_review.processing_jobs where source_item_id='+lit(hi)+" and processing_stage='ai_enrichment')")
hq=rpc('admin_ai_queue_review_detail',[hj])
rpc('admin_ai_queue_request_recheck',[hj,hq['revision'],hq['version'],str(uuid4()),'',ACTOR])
hd=rpc('admin_program_detail',[hi]);hold_filters=copy.deepcopy(hd['filterInfo']['data'])
sql('begin;set local role service_role;select public.admin_program_save('+','.join(map(lit,[hi,hd['revision'],hd['version'],{'delivery_mode':'unknown','activity_region':'unknown'}]))+",'{}'::text[],'합성 재검토',"+lit(ACTOR)+');commit;')
hd=rpc('admin_program_detail',[hi]);rpc('admin_content_filter_save',save_args(hi,hd,{k:hold_filters[k] for k in ('delivery','location')}));hs=rpc('admin_program_detail',[hi])
ok(hs['facts']['delivery_mode']=='offline' and 'ai_recheck_requested' in hs['result']['reasons'],'facts can link while deliberate AI hold remains')
ok(rpc('claim_seoul_program_ai',[hi,hs['revision'],'synthetic-held',600])==[],'linking never releases an AI hold')
# Neither unknown/nationwide locations nor automatic observations confirm a physical venue.
ui,ud,_=create('synthetic_unknown_location',delivery_mode='unknown',activity_region='unknown')
# Fixture reset represents an unreviewed automatic observation, not an operator API.
sql('update machimoa_review.source_item_program_facts set facts='+lit({**ud['facts'],'delivery_mode':'unknown','activity_region':'unknown','activity_evidence':[]})+' where source_item_id='+lit(ui)+';')
sql("update machimoa_review.source_item_content_filters set origins=origins||'{\"delivery\":\"automatic\",\"location\":\"automatic\"}'::jsonb,source_binding=machimoa_review.content_filter_binding(source_item_id,revision_hash) where source_item_id="+lit(ui)+';')
sql('select machimoa_review.program_refresh('+lit(ui)+');')
ud=rpc('admin_program_detail',[ui]);rpc('admin_content_filter_save',save_args(ui,ud,{'topic':ud['filterInfo']['data']['topic']}));ud=rpc('admin_program_detail',[ui])
ok(ud['facts']['delivery_mode']=='unknown','topic save cannot convert automatic venue observations into confirmed facts')
rpc('admin_content_filter_save',save_args(ui,ud,{'delivery':{'status':'known','value':'onsite'},'location':{'status':'unknown','value':None}}));ud=rpc('admin_program_detail',[ui])
ok(ud['facts']['activity_region']=='unknown' and ud['aiStatus']!='queued','unknown region is not inferred from onsite delivery')
rpc('admin_content_filter_save',save_args(ui,ud,{'location':{'status':'known','value':{'scope':'nationwide','venues':[]}}}));ud=rpc('admin_program_detail',[ui])
ok(ud['facts']['activity_region']=='unknown','nationwide availability is not a capital venue')
# A real mode contradiction is rejected, rather than overwritten.
bi,bd,_=create('synthetic_mode_conflict',delivery_mode='offline',activity_region='capital')
# Held editing permits a filter test on an otherwise completed item.
bj=scalar('(select id from machimoa_review.processing_jobs where source_item_id='+lit(bi)+" and processing_stage='ai_enrichment')")
bq=rpc('admin_ai_queue_review_detail',[bj]);rpc('admin_ai_queue_request_recheck',[bj,bq['revision'],bq['version'],str(uuid4()),'',ACTOR]);bd=rpc('admin_program_detail',[bi]);bb=snapshot(bi)
deny(query('admin_content_filter_save',save_args(bi,bd,{'delivery':{'status':'known','value':'online'},'location':{'status':'not_applicable','value':None}})),'content_filter_facts_mismatch')
ok(snapshot(bi)==bb,'real delivery conflict leaves all facts/history/hold unchanged')
for residence,evidence in [('nationwide',['합성 전국 참여 조건']),('not_stated',[])]:
    oi,od,_=create('synthetic_online_'+residence,filter_mode='online',delivery_mode='unknown',activity_region='unknown',residence_scope=residence,residence_evidence=evidence)
    ok(od['facts']['delivery_mode']=='online' and od['facts']['activity_region']=='not_applicable','online mode links without inventing a venue: '+residence)
    ok((od['aiStatus']=='queued')==(residence=='nationwide'),'online residence gate is preserved: '+residence)
pi,pd,_=create('synthetic_prior_candidate',delivery_mode='unknown',activity_region='unknown')
sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,content,raw_payload,ai_status) values('seoul_reservation','synthetic_prior_candidate',"+lit(pd['revision'])+",'synthetic-existing-linked-candidate','합성 후보','기존 본문','{}','success');")
old_candidate=scalar("(select to_jsonb(c) from machimoa_review.curation_candidates c where source_item_id='synthetic_prior_candidate')")
deny(query('admin_content_filter_save',save_args(pi,rpc('admin_program_detail',[pi]))),'review_conflict')
ok(scalar("(select to_jsonb(c) from machimoa_review.curation_candidates c where source_item_id='synthetic_prior_candidate')")==old_candidate,'existing candidate remains completely unchanged')
# Other source adapters remain on the old save implementation.
from test_myseoul_db import fixtures as myseoul_fixtures
sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('myseoul_program','synthetic','content','rest',true,'approved_noncommercial','myseoul_program');insert into machimoa_review.source_sync_state(source_id) values('myseoul_program');")
mr=scalar("(select run_id from public.start_ingest_run('myseoul_program',3600))")
mv=copy.deepcopy(myseoul_fixtures()['fixtures'][0]['item']);mi=rpc('observe_myseoul_program',[mr,[mv],None])[0]['id'];md=rpc('admin_myseoul_program_detail',[mi]);mf=copy.deepcopy(md['facts'])
rpc('admin_content_filter_save',save_args(mi,md,{'topic':{'status':'known','value':'culture_experience'}}));ma=rpc('admin_myseoul_program_detail',[mi])
ok(ma['facts']==mf and ma['factsVersion']==md['factsVersion'],'MySeoul facts stay unchanged by the shared filter save wrapper')
for sig in ['admin_program_detail(uuid)','admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid)']:
    for role in ['anon','authenticated','service_role']:
        ok(scalar("has_function_privilege("+lit(role)+",'public."+sig+"','execute')")==(role=='service_role'),role+' ACL '+sig)
for sig in ['seoul_filter_facts_sync(uuid,text,uuid)','seoul_before_filter_fact_sync(uuid,text,text,bigint,jsonb,uuid)']:
    for role in ['anon','authenticated','service_role']:
        ok(not scalar("has_function_privilege("+lit(role)+",'machimoa_review."+sig+"','execute')"),role+' private helper inaccessible')
(ROOT/'scripts/__pycache__/seoul_filter_link_fixture.json').write_text(json.dumps({'before':d,'after':saved},ensure_ascii=False),encoding='utf8')
print(json.dumps({'result':'passed','checks':len(checks),'database':DB,'sharedDBAccess':False,'actualProviderCalls':0},ensure_ascii=False))
