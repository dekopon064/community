"""Real PostgreSQL transactions; fresh schema-only DB in network-none container.

Synthetic facts only. Never reads credentials, calls providers or shared DBs.
Two independent psql sessions exercise races. Test claims are SQL fences only.
"""
import argparse, copy, hashlib, json, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4
from test_program_db import fixtures as seoul_fixtures
from test_myseoul_db import fixtures as myseoul_fixtures

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--schema-database',default='seoul_contract_local_20261011_release')
parser.add_argument('--node',default='node')
args=parser.parse_args()
assert args.schema_database.startswith('seoul_contract_local_') and args.schema_database.replace('_','').isalnum()
CONTAINER='machimoa-saved-count-sql-20261009-56ca9041'
DB='ai_recheck_local_'+uuid4().hex[:12]
def docker(parts,body=None):
 result=subprocess.run(['docker',*parts],input=body.encode() if isinstance(body,str) else body,capture_output=True)
 if result.returncode:raise RuntimeError(result.stderr.decode('utf8'))
 return result.stdout.decode('utf8').strip()
m=json.loads(docker(['inspect',CONTAINER]))[0]
assert m['State']['Running'] and m['HostConfig']['NetworkMode']=='none' and not m['HostConfig']['PortBindings']
assert m['Config']['Labels'].get('machimoa.purpose')=='saved-count-sql-validation'
assert m['Mounts'] and all(v['Type']=='volume' and v['Name']==CONTAINER+'-data' for v in m['Mounts'])
assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
dump=docker(['exec',CONTAINER,'pg_dump','-U','postgres','-d',args.schema_database,'--schema-only','--schema=public','--schema=machimoa_review'])
assert dump.count('CREATE SCHEMA public;')==1
dump=dump.replace('CREATE SCHEMA public;','-- Fresh database already contains empty public schema.',1)
docker(['exec',CONTAINER,'createdb','-U','postgres',DB])
def sql(q):return docker(['exec','-i',CONTAINER,'psql','-XqAt','-U','postgres','-d',DB,'-v','ON_ERROR_STOP=1','-v','VERBOSITY=verbose'],"set statement_timeout='15s';set lock_timeout='5s';"+q)
sql(dump)
def lit(v):
 if v is None:return 'NULL'
 if isinstance(v,bool):return str(v).lower()
 if isinstance(v,int):return str(v)
 return "'"+(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False)).replace("'","''")+"'"
