-- Revision-scoped product_type table, dedicated writers, v3 upsert, and
-- claim/apply AND-read plus Phase 2 lease equality (<= now).
-- Do not apply this file without a separate operating-database approval.
-- Non-destructive rollback:
--   supabase/rollback/20260918000001_ingest_product_type_rpc_adapters_down.sql
--   then supabase/rollback/20260918000000_ingest_product_type_down.sql
-- This migration must not delete curation_candidates or public.curations.
-- Existing v1/v2 signatures stay. apply_source_item_product_type has no public adapter.
--
-- Supabase CLI linked db push uses session_user=cli_login_postgres
-- with current_user=postgres. DDL authorization requires current_user=postgres.

begin;

do $guard$
begin
  if current_user <> 'postgres' then
    raise exception
      'ingest product_type migration must run as postgres (current_user=%)',
      current_user;
  end if;

  if session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'ingest product_type migration session_user not allowed (%)',
      session_user;
  end if;

  if pg_catalog.to_regclass('machimoa_review.source_items') is null then
    raise exception 'machimoa_review.source_items must exist';
  end if;
  if pg_catalog.to_regclass('machimoa_review.processing_jobs') is null then
    raise exception 'machimoa_review.processing_jobs must exist';
  end if;
  if pg_catalog.to_regclass('machimoa_review.ingest_review_decisions') is null then
    raise exception 'machimoa_review.ingest_review_decisions must exist';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.apply_ingest_review_decision(pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text, pg_catalog.text)'
     ) is null then
    raise exception 'machimoa_review.apply_ingest_review_decision signature is missing';
  end if;
  if pg_catalog.to_regclass('machimoa_review.source_item_product_types') is not null then
    raise exception
      'table machimoa_review.source_item_product_types already exists; inspect manually';
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
      'relevance_review',
      'product_type_review'
    )
  );

create table machimoa_review.source_item_product_types (
  source_item_id pg_catalog.uuid not null
    references machimoa_review.source_items (id)
    on delete restrict,
  revision_hash pg_catalog.text not null,
  product_type pg_catalog.text not null,
  origin pg_catalog.text not null,
  rule_version pg_catalog.text not null,
  reason_codes pg_catalog.text[] not null default '{}'::pg_catalog.text[],
  period_signals pg_catalog.text[] not null default '{}'::pg_catalog.text[],
  reviewer pg_catalog.text not null,
  memo pg_catalog.text,
  created_at pg_catalog.timestamptz not null default pg_catalog.now(),
  updated_at pg_catalog.timestamptz not null default pg_catalog.now(),
  constraint source_item_product_types_pk
    primary key (source_item_id, revision_hash),
  constraint source_item_product_types_hash_ck
    check (revision_hash ~ '^[0-9a-f]{64}$'),
  constraint source_item_product_types_type_ck
    check (product_type in ('event_program', 'policy_reference')),
  constraint source_item_product_types_origin_ck
    check (origin in ('classifier', 'human')),
  constraint source_item_product_types_rule_ck
    check (pg_catalog.char_length(rule_version) between 1 and 64),
  constraint source_item_product_types_reviewer_ck
    check (pg_catalog.char_length(reviewer) between 1 and 128),
  constraint source_item_product_types_memo_ck
    check (memo is null or pg_catalog.char_length(memo) <= 500)
);

alter table machimoa_review.source_item_product_types enable row level security;

revoke all privileges on table machimoa_review.source_item_product_types
  from public, anon, authenticated, service_role;

