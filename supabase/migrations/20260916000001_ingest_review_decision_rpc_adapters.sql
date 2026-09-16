-- Public PostgREST adapters for ingest review-decision RPCs and v2 upsert.
-- Do not apply this file without a separate operating-database approval.
-- Private 00000/00001/00002 function signatures stay frozen except
-- claim_processing_jobs body replacement in 20260916000000.
-- apply_ingest_review_decision has no public adapter.
-- Non-destructive rollback:
--   supabase/rollback/20260916000001_ingest_review_decision_rpc_adapters_down.sql
--
-- Supabase CLI linked db push uses session_user=cli_login_postgres
-- with current_user=postgres. DDL authorization requires current_user=postgres.

begin;

do $guard$
begin
  if current_user <> 'postgres' then
    raise exception
      'ingest review decision adapters must run as postgres (current_user=%)',
      current_user;
  end if;

  if session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'ingest review decision adapters session_user not allowed (%)',
      session_user;
  end if;

  if pg_catalog.to_regclass('machimoa_review.ingest_review_decisions') is null then
    raise exception 'machimoa_review.ingest_review_decisions must exist';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.apply_ingest_review_decision(pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text, pg_catalog.text)'
     ) is null then
    raise exception 'machimoa_review.apply_ingest_review_decision signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.resolve_ingest_review_decision(pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text, pg_catalog.text)'
     ) is null then
    raise exception 'machimoa_review.resolve_ingest_review_decision signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.reconcile_queued_ai_job(pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text, pg_catalog.text)'
     ) is null then
    raise exception 'machimoa_review.reconcile_queued_ai_job signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.upsert_source_observations_v2(pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb)'
     ) is null then
    raise exception 'machimoa_review.upsert_source_observations_v2 signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.claim_processing_jobs(pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4)'
     ) is null then
    raise exception 'machimoa_review.claim_processing_jobs signature is missing';
  end if;
end
$guard$;

create function public.resolve_ingest_review_decision(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_review_type pg_catalog.text,
  p_decision pg_catalog.text,
  p_region_scope pg_catalog.text,
  p_audience_relevance pg_catalog.text[],
  p_reason_codes pg_catalog.text[],
  p_rule_version pg_catalog.text,
  p_reviewer pg_catalog.text,
  p_memo pg_catalog.text default null
)
returns table (
  decision_id pg_catalog.uuid,
  source_item_id pg_catalog.uuid,
  revision_hash pg_catalog.text,
  review_type pg_catalog.text,
  decision pg_catalog.text,
  ai_job_id pg_catalog.uuid,
  ai_job_status pg_catalog.text,
  review_job_id pg_catalog.uuid,
  review_job_status pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
begin
  return query
  select *
  from machimoa_review.resolve_ingest_review_decision(
    p_source_item_id,
    p_revision_hash,
    p_review_type,
    p_decision,
    p_region_scope,
    p_audience_relevance,
    p_reason_codes,
    p_rule_version,
    p_reviewer,
    p_memo
  );
end
$function$;

create function public.reconcile_queued_ai_job(
  p_job_id pg_catalog.uuid,
  p_action pg_catalog.text,
  p_review_type pg_catalog.text,
  p_region_scope pg_catalog.text,
  p_audience_relevance pg_catalog.text[],
  p_reason_codes pg_catalog.text[],
  p_rule_version pg_catalog.text,
  p_reviewer pg_catalog.text,
  p_memo pg_catalog.text default null
)
returns table (
  action_result pg_catalog.text,
  decision_id pg_catalog.uuid,
  source_item_id pg_catalog.uuid,
  revision_hash pg_catalog.text,
  review_type pg_catalog.text,
  decision pg_catalog.text,
  ai_job_id pg_catalog.uuid,
  ai_job_status pg_catalog.text,
  review_job_id pg_catalog.uuid,
  review_job_status pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
begin
  return query
  select *
  from machimoa_review.reconcile_queued_ai_job(
    p_job_id,
    p_action,
    p_review_type,
    p_region_scope,
    p_audience_relevance,
    p_reason_codes,
    p_rule_version,
    p_reviewer,
    p_memo
  );
end
$function$;

create function public.upsert_source_observations_v2(
  p_source_id pg_catalog.text,
  p_run_id pg_catalog.uuid,
  p_items pg_catalog.jsonb,
  p_next_checkpoint pg_catalog.jsonb
)
returns table (
  input_index pg_catalog.int4,
  external_key pg_catalog.text,
  outcome pg_catalog.text,
  duplicate_in_batch pg_catalog.bool
)
language plpgsql
security definer
set search_path = ''
as $function$
begin
  return query
  select *
  from machimoa_review.upsert_source_observations_v2(
    p_source_id,
    p_run_id,
    p_items,
    p_next_checkpoint
  );
end
$function$;

alter function public.resolve_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) owner to postgres;
alter function public.reconcile_queued_ai_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
) owner to postgres;
alter function public.upsert_source_observations_v2(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) owner to postgres;

revoke all privileges on function public.resolve_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function public.reconcile_queued_ai_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function public.upsert_source_observations_v2(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) from public, anon, authenticated, service_role;

grant execute on function public.resolve_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) to service_role;
grant execute on function public.reconcile_queued_ai_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
) to service_role;
grant execute on function public.upsert_source_observations_v2(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) to service_role;

revoke all privileges on function machimoa_review.apply_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.resolve_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.reconcile_queued_ai_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.upsert_source_observations_v2(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) from public, anon, authenticated, service_role;

notify pgrst, 'reload schema';

commit;
