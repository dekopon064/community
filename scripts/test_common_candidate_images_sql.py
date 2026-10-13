"""Image RPC/projection checks in an existing network-none synthetic PostgreSQL.

Prepare the predecessor with test_review_reclassification_sql.py --setup-only.
No credentials, provider, source HTTP or production DB access. Publication cases
exercise the isolated projection trigger, not a production approval action.
"""
import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--container', default='machimoa-program-ai-5689d361')
parser.add_argument('--database', required=True)
args = parser.parse_args()
assert args.database.startswith('review_reclass_') and args.database.replace('_', '').isalnum()

def docker(parts, body=None):
    p = subprocess.run(['docker', *parts], input=body.encode() if body else None, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.decode('utf-8').strip())
    return p.stdout.decode('utf-8').strip()

resource = json.loads(docker(['inspect', args.container]))[0]
assert resource['State']['Running'] and resource['HostConfig']['NetworkMode'] == 'none'
assert not resource['HostConfig'].get('PortBindings') and not resource['Mounts']
assert resource['Config']['Labels'].get('machimoa.purpose') == 'isolated-program-ai-concurrency'
context = json.loads(docker(['context', 'inspect']))[0]
assert context['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'

def sql(body):
    return docker(['exec', '-i', args.container, 'psql', '-XqAt', '-U', 'postgres', '-d', args.database,
                   '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=verbose'], body)

def lit(v):
    if v is None:
        return 'NULL'
    if not isinstance(v, str):
        v = json.dumps(v, ensure_ascii=False)
    return "'" + v.replace("'", "''") + "'"

def scalar(expression):
    return json.loads(sql('select to_jsonb(' + expression + ');') or 'null')

def rpc(name, values):
    return json.loads(sql('begin;set local role service_role;select to_jsonb(public.' + name +
                         '(' + ','.join(map(lit, values)) + '));commit;'))

checks = 0

def equal(actual, expected):
    global checks
    assert actual == expected, (actual, expected)
    checks += 1

def reject(body, message):
    global checks
    try:
        sql(body)
    except RuntimeError as e:
        assert message in str(e), str(e)
        checks += 1
    else:
        raise AssertionError('Expected rejection: ' + message)

def fingerprint():
    return scalar("(select md5(coalesce(jsonb_agg(to_jsonb(t) order by id)::text,'')) from machimoa_review.curation_candidates t)")

before = fingerprint()
for filename, marker, error in [
    ('20261013003454_seoul_candidate_images.sql', 'seoul_images_base_admin_review_item(text,uuid)', 'candidate_image_contract_changed'),
    ('20261013012432_common_candidate_images.sql', 'common_images_base_admin_review_item(text,uuid)', 'common_candidate_images_prerequisite_missing')]:
    migration = (ROOT / 'supabase/migrations' / filename).read_text(encoding='utf-8')
    if not scalar('to_regprocedure(' + lit('machimoa_review.' + marker) + ') is not null'):
        sql(migration)
    equal(fingerprint(), before)
    reject(migration, error)
    equal(fingerprint(), before)

common = 'public.admin_review_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid)'
for role in ['anon', 'authenticated']:
    equal(scalar('has_function_privilege(' + lit(role) + ',' + lit(common) + ",'execute')"), False)
    equal(scalar('has_table_privilege(' + lit(role) + ",'machimoa_review.curation_candidates','update')"), False)
equal(scalar("has_function_privilege('service_role'," + lit(common) + ",'execute')"), True)
equal(scalar("has_function_privilege('service_role','machimoa_review.candidate_source_image_url(uuid)','execute')"), False)
equal(scalar("to_regprocedure('public.admin_myseoul_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid)') is not null"), True)

# Future workflow onboarding is a fixture-only core registration. Image functions
# remain unchanged, demonstrating that they have no separate source allowlist.
if not scalar("to_regprocedure('machimoa_review.synthetic_base_canonical_source_id(text)') is not null"):
    sql("alter function machimoa_review.canonical_source_id(text) rename to synthetic_base_canonical_source_id;"
    "create function machimoa_review.canonical_source_id(text) returns text language sql immutable set search_path='' as $$"
        "select case when $1='synthetic_future' then $1 else machimoa_review.synthetic_base_canonical_source_id($1) end$$;")
sql("insert into machimoa_review.ingest_sources(source_id,provider,source_kind,connector_type,legacy_curation_source) "
    "select 'synthetic_future',provider,source_kind,connector_type,'synthetic_future' from machimoa_review.ingest_sources where source_id='youthcenter_content' on conflict(source_id) do nothing;")

ACTOR = '00000000-0000-4000-8000-000000000001'
REV = 'a' * 64
detail = lambda cid: rpc('admin_review_detail', ['candidates', cid])

def save(d, selection, content=None):
    return rpc('admin_review_save_candidate_image', [d['id'], d['revision'], d['version'],
                                                    content or d['content'], selection, ACTOR])

def denied_save(d, selection, message='review_invalid_input', content=None):
    values = [d['id'], d['revision'], d['version'], content or d['content'], selection, ACTOR]
    reject('begin;set local role service_role;select public.admin_review_save_candidate_image(' +
           ','.join(map(lit, values)) + ');commit;', message)

def seed(origin, image):
    key = 'image-synthetic-' + uuid4().hex
    legacy = scalar('(select legacy_curation_source from machimoa_review.ingest_sources where source_id=' + lit(origin) + ')')
    payload = {'plain_text': '합성 원문', 'source_url': 'https://example.invalid/fixture', 'source_image_url': image}
    sid = json.loads(sql(
        "insert into machimoa_review.source_items(source_id,external_key,revision_hash,first_seen_at,last_seen_at,"
        "source_created_parse_status,source_updated_parse_status,disposition,min_fields,normalized_payload,has_source_url,body_usable) values(" +
        ','.join(map(lit, [origin, key, REV])) + ",now(),now(),'missing','missing','target'," +
        lit({'title': '합성 제목', 'source_url': payload['source_url']}) + ',' + lit(payload) + ",true,true) returning to_jsonb(id);"))
    cid = json.loads(sql("insert into machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,"
        "title_ko,summary_ko,content_ko,title_ja,summary_ja,content_ja,ai_status,ai_status_ko,ai_status_ja,raw_payload,review_status) values(" +
        ','.join(map(lit, [legacy, key, REV, key])) + ",'제목','요약','본문','제목','요약','본문','題名','要約','本文','success','success','success','{}','pending') returning to_jsonb(id);"))
    return sid, cid, key

def verify_source(origin):
    for image in ['https://images.example.org/source.png', None]:
        sid, cid, key = seed(origin, image)
        d = detail(cid)
        equal(d['image'], {'mode': 'source', 'url': None, 'sourceUrl': image})
        provenance = scalar('(select to_jsonb(s) from machimoa_review.source_items s where id=' + lit(sid) + ')')
        for selection in [{'mode': 'override', 'url': 'https://images.example.org/first.png'},
                          {'mode': 'override', 'url': 'https://images.example.org/second.png'},
                          {'mode': 'none', 'url': None}, {'mode': 'source', 'url': None}]:
            previous = d
            d = save(d, selection)
            equal(d['image'], {**selection, 'sourceUrl': image})
            equal(d['content'], previous['content'])
            denied_save(previous, selection, 'review_conflict')
            equal(scalar('(select to_jsonb(s) from machimoa_review.source_items s where id=' + lit(sid) + ')'), provenance)
        equal(save(d, {'mode': 'source', 'url': None})['version'], d['version'])
        for selection in [{'mode': 'override', 'url': 'http://images.example.org/a.png'},
                          {'mode': 'override', 'url': 'https://127.0.0.1/a.png'},
                          {'mode': 'override', 'url': 'https://images.example.org/a.svg'},
                          {'mode': 'none', 'url': image or 'https://images.example.org/a.png'},
                          {'mode': 'invalid', 'url': None}, {'mode': 'source', 'url': None, 'extra': True}]:
            denied_save(d, selection, content={**d['content'], 'titleKo': '저장되면 안 될 제목'})
            equal(detail(cid), d)
        # Projection-only isolated transaction: no approval/publish RPC bypass claim.
        public = json.loads(sql("insert into public.curations(slug,title,content,source,source_item_id,is_published) values(" +
            ','.join(map(lit, [key, '합성 제목', '합성 본문', d['source']['name'], key])) + ",true) returning to_jsonb(id);"))
        for mode in ['override', 'none', 'source']:
            chosen = 'https://images.example.org/operator.png' if mode == 'override' else None
            sql("begin;update machimoa_review.curation_candidates set image_selection_mode=" + lit(mode) + ',image_override_url=' +
                lit(chosen) + ",review_status='published',published_curation_id=" + lit(public) +
                ",published_at=now(),reviewed_at=now(),reviewed_by='synthetic' where id=" + lit(cid) + ';rollback;')
            equal(detail(cid), d)
            sql("update machimoa_review.curation_candidates set image_selection_mode=" + lit(mode) + ',image_override_url=' + lit(chosen) +
                ",review_status='published',published_curation_id=" + lit(public) + ",published_at=now(),reviewed_at=now(),reviewed_by='synthetic' where id=" + lit(cid) + ';')
            equal(scalar('(select source_image_url from public.curations where id=' + lit(public) + ')'),
                  chosen if mode == 'override' else None if mode == 'none' else image)
            denied_save(detail(cid), {'mode': 'none', 'url': None}, 'review_already_processed')
            sql("update machimoa_review.curation_candidates set review_status='pending',published_curation_id=null,published_at=null,reviewed_at=null,reviewed_by=null,image_selection_mode='source',image_override_url=null where id=" + lit(cid) + ';')
            d = detail(cid)
    print('verified synthetic source: ' + origin, flush=True)

with ThreadPoolExecutor(max_workers=3) as pool:
    list(pool.map(verify_source, ['myseoul_program', 'seoul_reservation', 'youthcenter_content', 'youthcenter_policy', 'synthetic_future']))

sid, cid, key = seed('youthcenter_content', 'https://images.example.org/source.png')
d = detail(cid)
sql("create function public.synthetic_image_event_failure() returns trigger language plpgsql as $$begin "
    "if 'image_selection_mode'=any(new.changed_fields) then raise exception 'synthetic_event_failure';end if;return new;end$$;"
    "create trigger synthetic_image_event_failure before insert on machimoa_review.admin_review_events for each row execute function public.synthetic_image_event_failure();")
denied_save(d, {'mode': 'none', 'url': None}, 'synthetic_event_failure', {**d['content'], 'titleKo': '원자성 시험'})
equal(detail(cid), d)
sql('drop trigger synthetic_image_event_failure on machimoa_review.admin_review_events;drop function public.synthetic_image_event_failure();')

barrier = Barrier(2)
def concurrent(url):
    barrier.wait()
    try:
        save(d, {'mode': 'override', 'url': url})
        return 'saved'
    except RuntimeError as e:
        assert 'review_conflict' in str(e), str(e)
        return 'conflict'
with ThreadPoolExecutor(max_workers=2) as pool:
    equal(sorted(pool.map(concurrent, ['https://images.example.org/a.png', 'https://images.example.org/b.png'])), ['conflict', 'saved'])
sql('update machimoa_review.source_items set revision_hash=' + lit('e' * 64) + ' where id=' + lit(sid) + ';')
equal(scalar('machimoa_review.candidate_source_image_url(' + lit(cid) + ')'), None)
reject('begin;set local role service_role;select public.admin_review_detail(\'candidates\',' + lit(cid) + ');commit;', 'review_conflict')
denied_save(d, {'mode': 'none', 'url': None}, 'review_conflict')
print(json.dumps({'checks': checks, 'database': args.database, 'transport': 'network-none PostgreSQL',
                  'productionWrites': 0, 'actualAI': 0, 'publicationTests': 'isolated projection trigger'}, ensure_ascii=False))
