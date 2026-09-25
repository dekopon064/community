-- Human-confirmed display category is separate from product type and source label.
-- Existing candidates and curations remain nullable until a separate approved backfill.
begin;

create table machimoa_review.source_item_user_categories (
  source_item_id pg_catalog.uuid not null
    references machimoa_review.source_items (id) on delete restrict,
  revision_hash pg_catalog.text not null,
  user_category pg_catalog.text not null,
  reviewer pg_catalog.text not null,
  created_at pg_catalog.timestamptz not null default pg_catalog.now(),
  updated_at pg_catalog.timestamptz not null default pg_catalog.now(),
  constraint source_item_user_categories_pk primary key (source_item_id, revision_hash),
  constraint source_item_user_categories_hash_ck check (revision_hash ~ '^[0-9a-f]{64}$'),
  constraint source_item_user_categories_kind_ck check (
    user_category in ('policy', 'program', 'event', 'youth_space', 'living')
  ),
  constraint source_item_user_categories_reviewer_ck check (
    pg_catalog.char_length(pg_catalog.btrim(reviewer)) between 1 and 128
  )
);
alter table machimoa_review.source_item_user_categories owner to postgres;
alter table machimoa_review.source_item_user_categories enable row level security;
revoke all privileges on table machimoa_review.source_item_user_categories
  from public, anon, authenticated, service_role;

create table machimoa_review.source_item_event_periods (
  source_item_id pg_catalog.uuid not null,
  revision_hash pg_catalog.text not null,
  event_start_on pg_catalog.date not null,
  event_end_on pg_catalog.date not null,
  created_at pg_catalog.timestamptz not null default pg_catalog.now(),
  updated_at pg_catalog.timestamptz not null default pg_catalog.now(),
  constraint source_item_event_periods_pk primary key (source_item_id, revision_hash),
  constraint source_item_event_periods_category_fk foreign key (source_item_id, revision_hash)
    references machimoa_review.source_item_user_categories (source_item_id, revision_hash)
    on delete restrict,
  constraint source_item_event_periods_order_ck check (event_start_on <= event_end_on)
);
alter table machimoa_review.source_item_event_periods owner to postgres;
alter table machimoa_review.source_item_event_periods enable row level security;
revoke all privileges on table machimoa_review.source_item_event_periods
  from public, anon, authenticated, service_role;

alter table machimoa_review.curation_candidates
  add column user_category pg_catalog.text,
  add column event_start_on pg_catalog.date,
  add column event_end_on pg_catalog.date,
  add constraint curation_candidates_user_category_period_ck check (
    (user_category is null and event_start_on is null and event_end_on is null)
    or (user_category in ('policy', 'program')
        and application_deadline_kind is not null
        and event_start_on is null and event_end_on is null)
    or (user_category = 'event'
        and application_deadline_kind is null
        and event_start_on is not null and event_end_on is not null
        and event_start_on <= event_end_on)
    or (user_category in ('youth_space', 'living')
        and application_deadline_kind is null
        and event_start_on is null and event_end_on is null)
  );

alter table public.curations
  add column user_category pg_catalog.text,
  add column event_start_on pg_catalog.date,
  add column event_end_on pg_catalog.date,
  add constraint curations_user_category_period_ck check (
    (user_category is null and event_start_on is null and event_end_on is null)
    or (user_category in ('policy', 'program')
        and application_deadline_kind is not null
        and event_start_on is null and event_end_on is null)
    or (user_category = 'event'
        and application_deadline_kind is null
        and event_start_on is not null and event_end_on is not null
        and event_start_on <= event_end_on)
    or (user_category in ('youth_space', 'living')
        and application_deadline_kind is null
        and event_start_on is null and event_end_on is null)
  );

create function machimoa_review.category_period_ready(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text
)
returns pg_catalog.bool
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1
    from machimoa_review.source_item_user_categories as cat
    where cat.source_item_id = p_source_item_id
      and cat.revision_hash is not distinct from p_revision_hash
      and (
        (cat.user_category in ('policy', 'program') and exists (
          select 1 from machimoa_review.source_item_application_deadlines as dl
          where dl.source_item_id = cat.source_item_id
            and dl.revision_hash = cat.revision_hash
        ))
        or (cat.user_category = 'event' and exists (
          select 1 from machimoa_review.source_item_event_periods as ep
          where ep.source_item_id = cat.source_item_id
            and ep.revision_hash = cat.revision_hash
        ))
        or cat.user_category in ('youth_space', 'living')
      )
  )
$function$;

create function machimoa_review.append_content_review_reason(
  p_jobs pg_catalog.jsonb,
  p_reason pg_catalog.text
)
returns pg_catalog.jsonb
language plpgsql
immutable
security definer
set search_path = ''
as $function$
declare
  v_jobs pg_catalog.jsonb := coalesce(p_jobs, '[]'::pg_catalog.jsonb);
  v_index pg_catalog.int4;
  v_job pg_catalog.jsonb;
  v_reasons pg_catalog.jsonb;
