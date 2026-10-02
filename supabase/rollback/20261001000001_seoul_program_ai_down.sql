-- Stop program worker calls first. No deletion of jobs, candidates or input history.
begin;
do $$ begin
 if exists(select 1 from machimoa_review.program_candidate_inputs) or
 exists(select 1 from machimoa_review.curation_candidates where source='seoul_reservation') or
 exists(select 1 from machimoa_review.processing_jobs j join machimoa_review.source_items s on s.id=j.source_item_id
 where s.source_id='seoul_reservation' and j.status='claimed') then
 raise exception 'program_ai_rollback_has_references';end if;
end $$;

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
  ) from machimoa_review.source_items s join machimoa_review.ingest_sources src on src.source_id=s.source_id
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
  return base||pg_catalog.jsonb_build_object('status',c->>'review_status','category',coalesce(c->>'user_category',''),
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

create or replace function machimoa_review.canonical_source_id(
  p_source pg_catalog.text
)
returns pg_catalog.text
language sql
stable
security definer
set search_path = ''
as $function$
  select case pg_catalog.btrim(pg_catalog.lower(coalesce(p_source, '')))
    when 'youthcenter' then 'youthcenter_policy'
    when 'youthcenter_policy' then 'youthcenter_policy'
    when 'youthcenter_content' then 'youthcenter_content'
    else null
  end;
$function$;
drop function public.claim_seoul_program_ai(uuid,text,text,integer);
drop function public.finish_seoul_program_ai(uuid,text,bigint,timestamptz,timestamptz,text,jsonb);
drop function public.fail_seoul_program_ai(uuid,timestamptz,timestamptz,text,text);
drop function machimoa_review.program_candidate_guard(uuid);
drop function machimoa_review.program_candidate_info(uuid);
drop function machimoa_review.program_ai_check(uuid,text,bigint);
drop table machimoa_review.program_candidate_inputs;
notify pgrst,'reload schema';
commit;
