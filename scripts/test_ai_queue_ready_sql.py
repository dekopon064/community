"""Read-only queue projection in fresh network-none PostgreSQL, synthetic rows only."""
import copy
import hashlib
import json
import socket
import subprocess
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from test_seoul_culture_external_links_sql import docker, literal, CONTAINER
from test_program_db import fixtures
from test_seoul_content import synthetic_facts
from test_myseoul_db import fixtures as my_fixtures
from test_reclassification_ai import context as classified_fixture
from ingest.content_filters import extract_filter_facts

ROOT=Path(__file__).resolve().parents[1]
BASE='seoul_value_link_local_24441ef2cc89'
MIGRATION=ROOT/'supabase/migrations/20261015050552_ai_queue_execution_ready.sql'
ACTOR='00000000-0000-4000-8000-000000000001'


def main():
    meta=json.loads(docker(['inspect',CONTAINER]))[0]
    assert meta['State']['Running'] and meta['HostConfig']['NetworkMode']=='none'
    assert not meta['HostConfig']['PortBindings'] and not meta['HostConfig']['Binds']
    assert meta['Config']['Labels']['machimoa.purpose']=='saved-count-sql-validation'
    assert all(m['Type']=='volume' and m['Name']==CONTAINER+'-data' for m in meta['Mounts'])
    assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
    db='ai_queue_ready_local_'+uuid4().hex[:12]
    schema=docker(['exec',CONTAINER,'pg_dump','-U','postgres','-d',BASE,'--schema-only','--schema=public','--schema=machimoa_review'])
    assert schema.count('CREATE SCHEMA public;')==1
    docker(['exec',CONTAINER,'createdb','-U','postgres',db])
    def sql(q):return docker(['exec','-i',CONTAINER,'psql','-XqAt','-U','postgres','-d',db,'-v','ON_ERROR_STOP=1'],"set statement_timeout='15s';set lock_timeout='5s';"+q)
    def scalar(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
    def rpc(name,args):
        values=list(map(literal,args))
        if name=='admin_review_ai_queue':values[2]='array['+','.join(map(literal,args[2]))+']::uuid[]'
        return json.loads(sql('begin;set local role service_role;select public.'+name+'('+','.join(values)+');commit;'))
    checks=[]
    def ok(v,label):assert v,label;checks.append(label)
    def deny(q,code):
        try:sql(q)
        except RuntimeError as e:ok(code in str(e),code)
        else:raise AssertionError('expected '+code)
    sql(schema.replace('CREATE SCHEMA public;','-- fresh public exists',1))
    for t in ('source_items','processing_jobs','curation_candidates'):
        ok(scalar('(select count(*) from machimoa_review.'+t+')')==0,'schema-only '+t)
    for origin in ('seoul_reservation','myseoul_program','youthcenter_policy','youthcenter_content'):
        sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values("+','.join(map(literal,[origin,'synthetic','content','rest',True,'approved_noncommercial',origin]))+");insert into machimoa_review.source_sync_state(source_id) values("+literal(origin)+");")
    runs={s:scalar("(select run_id from public.start_ingest_run("+literal(s)+",3600))") for s in ('seoul_reservation','myseoul_program')}
    known=lambda v:{'status':'known','value':v}
    def create(origin='seoul_reservation',ready=True,classified=False):
        key=('SYNTH_READY_'+uuid4().hex[:12]) if origin=='seoul_reservation' else uuid4().hex.upper()
        rev=hashlib.sha256(key.encode()).hexdigest()
        if origin=='seoul_reservation':
            item=copy.deepcopy(fixtures(storage=True)[0]['item'])
            f=synthetic_facts();f.update(missing=[],conflicts=[],editorial_pending=[])
            for name in f['periods']:
                day='2020-01-01' if name.endswith('BGNDT') else '2099-10-15'
                f['periods'][name]=dict(raw=day,value=day,status='ok',precision='day')
            f['official_url']='https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id='+key
            item.update(external_key=key,revision_hash=rev,program_facts=f)
            item['min_fields']['title']='합성 '+key
            item['normalized_payload'].update(title='합성 '+key,source_url=f['official_url'],program_text=f['description'])
            item['normalized_payload']['provider_fields'].update(SVCID=key,MAXCLASSNM='문화체험')
            item['filterFacts']=extract_filter_facts(origin,item['normalized_payload'],f)
            sid=rpc('observe_seoul_program_new_only',[runs[origin],[item],None])[0]['id']
        else:
            item=copy.deepcopy(my_fixtures()['fixtures'][0]['item'])
            old=item['external_key'].split(':')[-1];item=json.loads(json.dumps(item).replace(old,key))
            item['revision_hash']=rev;f=item['myseoul_facts'];f.update(source_revision=rev,public_category='program',issues=[])
            for group in ('application','operation'):
                for period in f['periods'][group]:period.update(status='ok',endpoints=[{'value':'2020-01-01','precision':'day'},{'value':'2099-10-15','precision':'day'}])
            sid=rpc('observe_myseoul_program',[runs[origin],[item],None])[0]['id']
        detail_name='admin_program_detail' if origin=='seoul_reservation' else 'admin_myseoul_program_detail'
        d=rpc(detail_name,[sid])
        if classified:
            c=classified_fixture('event',origin);c['facts'].update(delivery='offline',scope='unknown',evidence='')
            cd=rpc('admin_review_classification_detail',[sid])
            out=rpc('admin_review_reclassify',[sid,rev,cd['version'],cd['classificationVersion'],c['facts'],c['filters'],'',ACTOR])
            ok(out['ready'],'synthetic classification ready')
        elif ready:
            data={'topic':known('culture_experience'),'audience':known('other'),'delivery':known('onsite'),
                  'location':known({'scope':'specific','venues':[{'province':'11','district':'종로구','facility':'','address':''}]})}
            rpc('admin_content_filter_save',[sid,rev,d['version'],d['filterInfo']['filterVersion'],data,ACTOR])
            d=rpc(detail_name,[sid])
            if d.get('activityReview',{}).get('pending'):
                if origin=='seoul_reservation':rpc('admin_program_activity_confirm',[sid,rev,d['version'],d['factsVersion'],d['filterInfo']['filterVersion'],{k:data[k] for k in ('location','delivery')},'',ACTOR])
                else:rpc('admin_myseoul_activity_confirm',[sid,rev,d['version'],d['filterInfo']['filterVersion'],{'location':data['location']},{},ACTOR])
        job=scalar("(select id from machimoa_review.processing_jobs where source_item_id="+literal(sid)+" and revision_hash="+literal(rev)+" and processing_stage='ai_enrichment')")
        assert job,'fixture lacks job'
        return dict(id=sid,job=job,revision=rev,origin=origin)
    def read(watch=None,offset=0):return rpc('admin_review_ai_queue',[offset,25,watch or []])
    def ids(d):return [v['jobId'] for v in d['items']]
    def executable(t):return scalar('machimoa_review.ai_queue_executable('+literal(t['job'])+'::uuid)')
    def snapshot():
        return scalar("(select jsonb_object_agg(n,v) from ("+' union all '.join("select '"+t+"' n,coalesce(jsonb_agg(to_jsonb(x) order by to_jsonb(x)::text),'[]') v from machimoa_review."+t+" x" for t in ('source_items','source_item_program_facts','source_item_content_filters','processing_jobs','curation_candidates','admin_review_events','content_filter_edits','review_classifications','ai_rechecks'))+") z)")
    blocked=create(ready=False);ready=create();my=create('myseoul_program');classified=create(classified=True)
    ok(blocked['job'] in ids(read()),'before: blocked queued record incorrectly appears')
    ok(rpc('admin_program_detail',[blocked['id']])['aiStatus']=='blocked','before: facts detail correctly blocks same record')
    before=snapshot();up=MIGRATION.read_text(encoding='utf8')
    deny("begin;alter function machimoa_review.ai_recheck_base_queue(integer,integer,uuid[]) set search_path='public';"+up,'ai_queue_ready_predecessor_changed')
    ok(snapshot()==before,'invalid predecessor changes no rows')
    sql(up);ok(snapshot()==before,'migration changes no rows, versions or history')
    ok(not executable(blocked) and blocked['job'] not in ids(read()),'after: unfinished filters absent from executable queue')
    ok(rpc('admin_program_detail',[blocked['id']])['status']=='open','blocked item remains in human review')
    people=rpc('admin_review_list',['facts',0,25])
    ok(any(x['id']==blocked['id'] for x in people),'actual unified human list retains blocked item')
    # Classification saving may intentionally cancel the native AI job. Listing
    # never requeues it. Model an independently registered queued classification
    # in the synthetic fixture to exercise the read predicate for that path.
    ok(not executable(classified),'cancelled classification is never silently requeued')
    sql("update machimoa_review.processing_jobs set status='queued',completed_at=null where id="+literal(classified['job'])+';')
    for t in (ready,my,classified):ok(executable(t) and t['job'] in ids(read()),'ready source/classification visible '+t['origin'])
    # Non-locking list reads under read-only transactions, with no hidden refresh.
    unchanged=snapshot();sql("begin read only;set local role service_role;select public.admin_review_ai_queue(0,25,'{}');commit;")
    ok(snapshot()==unchanged,'read-only GET has no side effects')
    q=read([blocked['job']]);ok(q['observed'][0]['status']=='queued','watch reports actual status, not fake missing/completed')
    for role in ('anon','authenticated','service_role'):
        ok(not scalar("has_function_privilege("+literal(role)+",'machimoa_review.ai_queue_executable(uuid)','execute')"),'helper private '+role)
        ok(scalar("has_function_privilege("+literal(role)+",'public.admin_review_ai_queue(integer,integer,uuid[])','execute')")==(role=='service_role'),'public ACL '+role)
    for role in ('anon','authenticated'):deny('set role '+role+";select public.admin_review_ai_queue();",'permission denied')
    deny("select public.admin_review_ai_queue(100001,25,'{}');",'review_invalid_input')
    # Real omitted facts and actual conflicts stay in review; no force-ready path.
    for change in ("facts=jsonb_set(facts,'{description}','\"\"')", "facts=jsonb_set(facts,'{conflicts}','[\"body_api_period_conflict\"]')"):
        sql('update machimoa_review.source_item_program_facts set '+change+' where source_item_id='+literal(ready['id'])+';')
        ok(not executable(ready),'missing/conflicting current facts blocked')
        # Independent calls need committed fixtures; restore from preserved fixture.
        sql('update machimoa_review.source_item_program_facts set facts='+literal(before['source_item_program_facts'][next(i for i,x in enumerate(before['source_item_program_facts']) if x['source_item_id']==ready['id'])]['facts'])+' where source_item_id='+literal(ready['id'])+';')
    sql("update machimoa_review.ingest_sources set enabled=false where source_id='seoul_reservation';")
    ok(not executable(ready) and not executable(classified),'disabled source blocks native and reclassified')
    sql("update machimoa_review.ingest_sources set enabled=true where source_id='seoul_reservation';")
    for column in ('available_at','next_retry_at'):
        sql('update machimoa_review.processing_jobs set '+column+"='2199-01-01' where id="+literal(ready['job'])+';')
        ok(not executable(ready),'not yet available '+column)
        sql('update machimoa_review.processing_jobs set '+column+('=null' if column=='next_retry_at' else "='2020-01-01'")+' where id='+literal(ready['job'])+';')
    sql('update machimoa_review.source_items set revision_hash='+literal('f'*64)+' where id='+literal(ready['id'])+';')
    ok(not executable(ready),'old revision job is not executable')
    sql('update machimoa_review.source_items set revision_hash='+literal(ready['revision'])+' where id='+literal(ready['id'])+';')
    old_facts=scalar('(select to_jsonb(f) from machimoa_review.source_item_program_facts f where source_item_id='+literal(classified['id'])+')')
    sql('update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id='+literal(classified['id'])+';')
    ok(not executable(classified),'changed native snapshot blocks stale classification')
    sql('update machimoa_review.source_item_program_facts set facts_version='+str(old_facts['facts_version'])+' where source_item_id='+literal(classified['id'])+';')
    sql("update machimoa_review.processing_jobs set status='claimed',claimed_at=now()-interval '1 hour',claim_lease_until=now()-interval '1 minute',claimed_by='synthetic' where id="+literal(ready['job'])+';')
    ok(ready['job'] in ids(read()) and not executable(ready),'expired claim remains reachable, never relabelled executable')
    sql("update machimoa_review.processing_jobs set status='failed',completed_at=now(),claim_lease_until=null where id="+literal(ready['job'])+';')
    ok(ready['job'] in ids(read()),'failed attempt recovery retained')
    # Hold and observation use existing formal server contracts, no actual AI.
    d=rpc('admin_ai_queue_review_detail',[my['job']])
    held=rpc('admin_ai_queue_request_recheck',[my['job'],d['revision'],d['version'],str(uuid4()),'',ACTOR])
    ok(held['recheckPending'] and my['job'] not in ids(read()),'held item not executable')
    ok(my['job'] in [x['jobId'] for x in read()['held']],'held recovery still reachable')
    # Page boundaries are over eligible rows, even when >25 blocked rows precede them.
    for _ in range(26):create(ready=False)
    for _ in range(26):create()
    page1=read();page2=read(offset=25)
    all_ids=ids(page1)+ids(page2)
    ok(page1['hasMore'] and not page2['hasMore'],'filtered hasMore exact')
    ok(len(all_ids)==len(set(all_ids)) and len(all_ids)==28,'no duplicate, hole or hidden blocked page')
    ok(all(scalar('machimoa_review.ai_queue_executable('+literal(x['jobId'])+'::uuid)') for x in page1['items']+page2['items'] if x['status']=='queued'),'all queued projections executable')
    for origin in ('youthcenter_policy','youthcenter_content'):
        # Minimal synthetic legacy living-guide branch, already supported by
        # the existing generic claim contract; no provider or real content.
        sid=str(uuid4());rev=hashlib.sha256(sid.encode()).hexdigest();job=str(uuid4())
        sql("insert into machimoa_review.source_items(id,source_id,external_key,revision_hash,first_seen_at,last_seen_at,source_created_parse_status,source_updated_parse_status,disposition,min_fields,normalized_payload,has_source_url,body_usable) values("+','.join(map(literal,[sid,origin,'SYNTH_'+sid,rev]))+",now(),now(),'missing','missing','target','{\"title\":\"합성 생활 안내\"}','{\"plain_text\":\"합성 자료\"}',true,true);"
            "insert into machimoa_review.source_item_product_types(source_item_id,revision_hash,product_type,origin,rule_version,reviewer) values("+','.join(map(literal,[sid,rev,'living_guide','human','synthetic-v1',ACTOR]))+");"
            "insert into machimoa_review.source_item_user_categories(source_item_id,revision_hash,user_category,reviewer) values("+','.join(map(literal,[sid,rev,'living',ACTOR]))+");"
            "insert into machimoa_review.ingest_review_decisions(source_item_id,revision_hash,review_type,decision,region_scope,audience_relevance,rule_version,reviewer) values("+','.join(map(literal,[sid,rev,'content','approve_ai','capital']))+",array['foreign_residents_in_kr'],'synthetic-v1',"+literal(ACTOR)+");"
            "insert into machimoa_review.processing_jobs(id,source_item_id,revision_hash,processing_stage,status,queued_at,available_at) values("+','.join(map(literal,[job,sid,rev,'ai_enrichment','queued']))+",now(),now());")
        target={'job':job}
        ok(executable(target),'generic source positive readiness '+origin)
        sql("update machimoa_review.source_items set body_usable=false where id="+literal(sid)+';')
        ok(not executable(target),'generic source incomplete body blocked '+origin)
        sql("update machimoa_review.source_items set body_usable=true where id="+literal(sid)+';')
    candidate_target=create()
    sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) select source_id,external_key,revision_hash,'synthetic-already-candidate','합성','합성','합성','{}','success' from machimoa_review.source_items where id="+literal(candidate_target['id'])+';')
    ok(not executable(candidate_target),'existing candidate skipped without overwrite')
    # A fresh snapshot is the displayed time only; final worker claims still
    # enforce the original version/fence checks. Nothing is auto-requeued here.
    immutable=snapshot();packets={'beforeBlocked':blocked['job'],'after':read([blocked['job']]),'held':read([my['job']]),'page2':page2}
    result=subprocess.run(['node',str(ROOT/'scripts/test_ai_queue_ready.mjs')],input=json.dumps(packets).encode(),capture_output=True)
    assert result.returncode==0,result.stdout.decode()+result.stderr.decode()
    ok(snapshot()==immutable,'fake Auth/RPC verification changes no database state')
    print(result.stdout.decode().strip())
    print(json.dumps({'checks':len(checks),'result':'passed','database':db,'network':'none','production':0,'ai':0}))


if __name__=='__main__':
    with patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')):main()