begin
  if p_reason not in (
    'user_category_unconfirmed',
    'application_deadline_unknown',
    'event_period_unknown'
  ) then
    raise exception 'invalid_content_review_reason';
  end if;
  if pg_catalog.jsonb_typeof(v_jobs) is distinct from 'array' then
    v_jobs := '[]'::pg_catalog.jsonb;
  end if;
  if pg_catalog.jsonb_array_length(v_jobs) > 0 then
    for v_index in 0 .. pg_catalog.jsonb_array_length(v_jobs) - 1 loop
      v_job := v_jobs -> v_index;
      if pg_catalog.btrim(coalesce(v_job ->> 'stage', '')) = 'content_review' then
        v_reasons := coalesce(v_job -> 'reason_codes', '[]'::pg_catalog.jsonb);
        if not exists (
          select 1 from pg_catalog.jsonb_array_elements_text(v_reasons) as code
          where code = p_reason
        ) then
          v_reasons := v_reasons || pg_catalog.jsonb_build_array(p_reason);
          v_job := pg_catalog.jsonb_set(v_job, '{reason_codes}', v_reasons, true);
          v_jobs := pg_catalog.jsonb_set(
            v_jobs, array[v_index::pg_catalog.text], v_job, false
          );
        end if;
        return v_jobs;
      end if;
    end loop;
  end if;
  return v_jobs || pg_catalog.jsonb_build_array(
    pg_catalog.jsonb_build_object(
      'stage', 'content_review',
      'reason_codes', pg_catalog.jsonb_build_array(p_reason)
    )
  );
end
$function$;

