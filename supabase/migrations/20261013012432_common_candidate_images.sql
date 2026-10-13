-- Unapplied local follow-up to Seoul images: image metadata for every registered
-- review source. No collector/AI registration, source refresh or content backfill.
begin;
do $$ begin if current_user<>'postgres' then raise exception 'postgres_required';end if;end $$;
do $guard$
begin
 if to_regprocedure('machimoa_review.seoul_images_base_admin_review_item(text,uuid)') is null
   or to_regprocedure('public.admin_review_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid)') is null
   or to_regprocedure('machimoa_review.common_images_base_admin_review_item(text,uuid)') is not null
   or to_regprocedure('machimoa_review.candidate_source_image_url(uuid)') is not null then
  raise exception 'common_candidate_images_prerequisite_missing';
 end if;
 -- Guard bodies are filled from the preceding local migration, not from a DB.
 if (select replace(prosrc,chr(13),'') from pg_proc where oid='machimoa_review.project_published_source_image()'::regprocedure)
    is distinct from $projection_expected$
declare v_url text;
begin
 if new.source in ('myseoul_program','seoul_reservation') and new.image_selection_mode='override' then
   v_url:=machimoa_review.safe_source_image_url(new.image_override_url);
 elsif new.source in ('myseoul_program','seoul_reservation') and new.image_selection_mode='none' then
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
end $projection_expected$
   or (select replace(prosrc,chr(13),'') from pg_proc where oid='public.admin_review_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid)'::regprocedure)
    is distinct from $save_expected$
declare sid uuid; c machimoa_review.curation_candidates%rowtype; mode text; url text; result jsonb;
begin
 sid:=machimoa_review.admin_review_lock('candidates',p_id,p_revision,p_version,p_actor);
 select * into c from machimoa_review.curation_candidates where id=p_id;
 if c.source not in ('myseoul_program','seoul_reservation') or c.review_status<>'pending'
    or c.published_curation_id is not null or not exists(
      select 1 from machimoa_review.source_items si join machimoa_review.ingest_sources s on s.source_id=si.source_id
      where si.id=sid and si.source_id in ('myseoul_program','seoul_reservation')
        and si.external_key=c.source_item_id and si.revision_hash=c.source_revision_hash
        and s.legacy_curation_source=c.source) then
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
end $save_expected$ then
  raise exception 'candidate_image_contract_changed';
 end if;
end $guard$;

alter table machimoa_review.curation_candidates drop constraint candidate_image_selection_ck;
alter table machimoa_review.curation_candidates add constraint candidate_image_selection_ck check (
 (image_selection_mode in ('source','none') and image_override_url is null) or
 (image_selection_mode='override' and image_override_url is not null
   and machimoa_review.safe_source_image_url(image_override_url) is not null
   and image_override_url=machimoa_review.safe_source_image_url(image_override_url))
);

