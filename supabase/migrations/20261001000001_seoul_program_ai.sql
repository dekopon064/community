-- Local-only until separately approved. No source activation/permission changes.
begin;
create table machimoa_review.program_candidate_inputs (
 candidate_id uuid primary key references machimoa_review.curation_candidates(id),
 source_item_id uuid not null, revision_hash text not null, facts_version bigint not null check(facts_version>0),
 job_id uuid not null unique references machimoa_review.processing_jobs(id),
 claimed_at timestamptz not null, lease_until timestamptz not null, worker_id text not null,
 schema_version text not null check(schema_version='program-scope-v1-local'),
 profile text not null check(profile='program_capital_v1_local'),
 api_category text not null check(api_category='문화체험'), input_facts jsonb not null,
 output_hash text not null, created_at timestamptz not null default clock_timestamp(),
 foreign key(source_item_id,revision_hash) references machimoa_review.source_item_program_facts(source_item_id,revision_hash),
 unique(source_item_id,revision_hash)
);
alter table machimoa_review.program_candidate_inputs enable row level security;
revoke all on machimoa_review.program_candidate_inputs from public,anon,authenticated,service_role;

-- Does not reinterpret program facts as capital_v1 facts. Call under source lock.
create function machimoa_review.program_ai_check(p_id uuid,p_revision text,p_version bigint) returns void
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; allowed boolean;
begin
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation' for update;
 if not found or s.revision_hash is distinct from p_revision then
  raise exception using errcode='PT409',message='program_ai_stale';end if;
 select enabled and permission_status in ('approved_noncommercial','approved_commercial') into allowed
 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision for update;
 if not found or f.facts_version is distinct from p_version or
 f.schema_version<>'program-scope-v1-local' or f.evaluated_profile<>'program_capital_v1_local' then
  raise exception using errcode='PT409',message='program_ai_stale';end if;
 if not coalesce(allowed,false) or f.manual_excluded or
 machimoa_review.program_evaluate(f.facts,clock_timestamp())->>'decision'<>'in_scope' or
 s.normalized_payload->'provider_fields'->>'MAXCLASSNM' is distinct from '문화체험' or
 exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision
 and processing_stage<>'ai_enrichment' and status in ('queued','claimed')) then
  raise exception using errcode='PT409',message='program_ai_unavailable';end if;
end $$;

create function public.claim_seoul_program_ai(p_source_item_id uuid,p_revision text,p_worker_id text,p_lease_seconds integer) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype;
 j machimoa_review.processing_jobs%rowtype; v_now timestamptz;
begin
 if p_source_item_id is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or
 p_worker_id is null or char_length(btrim(p_worker_id)) not between 1 and 128 or p_worker_id<>btrim(p_worker_id) or
 p_lease_seconds is null or p_lease_seconds not between 30 and 3600 then
 raise exception using errcode='PT422',message='program_ai_invalid';end if;
 -- Direct target selection; a different source/job cannot win this claim.
 select * into s from machimoa_review.source_items where id=p_source_item_id and source_id='seoul_reservation' for update skip locked;
 if not found then return '[]'::jsonb;end if;
 -- Recover expired attempts even when gate is now closed. A queued row is not
 -- execution permission; the gate below remains authoritative. This prevents
 -- an abandoned claim from permanently blocking program refresh/admin edits.
 update machimoa_review.processing_jobs set status='queued',claimed_at=null,claimed_by=null,claim_lease_until=null
 where source_item_id=s.id and processing_stage='ai_enrichment' and status='claimed' and claim_lease_until<=clock_timestamp();
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision;
 if not found then return '[]'::jsonb;end if;
 begin perform machimoa_review.program_ai_check(s.id,p_revision,f.facts_version);
 exception when sqlstate 'PT409' then return '[]'::jsonb;end;
 if exists(select 1 from machimoa_review.curation_candidates where source='seoul_reservation'
 and source_item_id=s.external_key and source_revision_hash=p_revision) then return '[]'::jsonb;end if;
 v_now:=clock_timestamp();
 select * into j from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision
 and processing_stage='ai_enrichment' and ((status='queued' and available_at<=v_now and (next_retry_at is null or next_retry_at<=v_now))
 or (status='claimed' and claim_lease_until<=v_now)) for update skip locked;
 if not found then return '[]'::jsonb;end if;
 update machimoa_review.processing_jobs set status='claimed',claimed_at=v_now,
 claimed_by=p_worker_id,claim_lease_until=v_now+make_interval(secs=>p_lease_seconds) where id=j.id returning * into j;
 return jsonb_build_array(jsonb_build_object('jobId',j.id,'sourceItemId',s.id,'source','seoul_reservation',
 'externalKey',s.external_key,'revision',p_revision,'schema',f.schema_version,'profile',f.evaluated_profile,
 'factsVersion',f.facts_version,'title',s.min_fields->>'title','apiCategory','문화체험',
 'facts',f.facts,'observedFacts',f.observed_facts,'claimedAt',j.claimed_at,'leaseUntil',j.claim_lease_until,'workerId',p_worker_id));
