-- Preserve observations, facts, review history and accepted schema pair.
-- Re-enabling requires a separately reviewed forward recovery migration.
begin;
do $$ begin if current_user <> 'postgres' then raise exception 'postgres_required';end if;end $$;
do $$ begin
 perform 1 from machimoa_review.source_sync_state where source_id='myseoul_program' for update;
 perform 1 from machimoa_review.source_items where source_id='myseoul_program' order by external_key for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id in
 (select id from machimoa_review.source_items where source_id='myseoul_program') order by source_item_id,revision_hash,processing_stage for update;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id in
 (select id from machimoa_review.source_items where source_id='myseoul_program') and status='claimed') or
 exists(select 1 from machimoa_review.source_sync_state where source_id='myseoul_program' and lease_expires_at>clock_timestamp()) then
 raise exception using errcode='PT409',message='myseoul_processing_active';end if;
 update machimoa_review.ingest_sources set enabled=false,updated_at=clock_timestamp() where source_id='myseoul_program';
 update machimoa_review.processing_jobs set status='cancelled',completed_at=clock_timestamp() where source_item_id in
 (select id from machimoa_review.source_items where source_id='myseoul_program') and status in ('queued','failed');
end $$;
drop function public.admin_myseoul_program_save(uuid,text,text,jsonb,text[],text,uuid);
drop function public.admin_myseoul_program_exclude(uuid,text,text,text,uuid);
drop function machimoa_review.myseoul_admin_lock(uuid,text,text,uuid);
drop function public.admin_myseoul_program_detail(uuid);
drop function public.observe_myseoul_program(uuid,jsonb,jsonb);
drop function public.finish_myseoul_run(uuid,jsonb,integer,integer);
drop function machimoa_review.myseoul_refresh(uuid,timestamptz);
drop function machimoa_review.myseoul_evaluate(jsonb,timestamptz);
drop function machimoa_review.myseoul_comparison(text,text);
drop function machimoa_review.myseoul_reason_fields(text);
drop function machimoa_review.myseoul_validate(jsonb);
drop function machimoa_review.myseoul_boundary(jsonb,boolean);
drop function machimoa_review.myseoul_strings(jsonb);
drop function machimoa_review.myseoul_url(text);
-- Shared CHECK expansion, run summary, source identity and all data stay.
commit;
