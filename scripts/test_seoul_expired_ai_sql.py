"""Network-none PostgreSQL, synthetic claims/fixtures, fake worker responses.

Copies only a known local test schema; never reads keys, shared DBs or live data.
"""
import argparse
import copy
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from test_program_db import fixtures
from test_seoul_fact_roles import confirmed_case, recorded, fake_translation
from test_ingest_ai_chatgpt_plan import verified_session, streamed
from test_ingest_ai_openai import response
from ingest.ai_provider import create_provider_adapter
from ingest.content_filters import extract_filter_facts
from ingest.seoul_content import assemble_seoul_body
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job

ROOT = Path(__file__).resolve().parents[1]
C = 'machimoa-saved-count-sql-20261009-56ca9041'
BASE = 'event_status_local_65f26d571185'
ACTOR = '00000000-0000-4000-8000-000000000001'
MIGRATION = ROOT/'supabase/migrations/20261013063052_seoul_expired_ai_recheck.sql'


def docker(args, body=None):
    r = subprocess.run(['docker', *args], input=body.encode() if body else None, capture_output=True)
    if r.returncode: raise RuntimeError(r.stderr.decode('utf8'))
    return r.stdout.decode('utf8').strip()


def lit(v):
    if v is None: return 'NULL'
    if type(v) is int: return str(v)
    return "'"+(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)).replace("'", "''")+"'"


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--before-fix', action='store_true')
    args = parser.parse_args()
    m = json.loads(docker(['inspect', C]))[0]
    assert m['State']['Running'] and m['HostConfig']['NetworkMode'] == 'none' and not m['HostConfig']['PortBindings']
    assert m['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
    assert m['Mounts'] and all(x['Type'] == 'volume' and x['Name'] == C+'-data' for x in m['Mounts'])
    assert json.loads(docker(['context', 'inspect']))[0]['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'
    db = 'seoul_expired_local_'+uuid4().hex[:12]
    dump = docker(['exec', C, 'pg_dump', '-U', 'postgres', '-d', BASE, '--schema-only', '--schema=public', '--schema=machimoa_review'])
    assert dump.count('CREATE SCHEMA public;') == 1
    docker(['exec', C, 'createdb', '-U', 'postgres', db])
    def sql(q):
        return docker(['exec', '-i', C, 'psql', '-XqAt', '-U', 'postgres', '-d', db, '-v', 'ON_ERROR_STOP=1'],
                      "set statement_timeout='15s';set lock_timeout='5s';"+q)
    sql(dump.replace('CREATE SCHEMA public;', '-- existing empty public', 1))
    def scalar(q): return json.loads(sql('select to_jsonb('+q+');') or 'null')
    def query(n, a):
        values = list(map(lit, a))
        if n == 'admin_program_save': values[4] = 'array['+','.join(map(lit, a[4]))+']::text[]'
        return 'begin;set local role service_role;select public.'+n+'('+','.join(values)+');commit;'
    def rpc(n, a): return json.loads(sql(query(n, a)))
    checks = []
    def ok(v, label):
        assert v, label; checks.append(label)
    def deny(q, messages):
        if isinstance(messages, str): messages = [messages]
        try: sql(q)
        except RuntimeError as e: ok(any(s in str(e) for s in messages), 'denied '+messages[0])
        else: raise AssertionError('expected '+str(messages))
    for t in ('source_items', 'processing_jobs', 'curation_candidates'):
        ok(scalar('(select count(*) from machimoa_review.'+t+')') == 0, 'schema-only '+t)
    sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation');insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation');")
    run = scalar("(select run_id from public.start_ingest_run('seoul_reservation',3600))")
    def create():
        key = 'SYNTH_EXPIRED_'+uuid4().hex[:12]
        item = copy.deepcopy(fixtures(storage=True)[0]['item'])
        f = copy.deepcopy(confirmed_case()['facts'])
        f['description'] = recorded()['facts']['description']  # recorded API text lost blank positions
        f.update(missing=[], conflicts=[], editorial_pending=[], activity_region='capital', delivery_mode='offline')
        for k in f['periods']:
            day = '2020-01-01' if k.endswith('BGNDT') else '2099-10-15'
            f['periods'][k] = {'raw': day, 'value': day, 'status': 'ok', 'precision': 'day'}
        f['official_url'] = 'https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id='+key
        item.update(external_key=key, revision_hash=hashlib.sha256(key.encode()).hexdigest(), program_facts=f)
        item['min_fields']['title'] = '합성 요일별 해설'
        item['normalized_payload'].update(title='합성 요일별 해설', source_url=f['official_url'], program_text=f['description'])
        item['normalized_payload']['provider_fields'].update(SVCID=key, MAXCLASSNM='문화체험')
        item['filterFacts'] = extract_filter_facts('seoul_reservation', item['normalized_payload'], f)
        sid = rpc('observe_seoul_program_new_only', [run, [item], None])[0]['id']
        d = rpc('admin_program_detail', [sid])
        known = lambda v: {'status': 'known', 'value': v}
        filters = {'topic': known('culture_experience'), 'audience': known('other'),
                   'location': known({'scope':'specific','venues':[{'province':'11','district':'종로구','facility':'','address':''}]}),
                   'delivery': known('onsite')}
        rpc('admin_content_filter_save', [sid,d['revision'],d['version'],d['filterInfo']['filterVersion'],filters,ACTOR])
        context = rpc('claim_seoul_program_ai', [sid, d['revision'], 'synthetic-expired-worker', 300])[0]
        # Expiry only in an isolated fixture; immutable snapshot mirrors this
        # synthetic attempt. Production code never changes a lease to force expiry.
        job = lit(context['jobId'])
        sql("update machimoa_review.processing_jobs set claim_lease_until=now()-interval '1 second' where id="+job+";update machimoa_review.content_filter_claim_inputs set lease_until=(select claim_lease_until from machimoa_review.processing_jobs where id="+job+") where job_id="+job+" and claimed_at="+lit(context['claimedAt'])+";")
        context['leaseUntil'] = scalar('(select claim_lease_until from machimoa_review.processing_jobs where id='+job+')')
        return context
    def detail(c): return rpc('admin_ai_queue_review_detail', [c['jobId']])
    def cancel_args(c, d=None, request=None):
        d = d or detail(c)
        return [c['jobId'],c['revision'],d['version'],d.get('expiredCancellation',{}).get('attempt','f'*64),request or str(uuid4()),'',ACTOR]
    def snapshot(c):
        sid = lit(c['sourceItemId'])
        return scalar("jsonb_build_array((select to_jsonb(s) from machimoa_review.source_items s where id="+sid+"),(select to_jsonb(f) from machimoa_review.source_item_program_facts f where source_item_id="+sid+"),(select to_jsonb(f) from machimoa_review.source_item_content_filters f where source_item_id="+sid+"),(select coalesce(jsonb_agg(to_jsonb(i)),'[]') from machimoa_review.content_filter_claim_inputs i where source_item_id="+sid+"),(select coalesce(jsonb_agg(to_jsonb(c)),'[]') from machimoa_review.curation_candidates c))")
    c = create(); d = detail(c)
    ok(d['status']=='claimed' and d['review']['editableFields']==[], 'expired claim still blocks old fact editor')
    deny(query('fail_seoul_program_ai',[c['jobId'],c['claimedAt'],c['leaseUntil'],c['workerId'],'ai_schema_error']), 'program_ai_lease_lost')
    deny(query('admin_ai_queue_request_recheck',[c['jobId'],c['revision'],d['version'],str(uuid4()),'',ACTOR]), 'recheck_conflict')
    if args.before_fix:
        assert d.get('expiredCancellation'), 'REGRESSION: no safe expired cancellation/recheck path'
    up = MIGRATION.read_text(encoding='utf8')
    before = snapshot(c)
    deny("begin;alter function public.admin_ai_queue_review_detail(uuid) set search_path='public';"+up, 'seoul_expired_predecessor_changed')
    deny("begin;grant execute on function machimoa_review.ai_recheck_command(uuid,text,text,uuid,text,uuid,text) to service_role;"+up, 'seoul_expired_recheck_changed')
    ok(scalar("to_regclass('machimoa_review.seoul_expired_ai_receipts') is null"), 'failed DDL creates no receipt table')
    sql(up); ok(snapshot(c)==before, 'DDL preserves facts, observations, filters, snapshots, candidates')
    deny(up, 'seoul_expired_predecessor_changed')
    details = [detail(c)]
    a = cancel_args(c); old = scalar('(select to_jsonb(j) from machimoa_review.processing_jobs j where id='+lit(c['jobId'])+')')
    held = rpc('admin_seoul_ai_cancel_expired', a)
    ok(held['status']=='cancelled' and held['recheckPending'] and 'description' in held['review']['editableFields'], 'cancel and full existing fact review open atomically')
    ok(snapshot(c)==before, 'cancellation changes no source/fact/filter/snapshot/candidate')
    ok(rpc('admin_seoul_ai_cancel_expired', a)==held, 'identical receipt confirms once')
    receipt = scalar('(select to_jsonb(r) from machimoa_review.seoul_expired_ai_receipts r where request_id='+lit(a[4])+')')
    ok(receipt['prior_attempt']==old and receipt['actor']==ACTOR and receipt['input'][-1]=='', 'old attempt and optional note audit preserved')
    ok(scalar('(select count(*) from machimoa_review.ai_rechecks where job_id='+lit(c['jobId'])+')')==1, 'one deliberate hold only')
    ok(not held['canRecheck'] and not held['expiredCancellation'], 'cancelled hold never offers another cancellation')
    ok(rpc('claim_seoul_program_ai',[c['sourceItemId'],c['revision'],'synthetic-no-call',300])==[], 'held job cannot run provider')
    for index, value in [(1,'f'*64),(2,'f'*64),(3,'f'*64),(5,'changed'),(6,str(uuid4()))]:
        bad = a.copy(); bad[index]=value
        deny(query('admin_seoul_ai_cancel_expired',bad), 'request_id_conflict')
    for field in ('revision','version','attempt'):
        other = create(); args2 = cancel_args(other); args2[{'revision':1,'version':2,'attempt':3}[field]]='f'*64
        deny(query('admin_seoul_ai_cancel_expired',args2), 'expired_cancel_conflict')
    for scenario in ('active','completed','new_worker','new_claim','missing_snapshot','moved_snapshot','fact_version','filter_version'):
        other=create(); saved=cancel_args(other); job=lit(other['jobId']); sid=lit(other['sourceItemId'])
        if scenario=='active': q="update machimoa_review.processing_jobs set claim_lease_until=now()+interval '5 minutes' where id="+job
        elif scenario=='completed': q="update machimoa_review.processing_jobs set status='completed',completed_at=now() where id="+job
        elif scenario=='new_worker': q="update machimoa_review.processing_jobs set claimed_by='new-worker' where id="+job
        elif scenario=='new_claim': q="update machimoa_review.processing_jobs set claimed_at=now() where id="+job
        elif scenario=='missing_snapshot': q="delete from machimoa_review.content_filter_claim_inputs where job_id="+job
        elif scenario=='moved_snapshot': q="update machimoa_review.content_filter_claim_inputs set data=jsonb_set(data,'{audience,value}', '\"children\"') where job_id="+job
        elif scenario=='fact_version': q="update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id="+sid
        else: q="update machimoa_review.source_item_content_filters set filter_version=filter_version+1 where source_item_id="+sid
        sql(q+';'); deny(query('admin_seoul_ai_cancel_expired',saved), 'expired_cancel_conflict')
    other=create(); saved=cancel_args(other)
    key=scalar('(select external_key from machimoa_review.source_items where id='+lit(other['sourceItemId'])+')')
    sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) values("+','.join(map(lit,['seoul_reservation',key,'e'*64,'synthetic-existing-'+uuid4().hex,'합성 기존 후보','요약','기존 본문',{},'success']))+");")
    unchanged=snapshot(other); deny(query('admin_seoul_ai_cancel_expired',saved), 'expired_cancel_conflict')
    ok(snapshot(other)==unchanged, 'existing older revision candidate preserved')
    other=create(); saved=cancel_args(other); baseline=snapshot(other)
    sql("create function public.synthetic_cancel_audit_failure() returns trigger language plpgsql as $$begin raise exception 'synthetic_cancel_audit_failure';end$$;create trigger synthetic_cancel_audit_failure before insert on machimoa_review.seoul_expired_ai_receipts for each row execute function public.synthetic_cancel_audit_failure();")
    deny(query('admin_seoul_ai_cancel_expired',saved), 'synthetic_cancel_audit_failure')
    ok(detail(other)['status']=='claimed' and not detail(other)['recheckPending'] and snapshot(other)==baseline, 'audit failure rolls entire cancel/review opening back')
    sql('drop trigger synthetic_cancel_audit_failure on machimoa_review.seoul_expired_ai_receipts;drop function public.synthetic_cancel_audit_failure();')
    # Two cancellation requests cannot create two holds or erase the prior fence.
    def race(tasks):
        b=Barrier(len(tasks))
        def call(fn):
            b.wait()
            try:return ('saved',fn())
            except RuntimeError as e:return ('conflict',str(e))
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:return list(pool.map(call,tasks))
    other=create(); saved=cancel_args(other); second=saved.copy();second[4]=str(uuid4())
    outcomes=race([lambda:rpc('admin_seoul_ai_cancel_expired',saved),lambda:rpc('admin_seoul_ai_cancel_expired',second)])
    ok(sorted(x[0] for x in outcomes)==['conflict','saved'], 'concurrent cancel one winner no deadlock')
    other=create(); saved=cancel_args(other)
    outcomes=race([lambda:rpc('admin_seoul_ai_cancel_expired',saved),
                   lambda:rpc('claim_seoul_program_ai',[other['sourceItemId'],other['revision'],'new-racing-worker',300])])
    state=detail(other)
    ok((state['status']=='cancelled' and state['recheckPending']) or
       (state['status']=='claimed' and not state['recheckPending'] and any(x[0]=='conflict' for x in outcomes)), 'reclaim vs cancel binds current source fence')
    def output_for(attempt):
        return {'titleKo':attempt['title'],'titleJa':'合成','summaryKo':'합성 설명','summaryJa':'合成の説明','contentKo':'[한 줄 요약]\n합성\n[주요 내용]\n합성','contentJa':'[要約]\n合成\n[主な内容]\n合成','aiModel':'gpt-6.1-sol'}
    other=create(); saved=cancel_args(other)
    late=[other['jobId'],other['revision'],other['factsVersion'],other['claimedAt'],other['leaseUntil'],other['workerId'],output_for(other)]
    outcomes=race([lambda:rpc('admin_seoul_ai_cancel_expired',saved),lambda:rpc('finish_seoul_program_ai',late)])
    ok(sorted(x[0] for x in outcomes)==['conflict','saved'] and detail(other)['recheckPending'], 'late completion vs expired cancellation protects the same locked source')
    ok(any(x[0]=='conflict' and any(code in x[1] for code in ('program_ai_stale','program_ai_lease_lost','program_ai_unavailable')) for x in outcomes), 'late completion rejects actual fence, not arbitrary output')
    # Existing description save + explicit release, no AI execution. Keep all
    # original lines/conditions and append a unique reviewed note in this fixture.
    new_description=confirmed_case()['facts']['description']  # separately confirmed local table fixture
    saved=rpc('admin_program_save',[c['sourceItemId'],c['revision'],held['review']['version'],{'description':new_description},[],'',ACTOR])
    ok(saved['facts']['description']==new_description and saved['observedFacts']==held['review']['observedFacts'], 'formal description save preserves original observations')
    deny(query('admin_program_save',[c['sourceItemId'],c['revision'],held['review']['version'],{'description':'stale'},[],'',ACTOR]), 'program_version_conflict')
    fresh=detail(c)
    released=rpc('admin_ai_queue_complete_recheck',[c['jobId'],c['revision'],fresh['version'],str(uuid4()),'',ACTOR])
    ok(not released['recheckPending'] and released['status']=='cancelled' and 'topic' in released['review']['filterInfo']['missing'], 'incomplete filter reconfirmation cannot requeue or run AI')
    # Current source-description changes correctly invalidate the prior topic
    # confirmation. Preserve that contract and explicitly confirm the same
    # existing value with the formal versioned filter RPC; never force readiness.
    rpc('admin_content_filter_save',[c['sourceItemId'],c['revision'],released['review']['version'],released['review']['filterInfo']['filterVersion'],{'topic':held['review']['filterInfo']['data']['topic']},ACTOR])
    released=detail(c)
    ok(released['status']=='queued' and not released['recheckPending'], 'explicit current filter confirmation queues reviewed input without AI')
    deny(query('admin_seoul_ai_cancel_expired',a), 'expired_cancel_superseded')
    details.extend([held,fresh,released])
    # Use the real worker + isolated RPC, fake summary/translation only. No keys,
    # provider client or external socket; this is NOT a model-quality test.
    calls=[]; context_seen=[]
    summary=copy.deepcopy(confirmed_case()['summary'])
    assembled=assemble_seoul_body(summary['content_ko'],released['review']['facts'])
    japanese={'title_ja':'合成の解説','content_ja':fake_translation(assembled)}
    client=streamed([response(json.dumps(summary,ensure_ascii=False)),response(json.dumps(japanese,ensure_ascii=False))])
    provider=create_provider_adapter('chatgpt_plan',None,client=client,plan_session=verified_session())
    def summarize(body,url,title):
        calls.append('summary'); context_seen.append(json.loads(body))
        return provider.summarize_program_ko(body,url,title=title)
    def translate(title,body):
        calls.append('translation'); return provider.translate_ja(title,body)
    def transport(name, values):
        if name=='claim_seoul_program_ai':
            result=rpc(name,[values[k] for k in ('p_source_item_id','p_revision','p_worker_id','p_lease_seconds')])
            if result: context_seen.append(result[0])
            return result
        if name=='finish_seoul_program_ai':
            # Candidate completion is a fake RPC only in this local task.
            ok(values['p_claimed_at']!=c['claimedAt'], 'new attempt has a new claimedAt')
            ok(values['p_facts_version']==saved['factsVersion'], 'new attempt binds current facts version')
            return {'outcome':'inserted','candidateId':str(uuid4())}
        raise AssertionError(name)
    try:
        with patch('socket.socket.connect',side_effect=AssertionError('network forbidden')),patch('socket.create_connection',side_effect=AssertionError('network forbidden')),patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')),patch('ingest.chatgpt_plan_auth.authenticate_worker',side_effect=AssertionError('real auth forbidden')):
            result=process_seoul_program_job(ProgramAIAdapter(transport),source_item_id=c['sourceItemId'],revision=c['revision'],worker_id='new-explicit-synthetic-worker',summarize_ko=summarize,translate_ja=translate)
    finally:provider.close()
    ok(result.completed==1 and calls==['summary','translation'], 'new explicit fake worker uses each stage once')
    ok(len(client.calls)==2 and all(request['model']=='gpt-6.1-sol' for request in client.calls), 'fake Pro client and provider/model path used, no fallback')
    ok(context_seen[1]['currentFacts']['description']==new_description, 'new confirmed description reaches actual summary input builder')
    ok(context_seen[1]['weeklyScheduleEvidence']['rows'][0][-2:]==[None,None], 'weekday blank cell positions reach new summary request')
    ok(scalar('(select count(*) from machimoa_review.program_candidate_inputs where job_id='+lit(c['jobId'])+')')==0, 'fake completion created no database candidate')
    # Old late completion must be refused even after a new attempt exists.
    output=output_for(c)
    deny(query('finish_seoul_program_ai',[c['jobId'],c['revision'],c['factsVersion'],c['claimedAt'],c['leaseUntil'],c['workerId'],output]), ['program_ai_stale','program_ai_lease_lost'])
    deny(query('fail_seoul_program_ai',[c['jobId'],c['claimedAt'],c['leaseUntil'],c['workerId'],'ai_schema_error']), 'program_ai_lease_lost')
    for role in ('anon','authenticated','service_role'):
        ok(scalar("has_function_privilege('"+role+"','public.admin_seoul_ai_cancel_expired(uuid,text,text,text,uuid,text,uuid)','execute')")== (role=='service_role'), role+' cancel RPC ACL')
        ok(not scalar("has_function_privilege('"+role+"','machimoa_review.seoul_expired_ai_attempt(uuid,text)','execute')"), role+' private attempt helper')
        ok(not scalar("has_table_privilege('"+role+"','machimoa_review.seoul_expired_ai_receipts','SELECT,INSERT,UPDATE,DELETE')"), role+' no direct receipt access')
    ok(scalar("(select relrowsecurity from pg_class where oid='machimoa_review.seoul_expired_ai_receipts'::regclass)"), 'receipt RLS')
    node=subprocess.run(['node',str(ROOT/'scripts/test_ai_queue_recheck_sql_dto.mjs')],input=json.dumps({'details':details,'queues':[]}).encode(),capture_output=True)
    assert node.returncode==0,node.stderr.decode()
    ok(json.loads(node.stdout)['result']=='passed', 'actual SQL responses pass existing DTO parser')
    print(json.dumps({'database':db,'checks':len(checks),'result':'passed','network':'none','actualAiCalls':0,'sharedDBAccess':False,'cases':checks},ensure_ascii=False))


if __name__=='__main__': main()
