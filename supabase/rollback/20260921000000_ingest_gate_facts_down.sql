-- Roll back V1 gate_facts columns, v4 upsert, DB evaluator, and split AI paths.
-- Apply after 20260921000001_ingest_gate_facts_rpc_adapters_down.sql.
-- Restores claim/ensure bodies to the 20260918000000 contract.
-- Do not delete curation_candidates, public.curations, ingest_review_decisions,
-- source_items, or completed AI result rows.
-- This file is not auto-applied.
-- Fail closed if V1 gate_facts rows or living_guide product types exist.

begin;

do $preflight$
begin
  lock table machimoa_review.source_item_product_types
    in access exclusive mode;
  lock table machimoa_review.processing_jobs
    in access exclusive mode;
  if exists (
    select 1
    from machimoa_review.source_item_product_types as pt
    where pt.gate_facts is not null
       or pt.assessment_schema_version is not null
       or pt.evaluated_profile is not null
       or pt.evaluated_at is not null
  ) then
    raise exception 'rollback_gate_facts_data_present';
  end if;
  if exists (
    select 1
    from machimoa_review.source_item_product_types as pt
    where pt.product_type = 'living_guide'
  ) then
    raise exception 'rollback_gate_facts_data_present';
  end if;
end
$preflight$;

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
    join machimoa_review.source_items as si
      on si.id = j.source_item_id
     and si.revision_hash is not distinct from j.revision_hash
    where j.processing_stage = 'ai_enrichment'
      and si.disposition = 'target'
      and si.body_usable is true
      and si.has_source_url is true
      and (
        (
          j.status = 'queued'
          and j.available_at <= v_now
          and (j.next_retry_at is null or j.next_retry_at <= v_now)
        )
        or (
          j.status = 'claimed'
          and j.claim_lease_until is not null
          and j.claim_lease_until <= v_now
        )
      )
      and exists (
        select 1
        from machimoa_review.ingest_review_decisions as d
        where d.source_item_id = j.source_item_id
          and d.revision_hash is not distinct from j.revision_hash
          and d.decision = 'approve_ai'
      )
      and exists (
        select 1
        from machimoa_review.source_item_product_types as pt
        where pt.source_item_id = j.source_item_id
          and pt.revision_hash is not distinct from j.revision_hash
      )
      and not exists (
        select 1
        from machimoa_review.processing_jobs as r
        where r.source_item_id = j.source_item_id
          and r.revision_hash is not distinct from j.revision_hash
          and r.processing_stage in (
            'region_review',
            'relevance_review',
            'content_review',
            'product_type_review'
          )
          and r.status in ('queued', 'claimed')
      )
    order by j.queued_at, j.id
    for update of j skip locked
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

create or replace function machimoa_review.ensure_ai_enrichment_job(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_reason_codes pg_catalog.text[]
)
returns pg_catalog.void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_hash pg_catalog.text := pg_catalog.btrim(coalesce(p_revision_hash, ''));
  v_reasons pg_catalog.text[] := coalesce(p_reason_codes, '{}'::pg_catalog.text[]);
  v_item machimoa_review.source_items%rowtype;
  v_ai machimoa_review.processing_jobs%rowtype;
  v_ready pg_catalog.bool := false;
