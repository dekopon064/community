"""Explicit synthetic-only DB; never reads environment files or remote databases."""
import argparse,copy,json,subprocess
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from test_myseoul_db import fixtures

args=argparse.ArgumentParser();args.add_argument('--database',required=True);args.add_argument('--only',choices=['core','delta','install'],default='core');a=args.parse_args()
assert a.database.startswith('review_residence_') and a.database.replace('_','').isalnum()
container='machimoa-program-ai-5689d361'
def docker(parts,body=None):
 r=subprocess.run(['docker',*parts],input=body.encode() if body else None,capture_output=True)
 if r.returncode:raise RuntimeError(r.stderr.decode())
 return r.stdout.decode().strip()
meta=json.loads(docker(['inspect',container]))[0]
assert meta['State']['Running'] and meta['HostConfig']['NetworkMode']=='none' and not meta['HostConfig']['PortBindings'] and not meta['Mounts'] and meta['Config']['Labels']['machimoa.purpose']=='isolated-program-ai-concurrency'
assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
def sql(q):return docker(['exec','-i',container,'psql','-X','-U','postgres','-d',a.database,'-v','ON_ERROR_STOP=1','-v','VERBOSITY=verbose','-qAt'],q)
def lit(x):return 'NULL' if x is None else str(x).lower() if isinstance(x,bool) else str(x) if isinstance(x,int) else "'"+(x if isinstance(x,str) else json.dumps(x,ensure_ascii=False)).replace("'","''")+"'"
def value(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
def rpc(name,x):return json.loads(sql('begin;set local role service_role;select public.'+name+'('+','.join(map(lit,x))+');commit;'))
count=0
def ok(x):
 global count
 assert x;count+=1
def deny(q,code):
 global count
 try:sql(q)
 except RuntimeError as e:assert code in str(e),str(e);count+=1
 else:raise AssertionError('expected '+code)
root=Path(__file__).resolve().parents[1]
up=(root/'supabase/migrations/20261010065809_myseoul_residence_review.sql').read_text(encoding='utf8')
down=(root/'supabase/rollback/20261010065809_myseoul_residence_review_down.sql').read_text(encoding='utf8')
if a.only in ('core','install'):
 if not value('exists(select 1 from machimoa_review.myseoul_residence_reviews)'):
  deny("begin;alter function public.admin_myseoul_residence_confirm(uuid,text,text,boolean,text,text,jsonb,uuid,uuid) set search_path='public';"+down,'residence_successor_changed')
  ok(value("(select proconfig=array['search_path=\"\"']::text[] from pg_proc where oid='public.admin_myseoul_residence_confirm(uuid,text,text,boolean,text,text,jsonb,uuid,uuid)'::regprocedure)"))
  sql(down);ok(value("to_regclass('machimoa_review.myseoul_residence_reviews') is null"));sql(up)
 for role in ['anon','authenticated','service_role']:
  ok(not value("has_table_privilege('"+role+"','machimoa_review.myseoul_residence_reviews','select')"))
  ok(value("has_function_privilege('"+role+"','public.admin_myseoul_residence_confirm(uuid,text,text,boolean,text,text,jsonb,uuid,uuid)','execute')")== (role=='service_role'))
 ok(value("(select relrowsecurity from pg_class where oid='machimoa_review.myseoul_residence_reviews'::regclass)"))
actor='00000000-0000-4000-8000-000000000001'
sql("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='myseoul_program';")
run=value("(select active_run_id from machimoa_review.source_sync_state where source_id='myseoul_program' and lease_expires_at>clock_timestamp())")
if not run:run=value("(select run_id from public.start_ingest_run('myseoul_program',3600))")
base=next(x['item'] for x in fixtures()['fixtures'] if x['name']=='online')
def observe(extra=None):
 p=copy.deepcopy(base);old=p['external_key'].split(':')[-1];new=uuid4().hex.upper();p=json.loads(json.dumps(p).replace(old,new));p['revision_hash']=uuid4().hex*2
 f=p['myseoul_facts'];f['source_revision']=p['revision_hash'];f.update(delivery_mode='online',residence_scope='unknown',residence='',residence_evidence=[])
 f['issues']=[v for v in f['issues'] if v['code']!='online_residence_unknown']+[{'code':'online_residence_unknown','field':'residence','evidence':[]}]
 if extra:
  f.update(extra)
  # These synthetic variants intentionally have no asserted filter facts;
  # do not keep the base online excerpt as evidence for a mixed mode.
  if extra.get('delivery_mode') or 'target' in extra:
   for k in list(p):
    if k.startswith('filter'):p.pop(k)
 return rpc('observe_myseoul_program',[run,[p],None])[0]['id']
detail=lambda sid:rpc('admin_myseoul_program_detail',[sid])
def command(d,restricted=False,scope='',condition='',evidence=None,request=None):return [d['id'],d['revision'],d['version'],restricted,scope,condition,evidence or [],actor,request or str(uuid4())]
confirm=lambda x:rpc('admin_myseoul_residence_confirm',x)
def reject(x,code='PT409'):deny('begin;set local role service_role;select public.admin_myseoul_residence_confirm('+','.join(map(lit,x))+');commit;',code)
if a.only=='core':
 sid=observe();d=detail(sid);facts=copy.deepcopy(d['facts']);ok('online_residence_unknown' in d['result']['reasons']);ok(not d['residenceReview']['confirmed'])
 args=command(d);n=confirm(args);ok(n['residenceReview']=={'confirmed':True,'basis':'operator_no_restriction'});ok('online_residence_unknown' not in n['result']['reasons']);ok(n['facts']['residence_scope']=='unknown' and n['facts']['residence_evidence']==[]);ok(n['observedFacts']==d['observedFacts']);ok(n['factsVersion']==d['factsVersion']+1);ok(n['filterInfo']==d['filterInfo']);ok(value("(select count(*) from machimoa_review.myseoul_residence_reviews where source_item_id="+lit(sid)+")")==1)
 ok(confirm(args)['version']==n['version']);ok(value("(select count(*) from machimoa_review.myseoul_residence_reviews where source_item_id="+lit(sid)+")")==1)
 bad=copy.deepcopy(args);bad[5]='different';reject(bad,'PT422');bad=copy.deepcopy(args);bad[7]=str(uuid4());reject(bad,'PT422');reject(command(d))
 ok(detail(sid)['version']==n['version'])
 # Related changes invalidate permanently, even after values are changed back.
 sql('update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,\'{target}\',\'"changed synthetic target"\'),facts_version=facts_version+1 where source_item_id='+lit(sid)+';')
 ok('online_residence_unknown' in detail(sid)['result']['reasons']);reject(args)
 sql('update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,\'{target}\','+lit(json.dumps(facts['target']))+'::jsonb),facts_version=facts_version+1 where source_item_id='+lit(sid)+';')
 ok('online_residence_unknown' in detail(sid)['result']['reasons'])
 sid2=observe();d2=detail(sid2);n2=confirm(command(d2,True,'capital','성남시 주민 전용',['합성 원문: 성남시 주민 전용']));ok(n2['facts']['residence']=='성남시 주민 전용');ok(n2['facts']['residence_scope']=='capital');ok(n2['residenceReview']['basis']=='source_evidence');ok('online_residence_unknown' not in n2['result']['reasons'])
 sid3=observe();d3=detail(sid3);reject(command(d3,True,'capital','성남시 주민 전용',[]),'PT422');ok(detail(sid3)['version']==d3['version']);reject(command(d3,True,'noncapital_only','비수도권만',[]),'PT422');ok(not value('exists(select 1 from machimoa_review.myseoul_residence_reviews where source_item_id='+lit(sid3)+')'))
 for changes in [{'delivery_mode':'mixed'},{'application_actor':'institution_only'},{'residence_scope':'noncapital_only'},{'residence_scope':'capital'}]:
  sid4=observe(changes);d4=detail(sid4)
  reject(command(d4),'PT409' if changes.get('residence_scope')!='capital' else 'PT422')
  if changes.get('application_actor')=='institution_only':ok(d4['result']['decision']=='out_of_scope')
  if changes.get('residence_scope')=='noncapital_only':ok('online_noncapital_only' in d4['result']['reasons'])
 # Concurrent same-version confirmations: only one writes; stale other request fails.
 sid5=observe();d5=detail(sid5);barrier=Barrier(2)
 def simultaneous(_):
  barrier.wait()
  try:confirm(command(d5));return True
  except RuntimeError as e:assert 'PT409' in str(e);return False
 with ThreadPoolExecutor(2) as pool:ok(sorted(pool.map(simultaneous,[1,2]))==[False,True])
 ok(value('(select count(*) from machimoa_review.myseoul_residence_reviews where source_item_id='+lit(sid5)+')')==1)
 # Common exclusion/72-hour restoration, using the exact My source DTO/version.
 sid6=observe();d6=detail(sid6);rid=str(uuid4());x=[sid6,d6['revision'],d6['version'],'region_not_suitable','',actor,rid]
 excluded=rpc('admin_review_exclude_reason',x);ok(excluded['item']['status']=='excluded');ok(rpc('admin_review_exclude_reason',x)['episodeId']==excluded['episodeId']);ok(value('(select count(*) from machimoa_review.admin_exclusion_episodes where source_item_id='+lit(sid6)+')')==1)
 episodes=rpc('admin_review_trash',[0,25])['items'];ep=next(e for e in episodes if e['sourceItemId']==sid6);ok(ep['reasonCode']=='region_not_suitable' and ep['note']=='대상 지역이 아님');ok(ep['canRestore']);ok(value('(select expires_at-excluded_at=interval \'72 hours\' from machimoa_review.admin_exclusion_episodes where id='+lit(ep['id'])+')'))
 restored=rpc('admin_review_restore',[ep['id'],ep['revision'],ep['version'],actor,str(uuid4())]);ok(restored['item']['restoredReviewPending']);ok(restored['item']['status']=='open');ok(restored['item']['observedFacts']==d6['observedFacts']);ok(restored['item']['facts']['official_url']==d6['facts']['official_url'])
 ok(value('(select count(*) from machimoa_review.source_items where id='+lit(sid6)+')')==1)
 deny(down,'residence_review_records_present');ok(value("to_regprocedure('public.admin_myseoul_residence_confirm(uuid,text,text,boolean,text,text,jsonb,uuid,uuid)') is not null"))
if a.only=='delta':
 # Narrow follow-up checks after the single independent review. No provider runs.
 sid=observe({'residence_scope':'nationwide','residence_evidence':['합성 원문: 지역 제한 없음'],'issues':[]})
 d=detail(sid);ok(d['residenceReview']=={'confirmed':True,'basis':'source_evidence'})
 ok(not value('exists(select 1 from machimoa_review.myseoul_residence_reviews where source_item_id='+lit(sid)+')'))
 sid=observe({'target':''});d=detail(sid);n=confirm(command(d))
 ok('target_missing' in n['result']['reasons'] and 'online_residence_unknown' not in n['result']['reasons'])
 ok(n['result']['decision']=='review_required')
 # Exact source revision changes never reuse a human judgment.
 sid=observe();d=detail(sid);n=confirm(command(d));old=n['revision']
 sql('update machimoa_review.source_items set revision_hash='+lit('f'*64)+' where id='+lit(sid)+';')
 ok(not value('machimoa_review.myseoul_residence_confirmed('+lit(n['facts'])+'::jsonb)'));reject(command(n))
 sql('update machimoa_review.source_items set revision_hash='+lit(old)+' where id='+lit(sid)+';')
 ok(not value('machimoa_review.myseoul_residence_confirmed('+lit(n['facts'])+'::jsonb)'))
 ok('online_residence_unknown' in detail(sid)['result']['reasons']);reject(command(n))
 # Concurrent confirmation and common exclusion serialize the same item/version.
 sid=observe();d=detail(sid);barrier=Barrier(2)
 def race(kind):
  barrier.wait()
  try:
   if kind=='confirm':confirm(command(d))
   else:rpc('admin_review_exclude_reason',[sid,d['revision'],d['version'],'service_not_suitable','',actor,str(uuid4())])
   return 'saved'
  except RuntimeError as e:assert 'PT409' in str(e),str(e);return 'conflict'
 with ThreadPoolExecutor(2) as pool:ok(sorted(pool.map(race,['confirm','exclude']))==['conflict','saved'])
 ok(value('(select count(*) from machimoa_review.myseoul_residence_reviews where source_item_id='+lit(sid)+')')+value('(select count(*) from machimoa_review.admin_exclusion_episodes where source_item_id='+lit(sid)+')')==1)
 # Active synthetic processing is not displaced by review or exclusion.
 sid=observe();d=detail(sid)
 sql("update machimoa_review.processing_jobs set status='claimed',claim_lease_until=clock_timestamp()+interval '5 minutes',claimed_at=clock_timestamp(),claimed_by='synthetic-test' where source_item_id="+lit(sid)+" and processing_stage='content_review';")
 reject(command(detail(sid)))
 deny('begin;set local role service_role;select public.admin_review_exclude_reason('+','.join(map(lit,[sid,d['revision'],detail(sid)['version'],'region_not_suitable','',actor,str(uuid4())]))+');commit;','PT409')
 ok(not value('exists(select 1 from machimoa_review.myseoul_residence_reviews where source_item_id='+lit(sid)+')'))
 # Native preparation accepts the exact confirmed version after existing filters
 # are ready. It does not enqueue, claim, call a provider, or make a candidate.
 sid=observe();d=detail(sid);n=confirm(command(d));fd=rpc('admin_content_filter_detail',[sid])
 patch={'application':{'status':'known','value':{'deadlineKind':'fixed','start':{'value':'2020-01-01T10:00:00+09:00','precision':'minute'},'end':{'value':'2099-10-15T18:00:00+09:00','precision':'minute'},'sourceStatus':'unknown'}}}
 if 'application' in fd['missing']:
  rpc('admin_content_filter_save',[sid,fd['revision'],fd['version'],fd['filterVersion'],patch,actor])
 # Existing fact-to-filter synchronization may already supply the known period.
 ok(value('machimoa_review.content_filter_ready('+lit(sid)+','+lit(n['revision'])+')'))
 n=detail(sid)
 before=value('(select count(*) from machimoa_review.processing_jobs where source_item_id='+lit(sid)+')')
 sql('select machimoa_review.myseoul_ai_preparation_check('+','.join(map(lit,[sid,n['revision'],n['factsVersion']]))+');');ok(True)
 deny('select machimoa_review.myseoul_ai_preparation_check('+','.join(map(lit,[sid,n['revision'],n['factsVersion']-1]))+');','PT409')
 ok(value('(select count(*) from machimoa_review.processing_jobs where source_item_id='+lit(sid)+')')==before)
 # Common reclassification uses its own complete facts; absent native residence
 # reasons alone must not create a green confirmation or a fabricated audit.
 sid=observe();native=detail(sid);cl=rpc('admin_review_classification_detail',[sid])
 facts={'productType':'living_guide','category':'living','scope':'nationwide','regions':[],'evidence':'합성 원문: 전국 대상 생활 안내','foreignEligibility':'unknown','delivery':'online','deadlineKind':'','deadlineOn':'','eventStart':'','eventEnd':''}
 out=rpc('admin_review_reclassify',[sid,cl['revision'],cl['version'],cl['classificationVersion'],facts,None,'합성 재분류 근거 확인',actor])
 ok(out['ready']);after=detail(sid)
 ok(not after['residenceReview']['confirmed']);ok(after['residenceReview']['basis']=='unconfirmed')
 ok(after['observedFacts']==native['observedFacts'])
 ok(not value('exists(select 1 from machimoa_review.myseoul_residence_reviews where source_item_id='+lit(sid)+')'))
 # A later native change invalidates the common snapshot, not silently updates it.
 sql("update machimoa_review.source_item_program_facts set facts=jsonb_set(facts,'{target}','\"synthetic changed target\"'),facts_version=facts_version+1 where source_item_id="+lit(sid)+';')
 current=rpc('admin_review_classification_detail',[sid]);ok(not current['ready'])
 ok('classification_input_changed' in detail(sid)['result']['reasons'])
 # Guard failures are transactional and retain all installed definitions.
 deny("begin;alter function machimoa_review.myseoul_evaluate(jsonb,timestamptz) set search_path='public';"+up,'residence_predecessor_changed')
 ok(value("(select proconfig=array['search_path=\"\"']::text[] from pg_proc where oid='machimoa_review.myseoul_evaluate(jsonb,timestamptz)'::regprocedure)"))
print(json.dumps({'checks':count,'database':a.database,'only':a.only,'providerCalls':0,'productionAccess':False}))
