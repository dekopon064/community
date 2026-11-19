"""Exercise the real fact/filter RPCs with synthetic rows in network-none PostgreSQL."""
import json
from pathlib import Path
from uuid import uuid4

from ingest.connectors.seoul_reservation import normalize_seoul_item
from ingest.program_db import program_rpc_item
from test_reclassification_ai import context
from test_seoul_program_purpose_sql import ACTOR, BASE, CONTAINER, KNOWN, UNKNOWN, docker, literal
from test_seoul_program_purpose_sql import MIGRATION as PURPOSE_MIGRATION
from test_seoul_reservation import row


MIGRATION = (Path(__file__).resolve().parents[1] /
             'supabase/migrations/20261119095825_seoul_preserve_confirmed_program_topic.sql')
BODY = ('<p>화요일 판소리 클래스</p><p>전통 발성을 통해 판소리를 배워보아요!</p>'
        '<p>중학생 이상</p><p>수강생 20명 / 대기자 5명</p>'
        '<p>중복 예약 방지를 위해 한 ID당 각 회차는 1회만 예약 할 수 있습니다.</p>')


def verify(db):
    def sql(query):
        return docker(['exec', '-i', CONTAINER, 'psql', '-XqAt', '-v', 'ON_ERROR_STOP=1',
                       '-U', 'postgres', '-d', db], "set statement_timeout='20s';\n" + query)

    def rpc(name, *args):
        command = 'select public.' + name + '(' + ','.join(map(literal, args)) + ');'
        return json.loads(sql('begin;set local role service_role;' + command + 'commit;'))

    def detail(source_id):
        return rpc('admin_program_detail', source_id)

    def save(d, patch):
        return rpc('admin_program_save', d['id'], d['revision'], d['version'],
                   patch, '{}', '', ACTOR)

    def topic(d):
        return d['filterInfo']['data']['topic']

    def observe():
        packet = program_rpc_item(normalize_seoul_item(row(
            sid='SYNTH_' + uuid4().hex, SVCNM='[합성 아뜰리에 교육] 판소리',
            MINCLASSNM='교육체험', USETGTINFO='성인, 청소년', SVCSTATNM='안내중', DTLCONT=BODY,
            PLACENM='석촌호수 아뜰리에', AREANM='송파구',
            RCPTBGNDT='2099-11-20 11:00:00.0', RCPTENDDT='2099-12-29 11:00:00.0',
            SVCOPNBGNDT='2099-12-01 00:00:00.0', SVCOPNENDDT='2099-12-29 00:00:00.0')))
        packet['filterFacts']['data']['topic'] = UNKNOWN
        packet['filterFacts']['evidence'].pop('topic', None)
        saved, = rpc('observe_seoul_program_new_only', run, [packet], None)
        assert saved['outcome'] == 'new_saved'
        d = detail(saved['id'])
        assert d['facts']['content_kind'] == 'unknown'
        assert 'program_purpose_unconfirmed' in d['result']['reasons']
        filters = {
            'topic': KNOWN,
            'delivery': {'status': 'known', 'value': 'onsite'},
            'location': {'status': 'known', 'value': {'scope': 'specific', 'venues': [
                {'province': '11', 'district': '송파구', 'facility': '석촌호수 아뜰리에', 'address': ''},
            ]}},
        }
        rpc('admin_content_filter_save', d['id'], d['revision'], d['version'],
            d['filterInfo']['filterVersion'], filters, ACTOR)
        saved = detail(d['id'])
        assert topic(saved) == KNOWN
        assert saved['facts']['content_kind'] == 'unknown'
        assert saved['filterInfo']['origins']['topic'] == 'operator'
        assert saved['filterInfo']['data']['category'] == 'program'
        return saved

    dump = docker(['exec', CONTAINER, 'pg_dump', '-U', 'postgres', '-d', BASE, '--schema-only',
                   '--schema=public', '--schema=machimoa_review'])
    assert dump.count('CREATE SCHEMA public;') == 1
    sql(dump.replace('CREATE SCHEMA public;', '', 1))
    for object_name, migration in (
        ('seoul_ai_correction_drafts', '20261104004126_seoul_ai_correction.sql'),
        ('seoul_ai_candidate_reviews', '20261104031651_seoul_ai_candidate_review.sql'),
    ):
        if sql("select to_regclass('machimoa_review." + object_name + "') is null;") == 't':
            sql(MIGRATION.with_name(migration).read_text(encoding='utf-8'))
    if sql("select to_regprocedure('machimoa_review.admin_trash_current_item(uuid,text)') is null;") == 't':
        sql(MIGRATION.with_name('20261103121330_restore_review_in_one_step.sql').read_text(encoding='utf-8'))
    for path in sorted(MIGRATION.parent.glob('*.sql')):
        if PURPOSE_MIGRATION.name <= path.name < MIGRATION.name:
            sql(path.read_text(encoding='utf-8'))
    sql("""insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,
           enabled,permission_status,legacy_curation_source) values
           ('seoul_reservation','synthetic','content','rest',true,'approved_noncommercial','seoul_reservation');
           insert into machimoa_review.source_sync_state(source_id) values ('seoul_reservation');""")
    run = sql("select run_id from public.start_ingest_run('seoul_reservation',3600);")

    before = observe()
    old = save(before, {'content_kind': 'program'})
    assert topic(old) == UNKNOWN and 'topic' in old['filterInfo']['missing']
    assert old['facts']['description'] == before['facts']['description']
    print('PASS reproduced before the migration: confirming purpose resets the saved topic')

    d = observe()
    sql(MIGRATION.read_text(encoding='utf-8'))
    assert detail(d['id']) == d, 'migration unexpectedly changed existing row'
    fixed = save(d, {'content_kind': 'program'})
    assert fixed['revision'] == d['revision']
    assert fixed['factsVersion'] == d['factsVersion'] + 1 and fixed['version'] != d['version']
    assert fixed['facts'] == {**d['facts'], 'content_kind': 'program'}
    assert fixed['filterInfo']['data'] == d['filterInfo']['data']
    assert fixed['filterInfo']['filterVersion'] == d['filterInfo']['filterVersion'] + 1
    assert fixed['filterInfo']['origins']['topic'] == 'operator'
    assert 'topic' not in fixed['filterInfo']['missing']
    assert fixed['result'] == old['result'], (old['result'], fixed['result'])
    assert 'application_not_started' in fixed['result']['reasons'], fixed['result']
    try:
        save(d, {'content_kind': 'program'})
    except RuntimeError as error:
        assert 'program_version_conflict' in str(error), error
    else:
        raise AssertionError('stale fact save succeeded')
    print('PASS purpose-only confirmation preserves the operator topic, versions and reception gate')

    desc = observe()
    changed = save(desc, {'content_kind': 'program',
                          'description': '직접 방문하는 지역 주민 대상 스마트폰 안전 교육을 진행합니다.'})
    assert topic(changed) == UNKNOWN and 'topic' in changed['filterInfo']['missing']
    assert changed['filterInfo']['origins']['topic'] == 'source_change'
    print('PASS a materially changed description still requires topic review')

    different = observe()
    policy = save(different, {'content_kind': 'policy_finance'})
    assert topic(policy) == UNKNOWN
    assert policy['facts']['description'] == different['facts']['description']
    print('PASS confirmation as a different purpose still invalidates the topic')

    d = observe()
    cl = rpc('admin_review_classification_detail', d['id'])
    event = context('event', 'seoul_reservation')
    event['facts'].update(delivery='offline', scope='unknown', evidence='')
    moved = rpc('admin_review_reclassify', d['id'], cl['revision'], cl['version'],
                cl['classificationVersion'], event['facts'], event['filters'],
                '합성 데이터의 프로그램과 행사 카테고리 전환 검증', ACTOR)
    assert moved['category'] == 'event' and moved['filters']['topic']['value'] == 'festival_exchange'
    assert moved['filters']['topic'] != topic(d)
    print('PASS an actual category change requires the event topic instead of keeping the program topic')

    assert sql("""select bool_or(has_function_privilege(r,
              'machimoa_review.content_filter_after_facts(uuid,text)','execute'))
              from unnest(array['anon','authenticated','service_role']) r;""") == 'f'
    assert sql("select count(*) from machimoa_review.processing_jobs where claimed_at is not null;") == '0'
    assert sql("select count(*) from machimoa_review.curation_candidates;") == '0'
    print('PASS private function permissions, no stored-data migration, no AI claims or candidates')


if __name__ == '__main__':
    meta, = json.loads(docker(['inspect', CONTAINER]))
    assert meta['State']['Running'] and meta['HostConfig']['NetworkMode'] == 'none'
    assert not meta['HostConfig']['PortBindings'] and not meta['HostConfig']['Binds']
    assert meta['Config']['Labels']['machimoa.purpose'] == 'saved-count-sql-validation'
    assert meta['Mounts'] and all(m['Type'] == 'volume' and m['Name'] == CONTAINER + '-data'
                                  for m in meta['Mounts'])
    assert json.loads(docker(['context', 'inspect']))[0]['Endpoints']['docker']['Host'] == (
        'npipe:////./pipe/dockerDesktopLinuxEngine')
    db = 'seoul_preserve_topic_test_' + uuid4().hex
    docker(['exec', CONTAINER, 'createdb', '-U', 'postgres', db])
    try:
        verify(db)
    finally:
        docker(['exec', CONTAINER, 'dropdb', '-U', 'postgres', db])
