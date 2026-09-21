-- Public PostgREST adapters for v4 upsert and gate-facts human resolve.
-- Do not apply this file without a separate operating-database approval.
-- apply_source_item_gate_facts / evaluate_source_item_gates have no public adapter.
-- resolve_source_item_product_type signature is unchanged.
-- Non-destructive rollback:
--   supabase/rollback/20260921000001_ingest_gate_facts_rpc_adapters_down.sql
--
-- Supabase CLI linked db push uses session_user=cli_login_postgres
-- with current_user=postgres. DDL authorization requires current_user=postgres.

begin;

do $guard$
begin
  if current_user <> 'postgres' then
    raise exception
      'ingest gate_facts adapters must run as postgres (current_user=%)',
      current_user;
  end if;

  if session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'ingest gate_facts adapters session_user not allowed (%)',
      session_user;
  end if;

  if pg_catalog.to_regprocedure(
       'machimoa_review.upsert_source_observations_v4(pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb)'
     ) is null then
    raise exception 'machimoa_review.upsert_source_observations_v4 signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.resolve_source_item_gate_facts(pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text, pg_catalog.text, pg_catalog.text)'
     ) is null then
    raise exception 'machimoa_review.resolve_source_item_gate_facts signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.apply_source_item_gate_facts(pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text, pg_catalog.text, pg_catalog.text)'
     ) is null then
    raise exception 'machimoa_review.apply_source_item_gate_facts signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.resolve_source_item_product_type(pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text, pg_catalog.text)'
     ) is null then
    raise exception 'machimoa_review.resolve_source_item_product_type signature is missing';
  end if;
end
$guard$;

create function public.resolve_source_item_gate_facts(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_gate_facts pg_catalog.jsonb,
  p_assessment_schema_version pg_catalog.text,
  p_reviewer pg_catalog.text,
  p_memo pg_catalog.text default null
)
returns table (
  source_item_id pg_catalog.uuid,
  revision_hash pg_catalog.text,
  product_type pg_catalog.text,
  disposition pg_catalog.text,
  assessment_schema_version pg_catalog.text,
  evaluated_profile pg_catalog.text,
  ai_job_id pg_catalog.uuid,
  ai_job_status pg_catalog.text,
  review_job_id pg_catalog.uuid,
  review_job_status pg_catalog.text,
  action_result pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
begin
  return query
  select *
  from machimoa_review.resolve_source_item_gate_facts(
    p_source_item_id,
    p_revision_hash,
    p_gate_facts,
    p_assessment_schema_version,
    p_reviewer,
    p_memo
  );
end
$function$;

create function public.upsert_source_observations_v4(
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
  from machimoa_review.upsert_source_observations_v4(
    p_source_id,
    p_run_id,
    p_items,
    p_next_checkpoint
  );
end
$function$;

alter function public.resolve_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) owner to postgres;
alter function public.upsert_source_observations_v4(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) owner to postgres;

revoke all privileges on function public.resolve_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function public.upsert_source_observations_v4(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) from public, anon, authenticated, service_role;

grant execute on function public.resolve_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) to service_role;
grant execute on function public.upsert_source_observations_v4(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) to service_role;

revoke all privileges on function machimoa_review.resolve_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.upsert_source_observations_v4(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.apply_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.evaluate_source_item_gates(
  pg_catalog.bool, pg_catalog.bool, pg_catalog.bool, pg_catalog.text,
  pg_catalog.text[], pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.apply_source_item_product_type_v4(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.ensure_ai_enrichment_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text[]
) from public, anon, authenticated, service_role;

notify pgrst, 'reload schema';

commit;
