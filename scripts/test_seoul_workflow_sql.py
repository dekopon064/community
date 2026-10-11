"""Actual PostgreSQL contracts in a verified network-none synthetic database.

No URLs/credentials/environment files/providers. Requires a fresh schema-only
database prepared in the existing explicitly labelled isolated test container.
"""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from test_program_db import fixtures,review_fixtures

parser=argparse.ArgumentParser();parser.add_argument('--database',required=True)
db=parser.parse_args().database
assert db.startswith('seoul_contract_local_') and db.replace('_','').isalnum()
container='machimoa-saved-count-sql-20261009-56ca9041'
def docker(parts,body=None):
 r=subprocess.run(['docker',*parts],input=body.encode() if body else None,capture_output=True)
 if r.returncode:raise RuntimeError(r.stderr.decode())
 return r.stdout.decode().strip()
m=json.loads(docker(['inspect',container]))[0]
assert m['State']['Running'] and m['HostConfig']['NetworkMode']=='none' and not m['HostConfig']['PortBindings']
assert m['Config']['Labels']['machimoa.purpose']=='saved-count-sql-validation'
assert m['Mounts'] and all(v['Type']=='volume' and v['Name']==container+'-data' for v in m['Mounts'])
assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
def sql(q):return docker(['exec','-i',container,'psql','-XqAt','-U','postgres','-d',db,'-v','ON_ERROR_STOP=1'],q)
def lit(v):
 if v is None:return 'NULL'
 if isinstance(v,int):return str(v)
 return "'"+(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False)).replace("'","''")+"'"
