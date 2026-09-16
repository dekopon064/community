-- Ingest review decisions, shared decision core, v2 upsert, and claim gate.
-- Do not apply this file without a separate operating-database approval.
-- Non-destructive rollback:
--   supabase/rollback/20260916000001_ingest_review_decision_rpc_adapters_down.sql
--   then supabase/rollback/20260916000000_ingest_review_decisions_down.sql
-- This migration must not delete curation_candidates or public.curations.
-- Private claim_processing_jobs signature stays frozen; body is replaced.
-- Existing v1 upsert_source_observations is not replaced.
-- Create order: apply core, resolve adapter, reconcile, private v2, claim body.
--
-- Supabase CLI linked db push uses session_user=cli_login_postgres
-- with current_user=postgres. DDL authorization requires current_user=postgres.

begin;

do $guard$
begin
  if current_user <> 'postgres' then
    raise exception
      'ingest review decision migration must run as postgres (current_user=%)',
      current_user;
  end if;

  if session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'ingest review decision migration session_user not allowed (%)',
      session_user;
  end if;

  if pg_catalog.to_regclass('machimoa_review.source_items') is null then
    raise exception 'machimoa_review.source_items must exist';
  end if;
  if pg_catalog.to_regclass('machimoa_review.processing_jobs') is null then
    raise exception 'machimoa_review.processing_jobs must exist';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.claim_processing_jobs(pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4)'
     ) is null then
    raise exception 'machimoa_review.claim_processing_jobs signature is missing';
  end if;
  if pg_catalog.to_regclass('machimoa_review.ingest_review_decisions') is not null then
    raise exception
      'table machimoa_review.ingest_review_decisions already exists; inspect manually';
  end if;
end
$guard$;

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

create table machimoa_review.ingest_review_decisions (
  id pg_catalog.uuid primary key default pg_catalog.gen_random_uuid(),
  source_item_id pg_catalog.uuid not null
    references machimoa_review.source_items (id)
    on delete restrict,
  revision_hash pg_catalog.text not null,
  review_type pg_catalog.text not null,
  decision pg_catalog.text not null,
  region_scope pg_catalog.text not null,
  audience_relevance pg_catalog.text[] not null default '{}'::pg_catalog.text[],
  reason_codes pg_catalog.text[] not null default '{}'::pg_catalog.text[],
  rule_version pg_catalog.text not null,
  reviewer pg_catalog.text not null,
  reviewed_at pg_catalog.timestamptz not null default pg_catalog.now(),
  memo pg_catalog.text,
  created_at pg_catalog.timestamptz not null default pg_catalog.now(),
  updated_at pg_catalog.timestamptz not null default pg_catalog.now(),
  constraint ingest_review_decisions_unique
    unique (source_item_id, revision_hash, review_type),
  constraint ingest_review_decisions_hash_ck
    check (revision_hash ~ '^[0-9a-f]{64}$'),
  constraint ingest_review_decisions_type_ck
    check (review_type in ('region', 'relevance')),
  constraint ingest_review_decisions_decision_ck
    check (decision in ('approve_ai', 'reject', 'needs_review')),
  constraint ingest_review_decisions_scope_ck
    check (
      region_scope in (
        'capital',
        'nationwide_or_online',
        'noncapital',
        'unknown'
      )
    ),
  constraint ingest_review_decisions_axes_ck
    check (
      audience_relevance <@ array[
        'jp_residents_in_kr',
        'foreign_residents_in_kr',
        'kr_japan_activity',
        'kr_jp_exchange'
      ]::pg_catalog.text[]
    ),
  constraint ingest_review_decisions_approve_ck
    check (
      decision is distinct from 'approve_ai'
      or (
        pg_catalog.cardinality(audience_relevance) >= 1
        and region_scope in ('capital', 'nationwide_or_online')
      )
    ),
  constraint ingest_review_decisions_memo_ck
    check (
      memo is null or pg_catalog.char_length(memo) <= 500
    ),
  constraint ingest_review_decisions_reviewer_ck
    check (pg_catalog.char_length(reviewer) between 1 and 128),
  constraint ingest_review_decisions_rule_ck
    check (pg_catalog.char_length(rule_version) between 1 and 64)
);

