begin;
set local lock_timeout='5s';set local statement_timeout='30s';
do $$ declare r record;begin
if current_user<>'postgres' then raise exception 'postgres_required';end if;
lock table machimoa_review.source_item_program_facts,machimoa_review.source_items,machimoa_review.myseoul_residence_reviews in access exclusive mode;
if exists(select 1 from machimoa_review.myseoul_residence_reviews) then raise exception 'residence_review_records_present';end if;
for r in select * from machimoa_review.residence_installed_objects loop
if r.kind='function' then
if to_regprocedure(r.name) is null or pg_get_functiondef(to_regprocedure(r.name)) is distinct from r.definition or (select jsonb_build_object('acl',proacl::text,'owner',pg_get_userbyid(proowner),'config',proconfig) from pg_proc where oid=to_regprocedure(r.name)) is distinct from r.metadata then raise exception 'residence_successor_changed: %',r.name;end if;
elsif r.kind='table' then
if machimoa_review.classification_table_metadata(r.name)::text is distinct from r.definition then raise exception 'residence_successor_table_changed';end if;
elsif (select pg_get_triggerdef(oid) from pg_trigger where tgrelid=to_regclass(r.metadata->>'table') and tgname=r.name) is distinct from r.definition then raise exception 'residence_successor_trigger_changed';end if;
end loop;end $$;
drop trigger invalidate_myseoul_residence on machimoa_review.source_item_program_facts;
drop trigger invalidate_myseoul_residence_revision on machimoa_review.source_items;
do $$ declare r record;begin for r in select * from machimoa_review.residence_function_backup loop execute r.definition;end loop;end $$;
drop function public.admin_myseoul_residence_confirm(uuid,text,text,boolean,text,text,jsonb,uuid,uuid);
drop function machimoa_review.invalidate_myseoul_residence();
drop function machimoa_review.myseoul_residence_confirmed(jsonb);
drop function machimoa_review.myseoul_residence_context(jsonb);
drop table machimoa_review.myseoul_residence_reviews,machimoa_review.residence_function_backup,machimoa_review.residence_installed_objects;
notify pgrst,'reload schema';commit;
