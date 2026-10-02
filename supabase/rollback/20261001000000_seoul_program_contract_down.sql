-- Retain observation snapshots/facts/history for recovery; do not delete source rows.
-- This rollback disables the source and removes only the new executable API.
-- Completed/failed/claimed jobs are not rewritten. Abort if any claim is active.
begin;
do $$ begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 perform 1 from machimoa_review.source_sync_state where source_id='seoul_reservation' for update;
 perform 1 from machimoa_review.source_items where source_id='seoul_reservation' order by external_key for update;
 if exists(select 1 from machimoa_review.processing_jobs j join machimoa_review.source_items s on s.id=j.source_item_id
 where s.source_id='seoul_reservation' and j.status='claimed') then raise exception 'seoul_claim_active';end if;
end $$;
update machimoa_review.ingest_sources set enabled=false,updated_at=clock_timestamp() where source_id='seoul_reservation';
update machimoa_review.processing_jobs j set status='cancelled',completed_at=clock_timestamp()
from machimoa_review.source_items s where s.id=j.source_item_id and s.source_id='seoul_reservation' and j.status='queued';
drop function public.admin_program_exclude(uuid,text,text,text,uuid);
drop function public.admin_program_save(uuid,text,text,jsonb,text[],text,uuid);
drop function public.admin_program_list(integer,integer);
drop function public.admin_program_detail(uuid);
drop function public.observe_seoul_program(uuid,jsonb,jsonb);
drop function machimoa_review.program_refresh(uuid,timestamptz);
drop function machimoa_review.program_reason_fields(text);
drop function machimoa_review.program_evaluate(jsonb,timestamptz);
drop function machimoa_review.program_validate(jsonb);
-- source_item_program_facts retains versioned observations and operator facts.
-- Reapplication is a reviewed recovery migration, not rerunning this CREATE file.
commit;
