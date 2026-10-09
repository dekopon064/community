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
DB = 'resident_numeric_' + uuid4().hex[:16]
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


sql(up)
legacy_up = up
legacy_down = down
NAME = '20261009094745_resident_codes_numeric_five'
up = (ROOT / 'supabase/migrations' / (NAME + '.sql')).read_text(encoding='utf-8')
down = (ROOT / 'supabase/rollback' / (NAME + '_down.sql')).read_text(encoding='utf-8')
up_tx = up.removeprefix('-- One-time display-code transition; stable resident IDs and receipts survive.\nbegin;').rsplit('commit;',1)[0]
down_tx = down.split('begin;',1)[1].rsplit('commit;',1)[0]

def current_hash():
    return sql("select md5(fingerprint::text) from machimoa_comments.install_guard")

def preserved():
    return sql("select jsonb_build_array((select jsonb_agg(to_jsonb(r)-'code' order by id) from machimoa_comments.residents r),(select jsonb_agg(to_jsonb(c) order by id) from machimoa_comments.comments c),(select jsonb_agg(to_jsonb(q) order by resident_id,request_id) from machimoa_comments.requests q))")

check(current_hash() == 'b925dc54c2a24fc98885fe7ecc6e2a16')
code_a = auth(f"public.prepare_comment_resident('{item}')")['code']
code_b = auth(f"public.prepare_comment_resident('{item}')", B)['code']
request = str(uuid4())
accepted = auth(f"public.create_information_comment('{item}','{request}','legacy live body 😀','{code_a}')")
orphan = str(uuid4())
sql(f"insert into machimoa_comments.residents(id,user_id,code) values('{orphan}',null,'ZZZZZZ')")
for state in ['deleted','hidden']:
    comment_id = str(uuid4())
    if state == 'deleted':
        sql(f"insert into machimoa_comments.comments(id,resident_id,curation_id,original_curation_id,body,state,deleted_at) values('{comment_id}','{orphan}','{item}','{item}',null,'deleted',clock_timestamp())")
    else:
        sql(f"insert into machimoa_comments.comments(id,resident_id,curation_id,original_curation_id,body,state,hidden_at,hidden_until) values('{comment_id}','{orphan}','{item}','{item}','hidden preserved body','hidden',now(),now()+interval '7 days')")
before = preserved()
old_codes = sql("select jsonb_object_agg(id,code) from machimoa_comments.residents")
for change in [
    "grant select on machimoa_comments.residents to anon;",
    "alter table machimoa_comments.comments disable row level security;",
    "create index unexpected_idx on machimoa_comments.comments(created_at);",
    "alter function public.create_information_comment(uuid,uuid,text,text) stable;",
    "grant update(code) on machimoa_comments.residents to authenticated;",
]:
    rejected('begin;' + change + up_tx, 'unexpected comment predecessor')
check(sql("select to_regclass('machimoa_comments.numeric_code_guard') is null") == 't')
check(preserved() == before)
rejected("begin;alter function machimoa_saved.is_savable(public.curations) volatile;"+up_tx, 'unexpected eligibility/auth predecessor')

# Random failure after guard and DDL must roll back both data and installation.
random_def = sql("select pg_get_functiondef('pg_catalog.gen_random_uuid()'::regprocedure)")
rejected('begin;'+up_tx+'select 1/0;', 'division by zero')
check(sql("select pg_get_functiondef('pg_catalog.gen_random_uuid()'::regprocedure)") == random_def)
check(sql("select to_regclass('machimoa_comments.numeric_code_backup') is null") == 't')
check(sql("select jsonb_object_agg(id,code) from machimoa_comments.residents") == old_codes)

