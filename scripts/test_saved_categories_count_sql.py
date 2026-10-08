"""New isolated PostgreSQL only; never starts/resets/deletes a container or database."""
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import subprocess, json, hashlib, re, argparse
ROOT=Path(__file__).resolve().parents[1]
NAME='20261008142938_saved_all_categories_count'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--container',default='machimoa-program-ai-5689d361')
CONTAINER=parser.parse_args().container
def run(args, data=None):
    p=subprocess.run(args,input=data,text=True,encoding='utf-8',capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return p.stdout.strip()
def docker(args,data=None):return run(['docker',*args],data)
# Hash regression is static and always runs, even if SQL execution is unavailable.
pattern=re.compile(r'create(?: or replace)? function\s+([\w.]+)\s*\((.*?)\)\s*(returns\s+.*?)\bas\s+(\$\w*\$)(.*?)\4\s*;',re.I|re.S)
expected={}
for f in ['20261001000100_saved_information.sql','20261001000200_saved_information_resume.sql','20261001000300_saved_information_order.sql']:
    for m in pattern.finditer((ROOT/'supabase/migrations'/f).read_text(encoding='utf-8')):
        sig=m[1]+'('+','.join(a.strip().split()[1].replace('pg_catalog.','') for a in m[2].split(',') if a.strip())+')'
        expected[sig]=hashlib.md5(m[5].encode()).hexdigest()
up=(ROOT/'supabase/migrations'/f'{NAME}.sql').read_text(encoding='utf-8');down=(ROOT/'supabase/rollback'/f'{NAME}_down.sql').read_text(encoding='utf-8')
for sig,digest in expected.items():assert f"('{sig}','{digest}'," in up, sig
assert len(expected)==12
assert 'saved_information_select_own' in up and 'polroles' in up and 'pg_get_expr' in up
assert "count(*) from machimoa_saved.information s where s.curation_id=c.id" in up
assert not re.search(r'(?:insert into|update|delete from)\s+(?:public\.curations|machimoa_saved\.(?:information|intent_orders|resume_receipts|resume_fences))\b',up,re.I)
assert not re.search(r'(?:delete from|truncate)\s+(?:public\.curations|machimoa_saved\.)',down,re.I)
assert 'installed_table_boundary' in up and 'expected_tables' in down
static=len(expected)+6
try:
    if CONTAINER!='machimoa-program-ai-5689d361':
        resource=json.loads(docker(['inspect',CONTAINER]))[0]
        assert resource['Config']['Labels'].get('machimoa.purpose')=='saved-count-sql-validation'
        assert resource['HostConfig']['NetworkMode']=='none'
        assert not resource['HostConfig']['PortBindings']
        assert not resource['HostConfig'].get('Tmpfs')
        assert len(resource['Mounts'])==1 and resource['Mounts'][0]['Type']=='volume'
        assert resource['Mounts'][0]['Name']==CONTAINER+'-data'
        assert resource['Mounts'][0]['Destination']=='/var/lib/postgresql/data'
    inspect=docker(['inspect',CONTAINER,'--format','{{json .State.Running}} {{.HostConfig.NetworkMode}} {{json .NetworkSettings.Ports}}'])
except RuntimeError:
    print(json.dumps({'staticChecks':static,'actualPostgreSQL':False,'reason':'approved_container_unavailable','newDatabaseCreated':False}));raise SystemExit(0)
if not inspect.startswith('true none '):
    print(json.dumps({'staticChecks':static,'actualPostgreSQL':False,'reason':'approved_container_stopped_or_not_isolated','newDatabaseCreated':False}));raise SystemExit(0)
if docker(['exec',CONTAINER,'df','-B1','/var/lib/postgresql/data']).splitlines():
    free=int(docker(['exec',CONTAINER,'df','-B1','/var/lib/postgresql/data']).splitlines()[-1].split()[3])
    if free<64*1024*1024:
        print(json.dumps({'staticChecks':static,'actualPostgreSQL':False,'reason':'isolated_storage_limit','newDatabaseCreated':False}));raise SystemExit(0)
db='saved_count_'+uuid4().hex[:16]
docker(['exec',CONTAINER,'createdb','-U','postgres',db])
print(json.dumps({'newDatabase':db,'container':CONTAINER}),flush=True)
def sql(body):return docker(['exec','-i',CONTAINER,'psql','-X','-U','postgres','-d',db,'-v','ON_ERROR_STOP=1','-qAt'],body)
def role(name,body,owner=''):
    return sql(f"begin;set local role {name};select set_config('request.jwt.claim.sub','{owner}',true);{body};commit;").splitlines()[-1]
A='00000000-0000-4000-8000-000000000001';B='00000000-0000-4000-8000-000000000002'
sql("""create schema auth;create table auth.users(id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
grant usage on schema auth to anon,authenticated,service_role;
create table public.curations(id uuid primary key,slug text not null,user_category text,is_published boolean,
 title_ko text,summary_ko text,content_ko text,title_ja text,summary_ja text,content_ja text,
 application_deadline_kind text,application_deadline_on date);
alter table public.curations enable row level security;
grant select on public.curations to anon,authenticated;
create policy public_read on public.curations for select to anon,authenticated using(is_published);
"""
+f"insert into auth.users values('{A}'),('{B}');")
for f in ['20261001000100_saved_information.sql','20261001000200_saved_information_resume.sql','20261001000300_saved_information_order.sql']:
    sql((ROOT/'supabase/migrations'/f).read_text(encoding='utf-8'))
# Preserve real synthetic predecessor rows while checking installation atomicity.
legacy_ids={c:str(uuid4()) for c in ['policy','program']}
for category,item in legacy_ids.items():
    sql(f"insert into public.curations values('{item}','legacy-{category}','{category}',true,'한국어','한국어','한국어','日本語','日本語','日本語',null,null)")
legacy_item=legacy_ids['policy']
role('authenticated',f"select public.save_information('{legacy_item}','0')",B)
legacy_token=json.loads(role('anon',f"select public.prepare_saved_information_intent('{legacy_item}')"))['token']
assert json.loads(role('authenticated',f"select public.resume_saved_information('{legacy_token}','{legacy_item}')",A))['outcome']=='saved'
role('authenticated',f"select public.remove_saved_information('{legacy_item}')",A)
legacy_version=json.loads(role('authenticated',f"select public.saved_information_state('{legacy_item}')",A))['version']
role('authenticated',f"select public.save_information('{legacy_item}','{legacy_version}')",A)

def fingerprint():
    return sql("""select jsonb_build_object(
      'data',jsonb_build_array(
        (select coalesce(jsonb_agg(to_jsonb(t) order by user_id,original_curation_id),'[]') from machimoa_saved.information t),
        (select coalesce(jsonb_agg(to_jsonb(t) order by token),'[]') from machimoa_saved.intent_orders t),
        (select coalesce(jsonb_agg(to_jsonb(t) order by token),'[]') from machimoa_saved.resume_receipts t),
        (select coalesce(jsonb_agg(to_jsonb(t) order by user_id,scope),'[]') from machimoa_saved.resume_fences t),
        (select coalesce(jsonb_agg(to_jsonb(t) order by id),'[]') from public.curations t)),
      'functions',(select jsonb_agg(jsonb_build_array(p.oid::regprocedure::text,md5(pg_get_functiondef(p.oid)),p.proacl::text,p.proowner::regrole::text,p.proconfig) order by p.oid)
        from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('public','machimoa_saved','auth')),
      'schema',(select nspacl::text from pg_namespace where nspname='machimoa_saved'),
      'relations',(select jsonb_agg(jsonb_build_array(c.relname,c.relkind,c.relacl::text,c.relowner::regrole::text,c.relrowsecurity,c.relforcerowsecurity) order by c.relname)
        from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_saved'),
      'policies',(select jsonb_agg(jsonb_build_array(polname,polcmd,polroles::text,polpermissive,polqual::text,polwithcheck::text) order by polname) from pg_policy where polrelid='machimoa_saved.information'::regclass),
      'columns',(select jsonb_agg(jsonb_build_array(c.relname,a.attname,a.attacl::text) order by c.relname,a.attnum) from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_saved' and a.attnum>0 and not a.attisdropped),
      'sequence',(select jsonb_build_array(last_value,is_called) from machimoa_saved.operation_order));""")

baseline=fingerprint()
guard_checks=0
def rejected_transaction(body,message):
    before=fingerprint()
    try:
        sql('begin;'+body)
    except RuntimeError as e:
        assert message in str(e),(message,str(e))
    else:
        raise AssertionError('expected rejection: '+message)
    assert fingerprint()==before

# The repaired CASE must not suppress privileges on genuine sequences.
for privilege in ['USAGE','SELECT','UPDATE']:
    rejected_transaction(f"grant {privilege} on sequence machimoa_saved.operation_order to anon;"+up.replace('begin;','',1),'latent anonymous private access')
    guard_checks+=2
for mutation,message in [
    ("grant usage on sequence machimoa_saved.operation_order to authenticated;",'unexpected saved ordering sequence boundary'),
    ("grant select on sequence machimoa_saved.operation_order to service_role;",'unexpected saved ordering sequence boundary'),
    ("grant select(user_id) on machimoa_saved.information to anon;",'latent anonymous private access'),
    ("grant select(token) on machimoa_saved.resume_receipts to authenticated;",'unexpected private saved record boundary'),
    ("alter table machimoa_saved.intent_orders disable row level security;",'unexpected private saved record boundary'),
    ("alter policy saved_information_select_own on machimoa_saved.information using(true);",'unexpected account-owned saved policy'),
    ("revoke execute on function machimoa_saved.is_savable(public.curations) from authenticated;",'unexpected saved RPC boundary'),
    ("alter function public.saved_information_state(uuid) owner to authenticated;",'unexpected predecessor definition')]:
    rejected_transaction(mutation+up.replace('begin;','',1),message)
    guard_checks+=2
try:
    sql(up)
except RuntimeError as install_error:
    # A real install failure is reported as failure, never as a successful skip.
    assert fingerprint()==baseline
    diagnostics=1
    assert sql("select to_regprocedure('public.saved_information_count(uuid)') is null and to_regprocedure('machimoa_saved.public_information_count(uuid)') is null and to_regclass('machimoa_saved.saved_count_contract_backup') is null and to_regclass('machimoa_saved.saved_information_curation_count_idx') is null")=='t'
    diagnostics+=1
    if 'is not a sequence' in str(install_error):
        try:
            sql("select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_saved' and c.relkind='S' and has_sequence_privilege('anon',c.oid,'USAGE,SELECT,UPDATE')")
        except RuntimeError as e:
            assert 'is not a sequence' in str(e)
            diagnostics+=1
        else:
            raise AssertionError('sequence guard failure not reproduced')
        # Diagnostic SELECT only; never apply a rewritten migration or bypass its guard.
        assert sql("select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_saved' and case when c.relkind='S' then has_sequence_privilege('anon',c.oid,'USAGE,SELECT,UPDATE') else false end")=='0'
        diagnostics+=1
    assert sql("select count(*)=2 and bool_and(regexp_replace(pg_get_expr(polqual,polrelid),'[[:space:]]','','g')='((SELECTauth.uid()ASuid)=user_id)') from pg_policy where polrelid='machimoa_saved.information'::regclass")=='t'
    diagnostics+=1
    # Earlier guards can still be verified without disabling the failing guard.
    for mutation,message in [
        ("create table machimoa_saved.saved_count_contract_backup(test int);",'name collision'),
        ("create function public.saved_information_count(uuid) returns jsonb language sql as $$select '{}'::jsonb$$;",'name collision'),
        ("alter function public.save_information(uuid,text) security invoker;",'unexpected predecessor definition'),
        ("alter function public.save_information(uuid,text) set search_path=public;",'unexpected predecessor definition'),
        ("create or replace function machimoa_saved.is_savable(p_row public.curations) returns boolean language sql immutable security invoker set search_path='' as $$select false$$;",'unexpected predecessor definition'),
        ("grant usage on schema machimoa_saved to anon;",'unexpected saved table/schema boundary'),
        ("grant create on schema machimoa_saved to authenticated;",'unexpected saved table/schema boundary'),
        ("revoke usage on schema machimoa_saved from authenticated;",'unexpected saved table/schema boundary'),
        ("grant select on machimoa_saved.information to anon;",'unexpected saved table/schema boundary'),
        ("grant update on machimoa_saved.information to authenticated;",'unexpected saved table/schema boundary'),
        ("grant select on machimoa_saved.information to service_role;",'unexpected saved table/schema boundary'),
        ("alter table machimoa_saved.information disable row level security;",'unexpected saved table/schema boundary')]:
        try:
            sql('begin;'+mutation+up.replace('begin;','',1))
        except RuntimeError as e:
            assert message in str(e),(message,str(e))
        else:
            raise AssertionError('guard accepted '+message)
        assert fingerprint()==baseline
        diagnostics+=2
    print(json.dumps({'staticChecks':static,'actualPostgreSQL':True,'migrationApplied':False,
      'diagnosticChecks':diagnostics,'status':'failed_installation_guard','error':str(install_error).splitlines()[0],
      'newDatabase':db,'databasePreserved':True,'predecessorRowsAndDefinitionsPreserved':True,
      'aggregateConcurrencyAndRollback':'not_executed_installation_blocked'}),flush=True)
    raise SystemExit(1)
assert json.loads(fingerprint())['data']==json.loads(baseline)['data']
sql(down);assert sql("select to_regprocedure('public.saved_information_count(uuid)') is null")=='t'
assert fingerprint()==baseline
sql(up)
assert json.loads(fingerprint())['data']==json.loads(baseline)['data']
checks=4
# Independent transactional fixtures test each rollback record guard without
# erasing records to make rollback pass. The connection abort restores the case.
rollback_item=str(uuid4())
fixture=f"insert into public.curations values('{rollback_item}','rollback-event','event',true,'한국어','한국어','한국어','日本語','日本語','日本語',null,null);"
for record in [
    f"insert into machimoa_saved.information(user_id,original_curation_id,curation_id) values('{A}','{rollback_item}','{rollback_item}');",
    f"insert into machimoa_saved.intent_orders(token,curation_id,issued_order) values('{uuid4()}','{rollback_item}',1);",
    f"insert into machimoa_saved.resume_receipts(token,user_id,curation_id,outcome) values('{uuid4()}','{A}','{rollback_item}','saved');"]:
    rejected_transaction(fixture+record+down.replace('begin;','',1),'preserve data')
    checks+=2
rejected_transaction(f"delete from public.curations where id='{legacy_item}';"+down.replace('begin;','',1),'preserve data')
checks+=2
for drift in [
    "alter function public.saved_information_count(uuid) set search_path=public;",
    "grant execute on function public.saved_information_count(uuid) to service_role;",
    "grant select on machimoa_saved.information to anon;",
    "alter table machimoa_saved.information disable row level security;",
    "alter policy saved_information_select_own on machimoa_saved.information using(true);",
    "grant select(user_id) on machimoa_saved.information to anon;",
    "grant usage on sequence machimoa_saved.operation_order to anon;",
    "grant create on schema machimoa_saved to authenticated;",
    "alter index machimoa_saved.saved_information_curation_count_idx set (fillfactor=75);"]:
    rejected_transaction(drift+down.replace('begin;','',1),'subsequent definition')
    checks+=2
rejected_transaction(up.replace('begin;','',1),'name collision')
checks+=2
ids={c:str(uuid4()) for c in ['policy','program','event','youth_space','living']}
for c,id in ids.items():
    sql(f"insert into public.curations values('{id}','test-{c}','{c}',true,'한국어','한국어','한국어','日本語','日本語','日本語',null,null)")
    assert json.loads(role('anon',f"select public.saved_information_count('{id}')"))=={'id':id,'savedCount':0};checks+=1
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:role('authenticated',f"select public.save_information('{id}','0')",A),range(2)))
    assert all(json.loads(v)['saved'] for v in results)
    assert json.loads(role('anon',f"select public.saved_information_count('{id}')"))['savedCount']==1;checks+=2
    role('authenticated',f"select public.save_information('{id}','0')",B)
    assert json.loads(role('anon',f"select public.saved_information_count('{id}')"))['savedCount']==2;checks+=1
    role('authenticated',f"select public.remove_saved_information('{id}')",A)
    assert json.loads(role('anon',f"select public.saved_information_count('{id}')"))['savedCount']==1;checks+=1
    assert json.loads(role('authenticated',f"select public.save_information('{id}','0')",A))['outcome']=='stale';checks+=1
    token=json.loads(role('anon',f"select public.prepare_saved_information_intent('{id}')"))['token']
    assert json.loads(role('authenticated',f"select public.resume_saved_information('{token}','{id}')",A))['outcome']=='saved';checks+=1
    assert json.loads(role('authenticated',f"select public.resume_saved_information('{token}','{id}')",A))['outcome']=='consumed';checks+=1
