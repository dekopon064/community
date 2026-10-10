"""Actual SQL contracts, using only a verified network-none synthetic database."""
import argparse,copy,json,subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
from uuid import uuid4
from test_myseoul_db import fixtures

args=argparse.ArgumentParser();args.add_argument('--database',required=True);db=args.parse_args().database
assert db.startswith('myseoul_confirmation_') and db.replace('_','').isalnum()
container='machimoa-saved-count-sql-20261009-56ca9041'
def docker(parts,body=None):
 r=subprocess.run(['docker',*parts],input=body.encode() if body else None,capture_output=True)
 if r.returncode:raise RuntimeError(r.stderr.decode())
 return r.stdout.decode().strip()
m=json.loads(docker(['inspect',container]))[0]
assert m['State']['Running'] and m['HostConfig']['NetworkMode']=='none' and not m['HostConfig']['PortBindings']
assert m['Config']['Labels']['machimoa.purpose']=='saved-count-sql-validation'
assert all(x['Type']=='volume' and x['Name']==container+'-data' for x in m['Mounts'])
assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
def sql(q):return docker(['exec','-i',container,'psql','-XqAt','-U','postgres','-d',db,'-v','ON_ERROR_STOP=1'],q)
def lit(v):
 if v is None:return 'NULL'
 if isinstance(v,int):return str(v)
 return "'"+(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False)).replace("'","''")+"'"