create function machimoa_review.ensure_ai_enrichment_job(
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

create function machimoa_review.apply_source_item_product_type(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_classification pg_catalog.jsonb
)
returns pg_catalog.void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_hash pg_catalog.text := pg_catalog.btrim(coalesce(p_revision_hash, ''));
  v_item machimoa_review.source_items%rowtype;
  v_kind pg_catalog.text;
  v_type pg_catalog.text;
  v_rule pg_catalog.text;
  v_reasons pg_catalog.text[];
  v_signals pg_catalog.text[];
  v_source_kind pg_catalog.text;
  v_existing machimoa_review.source_item_product_types%rowtype;
  v_review machimoa_review.processing_jobs%rowtype;
begin
  if p_source_item_id is null then
    raise exception 'source_item_not_found';
  end if;
  if v_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'revision_mismatch';
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
  from machimoa_review.source_item_product_types as pt
  where pt.source_item_id = v_item.id
    and pt.revision_hash = v_hash
  for update;
  if found then
    return;
  end if;
  if v_item.disposition is distinct from 'target' then
    return;
  end if;
  if p_classification is null or p_classification = 'null'::pg_catalog.jsonb then
    raise exception 'product_type_metadata_required';
  end if;
  if pg_catalog.jsonb_typeof(p_classification) <> 'object' then
    raise exception 'invalid_product_type_classification';
  end if;
  if exists (
    select 1
    from pg_catalog.jsonb_object_keys(p_classification) as key
    where key not in (
      'kind',
      'product_type',
      'reason_codes',
      'period_signals',
      'rule_version'
    )
  ) then
    raise exception 'invalid_product_type_classification';
  end if;

  v_kind := pg_catalog.btrim(coalesce(p_classification ->> 'kind', ''));
  if v_kind not in ('confirmed', 'review') then
    raise exception 'invalid_product_type_classification';
  end if;
  v_rule := pg_catalog.btrim(coalesce(p_classification ->> 'rule_version', ''));
  if pg_catalog.char_length(v_rule) not between 1 and 64 then
    raise exception 'invalid_rule_version';
  end if;
  if p_classification ? 'reason_codes'
     and pg_catalog.jsonb_typeof(p_classification -> 'reason_codes') <> 'array' then
    raise exception 'invalid_product_type_classification';
  end if;
  if p_classification ? 'period_signals'
     and pg_catalog.jsonb_typeof(p_classification -> 'period_signals') <> 'array' then
    raise exception 'invalid_period_signals';
  end if;
  v_reasons := coalesce(
    array(
      select pg_catalog.jsonb_array_elements_text(
        coalesce(p_classification -> 'reason_codes', '[]'::pg_catalog.jsonb)
      )
    ),
    '{}'::pg_catalog.text[]
  );
  v_signals := coalesce(
    array(
      select pg_catalog.jsonb_array_elements_text(
        coalesce(p_classification -> 'period_signals', '[]'::pg_catalog.jsonb)
      )
    ),
    '{}'::pg_catalog.text[]
  );
  if v_kind = 'review' then
    if p_classification ? 'product_type' then
      raise exception 'invalid_product_type';
    end if;
    v_type := null;
  else
    v_type := pg_catalog.btrim(coalesce(p_classification ->> 'product_type', ''));
    if v_type not in ('event_program', 'policy_reference') then
      raise exception 'invalid_product_type';
    end if;
  end if;

  select s.source_kind
    into v_source_kind
  from machimoa_review.ingest_sources as s
  where s.source_id = v_item.source_id;
  if not found then
    raise exception 'source_not_found';
  end if;

  if v_source_kind = 'content' then
    if v_kind is distinct from 'confirmed' or v_type is distinct from 'event_program' then
      raise exception 'content_product_type_locked';
    end if;
    insert into machimoa_review.source_item_product_types (
      source_item_id,
      revision_hash,
      product_type,
      origin,
      rule_version,
      reason_codes,
      period_signals,
      reviewer,
      memo
    )
    values (
      v_item.id,
      v_hash,
      'event_program',
      'classifier',
      v_rule,
      v_reasons,
      v_signals,
      'classifier:' || v_rule,
      null
    );
    return;
  end if;

  if v_kind = 'review' then
    select *
      into v_review
    from machimoa_review.processing_jobs as j
    where j.source_item_id = v_item.id
      and j.revision_hash = v_hash
      and j.processing_stage = 'product_type_review'
    for update;
    if not found then
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
        'product_type_review',
        'queued',
        v_now,
        v_now,
        v_reasons
      );
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
      where j.id = v_review.id;
    end if;
    return;
  end if;

  insert into machimoa_review.source_item_product_types (
    source_item_id,
    revision_hash,
    product_type,
    origin,
    rule_version,
    reason_codes,
    period_signals,
    reviewer,
    memo
  )
  values (
    v_item.id,
    v_hash,
    v_type,
    'classifier',
    v_rule,
    v_reasons,
    v_signals,
    'classifier:' || v_rule,
    null
  );
