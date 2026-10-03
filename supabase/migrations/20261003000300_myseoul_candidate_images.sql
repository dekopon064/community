-- Candidate-only image choice; observations, revisions and AI inputs stay intact.
begin;
do $$ begin if current_user <> 'postgres' then raise exception 'postgres_required'; end if; end $$;
do $projection_guard$
begin
 if (select replace(prosrc,chr(13),'') from pg_proc where oid='machimoa_review.project_published_source_image()'::regprocedure)
    is distinct from replace($expected$
declare v_url pg_catalog.text;
begin
  select machimoa_review.safe_source_image_url(
    coalesce(si.normalized_payload ->> 'source_image_url',
      case when si.source_id = 'seoul_reservation'
        then si.normalized_payload #>> '{provider_fields,IMGURL}' end)
  ) into v_url
  from machimoa_review.source_items si
  join machimoa_review.ingest_sources s on s.source_id = si.source_id
  where s.legacy_curation_source = new.source
    and si.external_key = new.source_item_id
    and si.revision_hash = new.source_revision_hash
    and si.source_id in ('youthcenter_content', 'seoul_reservation', 'myseoul_program');

  update public.curations c set source_image_url = v_url
  where c.id = new.published_curation_id and c.is_published
    and c.source = new.source and c.source_item_id = new.source_item_id;
  return new;
end;
$expected$,chr(13),'') then
   raise exception 'source_image_projection_definition_changed';
 end if;
end $projection_guard$;
create table machimoa_review.myseoul_image_function_backup(name text primary key, definition text not null, installed text);
alter table machimoa_review.myseoul_image_function_backup enable row level security;
revoke all on machimoa_review.myseoul_image_function_backup from public,anon,authenticated,service_role;
insert into machimoa_review.myseoul_image_function_backup(name,definition)
select oid::regprocedure::text,pg_get_functiondef(oid) from pg_proc
where oid in ('machimoa_review.admin_review_item(text,uuid)'::regprocedure,'machimoa_review.project_published_source_image()'::regprocedure);

alter table machimoa_review.curation_candidates
  add column image_selection_mode text not null default 'source',
  add column image_override_url text;
alter table machimoa_review.curation_candidates add constraint candidate_image_selection_ck check (
  (image_selection_mode='source' and image_override_url is null) or
  (source='myseoul_program' and (
    (image_selection_mode='none' and image_override_url is null) or
    (image_selection_mode='override' and image_override_url is not null
      and machimoa_review.safe_source_image_url(image_override_url) is not null
      and image_override_url=machimoa_review.safe_source_image_url(image_override_url))))
);

-- Snapshot already includes the full candidate row, so image edits participate
-- in the existing version check. Extend only the explicit My detail projection.
do $patch$
declare d text; needle text := 'return base||case when';
begin
 select definition into d from machimoa_review.myseoul_image_function_backup where name='machimoa_review.admin_review_item(text,uuid)';
 if strpos(d,needle)=0 or strpos(d,'myseoul_program')=0 then raise exception 'candidate_detail_contract_changed'; end if;
 d:=replace(d,needle,$image$return base||case when s->>'source_id'='myseoul_program' then pg_catalog.jsonb_build_object('image',pg_catalog.jsonb_build_object(
   'mode',c->>'image_selection_mode','url',c->'image_override_url',
   'sourceUrl',case when s->>'revision_hash'=c->>'source_revision_hash' then machimoa_review.safe_source_image_url(s->'normalized_payload'->>'source_image_url') end)) else '{}'::jsonb end||case when$image$);
 execute d;
end $patch$;

create function public.admin_myseoul_save_candidate_image(
 p_id uuid,p_revision text,p_version text,p_content jsonb,p_image jsonb,p_actor uuid
) returns jsonb language plpgsql security definer set search_path='' as $fn$
declare sid uuid; c machimoa_review.curation_candidates%rowtype; mode text; url text; result jsonb;
begin
 sid:=machimoa_review.admin_review_lock('candidates',p_id,p_revision,p_version,p_actor);
 select * into c from machimoa_review.curation_candidates where id=p_id;
 if c.source<>'myseoul_program' or c.review_status<>'pending' or c.published_curation_id is not null
    or not exists(select 1 from machimoa_review.source_items where id=sid and source_id='myseoul_program') then
   raise sqlstate 'PT422' using message='review_invalid_input';
 end if;
 if p_image is null or jsonb_typeof(p_image)<>'object' or (select count(*) from jsonb_object_keys(p_image))<>2
    or not (p_image ?& array['mode','url']) or jsonb_typeof(p_image->'mode')<>'string' then
   raise sqlstate 'PT422' using message='review_invalid_input';
 end if;
 mode:=p_image->>'mode';
 if mode='override' then
   if jsonb_typeof(p_image->'url')<>'string' then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
   url:=machimoa_review.safe_source_image_url(p_image->>'url');
   if url is null then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
 elsif mode not in ('source','none') or p_image->'url'<>'null'::jsonb then
   raise sqlstate 'PT422' using message='review_invalid_input';
 end if;
 -- Validate/save the six content fields through the existing protected action.
 -- An exception at any following step rolls this save and its event back too.
 result:=machimoa_review.admin_review_candidate_action('save_candidate',p_id,p_revision,p_version,p_content,null,p_actor);
 if c.image_selection_mode is distinct from mode or c.image_override_url is distinct from url then
   update machimoa_review.curation_candidates set image_selection_mode=mode,image_override_url=url where id=p_id;
   insert into machimoa_review.admin_review_events(source_item_id,candidate_id,revision_hash,action,actor,note,changed_fields)
   values(sid,p_id,p_revision,'save_candidate',p_actor,
     '이미지 선택 변경: '||c.image_selection_mode||' → '||mode||
       case when url is not null then E'\n이미지 URL: '||url else '' end,
     array['image_selection_mode','image_override_url']);
 end if;
 return machimoa_review.admin_review_item('candidates',p_id);
end $fn$;
revoke all on function public.admin_myseoul_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid) from public,anon,authenticated;
grant execute on function public.admin_myseoul_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid) to service_role;

create or replace function machimoa_review.project_published_source_image()
returns trigger language plpgsql security definer set search_path='' as $fn$
declare v_url text;
begin
 if new.source='myseoul_program' and new.image_selection_mode='override' then
   v_url:=machimoa_review.safe_source_image_url(new.image_override_url);
 elsif new.source='myseoul_program' and new.image_selection_mode='none' then
   v_url:=null;
 else
   select machimoa_review.safe_source_image_url(coalesce(si.normalized_payload->>'source_image_url',
     case when si.source_id='seoul_reservation' then si.normalized_payload#>>'{provider_fields,IMGURL}' end)) into v_url
   from machimoa_review.source_items si join machimoa_review.ingest_sources s on s.source_id=si.source_id
   where s.legacy_curation_source=new.source and si.external_key=new.source_item_id
     and si.revision_hash=new.source_revision_hash
     and si.source_id in ('youthcenter_content','seoul_reservation','myseoul_program');
 end if;
 update public.curations c set source_image_url=v_url
 where c.id=new.published_curation_id and c.is_published and c.source=new.source and c.source_item_id=new.source_item_id;
 return new;
end $fn$;
-- CREATE OR REPLACE retains the existing trigger/helper ACL; no new table access.
update machimoa_review.myseoul_image_function_backup b set installed=pg_get_functiondef(to_regprocedure(b.name));
notify pgrst,'reload schema';
commit;
