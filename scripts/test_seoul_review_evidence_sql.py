"""Real RPC in a fresh network-none database; only synthetic rows, never auth."""
import copy
import json
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from test_seoul_culture_external_links_sql import docker, literal, CONTAINER
from test_seoul_review_connections import detail
from test_seoul_evidence_connections import packets
from ingest.seoul_review_connections import same_period_supported, propose_connections

ROOT = Path(__file__).resolve().parents[1]
BASE = 'nine_correction_rehearsal_93a93a3ab94f'
MIGRATION = ROOT / 'supabase/migrations/20261015094041_seoul_same_period_reconfirmation.sql'
FORMAT_MIGRATION = ROOT / 'supabase/migrations/20261015131958_seoul_review_evidence_period_formats.sql'
ACTOR = '00000000-0000-4000-8000-000000000001'


def main():
    meta = json.loads(docker(['inspect', CONTAINER]))[0]
    assert meta['State']['Running'] and meta['HostConfig']['NetworkMode'] == 'none'
    assert not meta['HostConfig']['PortBindings'] and not meta['HostConfig']['Binds']
    assert meta['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
    assert all(m['Type'] == 'volume' and m['Name'] == CONTAINER+'-data' for m in meta['Mounts'])
    assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'
    db = 'seoul_review_evidence_local_' + uuid4().hex[:12]
    schema = docker(['exec',CONTAINER,'pg_dump','-U','postgres','-d',BASE,'--schema-only','--schema=public','--schema=machimoa_review'])
    docker(['exec',CONTAINER,'createdb','-U','postgres',db])
    def sql(q):
        return docker(['exec','-i',CONTAINER,'psql','-XqAt','-U','postgres','-d',db,'-v','ON_ERROR_STOP=1'],
                      "set statement_timeout='15s';set lock_timeout='5s';"+q)
    def scalar(q): return json.loads(sql('select to_jsonb('+q+');') or 'null')
    def rpc(name,args): return json.loads(sql('begin;set local role service_role;select public.'+name+'('+','.join(map(literal,args))+');commit;'))
    checks = []
    def ok(v,label): assert v,label; checks.append(label)
    def deny(q,code):
        try: sql(q)
        except RuntimeError as e: ok(code in str(e),code)
        else: raise AssertionError('expected '+code)
    def save_args(d): return [d['id'],d['revision'],d['version'],{'periods':d['facts']['periods']},'{body_period_needs_confirmation}','',ACTOR]
    def save_sql(args): return 'set role service_role;select public.admin_program_save('+','.join(map(literal,args))+');'
    def snapshot():
        return scalar('(select jsonb_object_agg(k,v) from ('+' union all '.join("select '"+t+"' k,coalesce(jsonb_agg(to_jsonb(x) order by to_jsonb(x)::text),'[]') v from machimoa_review."+t+' x' for t in ('source_items','source_item_program_facts','source_item_content_filters','processing_jobs','admin_review_events','curation_candidates'))+') x)')
    sql(schema.replace('CREATE SCHEMA public;','-- public already exists',1))
    sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation');insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation');")
    run = scalar("(select run_id from public.start_ingest_run('seoul_reservation',3600))")
    def insert(name,modify=lambda f:None):
        item = copy.deepcopy(packets()[0]['item']); f = detail()['facts']; modify(f)
        item['external_key'] = 'SYNTH_PERIOD_'+name; item['revision_hash'] = uuid4().hex*2
        item['program_facts'] = f; item['normalized_payload']['dates'] = f['periods']
        item['normalized_payload']['program_text'] = f['description']
        # Only synthetic operator-independent filters; leave unresolved fields explicit.
        for k in ('topic','delivery','location'): item['filterFacts']['data'][k] = {'status':'unknown','value':None}; item['filterFacts']['evidence'].pop(k,None)
        out = rpc('observe_seoul_program_new_only',[run,[item],None])[0]
        return rpc('admin_program_detail',[out['id']])
    d = insert('normal'); args = save_args(d)
    deny(save_sql(args),'program_change_required')
    before = snapshot(); sql(MIGRATION.read_text(encoding='utf-8'))
    ok(snapshot()==before,'predecessor migration changes no existing rows')
    public_before=scalar("(select jsonb_agg(jsonb_build_array(oid::regprocedure::text,pg_get_functiondef(oid),proacl::text) order by oid) from pg_proc where pronamespace='public'::regnamespace)")
    sql(FORMAT_MIGRATION.read_text(encoding='utf-8'))
    ok(snapshot()==before,'format migration changes no existing rows')
    ok(public_before==scalar("(select jsonb_agg(jsonb_build_array(oid::regprocedure::text,pg_get_functiondef(oid),proacl::text) order by oid) from pg_proc where pronamespace='public'::regnamespace)"),'all public RPC definitions and ACL unchanged')
    deny(FORMAT_MIGRATION.read_text(encoding='utf-8'),'review_period_format_predecessor_changed')
    ok(snapshot()==before,'predecessor guard rejects repeated or changed definition without writes')
    f = d['facts']; cases = [f]
    for desc in ('신청기간: 2026년 9월 29일 ~ 10월 27일','운영기간: 2026년 9월 28일 ~ 10월 27일',
                 '신청기간: 9월 28일 ~ 10월 27일','신청기간: 2026년 9월 28일(금) ~ 10월 27일',
                 '신청기간: 2026년 2월 30일 ~ 10월 27일','신청기간: 2026년 9월 28일 ~ 10월 27일 또는 11월 1일'):
        case = copy.deepcopy(f);case['description'] = desc;cases.append(case)
    for suffix in (' 13:00',' 14:00'):
        case = copy.deepcopy(f);case['description'] += suffix;case['period_evidence'][0] += suffix;cases.append(case)
    case=copy.deepcopy(f);case['description']=case['description'].replace('신청기간:','1. 신청기간:');cases.append(case)
    for conflict in ('body_api_period_conflict','date_weekday_conflict','period_order_conflict'):
        case=copy.deepcopy(f);case['conflicts']=[conflict];cases.append(case)
    case=copy.deepcopy(f);case['period_evidence']=['unrelated stale evidence'];cases.append(case)
    case=copy.deepcopy(f);case['periods']['RCPTENDDT']['status']='missing';case['periods']['RCPTENDDT']['value']=None;case['periods']['RCPTENDDT']['precision']=None;cases.append(case)
    # Supported new shapes and strict counterexamples, without changing facts.
    for text in ('접수기간: 2026년 9월 28일 10시 ~ 10월 27일 13시',
                 '접수기간: 2026년 9월 28일 11시 ~ 10월 27일 13시',
                 '접수기간: 2026년 9월 28일 10시 ~ 10월 27일 14시',
                 '접수기간: 2026년 9월 28일 24시 ~ 10월 27일 13시',
                 '접수기간: 2026년 2월 30일 10시 ~ 10월 27일 13시',
                 '운영기간: 2026년 9월 28일 10시 ~ 10월 27일 13시'):
        case=copy.deepcopy(f);case['description']=text;case['period_evidence']=[text.split(': ',1)[1]];cases.append(case)
    for text in ('운영기간: 2026.10.03','운영기간: 2026.10.03.', '접수기간: 2026.10.03',
                 '운영기간: 2026.10.04', '운영기간: 2026.2.30','운영기간: 10.03',
                 '운영기간: 2026.10.03 또는 2026.10.04'):
        case=copy.deepcopy(f);case['description']=text;case['period_evidence']=[text.split(': ',1)[1]]
        for k in ('SVCOPNBGNDT','SVCOPNENDDT'):case['periods'][k].update(value='2026-10-03',precision='day')
        cases.append(case)
    for i,case in enumerate(cases):
        ok(scalar('machimoa_review.seoul_same_period_supported('+literal(case)+'::jsonb)')==same_period_supported(case),'Python/SQL proof parity '+str(i))
    for prefix in ('♠','♣','📍','❍','◎','►','⦁'):
        case=copy.deepcopy(f);case['description']=prefix+' '+case['description']
        ok(scalar('machimoa_review.seoul_same_period_supported('+literal(case)+'::jsonb)')==same_period_supported(case),'decorated label SQL parity '+prefix)
    for role in ('anon','authenticated'):
        deny('set role '+role+';select public.admin_program_save('+','.join(map(literal,args))+');','permission denied')
    deny('set role service_role;select machimoa_review.seoul_same_period_supported('+literal(f)+'::jsonb);','permission denied')
    bad=copy.deepcopy(args);bad[-1]=None;deny(save_sql(bad),'invalid_program_command')
    bad=copy.deepcopy(args);bad[1]='f'*64;deny(save_sql(bad),'source_revision_conflict')
    bad=copy.deepcopy(args);bad[2]='f'*64;deny(save_sql(bad),'program_version_conflict')
    bad=copy.deepcopy(args);bad[4]='{body_api_period_conflict}';deny(save_sql(bad),'program_change_required')
    ok(snapshot()==before,'all denied requests preserve rows')
    after=rpc('admin_program_save',args)
    expected=copy.deepcopy(f);expected['missing'].remove('body_period_needs_confirmation')
    ok(after['facts']==expected,'only the proven missing flag removed; dates and evidence byte-preserved')
    ok(after['observedFacts']==d['observedFacts'] and after['source']==d['source'],'source and observations preserved')
    ok(after['filterInfo']['data']==d['filterInfo']['data'],'all filter choices preserved')
    ok(after['factsVersion']==d['factsVersion']+1 and after['version']!=d['version'],'normal version fence advances')
    ok(after['history'][0]['actor']==ACTOR and 'reconfirmed:periods' in after['history'][0]['fields'],'actor and explicit reconfirmation history')
    saved=snapshot();deny(save_sql(args),'program_version_conflict');ok(snapshot()==saved,'duplicate/stale request cannot repeat write')
    # Current-value connection proposals use the same existing facts/filter RPCs.
    def incomplete(f):
        f['description']='문화 공예 체험을 진행합니다.\n장소: 서울 도봉구 합성공원'
        f['missing']=['delivery_mode_unknown','activity_location_unknown']
        f['delivery_mode']='unknown';f['activity_region']='unknown';f['activity_evidence']=[]
    connected=insert('connections',incomplete);original=copy.deepcopy(connected)
    proposal=propose_connections(connected)
    ok(proposal['facts_patch']=={'delivery_mode':'offline','activity_region':'capital'},'pure current-evidence field plan')
    connected=rpc('admin_program_save',[connected['id'],connected['revision'],connected['version'],proposal['facts_patch'],'{'+','.join(proposal['resolve'])+'}','',ACTOR])
    filtered=rpc('admin_content_filter_save',[connected['id'],connected['revision'],connected['version'],connected['filterInfo']['filterVersion'],proposal['filters_patch'],ACTOR])
    connected=rpc('admin_program_detail',[connected['id']])
    ok(all(connected['filterInfo']['data'][k]==v for k,v in proposal['filters_patch'].items()),'proposed fields reach real existing fenced filter RPC')
    ok(connected['source']==original['source'] and connected['observedFacts']==original['observedFacts'],'connection preserves source and observations')
    ok(connected['facts']['periods']==original['facts']['periods'] and connected['facts']['conditions']==original['facts']['conditions'],'connection preserves dates and conditions')
    for key in ('audience','foreignerProgram','application'):
        ok(connected['filterInfo']['data'][key]==original['filterInfo']['data'][key],'unrelated filter preserved '+key)
    # Full/partial role-shape proposals through the existing real server RPCs.
    from test_seoul_review_evidence import examples
    for name,shape,provider in examples():
        def apply(f):
            f.update(copy.deepcopy(shape['facts']))
        current=insert('shape_'+name,apply);old=copy.deepcopy(current)
        proposal=propose_connections(current,provider_fields=provider)
        if proposal['facts_patch']:
            current=rpc('admin_program_save',[current['id'],current['revision'],current['version'],proposal['facts_patch'],'{'+','.join(proposal['resolve'])+'}','',ACTOR])
        if proposal['filters_patch']:
            rpc('admin_content_filter_save',[current['id'],current['revision'],current['version'],current['filterInfo']['filterVersion'],proposal['filters_patch'],ACTOR])
            current=rpc('admin_program_detail',[current['id']])
        ok(current['source']==old['source'] and current['observedFacts']==old['observedFacts'],name+' source observations unchanged')
        for k in ('description','conditions','periods','activity_evidence','target_raw','official_url'):
            ok(current['facts'][k]==old['facts'][k],name+' preserved '+k)
        if name in ('narrative','label'):
            ok(not current['filterInfo']['missing'],name+' all required filters complete')
            ok(current['aiStatus']=='queued',name+' server confirms AI readiness without executing AI')
        else:
            ok(current['aiStatus']!='queued',name+' actual missing/conflicting purpose or location stays blocked')
            ok('location' in current['filterInfo']['missing'],name+' meeting/institution address not a venue')
    # Both new period formats can be explicitly reconfirmed via fenced save.
    for name,text in [('hours','접수기간: 2026년 9월 28일 10시 ~ 10월 27일 13시'),('day','운영기간: 2026.10.03')]:
        def apply(f):
            f['description']=text;f['period_evidence']=[text.split(': ',1)[1]]
            if name=='day':
                for k in ('SVCOPNBGNDT','SVCOPNENDDT'):f['periods'][k].update(value='2026-10-03',precision='day')
        current=insert(name,apply);old=copy.deepcopy(current);current=rpc('admin_program_save',save_args(current))
        ok('body_period_needs_confirmation' not in current['facts']['missing'],name+' real same-value RPC resolves only proven flag')
        ok(current['facts']['periods']==old['facts']['periods'] and current['facts']['description']==old['facts']['description'],name+' no date or description rewrite')
    conflict=insert('conflict',lambda f:f['conflicts'].append('body_api_period_conflict'))
    b=snapshot();deny(save_sql(save_args(conflict)),'program_change_required');ok(snapshot()==b,'actual conflict remains human review')
    claimed=insert('active')
    sql("update machimoa_review.processing_jobs set status='claimed',claimed_at=clock_timestamp(),claim_lease_until=clock_timestamp()+interval '10 minutes',claimed_by='synthetic' where source_item_id="+literal(claimed['id'])+" and processing_stage='content_review';")
    claimed=rpc('admin_program_detail',[claimed['id']]);b=snapshot()
    deny(save_sql(save_args(claimed)),'program_already_processed');ok(snapshot()==b,'active attempt is never edited')

    candidate=insert('candidate')
    external=scalar('(select external_key from machimoa_review.source_items where id='+literal(candidate['id'])+')')
    sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) values('seoul_reservation',"+literal(external)+','+literal(candidate['revision'])+",'synthetic-period-existing','keep','keep','keep','{}','success');")
    candidate=rpc('admin_program_detail',[candidate['id']]);b=snapshot()
    deny(save_sql(save_args(candidate)),'program_reconfirmation_blocked');ok(snapshot()==b,'existing candidate and history preserved')
    concurrent=insert('concurrent');cargs=save_args(concurrent)
    def attempt(_):
        try:return ('ok',rpc('admin_program_save',cargs))
        except RuntimeError as e:return ('conflict','program_version_conflict' in str(e))
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(attempt,range(2)))
    ok(sum(x[0]=='ok' for x in results)==1 and all(x[0]=='ok' or x[1] for x in results),'concurrent same-version requests: one write only')
    ok(scalar("(select count(*) from machimoa_review.processing_jobs where processing_stage='ai_enrichment' and claimed_at is not null)")==0,'AI claims zero')
    ok(scalar('(select count(*) from machimoa_review.curation_candidates)')==1,'only the explicitly seeded existing candidate remains')
    print(json.dumps({'checks':len(checks),'database':db,'network':'none','result':'passed','operating_db':0,'ai_calls':0}))


if __name__=='__main__':
    with patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')):main()
