"""Schema-only clone in verified network-none Docker; synthetic rows only."""
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
from test_seoul_content import synthetic_facts
from test_reclassification_ai import context as classification_fixture
from ingest.content_filters import extract_filter_facts
from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job
from ingest.reclassification_ai import process_reclassified_job
from ingest.ai_errors import AiJobError

ROOT = Path(__file__).resolve().parents[1]
C = 'machimoa-saved-count-sql-20261009-56ca9041'
BASE = 'seoul_expired_local_c62a44344692'
MIGRATION = ROOT/'supabase/migrations/20261013102829_seoul_ai_no_retry.sql'
ACTOR = '00000000-0000-4000-8000-000000000001'


def docker(parts, body=None):
    r = subprocess.run(['docker', *parts], input=body.encode() if body else None, capture_output=True)
    if r.returncode: raise RuntimeError(r.stderr.decode('utf8'))
    return r.stdout.decode('utf8').strip()


def lit(value):
    if value is None: return 'NULL'
    if type(value) is int: return str(value)
    return "'"+(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)).replace("'", "''")+"'"


def main():
    m = json.loads(docker(['inspect', C]))[0]
    assert m['State']['Running'] and m['HostConfig']['NetworkMode'] == 'none' and not m['HostConfig']['PortBindings']
    assert m['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
    assert m['Mounts'] and all(x['Type']=='volume' and x['Name']==C+'-data' for x in m['Mounts'])
    assert json.loads(docker(['context', 'inspect']))[0]['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'
    db = 'seoul_no_retry_local_'+uuid4().hex[:12]
    dump = docker(['exec', C, 'pg_dump', '-U', 'postgres', '-d', BASE, '--schema-only', '--schema=public', '--schema=machimoa_review'])
    assert dump.count('CREATE SCHEMA public;') == 1
    docker(['exec', C, 'createdb', '-U', 'postgres', db])
    def sql(q):
        return docker(['exec', '-i', C, 'psql', '-XqAt', '-U', 'postgres', '-d', db, '-v', 'ON_ERROR_STOP=1'],
                      "set statement_timeout='15s';set lock_timeout='5s';"+q)
    sql(dump.replace('CREATE SCHEMA public;', '-- already empty public', 1))
    def scalar(q): return json.loads(sql('select to_jsonb('+q+');') or 'null')
    def command(n, a):
        values=list(map(lit,a))
        if n=='admin_review_ai_queue':values[2]='array['+','.join(map(lit,a[2]))+']::uuid[]'
        return 'begin;set local role service_role;select to_jsonb(public.'+n+'('+','.join(values)+'));commit;'
    def rpc(n, a): return json.loads(sql(command(n, a)))
    checks = []; details=[]; queues=[]
    def ok(value, label): assert value, label; checks.append(label)
    def deny(q, message):
        try: sql(q)
        except RuntimeError as exc: ok(message in str(exc), 'denied '+message)
        else: raise AssertionError('expected '+message)
    for table in ('source_items', 'processing_jobs', 'curation_candidates'):
        ok(scalar('(select count(*) from machimoa_review.'+table+')')==0, 'schema-only '+table)
    sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source) values('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation');insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation');")
    run = scalar("(select run_id from public.start_ingest_run('seoul_reservation',3600))")
    def create(classified=False):
        key = 'SYNTH_NO_RETRY_'+uuid4().hex[:12]
        item = copy.deepcopy(fixtures(storage=True)[0]['item'])
        f = synthetic_facts(); f.update(missing=[], conflicts=[], editorial_pending=[])
        for name in f['periods']:
            day = '2020-01-01' if name.endswith('BGNDT') else '2099-10-15'
            f['periods'][name] = dict(raw=day, value=day, status='ok', precision='day')
        f['official_url'] = 'https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id='+key
        item.update(external_key=key, revision_hash=hashlib.sha256(key.encode()).hexdigest(), program_facts=f)
        item['min_fields']['title'] = '합성 문화 체험'
        item['normalized_payload'].update(title='합성 문화 체험', source_url=f['official_url'], program_text=f['description'])
        item['normalized_payload']['provider_fields'].update(SVCID=key, MAXCLASSNM='문화체험')
        item['filterFacts'] = extract_filter_facts('seoul_reservation', item['normalized_payload'], f)
        sid = rpc('observe_seoul_program_new_only', [run, [item], None])[0]['id']
        if classified:
            d = rpc('admin_review_classification_detail', [sid]); c = classification_fixture('event', 'seoul_reservation')
            c['facts'].update(delivery='offline', scope='unknown', evidence='')
            out = rpc('admin_review_reclassify', [sid, d['revision'], d['version'], d['classificationVersion'], c['facts'], c['filters'], '', ACTOR])
            ok(out['ready'], 'synthetic reclassified event ready')
            return {'sourceItemId': sid, 'revision': d['revision'], 'classificationVersion': out['classificationVersion']}
        d = rpc('admin_program_detail', [sid]); known=lambda v: {'status':'known','value':v}
        filters = {'topic':known('culture_experience'), 'audience':known('other'), 'delivery':known('onsite'),
                   'location':known({'scope':'specific','venues':[{'province':'11','district':'종로구','facility':'','address':''}]})}
        rpc('admin_content_filter_save', [sid, d['revision'], d['version'], d['filterInfo']['filterVersion'], filters, ACTOR])
        return {'sourceItemId':sid, 'revision':d['revision']}
    def claim(target, once=True):
        if 'classificationVersion' in target:
            return rpc('claim_seoul_reclassified_ai_no_retry' if once else 'claim_reclassified_content_ai',
                       [target['sourceItemId'],target['revision'],target['classificationVersion'],'synthetic-one-shot-worker',300])
        return rpc('claim_seoul_program_ai_no_retry' if once else 'claim_seoul_program_ai',
                   [target['sourceItemId'],target['revision'],'synthetic-one-shot-worker',300])[0]
    def fail_args(c):
        return [c[k] for k in ('jobId','revision','claimedAt','leaseUntil','workerId')]+[c['failurePolicy']['attempt'],'ai_schema_error']
    def old_fail(c): return [c[k] for k in ('jobId','claimedAt','leaseUntil','workerId')]+['ai_schema_error']
    def job(c): return scalar('(select to_jsonb(j) from machimoa_review.processing_jobs j where id='+lit(c['jobId'])+')')
    def preserved(c):
        sid=lit(c['sourceItemId'])
        return scalar("jsonb_build_array((select to_jsonb(s) from machimoa_review.source_items s where id="+sid+"),(select to_jsonb(f) from machimoa_review.source_item_program_facts f where source_item_id="+sid+"),(select to_jsonb(f) from machimoa_review.source_item_content_filters f where source_item_id="+sid+"),(select coalesce(jsonb_agg(to_jsonb(c)),'[]') from machimoa_review.review_classifications c where source_item_id="+sid+"),(select coalesce(jsonb_agg(to_jsonb(c)),'[]') from machimoa_review.content_filter_claim_inputs c where source_item_id="+sid+"),(select coalesce(jsonb_agg(to_jsonb(c)),'[]') from machimoa_review.review_classification_claims c where source_item_id="+sid+"),(select coalesce(jsonb_agg(to_jsonb(c)),'[]') from machimoa_review.curation_candidates c))")
    # Reproduce the actual predecessor registration before installing anything.
    legacy=claim(create(), once=False)
    ok(rpc('fail_seoul_program_ai',old_fail(legacy))=='queued', 'before: known failure requeues')
    ok(job(legacy)['retry_count']==1 and job(legacy)['next_retry_at'] is not None, 'before: retry registered for 30 seconds later')
    migration=MIGRATION.read_text(encoding='utf8'); baseline=preserved(legacy); before_job=job(legacy)
    deny("begin;alter function public.claim_seoul_program_ai(uuid,text,text,integer) set search_path='public';"+migration, 'seoul_no_retry_predecessor_changed')
    deny("begin;grant execute on function public.claim_reclassified_content_ai(uuid,text,bigint,text,integer) to authenticated;"+migration, 'seoul_no_retry_predecessor_changed')
    sql(migration)
    ok(preserved(legacy)==baseline and job(legacy)==before_job, 'migration has no content/job backfill')
    print(json.dumps({'database':db,'phase':'migration_and_predecessor_passed'}), flush=True)
    for classified in (False, True):
        target=create(classified); c=claim(target); original=preserved(c); prior=job(c)
        ok(c['failurePolicy']['policy']=='no_retry', 'policy captured atomically')
        deny(command('fail_seoul_program_ai',old_fail(c)), 'no_retry_policy_required')
        ok(rpc('fail_seoul_ai_no_retry',fail_args(c))=='failed', 'formal no-retry failure')
        closed=job(c)
        ok(closed['status']=='failed' and closed['next_retry_at'] is None and closed['retry_count']==prior['retry_count'], 'terminal failure registers no retry')
        ok(all(closed[k] is None for k in ('claimed_at','claimed_by','claim_lease_until')), 'active lock released')
        ok(preserved(c)==original, 'facts, observations, filters, snapshots and candidates preserved')
        receipt=scalar('(select to_jsonb(a) from machimoa_review.seoul_ai_no_retry_attempts a where job_id='+lit(c['jobId'])+' and claimed_at='+lit(c['claimedAt'])+')')
        ok(receipt['input_snapshot']['job']==prior and receipt['closed_at'] and receipt['error_code']=='ai_schema_error', 'prior worker/claim/lease and safe error audit retained')
        ok(rpc('fail_seoul_ai_no_retry',fail_args(c))=='failed' and job(c)==closed, 'same terminal request confirms once')
        changed=fail_args(c);changed[-1]='ai_blocked_cost_cap';deny(command('fail_seoul_ai_no_retry',changed),'no_retry_attempt_superseded')
        # Ordinary queue listing cannot pick a failed attempt.
        queue=rpc('admin_review_ai_queue',[0,25,[]])
        queues.append(queue)
        ok(not any(x['sourceItemId']==c['sourceItemId'] and x['status']=='queued' for x in queue['items']), 'failed attempt never queued')
        if not classified:
            ok(rpc('claim_seoul_program_ai',[target['sourceItemId'],target['revision'],'not-explicitly-released',300])==[], 'normal worker cannot reclaim failed attempt')
        # Existing explicit recheck/release reuses the job; no provider call.
        d=rpc('admin_ai_queue_review_detail',[c['jobId']])
        details.append(d)
        ok(d['canRecheck'], 'failed attempt can enter existing recheck')
        held=rpc('admin_ai_queue_request_recheck',[c['jobId'],c['revision'],d['version'],str(uuid4()),'',ACTOR])
        details.append(held)
        ok(held['recheckPending'] and held['status']=='cancelled', 'existing explicit review hold')
        released=rpc('admin_ai_queue_complete_recheck',[c['jobId'],c['revision'],held['version'],str(uuid4()),'',ACTOR])
        details.append(released)
        ok(not released['recheckPending'] and released['status']=='queued', 'formal release queues without AI')
        newer=claim(target)
        ok(newer['jobId']==c['jobId'] and newer['claimedAt']!=c['claimedAt'] and newer['failurePolicy']['attempt']!=c['failurePolicy']['attempt'], 'explicit next attempt reuses job with new fence')
        deny(command('fail_seoul_ai_no_retry',fail_args(c)), 'no_retry_attempt_superseded')
        ok(scalar('(select count(*) from machimoa_review.seoul_ai_no_retry_attempts where job_id='+lit(c['jobId'])+')')==2, 'previous attempt history retained')
    # Ordinary callers retain their previous retry rules.
    normal=claim(create(), once=False)
    ok(rpc('fail_seoul_program_ai',old_fail(normal))=='queued' and job(normal)['retry_count']==1, 'default retry remains unchanged')
    ok(not rpc('admin_ai_queue_review_detail',[normal['jobId']])['canRecheck'], 'legacy retry registration does not gain new recheck capability')
    # A previously registered retry can be explicitly changed to one-shot on a
    # NEW claim. Keep its historical counter rather than resetting or forcing 3.
    sql('update machimoa_review.processing_jobs set next_retry_at=now()-interval \'1 second\' where id='+lit(normal['jobId'])+';')
    once=claim({'sourceItemId':normal['sourceItemId'],'revision':normal['revision']})
    rpc('fail_seoul_ai_no_retry',fail_args(once))
    ok(job(once)['retry_count']==1 and job(once)['next_retry_at'] is None and rpc('admin_ai_queue_review_detail',[once['jobId']])['canRecheck'], 'prior retry count preserved and explicit terminal attempt can recheck')
    for mutation in ('revision','facts_version','filter_version','snapshot','worker','claim','lease','completed'):
        c=claim(create()); j=lit(c['jobId']);sid=lit(c['sourceItemId'])
        q={'revision':"update machimoa_review.source_items set revision_hash='"+'e'*64+"' where id="+sid,
           'facts_version':'update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id='+sid,
           'filter_version':'update machimoa_review.source_item_content_filters set filter_version=filter_version+1 where source_item_id='+sid,
           'snapshot':"update machimoa_review.content_filter_claim_inputs set worker_id='other' where job_id="+j,
           'worker':"update machimoa_review.processing_jobs set claimed_by='new-worker' where id="+j,
           'claim':'update machimoa_review.processing_jobs set claimed_at=clock_timestamp() where id='+j,
           'lease':"update machimoa_review.processing_jobs set claim_lease_until=now()-interval '1 second' where id="+j,
           'completed':"update machimoa_review.processing_jobs set status='completed',completed_at=now() where id="+j}[mutation]
        sql(q+';'); deny(command('fail_seoul_ai_no_retry',fail_args(c)), 'no_retry_attempt_conflict')
    for index, value in ((1,'e'*64),(4,'other-worker'),(5,'e'*64),(6,'ai_network')):
        c=claim(create()); a=fail_args(c);a[index]=value
        deny(command('fail_seoul_ai_no_retry',a), 'no_retry_invalid' if index==6 else 'no_retry_attempt_conflict')
    c=claim(create(), once=False);c['failurePolicy']={'attempt':'e'*64}
    deny(command('fail_seoul_ai_no_retry',fail_args(c)), 'no_retry_attempt_conflict')
    # Candidate presence blocks termination even from a different source revision.
    c=claim(create());key=scalar('(select external_key from machimoa_review.source_items where id='+lit(c['sourceItemId'])+')')
    sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) values("+','.join(map(lit,['seoul_reservation',key,'e'*64,'synthetic-existing-'+uuid4().hex,'합성 기존 후보','요약','본문',{},'success']))+");")
    before=preserved(c);deny(command('fail_seoul_ai_no_retry',fail_args(c)), 'no_retry_attempt_conflict');ok(preserved(c)==before,'existing candidate preserved')
    # Real SQL races, source lock selects one winner.
    def race(tasks):
        barrier=Barrier(len(tasks))
        def call(fn):
            barrier.wait()
            try:return ('saved',fn())
            except RuntimeError as exc:return ('conflict',str(exc))
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:return list(pool.map(call,tasks))
    c=claim(create());a=fail_args(c)
    r=race([lambda:rpc('fail_seoul_ai_no_retry',a),lambda:rpc('fail_seoul_ai_no_retry',a)])
    ok(all(x==('saved','failed') for x in r), 'concurrent identical termination commits once')
    ok(scalar('(select count(*) from machimoa_review.seoul_ai_no_retry_attempts where job_id='+lit(c['jobId'])+' and closed_at is not null)')==1,'one termination receipt')
    c=claim(create())
    r=race([lambda:rpc('fail_seoul_ai_no_retry',fail_args(c)),lambda:rpc('fail_seoul_program_ai',old_fail(c))])
    ok(sorted(x[0] for x in r)==['conflict','saved'] and job(c)['status']=='failed' and job(c)['retry_count']==0 and job(c)['next_retry_at'] is None, 'terminal vs legacy retry cannot change captured policy')
    c=claim(create())
    output={'titleKo':c['title'],'titleJa':'合成','summaryKo':'합성','summaryJa':'合成','contentKo':'합성 본문','contentJa':'合成本文','aiModel':'fake-pro-model'}
    finish=[c[k] for k in ('jobId','revision','factsVersion','claimedAt','leaseUntil','workerId')]+[output]
    r=race([lambda:rpc('fail_seoul_ai_no_retry',fail_args(c)),lambda:rpc('finish_seoul_program_ai',finish)])
    ok(sorted(x[0] for x in r)==['conflict','saved'] and job(c)['status'] in ('failed','completed'), 'completion vs failure one winner no deadlock')
    # Expired one-shot attempts retain the existing explicit cancellation path.
    c=claim(create());j=lit(c['jobId'])
    sql("update machimoa_review.processing_jobs set claim_lease_until=now()-interval '1 second' where id="+j+";update machimoa_review.content_filter_claim_inputs set lease_until=(select claim_lease_until from machimoa_review.processing_jobs where id="+j+") where job_id="+j+";")
    d=rpc('admin_ai_queue_review_detail',[c['jobId']]);ok(d['expiredCancellation'] is not None,'expired attempt still cancellable')
    held=rpc('admin_seoul_ai_cancel_expired',[c['jobId'],c['revision'],d['version'],d['expiredCancellation']['attempt'],str(uuid4()),'',ACTOR])
    ok(held['status']=='cancelled' and held['recheckPending'] and 'description' in held['review']['editableFields'], 'existing expiry/recheck/description editor preserved')
    # Actual worker + actual isolated SQL failure, no real provider or network.
    for classified in (False,True):
        target=create(classified);calls=[]
        def transport(n,a):
            if n=='claim_seoul_program_ai_no_retry':return rpc(n,[a[k] for k in ('p_source_item_id','p_revision','p_worker_id','p_lease_seconds')])
            if n=='claim_seoul_reclassified_ai_no_retry':return rpc(n,[a[k] for k in ('p_id','p_revision','p_classification_version','p_worker_id','p_lease_seconds')])
            if n=='fail_seoul_ai_no_retry':return rpc(n,[a[k] for k in ('p_job_id','p_revision','p_claimed_at','p_lease_until','p_worker_id','p_attempt','p_error_code')])
            raise AssertionError(n)
        def fake_pro(*a,**k):calls.append('summary');raise AiJobError('ai_schema_error')
        kwargs=dict(source_item_id=target['sourceItemId'],revision=target['revision'],worker_id='synthetic-sql-worker',summarize_ko=fake_pro,translate_ja=fake_pro,no_retry=True)
        with patch('socket.socket.connect',side_effect=AssertionError('network forbidden')),patch('socket.getaddrinfo',side_effect=AssertionError('network forbidden')):
            result=process_reclassified_job(ProgramAIAdapter(transport),classification_version=target['classificationVersion'],**kwargs) if classified else process_seoul_program_job(ProgramAIAdapter(transport),**kwargs)
        ok(result.failed==1 and not result.retried and not result.state_unknown and calls==['summary'],'actual worker and isolated SQL terminate once')
    for role in ('anon','authenticated','service_role'):
        for signature in ('claim_seoul_program_ai_no_retry(uuid,text,text,integer)','claim_seoul_reclassified_ai_no_retry(uuid,text,bigint,text,integer)','fail_seoul_ai_no_retry(uuid,text,timestamptz,timestamptz,text,text,text)'):
            ok(scalar("has_function_privilege('"+role+"','public."+signature+"','execute')")== (role=='service_role'),role+' RPC ACL '+signature)
        for signature in ('seoul_ai_no_retry_snapshot(uuid)','seoul_ai_no_retry_record(jsonb)','seoul_no_retry_base_fail(uuid,timestamptz,timestamptz,text,text)','seoul_no_retry_base_detail(uuid)'):
            ok(not scalar("has_function_privilege('"+role+"','machimoa_review."+signature+"','execute')"), role+' private helper denied')
        ok(not scalar("has_table_privilege('"+role+"','machimoa_review.seoul_ai_no_retry_attempts','SELECT,INSERT,UPDATE,DELETE')"),role+' private attempt table denied')
    ok(scalar("(select relrowsecurity from pg_class where oid='machimoa_review.seoul_ai_no_retry_attempts'::regclass)"),'attempt RLS enabled')
    node=subprocess.run(['node',str(ROOT/'scripts/test_ai_queue_recheck_sql_dto.mjs')],input=json.dumps({'details':details,'queues':queues}).encode(),capture_output=True)
    assert node.returncode==0,node.stderr.decode('utf8')
    ok(json.loads(node.stdout)['result']=='passed','actual SQL responses pass server and browser DTO')
    print(json.dumps({'database':db,'checks':len(checks),'result':'passed','network':'none','actualAiCalls':0,'sharedDBAccess':False,'cases':checks},ensure_ascii=False))


if __name__=='__main__': main()