assert sql("select not has_table_privilege('anon','machimoa_saved.information','SELECT')")=='t';checks+=1
assert len(json.loads(role('authenticated',"select public.list_saved_information('ko',25,0)",A))['items'])==6;checks+=1
assert role('authenticated','select count(*) from machimoa_saved.information',A)=='6';checks+=1
for table in ['information','intent_orders','resume_receipts','resume_fences']:
    try:role('anon',f'select * from machimoa_saved.{table}')
    except RuntimeError:checks+=1
    else:raise AssertionError('anon row access '+table)
for id in [ids['event'],str(uuid4())]:
    if id==ids['event']:sql(f"update public.curations set is_published=false where id='{id}'")
    try:role('anon',f"select public.saved_information_count('{id}')")
    except RuntimeError as e:assert 'information_unavailable' in str(e);checks+=1
    else:raise AssertionError('private count exposed')
try:sql(down)
except RuntimeError as e:assert 'preserve data' in str(e);checks+=1
else:raise AssertionError('rollback accepted new-category records')
# Transactional permission drift must block rollback and not alter existing rows.
try:sql("begin;alter policy saved_information_select_own on machimoa_saved.information using(true);"+down.replace('begin;','',1).rsplit('commit;',1)[0])
except RuntimeError as e:assert 'subsequent definition' in str(e);checks+=1
else:raise AssertionError('rollback overwrote later policy')
print(json.dumps({'staticChecks':static,'sqlChecks':checks,'sequenceAndBoundaryGuardChecks':guard_checks,'actualPostgreSQL':True,'newDatabase':db,'databasePreserved':True}))