end $$;

create function public.finish_seoul_program_ai(p_job_id uuid,p_revision text,p_facts_version bigint,
 p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_output jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype;
 j machimoa_review.processing_jobs%rowtype; m machimoa_review.program_candidate_inputs%rowtype;
 v_id uuid; k text; v text; v_now timestamptz; v_hash text; deadline date;
begin
 if p_job_id is null or p_revision is null or p_facts_version is null or p_claimed_at is null or p_lease_until is null or
 p_worker_id is null or p_output is null or jsonb_typeof(p_output)<>'object' or octet_length(p_output::text)>600000 or
 (select array_agg(key order by key) from jsonb_object_keys(p_output) key) is distinct from
 array['aiModel','contentJa','contentKo','summaryJa','summaryKo','titleJa','titleKo'] then
 raise exception using errcode='PT422',message='program_ai_invalid';end if;
 for k,v in select key,value from jsonb_each_text(p_output) loop
 if jsonb_typeof(p_output->k)<>'string' or char_length(btrim(v)) not between 1 and
 (case when k like 'title%' then 300 when k like 'summary%' then 1000 when k='aiModel' then 100 else 200000 end) then
 raise exception using errcode='PT422',message='program_ai_invalid';end if;
 p_output:=jsonb_set(p_output,array[k],to_jsonb(btrim(v)));end loop;
 select si.* into s from machimoa_review.source_items si join machimoa_review.processing_jobs pj on pj.source_item_id=si.id
 where pj.id=p_job_id and si.source_id='seoul_reservation' for update of si;
 if not found then raise exception using errcode='PT409',message='program_ai_stale';end if;
 perform machimoa_review.program_ai_check(s.id,p_revision,p_facts_version);
 select * into f from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision;
 select * into j from machimoa_review.processing_jobs where id=p_job_id for update;
 if j.revision_hash is distinct from p_revision or j.processing_stage<>'ai_enrichment' or
 p_output->>'titleKo' is distinct from s.min_fields->>'title' then
 raise exception using errcode='PT409',message='program_ai_stale';end if;
 v_hash:=encode(sha256(convert_to(p_output::text,'UTF8')),'hex');
 select * into m from machimoa_review.program_candidate_inputs where job_id=p_job_id;
 if found then
 if j.status<>'completed' or m.facts_version<>p_facts_version or m.claimed_at is distinct from p_claimed_at or
 m.lease_until is distinct from p_lease_until or m.worker_id is distinct from p_worker_id or m.output_hash<>v_hash then
 raise exception using errcode='PT409',message='program_ai_stale';end if;
 return jsonb_build_object('candidateId',m.candidate_id,'outcome','duplicate');end if;
 v_now:=clock_timestamp();
 if j.status<>'claimed' or j.claimed_by is distinct from p_worker_id or j.claimed_at is distinct from p_claimed_at or
 j.claim_lease_until is distinct from p_lease_until or j.claim_lease_until<=v_now then
 raise exception using errcode='PT409',message='program_ai_lease_lost';end if;
 perform pg_advisory_xact_lock(hashtextextended('seoul_reservation:'||s.external_key,0));
 if exists(select 1 from machimoa_review.curation_candidates where source='seoul_reservation' and source_item_id=s.external_key
 and source_revision_hash=p_revision) then raise exception using errcode='PT409',message='program_ai_stale';end if;
 deadline:=left(f.facts->'periods'->'RCPTENDDT'->>'value',10)::date;
 v_id:=gen_random_uuid();
 update machimoa_review.curation_candidates set review_status='superseded',superseded_at=v_now,superseded_by_candidate_id=v_id
 where source='seoul_reservation' and source_item_id=s.external_key and review_status='pending';
 insert into machimoa_review.curation_candidates(id,source,source_item_id,source_revision_hash,slug,category,user_category,
 title,summary,content,ai_status,title_ko,summary_ko,content_ko,ai_status_ko,title_ja,summary_ja,content_ja,ai_status_ja,
 source_url,ai_model,raw_payload,application_deadline_kind,application_deadline_on)
 values(v_id,'seoul_reservation',s.external_key,p_revision,'seoul-'||substr(encode(sha256(convert_to(s.external_key,'UTF8')),'hex'),1,32),
 '문화체험','program',p_output->>'titleKo',p_output->>'summaryKo',p_output->>'contentKo','success',
 p_output->>'titleKo',p_output->>'summaryKo',p_output->>'contentKo','success',
 p_output->>'titleJa',p_output->>'summaryJa',p_output->>'contentJa','success',f.facts->>'official_url',p_output->>'aiModel',
 jsonb_build_object('schema',f.schema_version,'profile',f.evaluated_profile,'factsVersion',f.facts_version,'apiCategory','문화체험'),
 'fixed',deadline);
 insert into machimoa_review.program_candidate_inputs(candidate_id,source_item_id,revision_hash,facts_version,job_id,claimed_at,
 lease_until,worker_id,schema_version,profile,api_category,input_facts,output_hash)
 values(v_id,s.id,p_revision,f.facts_version,j.id,p_claimed_at,p_lease_until,p_worker_id,f.schema_version,f.evaluated_profile,
 '문화체험',f.facts,v_hash);
 perform machimoa_review.complete_processing_job(j.id,p_worker_id);
 return jsonb_build_object('candidateId',v_id,'outcome','inserted');
end $$;

-- Failed provider attempts also use an attempt fence before reusing legacy retry rules.
create function public.fail_seoul_program_ai(p_job_id uuid,p_claimed_at timestamptz,p_lease_until timestamptz,p_worker_id text,p_error_code text) returns text
language plpgsql security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype; sid uuid;
begin
 select si.id into sid from machimoa_review.source_items si join machimoa_review.processing_jobs pj on pj.source_item_id=si.id
 where pj.id=p_job_id and si.source_id='seoul_reservation' for update of si;
 if sid is null then raise exception using errcode='PT409',message='program_ai_stale';end if;
 select * into j from machimoa_review.processing_jobs where id=p_job_id for update;
 if j.processing_stage<>'ai_enrichment' or j.status<>'claimed' or j.claimed_at is distinct from p_claimed_at or
 j.claim_lease_until is distinct from p_lease_until or j.claimed_by is distinct from p_worker_id or j.claim_lease_until<=clock_timestamp() then
 raise exception using errcode='PT409',message='program_ai_lease_lost';end if;
 if p_error_code is null or p_error_code not in ('ai_schema_error','ai_blocked_cost_cap','ai_cost_bound_breach',
 'ai_or_enqueue_failed','ai_http_429','ai_http_404','ai_http_5xx','ai_http_4xx','ai_network','ai_unexpected_thinking') then
 p_error_code:='ai_or_enqueue_failed';end if;
 perform machimoa_review.fail_processing_job(p_job_id,p_worker_id,p_error_code);
 select status into j.status from machimoa_review.processing_jobs where id=p_job_id;
 return j.status;
end $$;

create function machimoa_review.program_candidate_guard(p_id uuid) returns void
language plpgsql security definer set search_path='' as $$
declare m machimoa_review.program_candidate_inputs%rowtype; f machimoa_review.source_item_program_facts%rowtype;
begin
 select * into m from machimoa_review.program_candidate_inputs where candidate_id=p_id;
 if not found then raise exception using errcode='PT409',message='program_candidate_input_changed';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=m.source_item_id and revision_hash=m.revision_hash for update;
 if not found or f.facts_version<>m.facts_version then raise exception using errcode='PT409',message='program_candidate_input_changed';end if;
 begin perform machimoa_review.program_ai_check(m.source_item_id,m.revision_hash,m.facts_version);
 exception when sqlstate 'PT409' then raise exception using errcode='PT409',message='program_candidate_unavailable';end;
end $$;

-- Source-specific canonical mapping; unknown sources remain unknown.
create or replace function machimoa_review.canonical_source_id(p_source text) returns text
language sql stable security definer set search_path='' as $$
 select case btrim(lower(coalesce(p_source,''))) when 'youthcenter' then 'youthcenter_policy'
 when 'youthcenter_policy' then 'youthcenter_policy' when 'youthcenter_content' then 'youthcenter_content'
 when 'seoul_reservation' then 'seoul_reservation' else null end;
$$;

create function machimoa_review.program_candidate_info(p_id uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('inputFactsVersion',m.facts_version,'currentFactsVersion',f.facts_version,
 'inputChanged',m.facts_version<>f.facts_version,
 'canPublish',m.facts_version=f.facts_version and not f.manual_excluded and src.enabled and
 src.permission_status in ('approved_noncommercial','approved_commercial') and
 machimoa_review.program_evaluate(f.facts,statement_timestamp())->>'decision'='in_scope',
 'applicationPeriod',concat(m.input_facts->'periods'->'RCPTBGNDT'->>'value',' ~ ',m.input_facts->'periods'->'RCPTENDDT'->>'value'),
 'operatingPeriod',concat(m.input_facts->'periods'->'SVCOPNBGNDT'->>'value',' ~ ',m.input_facts->'periods'->'SVCOPNENDDT'->>'value'))
 from machimoa_review.program_candidate_inputs m join machimoa_review.source_item_program_facts f
 on f.source_item_id=m.source_item_id and f.revision_hash=m.revision_hash
 join machimoa_review.source_items s on s.id=f.source_item_id and s.revision_hash=f.revision_hash
 join machimoa_review.ingest_sources src on src.source_id=s.source_id where m.candidate_id=p_id;
$$;
create or replace function machimoa_review.admin_review_snapshot(p_kind text, p_id uuid) returns jsonb
language sql stable security definer set search_path = '' as $fn$
  select pg_catalog.jsonb_build_object(
    'source', pg_catalog.to_jsonb(s), 'permission', pg_catalog.to_jsonb(src),
    'product', (select pg_catalog.to_jsonb(p) from machimoa_review.source_item_product_types p where p.source_item_id=s.id and p.revision_hash=s.revision_hash),
    'category', (select pg_catalog.to_jsonb(p) from machimoa_review.source_item_user_categories p where p.source_item_id=s.id and p.revision_hash=s.revision_hash),
    'deadline', (select pg_catalog.to_jsonb(p) from machimoa_review.source_item_application_deadlines p where p.source_item_id=s.id and p.revision_hash=s.revision_hash),
    'period', (select pg_catalog.to_jsonb(p) from machimoa_review.source_item_event_periods p where p.source_item_id=s.id and p.revision_hash=s.revision_hash),
    'jobs', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(j) order by j.processing_stage) from machimoa_review.processing_jobs j where j.source_item_id=s.id and j.revision_hash=s.revision_hash), '[]'::jsonb),
    'decisions', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(d) order by d.review_type) from machimoa_review.ingest_review_decisions d where d.source_item_id=s.id and d.revision_hash=s.revision_hash), '[]'::jsonb),
    'candidate', case when p_kind='candidates' then (select pg_catalog.to_jsonb(c) from machimoa_review.curation_candidates c where c.id=p_id) end,
    'event', (select pg_catalog.max(e.id) from machimoa_review.admin_review_events e where e.source_item_id=s.id)
  ) || case when s.source_id='seoul_reservation' then pg_catalog.jsonb_build_object(
    'program',(select pg_catalog.to_jsonb(f) from machimoa_review.source_item_program_facts f where f.source_item_id=s.id and f.revision_hash=s.revision_hash),
    'programInput',(select pg_catalog.to_jsonb(m) from machimoa_review.program_candidate_inputs m where m.candidate_id=p_id)) else '{}'::jsonb end
   from machimoa_review.source_items s join machimoa_review.ingest_sources src on src.source_id=s.source_id
  where s.id=machimoa_review.admin_review_source(p_kind,p_id)
