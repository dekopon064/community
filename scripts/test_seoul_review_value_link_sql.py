"""Fresh schema-only local PostgreSQL; synthetic rows, network=none. No credentials."""
import copy
import json
from pathlib import Path
from uuid import uuid4
from test_seoul_culture_external_links_sql import docker, literal, CONTAINER, BASE
from test_seoul_review_value_link import synthetic_packets

ROOT=Path(__file__).resolve().parents[1]
ACTOR='00000000-0000-4000-8000-000000000001'


def main():
    meta=json.loads(docker(['inspect',CONTAINER]))[0]
    assert meta['State']['Running'] and meta['HostConfig']['NetworkMode']=='none'
    assert not meta['HostConfig']['PortBindings'] and not meta['HostConfig']['Binds']
    assert meta['Config']['Labels']['machimoa.purpose']=='saved-count-sql-validation'
    assert all(v['Type']=='volume' and v['Name']==CONTAINER+'-data' for v in meta['Mounts'])
    assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
    db='seoul_value_link_local_'+uuid4().hex[:12]
    schema=docker(['exec',CONTAINER,'pg_dump','-U','postgres','-d',BASE,'--schema-only','--schema=public','--schema=machimoa_review'])
    assert schema.count('CREATE SCHEMA public;')==1
    docker(['exec',CONTAINER,'createdb','-U','postgres',db])
    def sql(q):return docker(['exec','-i',CONTAINER,'psql','-XqAt','-U','postgres','-d',db,'-v','ON_ERROR_STOP=1'],"set statement_timeout='15s';set lock_timeout='5s';"+q)
    def scalar(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
    def rpc(name,args):return json.loads(sql('begin;set local role service_role;select public.'+name+'('+','.join(literal(v) for v in args)+');commit;'))
    checks=[]
    def ok(v,label):assert v,label;checks.append(label)
    def deny(q,code):
        try:sql(q)
        except RuntimeError as e:ok(code in str(e),code)
        else:raise AssertionError('expected '+code)
    sql(schema.replace('CREATE SCHEMA public;','-- fresh public exists',1))
    sql((ROOT/'supabase/migrations/20261014163727_seoul_culture_external_url_validation.sql').read_text(encoding='utf-8'))
    def snapshot():
        return scalar("(select jsonb_object_agg(k,v) from (values ('sources',(select coalesce(jsonb_agg(to_jsonb(x)),'[]') from machimoa_review.source_items x)),('facts',(select coalesce(jsonb_agg(to_jsonb(x)),'[]') from machimoa_review.source_item_program_facts x)),('filters',(select coalesce(jsonb_agg(to_jsonb(x)),'[]') from machimoa_review.source_item_content_filters x)),('jobs',(select coalesce(jsonb_agg(to_jsonb(x)),'[]') from machimoa_review.processing_jobs x)),('history',(select coalesce(jsonb_agg(to_jsonb(x)),'[]') from machimoa_review.admin_review_events x)),('candidates',(select coalesce(jsonb_agg(to_jsonb(x)),'[]') from machimoa_review.curation_candidates x))) t(k,v))")
    packets=synthetic_packets()
    future=next(x['item']['program_facts'] for x in packets if x['name']=='announced')
    deny('select machimoa_review.program_validate('+literal(future)+');','invalid_program_value')
    sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation');insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation');")
    run=scalar("(select run_id from public.start_ingest_run('seoul_reservation',3600))")
    legacy=copy.deepcopy(next(x['item'] for x in packets if x['name']=='missing'))
    legacy['external_key']='SYNTH_existing_preserved'
    existing=rpc('observe_seoul_program_new_only',[run,[legacy],{'synthetic':True}])[0]
    old=rpc('admin_program_detail',[existing['id']])
    edited=rpc('admin_program_save',[existing['id'],old['revision'],old['version'],
        {'description':'운영자가 별도로 확인한 합성 설명과 고유 조건을 보존합니다.'},'{program_description_missing}','',ACTOR])
    ok(edited['factsVersion']>old['factsVersion'],'existing formal edit has a newer version and history')
    sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) values('seoul_reservation','SYNTH_existing_preserved',"+literal(legacy['revision_hash'])+",'synthetic-value-link-existing','keep-title','keep-summary','keep-body','{\"synthetic\":true}','success');")
    definition=scalar("pg_get_functiondef('machimoa_review.program_validate(jsonb)'::regprocedure)")
    before_meta=scalar("(select jsonb_build_array(proowner,proacl,proconfig,prosecdef,provolatile) from pg_proc where oid='machimoa_review.program_validate(jsonb)'::regprocedure)")
    before=snapshot();migration=(ROOT/'supabase/migrations/20261015021859_seoul_review_value_link.sql').read_text(encoding='utf-8')
    deny("begin;alter function machimoa_review.program_validate(jsonb) set search_path='public';"+migration,'seoul_status_prerequisite_changed')
    ok(scalar("pg_get_functiondef('machimoa_review.program_validate(jsonb)'::regprocedure)")==definition,'bad predecessor rolls back')
    deny('begin;'+definition.replace('invalid_program_value','different_validation_message')+';'+migration,'seoul_status_prerequisite_changed')
    ok(snapshot()==before,'definition mismatch preserves existing rows')
    link_sigs=['machimoa_review.content_filter_fact_values(uuid,text)',
               'machimoa_review.program_evaluate_with_confirmation(jsonb,timestamptz,boolean)']
    def meta(sig):return scalar("(select jsonb_build_array(proowner,proacl,proconfig,prosecdef,provolatile) from pg_proc where oid="+literal(sig)+"::regprocedure)")
    link_meta=[meta(sig) for sig in link_sigs]
    deny("begin;alter function machimoa_review.content_filter_fact_values(uuid,text) set search_path='public';"+migration,'seoul_status_link_prerequisite_changed')
    ok(scalar("pg_get_functiondef('machimoa_review.program_validate(jsonb)'::regprocedure)")==definition,'late prerequisite failure rolls back validator too')
    sql(migration)
    ok(snapshot()==before,'DDL changes no facts filters history jobs candidates')
    ok(scalar("(select jsonb_build_array(proowner,proacl,proconfig,prosecdef,provolatile) from pg_proc where oid='machimoa_review.program_validate(jsonb)'::regprocedure)")==before_meta,'owner ACL search_path immutable security unchanged')
    for role in ['anon','authenticated','service_role']:
        ok(not scalar("has_function_privilege("+literal(role)+",'machimoa_review.program_validate(jsonb)','execute')"),'private validator denied '+role)
    for sig,previous in zip(link_sigs,link_meta):
        ok(meta(sig)==previous,'linked function metadata preserved '+sig)
        for role in ['anon','authenticated','service_role']:
            ok(not scalar('has_function_privilege('+literal(role)+','+literal(sig)+",'execute')"),'linked function private '+role+' '+sig)
    for value in packets:
        scalar('machimoa_review.program_validate('+literal(value['item']['program_facts'])+')')
    bad=copy.deepcopy(future);bad['source_status']='invented'
    deny('select machimoa_review.program_validate('+literal(bad)+');','invalid_program_value')
    for value in packets:
        item=value['item'];name=value['name']
        result=rpc('observe_seoul_program_new_only',[run,[item],{'synthetic':True}])[0]
        d=rpc('admin_program_detail',[result['id']])
        expected=json.loads(json.dumps(item['program_facts']))
        ok(d['facts']==expected and d['observedFacts']==expected,'current and observed facts preserved '+name)
        if name=='numbered':ok(d['facts']['delivery_mode']=='offline' and d['filterInfo']['data']['location']['status']=='known','facts and filter use same place')
        if name=='long_topic':ok(d['filterInfo']['data']['topic']['status']=='known','short exact topic excerpt accepted by SQL')
        if name=='announced':
            ok('source_status_unknown' not in d['result']['reasons'] and d['facts']['source_status']=='announced','announcement is known without open substitution')
            confirmed=scalar('machimoa_review.content_filter_fact_values('+literal(result['id'])+'::uuid,'+literal(d['revision'])+')')
            ok(confirmed['application']['sourceStatus']=='not_started','server confirmed facts map to pre-reception')
            ok(d['filterInfo']['data']['application']['value']['sourceStatus']=='not_started','stored filter agrees with server')
        if name=='missing':ok('program_description_missing' in d['result']['reasons'],'missing description still reviewable')
        if name=='conflict':ok('body_api_period_conflict' in d['result']['reasons'],'actual date conflict remains')
        before=snapshot();changed=copy.deepcopy(item);changed['program_facts']['description']='overwrite forbidden'
        skipped=rpc('observe_seoul_program_new_only',[run,[changed],{'synthetic':True}])[0]
        ok(skipped['outcome']=='existing_skipped' and snapshot()==before,'existing values jobs versions history untouched '+name)
    ok(scalar('(select count(*) from machimoa_review.curation_candidates)')==1,'existing synthetic candidate preserved; no new candidate')
    ready=copy.deepcopy(next(x['item']['program_facts'] for x in packets if x['name']=='numbered'))
    ready['source_status']='announced'
    def evaluate(f):return scalar('machimoa_review.program_evaluate('+literal(f)+",'2026-10-01T18:00:00+09:00'::timestamptz)")
    for start in ['2026-09-01T10:00:00+09:00','2026-10-02T10:00:00+09:00']:
        ready['periods']['RCPTBGNDT']['value']=start
        e=evaluate(ready)
        ok(e['decision']=='not_currently_available' and e['reasons']==['application_not_started'],'pre-reception is never accepting '+start)
    for code in ['body_api_period_conflict','source_status_conflict']:
        bad=copy.deepcopy(ready);bad['conflicts']=[code];e=evaluate(bad)
        ok(e['decision']=='review_required' and code in e['reasons'],'real conflict survives '+code)
    bad=copy.deepcopy(ready);bad['periods']['RCPTBGNDT']['value']='2026-11-01T10:00:00+09:00'
    ok('period_order_conflict' in evaluate(bad)['reasons'],'real reception-date order conflict survives')
    again=rpc('admin_program_detail',[existing['id']])
    ok(again['facts']==edited['facts'] and again['factsVersion']==edited['factsVersion'] and again['history']==edited['history'],'operator facts version and history preserved through migration and insertions')
    print(json.dumps({'checks':len(checks),'result':'passed','database':db,'network':'none','production':0,'ai':0},ensure_ascii=False))


if __name__=='__main__':main()
