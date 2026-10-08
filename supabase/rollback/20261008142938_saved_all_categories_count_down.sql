-- Restore only this contract. Never delete bookmarks or intention/history rows.
-- Rollback is blocked once added categories have saved/intention/receipt records;
-- unidentified deleted targets also block rollback to preserve their supported path.
begin;
do $rollback$
declare prior text; expected jsonb; current_functions jsonb; expected_tables jsonb; schema_acl text; index_definition text;
begin
  if current_user <> 'postgres' then raise exception 'requires postgres'; end if;
  if to_regclass('machimoa_saved.saved_count_contract_backup') is null then raise exception 'contract backup missing'; end if;
  select prior_definition,installed_functions,installed_schema_acl,installed_index,installed_table_boundary
    into prior,expected,schema_acl,index_definition,expected_tables from machimoa_saved.saved_count_contract_backup where singleton;
  if prior is null or expected is null then raise exception 'incomplete contract backup'; end if;
  select jsonb_object_agg(sig, jsonb_build_object(
    'definition', md5(replace(pg_get_functiondef(sig::regprocedure), E'\r\n', E'\n')),
    'acl', coalesce(p.proacl::text,'NULL'), 'owner', pg_get_userbyid(p.proowner))) into current_functions
  from unnest(array['machimoa_saved.is_savable(public.curations)','public.save_information(uuid)','public.remove_saved_information(uuid)','public.saved_information_state(uuid)','public.list_saved_information(text,int4,int4)','public.cancel_saved_information_resume(uuid)','public.resume_saved_information(uuid,uuid,timestamptz)','machimoa_saved.current_version(uuid,uuid)','public.save_information(uuid,text)','public.prepare_saved_information_intent(uuid)','public.cancel_saved_information_intent(uuid)','public.resume_saved_information(uuid,uuid)','machimoa_saved.public_information_count(uuid)','public.saved_information_count(uuid)']) sig join pg_proc p on p.oid=to_regprocedure(sig);
  if current_functions is distinct from expected or (select jsonb_object_agg(c.relname,jsonb_build_object(
    'acl',coalesce(c.relacl::text,'NULL'),'rls',c.relrowsecurity,'forced',c.relforcerowsecurity,
    'owner',pg_get_userbyid(c.relowner),'policies',(select coalesce(jsonb_agg(jsonb_build_object(
      'name',polname,'roles',polroles::text,'command',polcmd,'permissive',polpermissive,
      'using',polqual::text,'check',polwithcheck::text) order by polname),'[]'::jsonb) from pg_policy where polrelid=c.oid),
    'columns',(select coalesce(jsonb_agg(jsonb_build_object('name',attname,'acl',attacl::text) order by attnum),'[]'::jsonb)
      from pg_attribute where attrelid=c.oid and attnum>0 and not attisdropped)))
  from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_saved'
    and c.relname in ('information','resume_receipts','resume_fences','intent_orders','operation_order')) is distinct from expected_tables
    or (select coalesce(nspacl::text,'NULL') from pg_namespace where nspname='machimoa_saved') is distinct from schema_acl
    or to_regclass('machimoa_saved.saved_information_curation_count_idx') is null
    or pg_get_indexdef('machimoa_saved.saved_information_curation_count_idx'::regclass) is distinct from index_definition then
    raise exception 'subsequent definition/permission/index change: rollback blocked';
  end if;
  lock table machimoa_saved.information,machimoa_saved.intent_orders,machimoa_saved.resume_receipts in share mode;
  if exists(select 1 from (
      select original_curation_id as id from machimoa_saved.information
      union select curation_id from machimoa_saved.intent_orders
      union select curation_id from machimoa_saved.resume_receipts
    ) used left join public.curations c on c.id=used.id
    where c.id is null or c.user_category is null or c.user_category not in ('policy','program')) then
    raise exception 'additional category or unidentified target records: preserve data and retain contract';
  end if;
  execute prior;
end $rollback$;
drop function public.saved_information_count(uuid);
drop function machimoa_saved.public_information_count(uuid);
drop index machimoa_saved.saved_information_curation_count_idx;
revoke usage on schema machimoa_saved from anon;
drop table machimoa_saved.saved_count_contract_backup;
notify pgrst, 'reload schema';
commit;
