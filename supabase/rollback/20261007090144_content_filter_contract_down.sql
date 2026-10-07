-- No record deletion. Restore is allowed only before any filter records exist.
begin;
set local lock_timeout='5s';
do $$ declare r record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 if exists(select 1 from machimoa_review.source_item_content_filters) or exists(select 1 from machimoa_review.content_filter_edits) or exists(select 1 from machimoa_review.content_filter_claim_inputs) or exists(select 1 from machimoa_review.candidate_content_filters) or exists(select 1 from public.curations where content_filters is not null) then raise exception 'content_filter_records_exist';end if;
 for r in select * from machimoa_review.content_filter_function_backup loop
 if pg_get_functiondef(to_regprocedure(r.name)) is distinct from r.installed or (select proacl::text from pg_proc where oid=to_regprocedure(r.name)) is distinct from r.installed_acl or (r.base_name is not null and (pg_get_functiondef(to_regprocedure(r.base_name)) is distinct from r.base_installed or (select proacl::text from pg_proc where oid=to_regprocedure(r.base_name)) is distinct from r.base_installed_acl)) then raise exception 'content_filter_successor_changed';end if;end loop;
 for r in select * from machimoa_review.content_filter_installed_objects loop
 if (r.kind='function' and (pg_get_functiondef(to_regprocedure(r.name)) is distinct from r.definition or (select proacl::text from pg_proc where oid=to_regprocedure(r.name)) is distinct from r.acl)) or (r.kind='trigger' and (select pg_get_triggerdef(oid) from pg_trigger where tgname=r.name and tgrelid='machimoa_review.processing_jobs'::regclass) is distinct from r.definition) then raise exception 'content_filter_successor_changed';end if;end loop;
end $$;
drop trigger content_filter_claim_capture on machimoa_review.processing_jobs;
drop function public.upsert_source_observations_v4(text,uuid,jsonb,jsonb);
drop function machimoa_review.admin_review_snapshot(text,uuid);
drop function machimoa_review.admin_review_item(text,uuid);
drop function public.admin_myseoul_program_detail(uuid);
drop function public.admin_program_detail(uuid);
drop function machimoa_review.myseoul_refresh(uuid,timestamp with time zone);
drop function machimoa_review.program_refresh(uuid,timestamp with time zone);
drop function public.admin_review_save_facts(uuid,text,text,jsonb,uuid);
drop function public.admin_review_save_candidate(uuid,text,text,jsonb,uuid);
drop function public.admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid);
drop function machimoa_review.publish_curation_candidate(uuid,text,text,boolean);
drop function public.enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text);
do $$ declare r record;a record;begin
 for r in select * from machimoa_review.content_filter_function_backup loop
 execute r.definition;
 execute format('revoke all on function %s from public,anon,authenticated,service_role',r.name);
 for a in select case when grantee=0 then 'public' else pg_get_userbyid(grantee) end role from aclexplode(coalesce(r.acl::aclitem[],acldefault('f',(select proowner from pg_proc where oid=to_regprocedure(r.name))))) where privilege_type='EXECUTE' loop execute format('grant execute on function %s to %I',r.name,a.role);end loop;
 end loop;end $$;
drop function machimoa_review.cf_base_pub_upsert_source_observations_v4(text,uuid,jsonb,jsonb);
drop function machimoa_review.cf_base_admin_review_snapshot(text,uuid);
drop function machimoa_review.cf_base_admin_review_item(text,uuid);
drop function machimoa_review.cf_base_pub_admin_myseoul_program_detail(uuid);
drop function machimoa_review.cf_base_pub_admin_program_detail(uuid);
drop function machimoa_review.cf_base_myseoul_refresh(uuid,timestamp with time zone);
drop function machimoa_review.cf_base_program_refresh(uuid,timestamp with time zone);
drop function machimoa_review.cf_base_pub_admin_review_save_facts(uuid,text,text,jsonb,uuid);
drop function machimoa_review.cf_base_pub_admin_review_save_candidate(uuid,text,text,jsonb,uuid);
drop function machimoa_review.cf_base_pub_admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid);
drop function machimoa_review.cf_base_publish_curation_candidate(uuid,text,text,boolean);
drop function machimoa_review.cf_base_pub_enqueue_curation_candidate(text,text,text,text,text,text,jsonb,text,text,text,text,text,text,text,text,text);
drop function public.finish_content_filter_ai(uuid,text,bigint,timestamp with time zone,timestamp with time zone,text,jsonb);
drop function public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid);
drop function public.admin_content_filter_detail(uuid);
do $$ declare r record;begin for r in select p.oid::regprocedure name from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_review' and p.proname like 'content_filter_%' loop execute format('drop function %s',r.name);end loop;end $$;
drop table machimoa_review.candidate_content_filters,machimoa_review.content_filter_claim_inputs,machimoa_review.content_filter_edits,machimoa_review.source_item_content_filters,machimoa_review.content_filter_function_backup,machimoa_review.content_filter_installed_objects;
alter table public.curations drop column content_filters;
notify pgrst,'reload schema';
commit;