def scalar(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
def query(n,a):return 'begin;set local role service_role;select public.'+n+'('+','.join(map(lit,a))+');commit;'
def rpc(n,a):return json.loads(sql(query(n,a)))
checks=[]
def ok(v,label):assert v,label;checks.append(label)
def deny(q,reason):
 try:sql(q)
 except RuntimeError as e:assert reason in str(e),str(e);checks.append('deny: '+reason)
 else:raise AssertionError(reason)
root=Path(__file__).resolve().parents[1]
up=(root/'supabase/migrations/20261011143611_seoul_new_only_activity_confirmation.sql').read_text(encoding='utf8')
actor='00000000-0000-4000-8000-000000000001'
ok(scalar('(select count(*) from machimoa_review.source_items)')==0,'fresh database contains no source data')
ok(scalar('(select count(*) from machimoa_review.curation_candidates)')==0,'fresh database contains no candidates')
deny("begin;alter function public.observe_seoul_program(uuid,jsonb,jsonb) set search_path='public';"+up,'predecessor_changed')
# Production predecessor has CRLF only inside this body's dollar quotes.
base=sql("select pg_get_functiondef('public.admin_program_detail(uuid)'::regprocedure);")
parts=base.split('$function$');assert len(parts)==3
sql(parts[0]+'$function$'+parts[1].replace('\n','\r\n')+'$function$'+parts[2])
ok(scalar("encode(sha256(convert_to(pg_get_functiondef('public.admin_program_detail(uuid)'::regprocedure),'UTF8')),'hex')")=='7649d0a900ac1f95420ed1627e4ed17079f802924202603ecda89a5b56067cfc','exact verified production CRLF predecessor')
sql(up)
for fixture in fixtures():
 # Source-only evaluator is still the same conservative parity contract.
 from test_seoul_reservation import NOW
 actual=scalar('machimoa_review.program_evaluate('+lit(fixture['item']['program_facts'])+','+lit(NOW.isoformat())+'::timestamptz)')
 ok(actual==fixture['expected'],'pure evaluator parity '+fixture['name'])
for role in ('anon','authenticated','service_role'):
 ok(not scalar("has_table_privilege('"+role+"','machimoa_review.seoul_activity_confirmations','SELECT,INSERT,UPDATE,DELETE')"),role+' direct audit DML denied')
for sig in ['observe_seoul_program_new_only(uuid,jsonb,jsonb)','admin_program_activity_confirm(uuid,text,text,bigint,bigint,jsonb,text,uuid)','seoul_collection_contract()']:
 for role in ('anon','authenticated','service_role'):
  ok(scalar("has_function_privilege('"+role+"','public."+sig+"','execute')")== (role=='service_role'),role+' '+sig)
ok(scalar("(select relrowsecurity from pg_class where oid='machimoa_review.seoul_activity_confirmations'::regclass)"),'audit RLS enabled')
sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('seoul_reservation','seoul_open_data','content','rest',true,'approved_noncommercial','seoul_reservation');insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation');")
run=scalar("(select run_id from public.start_ingest_run('seoul_reservation',3600))")
samples=fixtures(storage=True)
def item(key,**updates):
 v=copy.deepcopy(samples[0]['item']);v['external_key']=key;v['revision_hash']=hashlib.sha256(key.encode()).hexdigest()
 v['normalized_payload']['provider_fields']['SVCID']=key
 v['normalized_payload']['source_url']=v['program_facts']['official_url']='https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id='+key
 v['program_facts'].update(updates)
 # Far-future SYNTHETIC dates for stable temporal checks; no real source data.
 for k in v['program_facts']['periods']:
  v['program_facts']['periods'][k]={'raw':'2099-10-01' if k.startswith('RCPT') else '2099-10-18','value':'2099-10-01' if k.startswith('RCPT') else '2099-10-18','status':'ok','precision':'day'}
 v['program_facts']['periods']['RCPTBGNDT']['value']='2020-01-01'
 v['program_facts']['missing']=[];v['program_facts']['conflicts']=[]
 return v
def observe(items,checkpoint=None):return rpc('observe_seoul_program_new_only',[run,items,checkpoint])
def detail(i):return rpc('admin_program_detail',[i])
def snapshot(i):return scalar("(select jsonb_build_object('source',to_jsonb(s),'facts',(select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_program_facts f where f.source_item_id=s.id),'filters',(select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_content_filters f where f.source_item_id=s.id),'observations',(select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_program_facts f where f.source_item_id=s.id),'jobs',(select jsonb_agg(to_jsonb(f)) from machimoa_review.processing_jobs f where f.source_item_id=s.id),'candidates',(select jsonb_agg(to_jsonb(c)) from machimoa_review.curation_candidates c where c.source='seoul_reservation' and c.source_item_id=s.external_key)) from machimoa_review.source_items s where s.id="+lit(i)+")")
old=item('synthetic_old');o=observe([old])[0];sid=o['id']
sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,content,raw_payload,ai_status) values('seoul_reservation','synthetic_old',"+lit(old['revision_hash'])+",'synthetic-old-candidate','합성 후보','기존 본문','{}','success');")
before=snapshot(sid)
changed=copy.deepcopy(old);changed['revision_hash']='f'*64;changed['normalized_payload']['title']='변경된 관측';changed['program_facts']['description']='새 관측 설명이지만 기존 항목은 변경하지 않습니다.'
mixed=observe([changed,item('synthetic_new')],{'page':1,'offset':2})
ok(mixed[0]['outcome']=='existing_skipped' and mixed[0]['revision']==old['revision_hash'],'changed existing revision skipped authoritatively')
ok(mixed[1]['outcome']=='new_saved','only new stored')
ok(snapshot(sid)==before,'source/facts/filters/observations/jobs/candidate fully preserved')
ok(observe([changed],{'page':1,'offset':3})[0]['outcome']=='existing_skipped','all-existing batch acknowledged')
ok(scalar("(select committed_checkpoint from machimoa_review.source_sync_state where source_id='seoul_reservation')")=={'page':1,'offset':3},'all-existing checkpoint advances without content writes')
ok(observe([],{'page':1,'offset':4})==[],'empty scoped page commits checkpoint')
deny(query('observe_seoul_program_new_only',[str(uuid4()),[item('badlease')],None]),'lease_lost')
deny(query('observe_seoul_program_new_only',[run,[item('duplicate')]*2,None]),'duplicate_program_id')
deny(query('observe_seoul_program_new_only',[run,[item('limit_'+str(n)) for n in range(41)],None]),'program_batch_invalid')
other=item('other_category');other['normalized_payload']['provider_fields']['MAXCLASSNM']='교육강좌'
deny(query('observe_seoul_program_new_only',[run,[other],None]),'invalid_program_observation')
checkpoint=scalar("(select committed_checkpoint from machimoa_review.source_sync_state where source_id='seoul_reservation')")
bad=item('rollback_bad');bad['program_facts']['activity_region']='invented'
deny(query('observe_seoul_program_new_only',[run,[item('rollback_good'),bad],{'page':2}]),'invalid_program_value')
ok(not scalar("exists(select 1 from machimoa_review.source_items where external_key='rollback_good')"),'invalid new batch rolls back fully')
ok(scalar("(select committed_checkpoint from machimoa_review.source_sync_state where source_id='seoul_reservation')")==checkpoint,'failed batch checkpoint preserved')
# Independent SQL sessions for new-vs-new and new-vs-legacy races.
def race(funcs,key):
 barrier=Barrier(2);v=item(key)
 def work(fn):barrier.wait();return rpc(fn,[run,[v],None])
 with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(work,funcs))