def scalar(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
def query(n,a):return 'begin;set local role service_role;select public.'+n+'('+','.join(map(lit,a))+');commit;'
def rpc(n,a):return json.loads(sql(query(n,a)))
checks=0
def ok(v):
 global checks
 assert v
 checks+=1
def deny(q,expected):
 global checks
 try:sql(q)
 except RuntimeError as e:assert expected in str(e),str(e);checks+=1
 else:raise AssertionError(expected)
root=Path(__file__).resolve().parents[1]
up=(root/'supabase/migrations/20261010132530_myseoul_review_confirmations.sql').read_text(encoding='utf8')
down=(root/'supabase/rollback/20261010132530_myseoul_review_confirmations_down.sql').read_text(encoding='utf8')
deny("begin;alter function machimoa_review.myseoul_evaluate(jsonb,timestamptz) set search_path='public';"+down,'successor_changed')
deny('begin;alter table machimoa_review.myseoul_review_confirmations disable row level security;'+down,'table_changed')
deny("begin;update machimoa_review.myseoul_confirmation_install set backup='{}';"+down,'backup_changed')
deny('begin;alter table machimoa_review.myseoul_review_confirmations disable trigger myseoul_confirmation_dirty;'+down,'trigger_changed')
sql(down);ok(scalar("to_regclass('machimoa_review.myseoul_review_confirmations') is null"))
deny("begin;alter function machimoa_review.myseoul_evaluate(jsonb,timestamptz) set search_path='public';"+up,'predecessor_changed')
sql(up)
for role in ('anon','authenticated','service_role'):
 ok(not scalar("has_table_privilege('"+role+"','machimoa_review.myseoul_review_confirmations','SELECT,INSERT,UPDATE,DELETE')"))
for role in ('anon','authenticated'):
 for n in ('admin_myseoul_activity_confirm(uuid,text,text,bigint,jsonb,jsonb,uuid)','admin_myseoul_body_confirm(uuid,text,text,text,uuid)'):
  ok(not scalar("has_function_privilege('"+role+"','public."+n+"','execute')"))
actor='00000000-0000-4000-8000-000000000001'
sql("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='myseoul_program';")
run=scalar("(select active_run_id from machimoa_review.source_sync_state where source_id='myseoul_program' and lease_expires_at>clock_timestamp())")
if not run:run=scalar("(select run_id from public.start_ingest_run('myseoul_program',3600))")
base=next(x['item'] for x in fixtures()['fixtures'] if x['name']=='personal')
known=lambda v:{'status':'known','value':v}
na={'status':'not_applicable','value':None}
location=known({'scope':'specific','venues':[{'province':'11','district':'종로구','facility':'','address':''}]})
filters={'schema':'content-filters-v1','category':'program','topic':known('employment_career'),'location':location,'delivery':known('onsite'),'audience':known('other'),'spaceKind':na,'application':known({'deadlineKind':'fixed','start':{'value':'2020-01-01','precision':'day'},'end':{'value':'2099-10-15','precision':'day'},'sourceStatus':'unknown'}),'schedule':na}
def observe(poster=False,extra=None):
 p=copy.deepcopy(base);old=p['external_key'].split(':')[-1]
 p=json.loads(json.dumps(p).replace(old,uuid4().hex.upper()));p['revision_hash']=uuid4().hex*2
 f=p['myseoul_facts'];f.update(source_revision=p['revision_hash'],public_category='program',delivery_mode='offline',activity_region='capital',venue='',activity_evidence=[],residence_scope='unknown',residence='',residence_evidence=[],issues=[])
 for key in ('application','operation'):
  for period in f['periods'][key]:
   period.update(status='ok',endpoints=[{'value':'2020-01-01','precision':'day'},{'value':'2099-10-15','precision':'day'}])
 if poster:
  f.update(description='',issues=[{'code':'description_missing','field':'description','evidence':[]}])
  p['body_usable']=False;p['attachment_present']=True
  p['normalized_payload'].update(description='',plain_text='',source_image_url='https://global.seoul.go.kr/contents/commoneditor/synthetic-poster.png',body_has_images=True)
 if extra:f.update(extra)
 for key in list(p):
  if key.startswith('filter'):p.pop(key)
 sid=rpc('observe_myseoul_program',[run,[p],None])[0]['id']
 sql('insert into machimoa_review.source_item_content_filters(source_item_id,revision_hash,data,observed_data,origins,evidence,source_binding) values('+','.join(map(lit,[sid,p['revision_hash'],filters,filters,{},{}]))+',machimoa_review.content_filter_binding('+lit(sid)+','+lit(p['revision_hash'])+'));')
 return sid
detail=lambda sid:rpc('admin_myseoul_program_detail',[sid])
def activity_args(d,patch=None,selected=None):return [d['id'],d['revision'],d['version'],d['filterInfo']['filterVersion'],selected or {'location':location},patch or {},actor]
sid=observe();d=detail(sid);observed=copy.deepcopy(d['observedFacts']);fv=d['factsVersion'];v=d['version']
ok(d['facts']['venue']=='' and d['facts']['activity_evidence']==[] and d['filterInfo']['missing']==[] and d['result']['reasons']==['activity_region_unknown'])
# Reproduce the former deployed failure, before using the new explicit command.
deny(query('admin_myseoul_program_save_v2',[sid,d['revision'],v,{'delivery_mode':'offline','activity_region':'capital','venue':''},actor]),'myseoul_no_resolved_fact')
ok(detail(sid)['factsVersion']==fv and not detail(sid)['activityReview']['confirmed'])
bad=copy.deepcopy(location);bad['value']['venues'][0].update(province='26',district=None)
deny(query('admin_myseoul_activity_confirm',activity_args(d,selected={'location':bad})),'invalid_content_filters')
deny(query('admin_myseoul_activity_confirm',activity_args(d)[:-1]+[None]),'invalid_myseoul_command')
bad_args=activity_args(d);bad_args[3]+=1
deny(query('admin_myseoul_activity_confirm',bad_args),'content_filter_input_changed')
# A valid scoped fact edit followed by invalid filters rolls back every write.
atomic=observe(extra={'description':'','issues':[{'code':'description_missing','field':'description','evidence':[]}]});ad=detail(atomic)
events_before=scalar('(select count(*) from machimoa_review.admin_review_events where source_item_id='+lit(atomic)+')')
deny(query('admin_myseoul_activity_confirm',activity_args(ad,patch={'description':'합성 원문에서 보완한 설명입니다. 다른 사실을 수정한 후 필터 검증이 실패하는 상황입니다.'},selected={'location':bad})),'invalid_content_filters')
ok(detail(atomic)==ad)
ok(scalar('(select count(*) from machimoa_review.admin_review_events where source_item_id='+lit(atomic)+')')==events_before)
ok(scalar('(select count(*) from machimoa_review.myseoul_review_confirmations where source_item_id='+lit(atomic)+')')==0)
saved=rpc('admin_myseoul_activity_confirm',activity_args(d))
ok(saved['status']=='resolved' and saved['activityReview']['confirmed'] and 'activity_region_unknown' not in saved['result']['reasons'])
ok(saved['facts']['venue']=='' and saved['facts']['activity_evidence']==[] and saved['observedFacts']==observed)
ok(saved['filterInfo']['data']['location']==location and saved['factsVersion']==fv+1)
deny(query('admin_myseoul_activity_confirm',activity_args(d)),'version_conflict')
ok(scalar('(select count(*) from machimoa_review.myseoul_review_confirmations where source_item_id='+lit(sid)+')')==1)
# Real native claim produces an exact current snapshot. No provider is invoked.
ctx=rpc('claim_myseoul_program_ai',[sid,saved['revision'],'synthetic-confirmation',300])[0]
from ingest.myseoul_ai import validate_context,myseoul_input
ok(validate_context(ctx,sid,saved['revision'],'synthetic-confirmation',read_detail=detail)['facts']['venue']=='')
ok(json.loads(myseoul_input(ctx))['currentFacts']['activity_region']=='capital')
deny(query('admin_myseoul_activity_confirm',activity_args(detail(sid))),'processing_active')

poster=observe(poster=True);d=detail(poster)
ok('attachment_dependent' in d['result']['reasons'] and d['bodyReview']['required'] and not d['bodyReview']['confirmed'])
description='합성 이미지 원문을 사람이 확인한 설명입니다. 부모와 자녀가 함께 참여하는 가족관계 개선 활동입니다.'
deny(query('admin_myseoul_body_confirm',[poster,d['revision'],d['version'],'짧음',actor]),'invalid_myseoul_body_confirmation')
raw_before=scalar('(select normalized_payload from machimoa_review.source_items where id='+lit(poster)+')')
body=rpc('admin_myseoul_body_confirm',[poster,d['revision'],d['version'],description,actor])
ok(body['bodyReview']['confirmed'] and 'attachment_dependent' not in body['result']['reasons'] and 'description_missing' not in body['result']['reasons'])
ok(body['facts']['description']==description and body['observedFacts']['description']=='' and 'activity_region_unknown' in body['result']['reasons'])
ok(scalar('(select normalized_payload from machimoa_review.source_items where id='+lit(poster)+')')==raw_before)
ok(not scalar('(select body_usable from machimoa_review.source_items where id='+lit(poster)+')'))
deny(query('admin_myseoul_body_confirm',[poster,d['revision'],d['version'],description,actor]),'version_conflict')
body=rpc('admin_myseoul_activity_confirm',activity_args(body,selected={'location':location,'topic':filters['topic']}))
ctx2=rpc('claim_myseoul_program_ai',[poster,body['revision'],'synthetic-poster',300])[0]
ok(validate_context(ctx2,poster,body['revision'],'synthetic-poster',read_detail=detail)['facts']['description']==description)
ok(json.loads(myseoul_input(ctx2))['currentFacts']['description']==description)

# An already reclassified poster keeps its category/filters; snapshot and version advance.
classified=observe(poster=True,extra={'public_category':'unknown','issues':[{'code':'description_missing','field':'description','evidence':[]},{'code':'category_unresolved','field':'public_category','evidence':[]}]});d=rpc('admin_review_classification_detail',[classified]);cf=copy.deepcopy(d['drafts']['program']);cf['filters']=copy.deepcopy(filters);cf['facts'].update(delivery='offline',deadlineKind='fixed',deadlineOn='2099-10-15',scope='unknown',regions=[],evidence='')
cl=rpc('admin_review_reclassify',[classified,d['revision'],d['version'],d['classificationVersion'],cf['facts'],cf['filters'],'합성 원문 분류 및 필터 확인',actor])
ok(not cl['ready'] and 'attachment_dependent' in cl['sourceReasons'])
native=detail(classified)
ok('description' in native['editableFields'])
confirmed=rpc('admin_myseoul_body_confirm',[classified,native['revision'],native['version'],description,actor])
cl2=rpc('admin_review_classification_detail',[classified])
ok(cl2['ready'] and cl2['category']=='program' and cl2['filters']==cl['filters'] and cl2['classificationVersion']==cl['classificationVersion']+1)
ok('classification_input_changed' not in cl2['reasons'] and confirmed['bodyReview']['confirmed'])
ctx3=rpc('claim_reclassified_content_ai',[classified,cl2['revision'],cl2['classificationVersion'],'synthetic-classified-poster',300])
from ingest.reclassification_ai import classification_input,validate_context as validate_classified
ok(validate_classified(ctx3,classified,cl2['revision'],cl2['classificationVersion'],'synthetic-classified-poster')['nativeConfirmedFacts']['programFacts']['description']==description)
ok(json.loads(classification_input(ctx3))['operatorSupplementedText']==description)

# No fake evidence, automatic claim or user data changes at save time.
other=observe(extra={'application_actor':'institution_only'});ok(detail(other)['status']=='excluded')
deny(query('admin_myseoul_activity_confirm',activity_args(detail(other))),'already_processed')
race_id=observe();race_d=detail(race_id);barrier=Barrier(2)
def race(_):
 barrier.wait()
 try:return rpc('admin_myseoul_activity_confirm',activity_args(race_d))['status']
 except RuntimeError as e:assert 'version_conflict' in str(e);return 'conflict'
with ThreadPoolExecutor(max_workers=2) as pool:r=list(pool.map(race,range(2)))
ok(r.count('conflict')==1 and r.count('resolved')==1)
ok(scalar('(select count(*) from machimoa_review.processing_jobs where source_item_id='+lit(race_id)+" and status='claimed')")==0)
old=detail(race_id);sql("update machimoa_review.source_item_content_filters set data=jsonb_set(data,'{location,value,venues,0,province}','\"41\"') where source_item_id="+lit(race_id)+';')
ok(not detail(race_id)['activityReview']['confirmed'] and 'activity_region_unknown' in detail(race_id)['result']['reasons'])
revision=uuid4().hex*2
ok(not scalar('machimoa_review.myseoul_body_confirmed(jsonb_set('+lit(confirmed['facts'])+"::jsonb,'{source_revision}',to_jsonb("+lit(revision)+'::text)))'))
ok(not scalar('machimoa_review.myseoul_body_confirmed(jsonb_set('+lit(confirmed['facts'])+"::jsonb,'{description}',to_jsonb('다른 설명'::text)))"))
deny(down,'records_present')
ok(scalar("to_regprocedure('public.admin_myseoul_body_confirm(uuid,text,text,text,uuid)') is not null"))
print(json.dumps({'checks':checks,'database':db,'actualProviderCalls':0,'productionAccess':False,'result':'passed'}))
