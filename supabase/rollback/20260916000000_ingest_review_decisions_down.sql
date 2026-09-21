-- Roll back ingest review-decision table, private v2, core, and private RPCs.
-- Apply after 20260916000001_ingest_review_decision_rpc_adapters_down.sql.
-- Drop order is the reverse of create: private v2, reconcile, resolve, apply core.
-- Do not delete curation_candidates or public.curations.
-- Restores claim_processing_jobs body to the 20260913000000 contract.
-- This file is not auto-applied.
-- Fail closed if ingest_review_decisions rows or relevance_review jobs exist.
-- Do not delete or remap remaining Phase 2 rows. Clean databases may roll back fully.

begin;

do $preflight$
begin
  lock table machimoa_review.ingest_review_decisions
    in access exclusive mode;
  lock table machimoa_review.processing_jobs
    in access exclusive mode;
  if exists (
    select 1
    from machimoa_review.ingest_review_decisions
  ) then
    raise exception 'rollback_phase2_data_present';
  end if;
  if exists (
    select 1
    from machimoa_review.processing_jobs as j
    where j.processing_stage = 'relevance_review'
  ) then
    raise exception 'rollback_phase2_data_present';
  end if;
end
$preflight$;

drop function if exists machimoa_review.upsert_source_observations_v2(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
);
drop function if exists machimoa_review.reconcile_queued_ai_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
);
drop function if exists machimoa_review.resolve_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
);
drop function if exists machimoa_review.apply_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
);

create or replace function machimoa_review.claim_processing_jobs(
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
declare
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_limit pg_catalog.int4 := coalesce(p_limit, 10);
  v_worker pg_catalog.text := pg_catalog.btrim(coalesce(p_worker_id, ''));
  v_lease pg_catalog.int4 := coalesce(p_lease_seconds, 300);
begin
  if p_stage is distinct from 'ai_enrichment' then
    return;
  end if;
  if v_limit < 1 or v_limit > 10 then
    raise exception 'invalid claim limit';
  end if;
  if pg_catalog.char_length(v_worker) not between 1 and 64 then
    raise exception 'invalid worker_id';
  end if;

  return query
  with picked as (
    select j.id
    from machimoa_review.processing_jobs as j
    where j.processing_stage = 'ai_enrichment'
      and (
        (
          j.status = 'queued'
          and j.available_at <= v_now
          and (j.next_retry_at is null or j.next_retry_at <= v_now)
        )
        or (
          j.status = 'claimed'
          and j.claim_lease_until is not null
          and j.claim_lease_until < v_now
        )
      )
    order by j.queued_at, j.id
    for update skip locked
    limit v_limit
  ),
  updated as (
    update machimoa_review.processing_jobs as j
    set
      status = 'claimed',
      claimed_at = v_now,
      claim_lease_until = v_now + (v_lease || ' seconds')::pg_catalog.interval,
      claimed_by = v_worker
    from picked
    where j.id = picked.id
    returning j.*
  )
  select
    u.id,
    u.source_item_id,
    si.source_id,
    si.external_key,
    u.revision_hash,
    u.processing_stage,
    s.legacy_curation_source,
    si.normalized_payload,
    si.disposition
  from updated as u
  join machimoa_review.source_items as si
    on si.id = u.source_item_id
  join machimoa_review.ingest_sources as s
    on s.source_id = si.source_id;
end
$function$;

alter function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) owner to postgres;

revoke all privileges on function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) from public, anon, authenticated, service_role;

drop table if exists machimoa_review.ingest_review_decisions;

alter table machimoa_review.processing_jobs
  drop constraint if exists processing_jobs_stage_ck;

alter table machimoa_review.processing_jobs
  add constraint processing_jobs_stage_ck
  check (
    processing_stage in (
      'region_review',
      'content_review',
      'relationship_review',
      'ai_enrichment'
    )
  );

commit;
