-- Local-only draft until explicit operating approval. No backfill or record deletion.
begin;
do $$begin if current_user<>'postgres' then raise exception 'postgres owner required';end if;end$$;
alter table machimoa_review.ingest_review_decisions add column revoked_at timestamptz;
alter table machimoa_review.admin_review_events drop constraint admin_review_events_action_check;
alter table machimoa_review.admin_review_events add constraint admin_review_events_action_check
 check(action in ('save_facts','exclude','save_candidate','publish','reject','restore','confirm_restored'));
create table machimoa_review.admin_exclusion_episodes(
 id uuid primary key default gen_random_uuid(),source_item_id uuid not null,revision_hash text not null check(revision_hash~'^[a-f0-9]{64}$'),
 source_name text not null,title text not null,reason_code text not null check(reason_code in ('service_not_suitable','region_not_suitable','custom')),
 note text not null check(char_length(note) between 1 and 4000),actor uuid not null,
 excluded_at timestamptz not null,expires_at timestamptz not null,restored_at timestamptz,restored_by uuid,review_completed_at timestamptz,
 prior_jobs jsonb not null,prior_decisions jsonb not null,decision_ids uuid[] not null default '{}',
 check(expires_at=excluded_at+interval '72 hours'),check((restored_at is null)=(restored_by is null)),
 check(review_completed_at is null or restored_at is not null)
);
create unique index admin_exclusion_active_idx on machimoa_review.admin_exclusion_episodes(source_item_id,revision_hash) where restored_at is null;
create index admin_exclusion_pending_idx on machimoa_review.admin_exclusion_episodes(source_item_id,revision_hash) where restored_at is not null and review_completed_at is null;
create index admin_exclusion_expiry_idx on machimoa_review.admin_exclusion_episodes(expires_at,excluded_at desc) where restored_at is null;
create table machimoa_review.admin_exclusion_requests(
 request_id uuid primary key,actor uuid not null,input jsonb not null,episode_id uuid not null references machimoa_review.admin_exclusion_episodes(id),
 response jsonb not null,created_at timestamptz not null default clock_timestamp()
);
alter table machimoa_review.admin_exclusion_episodes enable row level security;
alter table machimoa_review.admin_exclusion_requests enable row level security;
revoke all on machimoa_review.admin_exclusion_episodes,machimoa_review.admin_exclusion_requests from public,anon,authenticated,service_role;

create function machimoa_review.admin_trash_pending(p_id uuid,p_revision text) returns boolean
language sql stable security definer set search_path='' as $$
 select exists(select 1 from machimoa_review.admin_exclusion_episodes e where e.source_item_id=p_id and e.revision_hash=p_revision
 and e.restored_at is not null and e.review_completed_at is null)
$$;
create function machimoa_review.admin_trash_add_confirmation(p_jobs jsonb) returns jsonb
language sql immutable security definer set search_path='' as $$
 select coalesce((select jsonb_agg(case when j->>'stage'='content_review' then
   j||jsonb_build_object('reason_codes',coalesce(j->'reason_codes','[]'::jsonb)||jsonb_build_array('restored_review_pending')) else j end)
   from jsonb_array_elements(coalesce(p_jobs,'[]'::jsonb))j),'[]'::jsonb)
   ||case when exists(select 1 from jsonb_array_elements(coalesce(p_jobs,'[]'::jsonb))j where j->>'stage'='content_review') then '[]'::jsonb
      else jsonb_build_array(jsonb_build_object('stage','content_review','reason_codes',jsonb_build_array('restored_review_pending'))) end