end
$function$;

create function machimoa_review.resolve_source_item_product_type(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_action pg_catalog.text,
  p_product_type pg_catalog.text,
  p_reason_codes pg_catalog.text[],
  p_period_signals pg_catalog.text[],
  p_rule_version pg_catalog.text,
  p_reviewer pg_catalog.text,
  p_memo pg_catalog.text default null
)
returns table (
  source_item_id pg_catalog.uuid,
  revision_hash pg_catalog.text,
  product_type pg_catalog.text,
  origin pg_catalog.text,
  review_job_id pg_catalog.uuid,
  review_job_status pg_catalog.text,
  ai_job_id pg_catalog.uuid,
  ai_job_status pg_catalog.text,
  action_result pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_hash pg_catalog.text := pg_catalog.btrim(coalesce(p_revision_hash, ''));
  v_action pg_catalog.text := pg_catalog.btrim(coalesce(p_action, ''));
  v_type pg_catalog.text := nullif(pg_catalog.btrim(coalesce(p_product_type, '')), '');
  v_rule pg_catalog.text := pg_catalog.btrim(coalesce(p_rule_version, ''));
  v_reviewer pg_catalog.text := pg_catalog.btrim(coalesce(p_reviewer, ''));
  v_memo pg_catalog.text := nullif(pg_catalog.btrim(coalesce(p_memo, '')), '');
  v_reasons pg_catalog.text[] := coalesce(p_reason_codes, '{}'::pg_catalog.text[]);
  v_signals pg_catalog.text[] := coalesce(p_period_signals, '{}'::pg_catalog.text[]);
  v_item machimoa_review.source_items%rowtype;
  v_source_kind pg_catalog.text;
  v_existing machimoa_review.source_item_product_types%rowtype;
  v_ai machimoa_review.processing_jobs%rowtype;
  v_review machimoa_review.processing_jobs%rowtype;
  v_kind pg_catalog.text;
  v_result pg_catalog.text;
begin
  if p_source_item_id is null then
    raise exception 'source_item_not_found';
  end if;
  if v_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'revision_mismatch';
  end if;
  if v_action not in ('confirm', 'override', 'rollback') then
    raise exception 'invalid_product_type_action';
  end if;
  if v_action in ('confirm', 'override')
     and v_type not in ('event_program', 'policy_reference') then
    raise exception 'invalid_product_type';
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

  select s.source_kind
    into v_source_kind
  from machimoa_review.ingest_sources as s
  where s.source_id = v_item.source_id;
  if not found then
    raise exception 'source_not_found';
  end if;
  if v_source_kind = 'content'
     and (
       v_action is distinct from 'confirm'
       or v_type is distinct from 'event_program'
     ) then
    raise exception 'content_product_type_locked';
  end if;

  select *
    into v_existing
  from machimoa_review.source_item_product_types as pt
  where pt.source_item_id = v_item.id
    and pt.revision_hash = v_hash
  for update;

  if v_action = 'confirm' then
    if not found then
      v_kind := 'mutate';
    elsif v_existing.product_type is not distinct from v_type then
      v_kind := 'no-op';
    else
      v_kind := 'reject';
    end if;
  elsif v_action = 'override' then
    if not found then
      v_kind := 'reject';
    elsif v_existing.product_type is not distinct from v_type then
      v_kind := 'no-op';
    else
      v_kind := 'mutate';
    end if;
  else
    if not found then
      v_kind := 'no-op';
    else
      v_kind := 'mutate';
    end if;
  end if;

  if v_kind = 'no-op' then
    v_result := 'no-op';
  elsif v_kind = 'reject' then
    raise exception 'decision_conflict';
  else
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
      raise exception 'ai_job_claimed';
    end if;
    if v_action in ('override', 'rollback') and v_memo is null then
      raise exception 'invalid_memo';
    end if;

    if v_action = 'confirm' then
      insert into machimoa_review.source_item_product_types (
        source_item_id,
        revision_hash,
        product_type,
        origin,
        rule_version,
        reason_codes,
        period_signals,
        reviewer,
        memo
      )
      values (
        v_item.id,
        v_hash,
        v_type,
        'human',
        v_rule,
        v_reasons,
        v_signals,
        v_reviewer,
        v_memo
      );
      update machimoa_review.processing_jobs as j
      set
        status = 'completed',
        completed_at = v_now,
        claimed_by = null,
        claim_lease_until = null
      where j.source_item_id = v_item.id
        and j.revision_hash = v_hash
        and j.processing_stage = 'product_type_review'
        and j.status in ('queued', 'claimed');
      perform machimoa_review.ensure_ai_enrichment_job(
        v_item.id, v_hash, v_reasons
      );
      v_result := 'confirmed';
    elsif v_action = 'override' then
      update machimoa_review.source_item_product_types as pt
      set
        product_type = v_type,
        origin = 'human',
        rule_version = v_rule,
        reason_codes = v_reasons,
        period_signals = v_signals,
        reviewer = v_reviewer,
        memo = v_memo,
        updated_at = v_now
      where pt.source_item_id = v_item.id
        and pt.revision_hash = v_hash;
      update machimoa_review.processing_jobs as j
      set
        status = 'completed',
        completed_at = v_now,
        claimed_by = null,
        claim_lease_until = null
      where j.source_item_id = v_item.id
        and j.revision_hash = v_hash
        and j.processing_stage = 'product_type_review'
        and j.status in ('queued', 'claimed');
      perform machimoa_review.ensure_ai_enrichment_job(
        v_item.id, v_hash, v_reasons
      );
      v_result := 'overridden';
    else
      delete from machimoa_review.source_item_product_types as pt
      where pt.source_item_id = v_item.id
        and pt.revision_hash = v_hash;
      select *
        into v_review
      from machimoa_review.processing_jobs as j
      where j.source_item_id = v_item.id
        and j.revision_hash = v_hash
        and j.processing_stage = 'product_type_review'
      for update;
      if not found then
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
          'product_type_review',
          'queued',
          v_now,
          v_now,
          v_reasons
        );
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
        where j.id = v_review.id;
      end if;
      if v_ai.id is not null
         and (
           v_ai.status = 'queued'
           or (
             v_ai.status = 'claimed'
             and v_ai.claim_lease_until is not null
             and v_ai.claim_lease_until <= v_now
           )
         ) then
        update machimoa_review.processing_jobs as j
        set
          status = 'cancelled',
          claimed_by = null,
          claim_lease_until = null,
          claimed_at = null,
          next_retry_at = null,
          reason_codes = case
            when pg_catalog.cardinality(v_reasons) >= 1 then v_reasons
            else array['product_type_rollback']::pg_catalog.text[]
          end
        where j.id = v_ai.id;
      end if;
      v_result := 'rolled_back';
    end if;
  end if;

  select *
    into v_existing
  from machimoa_review.source_item_product_types as pt
  where pt.source_item_id = v_item.id
    and pt.revision_hash = v_hash;
  select *
    into v_review
  from machimoa_review.processing_jobs as j
  where j.source_item_id = v_item.id
    and j.revision_hash = v_hash
    and j.processing_stage = 'product_type_review';
  select *
    into v_ai
  from machimoa_review.processing_jobs as j
  where j.source_item_id = v_item.id
    and j.revision_hash = v_hash
    and j.processing_stage = 'ai_enrichment';

  return query select
    v_item.id,
    v_hash,
    v_existing.product_type,
    v_existing.origin,
    v_review.id,
    v_review.status,
    v_ai.id,
    v_ai.status,
    v_result;
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
     and v_ai.claim_lease_until is null then
    raise exception 'ai_job_malformed_lease';
  end if;
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
             'content_review',
             'product_type_review'
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

    perform machimoa_review.ensure_ai_enrichment_job(
      v_item.id,
      v_hash,
      v_reasons
    );
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
    if v_ai.id is not null
       and (
         v_ai.status = 'queued'
         or (
           v_ai.status = 'claimed'
           and v_ai.claim_lease_until is not null
           and v_ai.claim_lease_until <= v_now
         )
       ) then
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
        and (
          j.status = 'queued'
          or (
            j.status = 'claimed'
            and j.claim_lease_until is not null
            and j.claim_lease_until <= v_now
          )
        )
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
    if v_ai.id is not null
       and (
         v_ai.status = 'queued'
         or (
           v_ai.status = 'claimed'
           and v_ai.claim_lease_until is not null
           and v_ai.claim_lease_until <= v_now
         )
       ) then
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
        and (
          j.status = 'queued'
          or (
            j.status = 'claimed'
            and j.claim_lease_until is not null
            and j.claim_lease_until <= v_now
          )
        )
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
  if v_job.status = 'claimed' and v_job.claim_lease_until is null then
    raise exception 'ai_job_malformed_lease';
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

