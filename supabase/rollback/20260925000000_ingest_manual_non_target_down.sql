-- Restore the content-review close writer and evaluator.
-- Does not delete decision, job, candidate, or publication rows.
-- Does not revert candidate review_status. Fails closed when a product_type
-- decision or a manual_non_target reason already exists.

begin;

lock table machimoa_review.ingest_review_decisions in access exclusive mode;

do $guard$
begin
  if exists (
    select 1
    from machimoa_review.ingest_review_decisions as d
    where d.review_type = 'product_type'
       or 'manual_non_target' = any(d.reason_codes)
  ) then
    raise exception 'rollback_manual_non_target_data_present';
  end if;
end
$guard$;

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
  v_curation_source pg_catalog.text;
begin
  if p_source_item_id is null then
    raise exception 'source_item_not_found';
  end if;
  if v_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'revision_mismatch';
  end if;
  if v_type not in ('region', 'relevance', 'content') then
    raise exception 'invalid_review_type';
  end if;
  if v_decision not in ('approve_ai', 'reject', 'needs_review') then
    raise exception 'invalid_decision';
  end if;
  if v_type = 'content' and v_decision is distinct from 'reject' then
    raise exception 'invalid_decision';
  end if;
  if v_type = 'content'
     and not (
       'insufficient_evidence' = any(coalesce(v_reasons, '{}'::pg_catalog.text[]))
     ) then
    raise exception 'insufficient_evidence_required';
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

  if v_type = 'content' and v_decision = 'reject' then
    select *
      into v_review
    from machimoa_review.processing_jobs as j
    where j.source_item_id = v_item.id
      and j.revision_hash = v_hash
      and j.processing_stage = 'content_review'
      and j.status in ('queued', 'claimed')
    for update;
    if not found then
      raise exception 'content_review_not_open';
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
      raise exception 'ai_job_claimed';
    end if;

    select s.legacy_curation_source
      into v_curation_source
    from machimoa_review.ingest_sources as s
    where s.source_id = v_item.source_id;

    perform pg_catalog.pg_advisory_xact_lock(
      pg_catalog.hashtextextended(
        v_curation_source || ':' || v_item.external_key,
        0::pg_catalog.int8
      )
    );

    if exists (
      select 1
      from machimoa_review.curation_candidates as c
      where c.source_item_id = v_item.external_key
        and c.source_revision_hash = v_hash
        and c.source in (v_curation_source, v_item.source_id)
    ) then
      raise exception 'curation_candidate_exists';
    end if;
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
    when 'content' then 'content_review'
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

create or replace function machimoa_review.apply_source_item_evaluation(
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
  v_closed pg_catalog.bool := false;
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

  v_closed := exists (
    select 1
    from machimoa_review.ingest_review_decisions as d
    where d.source_item_id = v_item.id
      and d.revision_hash is not distinct from v_hash
      and d.review_type = 'content'
      and d.decision = 'reject'
      and 'insufficient_evidence' = any(d.reason_codes)
  );
  if v_closed then
    update machimoa_review.source_items as si
    set disposition = 'non_target'
    where si.id = v_item.id
      and si.disposition is distinct from 'non_target';

    perform machimoa_review.sync_source_item_evaluation_jobs(
      v_item.id,
      v_hash,
      '[]'::pg_catalog.jsonb
    );
    perform machimoa_review.ensure_ai_enrichment_job(
      v_item.id,
      v_hash,
      array['insufficient_evidence']::pg_catalog.text[]
    );
    return 'non_target';
  end if;

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

alter function machimoa_review.apply_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) owner to postgres;
alter function machimoa_review.apply_source_item_evaluation(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text[],
  pg_catalog.jsonb
) owner to postgres;

revoke all privileges on function machimoa_review.apply_ingest_review_decision(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text,
  pg_catalog.text, pg_catalog.text[], pg_catalog.text[], pg_catalog.text,
  pg_catalog.text, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.apply_source_item_evaluation(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.text[],
  pg_catalog.jsonb
) from public, anon, authenticated, service_role;

alter table machimoa_review.ingest_review_decisions
  drop constraint ingest_review_decisions_type_ck;

alter table machimoa_review.ingest_review_decisions
  add constraint ingest_review_decisions_type_ck
  check (review_type in ('region', 'relevance', 'content'));

notify pgrst, 'reload schema';

commit;
