"""Real PostgreSQL in a network-none synthetic container. No credentials or provider."""
import copy
import json
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from ingest.pc_worker_existing import ExistingWorkers
from ingest.program_ai import ProgramAIAdapter
from test_myseoul_db import fixtures
from test_seoul_culture_external_links_sql import CONTAINER, docker, literal

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / 'supabase/migrations'
BASE = 'seoul_same_period_local_5f9f157666b3'
ACTOR = str(uuid4())


def main():
    meta = json.loads(docker(['inspect', CONTAINER]))[0]
    assert meta['State']['Running'] and meta['HostConfig']['NetworkMode'] == 'none'
    assert not meta['HostConfig']['PortBindings'] and not meta['HostConfig']['Binds']
    assert meta['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
    assert all(m['Type']=='volume' and m['Name']==CONTAINER+'-data' for m in meta['Mounts'])
    assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
    db = 'classification_queue_fixture_' + uuid4().hex[:12]
    schema = docker(['exec', CONTAINER, 'pg_dump', '-U', 'postgres', '-d', BASE, '--schema-only',
                     '--schema=public', '--schema=machimoa_review'])
    docker(['exec', CONTAINER, 'createdb', '-U', 'postgres', db])

    def sql(query):
        return docker(['exec','-i',CONTAINER,'psql','-XqAt','-U','postgres','-d',db,'-v','ON_ERROR_STOP=1'],query)

    def rpc(name, *args):
        return json.loads(sql('begin;set local role service_role;select to_jsonb(public.'+name+'('+
                              ','.join(map(literal,args))+'));commit;'))

    def denied(operation, message):
        try:
            operation()
        except RuntimeError as e:
            assert message in str(e), str(e)
        else:
            raise AssertionError('expected '+message)

    sql(schema.replace('CREATE SCHEMA public;', '-- existing public'))
    for version in ['20261104004126','20261104031651','20261117102024','20261117114500','20261117114501','20261124150000']:
        sql(next(MIGRATIONS.glob(version+'_*')).read_text(encoding='utf8'))
    sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('myseoul_program','fixture','content','rest',true,'approved_noncommercial','myseoul_program');insert into machimoa_review.source_sync_state(source_id) values('myseoul_program');")
    run = sql("select run_id from public.start_ingest_run('myseoul_program',3600)")
    sample = next(x['item'] for x in fixtures()['fixtures'] if x['name']=='personal')

    def seed():
        item = json.loads(json.dumps(sample).replace(sample['external_key'].split(':')[-1],uuid4().hex.upper()))
        item['revision_hash'] = uuid4().hex*2
        item['min_fields']['title'] = '나를 위한 크리스마스 힐링 워크숍 참여자 모집 (합성)'
        f = item['myseoul_facts']
        f.update(source_revision=item['revision_hash'],public_category='unknown',delivery_mode='offline')
        f['issues'] = [{'code':'category_unresolved','field':'public_category','evidence':[]}]
        for key in list(item):
            if key.startswith('filter'): del item[key]
        sid = rpc('observe_myseoul_program',run,[item],None)[0]['id']
        d = rpc('admin_review_classification_detail',sid)
        assert not d['category'],d['category']
        draft = d['drafts']['program']
        draft['facts']['delivery'] = 'offline'
        known = lambda value: {'status':'known','value':value}
        draft['filters'].update(delivery=known('onsite'),topic=known('culture_experience'),audience=known('other'),
            location=known({'scope':'specific','venues':[{'province':'11','district':None,'facility':'','address':''}]}))
        draft['filters'].setdefault('foreignerProgram',{'status':'unknown','value':None})
        return [sid,d['revision'],d['version'],0,draft['facts'],draft['filters'],'',ACTOR]

    def state(sid):
        facts = rpc('admin_review_list','facts',0,25)
        queue = rpc('admin_review_ai_queue',0,25,'{}')['items']
        ai = sql("select count(*) from machimoa_review.processing_jobs where source_item_id="+literal(sid)+" and processing_stage='ai_enrichment'")
        return (sum(x['id']==sid for x in facts),sum(x['sourceItemId']==sid and x['status']=='queued' for x in queue),int(ai))

    def recover(d):
        return rpc('admin_queue_confirmed_classification',d['id'],d['revision'],d['classificationVersion'],d['version'])

    old = seed()
    before = rpc('admin_review_reclassify',*old)
    assert before['ready'] and state(old[0])==(0,0,0)
    sql(next(MIGRATIONS.glob('20261125073000_*')).read_text(encoding='utf8'))
    assert state(old[0])==(0,0,0)
    job = recover(before)
    current = rpc('admin_review_classification_detail',old[0])
    assert recover(current)==job and current['classificationVersion']==1 and state(old[0])==(0,1,1)
    print('PASS reproduced original gap; migration left old row alone; fenced recovery is idempotent',flush=True)

    args = seed()
    browser_data = {'native':rpc('admin_myseoul_program_detail',args[0]),
                    'classification':rpc('admin_review_classification_detail',args[0])}
    assert state(args[0])==(1,0,0)
    bad = copy.deepcopy(args);bad[5]['topic']={'status':'unknown','value':None}
    denied(lambda:rpc('admin_review_reclassify',*bad),'classification_missing_filters')
    assert state(args[0])==(1,0,0)
    sql("""create function public.test_reject_queue() returns trigger language plpgsql as $$begin
         if new.processing_stage='ai_enrichment' then raise exception 'fixture_reject';end if;return new;end$$;
         create trigger test_reject before insert on machimoa_review.processing_jobs for each row execute function public.test_reject_queue();""")
    denied(lambda:rpc('admin_review_reclassify',*args),'fixture_reject')
    assert state(args[0])==(1,0,0) and rpc('admin_review_classification_detail',args[0])['version']==args[2]
    sql('drop trigger test_reject on machimoa_review.processing_jobs')
    gate=Barrier(2)
    def concurrent(_):
        gate.wait()
        try:return rpc('admin_review_reclassify',*args)['ready']
        except RuntimeError as e:
            assert 'classification_conflict' in str(e);return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(concurrent,range(2)))==[False,True]
    # Treat the winning response as lost. A GET verifies the saved values.
    saved = rpc('admin_review_classification_detail',args[0])
    assert saved['ready'] and saved['classificationVersion']==1 and saved['facts']==args[4] and saved['filters']==args[5]
    assert state(args[0])==(0,1,1)
    native_saved=rpc('admin_myseoul_program_detail',args[0])
    assert native_saved['status']=='resolved' and native_saved['aiStatus']=='queued', (native_saved['status'],native_saved['aiStatus'])
    if os.getenv('CLASSIFICATION_BROWSER_TEST')=='1':
        browser_data.update(saved=saved,nativeSaved=native_saved,job=next(
            j for j in rpc('admin_review_ai_queue',0,25,'{}')['items'] if j['sourceItemId']==args[0]))
        folder=ROOT/'.next/cache'
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'classification-queue-fixture.json').write_text(json.dumps(browser_data),encoding='utf8')
    denied(lambda:rpc('admin_review_reclassify',*args),'classification_conflict')
    print('PASS missing field, atomic enqueue failure, concurrent submissions and lost save response',flush=True)

    held = seed()
    sql("insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,reason_codes,queued_at,available_at) values("+literal(held[0])+","+literal(held[1])+",'relationship_review','queued',array['synthetic_reason'],now(),now())")
    held[2]=rpc('admin_review_classification_detail',held[0])['version']
    assert not rpc('admin_review_reclassify',*held)['ready'] and state(held[0])==(1,0,0)

    jid = recover(saved)
    repeat=copy.deepcopy(args)
    repeat[2:4]=[saved['version'],1]
    assert rpc('admin_review_reclassify',*repeat)['classificationVersion']==1 and recover(saved)==jid
    # A real edit after registration invalidates the frozen version; keep the one queued row.
    repeat[5]['topic']['value']='daily_safety'
    updated=rpc('admin_review_reclassify',*repeat)
    assert updated['classificationVersion']==2 and state(args[0])==(0,1,1)
    assert recover(updated)==jid
    claim_args = [jid,args[0],args[1],2,'fake-worker',300]
    for idx,value in [(0,str(uuid4())),(2,'f'*64),(3,1)]:
        stale=claim_args.copy();stale[idx]=value
        assert rpc('claim_queued_classification_no_retry',*stale)==[]
    ctx = rpc('claim_queued_classification_no_retry',*claim_args)
    assert ctx['failurePolicy']['policy']=='no_retry' and ctx['filters']==updated['filters']
    assert rpc('claim_queued_classification_no_retry',*claim_args)==[]
    denied(lambda:recover(rpc('admin_review_classification_detail',args[0])),'classification_not_ready')
    print('PASS unrelated review, existing queued/claimed, stale job/revision/classification rejected',flush=True)

    # Only the recovered fixture is queued. Dispatch the real PC all-button path
    # against the local RPCs and a fake Pro, stopping at a private candidate.
    events=[]
    class Pro:
        def summarize_myseoul_ko(self,body,url,*,title):
            assert json.loads(body)['currentFilters']==before['filters']
            events.append('summary')
            return '[한 줄 요약]\n합성 안내\n[주요 내용]\n합성 본문','success','fake-model'
        def translate_ja(self,title,body):
            events.append('translation')
            return '合成案内','[要約]\n合成案内\n[主な内容]\n参加情報 '+ ' '.join(re.findall(r'\d[\d,]*',body)),'success','fake-model'
    def invoke(name,params):
        parts=[k+'=> '+("'{}'::uuid[]" if k=='p_watch' else literal(v)) for k,v in params.items()]
        events.append(name)
        return json.loads(sql('begin;set local role service_role;select public.'+name+'('+','.join(parts)+');commit;'))
    worker=ExistingWorkers('fake',ai_context=lambda:(ProgramAIAdapter(invoke),Pro(),lambda:None))
    result=worker({'kind':'ai','limit':'all','source':'all'})
    assert result['counts']['completed']==1,(result,events)
    assert events.count('summary')==events.count('translation')==events.count('finish_reclassified_content_ai')==1
    assert state(old[0])==(0,0,1)
    assert sql("select review_status from machimoa_review.curation_candidates where title like '%힐링 워크숍%'")=='pending'
    candidate_detail=rpc('admin_review_classification_detail',old[0])
    denied(lambda:recover(candidate_detail),'classification_not_ready')
    old[2:4]=[candidate_detail['version'],candidate_detail['classificationVersion']]
    assert rpc('admin_review_reclassify',*old)['classificationVersion']==1
    assert sql("select review_status from machimoa_review.curation_candidates where title like '%힐링 워크숍%'")=='pending'
    print('PASS normal PC button -> saved classification -> fake Pro -> single private candidate; duplicate recovery blocked',flush=True)


if __name__=='__main__':
    with patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')):
        main()