create function machimoa_review.resolve_source_item_user_category(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_user_category pg_catalog.text,
  p_event_start_on pg_catalog.date,
  p_event_end_on pg_catalog.date,
  p_reviewer pg_catalog.text
)
returns table (
  source_item_id pg_catalog.uuid,
  revision_hash pg_catalog.text,
  user_category pg_catalog.text,
  event_start_on pg_catalog.date,
  event_end_on pg_catalog.date,
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
  v_category pg_catalog.text := pg_catalog.btrim(coalesce(p_user_category, ''));
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
  if pg_catalog.char_length(v_reviewer) not between 1 and 128 then
    raise exception 'invalid_reviewer';
  end if;
  if v_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'revision_mismatch';
  end if;
  if v_category not in ('policy', 'program', 'event', 'youth_space', 'living') then
    raise exception 'invalid_user_category';
  end if;
  if v_category = 'event' then
    if p_event_start_on is null or p_event_end_on is null
       or p_event_start_on > p_event_end_on then
      raise exception 'invalid_event_period';
    end if;
  elsif p_event_start_on is not null or p_event_end_on is not null then
    raise exception 'invalid_event_period';
  end if;

  select * into v_item
  from machimoa_review.source_items as si
  where si.id = p_source_item_id
  for update;
  if not found then
    raise exception 'source_item_not_found';
  end if;
  if v_item.revision_hash is distinct from v_hash then
    raise exception 'revision_mismatch';
  end if;
  select * into v_review
  from machimoa_review.processing_jobs as j
  where j.source_item_id = v_item.id
    and j.revision_hash = v_hash
    and j.processing_stage = 'content_review'
  for update;
  if not found or v_review.status not in ('queued', 'claimed')
     or not ('user_category_unconfirmed' = any(v_review.reason_codes)) then
    raise exception 'user_category_review_not_open';
  end if;
  select * into v_ai
  from machimoa_review.processing_jobs as j
  where j.source_item_id = v_item.id
    and j.revision_hash = v_hash
    and j.processing_stage = 'ai_enrichment'
  for update;
  if found and v_ai.status = 'claimed' and v_ai.claim_lease_until is null then
    raise exception 'ai_job_malformed_lease';
  end if;
  if found and v_ai.status = 'claimed'
     and v_ai.claim_lease_until is not null
     and v_ai.claim_lease_until > v_now then
    raise exception 'ai_job_claimed';
  end if;

  insert into machimoa_review.source_item_user_categories (
    source_item_id, revision_hash, user_category, reviewer
  ) values (v_item.id, v_hash, v_category, v_reviewer);
  if v_category = 'event' then
    insert into machimoa_review.source_item_event_periods (
      source_item_id, revision_hash, event_start_on, event_end_on
    ) values (v_item.id, v_hash, p_event_start_on, p_event_end_on);
  end if;
  -- A live claimed review is not rewritten by sync_source_item_evaluation_jobs.
  -- Record the next required reason while the review row is locked.
  v_reasons := pg_catalog.array_remove(
    pg_catalog.array_remove(
      pg_catalog.array_remove(
        coalesce(v_review.reason_codes, '{}'::pg_catalog.text[]),
        'user_category_unconfirmed'
      ),
      'application_deadline_unknown'
    ),
    'event_period_unknown'
  );
  if v_category in ('policy', 'program') and not exists (
    select 1 from machimoa_review.source_item_application_deadlines as dl
    where dl.source_item_id = v_item.id and dl.revision_hash = v_hash
  ) then
    v_reasons := pg_catalog.array_append(v_reasons, 'application_deadline_unknown');
  end if;
  update machimoa_review.processing_jobs as j
  set reason_codes = v_reasons
  where j.id = v_review.id;

  select * into v_pt
  from machimoa_review.source_item_product_types as pt
  where pt.source_item_id = v_item.id and pt.revision_hash = v_hash;
  if found and machimoa_review.gate_facts_row_is_complete_v1(
    v_pt.product_type, v_pt.gate_facts, v_pt.assessment_schema_version,
    v_pt.evaluated_profile, v_pt.evaluated_at, 'capital_v1'
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
    v_reasons := pg_catalog.array_remove(v_reasons, 'event_period_unknown');
  end if;
  v_disposition := machimoa_review.apply_source_item_evaluation(
    v_item.id, v_hash, v_eval_type, v_reasons, v_eval_facts
  );
  select j.id, j.status into v_review_id, v_review_status
  from machimoa_review.processing_jobs as j
  where j.source_item_id = v_item.id
    and j.revision_hash = v_hash
    and j.processing_stage = 'content_review';
  return query select v_item.id, v_hash, v_category,
    p_event_start_on, p_event_end_on, v_disposition,
    v_review_id, v_review_status;
end
$function$;

create function public.resolve_source_item_user_category(
  p_source_item_id pg_catalog.uuid,
  p_revision_hash pg_catalog.text,
  p_user_category pg_catalog.text,
  p_event_start_on pg_catalog.date,
  p_event_end_on pg_catalog.date,
  p_reviewer pg_catalog.text
)
returns table (
  source_item_id pg_catalog.uuid,
  revision_hash pg_catalog.text,
  user_category pg_catalog.text,
  event_start_on pg_catalog.date,
  event_end_on pg_catalog.date,
  disposition pg_catalog.text,
  review_job_id pg_catalog.uuid,
  review_job_status pg_catalog.text
)
language plpgsql
security definer
set search_path = ''
as $function$
begin
  return query select * from machimoa_review.resolve_source_item_user_category(
    p_source_item_id, p_revision_hash, p_user_category,
    p_event_start_on, p_event_end_on, p_reviewer
  );
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
  v_manual_closed pg_catalog.bool := false;
  v_evidence_closed pg_catalog.bool := false;
  v_user_category pg_catalog.text;
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

  v_manual_closed := exists (
    select 1
    from machimoa_review.ingest_review_decisions as d
    where d.source_item_id = v_item.id
      and d.revision_hash is not distinct from v_hash
      and d.review_type in ('content', 'product_type')
      and d.decision = 'reject'
      and 'manual_non_target' = any(d.reason_codes)
  );
  v_evidence_closed := exists (
    select 1
    from machimoa_review.ingest_review_decisions as d
    where d.source_item_id = v_item.id
      and d.revision_hash is not distinct from v_hash
      and d.review_type = 'content'
      and d.decision = 'reject'
      and 'insufficient_evidence' = any(d.reason_codes)
  );
  v_closed := v_manual_closed or v_evidence_closed;
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
      case
        when v_manual_closed then array['manual_non_target']::pg_catalog.text[]
        else array['insufficient_evidence']::pg_catalog.text[]
      end
    );
    return 'non_target';
  end if;

  if v_eval.disposition is distinct from 'non_target' then
    select cat.user_category into v_user_category
    from machimoa_review.source_item_user_categories as cat
    where cat.source_item_id = v_item.id
      and cat.revision_hash = v_hash;
    if not found then
      v_eval.jobs := machimoa_review.append_content_review_reason(
        v_eval.jobs, 'user_category_unconfirmed'
      );
    elsif v_user_category in ('policy', 'program')
       and not exists (
         select 1 from machimoa_review.source_item_application_deadlines as dl
         where dl.source_item_id = v_item.id and dl.revision_hash = v_hash
       ) then
      v_eval.jobs := machimoa_review.append_content_review_reason(
        v_eval.jobs, 'application_deadline_unknown'
      );
    elsif v_user_category = 'event'
       and not exists (
         select 1 from machimoa_review.source_item_event_periods as ep
         where ep.source_item_id = v_item.id and ep.revision_hash = v_hash
       ) then
      v_eval.jobs := machimoa_review.append_content_review_reason(
        v_eval.jobs, 'event_period_unknown'
      );
    end if;
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
    )

    and machimoa_review.category_period_ready(v_item.id, v_hash);

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
    )

    and machimoa_review.category_period_ready(v_item.id, v_hash);

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
      and machimoa_review.category_period_ready(j.source_item_id, j.revision_hash)
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