def scalar(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
def query(name,a):
 values=list(map(lit,a))
 if name=='admin_review_ai_queue':values[2]='array['+','.join(map(lit,a[2]))+']::uuid[]'
 return 'begin;set local role service_role;select public.'+name+'('+','.join(values)+');commit;'
def rpc(name,a):return json.loads(sql(query(name,a)))
checks=[]
dto_details=[];dto_queues=[]
def ok(condition,label):
 assert condition,label
 checks.append(label)
def deny(q,message):
 try:sql(q)
 except RuntimeError as e:assert message in str(e),str(e);checks.append('denied '+message)
 else:raise AssertionError('expected '+message)
for t in ['source_items','curation_candidates','processing_jobs']:
 ok(scalar('(select count(*) from machimoa_review.'+t+')')==0,'schema-only copy has zero '+t)
up=(ROOT/'supabase/migrations/20261012014759_ai_queue_recheck_hold.sql').read_text(encoding='utf8')
deny("begin;alter function public.admin_program_detail(uuid) set search_path='public';"+up,'ai_recheck_predecessor_changed')
ok(scalar("to_regclass('machimoa_review.ai_rechecks') is null"),'predecessor failure atomically creates nothing')
sql(up)
pending_up=(ROOT/'supabase/migrations/20261012023943_ai_queue_recheck_pending_review.sql').read_text(encoding='utf8')
deny("begin;alter function public.admin_ai_queue_review_detail(uuid) set search_path='public';"+pending_up,'ai_recheck_pending_predecessor_changed')
sql(pending_up)
deny(pending_up,'ai_recheck_pending_predecessor_changed')
print(json.dumps({'database':DB,'stage':'migration-applied','network':'none'}),flush=True)
deny(up,'ai_recheck_predecessor_changed')
for t in ['ai_rechecks','ai_recheck_receipts']:
 ok(scalar("(select relrowsecurity from pg_class where oid='machimoa_review."+t+"'::regclass)"),t+' RLS')
 for role in ['anon','authenticated','service_role']:
  ok(not scalar("has_table_privilege('"+role+"','machimoa_review."+t+"','SELECT,INSERT,UPDATE,DELETE')"),role+' no direct '+t)
for sig in ['admin_ai_queue_review_detail(uuid)','admin_ai_queue_request_recheck(uuid,text,text,uuid,text,uuid)','admin_ai_queue_complete_recheck(uuid,text,text,uuid,text,uuid)','admin_program_detail(uuid)','admin_myseoul_program_detail(uuid)','admin_review_ai_queue(integer,integer,uuid[])']:
 for role in ['anon','authenticated','service_role']:
  ok(scalar("has_function_privilege('"+role+"','public."+sig+"','execute')")== (role=='service_role'),sig+' '+role+' ACL')
for role in ['anon','authenticated','service_role']:
 for sig in ['ai_recheck_pending(uuid,text)','ai_recheck_job_guard()','ai_recheck_command(uuid,text,text,uuid,text,uuid,text)','ai_recheck_base_program_detail(uuid)','ai_recheck_base_myseoul_detail(uuid)','ai_recheck_base_queue(integer,integer,uuid[])']:
  ok(not scalar("has_function_privilege('"+role+"','machimoa_review."+sig+"','execute')"),sig+' private '+role)
ACTOR='00000000-0000-4000-8000-000000000001'
for name in ['seoul_reservation','myseoul_program','youthcenter_policy','youthcenter_content']:
 sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values("+','.join(map(lit,[name,'synthetic','content','rest',True,'approved_noncommercial',name]))+");insert into machimoa_review.source_sync_state(source_id) values("+lit(name)+");")
RUNS={n:scalar("(select run_id from public.start_ingest_run("+lit(n)+",3600))") for n in ['seoul_reservation','myseoul_program']}
known=lambda v:{'status':'known','value':v}
na={'status':'not_applicable','value':None}
def filters():
 return {'schema':'content-filters-v1','category':'program','topic':known('culture_experience'),'location':known({'scope':'specific','venues':[{'province':'11','district':'종로구','facility':'','address':''}]}),'delivery':known('onsite'),'audience':known('other'),'spaceKind':na,'application':known({'deadlineKind':'fixed','start':{'value':'2020-01-01','precision':'day'},'end':{'value':'2099-10-15','precision':'day'},'sourceStatus':'unknown'}),'schedule':na}
def source(origin='seoul_reservation',fill_filters=True):
 key=uuid4().hex.upper();rev=hashlib.sha256(key.encode()).hexdigest()
 if origin=='seoul_reservation':
  p=copy.deepcopy(seoul_fixtures(storage=True)[0]['item']);p['external_key']=key;p['revision_hash']=rev
  p['normalized_payload']['provider_fields']['SVCID']=key
  p['program_facts'].update(missing=[],conflicts=[])
  for k in p['program_facts']['periods']:
   day='2020-01-01' if k.endswith('BGNDT') else '2099-10-15'
   p['program_facts']['periods'][k]={'raw':day,'value':day,'status':'ok','precision':'day'}
  sid=rpc('observe_seoul_program_new_only',[RUNS[origin],[p],None])[0]['id']
 elif origin=='myseoul_program':
  p=copy.deepcopy(myseoul_fixtures()['fixtures'][0]['item']);old=p['external_key'].split(':')[-1]
  p=json.loads(json.dumps(p).replace(old,key));p['revision_hash']=rev;p['myseoul_facts']['source_revision']=rev
  f=p['myseoul_facts'];f.update(public_category='program',issues=[])
  for group in ['application','operation']:
   for period in f['periods'][group]:period.update(status='ok',endpoints=[{'value':'2020-01-01','precision':'day'},{'value':'2099-10-15','precision':'day'}])
  sid=rpc('observe_myseoul_program',[RUNS[origin],[p],None])[0]['id']
 else:
  raise AssertionError('unsupported synthetic source')
 if not fill_filters:
  job=scalar("(select id from machimoa_review.processing_jobs where source_item_id="+lit(sid)+" and revision_hash="+lit(rev)+" and processing_stage='ai_enrichment')")
  assert job,'synthetic source has no initial AI job'
  return job
 d=rpc('admin_program_detail' if origin=='seoul_reservation' else 'admin_myseoul_program_detail',[sid])
 fd=filters()
 for k in ['application','delivery']:
  if d['filterInfo']['data'][k]['status']=='known':fd[k]=copy.deepcopy(d['filterInfo']['data'][k])
 # Source-authoritative values match the synthetic current facts.
 rpc('admin_content_filter_save',[sid,rev,d['version'],d['filterInfo']['filterVersion'],{k:v for k,v in fd.items() if k not in ['schema','category']},ACTOR])
 # Explicit unchanged venue confirmation if that source asks for it.
 d=rpc('admin_program_detail' if origin=='seoul_reservation' else 'admin_myseoul_program_detail',[sid])
 if d.get('activityReview',{}).get('pending'):
  if origin=='seoul_reservation':rpc('admin_program_activity_confirm',[sid,rev,d['version'],d['factsVersion'],d['filterInfo']['filterVersion'],{k:fd[k] for k in ['location','delivery']},'합성 서울 개최 확인',ACTOR])
  else:rpc('admin_myseoul_activity_confirm',[sid,rev,d['version'],d['filterInfo']['filterVersion'],{'location':fd['location']},{},ACTOR])
 job=scalar("(select id from machimoa_review.processing_jobs where source_item_id="+lit(sid)+" and revision_hash="+lit(rev)+" and processing_stage='ai_enrichment')")
 assert job,'synthetic source did not queue AI: '+json.dumps(d,ensure_ascii=False)
 v=detail(job);assert v['canRecheck'],json.dumps(v,ensure_ascii=False)
 return job
def detail(job):return rpc('admin_ai_queue_review_detail',[job])
def command(d,action='request_recheck',request=None,note='합성 원문 재확인 요청',actor=ACTOR):
 return [d['jobId'],d['revision'],d['version'],request or str(uuid4()),note,actor]
def hold(job):return rpc('admin_ai_queue_request_recheck',command(detail(job)))
def complete(job):return rpc('admin_ai_queue_complete_recheck',command(detail(job),note='합성 재검토 완료'))
def snapshot(d):
 sid=lit(d['sourceItemId'])
 return scalar("jsonb_build_array((select jsonb_build_array(normalized_payload,min_fields,revision_hash) from machimoa_review.source_items where id="+sid+"),(select jsonb_agg(jsonb_build_array(facts,observed_facts,facts_version,source_snapshot)) from machimoa_review.source_item_program_facts where source_item_id="+sid+"),(select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_content_filters f where source_item_id="+sid+"),(select jsonb_agg(to_jsonb(c)) from machimoa_review.review_classifications c where source_item_id="+sid+"),(select jsonb_agg(to_jsonb(c)) from machimoa_review.curation_candidates c))")

for origin in ['seoul_reservation','myseoul_program']:
 job=source(origin);d=detail(job);before=snapshot(d);a=command(d);held=rpc('admin_ai_queue_request_recheck',a)
 ok(held['status']=='cancelled' and held['recheckPending'] and not held['canRecheck'],origin+' explicit hold')
 ok(snapshot(held)==before,origin+' source/current/observed/filters/candidates unchanged')
 ok(held['version']!=d['version'],origin+' hold changes version')
 dto_details.extend([d,held]);dto_queues.append(rpc('admin_review_ai_queue',[0,25,[job]]))
 ok(rpc('admin_ai_queue_request_recheck',a)==held,origin+' exact receipt replay')
 for i,v in [(0,str(uuid4())),(1,'f'*64),(2,'f'*64),(4,'다른 요청'),(5,str(uuid4()))]:
  b=a.copy();b[i]=v;deny(query('admin_ai_queue_request_recheck',b),'request_id_conflict')
 deny(query('admin_ai_queue_complete_recheck',command(d)),'recheck_conflict')
 rd=rpc('admin_program_detail' if origin=='seoul_reservation' else 'admin_myseoul_program_detail',[d['sourceItemId']])
 ok(rd['status']=='open' and 'ai_recheck_requested' in rd['result']['reasons'],origin+' real existing fact review opens')
 ok(any(x['jobId']==job for x in rpc('admin_review_ai_queue',[0,25,[]])['held']),origin+' hold survives queue refresh')
 # Actual refresh must not release a deliberate hold or change confirmed values.
 sql('select machimoa_review.'+('program_refresh' if origin=='seoul_reservation' else 'myseoul_refresh')+'('+lit(d['sourceItemId'])+');')
 ok(detail(job)['recheckPending'] and detail(job)['status']=='cancelled',origin+' native refresh keeps hold')
 ok(scalar("(select status='queued' and 'ai_recheck_requested'=any(reason_codes) from machimoa_review.processing_jobs where source_item_id="+lit(d['sourceItemId'])+" and revision_hash="+lit(d['revision'])+" and processing_stage='content_review')"),origin+' unresolved hold marker survives refresh')
 claim='claim_seoul_program_ai' if origin=='seoul_reservation' else 'claim_myseoul_program_ai'
 ok(rpc(claim,[d['sourceItemId'],d['revision'],'synthetic-held-worker',300])==[],origin+' actual targeted claim cannot run held job')
 deny("update machimoa_review.processing_jobs set status='claimed',claimed_at=now(),claimed_by='synthetic',claim_lease_until=now()+interval '5 minutes' where id="+lit(job)+';','ai_recheck_pending')
 fresh=detail(job);old_version=fresh['version'];patch={'topic':known('language_learning')}
 rpc('admin_content_filter_save',[d['sourceItemId'],d['revision'],fresh['review']['version'],fresh['review']['filterInfo']['filterVersion'],patch,ACTOR])
 ok(detail(job)['status']=='cancelled' and detail(job)['recheckPending'],origin+' actual filter save cannot release hold')
 ok(detail(job)['version']!=old_version,origin+' filter write invalidates recheck version')
 deny(query('admin_ai_queue_complete_recheck',command(fresh,note='합성 완료')),'recheck_conflict')
 final=complete(job)
 ok(not final['recheckPending'] and final['status']=='queued',origin+' explicit complete freshly re-evaluates ready input')
 ok(final['review']['filterInfo']['data']['topic']==patch['topic'],origin+' edited filter preserved')
 ok(not any(x['jobId']==job for x in rpc('admin_review_ai_queue',[0,25,[]])['held']),origin+' completed hold disappears from held list')
 ok(scalar('(select count(*) from machimoa_review.curation_candidates)')==0,origin+' completion never creates candidate')
 dto_details.append(final)
 print(origin+' native hold/release passed',flush=True)

# Already pending review must not prevent a deliberate hold. This recreates the
# deployed queue shape without reading any real content or using its identifiers.
for origin in ['seoul_reservation','myseoul_program']:
 job=source(origin,fill_filters=False);d=detail(job);sid=d['sourceItemId'];before=snapshot(d)
 ok(d['review']['filterInfo']['missing'] and d['canRecheck'],origin+' pending filters still permit explicit hold')
 old_codes=scalar("(select reason_codes from machimoa_review.processing_jobs where source_item_id="+lit(sid)+" and processing_stage='content_review' and revision_hash="+lit(d['revision'])+")")
 held=hold(job)
 ok(held['status']=='cancelled' and held['recheckPending'],origin+' pending-review AI queue deliberately held')
 codes=scalar("(select reason_codes from machimoa_review.processing_jobs where source_item_id="+lit(sid)+" and processing_stage='content_review' and revision_hash="+lit(d['revision'])+")")
 ok(set(old_codes or [])<=set(codes) and 'ai_recheck_requested' in codes,origin+' existing filter/source review reasons preserved')
 ok(snapshot(held)==before,origin+' holding incomplete source preserves facts and filters')
 final=complete(job)
 ok(final['status']=='cancelled' and not final['recheckPending'] and final['review']['filterInfo']['missing'],origin+' incomplete review cannot requeue after hold completion')
 dto_details.extend([d,held,final])

# Invalid commands and the actor/action/request binding fail without a hold.
job=source();d=detail(job)
for index,value in [(0,None),(1,None),(1,'bad'),(2,None),(2,'bad'),(3,None),(4,''),(4,' '),(4,'x'*1001),(5,None)]:
 a=command(d);a[index]=value;deny(query('admin_ai_queue_request_recheck',a),'invalid_recheck')
deny('select machimoa_review.ai_recheck_command('+','.join(map(lit,command(d)))+',NULL);','invalid_recheck')
ok(not detail(job)['recheckPending'],'invalid commands create no hold')
deny(query('admin_ai_queue_complete_recheck',command(d)),'recheck_conflict')
for role in ['anon','authenticated']:
 deny('begin;set local role '+role+';select public.admin_ai_queue_review_detail('+lit(job)+');','42501')

# Audit failure rolls the job/source/hold/receipt changes back as one transaction.
before=detail(job);before_values=snapshot(before)
sql("create function public.synthetic_recheck_audit_failure() returns trigger language plpgsql as $$begin raise exception 'synthetic_audit_failure';end$$;create trigger synthetic_recheck_audit_failure before insert on machimoa_review.ai_recheck_receipts for each row execute function public.synthetic_recheck_audit_failure();")
deny(query('admin_ai_queue_request_recheck',command(before)),'synthetic_audit_failure')
ok(detail(job)==before and snapshot(before)==before_values,'failed request rolls everything back')
sql('drop trigger synthetic_recheck_audit_failure on machimoa_review.ai_recheck_receipts;drop function public.synthetic_recheck_audit_failure();')
hold(job);before=detail(job)
sql("create function public.synthetic_recheck_audit_failure() returns trigger language plpgsql as $$begin raise exception 'synthetic_audit_failure';end$$;create trigger synthetic_recheck_audit_failure before insert on machimoa_review.ai_recheck_receipts for each row execute function public.synthetic_recheck_audit_failure();")
deny(query('admin_ai_queue_complete_recheck',command(before,note='합성 완료')),'synthetic_audit_failure')
ok(detail(job)==before,'failed complete preserves pending hold and version')
sql('drop trigger synthetic_recheck_audit_failure on machimoa_review.ai_recheck_receipts;drop function public.synthetic_recheck_audit_failure();')
complete(job);replay=command(detail(job))
# Fresh request id is required for a new episode; old receipts never reapply writes.
held_again=rpc('admin_ai_queue_request_recheck',replay)
ok(held_again['recheckPending'],'same source can start a separate deliberate episode')
ok(scalar('(select count(*) from machimoa_review.ai_rechecks where job_id='+lit(job)+')')==2,'completed hold history retained')

# A real facts conflict remains review-required after explicit hold completion.
job=source();d=hold(job);sid=d['sourceItemId']
sql("update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,'{conflicts}','[\"period_order_conflict\"]'),facts_version=facts_version+1 where source_item_id="+lit(sid)+';select machimoa_review.program_refresh('+lit(sid)+');')
blocked=complete(job)
ok(not blocked['recheckPending'] and blocked['status']=='cancelled','remaining real conflict does not requeue AI')
ok('period_order_conflict' in blocked['review']['result']['reasons'],'actual schedule conflict preserved')
ok(rpc('claim_seoul_program_ai',[sid,d['revision'],'synthetic-blocked',300])==[],'conflicting source cannot claim after release')
dto_details.append(blocked)

# Missing filter, revoked permission and exclusion finish review but never queue.
job=source();held=hold(job);sid=held['sourceItemId']
sql("update machimoa_review.processing_jobs set reason_codes=reason_codes||array['relationship_unresolved'] where source_item_id="+lit(sid)+" and processing_stage='content_review';")
final=complete(job)
ok(final['status']=='cancelled' and not final['recheckPending'],'completion never resolves an unrelated review reason')
ok(scalar("(select status='queued' and 'relationship_unresolved'=any(reason_codes) and not ('ai_recheck_requested'=any(reason_codes)) from machimoa_review.processing_jobs where source_item_id="+lit(sid)+" and processing_stage='content_review')"),'only hold reason removed; actual unresolved reason preserved')

for condition in ['missing_filter','permission','excluded']:
 job=source();d=hold(job);sid=d['sourceItemId']
 if condition=='missing_filter':
  sql("update machimoa_review.source_item_content_filters set data=jsonb_set(data,'{topic}','{\"status\":\"unknown\",\"value\":null}'),filter_version=filter_version+1 where source_item_id="+lit(sid)+';')
 elif condition=='permission':sql("update machimoa_review.ingest_sources set enabled=false where source_id='seoul_reservation';")
 else:
  native=d['review'];rpc('admin_program_exclude',[sid,d['revision'],native['version'],'합성 서비스 범위 제외',ACTOR])
 final=complete(job)
 ok(not final['recheckPending'] and final['status']=='cancelled',condition+' does not queue AI')
 if condition=='permission':sql("update machimoa_review.ingest_sources set enabled=true where source_id='seoul_reservation';")
 dto_details.append(final)

# Native values and current target classification are independent and preserved.
job=source('myseoul_program');held=hold(job);sid=held['sourceItemId']
c=rpc('admin_review_classification_detail',[sid]);native_before=snapshot(held)
facts={'productType':'living_guide','category':'living','scope':'nationwide','regions':[],'evidence':'합성 생활 안내','foreignEligibility':'unknown','delivery':'online','deadlineKind':'','deadlineOn':'','eventStart':'','eventEnd':''}
c=rpc('admin_review_reclassify',[sid,c['revision'],c['version'],c['classificationVersion'],facts,None,'합성 원문 근거에 따라 생활 안내로 재분류합니다.',ACTOR])
ok(detail(job)['recheckPending'] and detail(job)['status']=='cancelled','real reclassification save cannot release hold')
before=snapshot(detail(job));final=complete(job)
ok(final['classification']['facts']==facts and final['status']=='queued','release evaluates current target classification')
ok(snapshot(final)==before,'release preserves native facts and classification/filter snapshots')
ok(final['classification']['ready'],'target classification ready only after explicit completion')
dto_details.extend([detail(job),final])
claim=rpc('claim_reclassified_content_ai',[sid,final['revision'],final['classification']['classificationVersion'],'synthetic-target-fence',300])
ok(claim['jobId']==job,'actual reclassified claim uses original job after release')
deny(query('admin_ai_queue_request_recheck',command(detail(job))),'recheck_conflict')

# Any change in native classification input must remain a conflict, not be rebased.
job=source();held=hold(job);sid=held['sourceItemId'];c=rpc('admin_review_classification_detail',[sid])
rpc('admin_review_reclassify',[sid,c['revision'],c['version'],c['classificationVersion'],facts,None,'합성 원문 근거에 따라 생활 안내로 재분류합니다.',ACTOR])
sql('update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id='+lit(sid)+';')
final=complete(job)
ok(final['status']=='cancelled' and 'classification_input_changed' in final['classification']['reasons'],'stale classification/native snapshot stays blocked')

# Existing candidates, including old revisions and published history, stay exact.
def seed_candidate(d):
 key=scalar('(select external_key from machimoa_review.source_items where id='+lit(d['sourceItemId'])+')')
 return sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) values("+','.join(map(lit,[d['sourceName'],key,'e'*64,'synthetic-candidate-'+uuid4().hex,'합성 후보','합성 요약','합성 기존 본문',{},'success']))+") returning id;")
