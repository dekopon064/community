-- Public PostgREST adapters for ingest RPCs.
-- Do not apply this file without a separate operating-database approval.
-- Private 00000/00001 function signatures stay frozen.
-- Non-destructive rollback:
--   supabase/rollback/20260914000000_ingest_public_rpc_adapters_down.sql
--
-- Supabase CLI linked db push uses session_user=cli_login_postgres
-- with current_user=postgres. DDL authorization requires current_user=postgres.

begin;

do $guard$
declare
  v_complete_result pg_catalog.text;
  v_fail_result pg_catalog.text;
  v_finish_result pg_catalog.text;
  v_complete_count pg_catalog.int4;
  v_fail_count pg_catalog.int4;
  v_finish_count pg_catalog.int4;
begin
  if current_user <> 'postgres' then
    raise exception
      'ingest public rpc adapters must run as postgres (current_user=%)',
      current_user;
  end if;

  if session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'ingest public rpc adapters session_user not allowed (%)',
      session_user;
  end if;

  if pg_catalog.to_regclass('machimoa_review.ingest_sources') is null then
    raise exception 'machimoa_review.ingest_sources must exist';
  end if;
  if pg_catalog.to_regclass('machimoa_review.ingest_runs') is null then
    raise exception 'machimoa_review.ingest_runs must exist';
  end if;
  if pg_catalog.to_regclass('machimoa_review.processing_jobs') is null then
    raise exception 'machimoa_review.processing_jobs must exist';
  end if;
  if pg_catalog.to_regclass('machimoa_review.source_publications') is null then
    raise exception 'machimoa_review.source_publications must exist';
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_attribute as a
    join pg_catalog.pg_class as c
      on c.oid = a.attrelid
    join pg_catalog.pg_namespace as n
      on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = 'curations'
      and a.attname = 'is_published'
      and a.attnum > 0
      and not a.attisdropped
  ) then
    raise exception 'public.curations.is_published must exist';
  end if;

  if pg_catalog.to_regprocedure(
       'machimoa_review.start_ingest_run(pg_catalog.text, pg_catalog.int4)'
     ) is null then
    raise exception 'machimoa_review.start_ingest_run signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.upsert_source_observations(pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb)'
     ) is null then
    raise exception 'machimoa_review.upsert_source_observations signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.finish_ingest_run(pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.int4, pg_catalog.bool, pg_catalog.int4)'
     ) is null then
    raise exception 'machimoa_review.finish_ingest_run signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.claim_processing_jobs(pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4)'
     ) is null then
    raise exception 'machimoa_review.claim_processing_jobs signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.complete_processing_job(pg_catalog.uuid, pg_catalog.text)'
     ) is null then
    raise exception 'machimoa_review.complete_processing_job signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.fail_processing_job(pg_catalog.uuid, pg_catalog.text, pg_catalog.text)'
     ) is null then
    raise exception 'machimoa_review.fail_processing_job signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.write_publication_lineage(pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.uuid, pg_catalog.uuid, pg_catalog.text, pg_catalog.text)'
     ) is null then
    raise exception 'machimoa_review.write_publication_lineage signature is missing';
  end if;

  select pg_catalog.count(*)
    into v_complete_count
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'machimoa_review'
    and p.proname = 'complete_processing_job';
  if v_complete_count is distinct from 1 then
    raise exception 'unexpected machimoa_review.complete_processing_job overloads';
  end if;

  select pg_catalog.count(*)
    into v_fail_count
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'machimoa_review'
    and p.proname = 'fail_processing_job';
  if v_fail_count is distinct from 1 then
    raise exception 'unexpected machimoa_review.fail_processing_job overloads';
  end if;

  select pg_catalog.count(*)
    into v_finish_count
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'machimoa_review'
    and p.proname = 'finish_ingest_run';
  if v_finish_count is distinct from 1 then
    raise exception 'unexpected machimoa_review.finish_ingest_run overloads';
  end if;

  select pg_catalog.pg_get_function_result(p.oid)
    into v_complete_result
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'machimoa_review'
    and p.proname = 'complete_processing_job';
  if v_complete_result is distinct from 'void' then
    raise exception
      'machimoa_review.complete_processing_job must return void';
  end if;

  select pg_catalog.pg_get_function_result(p.oid)
    into v_fail_result
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'machimoa_review'
    and p.proname = 'fail_processing_job';
  if v_fail_result is distinct from 'void' then
    raise exception 'machimoa_review.fail_processing_job must return void';
  end if;

  select pg_catalog.pg_get_function_result(p.oid)
    into v_finish_result
  from pg_catalog.pg_proc as p
  join pg_catalog.pg_namespace as n
    on n.oid = p.pronamespace
  where n.nspname = 'machimoa_review'
    and p.proname = 'finish_ingest_run';
  if v_finish_result is distinct from 'void' then
    raise exception 'machimoa_review.finish_ingest_run must return void';
  end if;
end
$guard$;

