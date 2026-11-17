"""Seoul collection and operator-save regression. Only a schema-only, network-none local DB."""
import json
from pathlib import Path
from uuid import uuid4

from ingest.connectors.seoul_reservation import normalize_seoul_item
from ingest.program_db import program_rpc_item
from test_seoul_reservation import row
from test_seoul_culture_external_links_sql import CONTAINER, docker, literal
from test_seoul_same_period_sql import ACTOR

BASE = 'seoul_same_period_local_5f9f157666b3'
MIGRATION = Path(__file__).resolve().parents[1] / 'supabase/migrations/20261117071728_seoul_program_purpose_from_participation.sql'
TOUR = ('예약자 안내사항\n운영 당일 출발 5분 전 집결지로 도착해주시기 바랍니다.\n'
        '신청 시 신중하게 신청해주세요.\n초등학생 미만은 프로그램에 참여할 수 없습니다.')
GARDEN = ('폐정수장에서 친환경 생태공원으로의 역사와 분기별 생태적 볼거리 이야기\n'
          '대상&인원 : 성인 누구나/ 회차당 최대 15명\n예약방법 : 선착순 예약')
KNOWN = {'status': 'known', 'value': 'culture_experience'}
UNKNOWN = {'status': 'unknown', 'value': None}


def verify(db):
    def sql(query):
        return docker(['exec', '-i', CONTAINER, 'psql', '-XqAt', '-v', 'ON_ERROR_STOP=1',
                       '-U', 'postgres', '-d', db], query)

    def rpc(name, *args):
        return json.loads(sql("begin;set local role service_role;select public." + name +
                              '(' + ','.join(map(literal, args)) + ');commit;'))

    def observe(title, body, *, known, target='성인', **provider):
        packet = program_rpc_item(normalize_seoul_item(row(
            sid='SYNTH_' + uuid4().hex, SVCNM=title, USETGTINFO=target,
            RCPTENDDT='2099-10-30 17:00:00.0', SVCOPNENDDT='2099-11-03 11:30:00.0',
            DTLCONT=body, **provider)))
        # Represent a previously confirmed topic; keep the actual receipt and source excerpt.
        packet['filterFacts']['data']['topic'] = KNOWN if known else UNKNOWN
        if known:
            packet['filterFacts']['evidence']['topic'] = {'sourceField': 'payload.title', 'excerpt': title}
        else:
            packet['filterFacts']['evidence'].pop('topic', None)
        saved, = rpc('observe_seoul_program_new_only', run, [packet], None)
        assert saved['outcome'] == 'new_saved'
        return rpc('admin_program_detail', saved['id'])

    def save_filter(d, topic):
        rpc('admin_content_filter_save', d['id'], d['revision'], d['version'],
            d['filterInfo']['filterVersion'], {'topic': topic}, ACTOR)
        return rpc('admin_program_detail', d['id'])

    sql(docker(['exec', CONTAINER, 'pg_dump', '-U', 'postgres', '-d', BASE, '--schema-only',
                '--schema=public', '--schema=machimoa_review']).replace('CREATE SCHEMA public;', '', 1))
    sql("""insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,
           enabled,permission_status,legacy_curation_source) values
           ('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation');
           insert into machimoa_review.source_sync_state(source_id) values ('seoul_reservation');""")
    run = sql("select run_id from public.start_ingest_run('seoul_reservation',3600);")
    title = '(일) 서울한양도성 스탬프투어 무료해설 정기프로그램'
    before = observe(title, TOUR, known=True, target='제한없음')
    assert before['facts']['content_kind'] == 'unknown'
    sql(MIGRATION.read_text(encoding='utf-8'))
    assert rpc('admin_program_detail', before['id']) == before, 'DDL must not backfill'
    assert sql("""select bool_or(has_function_privilege(r, f, 'execute'))
                  from unnest(array['anon','authenticated','service_role']) r
                  cross join unnest(array['machimoa_review.seoul_personal_program(jsonb,jsonb,text,boolean)',
                    'machimoa_review.content_filter_review_sync(uuid,text)']) f;""") == 'f'
    tour = observe(title, TOUR, known=True, target='제한없음')
    assert tour['observedFacts']['content_kind'] == 'unknown'
    assert tour['facts']['content_kind'] == 'program'
    assert set(tour['result']['reasons']) == set(before['result']['reasons']) - {'program_purpose_unconfirmed'}
    garden = observe('[선유도공원] 이야기정원', GARDEN, known=False)
    assert garden['facts']['content_kind'] == 'unknown'
    linked = save_filter(garden, KNOWN)
    assert linked['facts'] == {**garden['facts'], 'content_kind': 'program'}
    assert linked['observedFacts'] == garden['observedFacts']
    assert linked['factsVersion'] == garden['factsVersion'] + 1
    assert linked['filterInfo']['origins']['topic'] == 'operator'
    try:
        save_filter(garden, KNOWN)
    except RuntimeError as error:
        assert 'conflict' in str(error) or 'changed' in str(error), error
    else:
        raise AssertionError('stale save succeeded')
    assert save_filter(linked, UNKNOWN)['facts']['content_kind'] == 'unknown'
    # All other facts are complete in this synthetic variant. Queue, never claim.
    ready = observe('이야기정원 합성 회차', GARDEN + '\n장소: 서울 도봉구 합성공원',
                    known=False, PLACENM='합성공원', AREANM='도봉구')
    ready = save_filter(ready, KNOWN)
    assert ready['filterInfo']['missing'] == [], ready['filterInfo']['missing']
    assert sql("select status from machimoa_review.processing_jobs where processing_stage='ai_enrichment' and source_item_id="
               + literal(ready['id']) + ";") == 'queued', ready['result']

    for title, body, target, expected in (
        ('문화단체 보조금', '문화단체에 사업비를 지급합니다. 개인 신청 가능', '성인', 'policy_finance'),
        ('지원 공모', '사업내용: 문화단체 보조금 지급\n대상: 성인 누구나', '성인', 'policy_finance'),
        ('지원 공모', '선정된 문화단체에 보조금을 지급합니다.', '성인', 'policy_finance'),
        ('이야기정원', '자세한 사항은 다음 안내를 참고해 주시기 바랍니다.', '제한없음', 'unknown'),
        ('이야기정원', GARDEN + '\n학교만 신청 가능', '성인', 'unknown'),
        ('이야기정원', GARDEN + '\n개인 예약은 불가합니다.', '성인', 'unknown'),
        ('이야기정원', '개인 신청 가능 여부는 운영기관에 문의해 주세요.', '제한없음', 'unknown'),
        ('이야기정원', '프로그램 예약은 개인과 단체 모두 신청 가능합니다.', '제한없음', 'program'),
        ('스탬프투어', '초등학생 미만은 프로그램에 참여할 수 없습니다.', '제한없음', 'unknown'),
    ):
        d = observe(title, body, known=True, target=target)
        assert d['facts']['content_kind'] == expected, (title, d['facts']['content_kind'])

    # Explicit operator decision from an earlier review stays authoritative on later topic edits.
    d = observe('[선유도공원] 이야기정원', GARDEN, known=False)
    chosen = rpc('admin_program_save', d['id'], d['revision'], d['version'],
                 {'content_kind': 'policy_finance'}, '{}', '합성 운영자 판단', ACTOR)
    after = save_filter(chosen, KNOWN)
    assert after['facts']['content_kind'] == 'policy_finance'
    assert after['factsVersion'] == chosen['factsVersion']
    assert after['history'] == chosen['history']
    pending = rpc('admin_program_save', after['id'], after['revision'], after['version'],
                  {'content_kind': 'unknown'}, '{}', '합성 운영자 확인 필요', ACTOR)
    assert pending['facts']['content_kind'] == 'unknown'
    assert save_filter(pending, KNOWN)['facts']['content_kind'] == 'unknown'
    assert sql("select count(*) from machimoa_review.processing_jobs where processing_stage='ai_enrichment' and claimed_at is not null;") == '0'
    assert sql("select count(*) from machimoa_review.curation_candidates;") == '0'
    print('PASS collection, topic save/withdrawal, no backfill, stale save, operator decision, '
          'two grant cases, ambiguous participation, exclusivity, independent review reasons')


if __name__ == '__main__':
    meta, = json.loads(docker(['inspect', CONTAINER]))
    assert meta['State']['Running'] and meta['HostConfig']['NetworkMode'] == 'none'
    assert not meta['HostConfig']['PortBindings'] and not meta['HostConfig']['Binds']
    assert meta['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
    assert all(m['Type'] == 'volume' and m['Name'] == CONTAINER+'-data' for m in meta['Mounts'])
    assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'
    db = 'seoul_personal_program_test_' + uuid4().hex
    docker(['exec', CONTAINER, 'createdb', '-U', 'postgres', db])
    try:
        verify(db)
    finally:
        docker(['exec', CONTAINER, 'dropdb', '-U', 'postgres', db])
