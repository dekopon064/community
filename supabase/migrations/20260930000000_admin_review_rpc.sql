-- LOCAL DRAFT. Run only after isolated-DB execution/concurrency tests and approval.
-- Additive wrappers only: existing evaluator, publication policy and ACL stay intact.
begin;
do $guard$ begin
  if current_user <> 'postgres' then raise exception 'postgres migration owner required'; end if;
  if exists(select 1 from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
    where n.nspname in ('public','machimoa_review') and pg_catalog.left(p.proname,13)='admin_review_') then
    raise exception 'admin review function name already exists; inspect before applying';
  end if;
end $guard$;

create table machimoa_review.admin_review_events (
  id bigint generated always as identity primary key,
  source_item_id uuid not null references machimoa_review.source_items(id) on delete restrict,
  candidate_id uuid references machimoa_review.curation_candidates(id) on delete restrict,
  revision_hash text not null check (revision_hash ~ '^[0-9a-f]{64}$'),
  action text not null check (action in ('save_facts','exclude','save_candidate','publish','reject')),
  actor uuid not null,
  occurred_at timestamptz not null default pg_catalog.clock_timestamp(),
  note text not null default '' check (pg_catalog.char_length(note) <= 4000),
  changed_fields text[] not null default '{}'
);
alter table machimoa_review.admin_review_events owner to postgres;
alter table machimoa_review.admin_review_events enable row level security;
revoke all on table machimoa_review.admin_review_events from public, anon, authenticated, service_role;
revoke all on sequence machimoa_review.admin_review_events_id_seq from public, anon, authenticated, service_role;
create index admin_review_events_item_idx on machimoa_review.admin_review_events(source_item_id, id desc);

-- Resolve by canonical source + external key, never title or a browser-supplied relation.
create function machimoa_review.admin_review_source(p_kind text, p_id uuid) returns uuid
language plpgsql stable security definer set search_path = '' as $fn$
declare v_id uuid;
begin
  if p_kind = 'facts' then
    select s.id into v_id from machimoa_review.source_items s where s.id = p_id;
  elsif p_kind = 'candidates' then
    select s.id into v_id from machimoa_review.curation_candidates c
    join machimoa_review.source_items s
      on s.source_id = machimoa_review.canonical_source_id(c.source)
      and s.external_key = c.source_item_id where c.id = p_id;
  else raise sqlstate 'PT422' using message = 'review_invalid_input'; end if;
  if v_id is null then raise sqlstate 'PT404' using message = 'review_not_found'; end if;
  return v_id;
end $fn$;

-- Internal snapshot includes fact/job/decision changes within the SAME source revision.
-- Payloads remain server-side; the browser receives only a digest and projected DTO.
create function machimoa_review.admin_review_snapshot(p_kind text, p_id uuid) returns jsonb
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
  ) from machimoa_review.source_items s join machimoa_review.ingest_sources src on src.source_id=s.source_id
  where s.id=machimoa_review.admin_review_source(p_kind,p_id)
$fn$;

create function machimoa_review.admin_review_item(p_kind text, p_id uuid) returns jsonb
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
  return base||pg_catalog.jsonb_build_object('status',c->>'review_status','category',coalesce(c->>'user_category',''),
    'period',coalesce(c->>'event_start_on',c->>'application_deadline_on','기간 정보 없음'),
    'publishedAt',c->'published_at','publishedId',c->'published_curation_id',
    'content',pg_catalog.jsonb_build_object('titleKo',coalesce(c->>'title_ko',c->>'title',''),'titleJa',coalesce(c->>'title_ja',''),
      'summaryKo',coalesce(c->>'summary_ko',c->>'summary',''),'summaryJa',coalesce(c->>'summary_ja',''),
      'contentKo',coalesce(c->>'content_ko',c->>'content',''),'contentJa',coalesce(c->>'content_ja','')));
end $fn$;

