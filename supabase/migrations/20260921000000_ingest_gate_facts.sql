-- V1 versioned gate_facts, capital_v1 DB evaluator, v4 upsert, and
-- split legacy/V1 ensure_ai + claim predicates.
-- Do not apply this file without a separate operating-database approval.
-- Non-destructive rollback:
--   supabase/rollback/20260921000001_ingest_gate_facts_rpc_adapters_down.sql
--   then supabase/rollback/20260921000000_ingest_gate_facts_down.sql
-- This migration must not delete curation_candidates, public.curations,
-- ingest_review_decisions, open jobs, or completed AI result rows.
-- v1/v2/v3 upsert and apply_source_item_product_type keep their meaning.
-- apply_source_item_gate_facts / evaluate_source_item_gates have no public adapter.
--
-- Supabase CLI linked db push uses session_user=cli_login_postgres
-- with current_user=postgres. DDL authorization requires current_user=postgres.

begin;

do $guard$
begin
  if current_user <> 'postgres' then
    raise exception
      'ingest gate_facts migration must run as postgres (current_user=%)',
      current_user;
  end if;

  if session_user not in ('postgres', 'cli_login_postgres') then
    raise exception
      'ingest gate_facts migration session_user not allowed (%)',
      session_user;
  end if;

  if pg_catalog.to_regclass('machimoa_review.source_item_product_types') is null then
    raise exception 'machimoa_review.source_item_product_types must exist';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.upsert_source_observations_v3(pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb)'
     ) is null then
    raise exception 'machimoa_review.upsert_source_observations_v3 signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.ensure_ai_enrichment_job(pg_catalog.uuid, pg_catalog.text, pg_catalog.text[])'
     ) is null then
    raise exception 'machimoa_review.ensure_ai_enrichment_job signature is missing';
  end if;
  if pg_catalog.to_regprocedure(
       'machimoa_review.apply_source_item_product_type(pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb)'
     ) is null then
    raise exception 'machimoa_review.apply_source_item_product_type signature is missing';
  end if;
end
$guard$;

alter table machimoa_review.source_item_product_types
  add column gate_facts pg_catalog.jsonb,
  add column assessment_schema_version pg_catalog.text,
  add column evaluated_profile pg_catalog.text,
  add column evaluated_at pg_catalog.timestamptz;

alter table machimoa_review.source_item_product_types
  drop constraint source_item_product_types_type_ck;

alter table machimoa_review.source_item_product_types
  add constraint source_item_product_types_type_ck
  check (
    product_type in ('event_program', 'policy_reference', 'living_guide')
  );

alter table machimoa_review.source_item_product_types
  add constraint source_item_product_types_gate_state_ck
  check (
    (
      gate_facts is null
      and assessment_schema_version is null
      and evaluated_profile is null
      and evaluated_at is null
    )
    or (
      gate_facts is not null
      and pg_catalog.jsonb_typeof(gate_facts) = 'object'
      and gate_facts <> '{}'::pg_catalog.jsonb
      and assessment_schema_version is not null
      and pg_catalog.char_length(assessment_schema_version) between 1 and 64
      and evaluated_profile is not null
      and pg_catalog.char_length(evaluated_profile) between 1 and 64
      and evaluated_at is not null
      and not (gate_facts ?| array[
        'audience_relevance',
        'nationwide_or_online',
        'kr_japan_activity',
        'kr_jp_exchange',
        'activity_region_codes',
        'capital',
        'noncapital'
      ]::pg_catalog.text[])
      and (
        (
          product_type = 'living_guide'
          and gate_facts ? 'schema_version'
          and not gate_facts ? 'eligibility_scope'
          and not gate_facts ? 'eligibility_region_codes'
          and not gate_facts ? 'eligibility_region_evidence'
          and not gate_facts ? 'foreign_resident_eligibility'
        )
        or (
          product_type = 'event_program'
          and gate_facts ? 'schema_version'
          and gate_facts ? 'eligibility_scope'
          and gate_facts ? 'eligibility_region_codes'
          and gate_facts ? 'eligibility_region_evidence'
          and not gate_facts ? 'foreign_resident_eligibility'
        )
        or (
          product_type = 'policy_reference'
          and gate_facts ? 'schema_version'
          and gate_facts ? 'eligibility_scope'
          and gate_facts ? 'eligibility_region_codes'
          and gate_facts ? 'eligibility_region_evidence'
          and gate_facts ? 'foreign_resident_eligibility'
        )
      )
    )
  );

