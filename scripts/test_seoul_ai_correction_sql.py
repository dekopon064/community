"""Exercise the correction transaction against a network-isolated schema clone."""
import copy
import hashlib
import json
from uuid import uuid4

from test_seoul_ai_no_retry_sql import C, ROOT, ACTOR, docker, lit, fixtures, synthetic_facts, extract_filter_facts, classification_fixture


def main():
    m = json.loads(docker(['inspect', C]))[0]
    assert m['State']['Running'] and m['HostConfig']['NetworkMode'] == 'none' and not m['HostConfig']['PortBindings']
    assert m['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
    assert json.loads(docker(['context', 'inspect']))[0]['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'
    db = 'seoul_correction_local_' + uuid4().hex[:12]
    dump = docker(['exec', C, 'pg_dump', '-U', 'postgres', '-d', 'seoul_no_retry_local_3ee168a1a37e',
                   '--schema-only', '--schema=public', '--schema=machimoa_review'])
    assert dump.count('CREATE SCHEMA public;') == 1
    docker(['exec', C, 'createdb', '-U', 'postgres', db])
    try:
        exercise(db, dump)
    finally:
        docker(['exec', C, 'dropdb', '-U', 'postgres', db])


def exercise(db, dump):
    def sql(q):
        return docker(['exec', '-i', C, 'psql', '-XqAt', '-U', 'postgres', '-d', db, '-v', 'ON_ERROR_STOP=1'],
                      "set statement_timeout='15s';set lock_timeout='5s';"+q)
    def scalar(q): return json.loads(sql('select to_jsonb('+q+');') or 'null')
    def command(name, args, role='service_role'):
        return 'begin;set local role '+role+';select to_jsonb(public.'+name+'('+','.join(map(lit,args))+'));commit;'
    def rpc(name, args):
        return json.loads(sql(command(name,args)) or 'null')
    def deny(q, message):
        try:
            sql(q)
        except RuntimeError as exc:
            assert message in str(exc), str(exc)
        else:
            raise AssertionError(message)
    sql(dump.replace('CREATE SCHEMA public;', '-- already empty public', 1))
    assert scalar('(select count(*) from machimoa_review.source_items)') == 0
    sql((ROOT/'supabase/migrations/20261104004126_seoul_ai_correction.sql').read_text(encoding='utf-8-sig'))
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
            d = rpc('admin_review_classification_detail', [sid])
            c = classification_fixture('event', 'seoul_reservation')
            c['facts'].update(delivery='offline', scope='unknown', evidence='')
            out = rpc('admin_review_reclassify', [sid, d['revision'], d['version'], d['classificationVersion'],
                      c['facts'], c['filters'], '', ACTOR])
            assert out['ready']
            return {'sourceItemId': sid, 'revision': d['revision'], 'classificationVersion': out['classificationVersion']}
        d = rpc('admin_program_detail', [sid]); known=lambda v: {'status':'known','value':v}
        filters = {'topic':known('culture_experience'), 'audience':known('other'), 'delivery':known('onsite'),
                   'location':known({'scope':'specific','venues':[{'province':'11','district':'종로구','facility':'','address':''}]})}
        rpc('admin_content_filter_save', [sid, d['revision'], d['version'], d['filterInfo']['filterVersion'], filters, ACTOR])
        return {'sourceItemId':sid, 'revision':d['revision']}
    def claim(target):
        if 'classificationVersion' in target:
            return rpc('claim_seoul_reclassified_ai_no_retry', [target['sourceItemId'],target['revision'],
                        target['classificationVersion'],'synthetic-one-shot-worker',300])
        return rpc('claim_seoul_program_ai_no_retry',
                   [target['sourceItemId'],target['revision'],'synthetic-one-shot-worker',300])[0]
    def fail_args(c):
        return [c[k] for k in ('jobId','revision','claimedAt','leaseUntil','workerId')]+[c['failurePolicy']['attempt'],'ai_schema_error']

    def open_draft(classified=False):
        c = claim(create(classified))
        args = fail_args(c)
        ko = '가나다'
        draft = {'ko': ko, 'koFacts': {}, 'jaTitle': '合成体験', 'ja': '集合場所は3番出口です。', 'model': 'gpt-test'}
        failed_args = [*args, draft, 'translation', {'rule':'quantity','reason':'mismatch'}]
        assert rpc('fail_seoul_ai_with_draft',failed_args) == 'failed'
        assert rpc('fail_seoul_ai_with_draft',failed_args) == 'failed'
        d = rpc('admin_seoul_ai_draft',[c['jobId']])
        assert d['output']['ko'] == ko and not d['requested'] and 'koFacts' not in d['output']
        evidence = c['title']
        request = [d['id'],c['jobId'],ACTOR,'ja','3番出口',evidence,'합성']
        return c,d,request
    c,d,request = open_draft()
    deny(command('admin_seoul_ai_draft',[c['jobId']],'authenticated'),'permission denied')
    deny(command('admin_seoul_ai_correction_evidence',[d['id']],'anon'),'permission denied')
    deny('set role service_role; select * from machimoa_review.seoul_ai_correction_drafts;', 'permission denied')
    deny(command('admin_review_publish',[d['id'],c['revision'],'a'*64,ACTOR]),'not_found')
    wrong=request.copy(); wrong[5]='다른 합성 원문'
    deny(command('admin_request_seoul_ai_correction',wrong),'correction_evidence_or_excerpt_missing')
    assert rpc('admin_request_seoul_ai_correction',request)['requested']
    deny(command('admin_request_seoul_ai_correction',request),'correction_already_requested')
    assert rpc('claim_seoul_ai_correction',[d['id'],'fake-correction'])['field']=='ja'
    assert rpc('claim_seoul_ai_correction',[d['id'],'fake-correction']) is None
    wrong_candidate={'titleJa':'合成体験','contentJa':'무관한 수정'}
    deny(command('complete_seoul_ai_correction',[d['id'],'fake-correction','합성出口',wrong_candidate,'validated']),'correction_candidate_scope')
    assert rpc('complete_seoul_ai_correction',[d['id'],'fake-correction','합성出口',None,'validation_failed'])=='validation_failed'
    assert not rpc('admin_seoul_ai_draft',[c['jobId']])['candidateId']
    c,d,request = open_draft()
    assert rpc('admin_request_seoul_ai_correction',request)['requested']
    assert rpc('claim_seoul_ai_correction',[d['id'],'fake-correction'])
    sql('update machimoa_review.source_item_program_facts set facts_version=facts_version+1 where source_item_id='+lit(c['sourceItemId'])+';')
    deny(command('complete_seoul_ai_correction',[d['id'],'fake-correction',None,None,'invalid_suggestion']),'program_ai_stale')

    for classified in (False, True):
        c,d,request = open_draft(classified)
        assert rpc('admin_request_seoul_ai_correction',request)['requested']
        assert rpc('claim_seoul_ai_correction',[d['id'],'fake-correction'])
        candidate=dict(titleKo=c['title'],contentKo='합성 본문',summaryKo='합성 요약',titleJa='合成体験',
                       contentJa='集合場所は합성出口です。',summaryJa='合成要約',aiModel='gpt-test')
        assert rpc('complete_seoul_ai_correction',[d['id'],'fake-correction','합성出口',candidate,'validated'])=='validated'
        stored=rpc('admin_seoul_ai_draft',[c['jobId']])
        proof=rpc('admin_seoul_ai_correction_evidence',[stored['candidateId']])
        assert proof['before']=='3番出口' and proof['after']=='합성出口' and proof['evidence']==c['title']
        assert scalar("(select review_status from machimoa_review.curation_candidates where id="+lit(stored['candidateId'])+")")=='pending'
        assert scalar("(select count(*) from machimoa_review.seoul_ai_no_retry_attempts where job_id="+lit(c['jobId'])+" and closed_at is not null)")==1
    print('correction SQL passed: atomic draft, access, approval block, scope, dedup, stale facts, pending candidate and evidence')


if __name__ == '__main__':
    main()