$$;

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
      and d.decision = 'reject' and d.revoked_at is null
      and 'manual_non_target' = any(d.reason_codes)
  );
  v_evidence_closed := exists (
    select 1
    from machimoa_review.ingest_review_decisions as d
    where d.source_item_id = v_item.id
      and d.revision_hash is not distinct from v_hash
      and d.review_type = 'content'
      and d.decision = 'reject' and d.revoked_at is null
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

  if machimoa_review.admin_trash_pending(v_item.id,v_hash) then
    v_eval.disposition:='observe_only';
    v_eval.jobs:=machimoa_review.admin_trash_add_confirmation(v_eval.jobs);
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

  if machimoa_review.admin_trash_pending(v_item.id,v_hash) then return;end if;

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
        and d.decision = 'reject' and d.revoked_at is null
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

create or replace function machimoa_review.program_refresh(p_id uuid,p_now timestamptz default clock_timestamp()) returns void
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype;
 v_result jsonb; stage text; reason text[]; allowed boolean;
begin
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation' for update;
 if not found then raise exception using errcode='PT404',message='program_not_found';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash for update;
 if not found then raise exception using errcode='PT404',message='program_facts_not_found';end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed') then
   raise exception using errcode='PT409',message='program_processing_active';end if;
 select enabled and permission_status in ('approved_noncommercial','approved_commercial') into allowed
 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 v_result:=case when f.manual_excluded then jsonb_build_object('decision','out_of_scope','disposition','non_target','reasons',jsonb_build_array('manual_service_scope_excluded'))
 else machimoa_review.program_evaluate(f.facts,p_now) end;
 if not f.manual_excluded and machimoa_review.admin_trash_pending(p_id,s.revision_hash) then
   v_result:=v_result||jsonb_build_object('decision','review_required','disposition','observe_only',
     'reasons',coalesce(v_result->'reasons','[]'::jsonb)||jsonb_build_array('restored_review_pending'));
 end if;
 update machimoa_review.source_item_program_facts set result=v_result where source_item_id=p_id and revision_hash=s.revision_hash;
 update machimoa_review.source_items set disposition=v_result->>'disposition' where id=p_id;
 -- Old revisions cannot remain queued. Completed jobs are never resurrected.
 update machimoa_review.processing_jobs set status='cancelled',completed_at=clock_timestamp()
 where source_item_id=p_id and revision_hash<>s.revision_hash and status in ('queued','failed');
 stage:=case when v_result->>'decision'='review_required' then 'content_review'
             when v_result->>'decision'='in_scope' and allowed then 'ai_enrichment' else null end;
 update machimoa_review.processing_jobs set status=case when processing_stage='content_review' and v_result->>'decision'='in_scope' then 'completed' else 'cancelled' end,
 completed_at=clock_timestamp(),reason_codes=case when processing_stage='content_review' then '{}'::text[] else reason_codes end
 where source_item_id=p_id and revision_hash=s.revision_hash and status in ('queued','failed') and processing_stage is distinct from stage;
 if stage is not null then
   reason:=case when stage='content_review' then array(select jsonb_array_elements_text(v_result->'reasons')) else '{}'::text[] end;
   insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
   values(p_id,s.revision_hash,stage,'queued',clock_timestamp(),clock_timestamp(),reason)
   on conflict(source_item_id,revision_hash,processing_stage) do update
   set reason_codes=excluded.reason_codes,status='queued',completed_at=null
   where machimoa_review.processing_jobs.status in ('queued','cancelled','failed');
 end if;
end $$;

create or replace function machimoa_review.admin_review_item(p_kind text, p_id uuid) returns jsonb
language plpgsql stable security definer set search_path = '' as $fn$
declare
  v jsonb := machimoa_review.admin_review_snapshot(p_kind,p_id);
  s jsonb := v->'source'; p jsonb := v->'product'; c jsonb := v->'candidate';
  g jsonb := coalesce(p->'gate_facts','{}'::jsonb); reasons jsonb; stages text[];
  fields text[] := '{}'; history jsonb; base jsonb; is_open boolean; missing_type boolean; can_confirm_type boolean;
begin
  select coalesce(pg_catalog.jsonb_agg(distinct r.reason), '[]'::jsonb) into reasons
  from pg_catalog.jsonb_array_elements(v->'jobs') j,
       lateral pg_catalog.jsonb_array_elements_text(j->'reason_codes') r(reason)
  where j->>'processing_stage' <> 'ai_enrichment' and j->>'status' in ('queued','claimed');
  select coalesce(pg_catalog.array_agg(j->>'processing_stage'), '{}'::text[]) into stages
  from pg_catalog.jsonb_array_elements(v->'jobs') j
  where j->>'processing_stage' <> 'ai_enrichment' and j->>'status' in ('queued','claimed');
  is_open := pg_catalog.cardinality(stages)>0 and s->>'disposition'<>'non_target';
  missing_type := p is null or p = 'null'::jsonb;
  -- Since Sep 23, classification uncertainty is queued in content_review.
  -- Keep the legacy product_type_review path without permitting type overrides.
  can_confirm_type := missing_type and ('product_type_review'=any(stages) or
    ('content_review'=any(stages) and reasons ?| array['policy_lifecycle_uncertain','policy_lifecycle_conflict','end_date_absent_not_reference','product_type_unknown','product_type_unconfirmed']));
  if is_open then
    if can_confirm_type then fields := fields||array['productType']; end if;
    if can_confirm_type or
       (not missing_type and (machimoa_review.gate_facts_row_is_complete_v1(p->>'product_type',p->'gate_facts',
         p->>'assessment_schema_version',p->>'evaluated_profile',(p->>'evaluated_at')::timestamptz,'capital_v1') is not true
         or reasons ?| array['region_scope_unknown','relevance_unconfirmed'])) then
      fields := fields||array['delivery'];
      if missing_type or p->>'product_type'<>'living_guide' then fields := fields||array['scope','regions','evidence']; end if;
      if missing_type or p->>'product_type'='policy_reference' then fields := fields||array['foreignEligibility']; end if;
    end if;
    if reasons ? 'user_category_unconfirmed' and (v->>'category') is null then
      fields := fields||array['category','eventStart','eventEnd'];
    end if;
    if reasons ? 'application_deadline_unknown' then fields := fields||array['deadlineKind','deadlineOn']; end if;
  end if;
  -- Reuse original decisions and final candidate review metadata, supplement only missing edits.
  select coalesce(pg_catalog.jsonb_agg(h.entry order by h.at desc, h.tie desc),'[]'::jsonb) into history from (
    select e.occurred_at at, e.id::text tie, pg_catalog.jsonb_build_object('action',e.action,'actor',e.actor,'at',e.occurred_at,'note',e.note) entry
    from machimoa_review.admin_review_events e where e.source_item_id=(s->>'id')::uuid
      and e.revision_hash=s->>'revision_hash' and (p_kind='facts' and e.candidate_id is null or p_kind='candidates' and e.candidate_id=p_id)
    union all
    select d.reviewed_at, d.id::text, pg_catalog.jsonb_build_object('action',case when d.decision='reject' then 'exclude' else 'save_facts' end,'actor',d.reviewer,'at',d.reviewed_at,'note',coalesce(d.memo,''))
    from machimoa_review.ingest_review_decisions d where p_kind='facts' and d.source_item_id=(s->>'id')::uuid and d.revision_hash=s->>'revision_hash'
      and not exists(select 1 from machimoa_review.admin_review_events e where e.source_item_id=d.source_item_id and e.revision_hash=d.revision_hash and e.action='exclude' and e.actor::text=d.reviewer)
    union all
    select (c->>'reviewed_at')::timestamptz, 'legacy', pg_catalog.jsonb_build_object('action',case when c->>'review_status'='published' then 'publish' else 'reject' end,'actor',c->>'reviewed_by','at',c->>'reviewed_at','note',coalesce(c->>'review_notes',''))
    where p_kind='candidates' and c->>'reviewed_at' is not null and c->>'review_status' in ('published','rejected')
      and not exists(select 1 from machimoa_review.admin_review_events e where e.candidate_id=p_id and e.action in ('publish','reject'))
    order by 1 desc limit 100
  ) h;
  base := pg_catalog.jsonb_build_object('kind',p_kind,'id',p_id,'revision',s->>'revision_hash',
    'version',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(v::text,'UTF8')),'hex'),
    'source',pg_catalog.jsonb_build_object('name',s->>'source_id',
      'title',coalesce(s->'normalized_payload'->>'pstTtl',s->'normalized_payload'->>'plcyNm',s->'min_fields'->>'title','제목 확인 필요'),
      'url',coalesce(s->'normalized_payload'->>'source_url',s->'min_fields'->>'source_url',''),
      'body',pg_catalog.left(coalesce(s->'normalized_payload'->>'plain_text',''),200000)), 'history',history);
  if p_kind='facts' then return base||pg_catalog.jsonb_build_object(
    'status',case when s->>'disposition'='non_target' then 'excluded' when is_open then 'open' else 'resolved' end,
    'reasons',reasons,'editableFields',pg_catalog.to_jsonb(fields),
    'excludeAllowed',is_open and stages && array['content_review','product_type_review'],
    'restoredReviewPending',machimoa_review.admin_trash_pending(p_id,s->>'revision_hash'),
    'aiStatus',coalesce((select j->>'status' from pg_catalog.jsonb_array_elements(v->'jobs') j where j->>'processing_stage'='ai_enrichment'),'blocked'),
    'facts',pg_catalog.jsonb_build_object('productType',coalesce(p->>'product_type',''),'category',coalesce(v->'category'->>'user_category',''),
      'scope',coalesce(g->>'eligibility_scope','unknown'),'regions',coalesce(g->'eligibility_region_codes','[]'::jsonb),
      'evidence',coalesce(g->>'eligibility_region_evidence',''),'foreignEligibility',coalesce(g->>'foreign_resident_eligibility','unknown'),
      'delivery',coalesce(g->>'delivery_mode','unknown'),'deadlineKind',coalesce(v->'deadline'->>'application_deadline_kind',''),
      'deadlineOn',coalesce(v->'deadline'->>'application_deadline_on',''),'eventStart',coalesce(v->'period'->>'event_start_on',''),
      'eventEnd',coalesce(v->'period'->>'event_end_on',''))); end if;
  return base||case when s->>'source_id'='seoul_reservation' then pg_catalog.jsonb_build_object('programInfo',machimoa_review.program_candidate_info(p_id)) else '{}'::jsonb end||pg_catalog.jsonb_build_object('status',c->>'review_status','category',coalesce(c->>'user_category',''),
    'period',coalesce(c->>'event_start_on',c->>'application_deadline_on','기간 정보 없음'),
    'publishedAt',c->'published_at','publishedId',c->'published_curation_id',
    'content',pg_catalog.jsonb_build_object('titleKo',coalesce(c->>'title_ko',c->>'title',''),'titleJa',coalesce(c->>'title_ja',''),
      'summaryKo',coalesce(c->>'summary_ko',c->>'summary',''),'summaryJa',coalesce(c->>'summary_ja',''),
      'contentKo',coalesce(c->>'content_ko',c->>'content',''),'contentJa',coalesce(c->>'content_ja','')));