create or replace function machimoa_review.upsert_source_observations_v4(
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
  v_review machimoa_review.processing_jobs%rowtype;
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

      perform machimoa_review.record_source_item_application_deadline(
        v_locked.id,
        v_hash,
        v_item -> 'application_deadline'
      );

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
    elsif v_upsert_row.outcome = 'unchanged'
       and v_upsert_row.duplicate_in_batch is not true then
      -- Existing queued AI can predate the category requirement. Re-open only
      -- the missing fact review; do not rewrite a same-revision product decision.
      v_hash := pg_catalog.btrim(coalesce(v_item ->> 'revision_hash', ''));
      select * into v_locked
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
      if v_locked.disposition is distinct from 'non_target'
         and not machimoa_review.category_period_ready(v_locked.id, v_hash) then
        select cat.user_category into v_kind
        from machimoa_review.source_item_user_categories as cat
        where cat.source_item_id = v_locked.id and cat.revision_hash = v_hash;
        if not found then
          v_kind := 'user_category_unconfirmed';
        elsif v_kind in ('policy', 'program') and not exists (
          select 1 from machimoa_review.source_item_application_deadlines as dl
          where dl.source_item_id = v_locked.id and dl.revision_hash = v_hash
        ) then
          v_kind := 'application_deadline_unknown';
        elsif v_kind = 'event' and not exists (
          select 1 from machimoa_review.source_item_event_periods as ep
          where ep.source_item_id = v_locked.id and ep.revision_hash = v_hash
        ) then
          v_kind := 'event_period_unknown';
        else
          v_kind := null;
        end if;

        if v_kind is not null then
          select * into v_review
          from machimoa_review.processing_jobs as j
          where j.source_item_id = v_locked.id
            and j.revision_hash = v_hash
            and j.processing_stage = 'content_review'
          for update;
          if not found then
            insert into machimoa_review.processing_jobs (
              source_item_id, revision_hash, processing_stage,
              status, queued_at, available_at, reason_codes
            ) values (
              v_locked.id, v_hash, 'content_review',
              'queued', pg_catalog.now(), pg_catalog.now(),
              array[v_kind]::pg_catalog.text[]
            );
          elsif v_review.status in ('queued', 'claimed') then
            update machimoa_review.processing_jobs as j
            set reason_codes = case
              when v_kind = any(coalesce(j.reason_codes, '{}'::pg_catalog.text[]))
                then j.reason_codes
              else pg_catalog.array_append(
                coalesce(j.reason_codes, '{}'::pg_catalog.text[]), v_kind
              )
            end
            where j.id = v_review.id;
          else
            update machimoa_review.processing_jobs as j
            set status = 'queued',
                available_at = pg_catalog.now(),
                claimed_by = null,
                claim_lease_until = null,
                claimed_at = null,
                completed_at = null,
                next_retry_at = null,
                reason_codes = array[v_kind]::pg_catalog.text[]
            where j.id = v_review.id;
          end if;
          perform machimoa_review.ensure_ai_enrichment_job(
            v_locked.id, v_hash, array[v_kind]::pg_catalog.text[]
          );
        end if;
      end if;
    end if;
    return next;
  end loop;
end
$function$;

create or replace function public.enqueue_curation_candidate(
  p_source pg_catalog.text,
  p_source_item_id pg_catalog.text,
  p_source_revision_hash pg_catalog.text,
  p_slug pg_catalog.text,
  p_title_ko pg_catalog.text,
  p_content_ko pg_catalog.text,
  p_raw_payload pg_catalog.jsonb,
  p_ai_status_ko pg_catalog.text,
  p_category pg_catalog.text default null,
  p_summary_ko pg_catalog.text default null,
  p_source_url pg_catalog.text default null,
  p_ai_model pg_catalog.text default null,
  p_title_ja pg_catalog.text default null,
  p_content_ja pg_catalog.text default null,
  p_summary_ja pg_catalog.text default null,
  p_ai_status_ja pg_catalog.text default null
)
returns table (
  candidate_id pg_catalog.uuid,
  outcome pg_catalog.text,
  superseded_candidate_id pg_catalog.uuid
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_source pg_catalog.text :=
    pg_catalog.lower(pg_catalog.btrim(coalesce(p_source, '')));
  v_source_item_id pg_catalog.text :=
    pg_catalog.btrim(coalesce(p_source_item_id, ''));
  v_source_revision_hash pg_catalog.text :=
    pg_catalog.lower(
      pg_catalog.btrim(coalesce(p_source_revision_hash, ''))
    );
  v_slug pg_catalog.text :=
    pg_catalog.btrim(coalesce(p_slug, ''));
  v_title_ko pg_catalog.text :=
    pg_catalog.btrim(coalesce(p_title_ko, ''));
  v_content_ko pg_catalog.text :=
    pg_catalog.btrim(coalesce(p_content_ko, ''));
  v_raw_payload pg_catalog.jsonb := p_raw_payload;
  v_ai_status_ko pg_catalog.text :=
    pg_catalog.lower(pg_catalog.btrim(coalesce(p_ai_status_ko, '')));
  v_category pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_category, '')), '');
  v_summary_ko pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_summary_ko, '')), '');
  v_source_url pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_source_url, '')), '');
  v_ai_model pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_ai_model, '')), '');
  v_title_ja pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_title_ja, '')), '');
  v_content_ja pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_content_ja, '')), '');
  v_summary_ja pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_summary_ja, '')), '');
  v_ai_status_ja pg_catalog.text :=
    nullif(
      pg_catalog.lower(pg_catalog.btrim(coalesce(p_ai_status_ja, ''))),
      ''
    );
  v_latest_id pg_catalog.uuid;
  v_latest_hash pg_catalog.text;
  v_new_id pg_catalog.uuid;
  v_superseded_id pg_catalog.uuid;
  v_now pg_catalog.timestamptz;
  v_deadline_kind pg_catalog.text;
  v_deadline_on pg_catalog.date;
  v_user_category pg_catalog.text;
  v_event_start_on pg_catalog.date;
  v_event_end_on pg_catalog.date;
