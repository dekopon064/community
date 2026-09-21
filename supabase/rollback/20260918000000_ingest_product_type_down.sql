-- Roll back product_type table, writers, v3, and claim/apply AND-read.
-- Apply after 20260918000001_ingest_product_type_rpc_adapters_down.sql.
-- Drop order is the reverse of create: v3, resolve, apply_source, ensure.
-- Restores claim/apply/reconcile bodies to the 20260916000000 contract.
-- Do not delete curation_candidates, public.curations, or ingest_review_decisions.
-- This file is not auto-applied.
-- Fail closed if confirmed product_type rows or product_type_review jobs exist.
-- Do not delete or remap remaining Phase 2/3 rows. Clean databases may roll back fully.
-- Job status CHECK is unchanged and must not add a sixth token.

begin;

do $preflight$
begin
  lock table machimoa_review.source_item_product_types
    in access exclusive mode;
  lock table machimoa_review.processing_jobs
    in access exclusive mode;
  if exists (
    select 1
    from machimoa_review.source_item_product_types
  ) then
    raise exception 'rollback_product_type_data_present';
  end if;
  if exists (
    select 1
    from machimoa_review.processing_jobs as j
    where j.processing_stage = 'product_type_review'
  ) then
    raise exception 'rollback_product_type_data_present';
  end if;
end
$preflight$;