create function machimoa_review.gate_facts_row_is_legacy(
  p_gate_facts pg_catalog.jsonb,
  p_assessment_schema_version pg_catalog.text,
  p_evaluated_profile pg_catalog.text,
  p_evaluated_at pg_catalog.timestamptz
)
returns pg_catalog.bool
language sql
stable
security definer
set search_path = ''
as $function$
  select
    p_gate_facts is null
    and p_assessment_schema_version is null
    and p_evaluated_profile is null
    and p_evaluated_at is null;
$function$;

create function machimoa_review.validate_gate_facts(
  p_product_type pg_catalog.text,
  p_gate_facts pg_catalog.jsonb
)
returns pg_catalog.jsonb
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_type pg_catalog.text := pg_catalog.btrim(coalesce(p_product_type, ''));
  v_schema pg_catalog.text;
  v_scope pg_catalog.text;
  v_codes pg_catalog.text[];
  v_evidence pg_catalog.text;
  v_audience pg_catalog.text;
  v_delivery pg_catalog.text;
  v_out pg_catalog.jsonb;
begin
  if v_type not in ('event_program', 'policy_reference', 'living_guide') then
    raise exception 'invalid_product_type';
  end if;
  if p_gate_facts is null or pg_catalog.jsonb_typeof(p_gate_facts) <> 'object' then
    raise exception 'invalid_gate_facts';
  end if;
  if p_gate_facts = '{}'::pg_catalog.jsonb then
    raise exception 'gate_facts_incomplete';
  end if;
  if exists (
    select 1
    from pg_catalog.jsonb_object_keys(p_gate_facts) as key
    where key in (
      'audience_relevance',
      'nationwide_or_online',
      'kr_japan_activity',
      'kr_jp_exchange',
      'activity_region_codes',
      'capital',
      'noncapital'
    )
  ) then
    raise exception 'invalid_gate_facts';
  end if;
  if exists (
    select 1
    from pg_catalog.jsonb_object_keys(p_gate_facts) as key
    where key not in (
      'schema_version',
      'eligibility_scope',
      'eligibility_region_codes',
      'eligibility_region_evidence',
      'foreign_resident_eligibility',
      'delivery_mode'
    )
  ) then
    raise exception 'invalid_gate_facts';
  end if;

  v_schema := pg_catalog.btrim(coalesce(p_gate_facts ->> 'schema_version', ''));
  if v_schema is distinct from 'gate-facts-v1' then
    raise exception 'invalid_assessment_schema_version';
  end if;

  if p_gate_facts ? 'delivery_mode' then
    v_delivery := pg_catalog.btrim(coalesce(p_gate_facts ->> 'delivery_mode', ''));
    if v_delivery not in ('online', 'offline', 'hybrid', 'unknown') then
      raise exception 'invalid_gate_facts';
    end if;
  else
    v_delivery := null;
  end if;

  v_out := pg_catalog.jsonb_build_object('schema_version', v_schema);

  if v_type = 'living_guide' then
    if p_gate_facts ? 'eligibility_scope'
       or p_gate_facts ? 'eligibility_region_codes'
       or p_gate_facts ? 'eligibility_region_evidence'
       or p_gate_facts ? 'foreign_resident_eligibility' then
      raise exception 'invalid_gate_facts';
    end if;
    if v_delivery is not null then
      v_out := v_out || pg_catalog.jsonb_build_object('delivery_mode', v_delivery);
    end if;
    return v_out;
  end if;

  if not (
    p_gate_facts ? 'eligibility_scope'
    and p_gate_facts ? 'eligibility_region_codes'
    and p_gate_facts ? 'eligibility_region_evidence'
  ) then
    raise exception 'gate_facts_incomplete';
  end if;
  if v_type = 'policy_reference' and not p_gate_facts ? 'foreign_resident_eligibility' then
    raise exception 'gate_facts_incomplete';
  end if;
  if v_type = 'event_program' and p_gate_facts ? 'foreign_resident_eligibility' then
    raise exception 'invalid_gate_facts';
  end if;

  v_scope := pg_catalog.btrim(coalesce(p_gate_facts ->> 'eligibility_scope', ''));
  if v_scope not in ('nationwide', 'specific', 'unknown') then
    raise exception 'invalid_gate_facts';
  end if;
  if pg_catalog.jsonb_typeof(p_gate_facts -> 'eligibility_region_codes') <> 'array' then
    raise exception 'invalid_gate_facts';
  end if;
  if exists (
    select 1
    from pg_catalog.jsonb_array_elements(p_gate_facts -> 'eligibility_region_codes') as elem
    where pg_catalog.jsonb_typeof(elem) <> 'string'
       or pg_catalog.btrim(elem #>> '{}') = ''
  ) then
    raise exception 'invalid_gate_facts';
  end if;
  v_codes := coalesce(
    array(
      select pg_catalog.btrim(pg_catalog.jsonb_array_elements_text(
        p_gate_facts -> 'eligibility_region_codes'
      ))
    ),
    '{}'::pg_catalog.text[]
  );
  if v_scope = 'specific'
     and (pg_catalog.cardinality(v_codes) is null or pg_catalog.cardinality(v_codes) < 1) then
    raise exception 'invalid_gate_facts';
  end if;
  if v_scope in ('nationwide', 'unknown')
     and pg_catalog.cardinality(v_codes) is not null
     and pg_catalog.cardinality(v_codes) > 0 then
    raise exception 'invalid_gate_facts';
  end if;
  if pg_catalog.jsonb_typeof(p_gate_facts -> 'eligibility_region_evidence') <> 'string' then
    raise exception 'invalid_gate_facts';
  end if;
  v_evidence := coalesce(p_gate_facts ->> 'eligibility_region_evidence', '');
  if pg_catalog.char_length(v_evidence) > 500 then
    raise exception 'invalid_gate_facts';
  end if;

  v_out := v_out || pg_catalog.jsonb_build_object(
    'eligibility_scope', v_scope,
    'eligibility_region_codes', coalesce(p_gate_facts -> 'eligibility_region_codes', '[]'::pg_catalog.jsonb),
    'eligibility_region_evidence', v_evidence
  );

  if v_type = 'policy_reference' then
    v_audience := pg_catalog.btrim(coalesce(p_gate_facts ->> 'foreign_resident_eligibility', ''));
    if v_audience not in ('eligible', 'ineligible', 'unknown') then
      raise exception 'invalid_gate_facts';
    end if;
    v_out := v_out || pg_catalog.jsonb_build_object(
      'foreign_resident_eligibility', v_audience
    );
  end if;

  if v_delivery is not null then
    v_out := v_out || pg_catalog.jsonb_build_object('delivery_mode', v_delivery);
  end if;
  return v_out;
end
$function$;

create function machimoa_review.gate_facts_row_is_complete_v1(
  p_product_type pg_catalog.text,
  p_gate_facts pg_catalog.jsonb,
  p_assessment_schema_version pg_catalog.text,
  p_evaluated_profile pg_catalog.text,
  p_evaluated_at pg_catalog.timestamptz,
  p_expected_profile pg_catalog.text
)
returns pg_catalog.bool
language plpgsql
stable
security definer
set search_path = ''
as $function$
begin
  if p_gate_facts is null or p_gate_facts = '{}'::pg_catalog.jsonb then
    return false;
  end if;
  if p_assessment_schema_version is distinct from 'gate-facts-v1' then
    return false;
  end if;
  if p_evaluated_profile is distinct from p_expected_profile then
    return false;
  end if;
  if p_evaluated_at is null then
    return false;
  end if;
  perform machimoa_review.validate_gate_facts(p_product_type, p_gate_facts);
  return true;
exception
  when raise_exception then
    if sqlerrm in (
      'invalid_gate_facts',
      'gate_facts_incomplete',
      'invalid_assessment_schema_version',
      'invalid_product_type'
    ) then
      return false;
    end if;
    raise;
end
$function$;

create function machimoa_review.evaluate_source_item_gates(
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

create function machimoa_review.sync_source_item_evaluation_jobs(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_jobs pg_catalog.jsonb
)
returns pg_catalog.void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_hash pg_catalog.text := pg_catalog.btrim(coalesce(p_revision_hash, ''));
  v_jobs pg_catalog.jsonb := coalesce(p_jobs, '[]'::pg_catalog.jsonb);
  v_stage pg_catalog.text;
  v_reasons pg_catalog.text[];
  v_wanted pg_catalog.bool;
  v_job machimoa_review.processing_jobs%rowtype;
begin
  foreach v_stage in array array[
    'region_review',
    'relevance_review',
    'product_type_review',
    'content_review'
  ]::pg_catalog.text[]
  loop
    select coalesce(
      array(
        select pg_catalog.jsonb_array_elements_text(
          coalesce(picked.job -> 'reason_codes', '[]'::pg_catalog.jsonb)
        )
        from (
          select elem as job
          from pg_catalog.jsonb_array_elements(v_jobs) as elem
          where pg_catalog.btrim(coalesce(elem ->> 'stage', '')) = v_stage
          limit 1
        ) as picked
      ),
      '{}'::pg_catalog.text[]
    )
      into v_reasons;
    v_wanted := exists (
      select 1
      from pg_catalog.jsonb_array_elements(v_jobs) as elem
      where pg_catalog.btrim(coalesce(elem ->> 'stage', '')) = v_stage
    );

    select *
      into v_job
    from machimoa_review.processing_jobs as j
    where j.source_item_id = p_source_item_id
      and j.revision_hash = v_hash
      and j.processing_stage = v_stage
    for update;

    if v_wanted then
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
          p_source_item_id,
          v_hash,
          v_stage,
          'queued',
          v_now,
          v_now,
          v_reasons
        );
      elsif v_job.status not in ('queued', 'claimed') then
        update machimoa_review.processing_jobs as j
        set
          status = 'queued',
          available_at = v_now,
          claimed_by = null,
          claim_lease_until = null,
          completed_at = null,
          next_retry_at = null,
          reason_codes = v_reasons
        where j.id = v_job.id;
      end if;
    elsif found and v_job.status in ('queued', 'claimed') then
      update machimoa_review.processing_jobs as j
      set
        status = 'completed',
        completed_at = v_now,
        claimed_by = null,
        claim_lease_until = null
      where j.id = v_job.id;
    end if;
  end loop;
end
$function$;

create function machimoa_review.apply_source_item_evaluation(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_product_type pg_catalog.text,
  p_product_type_reasons pg_catalog.text[],
  p_gate_facts pg_catalog.jsonb
)
returns pg_catalog.text
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_hash pg_catalog.text := pg_catalog.btrim(coalesce(p_revision_hash, ''));
  v_item machimoa_review.source_items%rowtype;
  v_eval record;
begin
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
    into v_eval
  from machimoa_review.evaluate_source_item_gates(
    v_item.body_usable,
    v_item.has_source_url,
    v_item.attachment_present,
    p_product_type,
    p_product_type_reasons,
    p_gate_facts
  );

  update machimoa_review.source_items as si
  set disposition = v_eval.disposition
  where si.id = v_item.id
    and si.disposition is distinct from v_eval.disposition;

  perform machimoa_review.sync_source_item_evaluation_jobs(
    v_item.id,
    v_hash,
    v_eval.jobs
  );
  perform machimoa_review.ensure_ai_enrichment_job(
    v_item.id,
    v_hash,
    coalesce(
      array(
        select pg_catalog.jsonb_array_elements_text(
          coalesce(picked.job -> 'reason_codes', '[]'::pg_catalog.jsonb)
        )
        from (
          select elem as job
          from pg_catalog.jsonb_array_elements(v_eval.jobs) as elem
          limit 1
        ) as picked
      ),
      '{}'::pg_catalog.text[]
    )
  );
  return v_eval.disposition;
end
$function$;

create function machimoa_review.apply_source_item_product_type_v4(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_classification pg_catalog.jsonb,
  p_gate_facts pg_catalog.jsonb
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
  v_existing machimoa_review.source_item_product_types%rowtype;
  v_facts pg_catalog.jsonb;
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

  if p_classification is null or p_classification = 'null'::pg_catalog.jsonb then
    return;
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
    return;
  end if;

  v_type := pg_catalog.btrim(coalesce(p_classification ->> 'product_type', ''));
  if v_type not in ('event_program', 'policy_reference', 'living_guide') then
    raise exception 'invalid_product_type';
  end if;
  if p_gate_facts is null or p_gate_facts = 'null'::pg_catalog.jsonb then
    raise exception 'invalid_gate_facts';
  end if;
  v_facts := machimoa_review.validate_gate_facts(v_type, p_gate_facts);

  insert into machimoa_review.source_item_product_types (
    source_item_id,
    revision_hash,
    product_type,
    origin,
    rule_version,
    reason_codes,
    period_signals,
    reviewer,
    memo,
    gate_facts,
    assessment_schema_version,
    evaluated_profile,
    evaluated_at
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
    null,
    v_facts,
    'gate-facts-v1',
    'capital_v1',
    v_now
  );
end
$function$;

create function machimoa_review.apply_source_item_gate_facts(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_gate_facts pg_catalog.jsonb,
  p_assessment_schema_version pg_catalog.text,
  p_reviewer pg_catalog.text,
  p_memo pg_catalog.text
)
returns pg_catalog.void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_now pg_catalog.timestamptz := pg_catalog.now();
  v_hash pg_catalog.text := pg_catalog.btrim(coalesce(p_revision_hash, ''));
  v_schema pg_catalog.text := pg_catalog.btrim(coalesce(p_assessment_schema_version, ''));
  v_reviewer pg_catalog.text := pg_catalog.btrim(coalesce(p_reviewer, ''));
  v_memo pg_catalog.text := nullif(pg_catalog.btrim(coalesce(p_memo, '')), '');
  v_item machimoa_review.source_items%rowtype;
  v_existing machimoa_review.source_item_product_types%rowtype;
  v_ai machimoa_review.processing_jobs%rowtype;
  v_facts pg_catalog.jsonb;
begin
  if p_source_item_id is null then
    raise exception 'source_item_not_found';
  end if;
  if v_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'revision_mismatch';
  end if;
  if v_schema is distinct from 'gate-facts-v1' then
    raise exception 'invalid_assessment_schema_version';
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

  select *
    into v_existing
  from machimoa_review.source_item_product_types as pt
  where pt.source_item_id = v_item.id
    and pt.revision_hash = v_hash
  for update;
  if not found then
    raise exception 'product_type_not_confirmed';
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
    raise exception 'ai_job_claimed';
  end if;

  v_facts := machimoa_review.validate_gate_facts(v_existing.product_type, p_gate_facts);

  update machimoa_review.source_item_product_types as pt
  set
    gate_facts = v_facts,
    assessment_schema_version = 'gate-facts-v1',
    evaluated_profile = 'capital_v1',
    evaluated_at = v_now,
    reviewer = v_reviewer,
    memo = v_memo,
    updated_at = v_now
  where pt.source_item_id = v_item.id
    and pt.revision_hash = v_hash;

  perform machimoa_review.apply_source_item_evaluation(
    v_item.id,
    v_hash,
    v_existing.product_type,
    v_existing.reason_codes,
    v_facts
  );
end
$function$;

create function machimoa_review.resolve_source_item_gate_facts(
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
  v_pt machimoa_review.source_item_product_types%rowtype;
  v_ai_found pg_catalog.bool := false;
  v_pt_found pg_catalog.bool := false;
  v_legacy_ready pg_catalog.bool := false;
  v_v1_ready pg_catalog.bool := false;
  v_ready pg_catalog.bool := false;
  v_v1_row pg_catalog.bool := false;
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
  v_ai_found := found;

  select *
    into v_pt
  from machimoa_review.source_item_product_types as pt
  where pt.source_item_id = v_item.id
    and pt.revision_hash is not distinct from v_hash
  for update;
  v_pt_found := found;
  v_v1_row := v_pt_found and v_pt.gate_facts is not null;

  v_legacy_ready :=
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
        and pt.gate_facts is null
        and pt.assessment_schema_version is null
        and pt.evaluated_profile is null
        and pt.evaluated_at is null
    );

  v_v1_ready :=
    v_item.revision_hash is not distinct from v_hash
    and v_item.disposition = 'target'
    and v_item.body_usable is true
    and v_item.has_source_url is true
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
        and pt.gate_facts is not null
        and pt.gate_facts <> '{}'::pg_catalog.jsonb
        and pt.assessment_schema_version is not distinct from 'gate-facts-v1'
        and pt.evaluated_profile is not distinct from 'capital_v1'
        and pt.evaluated_at is not null
        and case
          when machimoa_review.gate_facts_row_is_complete_v1(
            pt.product_type,
            pt.gate_facts,
            pt.assessment_schema_version,
            pt.evaluated_profile,
            pt.evaluated_at,
            'capital_v1'
          ) then exists (
            select 1
            from machimoa_review.evaluate_source_item_gates(
              v_item.body_usable,
              v_item.has_source_url,
              v_item.attachment_present,
              pt.product_type,
              pt.reason_codes,
              pt.gate_facts
            ) as ev
            where ev.disposition is not distinct from 'target'
          )
          else false
        end
    );

  v_ready := v_legacy_ready or v_v1_ready;

  if v_ai_found
     and v_ai.status = 'claimed'
     and v_ai.claim_lease_until is null then
    if v_ready then
      raise exception 'ai_job_malformed_lease';
    end if;
    return;
  end if;

  if not v_ready then
    if v_v1_row
       and v_ai_found
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
          else array['v1_not_ai_ready']::pg_catalog.text[]
        end
      where j.id = v_ai.id;
    end if;
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

create function machimoa_review.upsert_source_observations_v4(
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
  v_facts pg_catalog.jsonb;
  v_kind pg_catalog.text;
  v_source_id pg_catalog.text := pg_catalog.btrim(coalesce(p_source_id, ''));
  v_hash pg_catalog.text;
  v_locked machimoa_review.source_items%rowtype;
  v_existing machimoa_review.source_item_product_types%rowtype;
  v_reasons pg_catalog.text[];
  v_upsert_row record;
  v_eval_type pg_catalog.text;
  v_eval_facts pg_catalog.jsonb;
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
      if exists (
        select 1
        from pg_catalog.jsonb_array_elements(v_jobs) as job
        where pg_catalog.btrim(coalesce(job ->> 'stage', ''))
              is distinct from 'relationship_review'
      ) then
        raise exception 'invalid_classifier_decision';
      end if;
    end if;

    v_meta := v_item -> 'classifier_decision';
    if v_meta is not null and v_meta <> 'null'::pg_catalog.jsonb then
      raise exception 'classifier_metadata_forbidden';
    end if;

    v_pt := v_item -> 'product_type_classification';
    if v_pt is null or v_pt = 'null'::pg_catalog.jsonb then
      v_pt := null;
    end if;
    if v_pt is not null then
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
      v_facts := v_item -> 'gate_facts';
      if v_facts is null or v_facts = 'null'::pg_catalog.jsonb then
        v_facts := null;
      end if;

      if v_locked.body_usable is true and v_locked.has_source_url is true then
        perform machimoa_review.apply_source_item_product_type_v4(
          v_locked.id,
          v_locked.revision_hash,
          v_pt,
          v_facts
        );
      end if;

      select *
        into v_existing
      from machimoa_review.source_item_product_types as pt
      where pt.source_item_id = v_locked.id
        and pt.revision_hash = v_hash;

      v_eval_type := null;
      v_eval_facts := null;
      v_reasons := '{}'::pg_catalog.text[];
      if found
         and machimoa_review.gate_facts_row_is_complete_v1(
           v_existing.product_type,
           v_existing.gate_facts,
           v_existing.assessment_schema_version,
           v_existing.evaluated_profile,
           v_existing.evaluated_at,
           'capital_v1'
         ) then
        v_eval_type := v_existing.product_type;
        v_eval_facts := v_existing.gate_facts;
        v_reasons := v_existing.reason_codes;
      else
        v_kind := pg_catalog.btrim(coalesce(v_pt ->> 'kind', ''));
        if v_pt is not null and v_kind = 'review' then
          v_reasons := coalesce(
            array(
              select pg_catalog.jsonb_array_elements_text(
                coalesce(v_pt -> 'reason_codes', '[]'::pg_catalog.jsonb)
              )
            ),
            '{}'::pg_catalog.text[]
          );
        end if;
      end if;

      perform machimoa_review.apply_source_item_evaluation(
        v_locked.id,
        v_locked.revision_hash,
        v_eval_type,
        v_reasons,
        v_eval_facts
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
      and (
        (
          exists (
            select 1
            from machimoa_review.source_item_product_types as pt
            where pt.source_item_id = j.source_item_id
              and pt.revision_hash is not distinct from j.revision_hash
              and pt.gate_facts is null
              and pt.assessment_schema_version is null
              and pt.evaluated_profile is null
              and pt.evaluated_at is null
          )
          and exists (
            select 1
            from machimoa_review.ingest_review_decisions as d
            where d.source_item_id = j.source_item_id
              and d.revision_hash is not distinct from j.revision_hash
              and d.decision = 'approve_ai'
          )
        )
        or (
          exists (
            select 1
            from machimoa_review.source_item_product_types as pt
            where pt.source_item_id = j.source_item_id
              and pt.revision_hash is not distinct from j.revision_hash
              and pt.gate_facts is not null
              and pt.gate_facts <> '{}'::pg_catalog.jsonb
              and pt.assessment_schema_version is not distinct from 'gate-facts-v1'
              and pt.evaluated_profile is not distinct from 'capital_v1'
              and pt.evaluated_at is not null
              and case
                when machimoa_review.gate_facts_row_is_complete_v1(
                  pt.product_type,
                  pt.gate_facts,
                  pt.assessment_schema_version,
                  pt.evaluated_profile,
                  pt.evaluated_at,
                  'capital_v1'
                ) then exists (
                  select 1
                  from machimoa_review.evaluate_source_item_gates(
                    si.body_usable,
                    si.has_source_url,
                    si.attachment_present,
                    pt.product_type,
                    pt.reason_codes,
                    pt.gate_facts
                  ) as ev
                  where ev.disposition is not distinct from 'target'
                )
                else false
              end
          )
        )
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

alter function machimoa_review.gate_facts_row_is_legacy(
  pg_catalog.jsonb, pg_catalog.text, pg_catalog.text, pg_catalog.timestamptz
) owner to postgres;
alter function machimoa_review.validate_gate_facts(
  pg_catalog.text, pg_catalog.jsonb
) owner to postgres;
alter function machimoa_review.gate_facts_row_is_complete_v1(
  pg_catalog.text, pg_catalog.jsonb, pg_catalog.text, pg_catalog.text,
  pg_catalog.timestamptz, pg_catalog.text
) owner to postgres;
alter function machimoa_review.evaluate_source_item_gates(
  pg_catalog.bool, pg_catalog.bool, pg_catalog.bool, pg_catalog.text,
  pg_catalog.text[], pg_catalog.jsonb
) owner to postgres;
alter function machimoa_review.sync_source_item_evaluation_jobs(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb
) owner to postgres;
alter function machimoa_review.apply_source_item_evaluation(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text[],
  pg_catalog.jsonb
) owner to postgres;
alter function machimoa_review.apply_source_item_product_type_v4(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.jsonb
) owner to postgres;
alter function machimoa_review.apply_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) owner to postgres;
alter function machimoa_review.resolve_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) owner to postgres;
alter function machimoa_review.ensure_ai_enrichment_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text[]
) owner to postgres;
alter function machimoa_review.upsert_source_observations_v4(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) owner to postgres;
alter function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) owner to postgres;

revoke all privileges on function machimoa_review.gate_facts_row_is_legacy(
  pg_catalog.jsonb, pg_catalog.text, pg_catalog.text, pg_catalog.timestamptz
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.validate_gate_facts(
  pg_catalog.text, pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.gate_facts_row_is_complete_v1(
  pg_catalog.text, pg_catalog.jsonb, pg_catalog.text, pg_catalog.text,
  pg_catalog.timestamptz, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.evaluate_source_item_gates(
  pg_catalog.bool, pg_catalog.bool, pg_catalog.bool, pg_catalog.text,
  pg_catalog.text[], pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.sync_source_item_evaluation_jobs(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.apply_source_item_evaluation(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text[],
  pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.apply_source_item_product_type_v4(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.apply_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.resolve_source_item_gate_facts(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.jsonb, pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.ensure_ai_enrichment_job(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text[]
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.upsert_source_observations_v4(
  pg_catalog.text, pg_catalog.uuid, pg_catalog.jsonb, pg_catalog.jsonb
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.claim_processing_jobs(
  pg_catalog.text, pg_catalog.int4, pg_catalog.text, pg_catalog.int4
) from public, anon, authenticated, service_role;

commit;
