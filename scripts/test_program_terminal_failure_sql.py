"""Real failure receipts on synthetic MySeoul data in a disposable network-none DB."""
import json
from pathlib import Path
from uuid import uuid4

from ingest.connectors.seoul_reservation import normalize_seoul_item
from ingest.program_db import program_rpc_item
from test_myseoul_db import fixtures
from test_seoul_reservation import row
from test_seoul_culture_external_links_sql import CONTAINER, docker, literal
from test_seoul_program_purpose_sql import BASE, GARDEN, MIGRATION as PURPOSE

MIGRATION = Path(__file__).resolve().parents[1] / 'supabase/migrations/20261117102024_program_ai_terminal_failure.sql'


def verify(db):
    def sql(q):
        return docker(['exec','-i',CONTAINER,'psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d',db], q)

    def rpc(name, *args, role='service_role'):
        return sql(f'set role {role};select public.{name}(' + ','.join(map(literal,args)) + ');')

    def reject(call, expected):
        try:
            call()
        except RuntimeError as error:
            assert expected in str(error), str(error)
        else:
            raise AssertionError(expected)

    schema = docker(['exec',CONTAINER,'pg_dump','--schema-only','--schema=public','--schema=machimoa_review',
                     '-U','postgres','-d',BASE])
    sql(schema.replace('CREATE SCHEMA public;', '', 1))
    sql(PURPOSE.read_text(encoding='utf8'))
    sql(MIGRATION.read_text(encoding='utf8'))
    sql(MIGRATION.with_name('20261117114500_program_ai_failure_detail.sql').read_text(encoding='utf8'))
    if sql("select to_regclass('machimoa_review.seoul_ai_correction_drafts') is null")=='t':
        sql(MIGRATION.with_name('20261104004126_seoul_ai_correction.sql').read_text(encoding='utf8'))
    if sql("select to_regclass('machimoa_review.seoul_ai_candidate_reviews') is null")=='t':
        sql(MIGRATION.with_name('20261104031651_seoul_ai_candidate_review.sql').read_text(encoding='utf8'))
    sql(MIGRATION.with_name('20261117114501_program_private_ai_outputs.sql').read_text(encoding='utf8'))
    if sql("select to_regprocedure('machimoa_review.admin_trash_current_item(uuid,text)') is null")=='t':
        sql(MIGRATION.with_name('20261103121330_restore_review_in_one_step.sql').read_text(encoding='utf8'))
    sql(MIGRATION.with_name('20261117130359_ai_queue_waiting_trash.sql').read_text(encoding='utf8'))
    sql(MIGRATION.with_name('20261117132621_ai_queue_period_ended_reason.sql').read_text(encoding='utf8'))
    sql("""insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,
        enabled,permission_status,legacy_curation_source) values
        ('myseoul_program','synthetic','content','rest',true,'approved_noncommercial','myseoul_program');
        insert into machimoa_review.source_sync_state(source_id) values('myseoul_program');""")
    run = sql("select run_id from public.start_ingest_run('myseoul_program',3600);")
    item = fixtures()['fixtures'][0]['item']
    saved, = json.loads(rpc('observe_myseoul_program', run, [item], None))
    sid = saved['id']
    d = json.loads(rpc('admin_myseoul_program_detail', sid))
    rev = d['revision']
    known = lambda v: {'status':'known','value':v}
    filters = {'topic':known('culture_experience'),'delivery':known('onsite'),'audience':known('other'),
               'location':known({'scope':'specific','venues':[{'province':'11','district':'종로구','facility':'','address':''}]})}
    actor = '00000000-0000-4000-8000-000000000001'
    rpc('admin_content_filter_save',sid,rev,d['version'],d['filterInfo']['filterVersion'],filters,actor)
    d = json.loads(rpc('admin_myseoul_program_detail',sid))
    if d.get('activityReview',{}).get('pending'):
        rpc('admin_myseoul_activity_confirm',sid,rev,d['version'],d['filterInfo']['filterVersion'],
            {'location':filters['location']},{},actor)
    claim = 'claim_myseoul_program_ai_no_retry'
    trash_case = Path(__file__).parent / 'fixtures/ai_queue_waiting_trash.sql'
    sql(f'\\set source_id {sid}\n' + trash_case.read_text(encoding='utf8'))
    print('PASS: retry trash, active claim rejection, stale version, idempotency and protected restore')
    reject(lambda:rpc(claim,sid,rev,'test',600,role='authenticated'), 'permission denied')
    c, = json.loads(rpc(claim,sid,rev,'test',600))
    job, at, lease = c['jobId'], c['claimedAt'], c['leaseUntil']
    args = [job,rev,at,lease,'test',c['failurePolicy']['attempt'],'ai_schema_error']
    fail = 'fail_myseoul_ai_no_retry'
    reject(lambda:rpc(fail,*args,role='anon'),'permission denied')
    reject(lambda:rpc(fail,*args[:4],'wrong',*args[5:]),'no_retry_attempt_conflict')
    reject(lambda:rpc('fail_seoul_ai_no_retry',*args),'no_retry_attempt_conflict')
    reject(lambda:rpc('fail_myseoul_program_ai',job,at,lease,'test','ai_schema_error'),'no_retry_policy_required')
    # The snapshot includes operator facts and filter version; a concurrent edit
    # and its failed completion roll back together in this synthetic transaction.
    reject(lambda:sql(f"begin;update machimoa_review.source_item_program_facts set facts_version=facts_version+1 "
                      f"where source_item_id='{sid}';select public.{fail}(" + ','.join(map(literal,args)) + ');'),
           'no_retry_attempt_conflict')
    detail=dict(stage='japanese_validation',code='ai_schema_error',rule='schedule_times',reason='missing',
                location={'field':'content_ja'},expected=[[600,690]],actual=[[600,750]])
    reject(lambda:rpc(fail,*args,detail,role='authenticated'),'permission denied')
    reject(lambda:rpc(fail,*args,dict(detail,actual=['private raw text'])),'invalid_failure_detail')
    finish='finish_program_ai_candidate_review'
    source='myseoul_program'
    output=dict(titleKo=c['title'],titleJa='合成',summaryKo='안내',summaryJa='案内',
                contentKo='오전 10시',contentJa='午前11時',aiModel='fake')
    review={'source':'오전 10시','issues':[{'stage':'japanese_validation','rule':'clock','reason':'mismatch',
            'disposition':'change','field':'contentJa','before':'11時','after':'10時','evidence':'오전 10시'}]}
    finish_args=[source,job,rev,at,lease,'test',c['factsVersion'],output,review]
    reject(lambda:rpc(finish,*finish_args,role='authenticated'),'permission denied')
    reject(lambda:rpc(finish,*finish_args[:6],c['factsVersion']+1,output,review),'stale')
    reject(lambda:rpc(finish,*finish_args[:-2],dict(output,titleJa=''),review),'invalid')
    statement='select public.'+finish+'('+','.join(map(literal,finish_args))+');'
    results=sql("begin; set local role service_role;"+statement+statement+"reset role;"
                "select review_status from machimoa_review.curation_candidates;"
                "select public.admin_seoul_ai_candidate_review(id) from machimoa_review.curation_candidates;rollback;").splitlines()
    assert json.loads(results[0])['outcome']=='inserted' and json.loads(results[1])['outcome']=='duplicate'
    assert results[2]=='pending' and json.loads(results[3])['review']==dict(review,matchesSavedOutput=True)
    draft={'ko':'합성 한국어','ja':'合成本文'}
    save='fail_program_ai_with_draft'
    reject(lambda:rpc(save,source,*args,detail,draft,role='authenticated'),'permission denied')
    reject(lambda:rpc(save,source,*args,detail,{**draft,'token':'forbidden'}),'invalid_failure_draft')
    assert rpc(save,source,*args,detail,draft)==rpc(save,source,*args,detail,draft)=='failed'
    reject(lambda:rpc(save,source,*args,detail,dict(draft,ko='다른 문구')),'failure_draft_conflict')
    reject(lambda:rpc('admin_program_ai_private_draft',job,role='anon'),'permission denied')
    assert json.loads(rpc('admin_program_ai_private_draft',job))['output']==draft
    assert rpc(fail,*args,detail) == rpc(fail,*args,detail) == rpc(fail,*args) == 'failed'
    reject(lambda:rpc(fail,*args,dict(detail,actual=[[5,6]])),'failure_detail_conflict')
    assert json.loads(rpc('admin_ai_queue_review_detail',job))['failureDetail']==detail
    assert sql(f"select status||':'||retry_count||':'||(next_retry_at is null)::text from "
               f"machimoa_review.processing_jobs where id='{job}';") == 'failed:0:true'
    assert json.loads(rpc('admin_ai_queue_review_detail',job))['canRecheck']
    assert json.loads(rpc(claim,sid,rev,'second-worker',600)) == []
    assert sql("select count(*) from machimoa_review.curation_candidates;") == '0'
    # The same shared SQL also serves the legacy-named Seoul no-retry RPCs.
    sql("""insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,
        enabled,permission_status,legacy_curation_source) values
        ('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation');
        insert into machimoa_review.source_sync_state(source_id) values('seoul_reservation');""")
    run = sql("select run_id from public.start_ingest_run('seoul_reservation',3600)")
    packet = program_rpc_item(normalize_seoul_item(row(sid='SYNTH_'+uuid4().hex, SVCNM='합성 정원 해설',
        USETGTINFO='성인', RCPTENDDT='2099-10-30 17:00:00.0', SVCOPNENDDT='2099-11-03 11:30:00.0', DTLCONT=GARDEN)))
    sid = json.loads(rpc('observe_seoul_program_new_only',run,[packet],None))[0]['id']
    d = json.loads(rpc('admin_program_detail',sid))
    rpc('admin_content_filter_save',sid,d['revision'],d['version'],d['filterInfo']['filterVersion'],filters,actor)
    d = json.loads(rpc('admin_program_detail',sid))
    if d.get('activityReview',{}).get('pending'):
        rpc('admin_program_activity_confirm',sid,d['revision'],d['version'],d['factsVersion'],
            d['filterInfo']['filterVersion'],{k:filters[k] for k in ('delivery','location')},'',actor)
    c, = json.loads(rpc('claim_seoul_program_ai_no_retry',sid,d['revision'],'test',600))
    args = [c['jobId'],c['revision'],c['claimedAt'],c['leaseUntil'],'test',c['failurePolicy']['attempt'],'ai_schema_error']
    reject(lambda:rpc(fail,*args),'no_retry_attempt_conflict')
    assert rpc('fail_seoul_ai_no_retry',*args) == 'failed'
    print('PASS: both source receipts, role/source/worker/version guards, legacy retry fenced, idempotent terminal receipt, recheck')


if __name__ == '__main__':
    meta, = json.loads(docker(['inspect',CONTAINER]))
    assert meta['State']['Running'] and meta['HostConfig']['NetworkMode']=='none' and not meta['HostConfig']['PortBindings']
    assert meta['Config']['Labels']['machimoa.purpose']=='saved-count-sql-validation'
    assert all(m['Type']=='volume' and m['Name']==CONTAINER+'-data' for m in meta['Mounts'])
    assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
    db = 'program_terminal_test_'+uuid4().hex
    docker(['exec',CONTAINER,'createdb','-U','postgres',db])
    try:
        verify(db)
    finally:
        docker(['exec',CONTAINER,'dropdb','-U','postgres',db])