create function public.get_ingest_source(
  p_source_id pg_catalog.text
)
returns table (
  source_id pg_catalog.text,
  enabled pg_catalog.bool,
  permission_status pg_catalog.text,
  legacy_curation_source pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_source_id pg_catalog.text := pg_catalog.btrim(coalesce(p_source_id, ''));
begin
  return query
  select
    s.source_id,
    s.enabled,
    s.permission_status,
    s.legacy_curation_source
  from machimoa_review.ingest_sources as s
  where s.source_id = v_source_id;
end
$function$;

create function public.start_ingest_run(
  p_source_id pg_catalog.text,
  p_lease_seconds pg_catalog.int4 default 120
)
returns table (
  run_id pg_catalog.uuid,
  bootstrap_complete pg_catalog.bool,
  committed_checkpoint pg_catalog.jsonb,
  skipped pg_catalog.bool,
  skip_reason pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
begin
  return query
  select *
  from machimoa_review.start_ingest_run(p_source_id, p_lease_seconds);
end
$function$;

create function public.upsert_source_observations(
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
  from machimoa_review.upsert_source_observations(
    p_source_id,
    p_run_id,
    p_items,
    p_next_checkpoint
  );
end
$function$;

create function public.finish_ingest_run(
  p_run_id pg_catalog.uuid,
  p_status pg_catalog.text,
  p_stop_reason pg_catalog.text,
  p_http_request_count pg_catalog.int4,
  p_bootstrap_complete pg_catalog.bool default false,
  p_batches_ok pg_catalog.int4 default 0
)
returns table (
  status pg_catalog.text,
  stop_reason pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_found pg_catalog.bool := false;
begin
  select true
    into v_found
  from machimoa_review.ingest_runs as r
  where r.id = p_run_id;
  if not found then
    raise exception 'run not found';
  end if;

  perform machimoa_review.finish_ingest_run(
    p_run_id,
    p_status,
    p_stop_reason,
    p_http_request_count,
    p_bootstrap_complete,
    p_batches_ok
  );

  return query
  select r.status, r.stop_reason
  from machimoa_review.ingest_runs as r
  where r.id = p_run_id;
end
$function$;

create function public.claim_processing_jobs(
  p_stage pg_catalog.text,
  p_limit pg_catalog.int4,
  p_worker_id pg_catalog.text,
  p_lease_seconds pg_catalog.int4 default 300
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
begin
  return query
  select *
  from machimoa_review.claim_processing_jobs(
    p_stage,
    p_limit,
    p_worker_id,
    p_lease_seconds
  );
end
$function$;

create function public.complete_processing_job(
  p_job_id pg_catalog.uuid,
  p_worker_id pg_catalog.text
)
returns pg_catalog.text
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_status pg_catalog.text;
begin
  select j.status
    into v_status
  from machimoa_review.processing_jobs as j
  where j.id = p_job_id
  for update;
  if not found then
    raise exception 'job not found';
  end if;

  perform machimoa_review.complete_processing_job(p_job_id, p_worker_id);

  select j.status
    into v_status
  from machimoa_review.processing_jobs as j
  where j.id = p_job_id;
  if not found or v_status is distinct from 'completed' then
    raise exception 'complete_status_mismatch';
  end if;
  return 'completed';
end
$function$;

create function public.fail_processing_job(
  p_job_id pg_catalog.uuid,
  p_worker_id pg_catalog.text,
  p_error_code pg_catalog.text
)
returns pg_catalog.text
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_status pg_catalog.text;
begin
  select j.status
    into v_status
  from machimoa_review.processing_jobs as j
  where j.id = p_job_id
  for update;
  if not found then
    raise exception 'job not found';
  end if;

  perform machimoa_review.fail_processing_job(
    p_job_id,
    p_worker_id,
    p_error_code
  );

  select j.status
    into v_status
  from machimoa_review.processing_jobs as j
  where j.id = p_job_id;
  if not found or v_status not in ('queued', 'failed') then
    raise exception 'unexpected_job_status';
  end if;
  return v_status;
end
$function$;

alter function public.get_ingest_source(pg_catalog.text)
  owner to postgres;
alter function public.start_ingest_run(pg_catalog.text, pg_catalog.int4)
  owner to postgres;
alter function public.upsert_source_observations(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) owner to postgres;
alter function public.finish_ingest_run(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.int4,
  pg_catalog.bool, pg_catalog.int4
) owner to postgres;
alter function public.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) owner to postgres;
alter function public.complete_processing_job(
  pg_catalog.uuid, pg_catalog.text
) owner to postgres;
alter function public.fail_processing_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text
) owner to postgres;

revoke all privileges on function public.get_ingest_source(
  pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function public.start_ingest_run(
  pg_catalog.text, pg_catalog.int4
) from public, anon, authenticated, service_role;
revoke all privileges on function public.upsert_source_observations(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function public.finish_ingest_run(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.int4,
  pg_catalog.bool, pg_catalog.int4
) from public, anon, authenticated, service_role;
revoke all privileges on function public.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) from public, anon, authenticated, service_role;
revoke all privileges on function public.complete_processing_job(
  pg_catalog.uuid, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function public.fail_processing_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;

grant execute on function public.get_ingest_source(
  pg_catalog.text
) to service_role;
grant execute on function public.start_ingest_run(
  pg_catalog.text, pg_catalog.int4
) to service_role;
grant execute on function public.upsert_source_observations(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) to service_role;
grant execute on function public.finish_ingest_run(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.int4,
  pg_catalog.bool, pg_catalog.int4
) to service_role;
grant execute on function public.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) to service_role;
grant execute on function public.complete_processing_job(
  pg_catalog.uuid, pg_catalog.text
) to service_role;
grant execute on function public.fail_processing_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text
) to service_role;

notify pgrst, 'reload schema';

commit;