-- Lock order: source -> source permission -> jobs -> canonical advisory -> candidate.
-- Snapshot checks run AFTER locks. Existing RPCs reuse these locks in this transaction.
create function machimoa_review.admin_review_lock(p_kind text,p_id uuid,p_revision text,p_version text,p_actor uuid) returns uuid
language plpgsql security definer set search_path = '' as $fn$
declare v_id uuid; s machimoa_review.source_items%rowtype; d jsonb; legacy text;
begin
  if p_actor is null or p_revision is null or p_revision !~ '^[0-9a-f]{64}$'
    or p_version is null or p_version !~ '^[0-9a-f]{64}$' then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  v_id := machimoa_review.admin_review_source(p_kind,p_id);
  select * into s from machimoa_review.source_items where id=v_id for update;
  if s.revision_hash is distinct from p_revision then raise sqlstate 'PT409' using message='review_conflict'; end if;
  select src.legacy_curation_source into legacy from machimoa_review.ingest_sources src where src.source_id=s.source_id for share;
  perform 1 from machimoa_review.processing_jobs j where j.source_item_id=v_id and j.revision_hash=p_revision order by j.processing_stage for update;
  if p_kind='candidates' then
    if legacy is null then raise sqlstate 'PT409' using message='review_conflict'; end if;
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(legacy||':'||s.external_key,0));
    perform 1 from machimoa_review.curation_candidates c where c.id=p_id for update;
    if exists(select 1 from machimoa_review.curation_candidates c where c.id=p_id and c.source_revision_hash is distinct from s.revision_hash) then
      raise sqlstate 'PT409' using message='review_conflict'; end if;
  end if;
  d := machimoa_review.admin_review_item(p_kind,p_id);
  if (p_kind='facts' and d->>'status'<>'open') or (p_kind='candidates' and d->>'status'<>'pending') then
    raise sqlstate 'PT409' using message='review_already_processed'; end if;
  if d->>'version' is distinct from p_version then raise sqlstate 'PT409' using message='review_conflict'; end if;
  if exists(select 1 from machimoa_review.processing_jobs j where j.source_item_id=v_id and j.revision_hash=p_revision
    and j.processing_stage='ai_enrichment' and j.status='claimed' and (j.claim_lease_until is null or j.claim_lease_until>pg_catalog.clock_timestamp())) then
    raise sqlstate 'PT409' using message='review_conflict'; end if;
  return v_id;
end $fn$;

create function public.admin_review_detail(p_kind text,p_id uuid) returns jsonb
language plpgsql stable security definer set search_path = '' as $fn$
begin
  if p_kind='candidates' and exists(select 1 from machimoa_review.curation_candidates c
    join machimoa_review.source_items s on s.id=machimoa_review.admin_review_source(p_kind,p_id)
    where c.id=p_id and c.source_revision_hash is distinct from s.revision_hash) then
    raise sqlstate 'PT409' using message='review_conflict';
  end if;
  return machimoa_review.admin_review_item(p_kind,p_id);
end
$fn$;

create function public.admin_review_list(p_kind text,p_offset integer default 0,p_limit integer default 25) returns jsonb
language plpgsql stable security definer set search_path = '' as $fn$
declare result jsonb;
begin
  if p_kind is null or p_kind not in ('facts','candidates') or p_offset is null or p_offset not between 0 and 999999
    or p_limit is null or p_limit not between 1 and 25 then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('id',q.id,'title',q.title,'sourceName',q.source_name,'status',q.status,'reasons',q.reasons) order by q.sort_at,q.id),'[]'::jsonb)
    into result from (
    select s.id,coalesce(s.normalized_payload->>'pstTtl',s.normalized_payload->>'plcyNm',s.min_fields->>'title','제목 확인 필요') title,
      s.source_id source_name,'open'::text status,
      (select coalesce(pg_catalog.jsonb_agg(distinct r.reason),'[]'::jsonb) from machimoa_review.processing_jobs j,
        lateral pg_catalog.unnest(j.reason_codes) r(reason) where j.source_item_id=s.id and j.revision_hash=s.revision_hash
        and j.processing_stage<>'ai_enrichment' and j.status in ('queued','claimed')) reasons,
      (select pg_catalog.min(j.queued_at) from machimoa_review.processing_jobs j where j.source_item_id=s.id and j.revision_hash=s.revision_hash and j.processing_stage<>'ai_enrichment' and j.status in ('queued','claimed')) sort_at
    from machimoa_review.source_items s where p_kind='facts' and s.disposition<>'non_target' and exists(
      select 1 from machimoa_review.processing_jobs j where j.source_item_id=s.id and j.revision_hash=s.revision_hash and j.processing_stage<>'ai_enrichment' and j.status in ('queued','claimed'))
    union all
    select c.id,coalesce(c.title_ko,c.title),s.source_id,c.review_status,'[]'::jsonb,c.created_at
    from machimoa_review.curation_candidates c join machimoa_review.source_items s
      on s.source_id=machimoa_review.canonical_source_id(c.source) and s.external_key=c.source_item_id and s.revision_hash=c.source_revision_hash
    where p_kind='candidates' and c.review_status='pending'
    order by sort_at,id offset p_offset limit p_limit
  ) q;
  return result;
