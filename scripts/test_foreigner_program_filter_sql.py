"""Real PostgreSQL in a fresh, verified network-none synthetic database only."""
import copy
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
from uuid import uuid4
from test_program_db import fixtures
from test_seoul_content import synthetic_facts
from test_myseoul_db import fixtures as myfixtures

ROOT=Path(__file__).resolve().parents[1]
CONTAINER='machimoa-saved-count-sql-20261009-56ca9041'
BASE='optional_review_local_51b23613fcce'
ACTOR='00000000-0000-4000-8000-000000000001'
checks=[]
def docker(args,body=None):
 r=subprocess.run(['docker',*args],input=body.encode() if body else None,capture_output=True)
 if r.returncode:raise RuntimeError(r.stderr.decode())
 return r.stdout.decode().strip()
def lit(v):
 if v is None:return 'NULL'
 if type(v) is int:return str(v)
 return "'"+(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False)).replace("'","''")+"'"
def ok(value,label):
 assert value,label
 checks.append(label)
def main():
 m=json.loads(docker(['inspect',CONTAINER]))[0]
 assert m['State']['Running'] and m['HostConfig']['NetworkMode']=='none' and not m['HostConfig']['PortBindings']
 assert m['Config']['Labels']['machimoa.purpose']=='saved-count-sql-validation'
 assert m['Mounts'] and all(x['Type']=='volume' and x['Name']==CONTAINER+'-data' for x in m['Mounts'])
 assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
 db='foreigner_filter_local_'+uuid4().hex[:12]
 dump=docker(['exec',CONTAINER,'pg_dump','-U','postgres','-d',BASE,'--schema-only','--schema=public','--schema=machimoa_review'])
 assert dump.count('CREATE SCHEMA public;')==1
 docker(['exec',CONTAINER,'createdb','-U','postgres',db])
 def sql(q):return docker(['exec','-i',CONTAINER,'psql','-XqAt','-U','postgres','-d',db,'-v','ON_ERROR_STOP=1'],"set statement_timeout='15s';set lock_timeout='5s';"+q)
 sql(dump.replace('CREATE SCHEMA public;','-- default empty public exists',1))
 def scalar(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
 def query(name,args):return 'begin;set local role service_role;select public.'+name+'('+','.join(map(lit,args))+');commit;'
 def rpc(name,args):return json.loads(sql(query(name,args)))
 def deny(q,error):
  try:sql(q)
  except RuntimeError as e:ok(error in str(e),'denied '+error)
  else:raise AssertionError(error)
 for table in ('source_items','curation_candidates','processing_jobs'):
  ok(scalar('(select count(*) from machimoa_review.'+table+')')==0,'empty '+table)
 sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation'),('myseoul_program','synthetic','content','rest',true,'approved_noncommercial','myseoul_program');insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation'),('myseoul_program');")
 runs={s:scalar('(select run_id from public.start_ingest_run('+lit(s)+',3600))') for s in ('seoul_reservation','myseoul_program')}
 def create(key,source='seoul_reservation',legacy=True):
  if source=='seoul_reservation':
   item=copy.deepcopy(fixtures(storage=True)[0]['item'])
   f=synthetic_facts();f.update(missing=[],conflicts=[],residence_scope='unknown',residence_evidence=[],activity_evidence=[])
   f['periods']['RCPTBGNDT']['value']='2020-01-01'
   item['program_facts']=f
   item['normalized_payload']['provider_fields']['SVCID']=key
   item['normalized_payload']['source_url']=f['official_url']='https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id='+key
   name='observe_seoul_program_new_only'
  else:
   item=copy.deepcopy(next(x['item'] for x in myfixtures()['fixtures'] if x['name']=='paid_family'))
   name='observe_myseoul_program'
  if source=='seoul_reservation':item['external_key']=key
  item['revision_hash']=hashlib.sha256(key.encode()).hexdigest()
  if source=='myseoul_program':
   item['myseoul_facts']['source_revision']=item['revision_hash']
   item['normalized_payload'].update(parser_version='myseoul-html-v2-local',revision_contract='myseoul-semantic-v2',source_language='ko')
  if legacy and item.get('filterFacts'):
   item['filterFacts']['data'].pop('foreignerProgram',None)
  row=rpc(name,[runs[source],[item],None])[0]
  return row['id']
 def detail(i):return rpc('admin_content_filter_detail',[i])
 def snap(i):return scalar("(select jsonb_build_array(to_jsonb(s),(select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_program_facts f where f.source_item_id=s.id),(select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_content_filters f where f.source_item_id=s.id),(select jsonb_agg(to_jsonb(e)) from machimoa_review.content_filter_edits e where e.source_item_id=s.id),(select jsonb_agg(to_jsonb(e)) from machimoa_review.admin_review_events e where e.source_item_id=s.id)) from machimoa_review.source_items s where s.id="+lit(i)+")")
 i=create('synthetic_foreigner_legacy');before=snap(i)
 migration=(ROOT/'supabase/migrations/20261012114647_foreigner_program_filter.sql').read_text(encoding='utf-8')
 deny("begin;alter function machimoa_review.content_filter_validate(jsonb) set search_path='public';"+migration,'foreigner_filter_predecessor_changed')
 ok(snap(i)==before,'failed precondition preserves existing rows')
 sql(migration)
 ok(snap(i)==before,'migration does not backfill legacy rows or histories')
 d=detail(i);old=copy.deepcopy(d['data']);new=copy.deepcopy(old);new['foreignerProgram']={'status':'known','value':'foreigner'}
 sql('select machimoa_review.content_filter_validate('+lit(new)+'::jsonb);')
 ok(scalar('machimoa_review.content_filter_missing('+lit(old)+'::jsonb)')==scalar('machimoa_review.content_filter_missing('+lit(new)+'::jsonb)'),'new classification is not a readiness prerequisite')
 optional={**old,'foreignerProgram':{'status':'unknown','value':None}}
 ok(scalar('machimoa_review.classification_filter_missing('+lit(old)+'::jsonb)')==scalar('machimoa_review.classification_filter_missing('+lit(optional)+'::jsonb)'),'reclassification also ignores only optional nationality discovery field')
 def args(d,value):return [i,d['revision'],d['version'],d['filterVersion'],{'foreignerProgram':{'status':'known','value':value}},ACTOR]
 saved=rpc('admin_content_filter_save',args(d,'foreigner'))
 ok(saved['data']['foreignerProgram']=={'status':'known','value':'foreigner'},'ordinary filter RPC saves operator classification')
 ok(saved['filterVersion']==d['filterVersion']+1 and saved['origins']['foreignerProgram']=='operator','one version advance and operator origin')
 ok({k:v for k,v in saved['data'].items() if k!='foreignerProgram'}==old,'all existing filter values preserved')
 after=snap(i)
 ok(after[0]==before[0] and after[1]==before[1],'source observations and current facts preserved')
 history=scalar('(select to_jsonb(e) from machimoa_review.content_filter_edits e where source_item_id='+lit(i)+' order by filter_version desc limit 1)')
 ok(history['actor']==ACTOR and history['fields']==['foreignerProgram'],'existing actor/history contract records only changed field')
 noop=rpc('admin_content_filter_save',args(saved,'foreigner'))
 ok(noop==saved and snap(i)==after,'identical operator selection makes no writes or extra versions')
 other=rpc('admin_content_filter_save',args(saved,'other'))
 ok(other['data']['foreignerProgram']['value']=='other' and other['filterVersion']==saved['filterVersion']+1,'explicit other is a distinct stored decision')
 deny(query('admin_content_filter_save',args(d,'foreigner')),'review_conflict')
 bad=args(other,'other');bad[3]-=1;deny(query('admin_content_filter_save',bad),'content_filter_input_changed')
 bad=args(other,'other');bad[1]='a'*64;deny(query('admin_content_filter_save',bad),'review_conflict')
 for value in ('eligible','foreign_only',None):
  bad=args(other,value);deny(query('admin_content_filter_save',bad),'invalid_content_filters')
 bad=args(other,'foreigner');bad[-1]=None;deny(query('admin_content_filter_save',bad),'invalid_content_filters')
 deny('begin;set local role authenticated;select public.admin_content_filter_save('+','.join(map(lit,args(other,'foreigner')))+');','permission denied')
 sql("update machimoa_review.processing_jobs set status='claimed',claimed_at=clock_timestamp(),claim_lease_until=clock_timestamp()+interval '5 minutes',claimed_by='synthetic' where source_item_id="+lit(i)+" and processing_stage='content_review';")
 locked=detail(i);deny(query('admin_content_filter_save',args(locked,'foreigner')),'content_filter_processing_active')
 sql("update machimoa_review.processing_jobs set status='queued',claimed_at=null,claim_lease_until=null,claimed_by=null where source_item_id="+lit(i)+" and claimed_by='synthetic';")
 current=detail(i);barrier=Barrier(2)
 def race(value):
  barrier.wait()
  try:return rpc('admin_content_filter_save',args(current,value))
  except RuntimeError as e:return str(e)
 with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(race,['foreigner','foreigner']))
 ok(sum(isinstance(x,dict) for x in outcomes)==1 and sum(isinstance(x,str) and 'review_conflict' in x for x in outcomes)==1,'concurrent edits have one success and one conflict')
 mid=create('synthetic_foreigner_my','myseoul_program');md=detail(mid)
 my_before=snap(mid)
 saved_my=rpc('admin_content_filter_save',[mid,md['revision'],md['version'],md['filterVersion'],{'foreignerProgram':{'status':'known','value':'foreigner'}},ACTOR])
 ok(saved_my['data']['foreignerProgram']['value']=='foreigner','MySeoul uses the same ordinary save contract')
 ok(snap(mid)[0:2]==my_before[0:2],'MySeoul original source/facts unchanged')
 for target in (i,mid):
  classified=rpc('admin_review_classification_detail',[target])
  ok(classified['filters']['foreignerProgram']=={'status':'known','value':'foreigner'},'native saved choice retained in reclassification draft')
 ok(scalar('(select count(*) from machimoa_review.curation_candidates)')==0,'no candidates generated')
 # Rows after migration still accept legacy extraction packets without invented decisions.
 nid=create('synthetic_foreigner_new');nd=detail(nid)
 ok('foreignerProgram' not in nd['data'],'existing extraction shape remains accepted without backfill')
 extended=detail(create('synthetic_foreigner_extended',legacy=False))
 ok(extended['data']['foreignerProgram']=={'status':'unknown','value':None},'new extraction keeps nationality classification unknown')
 print(json.dumps({'database':db,'checks':len(checks),'result':'passed','network':'none','aiCalls':0},ensure_ascii=False))
if __name__=='__main__':main()
