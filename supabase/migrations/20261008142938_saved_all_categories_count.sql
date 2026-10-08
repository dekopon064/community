-- Expand only the existing eligibility gate and add an anonymous numeric aggregate.
-- No bookmark/resume/content rows are changed. Existing fences remain in force.
begin;
do $guard$
declare expected record; actual record;
begin
  if current_user <> 'postgres' then raise exception 'requires postgres'; end if;
  if to_regclass('machimoa_saved.saved_count_contract_backup') is not null
    or to_regprocedure('public.saved_information_count(uuid)') is not null
    or to_regprocedure('machimoa_saved.public_information_count(uuid)') is not null
    or to_regclass('machimoa_saved.saved_information_curation_count_idx') is not null then
    raise exception 'saved count contract already exists or name collision';
  end if;
  for expected in select * from (values
      ('machimoa_saved.is_savable(public.curations)','215cb6fa94b471573cfba4c665a26aa3','boolean','sql','i',false),
      ('public.save_information(uuid)','d0b2fa5d232fc9cbc20b9d74abb77ac2','jsonb','plpgsql','v',true),
      ('public.remove_saved_information(uuid)','b90a2ba989dea5901ded859d30f3a42c','jsonb','plpgsql','v',true),
      ('public.saved_information_state(uuid)','bc9fcc57e1293baa5bd6aa6ce51ec49c','jsonb','plpgsql','s',true),
      ('public.list_saved_information(text,int4,int4)','ec6c5867782ad8a9a9378da9e2bd0bb0','jsonb','plpgsql','s',false),
      ('public.cancel_saved_information_resume(uuid)','9eb3baa5cd43bb52251c16e8615c71ae','jsonb','plpgsql','v',true),
      ('public.resume_saved_information(uuid,uuid,timestamptz)','10de5781685746f6e282c24ce58f9907','jsonb','plpgsql','v',true),
      ('machimoa_saved.current_version(uuid,uuid)','95cb07ecad968125b625f95685b3c7b4','text','sql','s',false),
      ('public.save_information(uuid,text)','315450b8aa0dd5f644b54193bf26953d','jsonb','plpgsql','v',true),
      ('public.prepare_saved_information_intent(uuid)','96a628988c47097683bc15aa7b8ec737','jsonb','plpgsql','v',true),
      ('public.cancel_saved_information_intent(uuid)','f79dc073c13d1172dd0549597123d180','jsonb','plpgsql','v',true),
      ('public.resume_saved_information(uuid,uuid)','74cb8cd03fad466ad159c17079bd4b83','jsonb','plpgsql','v',true)
  ) x(signature,body_hash,result_type,language_name,volatility,definer) loop
    select p.*, l.lanname into actual from pg_proc p join pg_language l on l.oid=p.prolang
      where p.oid=to_regprocedure(expected.signature);
    if not found then raise exception 'missing predecessor: %',expected.signature; end if;
    if md5(replace(actual.prosrc,E'\r\n',E'\n')) <> expected.body_hash
      or actual.prorettype <> to_regtype(expected.result_type)
      or actual.lanname <> expected.language_name
      or actual.provolatile::text <> expected.volatility
      or actual.prosecdef <> expected.definer
      or actual.proconfig is distinct from array['search_path=""']::text[]
      or pg_get_userbyid(actual.proowner) <> 'postgres' then
      raise exception 'unexpected predecessor definition: %',expected.signature;
    end if;
  end loop;
  if has_schema_privilege('anon','machimoa_saved','USAGE')
    or has_schema_privilege('anon','machimoa_saved','CREATE')
    or has_schema_privilege('authenticated','machimoa_saved','CREATE')
    or not has_schema_privilege('authenticated','machimoa_saved','USAGE')
    or has_table_privilege('anon','machimoa_saved.information','SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
    or has_table_privilege('authenticated','machimoa_saved.information','INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
    or has_table_privilege('service_role','machimoa_saved.information','SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
    or not has_table_privilege('authenticated','machimoa_saved.information','SELECT')
    or not (select relrowsecurity and relowner='postgres'::regrole from pg_class where oid='machimoa_saved.information'::regclass)
    or not exists(select 1 from pg_constraint where conrelid='machimoa_saved.information'::regclass
      and conname='saved_information_pk' and contype='p'
      and pg_get_constraintdef(oid)='PRIMARY KEY (user_id, original_curation_id)') then
    raise exception 'unexpected saved table/schema boundary';
  end if;
  -- Before granting schema USAGE, reject latent anonymous table/column/function
  -- privileges throughout the private schema, including intentions and receipts.
  if exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='machimoa_saved' and c.relkind in ('r','p','v','m','f')
        and (has_table_privilege('anon',c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
          or has_any_column_privilege('anon',c.oid,'SELECT,INSERT,UPDATE,REFERENCES')))
    or exists(select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace
      where n.nspname='machimoa_saved' and has_function_privilege('anon',p.oid,'EXECUTE'))
    or exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='machimoa_saved'
        and case when c.relkind='S'
          then has_sequence_privilege('anon',c.oid,'USAGE,SELECT,UPDATE')
          else false end) then
    raise exception 'latent anonymous private access: schema usage grant blocked';
  end if;
  if (select count(*) from pg_policy where polrelid='machimoa_saved.information'::regclass) <> 2
    or exists(select 1 from pg_policy p where polrelid='machimoa_saved.information'::regclass
      and (polname not in ('saved_information_select_own','saved_information_delete_own')
        or polcmd <> case polname when 'saved_information_select_own' then 'r'::"char" else 'd'::"char" end
        or polroles is distinct from array['authenticated'::regrole::oid]
        or not polpermissive or polwithcheck is not null
        or regexp_replace(pg_get_expr(polqual,polrelid),'[[:space:]]','','g') is distinct from '((SELECTauth.uid()ASuid)=user_id)')) then
    raise exception 'unexpected account-owned saved policy';
  end if;
  for expected in select * from (values ('resume_receipts'),('resume_fences'),('intent_orders')) x(table_name) loop
    if to_regclass('machimoa_saved.'||expected.table_name) is null then raise exception 'missing private saved record table'; end if;
    if not (select relrowsecurity and relowner='postgres'::regrole from pg_class where oid=to_regclass('machimoa_saved.'||expected.table_name))
      or exists(select 1 from pg_policy where polrelid=to_regclass('machimoa_saved.'||expected.table_name))
      or has_table_privilege('authenticated',to_regclass('machimoa_saved.'||expected.table_name),'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
      or has_any_column_privilege('authenticated',to_regclass('machimoa_saved.'||expected.table_name),'SELECT,INSERT,UPDATE,REFERENCES')
      or has_table_privilege('service_role',to_regclass('machimoa_saved.'||expected.table_name),'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') then
      raise exception 'unexpected private saved record boundary: %',expected.table_name;
    end if;
  end loop;
  if has_sequence_privilege('anon','machimoa_saved.operation_order','USAGE,SELECT,UPDATE')
    or has_sequence_privilege('authenticated','machimoa_saved.operation_order','USAGE,SELECT,UPDATE')
    or has_sequence_privilege('service_role','machimoa_saved.operation_order','USAGE,SELECT,UPDATE') then
    raise exception 'unexpected saved ordering sequence boundary';
  end if;
  if has_function_privilege('anon','machimoa_saved.is_savable(public.curations)','EXECUTE')
    or has_function_privilege('service_role','machimoa_saved.is_savable(public.curations)','EXECUTE')
    or not has_function_privilege('authenticated','machimoa_saved.is_savable(public.curations)','EXECUTE')
    or has_function_privilege('anon','public.save_information(uuid,text)','EXECUTE')
    or not has_function_privilege('authenticated','public.save_information(uuid,text)','EXECUTE')
    or has_function_privilege('authenticated','public.save_information(uuid)','EXECUTE')
    or has_function_privilege('authenticated','public.resume_saved_information(uuid,uuid,timestamptz)','EXECUTE') then
    raise exception 'unexpected saved RPC boundary';
  end if;
end $guard$;
-- Lock schema-sensitive tables for a consistent install; no user row writes.
lock table machimoa_saved.information in share mode;
create table machimoa_saved.saved_count_contract_backup (
  singleton boolean primary key default true check(singleton),
  prior_definition text not null,
  installed_functions jsonb,
  installed_table_boundary jsonb,
  installed_schema_acl text,
  installed_index text
);
alter table machimoa_saved.saved_count_contract_backup owner to postgres;
alter table machimoa_saved.saved_count_contract_backup enable row level security;
revoke all on machimoa_saved.saved_count_contract_backup from public,anon,authenticated,service_role;
insert into machimoa_saved.saved_count_contract_backup(singleton,prior_definition)
  values(true,pg_get_functiondef('machimoa_saved.is_savable(public.curations)'::regprocedure));
create or replace function machimoa_saved.is_savable(p_row public.curations)
returns bool language sql immutable security invoker set search_path = '' as $f$
  select coalesce(p_row.is_published and p_row.user_category in ('policy','program','event','youth_space','living')
    and length(btrim(p_row.title_ko, U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')) > 0
    and length(btrim(p_row.summary_ko, U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')) > 0
    and length(btrim(p_row.content_ko, U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')) > 0
    and length(btrim(p_row.title_ja, U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')) > 0
    and length(btrim(p_row.summary_ja, U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')) > 0
    and length(btrim(p_row.content_ja, U&'\0009\000A\000B\000C\000D\0020\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000\FEFF')) > 0, false);
$f$;
create index saved_information_curation_count_idx on machimoa_saved.information(curation_id) where curation_id is not null;

-- Stable read: eligibility and the aggregate use the caller statement snapshot.
-- No auth.uid(), personal rows, account identifiers or private metadata returned.
create function machimoa_saved.public_information_count(p_curation_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $count$
declare result jsonb;
begin
  if p_curation_id is null then raise exception using errcode='22023',message='invalid_curation_id'; end if;
  select jsonb_build_object('id',c.id,'savedCount',
    (select count(*) from machimoa_saved.information s where s.curation_id=c.id))
    into result from public.curations c where c.id=p_curation_id and machimoa_saved.is_savable(c);
  if result is null then raise exception using errcode='PT404',message='information_unavailable'; end if;
  return result;
end $count$;
alter function machimoa_saved.public_information_count(uuid) owner to postgres;
revoke all on function machimoa_saved.public_information_count(uuid) from public,anon,authenticated,service_role;
-- Usage grants neither personal-table SELECT nor access to other private helpers.
grant usage on schema machimoa_saved to anon;
grant execute on function machimoa_saved.public_information_count(uuid) to anon,authenticated;
create function public.saved_information_count(p_curation_id uuid)
returns jsonb language sql stable security invoker set search_path = '' as $count$
  select machimoa_saved.public_information_count(p_curation_id);
$count$;
alter function public.saved_information_count(uuid) owner to postgres;
revoke all on function public.saved_information_count(uuid) from public,anon,authenticated,service_role;
grant execute on function public.saved_information_count(uuid) to anon,authenticated;
update machimoa_saved.saved_count_contract_backup set installed_functions=(select jsonb_object_agg(sig, jsonb_build_object(
    'definition', md5(replace(pg_get_functiondef(sig::regprocedure), E'\r\n', E'\n')),
    'acl', coalesce(p.proacl::text,'NULL'), 'owner', pg_get_userbyid(p.proowner)))
  from unnest(array['machimoa_saved.is_savable(public.curations)','public.save_information(uuid)','public.remove_saved_information(uuid)','public.saved_information_state(uuid)','public.list_saved_information(text,int4,int4)','public.cancel_saved_information_resume(uuid)','public.resume_saved_information(uuid,uuid,timestamptz)','machimoa_saved.current_version(uuid,uuid)','public.save_information(uuid,text)','public.prepare_saved_information_intent(uuid)','public.cancel_saved_information_intent(uuid)','public.resume_saved_information(uuid,uuid)','machimoa_saved.public_information_count(uuid)','public.saved_information_count(uuid)']) sig join pg_proc p on p.oid=to_regprocedure(sig)),
  installed_table_boundary=(select jsonb_object_agg(c.relname,jsonb_build_object(
    'acl',coalesce(c.relacl::text,'NULL'),'rls',c.relrowsecurity,'forced',c.relforcerowsecurity,
    'owner',pg_get_userbyid(c.relowner),'policies',(select coalesce(jsonb_agg(jsonb_build_object(
      'name',polname,'roles',polroles::text,'command',polcmd,'permissive',polpermissive,
      'using',polqual::text,'check',polwithcheck::text) order by polname),'[]'::jsonb) from pg_policy where polrelid=c.oid),
    'columns',(select coalesce(jsonb_agg(jsonb_build_object('name',attname,'acl',attacl::text) order by attnum),'[]'::jsonb)
      from pg_attribute where attrelid=c.oid and attnum>0 and not attisdropped)))
  from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_saved'
    and c.relname in ('information','resume_receipts','resume_fences','intent_orders','operation_order')),
  installed_schema_acl=(select coalesce(nspacl::text,'NULL') from pg_namespace where nspname='machimoa_saved'),
  installed_index=pg_get_indexdef('machimoa_saved.saved_information_curation_count_idx'::regclass)
  where singleton;
notify pgrst, 'reload schema';
commit;