end $fn$;

create or replace function public.admin_program_detail(p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype;
 jobs jsonb; history jsonb; editable text[]; reasons text[]; permission jsonb;
begin
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation';
 if not found then raise exception using errcode='PT404',message='program_not_found';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash;
 if not found then raise exception using errcode='PT404',message='program_facts_not_found';end if;
 select coalesce(jsonb_agg(jsonb_build_object('stage',processing_stage,'status',status,'reasons',reason_codes) order by processing_stage),'[]') into jobs
 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=s.revision_hash;
 select jsonb_build_object('enabled',enabled,'permission',permission_status) into permission from machimoa_review.ingest_sources where source_id=s.source_id;
 reasons:=array(select jsonb_array_elements_text(f.result->'reasons'));
 select array_agg(distinct field order by field) into editable from unnest(reasons) reason cross join lateral unnest(machimoa_review.program_reason_fields(reason)) field;
 select coalesce(jsonb_agg(jsonb_build_object('action',action,'actor',actor,'at',occurred_at,'note',note,'fields',changed_fields) order by id desc),'[]') into history
 from (select * from machimoa_review.admin_review_events where source_item_id=p_id order by id desc limit 25) e;
 return jsonb_build_object('id',p_id,'revision',s.revision_hash,'version',encode(sha256(convert_to(jsonb_build_array(s.revision_hash,f.facts_version,f.result,jobs,permission)::text,'UTF8')),'hex'),
 'schema',f.schema_version,'profile',f.evaluated_profile,'factsVersion',f.facts_version,
 'source',jsonb_build_object('name',s.source_id,'title',s.normalized_payload->>'title','url',s.normalized_payload->>'source_url','body',s.normalized_payload->>'program_text'),
 'restoredReviewPending',machimoa_review.admin_trash_pending(p_id,s.revision_hash),'facts',f.facts,'observedFacts',f.observed_facts,'result',f.result,'editableFields',coalesce(to_jsonb(editable),'[]'),
 'status',case when f.manual_excluded or f.result->>'decision'='out_of_scope' then 'excluded' when f.result->>'decision'='review_required' then 'open' else 'resolved' end,
 'aiStatus',coalesce((select status from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=s.revision_hash and processing_stage='ai_enrichment'),'blocked'),
 'history',history);
end $$;

-- No public bypass to the old manual exclusion entry points. Their behavior remains reused internally.
alter function public.admin_review_exclude(uuid,text,text,text,uuid) set schema machimoa_review;
alter function machimoa_review.admin_review_exclude(uuid,text,text,text,uuid) rename to admin_review_exclude_before_trash;
revoke all on function machimoa_review.admin_review_exclude_before_trash(uuid,text,text,text,uuid) from public,anon,authenticated,service_role;
alter function public.admin_program_exclude(uuid,text,text,text,uuid) set schema machimoa_review;
alter function machimoa_review.admin_program_exclude(uuid,text,text,text,uuid) rename to admin_program_exclude_before_trash;
revoke all on function machimoa_review.admin_program_exclude_before_trash(uuid,text,text,text,uuid) from public,anon,authenticated,service_role;

create function machimoa_review.admin_trash_lock(p_id uuid,p_revision text,p_actor uuid) returns void
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;legacy text;
begin
 if p_id is null or p_actor is null or p_revision is null or p_revision!~'^[a-f0-9]{64}$' then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 select * into s from machimoa_review.source_items where id=p_id for update;
 if not found then raise sqlstate 'PT404' using message='review_not_found';end if;
 if s.revision_hash is distinct from p_revision then raise sqlstate 'PT409' using message='trash_source_changed';end if;
 select legacy_curation_source into legacy from machimoa_review.ingest_sources where source_id=s.source_id for share;
 if s.source_id='seoul_reservation' then
   perform 1 from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision for update;
 end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed' and
   (s.source_id='seoul_reservation' or (revision_hash=p_revision and processing_stage='ai_enrichment' and (claim_lease_until is null or claim_lease_until>clock_timestamp())))) then
   raise sqlstate 'PT409' using message='trash_processing_active';end if;
 if legacy is not null then
   perform pg_advisory_xact_lock(hashtextextended(legacy||':'||s.external_key,0));
   perform 1 from machimoa_review.curation_candidates where source=legacy and source_item_id=s.external_key order by id for update;
 end if;
 if exists(select 1 from machimoa_review.curation_candidates c where machimoa_review.canonical_source_id(c.source)=s.source_id
   and c.source_item_id=s.external_key and c.source_revision_hash=p_revision and c.review_status='published')
 or exists(select 1 from machimoa_review.source_publications where source_id=s.source_id and external_key=s.external_key and revision_hash=p_revision and publication_status='published') then
   raise sqlstate 'PT409' using message='trash_already_published';end if;