begin
  if v_source !~ '^[a-z][a-z0-9_]{1,31}$' then
    raise exception 'source must match ^[a-z][a-z0-9_]{1,31}$';
  end if;

  if pg_catalog.char_length(v_source_item_id) not between 1 and 128 then
    raise exception 'source_item_id length must be between 1 and 128';
  end if;

  if v_source_revision_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'source_revision_hash must be 64 lowercase hex characters';
  end if;

  if pg_catalog.char_length(v_slug) not between 1 and 128 then
    raise exception 'slug length must be between 1 and 128';
  end if;

  if pg_catalog.char_length(v_title_ko) not between 1 and 300 then
    raise exception 'title_ko length must be between 1 and 300';
  end if;

  if pg_catalog.char_length(v_content_ko) not between 1 and 200000 then
    raise exception 'content_ko length must be between 1 and 200000';
  end if;

  if v_category is not null
     and pg_catalog.char_length(v_category) > 100 then
    raise exception 'category length must not exceed 100';
  end if;

  if v_summary_ko is not null
     and pg_catalog.char_length(v_summary_ko) > 1000 then
    raise exception 'summary_ko length must not exceed 1000';
  end if;

  if v_title_ja is not null
     and pg_catalog.char_length(v_title_ja) not between 1 and 300 then
    raise exception 'title_ja length must be between 1 and 300';
  end if;

  if v_content_ja is not null
     and pg_catalog.char_length(v_content_ja) not between 1 and 200000 then
    raise exception 'content_ja length must be between 1 and 200000';
  end if;

  if v_summary_ja is not null
     and pg_catalog.char_length(v_summary_ja) > 1000 then
    raise exception 'summary_ja length must not exceed 1000';
  end if;

  if v_ai_model is not null
     and pg_catalog.char_length(v_ai_model) > 100 then
    raise exception 'ai_model length must not exceed 100';
  end if;

  if v_ai_status_ko not in (
    'success',
    'fallback_raw',
    'empty_response',
    'skipped_no_key',
    'error'
  ) then
    raise exception 'invalid ai_status_ko: %', v_ai_status_ko;
  end if;

  if v_ai_status_ja is not null
     and v_ai_status_ja not in (
       'success',
       'empty_response',
       'skipped_no_key',
       'error',
       'parse_error'
     ) then
    raise exception 'invalid ai_status_ja: %', v_ai_status_ja;
  end if;

  if v_source_url is not null
     and (
       v_source_url !~ '^https?://'
       or pg_catalog.char_length(v_source_url) > 2048
     ) then
    raise exception 'source_url must be an HTTP(S) URL up to 2048 characters';
  end if;

  if v_raw_payload is null
     or pg_catalog.jsonb_typeof(v_raw_payload) <> 'object' then
    raise exception 'raw_payload must be a JSON object';
  end if;

  if pg_catalog.octet_length(v_raw_payload::pg_catalog.text) > 65536 then
    raise exception 'raw_payload must not exceed 65536 bytes';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      v_source || ':' || v_source_item_id,
      0::pg_catalog.int8
    )
  );

  select c.id, c.source_revision_hash
    into v_latest_id, v_latest_hash
  from machimoa_review.curation_candidates as c
  where c.source = v_source
    and c.source_item_id = v_source_item_id
  order by c.revision_seq desc
  limit 1;

  if found and v_latest_hash = v_source_revision_hash then
    return query
    select
      v_latest_id,
      'duplicate'::pg_catalog.text,
      null::pg_catalog.uuid;
    return;
  end if;

  select cat.user_category, dl.application_deadline_kind,
         dl.application_deadline_on, ep.event_start_on, ep.event_end_on
    into v_user_category, v_deadline_kind, v_deadline_on,
         v_event_start_on, v_event_end_on
  from machimoa_review.source_items as si
  join machimoa_review.source_item_user_categories as cat
    on cat.source_item_id = si.id
   and cat.revision_hash = v_source_revision_hash
  left join machimoa_review.source_item_application_deadlines as dl
    on dl.source_item_id = si.id
   and dl.revision_hash = v_source_revision_hash
  left join machimoa_review.source_item_event_periods as ep
    on ep.source_item_id = si.id
   and ep.revision_hash = v_source_revision_hash
  where si.source_id = machimoa_review.canonical_source_id(v_source)
    and si.external_key = v_source_item_id
    and si.revision_hash = v_source_revision_hash;
  if not found then
    raise exception 'user_category_required';
  end if;
  if v_user_category in ('policy', 'program') then
    if v_deadline_kind is null then
      raise exception 'application_deadline_required';
    end if;
    v_event_start_on := null;
    v_event_end_on := null;
  elsif v_user_category = 'event' then
    if v_event_start_on is null or v_event_end_on is null then
      raise exception 'event_period_required';
    end if;
    v_deadline_kind := null;
    v_deadline_on := null;
  else
    v_deadline_kind := null;
    v_deadline_on := null;
    v_event_start_on := null;
    v_event_end_on := null;
  end if;

  v_new_id := pg_catalog.gen_random_uuid();
  v_now := pg_catalog.now();

  update machimoa_review.curation_candidates as c
  set
    review_status = 'superseded',
    superseded_at = v_now,
    superseded_by_candidate_id = v_new_id
  where c.source = v_source
    and c.source_item_id = v_source_item_id
    and c.review_status = 'pending'
  returning c.id into v_superseded_id;

  insert into machimoa_review.curation_candidates (
    id,
    source,
    source_item_id,
    source_revision_hash,
    slug,
    category,
    title,
    summary,
    content,
    source_url,
    raw_payload,
    ai_status,
    ai_model,
    title_ko,
    summary_ko,
    content_ko,
    ai_status_ko,
    title_ja,
    summary_ja,
    content_ja,
    ai_status_ja,
    application_deadline_kind,
    application_deadline_on,
    user_category,
    event_start_on,
    event_end_on
  )
  values (
    v_new_id,
    v_source,
    v_source_item_id,
    v_source_revision_hash,
    v_slug,
    v_category,
    v_title_ko,
    v_summary_ko,
    v_content_ko,
    v_source_url,
    v_raw_payload,
    v_ai_status_ko,
    v_ai_model,
    v_title_ko,
    v_summary_ko,
    v_content_ko,
    v_ai_status_ko,
    v_title_ja,
    v_summary_ja,
    v_content_ja,
    v_ai_status_ja,
    v_deadline_kind,
    v_deadline_on,
    v_user_category,
    v_event_start_on,
    v_event_end_on
  );

  return query
  select
    v_new_id,
    'inserted'::pg_catalog.text,
    v_superseded_id;
