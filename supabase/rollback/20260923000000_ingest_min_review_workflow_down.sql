-- Restore origin/main bodies of evaluate_source_item_gates,
-- resolve_source_item_product_type, and resolve_source_item_gate_facts.
-- Function definitions only. Do not delete review jobs, decisions, or items.
-- This file is not auto-applied.

begin;

do $guard$
begin
  if current_user <> 'postgres' then
    raise exception
      'ingest min review workflow rollback must run as postgres (current_user=%)',
      current_user;
  end if;

  if session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'ingest min review workflow rollback session_user not allowed (%)',
      session_user;
  end if;

  if pg_catalog.to_regprocedure(
       'machimoa_review.evaluate_source_item_gates(pg_catalog.bool, pg_catalog.bool, pg_catalog.bool, pg_catalog.text, pg_catalog.text[], pg_catalog.jsonb)'
     ) is null then
    raise exception 'machimoa_review.evaluate_source_item_gates signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.resolve_source_item_product_type(pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text, pg_catalog.text)'
     ) is null then
    raise exception 'machimoa_review.resolve_source_item_product_type signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.resolve_source_item_gate_facts(pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text, pg_catalog.text, pg_catalog.text)'
     ) is null then
    raise exception 'machimoa_review.resolve_source_item_gate_facts signature is missing';
  end if;
end
$guard$;

create or replace function machimoa_review.evaluate_source_item_gates(
  p_body_usable pg_catalog.bool,
  p_has_source_url pg_catalog.bool,
  p_attachment_present pg_catalog.bool,
  p_product_type pg_catalog.text,
  p_product_type_reasons pg_catalog.text[],
  p_gate_facts pg_catalog.jsonb
)
returns table (
  disposition pg_catalog.text,
  jobs pg_catalog.jsonb,
  region_status pg_catalog.text,
  audience_status pg_catalog.text,
  evaluated_profile pg_catalog.text
)
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_contract pg_catalog.text := 'capital_v1_evaluator';
  v_profile pg_catalog.text := 'capital_v1';
  v_type pg_catalog.text := nullif(pg_catalog.btrim(coalesce(p_product_type, '')), '');
  v_facts pg_catalog.jsonb;
  v_scope pg_catalog.text;
  v_region pg_catalog.text := 'not_applicable';
  v_audience pg_catalog.text := 'not_applicable';
  v_jobs pg_catalog.jsonb := '[]'::pg_catalog.jsonb;
  v_reasons pg_catalog.jsonb;
  v_disp pg_catalog.text;
  v_pt_reasons pg_catalog.text[] := coalesce(p_product_type_reasons, '{}'::pg_catalog.text[]);
begin
  perform v_contract;

  if p_body_usable is not true and p_attachment_present is true then
    v_reasons := pg_catalog.jsonb_build_array('attachment_dependent');
    if p_has_source_url is not true then
      v_reasons := v_reasons || pg_catalog.jsonb_build_array('missing_source_url');
    end if;
    disposition := 'attachment_dependent';
    jobs := pg_catalog.jsonb_build_array(
      pg_catalog.jsonb_build_object(
        'stage', 'content_review',
        'reason_codes', v_reasons
      )
    );
    region_status := 'not_applicable';
    audience_status := 'not_applicable';
    evaluated_profile := v_profile;
    return next;
    return;
  end if;

  if p_body_usable is not true then
    disposition := 'non_target';
    jobs := '[]'::pg_catalog.jsonb;
    region_status := 'not_applicable';
    audience_status := 'not_applicable';
    evaluated_profile := v_profile;
    return next;
    return;
  end if;

  if p_has_source_url is not true then
    disposition := 'observe_only';
    jobs := '[]'::pg_catalog.jsonb;
    region_status := 'not_applicable';
    audience_status := 'not_applicable';
    evaluated_profile := v_profile;
    return next;
    return;
  end if;

  if v_type is null then
    if pg_catalog.cardinality(v_pt_reasons) is null
       or pg_catalog.cardinality(v_pt_reasons) < 1 then
      v_pt_reasons := array['policy_lifecycle_uncertain']::pg_catalog.text[];
    end if;
    disposition := 'observe_only';
    jobs := pg_catalog.jsonb_build_array(
      pg_catalog.jsonb_build_object(
        'stage', 'product_type_review',
        'reason_codes', pg_catalog.to_jsonb(v_pt_reasons)
      )
    );
    region_status := 'not_applicable';
    audience_status := 'not_applicable';
    evaluated_profile := v_profile;
    return next;
    return;
  end if;

  if p_gate_facts is null then
    raise exception 'gate_facts_incomplete';
  end if;
  v_facts := machimoa_review.validate_gate_facts(v_type, p_gate_facts);

  if v_type = 'living_guide' then
    v_region := 'not_applicable';
  elsif v_type in ('event_program', 'policy_reference') then
    v_scope := v_facts ->> 'eligibility_scope';
    if v_scope = 'nationwide' then
      v_region := 'passed';
    elsif v_scope = 'unknown' then
      v_region := 'review_required';
    elsif exists (
      select 1
      from pg_catalog.jsonb_array_elements_text(
        coalesce(v_facts -> 'eligibility_region_codes', '[]'::pg_catalog.jsonb)
      ) as code
      where code in ('11', '28', '41')
    ) then
      v_region := 'passed';
    else
      v_region := 'failed';
    end if;
  else
    v_region := 'not_applicable';
  end if;

  if v_type is distinct from 'policy_reference' then
    v_audience := 'not_applicable';
  elsif (v_facts ->> 'foreign_resident_eligibility') = 'eligible' then
    v_audience := 'passed';
  elsif (v_facts ->> 'foreign_resident_eligibility') = 'ineligible' then
    v_audience := 'failed';
  else
    v_audience := 'review_required';
  end if;

  if v_region = 'failed' or v_audience = 'failed' then
    v_disp := 'non_target';
    v_jobs := '[]'::pg_catalog.jsonb;
  else
    if v_region = 'review_required' then
      v_jobs := v_jobs || pg_catalog.jsonb_build_array(
        pg_catalog.jsonb_build_object(
          'stage', 'region_review',
          'reason_codes', pg_catalog.jsonb_build_array('region_scope_unknown')
        )
      );
    end if;
    if v_audience = 'review_required' then
      v_jobs := v_jobs || pg_catalog.jsonb_build_array(
        pg_catalog.jsonb_build_object(
          'stage', 'relevance_review',
          'reason_codes', pg_catalog.jsonb_build_array('relevance_unconfirmed')
        )
      );
    end if;
    if v_jobs <> '[]'::pg_catalog.jsonb then
      v_disp := 'region_review_required';
    else
      v_disp := 'target';
    end if;
  end if;

  disposition := v_disp;
  jobs := v_jobs;
  region_status := v_region;
  audience_status := v_audience;
  evaluated_profile := v_profile;
  return next;