# Full capacity and over-capacity are independent transactions; no fixtures deleted.
fixtures = """with candidates as (select g, string_agg(substr('ABCDEFGHJKMNPQRSTUVWXYZ23456789',((g / power(31,n)::integer)%31)+1,1),'' order by n desc) code from generate_series(0,199999) g cross join generate_series(0,5) n group by g), available as(select code from candidates where not exists(select 1 from machimoa_comments.residents r where r.code=candidates.code) order by g limit __COUNT__) insert into machimoa_comments.residents(code) select code from available;"""
remaining = 100000 - int(sql('select count(*) from machimoa_comments.residents'))
check(sql('begin;'+fixtures.replace('__COUNT__',str(remaining))+up_tx+"select count(*)=100000 and count(distinct code)=100000 and bool_and(code ~ '^[0-9]{5}$') and min(code)='00000' and max(code)='99999' from machimoa_comments.residents;rollback;").splitlines()[-1] == 't')
rejected('begin;'+fixtures.replace('__COUNT__',str(remaining+1))+up_tx, 'resident numeric code space insufficient')
check(sql("select jsonb_object_agg(id,code) from machimoa_comments.residents") == old_codes)

# A migration holding the resident lock fences already-open old composers.
# Existing authenticated reads/prepares resume only after the complete conversion.
with ThreadPoolExecutor(max_workers=3) as executor:
    migrating = executor.submit(sql, 'begin;'+up_tx+'select pg_sleep(3);commit;')
    for _ in range(100):
        locked = sql("select exists(select 1 from pg_locks l join pg_stat_activity a on a.pid=l.pid where a.datname=current_database() and l.relation='machimoa_comments.residents'::regclass and l.mode='AccessExclusiveLock' and l.granted)")
        if locked == 't':
            break
        time.sleep(0.02)
    check(locked == 't')
    preparing = executor.submit(auth, f"public.prepare_comment_resident('{item}')")
    posting = executor.submit(rejected, f"begin;set local role authenticated;select set_config('request.jwt.claim.sub','{A}',true);select public.create_information_comment('{item}','{request}','legacy live body 😀','{code_a}');", 'identity_changed')
    for _ in range(100):
        waiting = int(sql("select count(distinct l.pid) from pg_locks l join pg_stat_activity a on a.pid=l.pid where a.datname=current_database() and not l.granted and l.relation='machimoa_comments.residents'::regclass"))
        if waiting >= 2:
            break
        time.sleep(0.02)
    check(waiting >= 2)
    migrating.result()
    resumed_code = preparing.result()['code']
    posting.result()
check(len(resumed_code) == 5)
check(preserved() == before)
check(sql("select count(*)=3 and count(distinct code)=3 and bool_and(code ~ '^[0-9]{5}$') from machimoa_comments.residents") == 't')
new_a = auth(f"public.prepare_comment_resident('{item}')")['code']
check(new_a != code_a and len(new_a) == 5)
page = auth(f"public.list_information_comments('{item}')")
check(page['code'] == new_a and page['items'][0]['residentCode'] == new_a)
check(page['items'][0]['body'] == 'legacy live body 😀')
check(auth(f"public.information_comment_request_state('{item}','{request}')") == accepted)
check(auth(f"public.create_information_comment('{item}','{request}','legacy live body 😀','{new_a}')") == accepted)
rejected(f"begin;set local role authenticated;select set_config('request.jwt.claim.sub','{A}',true);select public.create_information_comment('{item}','{request}','legacy live body 😀','{code_a}');", 'identity_changed')
rejected(f"begin;set local role authenticated;select set_config('request.jwt.claim.sub','{A}',true);select public.create_information_comment('{item}','{request}','different','{new_a}');", 'request_conflict')
check(preserved() == before)
rejected(up, 'numeric code contract name collision')
for role_name in ['anon','authenticated','service_role']:
    for table in ['numeric_code_backup','numeric_code_guard']:
        rejected(f'set role {role_name};select * from machimoa_comments.{table};','permission denied')
    for helper in ['random_numeric_code','numeric_records_fingerprint']:
        rejected(f'set role {role_name};select machimoa_comments.{helper}();','permission denied')