end
$function$;

create or replace function machimoa_review.publish_curation_candidate(
  p_candidate_id pg_catalog.uuid,
  p_reviewed_by pg_catalog.text,
  p_review_notes pg_catalog.text default null,
  p_allow_overwrite pg_catalog.bool default false
)
returns pg_catalog.uuid
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_candidate_id pg_catalog.uuid := p_candidate_id;
  v_reviewed_by pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_reviewed_by, '')), '');
  v_review_notes pg_catalog.text :=
    nullif(pg_catalog.btrim(coalesce(p_review_notes, '')), '');
  v_allow_overwrite pg_catalog.bool := coalesce(p_allow_overwrite, false);
  v_review_status pg_catalog.text;
  v_source pg_catalog.text;
  v_source_item_id pg_catalog.text;
  v_source_revision_hash pg_catalog.text;
  v_slug pg_catalog.text;
  v_category pg_catalog.text;
  v_title_ko pg_catalog.text;
  v_title_ja pg_catalog.text;
  v_summary_ko pg_catalog.text;
  v_summary_ja pg_catalog.text;
  v_content_ko pg_catalog.text;
  v_content_ja pg_catalog.text;
  v_source_url pg_catalog.text;
  v_deadline_kind pg_catalog.text;
  v_deadline_on pg_catalog.date;
  v_user_category pg_catalog.text;
  v_event_start_on pg_catalog.date;
  v_event_end_on pg_catalog.date;
  v_source_match_id pg_catalog.uuid;
  v_slug_match_id pg_catalog.uuid;
  v_slug_match_source pg_catalog.text;
  v_curation_id pg_catalog.uuid;
  v_target record;
  v_now pg_catalog.timestamptz := pg_catalog.now();