-- All connectors may supply this single normalized metadata field. Only the old
-- Seoul payload has a compatibility fallback; arbitrary provider fields are not inferred.
create function machimoa_review.candidate_source_image_url(p_id uuid)
returns text language sql stable security definer set search_path='' as $fn$
 select machimoa_review.safe_source_image_url(coalesce(si.normalized_payload->>'source_image_url',
   case when si.source_id='seoul_reservation' then si.normalized_payload#>>'{provider_fields,IMGURL}' end))
 from machimoa_review.curation_candidates c
 join machimoa_review.source_items si on si.source_id=machimoa_review.canonical_source_id(c.source)
   and si.external_key=c.source_item_id and si.revision_hash=c.source_revision_hash
 join machimoa_review.ingest_sources s on s.source_id=si.source_id and s.legacy_curation_source=c.source
 where c.id=p_id
$fn$;
revoke all on function machimoa_review.candidate_source_image_url(uuid) from public,anon,authenticated,service_role;
grant execute on function machimoa_review.candidate_source_image_url(uuid) to postgres;

-- Preserve the complete existing review/detail chain. The validated image object
-- is the client capability, including {sourceUrl:null} when no image was collected.
alter function machimoa_review.admin_review_item(text,uuid) rename to common_images_base_admin_review_item;
revoke all on function machimoa_review.common_images_base_admin_review_item(text,uuid) from public,anon,authenticated,service_role;
create function machimoa_review.admin_review_item(p_kind text,p_id uuid)
returns jsonb language plpgsql stable security definer set search_path='' as $fn$
declare item jsonb;c machimoa_review.curation_candidates%rowtype;
begin
 item:=machimoa_review.common_images_base_admin_review_item(p_kind,p_id);
 if p_kind='candidates' then
  select * into c from machimoa_review.curation_candidates where id=p_id;
  item:=item||jsonb_build_object('image',jsonb_build_object(
    'mode',c.image_selection_mode,'url',c.image_override_url,
    'sourceUrl',machimoa_review.candidate_source_image_url(p_id)));
 end if;
 return item;
end $fn$;
revoke all on function machimoa_review.admin_review_item(text,uuid) from public,anon,authenticated,service_role;
grant execute on function machimoa_review.admin_review_item(text,uuid) to postgres;

create or replace function public.admin_review_save_candidate_image(
 p_id uuid,p_revision text,p_version text,p_content jsonb,p_image jsonb,p_actor uuid
) returns jsonb language plpgsql security definer set search_path='' as $fn$
declare sid uuid;c machimoa_review.curation_candidates%rowtype;mode text;url text;result jsonb;
begin
 -- Resolves the server relationship, locks current source/jobs/candidate and checks
 -- actor/revision/snapshot/active claim. Source names are not a separate image allowlist.
 sid:=machimoa_review.admin_review_lock('candidates',p_id,p_revision,p_version,p_actor);
 select * into c from machimoa_review.curation_candidates where id=p_id;
 if c.review_status<>'pending' or c.published_curation_id is not null or not exists(
  select 1 from machimoa_review.source_items si join machimoa_review.ingest_sources s on s.source_id=si.source_id
  where si.id=sid and si.source_id=machimoa_review.canonical_source_id(c.source)
    and si.external_key=c.source_item_id and si.revision_hash=c.source_revision_hash
    and s.legacy_curation_source=c.source) then
  raise sqlstate 'PT422' using message='review_invalid_input';
 end if;
 if p_image is null or jsonb_typeof(p_image)<>'object' or (select count(*) from jsonb_object_keys(p_image))<>2
   or not(p_image ?& array['mode','url']) or jsonb_typeof(p_image->'mode')<>'string' then
  raise sqlstate 'PT422' using message='review_invalid_input';
 end if;
 mode:=p_image->>'mode';
 if mode='override' then
  if jsonb_typeof(p_image->'url')<>'string' then raise sqlstate 'PT422' using message='review_invalid_input';end if;
  url:=machimoa_review.safe_source_image_url(p_image->>'url');
  if url is null then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 elsif mode not in ('source','none') or p_image->'url'<>'null'::jsonb then
  raise sqlstate 'PT422' using message='review_invalid_input';
 end if;
 result:=machimoa_review.admin_review_candidate_action('save_candidate',p_id,p_revision,p_version,p_content,null,p_actor);
 if c.image_selection_mode is distinct from mode or c.image_override_url is distinct from url then
  update machimoa_review.curation_candidates set image_selection_mode=mode,image_override_url=url where id=p_id;
  insert into machimoa_review.admin_review_events(source_item_id,candidate_id,revision_hash,action,actor,note,changed_fields)
  values(sid,p_id,p_revision,'save_candidate',p_actor,'이미지 선택 변경: '||c.image_selection_mode||' → '||mode||
   case when url is not null then E'\n이미지 URL: '||url else '' end,array['image_selection_mode','image_override_url']);
 end if;
 return machimoa_review.admin_review_item('candidates',p_id);
end $fn$;
revoke all on function public.admin_review_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid) from public,anon,authenticated;
grant execute on function public.admin_review_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid) to service_role;
-- The old MySeoul RPC remains unchanged for existing clients.

create or replace function machimoa_review.project_published_source_image()
returns trigger language plpgsql security definer set search_path='' as $fn$
declare v_url text;
begin
 -- Do not project metadata for an unregistered/mismatched source relationship.
 select machimoa_review.safe_source_image_url(coalesce(si.normalized_payload->>'source_image_url',
   case when si.source_id='seoul_reservation' then si.normalized_payload#>>'{provider_fields,IMGURL}' end)) into v_url
 from machimoa_review.source_items si join machimoa_review.ingest_sources s on s.source_id=si.source_id
 where si.source_id=machimoa_review.canonical_source_id(new.source)
   and s.legacy_curation_source=new.source and si.external_key=new.source_item_id
   and si.revision_hash=new.source_revision_hash;
 if not found then return new;end if;
 if new.image_selection_mode='override' then v_url:=machimoa_review.safe_source_image_url(new.image_override_url);
 elsif new.image_selection_mode='none' then v_url:=null;
 end if;
 update public.curations c set source_image_url=v_url
 where c.id=new.published_curation_id and c.is_published
   and machimoa_review.canonical_source_id(c.source)=machimoa_review.canonical_source_id(new.source)
   and c.source_item_id=new.source_item_id;
 return new;
end $fn$;
-- Existing trigger, full-row version snapshot and ACL remain; no row updates here.
notify pgrst,'reload schema';
commit;