-- Restore Phase 2 claim body (decision gate, no product_type AND, lease < now)
-- before dropping ensure_ai_enrichment_job.

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
          and j.claim_lease_until < v_now
        )
      )
      and exists (
        select 1
        from machimoa_review.ingest_review_decisions as d
        where d.source_item_id = j.source_item_id
          and d.revision_hash is not distinct from j.revision_hash
          and d.decision = 'approve_ai'
      )
      and not exists (
        select 1
        from machimoa_review.processing_jobs as r
        where r.source_item_id = j.source_item_id
          and r.revision_hash is not distinct from j.revision_hash
          and r.processing_stage in (
            'region_review',
            'relevance_review',
            'content_review'
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

-- Restore Phase 2 apply and reconcile by replacing product_type-era bodies.
-- Apply body is the 20260916000000 contract: inline AI insert/cancelled requeue,
-- no ensure_ai_enrichment_job, no product_type_review blocking, no malformed-lease raise.

create or replace function machimoa_review.reconcile_queued_ai_job(
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
declare
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_action pg_catalog.text := pg_catalog.btrim(coalesce(p_action, ''));
  v_job machimoa_review.processing_jobs%rowtype;
  v_item machimoa_review.source_items%rowtype;
  v_decision pg_catalog.text;
  v_reasons pg_catalog.text[] := coalesce(p_reason_codes, '{}'::pg_catalog.text[]);
  v_row record;
begin
  if p_job_id is null then
    raise exception 'job not found';
  end if;
  if v_action not in ('keep_with_approve', 'cancel_unfit', 'move_to_review') then
    raise exception 'invalid_reconcile_action';
  end if;

  select *
    into v_job
  from machimoa_review.processing_jobs as j
  where j.id = p_job_id
  for update;
  if not found then
    raise exception 'job not found';
  end if;
  if v_job.processing_stage is distinct from 'ai_enrichment' then
    raise exception 'unexpected_job_status';
  end if;
  if v_job.status = 'completed' then
    raise exception 'completed_job_not_reconcileable';
  end if;
  if v_job.status = 'failed' then
    raise exception 'unexpected_job_status';
  end if;
  if v_job.status = 'claimed'
     and v_job.claim_lease_until is not null
     and v_job.claim_lease_until > v_now then
    raise exception 'ai_job_claimed';
  end if;
  if v_job.status not in ('queued', 'claimed', 'cancelled') then
    raise exception 'unexpected_job_status';
  end if;

  select *
    into v_item
  from machimoa_review.source_items as si
  where si.id = v_job.source_item_id
  for update;
  if not found then
    raise exception 'source_item_not_found';
  end if;
  if v_item.revision_hash is distinct from v_job.revision_hash then
    raise exception 'revision_mismatch';
  end if;

  if v_action = 'keep_with_approve' then
    v_decision := 'approve_ai';
  elsif v_action = 'cancel_unfit' then
    v_decision := 'reject';
    if pg_catalog.cardinality(v_reasons) is null
       or pg_catalog.cardinality(v_reasons) < 1 then
      v_reasons := array['reconcile_unfit']::pg_catalog.text[];
    end if;
  else
    v_decision := 'needs_review';
    if pg_catalog.cardinality(v_reasons) is null
       or pg_catalog.cardinality(v_reasons) < 1 then
      v_reasons := array['needs_review']::pg_catalog.text[];
    end if;
  end if;

  select *
    into v_row
  from machimoa_review.apply_ingest_review_decision(
    v_item.id,
    v_item.revision_hash,
    p_review_type,
    v_decision,
    p_region_scope,
    p_audience_relevance,
    v_reasons,
    p_rule_version,
    p_reviewer,
    p_memo
  );

  return query select
    v_action,
    v_row.decision_id,
    v_row.source_item_id,
    v_row.revision_hash,
    v_row.review_type,
    v_row.decision,
    v_row.ai_job_id,
    v_row.ai_job_status,
    v_row.review_job_id,
    v_row.review_job_status;
end
$function$;

create or replace function machimoa_review.apply_ingest_review_decision(
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
declare
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_hash pg_catalog.text := pg_catalog.btrim(coalesce(p_revision_hash, ''));
  v_type pg_catalog.text := pg_catalog.btrim(coalesce(p_review_type, ''));
  v_decision pg_catalog.text := pg_catalog.btrim(coalesce(p_decision, ''));
  v_scope pg_catalog.text := pg_catalog.btrim(coalesce(p_region_scope, ''));
  v_axes pg_catalog.text[] := coalesce(p_audience_relevance, '{}'::pg_catalog.text[]);
  v_reasons pg_catalog.text[] := coalesce(p_reason_codes, '{}'::pg_catalog.text[]);
  v_rule pg_catalog.text := pg_catalog.btrim(coalesce(p_rule_version, ''));
  v_reviewer pg_catalog.text := pg_catalog.btrim(coalesce(p_reviewer, ''));
  v_memo pg_catalog.text := nullif(pg_catalog.btrim(coalesce(p_memo, '')), '');
  v_item machimoa_review.source_items%rowtype;
  v_existing machimoa_review.ingest_review_decisions%rowtype;
  v_decision_id pg_catalog.uuid;
  v_ai machimoa_review.processing_jobs%rowtype;
  v_review machimoa_review.processing_jobs%rowtype;
  v_review_stage pg_catalog.text;
  v_live_claimed pg_catalog.bool := false;
begin
  if p_source_item_id is null then
    raise exception 'source_item_not_found';
  end if;
  if v_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'revision_mismatch';
  end if;
  if v_type not in ('region', 'relevance') then
    raise exception 'invalid_review_type';
  end if;
  if v_decision not in ('approve_ai', 'reject', 'needs_review') then
    raise exception 'invalid_decision';
  end if;
  if v_scope not in (
    'capital',
    'nationwide_or_online',
    'noncapital',
    'unknown'
  ) then
    raise exception 'invalid_region_scope';
  end if;
  if pg_catalog.char_length(v_rule) not between 1 and 64 then
    raise exception 'invalid_rule_version';
  end if;
  if pg_catalog.char_length(v_reviewer) not between 1 and 128 then
    raise exception 'invalid_reviewer';
  end if;
  if v_memo is not null and pg_catalog.char_length(v_memo) > 500 then
    raise exception 'invalid_memo';
  end if;
  if exists (
    select 1
    from pg_catalog.unnest(v_axes) as axis
    where axis not in (
      'jp_residents_in_kr',
      'foreign_residents_in_kr',
      'kr_japan_activity',
      'kr_jp_exchange'
    )
  ) then
    raise exception 'invalid_audience_relevance';
  end if;
  if v_decision = 'approve_ai'
     and (
       pg_catalog.cardinality(v_axes) is null
       or pg_catalog.cardinality(v_axes) < 1
       or v_scope not in ('capital', 'nationwide_or_online')
     ) then
    raise exception 'approve_requirements_not_met';
  end if;

  select *
    into v_item
  from machimoa_review.source_items as si
  where si.id = p_source_item_id
  for update;
  if not found then
    raise exception 'source_item_not_found';
  end if;
  if v_item.revision_hash is distinct from v_hash then
    raise exception 'revision_mismatch';
  end if;

  select *
    into v_existing
  from machimoa_review.ingest_review_decisions as d
  where d.source_item_id = v_item.id
    and d.revision_hash = v_hash
    and d.review_type = v_type
  for update;

  if found then
    if v_existing.decision is not distinct from v_decision then
      null;
    elsif v_existing.decision = 'needs_review'
          and v_decision in ('approve_ai', 'reject') then
      null;
    else
      raise exception 'decision_conflict';
    end if;
    update machimoa_review.ingest_review_decisions as d
    set
      decision = v_decision,
      region_scope = v_scope,
      audience_relevance = v_axes,
      reason_codes = v_reasons,
      rule_version = v_rule,
      reviewer = v_reviewer,
      reviewed_at = v_now,
      memo = v_memo,
      updated_at = v_now
    where d.id = v_existing.id
    returning d.id into v_decision_id;
  else
    insert into machimoa_review.ingest_review_decisions (
      source_item_id,
      revision_hash,
      review_type,
      decision,
      region_scope,
      audience_relevance,
      reason_codes,
      rule_version,
      reviewer,
      reviewed_at,
      memo
    )
    values (
      v_item.id,
      v_hash,
      v_type,
      v_decision,
      v_scope,
      v_axes,
      v_reasons,
      v_rule,
      v_reviewer,
      v_now,
      v_memo
    )
    returning id into v_decision_id;
  end if;

  v_review_stage := case v_type
    when 'region' then 'region_review'
    when 'relevance' then 'relevance_review'
    else null
  end;
  if v_review_stage is null then
    raise exception 'invalid_review_type';
  end if;

  select *
    into v_ai
  from machimoa_review.processing_jobs as j
  where j.source_item_id = v_item.id
    and j.revision_hash = v_hash
    and j.processing_stage = 'ai_enrichment'
  for update;

  if found
     and v_ai.status = 'claimed'
     and v_ai.claim_lease_until is not null
     and v_ai.claim_lease_until > v_now then
    v_live_claimed := true;
  end if;

  if v_decision = 'approve_ai' then
    update machimoa_review.processing_jobs as j
    set
      status = 'completed',
      completed_at = v_now,
      claimed_by = null,
      claim_lease_until = null
    where j.source_item_id = v_item.id
      and j.revision_hash = v_hash
      and j.processing_stage = v_review_stage
      and j.status in ('queued', 'claimed');

    if
       v_item.body_usable is true
       and v_item.has_source_url is true
       and v_item.disposition not in (
         'non_target',
         'observe_only',
         'attachment_dependent'
       )
       and v_scope in ('capital', 'nationwide_or_online')
       and exists (
         select 1
         from machimoa_review.ingest_review_decisions as d
         where d.source_item_id = v_item.id
           and d.revision_hash is not distinct from v_hash
           and d.review_type = 'region'
           and d.decision = 'approve_ai'
       )
       and exists (
         select 1
         from machimoa_review.ingest_review_decisions as d
         where d.source_item_id = v_item.id
           and d.revision_hash is not distinct from v_hash
           and d.review_type = 'relevance'
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
             'content_review'
           )
           and r.status in ('queued', 'claimed')
       )
    then
      update machimoa_review.source_items as si
      set disposition = 'target'
      where si.id = v_item.id
        and si.disposition is distinct from 'target';
      v_item.disposition := 'target';
    end if;

    if v_item.disposition = 'target'
       and v_item.body_usable is true
       and v_item.has_source_url is true
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
             'content_review'
           )
           and r.status in ('queued', 'claimed')
       )
    then
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
        )
        returning * into v_ai;
      elsif v_ai.status = 'cancelled' then
        update machimoa_review.processing_jobs as j
        set
          status = 'queued',
          available_at = v_now,
          claimed_by = null,
          claim_lease_until = null,
          claimed_at = null,
          next_retry_at = null,
          reason_codes = v_reasons
        where j.id = v_ai.id
        returning * into v_ai;
      end if;
    end if;
  elsif v_decision = 'reject' then
    if v_live_claimed then
      raise exception 'ai_job_claimed';
    end if;
    update machimoa_review.processing_jobs as j
    set
      status = 'completed',
      completed_at = v_now,
      claimed_by = null,
      claim_lease_until = null
    where j.source_item_id = v_item.id
      and j.revision_hash = v_hash
      and j.processing_stage = v_review_stage
      and j.status in ('queued', 'claimed');
    if v_ai.id is not null and v_ai.status in ('queued', 'claimed') then
      update machimoa_review.processing_jobs as j
      set
        status = 'cancelled',
        claimed_by = null,
        claim_lease_until = null,
        claimed_at = null,
        next_retry_at = null,
        reason_codes = case
          when pg_catalog.cardinality(v_reasons) >= 1 then v_reasons
          else array['rejected_non_target']::pg_catalog.text[]
        end
      where j.id = v_ai.id
        and j.status in ('queued', 'claimed')
      returning * into v_ai;
    end if;
    update machimoa_review.source_items as si
    set disposition = 'non_target'
    where si.id = v_item.id;
    v_item.disposition := 'non_target';
  else
    if v_live_claimed then
      raise exception 'ai_job_claimed';
    end if;
    if v_ai.id is not null and v_ai.status in ('queued', 'claimed') then
      update machimoa_review.processing_jobs as j
      set
        status = 'cancelled',
        claimed_by = null,
        claim_lease_until = null,
        claimed_at = null,
        next_retry_at = null,
        reason_codes = case
          when pg_catalog.cardinality(v_reasons) >= 1 then v_reasons
          else array['needs_review']::pg_catalog.text[]
        end
      where j.id = v_ai.id
        and j.status in ('queued', 'claimed')
      returning * into v_ai;
    end if;
  end if;

  select *
    into v_review
  from machimoa_review.processing_jobs as j
  where j.source_item_id = v_item.id
    and j.revision_hash = v_hash
    and j.processing_stage = v_review_stage
  for update;

  if v_decision = 'needs_review' then
    if v_review.id is null then
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
        v_review_stage,
        'queued',
        v_now,
        v_now,
        v_reasons
      )
      returning * into v_review;
    elsif v_review.status is distinct from 'queued' then
      update machimoa_review.processing_jobs as j
      set
        status = 'queued',
        available_at = v_now,
        claimed_by = null,
        claim_lease_until = null,
        completed_at = null,
        next_retry_at = null,
        reason_codes = v_reasons
      where j.id = v_review.id
      returning * into v_review;
    end if;
  else
    select *
      into v_review
    from machimoa_review.processing_jobs as j
    where j.source_item_id = v_item.id
      and j.revision_hash = v_hash
      and j.processing_stage = v_review_stage;
  end if;

  select *
    into v_ai
  from machimoa_review.processing_jobs as j
  where j.source_item_id = v_item.id
    and j.revision_hash = v_hash
    and j.processing_stage = 'ai_enrichment';

  return query select
    v_decision_id,
    v_item.id,
    v_hash,
    v_type,
    v_decision,
    v_ai.id,
    v_ai.status,
    v_review.id,
    v_review.status;
end
$function$;

drop function if exists machimoa_review.upsert_source_observations_v3(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
);
drop function if exists machimoa_review.resolve_source_item_product_type(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
);
drop function if exists machimoa_review.apply_source_item_product_type(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb
);
drop function if exists machimoa_review.ensure_ai_enrichment_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text[]
);

alter table machimoa_review.processing_jobs
  drop constraint processing_jobs_stage_ck;

alter table machimoa_review.processing_jobs
  add constraint processing_jobs_stage_ck
  check (
    processing_stage in (
      'region_review',
      'content_review',
      'relationship_review',
      'ai_enrichment',
      'relevance_review'
    )
  );

drop table if exists machimoa_review.source_item_product_types;

commit;
