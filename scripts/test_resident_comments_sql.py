"""Synthetic-only fresh DB on a checked, already-running isolated PostgreSQL."""
import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
NAME = '20261009044659_resident_codes_comments'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--container', default='machimoa-saved-count-sql-20261009-56ca9041')
CONTAINER = parser.parse_args().container

def docker(args, data=None):
    result = subprocess.run(['docker', *args], input=data, text=True, encoding='utf-8', capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()

resource = json.loads(docker(['inspect', CONTAINER]))[0]
assert resource['State']['Running'] and resource['HostConfig']['NetworkMode'] == 'none'
assert not resource['HostConfig']['PortBindings'] and not resource['HostConfig'].get('Tmpfs')
assert resource['Config']['Labels'].get('machimoa.purpose') == 'saved-count-sql-validation'
assert len(resource['Mounts']) == 1 and resource['Mounts'][0]['Type'] == 'volume'
assert resource['Mounts'][0]['Name'] == CONTAINER + '-data'
assert resource['Mounts'][0]['Destination'] == '/var/lib/postgresql/data'
free = int(docker(['exec', CONTAINER, 'df', '-B1', '/var/lib/postgresql/data']).splitlines()[-1].split()[3])
assert free >= 64 * 1024 * 1024, 'insufficient isolated storage: no DB created'
DB = 'resident_comments_' + uuid4().hex[:16]
docker(['exec', CONTAINER, 'createdb', '-U', 'postgres', DB])
print(json.dumps({'newDatabase': DB, 'container': CONTAINER, 'freeBytes': free}), flush=True)

def sql(body):
    return docker(['exec', '-i', CONTAINER, 'psql', '-X', '-U', 'postgres', '-d', DB, '-v', 'ON_ERROR_STOP=1', '-qAt'], body)

checks = 0
def check(value):
    global checks
    assert value
    checks += 1

def rejected(body, message):
    try:
        sql(body)
    except RuntimeError as error:
        check(message in str(error))
    else:
        raise AssertionError('expected rejection: ' + message)

A, B = str(uuid4()), str(uuid4())
def role(role_name, body, user=''):
    return sql(f"begin;set local role {role_name};select set_config('request.jwt.claim.sub','{user}',true);{body};commit;").splitlines()[-1]

def auth(body, user=A):
    return json.loads(role('authenticated', 'select ' + body, user))

sql("""create schema auth;create table auth.users(id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
grant usage on schema auth to anon,authenticated,service_role;
create table public.curations(id uuid primary key,slug text not null,user_category text,is_published boolean,
 title_ko text,summary_ko text,content_ko text,title_ja text,summary_ja text,content_ja text,
 application_deadline_kind text,application_deadline_on date);
alter table public.curations enable row level security;
grant select on public.curations to anon,authenticated;
create policy public_read on public.curations for select to anon,authenticated using(is_published);
""" + f"insert into auth.users values('{A}'),('{B}');")
for predecessor in ['20261001000100_saved_information', '20261001000200_saved_information_resume',
                    '20261001000300_saved_information_order', '20261008142938_saved_all_categories_count']:
    sql((ROOT / 'supabase/migrations' / (predecessor + '.sql')).read_text(encoding='utf-8'))
up = (ROOT / 'supabase/migrations' / (NAME + '.sql')).read_text(encoding='utf-8')
down = (ROOT / 'supabase/rollback' / (NAME + '_down.sql')).read_text(encoding='utf-8')
categories = {cat: str(uuid4()) for cat in ['policy', 'program', 'event', 'youth_space', 'living']}
for cat, item in categories.items():
    sql(f"insert into public.curations values('{item}','synthetic-{cat}','{cat}',true,'합성','합성','합성','合成','合成','合成','none',null)")
item = categories['program']
saved_baseline = sql("select md5(string_agg(pg_get_functiondef(p.oid),'' order by p.oid)) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_saved'")

# Guard failures are aborted transactions, leaving no partial installation.
rejected("begin;alter function machimoa_saved.is_savable(public.curations) volatile;" + up.replace('begin;', '', 1), 'unexpected public eligibility predecessor')
check(sql("select to_regnamespace('machimoa_comments') is null") == 't')
sql(up)
check(sql("select bool_and(relrowsecurity and relowner='postgres'::regrole) from pg_class where relnamespace='machimoa_comments'::regnamespace and relkind='r'") == 't')
rejected(up, 'comment contract name collision')
for change in [
    "grant select on machimoa_comments.residents to anon;",
    "alter table machimoa_comments.comments disable row level security;",
    "create index later_index on machimoa_comments.comments(created_at);",
    "create function machimoa_comments.later() returns int language sql as $$select 1$$;",
    "alter function public.list_information_comments(uuid,timestamptz,uuid) volatile;",
]:
    rejected('begin;' + change + down.replace('begin;', '', 1), 'subsequent comment contract changes')
check(sql("select count(*) from machimoa_comments.residents") == '0')
sql(down)
check(sql("select to_regnamespace('machimoa_comments') is null") == 't')
sql(up)

for cat, curation in categories.items():
    value = json.loads(role('anon', f"select public.list_information_comments('{curation}')"))
    check(value == {'items': [], 'next': None, 'code': None})
check(sql("select count(*) from machimoa_comments.residents") == '0')
for name in ['anon', 'authenticated', 'service_role']:
    for table in ['residents', 'comments', 'requests', 'install_guard']:
        rejected(f"set role {name};select * from machimoa_comments.{table};", 'permission denied')
rejected(f"set role anon;select public.prepare_comment_resident('{item}');", 'permission denied')
rejected(f"set role authenticated;select public.admin_hide_information_comment('{item}','{uuid4()}','{A}');", 'permission denied')
rejected(f"set role authenticated;select public.purge_expired_hidden_information_comments();", 'permission denied')
check(sql("select bool_and(proconfig=array['search_path=\"\"']) from pg_proc where pronamespace='machimoa_comments'::regnamespace") == 't')
check(sql("select count(*) from pg_policy where polrelid in (select oid from pg_class where relnamespace='machimoa_comments'::regnamespace)") == '0')

with ThreadPoolExecutor(max_workers=4) as executor:
    codes = list(executor.map(lambda _: auth(f"public.prepare_comment_resident('{item}')")['code'], range(4)))
check(len(set(codes)) == 1 and len(codes[0]) == 6)
code = codes[0]
code_b = auth(f"public.prepare_comment_resident('{item}')", B)['code']
check(code != code_b)
check(sql("select count(*) from machimoa_comments.residents") == '2')
# Force ten candidate collisions only inside a rolled-back synthetic DB
# transaction. No installed product function or another DB is changed.
third_user = str(uuid4())
sql(f"insert into auth.users values('{third_user}')")
alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
raw = bytes([alphabet.index(char) for char in code]) + bytes.fromhex('40008000000000000000')
assert len(raw) == 16
collision_uuid = str(__import__('uuid').UUID(bytes=raw))
random_definition = sql("select pg_get_functiondef('pg_catalog.gen_random_uuid()'::regprocedure)")
rejected("begin;create or replace function pg_catalog.gen_random_uuid() returns uuid language sql volatile as $$select '"
         + collision_uuid + "'::uuid$$;set local role authenticated;select set_config('request.jwt.claim.sub','"
         + third_user + "',true);select public.prepare_comment_resident('" + item + "');", 'resident_unavailable')
check(sql("select pg_get_functiondef('pg_catalog.gen_random_uuid()'::regprocedure)") == random_definition)
check(sql(f"select count(*) from machimoa_comments.residents where user_id='{third_user}'") == '0')
request = str(uuid4())
create = f"public.create_information_comment('{item}','{request}','첫 댓글 😀','{code}')"
with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(lambda _: auth(create), range(2)))
check(results[0] == results[1] and results[0]['state'] == 'live')
cid = results[0]['commentId']
check(sql("select count(*) from machimoa_comments.comments") == '1')
check(auth(f"public.information_comment_request_state('{item}','{request}')") == results[0])
check(auth(f"public.information_comment_request_state('{item}','{request}')", B) == {'outcome': 'absent'})
for body, expected in [
    (f"public.create_information_comment('{item}','{request}','다른 입력','{code}')", 'request_conflict'),
    (f"public.create_information_comment('{item}','{uuid4()}','유효 입력','{code_b}')", 'identity_changed'),
    (f"public.create_information_comment('{item}','{uuid4()}','   ','{code}')", 'invalid_comment'),
    (f"public.create_information_comment('{item}','{uuid4()}',repeat('😀',1001),'{code}')", 'invalid_comment'),
    (f"public.create_information_comment('{item}','{uuid4()}','두번째','{code}')", 'rate_limited'),
    (f"public.remove_information_comment('{item}','{cid}')", 'information_unavailable'),
]:
    user = B if 'remove_information' in body else A
    rejected(f"begin;set local role authenticated;select set_config('request.jwt.claim.sub','{user}',true);select {body};", expected)
