"""Fresh network-none DB, synthetic fixtures, real existing RPC contracts only."""
import copy
import json
import socket
import subprocess
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from test_seoul_culture_external_links_sql import docker,literal,CONTAINER
from test_seoul_evidence_connections import packets

ROOT=Path(__file__).resolve().parents[1]
BASE='nine_correction_rehearsal_93a93a3ab94f'
ACTOR='00000000-0000-4000-8000-000000000001'


def main():
    meta=json.loads(docker(['inspect',CONTAINER]))[0]
    assert meta['State']['Running'] and meta['HostConfig']['NetworkMode']=='none'
    assert not meta['HostConfig']['PortBindings'] and not meta['HostConfig']['Binds']
    assert meta['Config']['Labels']['machimoa.purpose']=='saved-count-sql-validation'
    assert all(m['Type']=='volume' and m['Name']==CONTAINER+'-data' for m in meta['Mounts'])
    assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
    db='seoul_evidence_local_'+uuid4().hex[:12]
    schema=docker(['exec',CONTAINER,'pg_dump','-U','postgres','-d',BASE,'--schema-only','--schema=public','--schema=machimoa_review'])
    docker(['exec',CONTAINER,'createdb','-U','postgres',db])
    def sql(q):return docker(['exec','-i',CONTAINER,'psql','-XqAt','-U','postgres','-d',db,'-v','ON_ERROR_STOP=1'],"set statement_timeout='15s';set lock_timeout='5s';"+q)
    def scalar(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
    def rpc(name,args):return json.loads(sql('begin;set local role service_role;select public.'+name+'('+','.join(map(literal,args))+');commit;'))
    def snapshot():return scalar('(select jsonb_object_agg(k,v) from ('+' union all '.join("select '"+t+"' k,coalesce(jsonb_agg(to_jsonb(x) order by to_jsonb(x)::text),'[]') v from machimoa_review."+t+' x' for t in ('source_items','source_item_program_facts','source_item_content_filters','processing_jobs','admin_review_events','content_filter_edits','curation_candidates'))+') x)')
    checks=[]
    def ok(v,label):assert v,label;checks.append(label)
    def deny(q,code):
        try:sql(q)
        except RuntimeError as e:ok(code in str(e),code)
        else:raise AssertionError('expected '+code)
    sql(schema.replace('CREATE SCHEMA public;','-- fresh public exists',1))
    ok(scalar('(select count(*) from machimoa_review.source_items)')==0,'schema-only, no copied operating content')
    sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation');insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation');")
    run=scalar("(select run_id from public.start_ingest_run('seoul_reservation',3600))")
    data=packets();stored=[]
    for packet in data:
        item=packet['item'];old=copy.deepcopy(item)
        if packet['name'].startswith('restored_'):
            # Already restored current facts, with independent operator choices.
            old['program_facts'].update(content_kind='program',delivery_mode='unknown',activity_region='unknown',activity_evidence=[])
            old['filterFacts']['data']['topic']={'status':'unknown','value':None}
            old['filterFacts']['evidence'].pop('topic',None)
            old['filterFacts']['data']['delivery']={'status':'unknown','value':None}
            old['filterFacts']['evidence'].pop('delivery',None)
            old['filterFacts']['data']['location']={'status':'unknown','value':None}
            old['filterFacts']['evidence'].pop('location',None)
        result=rpc('observe_seoul_program_new_only',[run,[old],None])[0]
        detail=rpc('admin_program_detail',[result['id']])
        stored.append((packet,result,detail))
        ok(detail['facts']==json.loads(json.dumps(old['program_facts'])),'SQL accepts unchanged schema '+packet['name'])
        if not packet['name'].startswith('restored_'):
            if packet['name'] in ('emoji','spaced','table'):
                ok(detail['filterInfo']['data']['location']['status']=='known','typed venue binding '+packet['name'])
            if packet['name']=='actual_conflict':ok('body_api_period_conflict' in detail['result']['reasons'],'actual date conflict is never resolved')
            if packet['name']=='missing':ok('program_description_missing' in detail['result']['reasons'],'missing description remains human review')
            if packet['name']=='ambiguous':ok(detail['filterInfo']['data']['topic']['status']=='unknown','competing topic remains unknown')
            if packet['name']=='negative_venue':ok(detail['filterInfo']['data']['location']['status']=='unknown','generic fallback cannot revive rejected venue')
        before=snapshot()
        skipped=rpc('observe_seoul_program_new_only',[run,[item],None])[0]
        ok(skipped['outcome']=='existing_skipped' and snapshot()==before,'existing fields/history/filter versions protected '+packet['name'])
    # Explicit operator values must not be overwritten by newer extraction.
    target=next(x for x in stored if x[0]['name']=='restored_5')
    packet,result,detail=target
    changed=rpc('admin_program_save',[result['id'],detail['revision'],detail['version'],{'delivery_mode':'offline','activity_region':'capital','activity_evidence':['서울 도봉구 합성생태공원 교육실']},'{}','',ACTOR])
    ok(changed['factsVersion']==detail['factsVersion']+1,'normal fenced fact save still works')
    confirmed={'topic':{'status':'known','value':'other'}}
    current=rpc('admin_content_filter_save',[result['id'],changed['revision'],changed['version'],changed['filterInfo']['filterVersion'],confirmed,ACTOR])
    now=rpc('admin_program_detail',[result['id']]);before=snapshot()
    skipped=rpc('observe_seoul_program_new_only',[run,[packet['item']],None])[0]
    ok(skipped['outcome']=='existing_skipped' and snapshot()==before,'operator-selected topic/facts remain authoritative')
    deny('set role service_role;select public.admin_program_save('+','.join(map(literal,[result['id'],detail['revision'],detail['version'],{'delivery_mode':'offline'},'{}','',ACTOR]))+');','program_version_conflict')
    ok(snapshot()==before,'stale request makes no edits')
    candidate_target=stored[0]
    item=candidate_target[0]['item']
    sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) values('seoul_reservation',"+literal(item['external_key'])+','+literal(item['revision_hash'])+",'synthetic-evidence-keep','keep','keep','keep','{}','success');")
    before=snapshot();rpc('observe_seoul_program_new_only',[run,[item],None]);ok(snapshot()==before,'existing candidate preserved without regeneration')
    for role in ('anon','authenticated'):deny('set role '+role+';select public.admin_program_detail('+literal(result['id'])+');','permission denied')
    # Reuse the real DTO/Auth/request handler with fake RPC only, fed from the
    # same extraction packets that just passed actual isolated PostgreSQL.
    response=subprocess.run(['node',str(ROOT/'scripts/test_seoul_review_value_link.mjs'),'--packets-stdin'],input=json.dumps(data).encode(),capture_output=True)
    assert response.returncode==0,response.stderr.decode()+response.stdout.decode()
    ok(snapshot()==before,'fake Auth/RPC execution cannot mutate isolated SQL state')
    print(response.stdout.decode().strip())
    print(json.dumps({'checks':len(checks),'result':'passed','database':db,'packets':len(data),'restored_shapes':9,'network':'none','operating_database':0,'ai_calls':0}))


if __name__=='__main__':
    with patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')):main()