job=source();d=detail(job);cid=seed_candidate(d);before=snapshot(d)
ok(not detail(job)['canRecheck'],'existing older-revision candidate blocks request')
deny(query('admin_ai_queue_request_recheck',command(detail(job))),'recheck_conflict')
ok(snapshot(d)==before,'candidate rejection preserves complete candidate/source values')
job=source();d=hold(job);cid=seed_candidate(d);before=snapshot(d)
deny(query('admin_ai_queue_complete_recheck',command(detail(job))),'recheck_conflict')
ok(detail(job)['recheckPending'] and snapshot(d)==before,'concurrent candidate blocks release without history mutation')

# Two independent transactions: at most one write wins a stale version race.
def race(actions):
 barrier=Barrier(len(actions))
 def work(fn):
  barrier.wait()
  try:return ('saved',fn())
  except RuntimeError as e:
   assert 'PT409' in str(e),str(e)
   return ('conflict',str(e))
 with ThreadPoolExecutor(max_workers=len(actions)) as pool:return list(pool.map(work,actions))
job=source();d=detail(job)
r=race([lambda:rpc('admin_ai_queue_request_recheck',command(d)),lambda:rpc('admin_ai_queue_request_recheck',command(d))])
ok(sorted(x[0] for x in r)==['conflict','saved'],'two concurrent hold writes: exactly one wins')
ok(scalar('(select count(*) from machimoa_review.ai_rechecks where job_id='+lit(job)+' and completed_at is null)')==1,'concurrent hold keeps one pending episode')
d=detail(job)
r=race([lambda:rpc('admin_ai_queue_complete_recheck',command(d,note='합성 완료 A')),lambda:rpc('admin_ai_queue_complete_recheck',command(d,note='합성 완료 B'))])
ok(sorted(x[0] for x in r)==['conflict','saved'],'two concurrent complete writes: exactly one wins')
ok(detail(job)['status']=='queued' and not detail(job)['recheckPending'],'concurrent complete leaves one fresh queue state')
for origin in ['seoul_reservation','myseoul_program']:
 job=source(origin);d=detail(job);claim_fn='claim_seoul_program_ai' if origin=='seoul_reservation' else 'claim_myseoul_program_ai'
 r=race([lambda:rpc('admin_ai_queue_request_recheck',command(d)),lambda:rpc(claim_fn,[d['sourceItemId'],d['revision'],'synthetic-race-fence',300])])
 final=detail(job)
 ok(final['status'] in ['claimed','cancelled'],origin+' concurrent hold/claim has one authoritative outcome')
 if final['status']=='claimed':ok(not final['recheckPending'] and any(x[0]=='conflict' for x in r),origin+' claim winner rejects hold')
 else:ok(final['recheckPending'] and next(x[1] for x in r if x[0]=='saved' and isinstance(x[1],list))==[],origin+' hold winner denies claim')

