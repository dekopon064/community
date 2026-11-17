begin;

-- The frozen claim is diagnostic evidence. Return only the text needed to
-- locate the conflict; do not return claim credentials or the full snapshot.
create function public.admin_seoul_ai_failed_schedule(p_job uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object(
   'code', a.error_code,
   'description', coalesce(a.input_context #>> '{facts,description}', a.input_context #>> '{nativeConfirmedFacts,programFacts,description}', ''),
   'observed', coalesce(a.input_context #>> '{observedFacts,description}', a.input_context->>'body', ''),
   'draft', case when d.id is not null then public.admin_seoul_ai_draft(p_job) end)
 from machimoa_review.processing_jobs j
 join machimoa_review.source_items s on s.id=j.source_item_id and s.source_id='seoul_reservation'
 join machimoa_review.seoul_ai_no_retry_attempts a on a.job_id=j.id and a.source_item_id=s.id
  and a.revision_hash=j.revision_hash and a.closed_at=j.completed_at and a.error_code=j.error_code
 left join machimoa_review.seoul_ai_correction_drafts d on d.job_id=a.job_id and d.claimed_at=a.claimed_at
 where j.id=p_job and j.status='failed' and a.input_context->>'source'='seoul_reservation'
$$;
revoke all on function public.admin_seoul_ai_failed_schedule(uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_seoul_ai_failed_schedule(uuid) to service_role;

create function public.fail_seoul_ai_weekly_input(p_job_id uuid,p_revision text,p_claimed_at timestamptz,
 p_lease_until timestamptz,p_worker_id text,p_attempt text,p_error_code text) returns text
language sql security definer set search_path='' as $$
 select machimoa_review.fail_program_with_detail('seoul_reservation',p_job_id,p_revision,p_claimed_at,
   p_lease_until,p_worker_id,p_attempt,p_error_code,
   '{"stage":"claim","code":"ai_schema_error","rule":"weekly_schedule_cell","reason":"missing"}'::jsonb)
$$;
revoke all on function public.fail_seoul_ai_weekly_input(uuid,text,timestamptz,timestamptz,text,text,text) from public,anon,authenticated,service_role;
grant execute on function public.fail_seoul_ai_weekly_input(uuid,text,timestamptz,timestamptz,text,text,text) to service_role;
commit;