results=race(['observe_seoul_program_new_only']*2,'new_race')
ok(sorted(x[0]['outcome'] for x in results)==['existing_skipped','new_saved'],'concurrent new-only inserts exactly once')
ok(scalar("(select count(*) from machimoa_review.source_item_program_facts o join machimoa_review.source_items s on s.id=o.source_item_id where s.external_key='new_race')")==1,'race has only one observation')
race(['observe_seoul_program_new_only','observe_seoul_program'],'legacy_race')
ok(scalar("(select count(*) from machimoa_review.source_items where external_key='legacy_race')")==1,'legacy and new-only share source lock')

v=item('same_value',activity_region='capital',delivery_mode='offline',activity_evidence=[])
i=observe([v])[0]['id'];d=detail(i)
ok('activity_location_unknown' in d['result']['reasons'],'same known region remains pending before explicit confirmation')
ok(d['activityReview']=={'supported':True,'confirmed':False,'pending':True},'server response advertises confirmation capability')
# Synthetic filter data supplied through existing official save RPC, never table
# bypass to create a confirmation. Other missing fields remain independent.
from ingest.content_filters import empty_filters,field
filters=empty_filters('program');filters['location']=field({'scope':'specific','venues':[{'province':'11','district':None,'facility':'','address':''}]})
filters['delivery']=field('onsite')
def args(d,values=None):return [i,d['revision'],d['version'],d['factsVersion'],d['filterInfo']['filterVersion'],values or {'location':filters['location'],'delivery':filters['delivery']},'합성 공식 원문에서 서울 개최를 대조했습니다.',actor]
deny(query('admin_program_activity_confirm',args(d)[:-1]+[None]),'invalid_program_confirmation')
deny(query('admin_program_activity_confirm',args(d)[:3]+[999]+args(d)[4:]),'program_version_conflict')
deny(query('admin_program_activity_confirm',args(d)[:4]+[999]+args(d)[5:]),'content_filter_input_changed')
wrong=copy.deepcopy(filters['location']);wrong['value']['venues'][0]['province']='26'
deny(query('admin_program_activity_confirm',args(d,{'location':wrong,'delivery':filters['delivery']})),'invalid_content_filters')
original=d['facts'];barrier=Barrier(2)
def confirm():
 barrier.wait()
 try:return rpc('admin_program_activity_confirm',args(d))
 except RuntimeError as e:assert 'program_version_conflict' in str(e);return 'conflict'
with ThreadPoolExecutor(max_workers=2) as pool:confirmed=list(pool.map(lambda _:confirm(),range(2)))
ok(sum(x=='conflict' for x in confirmed)==1,'same-value confirmation serialized; stale concurrent request rejected')
saved=next(x for x in confirmed if isinstance(x,dict))
ok(saved['facts']==original,'same-value confirmation preserves every actual fact')
ok(saved['factsVersion']==d['factsVersion']+1 and saved['version']!=d['version'],'confirmation advances facts/version fence')
ok(saved['filterInfo']['filterVersion']==d['filterInfo']['filterVersion']+1,'confirmation binds current filter version')
ok(saved['activityReview']['confirmed'] and 'activity_location_unknown' not in saved['result']['reasons'],'server re-evaluation accepts explicit region without facility/address')
ok(scalar('(select count(*) from machimoa_review.seoul_activity_confirmations where source_item_id='+lit(i)+')')==1,'single audit with actor/event')
ok(scalar('(select confirmed_values from machimoa_review.seoul_activity_confirmations where source_item_id='+lit(i)+')')['activity_evidence']==[],'audit does not fabricate source evidence')
deny(query('admin_program_activity_confirm',args(d)),'program_version_conflict')
# Pure observed evaluator remains conservative; identity-bound evaluator only.
ok(scalar('machimoa_review.program_evaluate('+lit(original)+",now())->'reasons'").count('activity_location_unknown')==1,'unconfirmed pure facts do not inherit another item confirmation')
sql('update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,\'{activity_evidence}\',\'["다른 원문 근거"]\') where source_item_id='+lit(i)+';')
ok(not scalar('machimoa_review.seoul_activity_confirmed('+lit(i)+','+lit(d['revision'])+')'),'changed bound evidence invalidates confirmation')
sql('update machimoa_review.source_item_program_facts set facts='+lit(original)+' where source_item_id='+lit(i)+';')
sql('update machimoa_review.source_item_content_filters set data=jsonb_set(data,\'{location,value,venues,0,province}\',\'"41"\') where source_item_id='+lit(i)+';')
ok(not scalar('machimoa_review.seoul_activity_confirmed('+lit(i)+','+lit(d['revision'])+')'),'changed public region invalidates confirmation')