end $$;

create function machimoa_review.admin_trash_version(p_episode uuid) returns text
language sql stable security definer set search_path='' as $$
 select encode(sha256(convert_to(jsonb_build_array(to_jsonb(e),s.revision_hash,s.disposition,
   case when s.id is null or s.revision_hash is distinct from e.revision_hash then null when s.source_id='seoul_reservation' then public.admin_program_detail(s.id)->>'version'
        else machimoa_review.admin_review_item('facts',s.id)->>'version' end)::text,'UTF8')),'hex')
 from machimoa_review.admin_exclusion_episodes e left join machimoa_review.source_items s on s.id=e.source_item_id where e.id=p_episode
$$;

create function public.admin_review_trash(p_offset integer default 0,p_limit integer default 25) returns jsonb
language plpgsql volatile security definer set search_path='' as $$
declare rows jsonb;stamp timestamptz:=clock_timestamp();
begin
 if p_offset is null or p_offset not between 0 and 999999 or p_limit is null or p_limit not between 1 and 25 then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',q.id,'sourceItemId',q.source_item_id,'revision',q.revision_hash,'version',machimoa_review.admin_trash_version(q.id),
   'sourceName',q.source_name,'title',q.title,'reasonCode',q.reason_code,'note',q.note,'excludedAt',q.excluded_at,'expiresAt',q.expires_at,
   'canRestore',q.block_reason is null,'blockReason',q.block_reason) order by q.excluded_at desc,q.id),'[]') into rows from (
   select e.*,case when s.id is null then 'source_missing' when s.revision_hash<>e.revision_hash then 'source_changed'
     when exists(select 1 from machimoa_review.processing_jobs j where j.source_item_id=s.id and j.status='claimed' and
       (s.source_id='seoul_reservation' or (j.revision_hash=e.revision_hash and j.processing_stage='ai_enrichment' and (j.claim_lease_until is null or j.claim_lease_until>stamp)))) then 'processing_active'
     when exists(select 1 from machimoa_review.source_publications p where p.source_id=s.source_id and p.external_key=s.external_key and p.revision_hash=e.revision_hash and p.publication_status='published')
       or exists(select 1 from machimoa_review.curation_candidates c where machimoa_review.canonical_source_id(c.source)=s.source_id and c.source_item_id=s.external_key and c.source_revision_hash=e.revision_hash and c.review_status='published') then 'already_published'
     when (s.source_id='seoul_reservation' and not exists(select 1 from machimoa_review.source_item_program_facts f where f.source_item_id=s.id and f.revision_hash=e.revision_hash and f.manual_excluded))
       or (s.source_id<>'seoul_reservation' and s.disposition<>'non_target') then 'state_changed' else null end block_reason
   from machimoa_review.admin_exclusion_episodes e left join machimoa_review.source_items s on s.id=e.source_item_id
   where e.restored_at is null and e.expires_at>stamp order by e.excluded_at desc,e.id offset p_offset limit p_limit
 )q;
 return jsonb_build_object('serverNow',stamp,'items',rows);
