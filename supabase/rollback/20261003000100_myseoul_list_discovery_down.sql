-- Stop/change the list collector code first. Preserve discovery/audit rows.
begin;
do $$ begin
 if exists(select 1 from machimoa_review.ingest_sources where source_id='myseoul_program' and enabled) or
 exists(select 1 from machimoa_review.source_sync_state where source_id='myseoul_program' and lease_expires_at>clock_timestamp()) then
 raise exception using errcode='PT409',message='myseoul_rollback_active';end if;
end $$;
drop function public.finish_myseoul_list_collection(uuid,integer,boolean);
drop function public.record_myseoul_detail_attempt(uuid,text,text);
drop function public.myseoul_pending_details(uuid);
drop function public.discover_myseoul_list_page(uuid,integer,integer,jsonb);
-- New restricted tables and all source/facts/history rows remain. No content rollback.
notify pgrst,'reload schema';
commit;