alter table machimoa_review.ingest_review_decisions enable row level security;

revoke all privileges on table machimoa_review.ingest_review_decisions
  from public, anon, authenticated, service_role;

create function machimoa_review.apply_ingest_review_decision(
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

create function machimoa_review.resolve_ingest_review_decision(
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
  from machimoa_review.apply_ingest_review_decision(
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

create function machimoa_review.reconcile_queued_ai_job(
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

create function machimoa_review.upsert_source_observations_v2(
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
declare
  v_idx pg_catalog.int4;
  v_item pg_catalog.jsonb;
  v_jobs pg_catalog.jsonb;
  v_meta pg_catalog.jsonb;
  v_disp pg_catalog.text;
  v_source_id pg_catalog.text := pg_catalog.btrim(coalesce(p_source_id, ''));
  v_hash pg_catalog.text;
  v_rule pg_catalog.text;
  v_scope pg_catalog.text;
  v_type pg_catalog.text;
  v_decision pg_catalog.text;
  v_axes pg_catalog.text[];
  v_reasons pg_catalog.text[];
  v_reviewer pg_catalog.text;
  v_locked machimoa_review.source_items%rowtype;
  v_applied record;
  v_upsert_row record;
begin
  if p_items is null or pg_catalog.jsonb_typeof(p_items) <> 'array' then
    raise exception 'items must be a json array';
  end if;

  for v_idx in 0 .. pg_catalog.jsonb_array_length(p_items) - 1 loop
    v_item := p_items -> v_idx;
    if pg_catalog.jsonb_typeof(v_item) <> 'object' then
      raise exception 'item must be an object';
    end if;

    v_jobs := v_item -> 'jobs';
    if v_jobs is not null and v_jobs <> 'null'::pg_catalog.jsonb then
      if pg_catalog.jsonb_typeof(v_jobs) <> 'array' then
        raise exception 'ai_job_not_allowed_in_upsert';
      end if;
      if exists (
        select 1
        from pg_catalog.jsonb_array_elements(v_jobs) as job
        where pg_catalog.btrim(coalesce(job ->> 'stage', '')) = 'ai_enrichment'
      ) then
        raise exception 'ai_job_not_allowed_in_upsert';
      end if;
    end if;

    v_disp := pg_catalog.btrim(coalesce(v_item ->> 'disposition', ''));
    v_meta := v_item -> 'classifier_decision';
    if v_meta is null or v_meta = 'null'::pg_catalog.jsonb then
      v_meta := null;
    end if;
    if v_disp is distinct from 'target' then
      if v_meta is not null then
        raise exception 'classifier_metadata_forbidden';
      end if;
    elsif v_meta is not null then
      if pg_catalog.jsonb_typeof(v_meta) <> 'object' then
        raise exception 'invalid_classifier_decision';
      end if;
      if exists (
        select 1
        from pg_catalog.jsonb_object_keys(v_meta) as key
        where key not in (
          'decision',
          'review_type',
          'region_scope',
          'audience_relevance',
          'reason_codes',
          'rule_version'
        )
      ) then
        raise exception 'invalid_classifier_decision';
      end if;
      v_decision := pg_catalog.btrim(coalesce(v_meta ->> 'decision', ''));
      if v_decision is distinct from 'approve_ai' then
        raise exception 'invalid_classifier_decision';
      end if;
      v_type := pg_catalog.btrim(coalesce(v_meta ->> 'review_type', ''));
      if v_type is distinct from 'relevance' then
        raise exception 'invalid_review_type';
      end if;
      v_scope := pg_catalog.btrim(coalesce(v_meta ->> 'region_scope', ''));
      if v_scope not in ('capital', 'nationwide_or_online') then
        raise exception 'invalid_region_scope';
      end if;
      v_rule := pg_catalog.btrim(coalesce(v_meta ->> 'rule_version', ''));
      if pg_catalog.char_length(v_rule) not between 1 and 64 then
        raise exception 'invalid_rule_version';
      end if;
      if not v_meta ? 'audience_relevance'
         or pg_catalog.jsonb_typeof(v_meta -> 'audience_relevance') <> 'array' then
        raise exception 'invalid_audience_relevance';
      end if;
      v_axes := array(
        select pg_catalog.jsonb_array_elements_text(v_meta -> 'audience_relevance')
      );
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
      if pg_catalog.cardinality(v_axes) is null
         or pg_catalog.cardinality(v_axes) < 1 then
        raise exception 'approve_requirements_not_met';
      end if;
      if v_meta ? 'reason_codes'
         and pg_catalog.jsonb_typeof(v_meta -> 'reason_codes') <> 'array' then
        raise exception 'invalid_classifier_decision';
      end if;
    end if;
  end loop;

  for v_upsert_row in
    select
      u.input_index,
      u.external_key,
      u.outcome,
      u.duplicate_in_batch
    from machimoa_review.upsert_source_observations(
      p_source_id,
      p_run_id,
      p_items,
      p_next_checkpoint
    ) as u
  loop
    input_index := v_upsert_row.input_index;
    external_key := v_upsert_row.external_key;
    outcome := v_upsert_row.outcome;
    duplicate_in_batch := v_upsert_row.duplicate_in_batch;
    v_item := p_items -> v_upsert_row.input_index;
    v_disp := pg_catalog.btrim(coalesce(v_item ->> 'disposition', ''));
    if v_upsert_row.outcome in ('new', 'changed')
       and v_upsert_row.duplicate_in_batch is not true
       and v_disp = 'target' then
      v_meta := v_item -> 'classifier_decision';
      if v_meta is null or v_meta = 'null'::pg_catalog.jsonb then
        raise exception 'classifier_metadata_required';
      end if;
      v_hash := pg_catalog.btrim(coalesce(v_item ->> 'revision_hash', ''));
      select *
        into v_locked
      from machimoa_review.source_items as si
      where si.source_id = v_source_id
        and si.external_key = v_upsert_row.external_key
      for update;
      if not found then
        raise exception 'source_item_not_found';
      end if;
      if v_locked.revision_hash is distinct from v_hash then
        raise exception 'revision_mismatch';
      end if;
      v_rule := pg_catalog.btrim(coalesce(v_meta ->> 'rule_version', ''));
      v_scope := pg_catalog.btrim(coalesce(v_meta ->> 'region_scope', ''));
      v_type := pg_catalog.btrim(coalesce(v_meta ->> 'review_type', ''));
      v_decision := pg_catalog.btrim(coalesce(v_meta ->> 'decision', ''));
      v_axes := coalesce(
        array(
          select pg_catalog.jsonb_array_elements_text(
            coalesce(v_meta -> 'audience_relevance', '[]'::pg_catalog.jsonb)
          )
        ),
        '{}'::pg_catalog.text[]
      );
      v_reasons := coalesce(
        array(
          select pg_catalog.jsonb_array_elements_text(
            coalesce(v_meta -> 'reason_codes', '[]'::pg_catalog.jsonb)
          )
        ),
        '{}'::pg_catalog.text[]
      );
      v_reviewer := 'classifier:' || v_rule;
      select *
        into v_applied
      from machimoa_review.apply_ingest_review_decision(
        v_locked.id,
        v_locked.revision_hash,
        v_type,
        v_decision,
        v_scope,
        v_axes,
        v_reasons,
        v_rule,
        v_reviewer,
        null
      );
    end if;
    return next;
  end loop;
end
$function$;

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

alter function machimoa_review.apply_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) owner to postgres;
alter function machimoa_review.resolve_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) owner to postgres;
alter function machimoa_review.reconcile_queued_ai_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
) owner to postgres;
alter function machimoa_review.upsert_source_observations_v2(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) owner to postgres;
alter function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) owner to postgres;

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

commit;
