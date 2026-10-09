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

sql(up)
NAME = '20261009094745_resident_codes_numeric_five'
sql((ROOT / 'supabase/migrations' / (NAME + '.sql')).read_text(encoding='utf-8'))
print('NUMERIC_FINGERPRINT='+sql("select md5(installed_fingerprint::text) from machimoa_comments.numeric_code_guard"),flush=True)

NAME='20261009120957_20261009103737_comment_threads_count'
up=(ROOT/'supabase/migrations'/f'{NAME}.sql').read_text(encoding='utf-8')
down=(ROOT/'supabase/rollback'/f'{NAME}_down.sql').read_text(encoding='utf-8')
up_tx=up.split('begin;',1)[1].rsplit('commit;',1)[0]
down_tx=down.split('begin;',1)[1].rsplit('commit;',1)[0]
code=auth(f"public.prepare_comment_resident('{item}')")['code']
code_b=auth(f"public.prepare_comment_resident('{item}')",B)['code']
legacy_key=str(uuid4())
root=auth(f"public.create_information_comment('{item}','{legacy_key}','original body','{code}')")['commentId']
baseline=sql("select machimoa_comments.numeric_records_fingerprint()")
for change in ["grant select on machimoa_comments.comments to anon;", "alter table machimoa_comments.comments disable row level security;", "alter function machimoa_comments.list(uuid,timestamptz,uuid) volatile;"]:
 rejected('begin;'+change+up_tx+'commit;', 'unexpected numeric comment predecessor')
 check(sql("select to_regclass('machimoa_comments.thread_guard') is null")=='t')
sql(up)
check(sql("select machimoa_comments.numeric_records_fingerprint()") != baseline) # only new nullable column in digest
rejected(up,'thread contract name collision')
for change in ["grant select on machimoa_comments.comments to authenticated;", "create index later_index on machimoa_comments.comments(created_at);", "alter function public.count_information_comments(uuid) volatile;", "alter table machimoa_comments.comments disable trigger comments_parent_guard;"]:
 rejected('begin;'+change+down_tx+'commit;','subsequent thread contract changes')
sql(down)
check(sql("select machimoa_comments.numeric_records_fingerprint()") == baseline)
sql(up)
check(role('anon',f"select public.count_information_comments('{item}')")=='{"count": 1}')
check(auth(f"public.create_information_comment('{item}','{legacy_key}','original body','{code}')")['commentId']==root)
for cat,cid in categories.items():
 check(json.loads(role('anon',f"select public.count_information_comments('{cid}')"))['count']==(1 if cat=='program' else 0))
check(auth(f"public.list_information_comment_threads('{item}')")['items'][0]['replyCount']==0)
for table in ['residents','comments','requests','thread_guard','numeric_code_backup']:
 rejected(f'set role anon;select * from machimoa_comments.{table};','permission denied')
check(sql("select bool_and(relrowsecurity) from pg_class where relnamespace='machimoa_comments'::regnamespace and relkind='r'")=='t')
rejected(f"set role anon;select public.create_information_comment_reply('{item}','{uuid4()}','reply','{code}','{root}')",'permission denied')
key=str(uuid4())
rejected(f"begin;select set_config('request.jwt.claim.sub','{A}',true);set local role authenticated;select public.create_information_comment_reply('{item}','{key}','reply','{code}','{root}');commit;",'rate_limited')
reply=auth(f"public.create_information_comment_reply('{item}','{key}','reply body','{code_b}','{root}')",B)['commentId']
check(auth(f"public.create_information_comment_reply('{item}','{key}','reply body','{code_b}','{root}')",B)['commentId']==reply)
for call in [f"public.create_information_comment('{item}','{key}','reply body','{code_b}')",f"public.create_information_comment_reply('{item}','{key}','other body','{code_b}','{root}')",f"public.create_information_comment_reply('{item}','{key}','reply body','{code_b}','{uuid4()}')"]:
 rejected(f"begin;set local role authenticated;select set_config('request.jwt.claim.sub','{B}',true);select {call};commit;",'request_conflict')
for parent,cid in [(reply,item),(str(uuid4()),item),(root,categories['event'])]:
 rejected(f"begin;set local role authenticated;select set_config('request.jwt.claim.sub','{A}',true);select public.create_information_comment_reply('{cid}','{uuid4()}','bad','{code}','{parent}');commit;",'parent_unavailable')