for change in [
    "grant select on machimoa_comments.numeric_code_backup to anon;",
    "alter table machimoa_comments.numeric_code_guard disable row level security;",
    "create index later_numeric_idx on machimoa_comments.residents(code);",
    "alter function machimoa_comments.random_numeric_code() stable;",
    "create policy unexpected_policy on machimoa_comments.numeric_code_backup for select to authenticated using(true);",
]:
    rejected('begin;'+change+down_tx,'subsequent numeric contract changes')
for change in [
    "update machimoa_comments.residents set last_posted_at=now();",
    "update machimoa_comments.comments set body='changed' where state='live';",
    "update machimoa_comments.numeric_code_backup set old_code='YYYYYY' where old_code='ZZZZZZ';",
]:
    rejected('begin;'+change+down_tx,'subsequent resident/comment records')
check(preserved() == before)
sql(down)
check(current_hash() == 'b925dc54c2a24fc98885fe7ecc6e2a16')
check(sql("select jsonb_object_agg(id,code) from machimoa_comments.residents") == old_codes)
check(preserved() == before)
check(sql("select to_regprocedure('machimoa_comments.random_numeric_code()') is null") == 't')
sql(up)
new_a = auth(f"public.prepare_comment_resident('{item}')")['code']

# Fresh authenticated first-prepare: concurrent, stable, string-preserving.
C = str(uuid4());sql(f"insert into auth.users values('{C}')")
with ThreadPoolExecutor(max_workers=4) as executor:
    codes=list(executor.map(lambda _: auth(f"public.prepare_comment_resident('{item}')",C)['code'],range(4)))
check(len(set(codes)) == 1 and len(codes[0]) == 5)
check(auth(f"public.prepare_comment_resident('{item}')",C)['code'] == codes[0])
rejected(down,'subsequent resident/comment records')
helper_def=sql("select pg_get_functiondef('machimoa_comments.random_numeric_code()'::regprocedure)")
def forced_helper(numeric):
    raw=bytes(int(ch) for ch in numeric)+bytes(11)
    return helper_def.replace('uuid_send(gen_random_uuid())',"decode('"+raw.hex()+"','hex')")+';'
for numeric in ['00000','00031','99999']:
    D=str(uuid4());sql(f"insert into auth.users values('{D}')")
    result=sql("begin;"+forced_helper(numeric)+"set local role authenticated;select set_config('request.jwt.claim.sub','"+D+"',true);select public.prepare_comment_resident('"+item+"');rollback;").splitlines()[-1]
    check(json.loads(result)['code'] == numeric)
    check(sql("select pg_get_functiondef('machimoa_comments.random_numeric_code()'::regprocedure)") == helper_def)
# Alter only random input in a rolled-back synthetic fixture, keeping actual loops.
D=str(uuid4());sql(f"insert into auth.users values('{D}')")
rejected("begin;"+forced_helper(new_a)+"set local role authenticated;select set_config('request.jwt.claim.sub','"+D+"',true);select public.prepare_comment_resident('"+item+"');",'resident_unavailable')
check(sql(f"select count(*) from machimoa_comments.residents where user_id='{D}'") == '0')
rejected("begin;"+helper_def.replace('uuid_send(gen_random_uuid())',"decode('"+('ff'*16)+"','hex')")+";select machimoa_comments.random_numeric_code();",'resident_unavailable')
check(sql("select pg_get_functiondef('machimoa_comments.random_numeric_code()'::regprocedure)") == helper_def)
for bad in ['1234','123456','ABCDE','１２３４５',' 00031']:
    rejected("begin;insert into machimoa_comments.residents(code) values('"+bad+"');",'residents_code_check')
rejected("begin;insert into machimoa_comments.residents(code) values(E'00031\\n');", 'residents_code_check')
check(sql("select bool_and(proconfig=array['search_path=\"\"'] and proowner='postgres'::regrole) from pg_proc where pronamespace='machimoa_comments'::regnamespace") == 't')
check(saved_baseline == sql("select md5(string_agg(pg_get_functiondef(p.oid),'' order by p.oid)) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_saved'"))
print(json.dumps({'checks':checks,'actualPostgreSQL':True,'container':CONTAINER,'newDatabase':DB,'preserved':True,'productionAccess':False}),flush=True)