end $$;

create function public.admin_review_exclude_reason(p_id uuid,p_revision text,p_version text,p_reason text,p_note text,p_actor uuid,p_request uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;e machimoa_review.admin_exclusion_episodes%rowtype;
 r machimoa_review.admin_exclusion_requests%rowtype;stamp timestamptz;v_memo text;before_item jsonb;result jsonb;input jsonb;jobs jsonb;decisions jsonb;
begin
 if p_request is null or p_version is null or p_version!~'^[a-f0-9]{64}$' or p_reason is null or p_reason not in ('service_not_suitable','region_not_suitable','custom') then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 perform machimoa_review.admin_trash_lock(p_id,p_revision,p_actor);
 select * into s from machimoa_review.source_items where id=p_id;
 v_memo:=case p_reason when 'service_not_suitable' then '서비스에 적합하지 않음' when 'region_not_suitable' then '대상 지역이 아님' else btrim(p_note) end;
 if v_memo is null or char_length(v_memo) not between 1 and (case when s.source_id='seoul_reservation' then 4000 else 500 end)
 or (p_reason<>'custom' and coalesce(p_note,'')<>'') then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 input:=jsonb_build_array('exclude',p_id,p_revision,p_version,p_reason,v_memo);
 select * into r from machimoa_review.admin_exclusion_requests where request_id=p_request;
 if found then
   if r.actor<>p_actor or r.input<>input then raise sqlstate 'PT422' using message='review_invalid_input';end if;
   if not exists(select 1 from machimoa_review.admin_exclusion_episodes where id=r.episode_id and restored_at is null) then raise sqlstate 'PT409' using message='review_conflict';end if;
   return r.response;
 end if;
 before_item:=case when s.source_id='seoul_reservation' then public.admin_program_detail(p_id) else machimoa_review.admin_review_item('facts',p_id) end;
 if before_item->>'version' is distinct from p_version then raise sqlstate 'PT409' using message='review_conflict';end if;
 select coalesce(jsonb_agg(to_jsonb(j)),'[]') into jobs from machimoa_review.processing_jobs j where source_item_id=p_id and revision_hash=p_revision;
 select coalesce(jsonb_agg(to_jsonb(d)),'[]') into decisions from machimoa_review.ingest_review_decisions d where source_item_id=p_id and revision_hash=p_revision;
 if s.source_id='seoul_reservation' then perform machimoa_review.admin_program_exclude_before_trash(p_id,p_revision,p_version,v_memo,p_actor);
 else perform machimoa_review.admin_review_exclude_before_trash(p_id,p_revision,p_version,v_memo,p_actor);end if;
 update machimoa_review.admin_exclusion_episodes set review_completed_at=clock_timestamp() where source_item_id=p_id and revision_hash=p_revision and restored_at is not null and review_completed_at is null;
 update machimoa_review.ingest_review_decisions set revoked_at=null where source_item_id=p_id and revision_hash=p_revision and decision='reject' and 'manual_non_target'=any(reason_codes) and reviewer=p_actor::text and ingest_review_decisions.memo=v_memo;
 stamp:=clock_timestamp();
 insert into machimoa_review.admin_exclusion_episodes(source_item_id,revision_hash,source_name,title,reason_code,note,actor,excluded_at,expires_at,prior_jobs,prior_decisions,decision_ids)
 values(p_id,p_revision,s.source_id,coalesce(before_item->'source'->>'title','제목 확인 필요'),p_reason,v_memo,p_actor,stamp,stamp+interval '72 hours',jobs,decisions,
   array(select id from machimoa_review.ingest_review_decisions where source_item_id=p_id and revision_hash=p_revision and decision='reject' and 'manual_non_target'=any(reason_codes) and reviewer=p_actor::text and ingest_review_decisions.memo=v_memo)) returning * into e;
 result:=jsonb_build_object('episodeId',e.id,'expiresAt',e.expires_at,'item',case when s.source_id='seoul_reservation' then public.admin_program_detail(p_id) else machimoa_review.admin_review_item('facts',p_id) end);
 insert into machimoa_review.admin_exclusion_requests values(p_request,p_actor,input,e.id,result,stamp);
 return result;
end $$;

-- Existing custom-exclude clients get the same atomic episode contract.
create function public.admin_review_exclude(p_id uuid,p_revision text,p_version text,p_note text,p_actor uuid) returns jsonb
language sql security definer set search_path='' as $$select public.admin_review_exclude_reason(p_id,p_revision,p_version,'custom',p_note,p_actor,gen_random_uuid())->'item'$$;
create function public.admin_program_exclude(p_id uuid,p_revision text,p_version text,p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$begin
 if not exists(select 1 from machimoa_review.source_items where id=p_id and source_id='seoul_reservation') then raise sqlstate 'PT404' using message='review_not_found';end if;
 return public.admin_review_exclude_reason(p_id,p_revision,p_version,'custom',p_note,p_actor,gen_random_uuid())->'item';end$$;

create function public.admin_review_restore(p_episode uuid,p_revision text,p_version text,p_actor uuid,p_request uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare e machimoa_review.admin_exclusion_episodes%rowtype;r machimoa_review.admin_exclusion_requests%rowtype;
 s machimoa_review.source_items%rowtype;result jsonb;input jsonb;reason text[];stamp timestamptz;
begin
 if p_request is null or p_episode is null or p_version is null or p_version!~'^[a-f0-9]{64}$' then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 select * into e from machimoa_review.admin_exclusion_episodes where id=p_episode;
 if not found then raise sqlstate 'PT404' using message='review_not_found';end if;
 perform machimoa_review.admin_trash_lock(e.source_item_id,p_revision,p_actor);
 select * into e from machimoa_review.admin_exclusion_episodes where id=p_episode for update;
 select * into s from machimoa_review.source_items where id=e.source_item_id;
 input:=jsonb_build_array('restore',p_episode,p_revision,p_version);
 select * into r from machimoa_review.admin_exclusion_requests where request_id=p_request;
 if found then
   if r.actor<>p_actor or r.input<>input then raise sqlstate 'PT422' using message='review_invalid_input';end if;
   if e.restored_at is null or e.review_completed_at is not null then raise sqlstate 'PT409' using message='review_conflict';end if;
   return r.response;
 end if;
 stamp:=clock_timestamp(); -- AFTER all source/job/candidate/episode lock waits.
 if e.restored_at is not null then raise sqlstate 'PT409' using message='review_already_processed';end if;
 if stamp>=e.expires_at then raise sqlstate 'PT409' using message='trash_expired';end if;
 if e.revision_hash is distinct from p_revision or machimoa_review.admin_trash_version(e.id) is distinct from p_version then raise sqlstate 'PT409' using message='review_conflict';end if;
 if (s.source_id<>'seoul_reservation' and s.disposition<>'non_target') or (s.source_id='seoul_reservation' and not exists(select 1 from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision and manual_excluded)) then raise sqlstate 'PT409' using message='review_conflict';end if;
 update machimoa_review.admin_exclusion_episodes set restored_at=stamp,restored_by=p_actor where id=e.id;
 update machimoa_review.ingest_review_decisions set revoked_at=stamp where id=any(e.decision_ids) and decision='reject' and 'manual_non_target'=any(reason_codes);
 if s.source_id='seoul_reservation' then
   update machimoa_review.source_item_program_facts set manual_excluded=false,facts_version=facts_version+1,updated_by=p_actor,updated_at=stamp where source_item_id=s.id and revision_hash=p_revision;
   perform machimoa_review.program_refresh(s.id);
 else
   -- Restore the actual previous human reasons, without overwriting any facts or reviving candidates.
   select coalesce(array_agg(distinct x),'{}') into reason from jsonb_array_elements(e.prior_jobs) j cross join lateral jsonb_array_elements_text(j->'reason_codes') x
   where j->>'processing_stage'<>'ai_enrichment' and j->>'status' in ('queued','claimed');
   update machimoa_review.source_items set disposition='observe_only' where id=s.id;
   insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
   values(s.id,p_revision,'content_review','queued',stamp,stamp,reason||array['restored_review_pending'])
   on conflict(source_item_id,revision_hash,processing_stage) do update set status='queued',completed_at=null,reason_codes=excluded.reason_codes;
 end if;
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note) values(s.id,p_revision,'restore',p_actor,'휴지통에서 복구 · 사람 사실 재확인 필요');
 result:=jsonb_build_object('episodeId',e.id,'sourceItemId',s.id,'sourceName',s.source_id,
   'item',case when s.source_id='seoul_reservation' then public.admin_program_detail(s.id) else machimoa_review.admin_review_item('facts',s.id) end);
 insert into machimoa_review.admin_exclusion_requests values(p_request,p_actor,input,e.id,result,stamp);
 return result;
end $$;

create function machimoa_review.admin_trash_finish(p_id uuid,p_revision text,p_actor uuid) returns void
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;p machimoa_review.source_item_product_types%rowtype;
begin
 if not machimoa_review.admin_trash_pending(p_id,p_revision) then raise sqlstate 'PT409' using message='review_conflict';end if;
 select * into s from machimoa_review.source_items where id=p_id for update;
 update machimoa_review.admin_exclusion_episodes set review_completed_at=clock_timestamp() where source_item_id=p_id and revision_hash=p_revision and restored_at is not null and review_completed_at is null;
 if s.source_id='seoul_reservation' then
   update machimoa_review.source_item_program_facts set facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp() where source_item_id=p_id and revision_hash=p_revision;
   perform machimoa_review.program_refresh(p_id);
 else
   select * into p from machimoa_review.source_item_product_types where source_item_id=p_id and revision_hash=p_revision;
   perform machimoa_review.apply_source_item_evaluation(p_id,p_revision,p.product_type,coalesce(p.reason_codes,'{}'),p.gate_facts);
 end if;
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note) values(p_id,p_revision,'confirm_restored',p_actor,'복구 후 사실을 재확인하고 재평가');
end $$;

create function public.admin_review_save_restored(p_id uuid,p_revision text,p_version text,p_facts jsonb,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare before_item jsonb;after_item jsonb;k text;
begin
 perform machimoa_review.admin_trash_lock(p_id,p_revision,p_actor);
 if not machimoa_review.admin_trash_pending(p_id,p_revision) then raise sqlstate 'PT409' using message='review_conflict';end if;
 before_item:=public.admin_review_detail('facts',p_id);
 if before_item->'source'->>'name'='seoul_reservation' then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 -- The unchanged branch still uses ALL original facts/permission/version validation.
 perform public.admin_review_save_facts(p_id,p_revision,p_version,p_facts,p_actor);
 perform machimoa_review.admin_trash_finish(p_id,p_revision,p_actor);
 after_item:=public.admin_review_detail('facts',p_id);
 for k in select jsonb_array_elements_text(before_item->'reasons') loop
   if k not in ('restored_review_pending','policy_lifecycle_uncertain','policy_lifecycle_conflict','end_date_absent_not_reference','product_type_unknown','product_type_unconfirmed','region_scope_unknown','relevance_unconfirmed','user_category_unconfirmed','application_deadline_unknown')
   and not (after_item->'reasons'?k) then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 end loop;
 return after_item;
end $$;

create function public.admin_program_save_restored(p_id uuid,p_revision text,p_version text,p_patch jsonb,p_resolve text[],p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare before_item jsonb;
begin
 perform machimoa_review.admin_trash_lock(p_id,p_revision,p_actor);
 if not exists(select 1 from machimoa_review.source_items where id=p_id and source_id='seoul_reservation') or not machimoa_review.admin_trash_pending(p_id,p_revision) then raise sqlstate 'PT409' using message='review_conflict';end if;
 before_item:=public.admin_program_detail(p_id);
 if before_item->>'version' is distinct from p_version or before_item->>'status'<>'open' then raise sqlstate 'PT409' using message='review_conflict';end if;
 if p_patch is null or jsonb_typeof(p_patch)<>'object' or p_resolve is null then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 if p_patch='{}'::jsonb then
   if cardinality(p_resolve)<>0 then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 else
   perform public.admin_program_save(p_id,p_revision,p_version,p_patch,p_resolve,p_note,p_actor);
 end if;
 perform machimoa_review.admin_trash_finish(p_id,p_revision,p_actor);
 return public.admin_program_detail(p_id);
end $$;

-- Preserve all prior ACLs on replacements; new internals never executable by service_role.
do $$declare p record;begin
 for p in select oid::regprocedure signature from pg_proc where pronamespace='machimoa_review'::regnamespace and proname like 'admin_trash_%' loop
   execute format('revoke all on function %s from public,anon,authenticated,service_role',p.signature);
 end loop;
 for p in select oid::regprocedure signature from pg_proc where pronamespace='public'::regnamespace and proname in ('admin_review_trash','admin_review_exclude_reason','admin_review_restore','admin_review_save_restored','admin_program_save_restored','admin_review_exclude','admin_program_exclude') loop
   execute format('revoke all on function %s from public,anon,authenticated,service_role',p.signature);
   execute format('grant execute on function %s to service_role',p.signature);
 end loop;
end$$;
notify pgrst,'reload schema';
commit;