check(json.loads(role('anon',f"select public.count_information_comments('{item}')"))['count']==2)
check(len(json.loads(role('anon',f"select public.list_information_comments('{item}')"))['items'])==1)
check(json.loads(role('anon',f"select public.list_information_comment_replies('{item}','{root}')"))['items'][0]['body']=='reply body')
# Account-agnostic forged ownership and deeper parent rows are denied by DB/API boundaries.
rejected(f"begin;insert into machimoa_comments.comments(resident_id,curation_id,original_curation_id,body,parent_id) select resident_id,curation_id,original_curation_id,'deeper',id from machimoa_comments.comments where id='{reply}';commit;",'invalid_comment_parent')
rejected(f"begin;update machimoa_comments.comments set parent_id='{reply}' where id='{root}';commit;",'immutable_comment_thread')
auth(f"public.remove_information_comment('{item}','{root}')")
threads=json.loads(role('anon',f"select public.list_information_comment_threads('{item}')"))
tomb=threads['items'][0]
check(tomb['state']=='deleted' and tomb['body'] is None and tomb['residentCode'] is None and not tomb['canDelete'])
check(json.loads(role('anon',f"select public.count_information_comments('{item}')"))['count']==1)
check(auth(f"public.create_information_comment_reply('{item}','{key}','reply body','{code_b}','{root}')",B)['commentId']==reply)
check(auth(f"public.information_comment_request_state('{item}','{key}')",B)['commentId']==reply)
rejected(f"begin;set local role authenticated;select set_config('request.jwt.claim.sub','{A}',true);select public.create_information_comment_reply('{item}','{uuid4()}','new','{code}','{root}');commit;",'parent_unavailable')
auth(f"public.remove_information_comment('{item}','{reply}')",B)
check(not json.loads(role('anon',f"select public.list_information_comment_threads('{item}')"))['items'])
check(json.loads(role('anon',f"select public.count_information_comments('{item}')"))['count']==0)
rejected(down,'subsequent comment records')
# Synthetic page fixtures, same timestamp stable tie-breaking, no writes to older DBs.
resident=sql(f"select id from machimoa_comments.residents where user_id='{A}'")
stamp='2026-10-09T00:00:00Z'
roots=[]
for i in range(25):
 rid=str(uuid4());roots.append(rid)
 sql(f"insert into machimoa_comments.comments(id,resident_id,curation_id,original_curation_id,body,created_at) values('{rid}','{resident}','{item}','{item}','root {i}','{stamp}')")
parent=roots[0]
for i in range(25):
 sql(f"insert into machimoa_comments.comments(resident_id,curation_id,original_curation_id,body,created_at,parent_id) values('{resident}','{item}','{item}','child {i}','{stamp}','{parent}')")
page=json.loads(role('anon',f"select public.list_information_comment_threads('{item}')"))
check(len(page['items'])==20 and bool(page['next']))
cursor=page['next']
page2=json.loads(role('anon',f"select public.list_information_comment_threads('{item}','{cursor['at']}','{cursor['id']}')"))
check(len(page2['items'])==5 and not page2['next'])
check(len({x['id'] for x in page['items']+page2['items']})==25)
rpage=json.loads(role('anon',f"select public.list_information_comment_replies('{item}','{parent}')"))
check(len(rpage['items'])==20 and bool(rpage['next']))
cursor=rpage['next']
rpage2=json.loads(role('anon',f"select public.list_information_comment_replies('{item}','{parent}','{cursor['at']}','{cursor['id']}')"))
check(len(rpage2['items'])==5 and len({x['id'] for x in rpage['items']+rpage2['items']})==25)
check([x['id'] for x in rpage['items']+rpage2['items']]==sorted(x['id'] for x in rpage['items']+rpage2['items']))
check(json.loads(role('anon',f"select public.count_information_comments('{item}')"))['count']==50)
# Hide parent retains children; purge shares the exact existing seven-day function.
role('service_role',f"select public.admin_hide_information_comment('{item}','{parent}','{A}')")
tomb=next((x for x in auth(f"public.list_information_comment_threads('{item}')")['items'] if x['id']==parent),None)
if tomb is None:
 tomb=next(x for x in page2['items'] if x['id']==parent) # refresh below checks DB public parent state