# New fixture with fully matching synthetic current facts/filters, including
# same public location: confirmation itself is the only semantic change.
from test_seoul_content import synthetic_facts
from test_program_ai import bind_program_filters,providers
from ingest.program_ai import ProgramAIAdapter,process_seoul_program_job
wf=item('synthetic_worker',**synthetic_facts());wf['program_facts']['official_url']=wf['normalized_payload']['source_url']
wf['program_facts']['activity_evidence']=[]
wi=observe([wf])[0]['id'];wd=detail(wi)
holder={'facts':wd['facts'],'claimedAt':'2099-01-01T00:00:00+00:00','leaseUntil':'2099-01-01T00:01:00+00:00','workerId':'synthetic'}
bind_program_filters(holder);fd=holder['filterContext']['data']
rpc('admin_content_filter_save',[wi,wd['revision'],wd['version'],wd['filterInfo']['filterVersion'],{k:v for k,v in fd.items() if k not in ('schema','category')},actor])
wd=detail(wi);before_filter=copy.deepcopy(wd['filterInfo']['data']);before_facts=copy.deepcopy(wd['facts'])
def wa(current=wd):return [wi,current['revision'],current['version'],current['factsVersion'],current['filterInfo']['filterVersion'],{k:current['filterInfo']['data'][k] for k in ('location','delivery')},'합성 공식 원문에서 기존 서울 개최값 재확인',actor]
sql("create function public.seoul_test_audit_failure() returns trigger language plpgsql as $$begin raise exception 'synthetic_audit_failure';end$$;create trigger seoul_test_audit_failure before insert on machimoa_review.seoul_activity_confirmations for each row execute function public.seoul_test_audit_failure();")
deny(query('admin_program_activity_confirm',wa()),'synthetic_audit_failure')
ok(detail(wi)==wd,'audit failure rolls facts/filter/version/event changes back atomically')
sql('drop trigger seoul_test_audit_failure on machimoa_review.seoul_activity_confirmations;drop function public.seoul_test_audit_failure();')
saved_w=rpc('admin_program_activity_confirm',wa())
ok(saved_w['facts']==before_facts and saved_w['filterInfo']['data']==before_filter,'confirmation of identical facts AND public region succeeds')
ok(saved_w['result']['decision']=='in_scope' and saved_w['aiStatus']=='queued','only resolved facts/filters enter synthetic AI queue')
ok(scalar('(select observed_facts from machimoa_review.source_item_program_facts where source_item_id='+lit(wi)+')')==wf['program_facts'],'observed source facts preserved')
def real_rpc(name,params):
 expression='public.'+name+'('+','.join(k+'=>'+lit(v) for k,v in params.items())+')'
 return json.loads(sql('begin;set local role service_role;select '+expression+';commit;'))
worker='synthetic-seoul-contract-worker'
claim=rpc('claim_seoul_program_ai',[wi,wd['revision'],worker,600])[0]
ok(claim['activityConfirmation']['confirmed'] and claim['activityConfirmation']['filterVersion']==claim['filterContext']['filterVersion'],'SQL claim binds region confirmation to exact filter snapshot')
ok(claim['activityConfirmation']['jobId']==claim['jobId'] and claim['activityConfirmation']['factsVersion']==saved_w['factsVersion'],'claim audit metadata preserves facts/job fences')
deny(query('admin_program_activity_confirm',wa(detail(wi))),'program_confirmation_boundary')
fake_ko,fake_ja,fake_calls=providers(claim)
events=[]
def transport(name,params):
 events.append((name,params))
 # Reuse the claimed SQL context; never create a second AI attempt.
 if name=='claim_seoul_program_ai':return [claim]
 return real_rpc(name,params)
