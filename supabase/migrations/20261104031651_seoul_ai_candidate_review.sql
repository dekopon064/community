begin;

create table machimoa_review.seoul_ai_candidate_reviews (
  candidate_id uuid primary key references machimoa_review.curation_candidates(id),
  review jsonb not null check (jsonb_typeof(review) = 'object' and octet_length(review::text) <= 180000)
);
alter table machimoa_review.seoul_ai_candidate_reviews enable row level security;
revoke all on table machimoa_review.seoul_ai_candidate_reviews from public, anon, authenticated, service_role;

alter table machimoa_review.admin_review_events
  add column candidate_content_before jsonb,
  add column candidate_content_after jsonb;

create function public.finish_seoul_ai_candidate_review(
  p_job_id uuid, p_revision text, p_claimed_at timestamptz, p_lease_until timestamptz,
  p_worker_id text, p_mode text, p_input_version bigint, p_output jsonb, p_review jsonb
) returns jsonb
language plpgsql security definer set search_path = '' as $fn$
declare result jsonb; cid uuid; stored_review jsonb;
begin
  if p_mode is null or p_mode not in ('program', 'classification') or p_input_version is null
    or p_review is null or jsonb_typeof(p_review) <> 'object' or octet_length(p_review::text) > 180000
    or jsonb_typeof(p_review->'source') is distinct from 'string'
    or char_length(p_review->>'source') > 32000
    or jsonb_typeof(p_review->'issues') is distinct from 'array' then
    raise sqlstate 'PT422' using message = 'seoul_candidate_review_invalid';
  end if;
  if jsonb_array_length(p_review->'issues') not between 1 and 32 then
    raise sqlstate 'PT422' using message = 'seoul_candidate_review_invalid';
  end if;
  if not exists (
    select 1 from machimoa_review.processing_jobs j
    join machimoa_review.source_items s on s.id = j.source_item_id
    where j.id = p_job_id and s.source_id = 'seoul_reservation'
  ) then
    raise sqlstate 'PT409' using message = 'seoul_candidate_review_stale';
  end if;

  if p_mode = 'program' then
    result := public.finish_seoul_program_ai(p_job_id, p_revision, p_input_version,
      p_claimed_at, p_lease_until, p_worker_id, p_output);
  else
    result := public.finish_reclassified_content_ai(p_job_id, p_revision, p_input_version,
      p_claimed_at, p_lease_until, p_worker_id, p_output);
  end if;
  cid := (result->>'candidateId')::uuid;
  if result->>'outcome' = 'inserted' then
    insert into machimoa_review.seoul_ai_candidate_reviews(candidate_id, review) values(cid, p_review);
  else
    select review into stored_review from machimoa_review.seoul_ai_candidate_reviews where candidate_id = cid;
    if result->>'outcome' is distinct from 'duplicate' or stored_review is distinct from p_review then
      raise sqlstate 'PT409' using message = 'seoul_candidate_review_stale';
    end if;
  end if;
  return result;
end $fn$;

create function public.admin_seoul_ai_candidate_review(p_candidate uuid) returns jsonb
language sql stable security definer set search_path = '' as $fn$
  select jsonb_build_object(
    'review', (select review from machimoa_review.seoul_ai_candidate_reviews where candidate_id = p_candidate),
    'evidence', public.admin_seoul_ai_correction_evidence(p_candidate)
  )
$fn$;

revoke all on function public.finish_seoul_ai_candidate_review(uuid,text,timestamptz,timestamptz,text,text,bigint,jsonb,jsonb),
  public.admin_seoul_ai_candidate_review(uuid) from public, anon, authenticated, service_role;
grant execute on function public.finish_seoul_ai_candidate_review(uuid,text,timestamptz,timestamptz,text,text,bigint,jsonb,jsonb),
  public.admin_seoul_ai_candidate_review(uuid) to service_role;

-- Keep the shared action and its locks/approval rules. Enrich the existing
-- audit event only when a candidate has advisory review data.

create or replace function machimoa_review.admin_review_candidate_action(p_action text,p_id uuid,p_revision text,p_version text,p_content jsonb,p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path = '' as $fn$
declare v_id uuid; before_item jsonb; changed text[]; k text; val text; max_len integer; before_content jsonb; after_content jsonb;
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
    if exists(select 1 from machimoa_review.seoul_ai_candidate_reviews where candidate_id=p_id) then
      select jsonb_object_agg(field, before_item->'content'->field), jsonb_object_agg(field, p_content->field)
        into before_content, after_content from unnest(changed) field;
    end if;
    update machimoa_review.curation_candidates set title_ko=p_content->>'titleKo',title=p_content->>'titleKo',title_ja=p_content->>'titleJa',
      summary_ko=p_content->>'summaryKo',summary=p_content->>'summaryKo',summary_ja=p_content->>'summaryJa',
      content_ko=p_content->>'contentKo',content=p_content->>'contentKo',content_ja=p_content->>'contentJa' where id=p_id;
  elsif p_action='publish' then
    if exists(select 1 from machimoa_review.source_items where id=v_id and source_id in ('seoul_reservation','myseoul_program')) then
      perform machimoa_review.program_candidate_guard(p_id);
    end if;
    begin
      perform machimoa_review.publish_curation_candidate(p_id,p_actor::text,null,false);
    exception when others then raise sqlstate 'PT503' using message='review_publish_failed'; end;
  elsif p_action='reject' then
    if p_note is null or pg_catalog.char_length(pg_catalog.btrim(p_note)) not between 1 and 4000 then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
    perform machimoa_review.reject_curation_candidate(p_id,p_actor::text,pg_catalog.btrim(p_note));
  else raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  insert into machimoa_review.admin_review_events(source_item_id,candidate_id,revision_hash,action,actor,note,changed_fields,candidate_content_before,candidate_content_after)
    values(v_id,p_id,p_revision,p_action,p_actor,coalesce(pg_catalog.btrim(p_note),''),coalesce(changed,'{}'::text[]),before_content,after_content);
  return machimoa_review.admin_review_item('candidates',p_id);
end $fn$;


notify pgrst, 'reload schema';
commit;
