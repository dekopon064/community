"""Only a pre-created, verified network-none synthetic PostgreSQL database."""
import argparse
import copy
import json
import subprocess
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from test_myseoul_db import fixtures

parser=argparse.ArgumentParser()
parser.add_argument('--database',required=True)
args=parser.parse_args()
assert args.database.startswith('review_classification_flow_') and args.database.replace('_','').isalnum()
container='machimoa-saved-count-sql-20261009-56ca9041'
def docker(parts,body=None):
    r=subprocess.run(['docker',*parts],input=body.encode() if body else None,capture_output=True)
    if r.returncode:raise RuntimeError(r.stderr.decode())
    return r.stdout.decode().strip()
meta=json.loads(docker(['inspect',container]))[0]
assert meta['State']['Running'] and meta['HostConfig']['NetworkMode']=='none' and not meta['HostConfig']['PortBindings']
assert meta['Config']['Labels']['machimoa.purpose']=='saved-count-sql-validation'
assert all(m['Type']=='volume' and m['Name']==container+'-data' for m in meta['Mounts'])
assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
def sql(q):return docker(['exec','-i',container,'psql','-XqAt','-U','postgres','-d',args.database,'-v','ON_ERROR_STOP=1','-v','VERBOSITY=verbose'],q)
def lit(v):
    if v is None:return 'NULL'
    if isinstance(v,bool):return str(v).lower()
    if isinstance(v,int):return str(v)
    return "'"+(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False)).replace("'","''")+"'"