$fn$;

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

create or replace function machimoa_review.admin_review_candidate_action(p_action text,p_id uuid,p_revision text,p_version text,p_content jsonb,p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path = '' as $fn$
declare v_id uuid; before_item jsonb; changed text[]; k text; val text; max_len integer;
begin
  v_id:=machimoa_review.admin_review_lock('candidates',p_id,p_revision,p_version,p_actor);
  if p_action='save_candidate' then
    if p_content is null or pg_catalog.jsonb_typeof(p_content)<>'object' or (select pg_catalog.count(*) from pg_catalog.jsonb_object_keys(p_content))<>6 then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
    for k,val in select t.key,t.value from pg_catalog.jsonb_each_text(p_content) t loop
      max_len:=case when k in ('titleKo','titleJa') then 300 when k in ('summaryKo','summaryJa') then 1000 when k in ('contentKo','contentJa') then 200000 else 0 end;
      if pg_catalog.jsonb_typeof(p_content->k)<>'string' or val is null or pg_catalog.char_length(pg_catalog.btrim(val)) not between 1 and max_len then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
      p_content:=pg_catalog.jsonb_set(p_content,array[k],pg_catalog.to_jsonb(pg_catalog.btrim(val)));
    end loop;
    before_item:=machimoa_review.admin_review_item('candidates',p_id);
    select coalesce(pg_catalog.array_agg(t.key),'{}'::text[]) into changed from pg_catalog.jsonb_each(p_content) t where t.value is distinct from before_item->'content'->t.key;
    if pg_catalog.cardinality(changed)=0 then return before_item; end if;
    update machimoa_review.curation_candidates set title_ko=p_content->>'titleKo',title=p_content->>'titleKo',title_ja=p_content->>'titleJa',
      summary_ko=p_content->>'summaryKo',summary=p_content->>'summaryKo',summary_ja=p_content->>'summaryJa',
      content_ko=p_content->>'contentKo',content=p_content->>'contentKo',content_ja=p_content->>'contentJa' where id=p_id;
  elsif p_action='publish' then
    if exists(select 1 from machimoa_review.source_items where id=v_id and source_id='seoul_reservation') then
      perform machimoa_review.program_candidate_guard(p_id);
    end if;
    begin
      perform machimoa_review.publish_curation_candidate(p_id,p_actor::text,null,false);
    exception when others then raise sqlstate 'PT503' using message='review_publish_failed'; end;
  elsif p_action='reject' then
    if p_note is null or pg_catalog.char_length(pg_catalog.btrim(p_note)) not between 1 and 4000 then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
    perform machimoa_review.reject_curation_candidate(p_id,p_actor::text,pg_catalog.btrim(p_note));
  else raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  insert into machimoa_review.admin_review_events(source_item_id,candidate_id,revision_hash,action,actor,note,changed_fields)
    values(v_id,p_id,p_revision,p_action,p_actor,coalesce(pg_catalog.btrim(p_note),''),coalesce(changed,'{}'::text[]));
  return machimoa_review.admin_review_item('candidates',p_id);
end $fn$;

do $acl$
declare f regprocedure;
begin
 for f in select p.oid::regprocedure from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname='machimoa_review' and p.proname in ('program_ai_check','program_candidate_guard','program_candidate_info')
 or n.nspname='public' and p.proname in ('claim_seoul_program_ai','finish_seoul_program_ai','fail_seoul_program_ai') loop
 execute format('alter function %s owner to postgres',f);
 execute format('revoke all on function %s from public,anon,authenticated,service_role',f);
 if (select n.nspname='public' from pg_proc p join pg_namespace n on n.oid=p.pronamespace where p.oid=f::oid) then
 execute format('grant execute on function %s to service_role',f);end if;
 end loop;
end $acl$;
notify pgrst,'reload schema';
commit;