result=process_seoul_program_job(ProgramAIAdapter(transport),source_item_id=wi,revision=claim['revision'],worker_id=worker,summarize_ko=fake_ko,translate_ja=fake_ja)
ok(result.completed==1,'Python current-input validation / fake summary-translation / actual isolated SQL candidate finish')
ok([n for n,_ in events]==['claim_seoul_program_ai','finish_seoul_program_ai'],'candidate completion uses original claim, no retry/fallback')
candidate=scalar("(select id from machimoa_review.curation_candidates where source='seoul_reservation' and source_item_id='synthetic_worker')")
ok(bool(candidate),'synthetic candidate created once')
ok(scalar('(select input_facts from machimoa_review.program_candidate_inputs where candidate_id='+lit(candidate)+')')==before_facts,'candidate stores unmodified current facts, no fake venue evidence')
ok(scalar('(select facts_version from machimoa_review.program_candidate_inputs where candidate_id='+lit(candidate)+')')==saved_w['factsVersion'],'candidate stores confirmed facts version')
ok(rpc('claim_seoul_program_ai',[wi,wd['revision'],worker,600])==[],'existing candidate blocks second claim')
candidate_before=scalar('(select to_jsonb(c) from machimoa_review.curation_candidates c where id='+lit(candidate)+')')
ok(observe([wf])[0]['outcome']=='existing_skipped','completed candidate source skipped by collection')
ok(scalar('(select to_jsonb(c) from machimoa_review.curation_candidates c where id='+lit(candidate)+')')==candidate_before,'completed candidate remains byte-for-byte unchanged')
# No publication. Candidate guard must still reject later changed confirmation.
sql('update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,\'{activity_region}\',\'"noncapital"\') where source_item_id='+lit(wi)+';')
ok(not scalar('machimoa_review.seoul_activity_confirmed('+lit(wi)+','+lit(wd['revision'])+')'),'outside-capital fact cannot retain previous confirmation')
deny('select machimoa_review.program_candidate_guard('+lit(candidate)+');','program_candidate_unavailable')
ok(scalar('(select review_status from machimoa_review.curation_candidates where id='+lit(candidate)+')')=='pending','candidate remains unapproved/unpublished')
# A venue confirmation cannot resolve a real eligibility/cost/date conflict.
conflict=item('synthetic_conflict',**synthetic_facts())
conflict['program_facts']['official_url']=conflict['normalized_payload']['source_url']
conflict['program_facts']['activity_evidence']=[]
conflict['program_facts']['conflicts']=['period_order_conflict']
ci=observe([conflict])[0]['id'];cd=detail(ci)
cf=copy.deepcopy(fd)
rpc('admin_content_filter_save',[ci,cd['revision'],cd['version'],cd['filterInfo']['filterVersion'],{k:v for k,v in cf.items() if k not in ('schema','category')},actor])
cd=detail(ci)
wrong_revision=query('admin_program_activity_confirm',[ci,'f'*64,cd['version'],cd['factsVersion'],cd['filterInfo']['filterVersion'],{k:cd['filterInfo']['data'][k] for k in ('location','delivery')},'합성 확인',actor])
deny(wrong_revision,'source_revision_conflict')
confirmed_conflict=rpc('admin_program_activity_confirm',[ci,cd['revision'],cd['version'],cd['factsVersion'],cd['filterInfo']['filterVersion'],{k:cd['filterInfo']['data'][k] for k in ('location','delivery')},'합성 원문에서 서울 개최만 확인',actor])
ok(confirmed_conflict['activityReview']['confirmed'] and confirmed_conflict['facts']['conflicts']==['period_order_conflict'],'region confirmation records only venue; other conflict facts preserved')
ok('period_order_conflict' in confirmed_conflict['result']['reasons'] and confirmed_conflict['result']['decision']=='review_required','real schedule conflict stays unresolved after venue confirmation')
ok(rpc('claim_seoul_program_ai',[ci,cd['revision'],'synthetic-blocked-worker',600])==[],'remaining conflict cannot claim AI')
print(json.dumps({'checks':len(checks),'result':'passed','database':db,'providerCalls':0,'sharedDBAccess':False,'cases':checks},ensure_ascii=False))