def scalar(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
def rpc(name,values):return json.loads(sql('begin;set local role service_role;select public.'+name+'('+','.join(map(lit,values))+');commit;'))
checks=0
def ok(v):
    global checks
    assert v
    checks+=1
def deny(q,message):
    global checks
    try:sql(q)
    except RuntimeError as e:
        assert message in str(e),str(e)
        checks+=1
    else:raise AssertionError(message)
root=Path(__file__).resolve().parents[1]
up=(root/'supabase/migrations/20261010115536_review_classification_flow.sql').read_text(encoding='utf8')
down=(root/'supabase/rollback/20261010115536_review_classification_flow_down.sql').read_text(encoding='utf8')
ok(scalar('(select not dirty from machimoa_review.classification_flow_install where singleton)'))
deny("begin;alter function machimoa_review.classification_validate(jsonb,jsonb) set search_path='public';"+down,'classification_flow_successor_changed')
deny("begin;alter table machimoa_review.review_classifications disable trigger classification_flow_dirty;"+down,'classification_flow_trigger_changed')
deny("begin;alter table machimoa_review.classification_flow_install disable row level security;"+down,'classification_flow_backup_changed')
deny("begin;update machimoa_review.classification_flow_install set backup='{}' where singleton;"+down,'classification_flow_backup_changed')
sql(down)
ok(scalar("to_regclass('machimoa_review.classification_flow_install') is null"))
deny("begin;alter function machimoa_review.classification_validate(jsonb,jsonb) set search_path='public';"+up,'classification_flow_predecessor_changed')
sql(up)
for role in ('anon','authenticated','service_role'):
    ok(not scalar("has_table_privilege('"+role+"','machimoa_review.classification_flow_install','select')"))
    ok(not scalar("has_function_privilege('"+role+"','machimoa_review.classification_flow_dirty()','execute')"))
for role in ('anon','authenticated'):
    ok(not scalar("has_function_privilege('"+role+"','public.admin_review_reclassify(uuid,text,text,bigint,jsonb,jsonb,text,uuid)','execute')"))
ok(scalar("(select relrowsecurity from pg_class where oid='machimoa_review.classification_flow_install'::regclass)"))
actor='00000000-0000-4000-8000-000000000001'
sql("update machimoa_review.ingest_sources set enabled=true,permission_status='approved_noncommercial' where source_id='myseoul_program';")
run=scalar("(select active_run_id from machimoa_review.source_sync_state where source_id='myseoul_program' and lease_expires_at>clock_timestamp())")
if not run:run=scalar("(select run_id from public.start_ingest_run('myseoul_program',3600))")
base=next(x['item'] for x in fixtures()['fixtures'] if x['name']=='personal')
def observe(category='program',mode='offline',excluded=False,region='capital'):
    p=copy.deepcopy(base);old=p['external_key'].split(':')[-1]
    p=json.loads(json.dumps(p).replace(old,uuid4().hex.upper()))
    p['revision_hash']=uuid4().hex*2
    f=p['myseoul_facts']
    f.update(source_revision=p['revision_hash'],public_category=category,delivery_mode=mode,
             residence_scope='unknown',residence='',residence_evidence=[],
             activity_region='noncapital' if excluded else region,venue='합성 서울 개최지',activity_evidence=['합성 원문: 서울에서 개최'])
    f['issues']=[x for x in f['issues'] if x['code'] not in ('category_unresolved','activity_region_unknown','online_residence_unknown','delivery_mode_unknown')]
    if category=='unknown':f['issues'].append({'code':'category_unresolved','field':'public_category','evidence':[]})
    for k in list(p):
        if k.startswith('filter'):p.pop(k)
    return rpc('observe_myseoul_program',[run,[p],None])[0]['id']
detail=lambda sid:rpc('admin_review_classification_detail',[sid])
known=lambda v:{'status':'known','value':v}
location=known({'scope':'specific','venues':[{'province':'11','district':None,'facility':'','address':''}]})
note='운영자 확인: 합성 원문과 보존한 값 및 누락 항목을 확인했습니다.'
def draft(d,category='program'):
    v=copy.deepcopy(d['drafts'][category]);f=v['facts'];cf=v['filters']
    cf['location']=copy.deepcopy(location)
    if category=='program':
        cf.update(topic=known('culture_experience'),audience=known('other'),delivery=known('onsite'))
        f['delivery']='offline'
    if category=='event':cf['topic']=known('festival_exchange')
    if category=='youth_space':cf['spaceKind']=known('introduction')
    return v
def save(d,v):return rpc('admin_review_reclassify',[d['id'],d['revision'],d['version'],d['classificationVersion'],v['facts'],v['filters'],note,actor])
def save_query(d,v):return 'begin;set local role service_role;select public.admin_review_reclassify('+','.join(map(lit,[d['id'],d['revision'],d['version'],d['classificationVersion'],v['facts'],v['filters'],note,actor]))+');commit;'
sid=observe();native=rpc('admin_myseoul_program_detail',[sid]);d=detail(sid);v=draft(d)
ok(v['facts']['scope']=='unknown' and not v['facts']['evidence'])
bad=copy.deepcopy(v);bad['filters']['topic']={'status':'unknown','value':None}
deny(save_query(d,bad),'classification_missing_filters')
ok(detail(sid)['classificationVersion']==0)
saved=save(d,v)
ok(saved['ready'] and saved['category']=='program')
ok(saved['facts']['scope']=='unknown' and saved['facts']['evidence']=='')
ok(saved['filters']==v['filters'])
ok(rpc('admin_myseoul_program_detail',[sid])['observedFacts']==native['observedFacts'])
ok(rpc('admin_myseoul_program_detail',[sid])['facts']==native['facts'])
deny(save_query(d,v),'PT409')
ok(saved['drafts']['program']==v)
ok(saved['drafts']['event']['filters']['location']==location)
bad=draft(saved);bad['facts']['delivery']='online';bad['filters']['delivery']=known('online');bad['filters']['location']={'status':'not_applicable','value':None}
deny(save_query(saved,bad),'classification_missing_evidence')
bad=copy.deepcopy(v);bad['filters']['application']['value']['start']=None
deny(save_query(saved,bad),'PT422')
ok(detail(sid)['classificationVersion']==1)
ok(scalar("(select count(*) from machimoa_review.processing_jobs where source_item_id="+lit(sid)+" and processing_stage='ai_enrichment' and status='claimed')")==0)
# A synthetic claim and fake candidate response verify the actual downstream contract.
job=rpc('claim_reclassified_content_ai',[sid,saved['revision'],1,'synthetic-flow',300])
from ingest.reclassification_ai import validate_context
ok(validate_context(job,sid,saved['revision'],1,'synthetic-flow')['facts']['evidence']=='')
deny(save_query(saved,v),'PT409')
output={'titleKo':'합성','summaryKo':'합성 요약','contentKo':'합성 본문','titleJa':'合成','summaryJa':'合成概要','contentJa':'合成本文','aiModel':'synthetic-only'}
finished=rpc('finish_reclassified_content_ai',[job['jobId'],job['revision'],1,job['claimedAt'],job['leaseUntil'],job['workerId'],output])
candidate=rpc('admin_review_detail',['candidates',finished['candidateId']])
d=detail(sid);changed=save(d,draft(d,'event'))
ok(changed['category']=='event' and changed['ready'])
ok(changed['facts']['scope']=='unknown' and changed['filters']['location']==location)
deny('begin;set local role service_role;select public.admin_review_publish('+','.join(map(lit,[candidate['id'],candidate['revision'],candidate['version'],actor]))+');commit;','PT409')
ok(scalar('(select review_status from machimoa_review.curation_candidates where id='+lit(candidate['id'])+')')=='superseded')
d=detail(sid);back=save(d,draft(d))
ok(back['category']=='program' and back['filters']['application']==v['filters']['application'])
ok(back['id']==sid and back['revision']==saved['revision'])
sid2=observe(category='unknown');d=detail(sid2)
ok(d['category']=='' and not d['active'])
saved2=save(d,draft(d));ok(saved2['category']=='program' and saved2['ready'])
sid_venue=observe(region='unknown');native_venue=rpc('admin_myseoul_program_detail',[sid_venue]);d=detail(sid_venue)
confirmed_venue=save(d,draft(d))
ok(confirmed_venue['ready'] and 'activity_region_unknown' not in confirmed_venue['sourceReasons'])
ok(confirmed_venue['facts']['scope']=='unknown' and not confirmed_venue['facts']['evidence'])
ok(rpc('admin_myseoul_program_detail',[sid_venue])['facts']==native_venue['facts'])
sid3=observe(excluded=True);d=detail(sid3)
ok(not d['editable'] and not d['ready'] and 'classification_source_excluded' in d['sourceReasons'])
deny(save_query(d,draft(d)),'PT409')
deny('begin;set local role service_role;select public.claim_reclassified_content_ai('+','.join(map(lit,[sid3,d['revision'],1,'synthetic-denied',300]))+');commit;','PT409')
# Explicit non-capital participant limits remain blocked rather than becoming nationwide.
sid4=observe();d=detail(sid4);restricted=draft(d);restricted['facts'].update(scope='specific',regions=['26'],evidence='합성 원문: 부산 주민만')
blocked=save(d,restricted);ok(not blocked['ready'])
ok(blocked['facts']['regions']==['26'])
sid6=observe();d=detail(sid6);news=draft(d,'youth_space')
news['facts'].update(scope='nationwide',regions=[],evidence='합성 원문: 전국 이용 대상')
news['filters'].update(spaceKind=known('news'),location={'status':'not_applicable','value':None})
news_saved=save(d,news);ok(news_saved['ready'] and 'activity_region_unknown' not in news_saved['sourceReasons'])
# One winner, one conflict, and one history record for a concurrent first confirmation.
sid5=observe();d=detail(sid5);barrier=Barrier(2)
def race(category):
    barrier.wait()
    try:return save(d,draft(d,category))['category']
    except RuntimeError as e:
        assert 'PT409' in str(e),str(e)
        return 'conflict'
with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(race,['program','event']))
ok(results.count('conflict')==1)
ok(scalar('(select count(*) from machimoa_review.review_classification_history where source_item_id='+lit(sid5)+')')==1)
deny(down,'classification_flow_records_present')
ok(scalar("to_regprocedure('machimoa_review.classification_validate(jsonb,jsonb)') is not null"))
print(json.dumps({'checks':checks,'database':args.database,'actualProviderCalls':0,'productionAccess':False,'result':'passed'}))
