-- Restore the exact pre-fix function body. No deadline data is deleted.
-- This reintroduces the ON CONFLICT ambiguity for future manual inputs.
begin;

create or replace function machimoa_review.resolve_source_item_application_deadline(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_application_deadline_kind pg_catalog.text,
  p_application_deadline_on pg_catalog.date,
  p_reviewer pg_catalog.text
)
returns table (
  source_item_id pg_catalog.uuid,
  revision_hash pg_catalog.text,
  application_deadline_kind pg_catalog.text,
  application_deadline_on pg_catalog.date,
  disposition pg_catalog.text,
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
  v_kind pg_catalog.text :=
    pg_catalog.btrim(coalesce(p_application_deadline_kind, ''));
  v_reviewer pg_catalog.text := pg_catalog.btrim(coalesce(p_reviewer, ''));
  v_item machimoa_review.source_items%rowtype;
  v_review machimoa_review.processing_jobs%rowtype;
  v_ai machimoa_review.processing_jobs%rowtype;
  v_pt machimoa_review.source_item_product_types%rowtype;
  v_eval_type pg_catalog.text := null;
  v_eval_facts pg_catalog.jsonb := null;
  v_reasons pg_catalog.text[] := '{}'::pg_catalog.text[];
  v_disposition pg_catalog.text;
  v_review_id pg_catalog.uuid;
  v_review_status pg_catalog.text;
begin
  if not (pg_catalog.char_length(v_reviewer) between 1 and 128) then
    raise exception 'invalid_reviewer';
  end if;
  if v_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'revision_mismatch';
  end if;
  if v_kind = 'fixed' then
    if p_application_deadline_on is null then
      raise exception 'invalid_application_deadline';
    end if;
  elsif v_kind in ('none', 'closed') then
    if p_application_deadline_on is not null then
      raise exception 'invalid_application_deadline';
    end if;
  else
    raise exception 'invalid_application_deadline';
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
    into v_review
  from machimoa_review.processing_jobs as j
  where j.source_item_id = v_item.id
    and j.revision_hash = v_hash
    and j.processing_stage = 'content_review'
  for update;
  if not found
     or v_review.status not in ('queued', 'claimed')
     or not ('application_deadline_unknown' = any(v_review.reason_codes)) then
    raise exception 'application_deadline_review_not_open';
  end if;

  select *
    into v_ai
  from machimoa_review.processing_jobs as j
  where j.source_item_id = v_item.id
    and j.revision_hash = v_hash
    and j.processing_stage = 'ai_enrichment'
  for update;
  if found and v_ai.status = 'claimed' and v_ai.claim_lease_until is null then
    raise exception 'ai_job_malformed_lease';
  end if;
  if found
     and v_ai.status = 'claimed'
     and v_ai.claim_lease_until is not null
     and v_ai.claim_lease_until > v_now then
    raise exception 'ai_job_claimed';
  end if;

  insert into machimoa_review.source_item_application_deadlines (
    source_item_id,
    revision_hash,
    application_deadline_kind,
    application_deadline_on
  )
  values (v_item.id, v_hash, v_kind, p_application_deadline_on)
  on conflict (source_item_id, revision_hash) do update
  set
    application_deadline_kind = excluded.application_deadline_kind,
    application_deadline_on = excluded.application_deadline_on,
    updated_at = v_now;

  update machimoa_review.processing_jobs as j
  set reason_codes = pg_catalog.array_remove(
    j.reason_codes, 'application_deadline_unknown'
  )
  where j.id = v_review.id;

  select *
    into v_pt
  from machimoa_review.source_item_product_types as pt
  where pt.source_item_id = v_item.id
    and pt.revision_hash = v_hash;
  if found
     and machimoa_review.gate_facts_row_is_complete_v1(
       v_pt.product_type,
       v_pt.gate_facts,
       v_pt.assessment_schema_version,
       v_pt.evaluated_profile,
       v_pt.evaluated_at,
       'capital_v1'
     ) then
    v_eval_type := v_pt.product_type;
    v_eval_facts := v_pt.gate_facts;
    v_reasons := v_pt.reason_codes;
  else
    select coalesce(j.reason_codes, '{}'::pg_catalog.text[])
      into v_reasons
    from machimoa_review.processing_jobs as j
    where j.id = v_review.id;
    v_reasons := pg_catalog.array_remove(v_reasons, 'application_deadline_unknown');
  end if;

  v_disposition := machimoa_review.apply_source_item_evaluation(
    v_item.id,
    v_hash,
    v_eval_type,
    v_reasons,
    v_eval_facts
  );

  select j.id, j.status
    into v_review_id, v_review_status
  from machimoa_review.processing_jobs as j
  where j.source_item_id = v_item.id
    and j.revision_hash = v_hash
    and j.processing_stage = 'content_review';

  return query
  select
    v_item.id,
    v_hash,
    v_kind,
    p_application_deadline_on,
    v_disposition,
    v_review_id,
    v_review_status;
end
$function$;

commit;
