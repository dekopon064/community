-- A targeted canary reuses the existing eligibility gate and rolls back the
-- claim if another queued job wins. It never returns a different item to AI.
create function public.claim_processing_job_for_source_item(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_worker_id pg_catalog.text,
  p_lease_seconds pg_catalog.int4
)
returns table (
  job_id pg_catalog.uuid,
  source_item_id pg_catalog.uuid,
  source_id pg_catalog.text,
  external_key pg_catalog.text,
  revision_hash pg_catalog.text,
  processing_stage pg_catalog.text,
  curation_source pg_catalog.text,
  normalized_payload pg_catalog.jsonb,
  disposition pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_job record;
begin
  if p_source_item_id is null
     or p_revision_hash is null
     or p_revision_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid_ai_target';
  end if;

  select c.* into v_job
  from machimoa_review.claim_processing_jobs(
    'ai_enrichment', 1, p_worker_id, p_lease_seconds
  ) as c;
  if not found then
    return;
  end if;
  if v_job.source_item_id is distinct from p_source_item_id
     or v_job.revision_hash is distinct from p_revision_hash then
    -- The exception rolls back the other job's claim in this same transaction.
    raise exception 'ai_target_mismatch';
  end if;

  return query select
    v_job.job_id,
    v_job.source_item_id,
    v_job.source_id,
    v_job.external_key,
    v_job.revision_hash,
    v_job.processing_stage,
    v_job.curation_source,
    v_job.normalized_payload,
    v_job.disposition;
end
$function$;

alter function public.claim_processing_job_for_source_item(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.int4
) owner to postgres;
revoke all privileges on function public.claim_processing_job_for_source_item(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.int4
) from public, anon, authenticated, service_role;
grant execute on function public.claim_processing_job_for_source_item(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.int4
) to service_role;

notify pgrst, 'reload schema';
