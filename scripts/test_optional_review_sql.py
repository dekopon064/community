"""Optional review inputs: real transactions in a fresh network-none synthetic DB."""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from test_program_db import fixtures
from test_myseoul_db import fixtures as myfixtures
from test_seoul_content import synthetic_facts
from test_program_ai import bind_program_filters

ROOT=Path(__file__).resolve().parents[1]
C='machimoa-saved-count-sql-20261009-56ca9041'
ACTOR='00000000-0000-4000-8000-000000000001'
checks=[]
def docker(a,b=None):
 r=subprocess.run(['docker',*a],input=b.encode() if b else None,capture_output=True)
 if r.returncode:raise RuntimeError(r.stderr.decode())
 return r.stdout.decode().strip()
def lit(v):
 if v is None:return 'NULL'
 if isinstance(v,bool):return str(v).lower()
 if isinstance(v,int):return str(v)
 return "'"+(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False)).replace("'","''")+"'"
def ok(v,label):assert v,label;checks.append(label)
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--before-fix',action='store_true');args=parser.parse_args()
 m=json.loads(docker(['inspect',C]))[0]
 assert m['State']['Running'] and m['HostConfig']['NetworkMode']=='none' and not m['HostConfig']['PortBindings']
 assert m['Config']['Labels']['machimoa.purpose']=='saved-count-sql-validation'
 assert m['Mounts'] and all(x['Type']=='volume' and x['Name']==C+'-data' for x in m['Mounts'])
 assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
 db='optional_review_local_'+uuid4().hex[:12]
 dump=docker(['exec',C,'pg_dump','-U','postgres','-d','seoul_delivery_local_fc41d941d670','--schema-only','--schema=public','--schema=machimoa_review'])
 assert dump.count('CREATE SCHEMA public;')==1
 docker(['exec',C,'createdb','-U','postgres',db])
 def sql(q):return docker(['exec','-i',C,'psql','-XqAt','-U','postgres','-d',db,'-v','ON_ERROR_STOP=1'],"set statement_timeout='15s';set lock_timeout='5s';"+q)
 sql(dump.replace('CREATE SCHEMA public;','-- Empty public exists',1))
 def scalar(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
 def query(n,a):
  x=list(map(lit,a))
  if n=='admin_program_save':x[4]='array['+','.join(map(lit,a[4]))+']::text[]'
  return 'begin;set local role service_role;select public.'+n+'('+','.join(x)+');commit;'
 def rpc(n,a):return json.loads(sql(query(n,a)))
 def deny(q,error):
  try:sql(q)
  except RuntimeError as e:ok(error in str(e),'denied '+error)
  else:raise AssertionError(error)
 for t in ('source_items','curation_candidates','processing_jobs'):ok(scalar('(select count(*) from machimoa_review.'+t+')')==0,'empty '+t)
 sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation'),('myseoul_program','synthetic','content','rest',true,'approved_noncommercial','myseoul_program');insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation'),('myseoul_program');")
 runs={s:scalar('(select run_id from public.start_ingest_run('+lit(s)+',3600))') for s in ('seoul_reservation','myseoul_program')}
 def create(key,**updates):
  v=copy.deepcopy(fixtures(storage=True)[0]['item']);v['external_key']=key;v['revision_hash']=hashlib.sha256(key.encode()).hexdigest()
  f=synthetic_facts();f.update(missing=[],conflicts=[],residence_scope='unknown',residence_evidence=[],activity_evidence=[])
  f['periods']['RCPTBGNDT']['value']='2020-01-01';f.update(updates)
  v['program_facts']=f;v['normalized_payload']['provider_fields']['SVCID']=key
  v['normalized_payload']['source_url']=f['official_url']='https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id='+key
  i=rpc('observe_seoul_program_new_only',[runs['seoul_reservation'],[v],None])[0]['id']
  return i,rpc('admin_program_detail',[i])
 def snap(i):return scalar("(select jsonb_build_array(to_jsonb(s),(select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_program_facts f where f.source_item_id=s.id),(select jsonb_agg(to_jsonb(e)) from machimoa_review.admin_review_events e where e.source_item_id=s.id),(select jsonb_agg(to_jsonb(f)) from machimoa_review.source_item_content_filters f where f.source_item_id=s.id)) from machimoa_review.source_items s where s.id="+lit(i)+")")
 # Existing synthetic record demonstrates no DDL backfill.
 i,d=create('legacy_optional_case',content_kind='unknown');before=snap(i)
 migration=(ROOT/'supabase/migrations/20261012085122_optional_review_evidence.sql').read_text(encoding='utf8')
 if not args.before_fix:
  deny("begin;alter function public.admin_program_save(uuid,text,text,jsonb,text[],text,uuid) set search_path='public';"+migration,'optional_review_predecessor_changed')
  ok(snap(i)==before,'precondition failure preserves rows')
  sql(migration);ok(snap(i)==before,'DDL does not backfill observations, facts or history')
 a=[i,d['revision'],d['version'],{'content_kind':'program'},[], '',ACTOR]
 after=rpc('admin_program_save',a)
 ok(after['facts']['content_kind']=='program','save without note')
 ok(after['facts']['residence_scope']=='unknown' and after['facts']['residence_evidence']==[],'no invented residence fact or quote')
 ok(after['observedFacts']==d['observedFacts'],'observed facts preserved')
 ok(after['factsVersion']==d['factsVersion']+1,'one facts version advance')
 ok(after['history'][0]['actor']==ACTOR and after['history'][0]['note']=='','automatic actor and empty optional note recorded')
 deny(query('admin_program_save',a),'program_version_conflict')
 raw=after['facts'];r=scalar('machimoa_review.program_evaluate('+lit(raw)+'::jsonb,statement_timestamp())')
 ok('residence_scope_unknown' not in r['reasons'] and 'activity_location_unknown' not in r['reasons'],'offline known venue needs no duplicate quotes')
 for mode in ('offline','hybrid'):
  f={**raw,'delivery_mode':mode};rr=scalar('machimoa_review.program_evaluate('+lit(f)+'::jsonb,statement_timestamp())');ok('residence_scope_unknown' not in rr['reasons'],mode+' residence unknown is not a blocking fact')
 for scope in ('unknown','not_stated'):
  f={**raw,'delivery_mode':'online','activity_region':'not_applicable','residence_scope':scope};rr=scalar('machimoa_review.program_evaluate('+lit(f)+'::jsonb,statement_timestamp())');ok('residence_scope_unknown' in rr['reasons'],'online '+scope+' still needs actual range')
 f={**raw,'delivery_mode':'online','activity_region':'not_applicable','residence_scope':'capital'}
 ok('residence_scope_unknown' not in scalar('machimoa_review.program_evaluate('+lit(f)+'::jsonb,statement_timestamp())')['reasons'],'online known scope needs no repeated quote')
 for field,value,reason in [('residence_scope','noncapital','residence_outside_capital'),('application_actor','nationality_excluded','nationality_explicitly_excluded'),('activity_region','noncapital','activity_outside_capital')]:
  rr=scalar('machimoa_review.program_evaluate('+lit({**raw,field:value})+'::jsonb,statement_timestamp())');ok(reason in rr['reasons'],'real restriction '+reason)
 # Actual date conflicts cannot be removed by merely typing an optional quote.
 j,jd=create('optional_conflict',conflicts=['body_api_period_conflict'])
 deny(query('admin_program_save',[j,jd['revision'],jd['version'],{'period_evidence':['new note']},['body_api_period_conflict'],'',ACTOR]),'program_reason_not_resolved')
 periods=copy.deepcopy(jd['facts']['periods']);periods['SVCOPNENDDT']['value']='2099-11-03'
 fixed=rpc('admin_program_save',[j,jd['revision'],jd['version'],{'periods':periods},['body_api_period_conflict'],'',ACTOR]);ok('body_api_period_conflict' not in fixed['facts']['conflicts'],'actual corrected periods resolve without quote')
 bad=copy.deepcopy(periods);bad['SVCOPNENDDT']['value']='1900-01-01'
 k,kd=create('bad_period',conflicts=['period_order_conflict'])
 deny(query('admin_program_save',[k,kd['revision'],kd['version'],{'periods':bad},['period_order_conflict'],'',ACTOR]),'invalid_period_order')
 k,kd=create('memo_limit',content_kind='unknown')
 deny(query('admin_program_save',[k,kd['revision'],kd['version'],{'content_kind':'program'},[],'x'*4001,ACTOR]),'invalid_program_command')
 memo=rpc('admin_program_save',[k,kd['revision'],kd['version'],{'content_kind':'program'},[],'  실제 합성 메모  ',ACTOR]);ok(memo['history'][0]['note']=='실제 합성 메모','provided note trimmed and preserved')
 # Two independent sessions cannot overwrite a reviewed version.
 rid,rd=create('concurrent_optional',content_kind='unknown');barrier=Barrier(2)
 def race():
  barrier.wait()
  try:return rpc('admin_program_save',[rid,rd['revision'],rd['version'],{'content_kind':'program'},[],'',ACTOR])
  except RuntimeError as e:return str(e)
 with ThreadPoolExecutor(max_workers=2) as pool: outcomes=list(pool.map(lambda _:race(),range(2)))
 ok(sum(isinstance(x,dict) for x in outcomes)==1,'one concurrent save succeeds')
 ok(sum(isinstance(x,str) and 'program_version_conflict' in x for x in outcomes)==1,'other concurrent save gets version conflict')
 ok(rpc('admin_program_detail',[rid])['factsVersion']==rd['factsVersion']+1,'race has exactly one version advance')
 # Formal classification save, no checkbox field and no generated operator quote.
 cd=rpc('admin_review_classification_detail',[i]);f=copy.deepcopy(cd['facts']);f.update(productType='living_guide',category='living',delivery='offline',deadlineKind='',deadlineOn='',eventStart='',eventEnd='',evidence='')
 c=rpc('admin_review_reclassify',[i,cd['revision'],cd['version'],cd['classificationVersion'],f,None,'',ACTOR])
 ok(c['active'] and c['note']=='','initial classification saves with no memo/check')
 ok(c['classificationVersion']==cd['classificationVersion']+1,'classification version advance')
 c2=rpc('admin_review_reclassify',[i,c['revision'],c['version'],c['classificationVersion'],f,None,'추가 합성 메모',ACTOR]);ok(c2['note']=='추가 합성 메모','same category confirmation and optional memo')
 deny(query('admin_review_reclassify',[i,c['revision'],c['version'],c['classificationVersion'],f,None,'',ACTOR]),'classification_conflict')
 policy={**f,'productType':'policy_reference','category':'policy','scope':'specific','regions':['11'],'foreignEligibility':'eligible','deadlineKind':'fixed','deadlineOn':'2099-10-10'}
 sql('select machimoa_review.classification_validate('+lit(policy)+'::jsonb,NULL);');ok(True,'policy known eligibility/scope accepts empty quote')
 deny('select machimoa_review.classification_validate('+lit({**policy,'scope':'unknown','regions':[]})+'::jsonb,NULL);','classification_missing_evidence')
 deny('select machimoa_review.classification_validate('+lit({**policy,'foreignEligibility':'unknown'})+'::jsonb,NULL);','classification_missing_evidence')
 # A true category change uses the same optional-note transaction.
 change=rpc('admin_review_reclassify',[i,c2['revision'],c2['version'],c2['classificationVersion'],policy,None,'',ACTOR])
 ok(change['category']=='policy' and change['facts']['evidence']=='','actual classification change without quote/check')
 previous_count=scalar('(select count(*) from machimoa_review.review_classification_history where source_item_id='+lit(i)+')')
 ok(previous_count==3,'initial/same/change history retained')
 # MySeoul: actual restriction retained, repeated quote optional.
 m=copy.deepcopy(next(x['item'] for x in myfixtures()['fixtures'] if x['name']=='online'))
 old=m['external_key'].split(':')[-1];m=json.loads(json.dumps(m).replace(old,'0123456789ABCDEF0123456789ABCDEF'))
 m['revision_hash']=hashlib.sha256(b'optional_online').hexdigest();mf=m['myseoul_facts'];mf['source_revision']=m['revision_hash']
 mf.update(public_category='program',issues=[],residence_scope='unknown',residence='',residence_evidence=[])
 for axis in ('application','operation'):
  for period in mf['periods'][axis]:period.update(status='ok',endpoints=[{'value':'2020-01-01','precision':'day'},{'value':'2099-10-15','precision':'day'}])
 mid=rpc('observe_myseoul_program',[runs['myseoul_program'],[m],None])[0]['id'];md=rpc('admin_myseoul_program_detail',[mid])
 ok('online_residence_unknown' in md['result']['reasons'],'MySeoul unknown online scope remains blocked')
 reviewed=rpc('admin_myseoul_residence_confirm',[mid,md['revision'],md['version'],True,'capital','수도권 거주자만 신청 가능합니다.',[],ACTOR,str(uuid4())])
 ok('online_residence_unknown' not in reviewed['result']['reasons'],'MySeoul actual condition saves without duplicate quote')
 ok(reviewed['facts']['residence']=='수도권 거주자만 신청 가능합니다.' and reviewed['facts']['residence_evidence']==[],'condition retained, no fabricated quote')
 ok(reviewed['observedFacts']==md['observedFacts'],'MySeoul observations preserved')
 # AI recheck holds and active claims remain independent of optional notes.
 hid,hd=create('held_optional')
 holder={'facts':hd['facts'],'workerId':'synthetic'};bind_program_filters(holder);fd=holder['filterContext']['data']
 rpc('admin_content_filter_save',[hid,hd['revision'],hd['version'],hd['filterInfo']['filterVersion'],{k:x for k,x in fd.items() if k not in ('schema','category')},ACTOR])
 job=scalar("(select id from machimoa_review.processing_jobs where source_item_id="+lit(hid)+" and processing_stage='ai_enrichment')")
 qd=rpc('admin_ai_queue_review_detail',[job]);held=rpc('admin_ai_queue_request_recheck',[job,qd['revision'],qd['version'],str(uuid4()),'',ACTOR])
 hd=rpc('admin_program_detail',[hid]);current=rpc('admin_program_save',[hid,hd['revision'],hd['version'],{'conditions':hd['facts']['conditions']+['준비물은 개인 지참']},[],'',ACTOR])
 ok('ai_recheck_requested' in current['result']['reasons'],'note-free save preserves explicit AI hold')
 ok(rpc('admin_ai_queue_review_detail',[job])['recheckPending'],'hold is not completed by fact save')
 cid,cd2=create('claimed_optional',content_kind='unknown')
 sql("update machimoa_review.processing_jobs set status='claimed',claimed_by='synthetic-claim',claimed_at=clock_timestamp(),claim_lease_until=clock_timestamp()+interval '1 hour' where source_item_id="+lit(cid)+" and processing_stage='content_review';")
 cd2=rpc('admin_program_detail',[cid])
 deny(query('admin_program_save',[cid,cd2['revision'],cd2['version'],{'content_kind':'program'},[],'',ACTOR]),'program_already_processed')
 # A qualification memo cannot erase unresolved nationality facts.
 visa=copy.deepcopy(next(x['item'] for x in myfixtures()['fixtures'] if x['name']=='visa'))
 old=visa['external_key'].split(':')[-1];visa=json.loads(json.dumps(visa).replace(old,'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'))
 visa['revision_hash']=hashlib.sha256(b'optional_visa').hexdigest();vf=visa['myseoul_facts'];vf['source_revision']=visa['revision_hash'];vf['public_category']='program'
 for axis in ('application','operation'):
  for period in vf['periods'][axis]:period.update(status='ok',endpoints=[{'value':'2020-01-01','precision':'day'},{'value':'2099-10-15','precision':'day'}])
 vid=rpc('observe_myseoul_program',[runs['myseoul_program'],[visa],None])[0]['id'];vd=rpc('admin_myseoul_program_detail',[vid])
 ok('nationality_or_visa_unresolved' in vd['result']['reasons'],'unclear visa remains a factual review')
 quoted=rpc('admin_myseoul_program_save_v2',[vid,vd['revision'],vd['version'],{'qualification_note':'길이가 충분한 메모만 작성한 합성 사례입니다.'},ACTOR])
 ok('nationality_or_visa_unresolved' in quoted['result']['reasons'],'quote alone never resolves unclear visa')
 actual=rpc('admin_myseoul_program_save_v2',[vid,quoted['revision'],quoted['version'],{'target':'유효한 D-2 비자를 보유한 성인','conditions':['D-2 비자 확인 후 신청 가능']},ACTOR])
 ok('nationality_or_visa_unresolved' not in actual['result']['reasons'],'explicit target/conditions resolve without required quote')
 ok(actual['facts']['conditions']==['D-2 비자 확인 후 신청 가능'],'actual visa restriction preserved')
 # Server privileges and empty-note data changes keep existing contracts.
 ok(scalar("has_function_privilege('anon','public.admin_program_save(uuid,text,text,jsonb,text[],text,uuid)','EXECUTE')")==False,'anon cannot save')
 ok(scalar("has_function_privilege('authenticated','public.admin_review_reclassify(uuid,text,text,bigint,jsonb,jsonb,text,uuid)','EXECUTE')")==False,'authenticated direct classify forbidden')
 ok(scalar('(select count(*) from machimoa_review.curation_candidates)')==0,'candidate/publish remains empty')
 Path(ROOT/'scripts/__pycache__/optional_review_ui_fixture.json').write_text(json.dumps({'before':d,'after':after,'classificationBefore':cd,'classificationAfter':c,'myseoulBefore':md,'myseoulAfter':reviewed,'database':db},ensure_ascii=False),encoding='utf8')
 print(json.dumps({'database':db,'checks':len(checks),'result':'passed','syntheticOnly':True,'sharedDB':False,'aiCalls':0,'cases':checks},ensure_ascii=False))
if __name__=='__main__':main()
