-- Restore functions only. Operator edits / change-review evidence are retained.
-- Roll back the matching app/CLI first; do not run against a later redefinition.
begin;
do $$ declare r record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 if exists(select 1 from machimoa_review.ingest_sources where source_id='myseoul_program' and enabled)
 or exists(select 1 from machimoa_review.source_sync_state where source_id='myseoul_program' and lease_expires_at>clock_timestamp())
 or exists(select 1 from machimoa_review.processing_jobs j join machimoa_review.source_items s on s.id=j.source_item_id where s.source_id='myseoul_program' and j.status='claimed') then
 raise exception 'disable_myseoul_and_finish_leases_before_rollback';end if;
 for r in select * from machimoa_review.myseoul_change_function_backup order by name loop
 if pg_get_functiondef(r.name::regprocedure) is distinct from r.installed then raise exception 'later_contract_requires_review: %',r.name;end if;
 end loop;
 for r in select * from machimoa_review.myseoul_change_function_backup order by name loop execute r.definition;end loop;
end $$;
drop function public.admin_myseoul_review_change(uuid,text,text,text,text,jsonb,uuid);
drop function public.myseoul_collection_state(uuid,text[]);
drop function public.finish_myseoul_collection(uuid,jsonb,integer,text,text);
-- Restricted audit/backup/cursor tables and private helpers stay for recovery.
-- This is not a content rollback, and the forward migration cannot be rerun as-is.
notify pgrst,'reload schema';
commit;