end
$function$;

create or replace function machimoa_review.resolve_source_item_product_type(
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

create or replace function machimoa_review.resolve_source_item_gate_facts(
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
declare
  v_hash pg_catalog.text := pg_catalog.btrim(coalesce(p_revision_hash, ''));
  v_item machimoa_review.source_items%rowtype;
  v_existing machimoa_review.source_item_product_types%rowtype;
  v_ai machimoa_review.processing_jobs%rowtype;
  v_review machimoa_review.processing_jobs%rowtype;
  v_stage pg_catalog.text;
begin
  perform machimoa_review.apply_source_item_gate_facts(
    p_source_item_id,
    p_revision_hash,
    p_gate_facts,
    p_assessment_schema_version,
    p_reviewer,
    p_memo
  );

  select *
    into v_item
  from machimoa_review.source_items as si
  where si.id = p_source_item_id;
  select *
    into v_existing
  from machimoa_review.source_item_product_types as pt
  where pt.source_item_id = p_source_item_id
    and pt.revision_hash = v_hash;
  select *
    into v_ai
  from machimoa_review.processing_jobs as j
  where j.source_item_id = p_source_item_id
    and j.revision_hash = v_hash
    and j.processing_stage = 'ai_enrichment';

  foreach v_stage in array array[
    'region_review',
    'relevance_review',
    'product_type_review'
  ]::pg_catalog.text[]
  loop
    select *
      into v_review
    from machimoa_review.processing_jobs as j
    where j.source_item_id = p_source_item_id
      and j.revision_hash = v_hash
      and j.processing_stage = v_stage
      and j.status in ('queued', 'claimed');
    if found then
      exit;
    end if;
    v_review := null;
  end loop;

  return query select
    v_item.id,
    v_hash,
    v_existing.product_type,
    v_item.disposition,
    v_existing.assessment_schema_version,
    v_existing.evaluated_profile,
    v_ai.id,
    v_ai.status,
    v_review.id,
    v_review.status,
    'confirmed'::pg_catalog.text;
end
$function$;

alter function machimoa_review.evaluate_source_item_gates(
  pg_catalog.bool, pg_catalog.bool, pg_catalog.bool, pg_catalog.text,
  pg_catalog.text[], pg_catalog.jsonb
) owner to postgres;
alter function machimoa_review.resolve_source_item_product_type(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
) owner to postgres;
alter function machimoa_review.resolve_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) owner to postgres;

revoke all privileges on function machimoa_review.evaluate_source_item_gates(
  pg_catalog.bool, pg_catalog.bool, pg_catalog.bool, pg_catalog.text,
  pg_catalog.text[], pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.resolve_source_item_product_type(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text[], pg_catalog.text[], pg_catalog.text, pg_catalog.text,
  pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.resolve_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;

notify pgrst, 'reload schema';

commit;

