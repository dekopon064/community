begin;

-- Separate from source-change acknowledgement and filter approval. Bodies only.
create table machimoa_review.published_body_edits (
  id bigint generated always as identity primary key,
  candidate_id uuid not null,
  curation_id uuid not null,
  actor uuid not null,
  occurred_at timestamptz not null default clock_timestamp(),
  note text not null check (char_length(btrim(note)) between 1 and 4000),
  revision_hash text not null,
  candidate_version text not null,
  public_version text not null,
  before_candidate jsonb not null,
  before_public jsonb not null,
  after_body jsonb not null
);
alter table machimoa_review.published_body_edits owner to postgres;
alter table machimoa_review.published_body_edits enable row level security;
revoke all on table machimoa_review.published_body_edits from public,anon,authenticated,service_role;
revoke all on sequence machimoa_review.published_body_edits_id_seq from public,anon,authenticated,service_role;
create index published_body_edits_candidate_idx on machimoa_review.published_body_edits(candidate_id,id desc);

create function public.admin_review_published_list(p_offset integer default 0,p_limit integer default 25) returns jsonb
language plpgsql stable security definer set search_path='' as $$
begin
 if p_offset is null or p_offset<0 or p_offset>999999 or p_limit is null or p_limit not between 1 and 25 then
  raise exception using errcode='PT422',message='review_invalid_input';end if;
 return coalesce((select jsonb_agg(q.item order by q.published_at desc,q.id) from (
  select c.id,c.published_at,jsonb_build_object('id',c.id,'title',coalesce(pc.title_ko,pc.title),
   'sourceName',s.source_id,'status','published','reasons','[]'::jsonb) item
  from machimoa_review.curation_candidates c
  join machimoa_review.source_items s on s.source_id=machimoa_review.canonical_source_id(c.source) and s.external_key=c.source_item_id
  join public.curations pc on pc.id=c.published_curation_id and pc.is_published
  where c.review_status='published' order by c.published_at desc,c.id offset p_offset limit p_limit
 )q),'[]'::jsonb);
end $$;