create function machimoa_review.upsert_source_observations_v3(
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
  v_pt pg_catalog.jsonb;
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
      if exists (
        select 1
        from pg_catalog.jsonb_array_elements(v_jobs) as job
        where pg_catalog.btrim(coalesce(job ->> 'stage', '')) = 'product_type_review'
      ) then
        raise exception 'product_type_review_not_allowed_in_upsert';
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

    v_pt := v_item -> 'product_type_classification';
    if v_pt is null or v_pt = 'null'::pg_catalog.jsonb then
      v_pt := null;
    end if;
    if v_disp is distinct from 'target' then
      if v_pt is not null then
        raise exception 'product_type_metadata_forbidden';
      end if;
    elsif v_pt is not null then
      if pg_catalog.jsonb_typeof(v_pt) <> 'object' then
        raise exception 'invalid_product_type_classification';
      end if;
      if exists (
        select 1
        from pg_catalog.jsonb_object_keys(v_pt) as key
        where key not in (
          'kind',
          'product_type',
          'reason_codes',
          'period_signals',
          'rule_version'
        )
      ) then
        raise exception 'invalid_product_type_classification';
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
       and v_upsert_row.duplicate_in_batch is not true then
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
      v_pt := v_item -> 'product_type_classification';
      if v_pt is null or v_pt = 'null'::pg_catalog.jsonb then
        v_pt := null;
      end if;
      perform machimoa_review.apply_source_item_product_type(
        v_locked.id,
        v_locked.revision_hash,
        v_pt
      );
    end if;
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

alter function machimoa_review.ensure_ai_enrichment_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text[]
) owner to postgres;
alter function machimoa_review.apply_source_item_product_type(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb
) owner to postgres;
alter function machimoa_review.resolve_source_item_product_type(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
) owner to postgres;
alter function machimoa_review.upsert_source_observations_v3(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) owner to postgres;
alter function machimoa_review.apply_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) owner to postgres;
alter function machimoa_review.reconcile_queued_ai_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
) owner to postgres;
alter function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) owner to postgres;

revoke all privileges on function machimoa_review.ensure_ai_enrichment_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text[]
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.apply_source_item_product_type(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.resolve_source_item_product_type(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.upsert_source_observations_v3(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.apply_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.reconcile_queued_ai_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) from public, anon, authenticated, service_role;

commit;