check(sql(f"select state='hidden' and body is not null from machimoa_comments.comments where id='{parent}'")=='t')
check(json.loads(role('anon',f"select public.count_information_comments('{item}')"))['count']==49)
child=rpage['items'][0]['id']
role('service_role',f"select public.admin_hide_information_comment('{item}','{child}','{A}')")
check(role('service_role','select public.purge_expired_hidden_information_comments(100)')=='0')
sql(f"update machimoa_comments.comments set hidden_at=now()-interval '8 days',hidden_until=now()-interval '1 day' where id='{child}'")
check(role('service_role','select public.purge_expired_hidden_information_comments(100)')=='1')
check(sql(f"select body is null from machimoa_comments.comments where id='{child}'")=='t')
check(json.loads(role('anon',f"select public.count_information_comments('{item}')"))['count']==48)
# Unpublish boundary in an independent transaction, rolled back afterward.
for fn in [f"public.count_information_comments('{item}')",f"public.list_information_comment_threads('{item}')",f"public.list_information_comment_replies('{item}','{parent}')"]:
 rejected(f"begin;update public.curations set is_published=false where id='{item}';set local role anon;select {fn};commit;",'information_unavailable')
check(saved_baseline==sql("select md5(string_agg(pg_get_functiondef(p.oid),'' order by p.oid)) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_saved'"))

# Exact-once concurrent replies and root/reply account-wide throttling.
new_parent=str(uuid4())
sql(f"insert into machimoa_comments.comments(id,resident_id,curation_id,original_curation_id,body) values('{new_parent}','{resident}','{item}','{item}','race parent')")
sql(f"update machimoa_comments.residents set last_posted_at=null where user_id='{B}'")
race_key=str(uuid4())
def concurrent_reply():
 return auth(f"public.create_information_comment_reply('{item}','{race_key}','concurrent reply','{code_b}','{new_parent}')",B)
with ThreadPoolExecutor(max_workers=2) as executor:
 results=list(executor.map(lambda _:concurrent_reply(),range(2)))
check(results[0]['commentId']==results[1]['commentId'])
check(sql(f"select count(*) from machimoa_comments.requests where request_id='{race_key}'")=='1')
rejected(f"begin;set local role authenticated;select set_config('request.jwt.claim.sub','{B}',true);select public.create_information_comment('{item}','{uuid4()}','root after reply','{code_b}');commit;",'rate_limited')
# Parent deletion holds the same row lock; a waiting writer sees the new deleted state.
sql(f"update machimoa_comments.residents set last_posted_at=null where user_id='{A}'")
with ThreadPoolExecutor(max_workers=2) as executor:
 deletion=executor.submit(auth,f"public.remove_information_comment('{item}','{new_parent}')")
 deletion.result()
 try:
  auth(f"public.create_information_comment_reply('{item}','{uuid4()}','must not appear','{code}','{new_parent}')")
 except RuntimeError as error:
  check('parent_unavailable' in str(error))
 else: raise AssertionError('deleted-parent race accepted')
check(sql(f"select count(*) from machimoa_comments.comments where parent_id='{new_parent}'")=='1')
# Lock ordering with publish/delete: blocked writer must recheck eligibility after release.
locked_parent=str(uuid4())
sql(f"insert into machimoa_comments.comments(id,resident_id,curation_id,original_curation_id,body) values('{locked_parent}','{resident}','{item}','{item}','locked parent')")
with ThreadPoolExecutor(max_workers=2) as executor:
 blocker=executor.submit(sql,f"begin;update machimoa_comments.comments set state='deleted',body=null,deleted_at=now() where id='{locked_parent}';select pg_sleep(2);commit;")
 time.sleep(.4)
 waiting=executor.submit(auth,f"public.create_information_comment_reply('{item}','{uuid4()}','blocked','{code}','{locked_parent}')")
 blocker.result()
 try: waiting.result()
 except RuntimeError as error: check('parent_unavailable' in str(error))
 else: raise AssertionError('locked deleted-parent accepted')
check(sql(f"select count(*) from machimoa_comments.comments where parent_id='{locked_parent}'")=='0')

print(json.dumps({'checks':checks,'actualPostgreSQL':True,'database':DB,'preserved':True}),flush=True)