end $fn$;

create function public.admin_review_save_facts(p_id uuid,p_revision text,p_version text,p_facts jsonb,p_actor uuid) returns jsonb
language plpgsql security definer set search_path = '' as $fn$
declare v_id uuid; before_item jsonb; after_item jsonb; changed text[]; gate jsonb; k text; new_type text;
begin
  v_id:=machimoa_review.admin_review_lock('facts',p_id,p_revision,p_version,p_actor);
  before_item:=machimoa_review.admin_review_item('facts',p_id);
  if p_facts is null or pg_catalog.jsonb_typeof(p_facts)<>'object'
    or (select pg_catalog.count(*) from pg_catalog.jsonb_object_keys(p_facts))<>11 then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  if exists(select 1 from pg_catalog.jsonb_each(p_facts) t where
    t.key not in ('productType','category','scope','regions','evidence','foreignEligibility','delivery','deadlineKind','deadlineOn','eventStart','eventEnd')
    or (t.key<>'regions' and pg_catalog.jsonb_typeof(t.value)<>'string'))
    or pg_catalog.jsonb_typeof(p_facts->'regions') is distinct from 'array'
    or p_facts->>'productType' not in ('','event_program','policy_reference','living_guide')
    or p_facts->>'category' not in ('','policy','program','event','youth_space','living')
    or p_facts->>'scope' not in ('nationwide','specific','unknown')
    or p_facts->>'foreignEligibility' not in ('eligible','ineligible','unknown')
    or p_facts->>'delivery' not in ('online','offline','hybrid','unknown')
    or p_facts->>'deadlineKind' not in ('','fixed','none','closed')
    or pg_catalog.char_length(p_facts->>'evidence')>500 then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  if pg_catalog.jsonb_array_length(p_facts->'regions')>17 or exists(select 1 from pg_catalog.jsonb_array_elements(p_facts->'regions') r
    where pg_catalog.jsonb_typeof(r)<>'string' or (r#>>'{}') !~ '^(11|26|27|28|29|30|31|36|41|42|43|44|45|46|47|48|50)$') then
    raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  select coalesce(pg_catalog.array_agg(t.key),'{}'::text[]) into changed from pg_catalog.jsonb_each(p_facts) t
    where t.value is distinct from before_item->'facts'->t.key;
  foreach k in array changed loop
    if not (before_item->'editableFields' ? k) then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  end loop;
  if pg_catalog.cardinality(changed)=0 then return before_item; end if;
  new_type:=p_facts->>'productType';
  if (new_type='living_guide' and changed && array['scope','regions','evidence','foreignEligibility'])
    or (new_type='event_program' and 'foreignEligibility'=any(changed)) then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  if 'productType'=any(changed) then
    perform machimoa_review.resolve_source_item_product_type(v_id,p_revision,'confirm',new_type,'{}'::text[],'{}'::text[],'admin-review-v1',p_actor::text,null);
  end if;
  if 'category'=any(changed) or 'eventStart'=any(changed) or 'eventEnd'=any(changed) then
    perform machimoa_review.resolve_source_item_user_category(v_id,p_revision,p_facts->>'category',nullif(p_facts->>'eventStart','')::date,nullif(p_facts->>'eventEnd','')::date,p_actor::text);
  end if;
  if 'deadlineKind'=any(changed) or 'deadlineOn'=any(changed) then
    perform machimoa_review.resolve_source_item_application_deadline(v_id,p_revision,p_facts->>'deadlineKind',nullif(p_facts->>'deadlineOn','')::date,p_actor::text);
  end if;
  if changed && array['productType','scope','regions','evidence','foreignEligibility','delivery'] then
    gate:=pg_catalog.jsonb_build_object('schema_version','gate-facts-v1','delivery_mode',p_facts->>'delivery');
    if new_type<>'living_guide' then gate:=gate||pg_catalog.jsonb_build_object('eligibility_scope',p_facts->>'scope',
      'eligibility_region_codes',p_facts->'regions','eligibility_region_evidence',p_facts->>'evidence'); end if;
    if new_type='policy_reference' then gate:=gate||pg_catalog.jsonb_build_object('foreign_resident_eligibility',p_facts->>'foreignEligibility'); end if;
    perform machimoa_review.resolve_source_item_gate_facts(v_id,p_revision,gate,'gate-facts-v1',p_actor::text,null);
  end if;
  insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,changed_fields) values(v_id,p_revision,'save_facts',p_actor,changed);
  after_item:=machimoa_review.admin_review_item('facts',p_id);
  -- An existing evaluator must not silently clear an unrelated/unsupported reason.
  for k in select pg_catalog.jsonb_array_elements_text(before_item->'reasons') loop
    if k not in ('policy_lifecycle_uncertain','policy_lifecycle_conflict','end_date_absent_not_reference','product_type_unknown','product_type_unconfirmed',
      'region_scope_unknown','relevance_unconfirmed','user_category_unconfirmed','application_deadline_unknown')
      and not (after_item->'reasons' ? k) then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  end loop;
  return after_item;
exception when invalid_text_representation or datetime_field_overflow or check_violation or raise_exception then
  raise sqlstate 'PT422' using message='review_invalid_input';
end $fn$;

create function public.admin_review_exclude(p_id uuid,p_revision text,p_version text,p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path = '' as $fn$
declare v_id uuid; review_type text;
begin
  v_id:=machimoa_review.admin_review_lock('facts',p_id,p_revision,p_version,p_actor);
  if p_note is null or pg_catalog.char_length(pg_catalog.btrim(p_note)) not between 1 and 500 then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  select case when j.processing_stage='content_review' then 'content' else 'product_type' end into review_type
    from machimoa_review.processing_jobs j where j.source_item_id=v_id and j.revision_hash=p_revision
    and j.processing_stage in ('content_review','product_type_review') and j.status in ('queued','claimed') order by j.processing_stage limit 1;
  if review_type is null then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  perform public.resolve_ingest_review_decision(v_id,p_revision,review_type,'reject','unknown','{}'::text[],array['manual_non_target'],'admin-review-v1',p_actor::text,pg_catalog.btrim(p_note));
  insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note) values(v_id,p_revision,'exclude',p_actor,pg_catalog.btrim(p_note));
  return machimoa_review.admin_review_item('facts',p_id);
exception when raise_exception then raise sqlstate 'PT409' using message='review_conflict';
end $fn$;

-- Shared private dispatcher is inaccessible to service_role; public wrappers fix action.
create function machimoa_review.admin_review_candidate_action(p_action text,p_id uuid,p_revision text,p_version text,p_content jsonb,p_note text,p_actor uuid) returns jsonb
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

create function public.admin_review_save_candidate(p_id uuid,p_revision text,p_version text,p_content jsonb,p_actor uuid) returns jsonb
language sql security definer set search_path = '' as $fn$
  select machimoa_review.admin_review_candidate_action('save_candidate',p_id,p_revision,p_version,p_content,null,p_actor)
$fn$;
create function public.admin_review_publish(p_id uuid,p_revision text,p_version text,p_actor uuid) returns jsonb
language sql security definer set search_path = '' as $fn$
  select machimoa_review.admin_review_candidate_action('publish',p_id,p_revision,p_version,null,null,p_actor)
$fn$;
create function public.admin_review_reject(p_id uuid,p_revision text,p_version text,p_note text,p_actor uuid) returns jsonb
language sql security definer set search_path = '' as $fn$
  select machimoa_review.admin_review_candidate_action('reject',p_id,p_revision,p_version,null,p_note,p_actor)
$fn$;

-- Enumerate ONLY newly created functions; never broaden existing private ACLs.
do $acl$
declare f regprocedure;
begin
  for f in select p.oid::regprocedure from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
    where n.nspname in ('public','machimoa_review') and p.proname in (
      'admin_review_source','admin_review_snapshot','admin_review_item','admin_review_lock','admin_review_candidate_action',
      'admin_review_detail','admin_review_list','admin_review_save_facts','admin_review_exclude','admin_review_save_candidate','admin_review_publish','admin_review_reject') loop
    execute pg_catalog.format('alter function %s owner to postgres',f);
    execute pg_catalog.format('revoke all on function %s from public, anon, authenticated, service_role',f);
    if (select n.nspname='public' from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace where p.oid=f::oid) then
      execute pg_catalog.format('grant execute on function %s to service_role',f);
    end if;
  end loop;
end $acl$;
notify pgrst, 'reload schema';
commit;