create function public.admin_review_published_detail(p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare item jsonb;pc public.curations%rowtype;history jsonb;
begin
 select p.* into pc from public.curations p join machimoa_review.curation_candidates c on c.published_curation_id=p.id
 where c.id=p_id and c.review_status='published' and p.is_published;
 if not found then raise exception using errcode='PT404',message='review_not_found';end if;
 item:=machimoa_review.admin_review_item('candidates',p_id);
 -- Read the actual public body; candidate and public text can have diverged.
 item:=item||jsonb_build_object('publishedBodyVersion',encode(sha256(convert_to(to_jsonb(pc)::text,'UTF8')),'hex'),
  'content',jsonb_build_object('titleKo',coalesce(pc.title_ko,pc.title,''),'titleJa',coalesce(pc.title_ja,''),
   'summaryKo',coalesce(pc.summary_ko,pc.summary,''),'summaryJa',coalesce(pc.summary_ja,''),
   'contentKo',coalesce(pc.content_ko,pc.content,''),'contentJa',coalesce(pc.content_ja,'')));
 select coalesce(jsonb_agg(case when exists(select 1 from machimoa_review.published_body_edits e
   where e.candidate_id=p_id and e.actor::text=h->>'actor' and e.occurred_at=(h->>'at')::timestamptz)
   then h||jsonb_build_object('fields',jsonb_build_array('published_body_edit')) else h end order by ord),'[]'::jsonb)
 into history from jsonb_array_elements(item->'history') with ordinality q(h,ord);
 return item||jsonb_build_object('history',history);
end $$;

create function public.admin_review_save_published_body(p_id uuid,p_revision text,p_version text,p_public_version text,p_body jsonb,p_note text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare sid uuid;s machimoa_review.source_items%rowtype;c machimoa_review.curation_candidates%rowtype;
 pc public.curations%rowtype;item jsonb;legacy text;key text;value text;stamp timestamptz;
begin
 if p_actor is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or p_version is null or p_version !~ '^[a-f0-9]{64}$'
 or p_public_version is null or p_public_version !~ '^[a-f0-9]{64}$' or char_length(btrim(coalesce(p_note,''))) not between 1 and 4000
 or p_body is null or jsonb_typeof(p_body)<>'object' or (select array_agg(k order by k) from jsonb_object_keys(p_body) k) is distinct from array['contentJa','contentKo']
 or octet_length(p_body::text)>1200000 then raise exception using errcode='PT422',message='review_invalid_input';end if;
 for key,value in select k,v from jsonb_each_text(p_body) q(k,v) loop
  if jsonb_typeof(p_body->key)<>'string' or char_length(btrim(value)) not between 1 and 200000 then
   raise exception using errcode='PT422',message='review_invalid_input';end if;
  p_body:=jsonb_set(p_body,array[key],to_jsonb(btrim(value)));
 end loop;
 -- Match the existing review lock order; never loosen pending save/publish gates.
 sid:=machimoa_review.admin_review_source('candidates',p_id);
 select * into s from machimoa_review.source_items where id=sid for update;
 if s.revision_hash is distinct from p_revision then raise exception using errcode='PT409',message='review_conflict';end if;
 select legacy_curation_source into legacy from machimoa_review.ingest_sources where source_id=s.source_id
  and enabled and permission_status in ('approved_noncommercial','approved_commercial') for share;
 if legacy is null then raise exception using errcode='PT409',message='program_candidate_unavailable';end if;
 perform 1 from machimoa_review.processing_jobs where source_item_id=sid order by revision_hash,processing_stage for update;
 perform pg_advisory_xact_lock(hashtextextended(legacy||':'||s.external_key,0));
 select * into c from machimoa_review.curation_candidates where id=p_id for update;
 if c.review_status is distinct from 'published' then raise exception using errcode='PT409',message='review_already_processed';end if;
 select * into pc from public.curations where id=c.published_curation_id for update;
 if not found or pc.is_published is not true then raise exception using errcode='PT409',message='review_conflict';end if;
 item:=machimoa_review.admin_review_item('candidates',p_id);
 if c.source_revision_hash is distinct from s.revision_hash or item->>'version' is distinct from p_version
 or encode(sha256(convert_to(to_jsonb(pc)::text,'UTF8')),'hex') is distinct from p_public_version
 or coalesce((item->'programInfo'->>'inputChanged')::boolean,false)
 or exists(select 1 from machimoa_review.processing_jobs where source_item_id=sid and status='claimed'
  and (claim_lease_until is null or claim_lease_until>clock_timestamp())) then
  raise exception using errcode='PT409',message='review_conflict';end if;
 if coalesce(pc.content_ko,pc.content,'')=p_body->>'contentKo' and coalesce(pc.content_ja,'')=p_body->>'contentJa' then
  raise exception using errcode='PT422',message='review_invalid_input';end if;
 stamp:=clock_timestamp();
 insert into machimoa_review.published_body_edits(candidate_id,curation_id,actor,occurred_at,note,revision_hash,candidate_version,public_version,before_candidate,before_public,after_body)
 values(p_id,pc.id,p_actor,stamp,btrim(p_note),p_revision,p_version,p_public_version,
  jsonb_build_object('contentKo',coalesce(c.content_ko,c.content,''),'contentJa',coalesce(c.content_ja,'')),
  jsonb_build_object('contentKo',coalesce(pc.content_ko,pc.content,''),'contentJa',coalesce(pc.content_ja,'')),p_body);
 update machimoa_review.curation_candidates set content=p_body->>'contentKo',content_ko=p_body->>'contentKo',content_ja=p_body->>'contentJa' where id=p_id;
 -- Existing candidate-body triggers can project the source image. Restore the
 -- locked public image in this same transaction: this action edits bodies only.
 update public.curations set content=p_body->>'contentKo',content_ko=p_body->>'contentKo',content_ja=p_body->>'contentJa',source_image_url=pc.source_image_url,updated_at=stamp where id=pc.id;
 insert into machimoa_review.admin_review_events(source_item_id,candidate_id,revision_hash,action,actor,note,occurred_at,changed_fields)
 values(sid,p_id,p_revision,'save_candidate',p_actor,btrim(p_note),stamp,array['published_body_edit','contentKo','contentJa']);
 return public.admin_review_published_detail(p_id);
end $$;

revoke all on function public.admin_review_published_list(integer,integer),public.admin_review_published_detail(uuid),public.admin_review_save_published_body(uuid,text,text,text,jsonb,text,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_review_published_list(integer,integer),public.admin_review_published_detail(uuid),public.admin_review_save_published_body(uuid,text,text,text,jsonb,text,uuid) to service_role;
notify pgrst,'reload schema';
commit;
