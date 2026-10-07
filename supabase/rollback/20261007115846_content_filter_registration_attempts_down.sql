-- Restore only before related filter/attempt records exist. Never delete business data.
begin;set local lock_timeout='5s';
do $$ declare r record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 if exists(select 1 from machimoa_review.content_filter_enrollments) or exists(select 1 from machimoa_review.source_item_content_filters) or exists(select 1 from machimoa_review.content_filter_claim_inputs) then raise exception 'content_filter_gap_records_exist';end if;
 for r in select * from machimoa_review.content_filter_gap_backup union all select name,definition,acl,definition,acl from machimoa_review.content_filter_gap_installed loop
 if pg_get_functiondef(to_regprocedure(r.name)) is distinct from r.installed or (select proacl::text from pg_proc where oid=to_regprocedure(r.name)) is distinct from r.installed_acl then raise exception 'content_filter_gap_successor_changed';end if;end loop;
end $$;
do $$ declare r record;begin for r in select * from machimoa_review.content_filter_gap_backup loop execute r.definition;end loop;end $$;
drop function public.fail_content_filter_ai(uuid,text,bigint,timestamptz,timestamptz,text,text);
drop function machimoa_review.content_filter_register_pending(uuid,text);
drop table machimoa_review.content_filter_enrollments,machimoa_review.content_filter_gap_installed,machimoa_review.content_filter_gap_backup;
notify pgrst,'reload schema';commit;