begin
  select *
    into v_item
  from machimoa_review.source_items as si
  where si.id = p_source_item_id
  for update;
  if not found then
    return;
  end if;

  select *
    into v_ai
  from machimoa_review.processing_jobs as j
  where j.source_item_id = v_item.id
    and j.revision_hash = v_hash
    and j.processing_stage = 'ai_enrichment'
  for update;

  v_ready :=
    v_item.revision_hash is not distinct from v_hash
    and v_item.disposition = 'target'
    and v_item.body_usable is true
    and v_item.has_source_url is true
    and exists (
      select 1
      from machimoa_review.ingest_review_decisions as d
      where d.source_item_id = v_item.id
        and d.revision_hash is not distinct from v_hash
        and d.decision = 'approve_ai'
    )
    and not exists (
      select 1
      from machimoa_review.ingest_review_decisions as d
      where d.source_item_id = v_item.id
        and d.revision_hash is not distinct from v_hash
        and d.decision = 'reject'
    )
    and not exists (
      select 1
      from machimoa_review.processing_jobs as r
      where r.source_item_id = v_item.id
        and r.revision_hash is not distinct from v_hash
        and r.processing_stage in (
          'region_review',
          'relevance_review',
          'content_review',
          'product_type_review'
        )
        and r.status in ('queued', 'claimed')
    )
    and exists (
      select 1
      from machimoa_review.source_item_product_types as pt
      where pt.source_item_id = v_item.id
        and pt.revision_hash is not distinct from v_hash
    );

  if found
     and v_ai.status = 'claimed'
     and v_ai.claim_lease_until is null then
    if v_ready then
      raise exception 'ai_job_malformed_lease';
    end if;
    return;
  end if;

  if not v_ready then
    return;
  end if;

  if v_ai.id is null then
    insert into machimoa_review.processing_jobs (
      source_item_id,
      revision_hash,
      processing_stage,
      status,
      queued_at,
      available_at,
      reason_codes
    )
    values (
      v_item.id,
      v_hash,
      'ai_enrichment',
      'queued',
      v_now,
      v_now,
      v_reasons
    );
    return;
  end if;

  if v_ai.status = 'cancelled'
     or (
       v_ai.status = 'claimed'
       and v_ai.claim_lease_until is not null
       and v_ai.claim_lease_until <= v_now
     ) then
    update machimoa_review.processing_jobs as j
    set
      status = 'queued',
      available_at = v_now,
      claimed_by = null,
      claim_lease_until = null,
      claimed_at = null,
      next_retry_at = null,
      reason_codes = v_reasons
    where j.id = v_ai.id;
  end if;
end
$function$;

drop function if exists machimoa_review.upsert_source_observations_v4(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
);
drop function if exists machimoa_review.resolve_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
);
drop function if exists machimoa_review.apply_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
);
drop function if exists machimoa_review.apply_source_item_product_type_v4(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.jsonb
);
drop function if exists machimoa_review.apply_source_item_evaluation(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text[],
  pg_catalog.jsonb
);
drop function if exists machimoa_review.sync_source_item_evaluation_jobs(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb
);
drop function if exists machimoa_review.evaluate_source_item_gates(
  pg_catalog.bool, pg_catalog.bool, pg_catalog.bool, pg_catalog.text,
  pg_catalog.text[], pg_catalog.jsonb
);
drop function if exists machimoa_review.gate_facts_row_is_complete_v1(
  pg_catalog.text, pg_catalog.jsonb, pg_catalog.text, pg_catalog.text,
  pg_catalog.timestamptz, pg_catalog.text
);
drop function if exists machimoa_review.validate_gate_facts(
  pg_catalog.text, pg_catalog.jsonb
);
drop function if exists machimoa_review.gate_facts_row_is_legacy(
  pg_catalog.jsonb, pg_catalog.text, pg_catalog.text, pg_catalog.timestamptz
);

alter table machimoa_review.source_item_product_types
  drop constraint if exists source_item_product_types_gate_state_ck;

alter table machimoa_review.source_item_product_types
  drop constraint if exists source_item_product_types_type_ck;

alter table machimoa_review.source_item_product_types
  drop column if exists gate_facts,
  drop column if exists assessment_schema_version,
  drop column if exists evaluated_profile,
  drop column if exists evaluated_at;

alter table machimoa_review.source_item_product_types
  add constraint source_item_product_types_type_ck
  check (product_type in ('event_program', 'policy_reference'));

alter function machimoa_review.ensure_ai_enrichment_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text[]
) owner to postgres;
alter function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) owner to postgres;

revoke all privileges on function machimoa_review.ensure_ai_enrichment_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text[]
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) from public, anon, authenticated, service_role;

commit;