public = json.loads(role('anon', f"select public.list_information_comments('{item}')"))
check(set(public) == {'items', 'next', 'code'} and public['items'][0]['canDelete'] is False)
check(set(public['items'][0]) == {'id', 'residentCode', 'body', 'createdAt', 'canDelete'})
check(A not in json.dumps(public) and B not in json.dumps(public))
check(auth(f"public.list_information_comments('{item}')")['items'][0]['canDelete'] is True)

# Cooldown and time-expiry simulations only touch this new DB's synthetic rows.
def elapsed(user=A):
    sql(f"update machimoa_comments.residents set last_posted_at=clock_timestamp()-interval '31 seconds' where user_id='{user}'")
elapsed()
with ThreadPoolExecutor(max_workers=2) as executor:
    def attempt(_):
        try:
            return auth(f"public.create_information_comment('{item}','{uuid4()}','동시 신규','{code}')")['outcome']
        except RuntimeError as error:
            assert 'rate_limited' in str(error)
            return 'limited'
    attempts = list(executor.map(attempt, range(2)))
check(sorted(attempts) == ['accepted', 'limited'])
check(auth(f"public.remove_information_comment('{item}','{cid}')") == {'outcome': 'deleted'})
check(sql(f"select body is null and state='deleted' from machimoa_comments.comments where id='{cid}'") == 't')
check(auth(create)['state'] == 'deleted')
elapsed()
hidden_id = auth(f"public.create_information_comment('{item}','{uuid4()}','숨김 본문','{code}')")['commentId']
check(json.loads(role('service_role', f"select public.admin_hide_information_comment('{item}','{hidden_id}','{B}')")) == {'outcome': 'hidden'})
check(sql(f"select body='숨김 본문' and hidden_until=hidden_at+interval '7 days' from machimoa_comments.comments where id='{hidden_id}'") == 't')
check(hidden_id not in json.dumps(auth(f"public.list_information_comments('{item}')")))
check(role('service_role', 'select public.purge_expired_hidden_information_comments()') == '0')
sql(f"update machimoa_comments.comments set hidden_at=statement_timestamp()-interval '8 days',hidden_until=statement_timestamp()-interval '1 day' where id='{hidden_id}'")
check(role('service_role', 'select public.purge_expired_hidden_information_comments()') == '1')
check(sql(f"select body is null and state='hidden' from machimoa_comments.comments where id='{hidden_id}'") == 't')