begin
  if v_candidate_id is null then
    raise exception 'candidate_id is required';
  end if;

  if v_reviewed_by is null
     or pg_catalog.char_length(v_reviewed_by) > 128 then
    raise exception
      'reviewed_by must contain 1 to 128 non-whitespace characters';
  end if;

  if v_review_notes is not null
     and pg_catalog.char_length(v_review_notes) > 4000 then
    raise exception 'review_notes length must not exceed 4000';
  end if;

  select
    c.review_status,
    pg_catalog.lower(pg_catalog.btrim(c.source)),
    pg_catalog.btrim(c.source_item_id),
    pg_catalog.btrim(c.source_revision_hash),
    pg_catalog.btrim(c.slug),
    nullif(pg_catalog.btrim(coalesce(c.category, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.title_ko, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.title_ja, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.summary_ko, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.summary_ja, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.content_ko, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.content_ja, '')), ''),
    nullif(pg_catalog.btrim(coalesce(c.source_url, '')), ''),
    c.application_deadline_kind,
    c.application_deadline_on,
    c.user_category,
    c.event_start_on,
    c.event_end_on
  into
    v_review_status,
    v_source,
    v_source_item_id,
    v_source_revision_hash,
    v_slug,
    v_category,
    v_title_ko,
    v_title_ja,
    v_summary_ko,
    v_summary_ja,
    v_content_ko,
    v_content_ja,
    v_source_url,
    v_deadline_kind,
    v_deadline_on,
    v_user_category,
    v_event_start_on,
    v_event_end_on
  from machimoa_review.curation_candidates as c
  where c.id = v_candidate_id
  for update;

  if not found then
    raise exception 'curation candidate % does not exist', v_candidate_id;
  end if;

  if v_review_status <> 'pending' then
    raise exception
      'curation candidate % is %, expected pending',
      v_candidate_id,
      v_review_status;
  end if;

  perform machimoa_review.assert_publish_allowed(v_source);

  if v_source !~ '^[a-z][a-z0-9_]{1,31}$' then
    raise exception 'candidate source has an invalid format';
  end if;

  if pg_catalog.char_length(v_source_item_id) not between 1 and 128 then
    raise exception 'candidate source_item_id is empty or too long';
  end if;

  if pg_catalog.char_length(v_slug) not between 1 and 128 then
    raise exception 'candidate slug is empty or too long';
  end if;

  if v_category is null
     or pg_catalog.char_length(v_category) > 100 then
    raise exception 'candidate category is required and must not exceed 100';
  end if;

  if v_title_ko is null
     or pg_catalog.char_length(v_title_ko) not between 1 and 300 then
    raise exception 'candidate title_ko is empty or too long';
  end if;

  if v_title_ja is null
     or pg_catalog.char_length(v_title_ja) not between 1 and 300 then
    raise exception 'candidate title_ja is empty or too long';
  end if;

  if v_summary_ko is null
     or pg_catalog.char_length(v_summary_ko) not between 1 and 1000 then
    raise exception
      'candidate summary_ko is required and must not exceed 1000';
  end if;

  if v_summary_ja is null
     or pg_catalog.char_length(v_summary_ja) not between 1 and 1000 then
    raise exception
      'candidate summary_ja is required and must not exceed 1000';
  end if;

  if v_content_ko is null
     or pg_catalog.char_length(v_content_ko) not between 1 and 200000 then
    raise exception 'candidate content_ko is empty or too long';
  end if;

  if v_content_ja is null
     or pg_catalog.char_length(v_content_ja) not between 1 and 200000 then
    raise exception 'candidate content_ja is empty or too long';
  end if;

  if v_source_url is null
     or v_source_url !~ '^https?://'
     or pg_catalog.char_length(v_source_url) > 2048 then
    raise exception
      'candidate source_url is required and must be an HTTP(S) URL';
  end if;

  if v_user_category not in ('policy', 'program', 'event', 'youth_space', 'living')
     or v_user_category is null then
    raise exception 'user_category_required';
  end if;
  if v_user_category in ('policy', 'program') then
    if v_deadline_kind is null
       or v_deadline_kind not in ('fixed', 'none', 'closed')
       or (v_deadline_kind = 'fixed' and v_deadline_on is null)
       or (v_deadline_kind in ('none', 'closed') and v_deadline_on is not null)
       or v_event_start_on is not null or v_event_end_on is not null then
      raise exception 'application_deadline_required';
    end if;
  elsif v_user_category = 'event' then
    if v_deadline_kind is not null or v_deadline_on is not null
       or v_event_start_on is null or v_event_end_on is null
       or v_event_start_on > v_event_end_on then
      raise exception 'event_period_required';
    end if;
  elsif v_deadline_kind is not null or v_deadline_on is not null
     or v_event_start_on is not null or v_event_end_on is not null then
    raise exception 'invalid_user_category_period';
  end if;

  for v_target in
    select
      c.id,
      c.source,
      c.source_item_id,
      c.slug
    from public.curations as c
    where (
      c.source = v_source
      and c.source_item_id = v_source_item_id
    )
    or c.slug = v_slug
    order by c.id
    for update
  loop
    if v_target.source = v_source
       and v_target.source_item_id = v_source_item_id then
      v_source_match_id := v_target.id;
    end if;

    if v_target.slug = v_slug then
      v_slug_match_id := v_target.id;
      v_slug_match_source := v_target.source;
    end if;
  end loop;

  if v_source_match_id is null and v_slug_match_id is null then
    insert into public.curations (
      slug,
      category,
      title,
      summary,
      content,
      title_ko,
      title_ja,
      summary_ko,
      summary_ja,
      content_ko,
      content_ja,
      source,
      source_item_id,
      source_url,
      application_deadline_kind,
      application_deadline_on,
      user_category,
      event_start_on,
      event_end_on,
      updated_at,
      is_published
    )
    values (
      v_slug,
      v_category,
      v_title_ko,
      v_summary_ko,
      v_content_ko,
      v_title_ko,
      v_title_ja,
      v_summary_ko,
      v_summary_ja,
      v_content_ko,
      v_content_ja,
      v_source,
      v_source_item_id,
      v_source_url,
      v_deadline_kind,
      v_deadline_on,
      v_user_category,
      v_event_start_on,
      v_event_end_on,
      v_now,
      true
    )
    returning id into v_curation_id;
  elsif v_source_match_id is not null
        and (
          v_slug_match_id is null
          or v_slug_match_id = v_source_match_id
        ) then
    update public.curations as c
    set
      slug = v_slug,
      category = v_category,
      title = v_title_ko,
      summary = v_summary_ko,
      content = v_content_ko,
      title_ko = v_title_ko,
      title_ja = v_title_ja,
      summary_ko = v_summary_ko,
      summary_ja = v_summary_ja,
      content_ko = v_content_ko,
      content_ja = v_content_ja,
      source = v_source,
      source_item_id = v_source_item_id,
      source_url = v_source_url,
      application_deadline_kind = v_deadline_kind,
      application_deadline_on = v_deadline_on,
      user_category = v_user_category,
      event_start_on = v_event_start_on,
      event_end_on = v_event_end_on,
      updated_at = v_now,
      is_published = true
    where c.id = v_source_match_id
    returning c.id into v_curation_id;
  elsif v_source_match_id is null and v_slug_match_id is not null then
    if v_slug_match_source is not null then
      raise exception
        'slug % belongs to a different sourced curation',
        v_slug;
    end if;

    if not v_allow_overwrite then
      raise exception
        'slug % belongs to a legacy curation; explicit overwrite approval is required',
        v_slug;
    end if;

    update public.curations as c
    set
      slug = v_slug,
      category = v_category,
      title = v_title_ko,
      summary = v_summary_ko,
      content = v_content_ko,
      title_ko = v_title_ko,
      title_ja = v_title_ja,
      summary_ko = v_summary_ko,
      summary_ja = v_summary_ja,
      content_ko = v_content_ko,
      content_ja = v_content_ja,
      source = v_source,
      source_item_id = v_source_item_id,
      source_url = v_source_url,
      application_deadline_kind = v_deadline_kind,
      application_deadline_on = v_deadline_on,
      user_category = v_user_category,
      event_start_on = v_event_start_on,
      event_end_on = v_event_end_on,
      updated_at = v_now,
      is_published = true
    where c.id = v_slug_match_id
    returning c.id into v_curation_id;
  else
    raise exception
      'candidate source and slug resolve to different public curations';
  end if;

  update machimoa_review.curation_candidates as c
  set
    review_status = 'published',
    review_notes = v_review_notes,
    reviewed_at = v_now,
    reviewed_by = v_reviewed_by,
    published_at = v_now,
    published_curation_id = v_curation_id
  where c.id = v_candidate_id;

  perform machimoa_review.write_publication_lineage(
    v_source,
    v_source_item_id,
    v_source_revision_hash,
    v_candidate_id,
    v_curation_id,
    v_slug,
    v_reviewed_by
  );

  return v_curation_id;
end
$function$;

alter function machimoa_review.category_period_ready(pg_catalog.uuid, pg_catalog.text)
  owner to postgres;
alter function machimoa_review.append_content_review_reason(pg_catalog.jsonb, pg_catalog.text)
  owner to postgres;
alter function machimoa_review.resolve_source_item_user_category(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.date,
  pg_catalog.date, pg_catalog.text
) owner to postgres;
alter function public.resolve_source_item_user_category(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.date,
  pg_catalog.date, pg_catalog.text
) owner to postgres;
revoke all privileges on function machimoa_review.category_period_ready(
  pg_catalog.uuid, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.append_content_review_reason(
  pg_catalog.jsonb, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function machimoa_review.resolve_source_item_user_category(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.date,
  pg_catalog.date, pg_catalog.text
) from public, anon, authenticated, service_role;
revoke all privileges on function public.resolve_source_item_user_category(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.date,
  pg_catalog.date, pg_catalog.text
) from public, anon, authenticated, service_role;
grant execute on function public.resolve_source_item_user_category(
  pg_catalog.uuid, pg_catalog.text, pg_catalog.text, pg_catalog.date,
  pg_catalog.date, pg_catalog.text
) to service_role;
notify pgrst, 'reload schema';
commit;