# Current revision, expired claims and retry metadata are never reset by recheck.
for state in ['revision','retry','expired_claim']:
 job=source();d=detail(job)
 if state=='revision':sql('update machimoa_review.source_items set revision_hash=repeat(\'f\',64) where id='+lit(d['sourceItemId'])+';')
 elif state=='retry':sql('update machimoa_review.processing_jobs set retry_count=1 where id='+lit(job)+';')
 else:sql("update machimoa_review.processing_jobs set status='claimed',claimed_at=now()-interval '1 hour',claimed_by='synthetic-expired',claim_lease_until=now()-interval '1 minute' where id="+lit(job)+';')
 before=scalar('(select to_jsonb(j) from machimoa_review.processing_jobs j where id='+lit(job)+')')
 deny(query('admin_ai_queue_request_recheck',command(d)),'source_revision_conflict' if state=='revision' else 'recheck_conflict')
 ok(scalar('(select to_jsonb(j) from machimoa_review.processing_jobs j where id='+lit(job)+')')==before,state+' metadata preserved after rejection')

for origin in ['youthcenter_policy','youthcenter_content']:
 sid=str(uuid4());rev=hashlib.sha256(sid.encode()).hexdigest()
 sql("insert into machimoa_review.source_items(id,source_id,external_key,revision_hash,first_seen_at,last_seen_at,source_created_parse_status,source_updated_parse_status,disposition,min_fields,normalized_payload,has_source_url,body_usable) values("+','.join(map(lit,[sid,origin,sid,rev]))+",now(),now(),'missing','missing','observe_only','{}',"+lit({'plcyNm':'합성 정책','pstTtl':'합성 안내','plain_text':'합성 전국 정책 안내 본문이며 실제 콘텐츠가 아닙니다.','source_url':'https://example.invalid/synthetic','private':'SYNTHETIC_PRIVATE_SENTINEL'})+",true,true);insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes) values("+lit(sid)+','+lit(rev)+",'content_review','queued',now(),now(),array['policy_lifecycle_uncertain','user_category_unconfirmed']);")
 def native():return rpc('admin_review_detail',['facts',sid])
 d=native()
 for patch in [{'productType':'policy_reference','scope':'nationwide','foreignEligibility':'eligible','evidence':'합성 전국 대상 안내'},{'category':'policy'},{'deadlineKind':'none'}]:
  d=rpc('admin_review_save_facts',[sid,rev,d['version'],{**d['facts'],**patch},ACTOR])
 job=scalar("(select id from machimoa_review.processing_jobs where source_item_id="+lit(sid)+" and revision_hash="+lit(rev)+" and processing_stage='ai_enrichment')")
 d=detail(job);ok(d['canRecheck'],origin+' actual generic facts save queues ready input')
 held=hold(job);dto_details.extend([d,held]);before=snapshot(held)
 sql('select machimoa_review.apply_source_item_evaluation('+lit(sid)+','+lit(rev)+",p.product_type,p.reason_codes,p.gate_facts) from machimoa_review.source_item_product_types p where source_item_id="+lit(sid)+';')
 ok(detail(job)['recheckPending'] and detail(job)['status']=='cancelled',origin+' actual generic reevaluation preserves hold')
 final=complete(job)
 ok(final['status']=='queued' and not final['recheckPending'],origin+' generic completion uses existing gate evaluation')
 ok(snapshot(final)==before,origin+' generic facts and source unchanged')
 dto_details.append(final)

dto_queues.append(rpc('admin_review_ai_queue',[0,25,[]]))
result=subprocess.run([args.node,str(ROOT/'scripts/test_ai_queue_recheck_sql_dto.mjs')],input=json.dumps({'details':dto_details,'queues':dto_queues}).encode(),capture_output=True)
assert result.returncode==0,result.stderr.decode()
dto=json.loads(result.stdout);ok(dto['result']=='passed','actual SQL DTOs pass production API/UI parsers')
ok(scalar('(select count(*) from public.curations)')==0,'no synthetic test published any content')

print(json.dumps({'checks':len(checks),'dtoChecks':dto['checks'],'database':DB,'result':'passed','providerCalls':0,'sharedDBAccess':False,'cases':checks},ensure_ascii=False))