for cat, target in categories.items():
    elapsed()
    value = auth(f"public.create_information_comment('{target}','{uuid4()}','{cat} 댓글','{code}')")
    check(value['state'] == 'live')
# Stable pagination with equal timestamps and microsecond-precision cursor.
resident = sql(f"select id from machimoa_comments.residents where user_id='{B}'")
sql(f"insert into machimoa_comments.comments(resident_id,curation_id,original_curation_id,body,created_at) select '{resident}','{item}','{item}','합성 페이지','2026-10-09T00:00:00.123456Z' from generate_series(1,23)")
first = auth(f"public.list_information_comments('{item}')")
check(len(first['items']) == 20 and first['next'] is not None)
second = auth(f"public.list_information_comments('{item}','{first['next']['at']}','{first['next']['id']}')")
check(not set(x['id'] for x in first['items']).intersection(x['id'] for x in second['items']))
check(first['next']['at'].endswith('123456Z'))
# Publication/deletion wins a row lock before a simultaneous comment write.
# Writer must recheck the locked current content row, not the old snapshot.
for operation in [f"update public.curations set is_published=false where id='{item}'", f"delete from public.curations where id='{item}'"]:
    elapsed()
    with ThreadPoolExecutor(max_workers=1) as executor:
        holder = executor.submit(sql, f"begin;{operation};select pg_sleep(1.5);commit;")
        locked = False
        for _ in range(20):
            if sql("select exists(select 1 from pg_locks where relation='public.curations'::regclass and mode='RowExclusiveLock' and granted and pid<>pg_backend_pid())") == 't':
                locked = True
                break
            time.sleep(0.02)
        check(locked)
        rejected(f"begin;set local role authenticated;select set_config('request.jwt.claim.sub','{A}',true);select public.create_information_comment('{item}','{uuid4()}','잠금 확인','{code}');", 'information_unavailable')
        holder.result()
    if operation.startswith('update'):
        sql(f"update public.curations set is_published=true where id='{item}'")
    else:
        check(sql(f"select count(*)>0 and bool_and(curation_id is null) from machimoa_comments.comments where original_curation_id='{item}'") == 't')
        # Recreate only this test's synthetic content; comments remain orphaned.
        sql(f"insert into public.curations values('{item}','synthetic-program','program',true,'합성','합성','합성','合成','合成','合成','none',null)")
        check(auth(f"public.list_information_comments('{item}')")['items'] == [])
for change in ["is_published=false", "title_ja=' '"]:
    rejected(f"begin;update public.curations set {change} where id='{item}';select public.list_information_comments('{item}');", 'information_unavailable')
    rejected(f"begin;update public.curations set {change} where id='{item}';select set_config('request.jwt.claim.sub','{A}',true);select public.prepare_comment_resident('{item}');", 'information_unavailable')
rejected(f"select public.list_information_comments('{uuid4()}');", 'information_unavailable')
rejected('begin;' + down.replace('begin;', '', 1), 'records exist')
check(sql("select md5(string_agg(pg_get_functiondef(p.oid),'' order by p.oid)) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_saved'") == saved_baseline)
print(json.dumps({'actualPostgreSQL': True, 'checks': checks, 'postgres': sql('show server_version'), 'databasePreserved': DB, 'productionAccess': False}))
