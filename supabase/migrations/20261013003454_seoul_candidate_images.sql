-- Local, unapplied contract: share candidate image choice with Seoul reservation.
-- No source/candidate/public-content backfill, AI input, or version change.
begin;
do $$ begin if current_user <> 'postgres' then raise exception 'postgres_required'; end if; end $$;
do $guard$
begin
 if to_regprocedure('machimoa_review.seoul_images_base_admin_review_item(text,uuid)') is not null
    or to_regprocedure('public.admin_review_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid)') is not null
    or to_regprocedure('public.admin_myseoul_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid)') is null
    or not exists(select 1 from pg_constraint where conrelid='machimoa_review.curation_candidates'::regclass
      and conname='candidate_image_selection_ck' and strpos(pg_get_constraintdef(oid),'myseoul_program')>0
      and strpos(pg_get_constraintdef(oid),'seoul_reservation')=0) then
   raise exception 'candidate_image_contract_changed';
 end if;
 if (select replace(prosrc,chr(13),'') from pg_proc where oid='machimoa_review.project_published_source_image()'::regprocedure)
 is distinct from $expected$
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
end $expected$ then raise exception 'source_image_projection_definition_changed'; end if;
end $guard$;

alter table machimoa_review.curation_candidates drop constraint candidate_image_selection_ck;
alter table machimoa_review.curation_candidates add constraint candidate_image_selection_ck check (
 (image_selection_mode='source' and image_override_url is null) or
 (source in ('myseoul_program','seoul_reservation') and (
   (image_selection_mode='none' and image_override_url is null) or
   (image_selection_mode='override' and image_override_url is not null
     and machimoa_review.safe_source_image_url(image_override_url) is not null
     and image_override_url=machimoa_review.safe_source_image_url(image_override_url))))
);

-- Preserve every existing fact/filter/program/public-body projection by delegation.
alter function machimoa_review.admin_review_item(text,uuid) rename to seoul_images_base_admin_review_item;
revoke all on function machimoa_review.seoul_images_base_admin_review_item(text,uuid) from public,anon,authenticated,service_role;
create function machimoa_review.admin_review_item(p_kind text,p_id uuid)
returns jsonb language plpgsql stable security definer set search_path='' as $fn$
declare item jsonb; c machimoa_review.curation_candidates%rowtype; v_url text;
begin
 item:=machimoa_review.seoul_images_base_admin_review_item(p_kind,p_id);
 if p_kind='candidates' then
   select * into c from machimoa_review.curation_candidates where id=p_id;
   if c.source='seoul_reservation' then
     select machimoa_review.safe_source_image_url(coalesce(si.normalized_payload->>'source_image_url',
       si.normalized_payload#>>'{provider_fields,IMGURL}')) into v_url
     from machimoa_review.source_items si join machimoa_review.ingest_sources s on s.source_id=si.source_id
     where si.source_id='seoul_reservation' and s.legacy_curation_source=c.source
       and si.external_key=c.source_item_id and si.revision_hash=c.source_revision_hash;
     item:=item||jsonb_build_object('image',jsonb_build_object(
       'mode',c.image_selection_mode,'url',c.image_override_url,'sourceUrl',v_url));
   end if;
 end if;
 return item;
end $fn$;
revoke all on function machimoa_review.admin_review_item(text,uuid) from public,anon,authenticated,service_role;
grant execute on function machimoa_review.admin_review_item(text,uuid) to postgres;

-- Existing MySeoul RPC stays available for older clients; new shared action is atomic.
create function public.admin_review_save_candidate_image(
 p_id uuid,p_revision text,p_version text,p_content jsonb,p_image jsonb,p_actor uuid
) returns jsonb language plpgsql security definer set search_path='' as $fn$
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
end $fn$;
revoke all on function public.admin_review_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid) from public,anon,authenticated;
grant execute on function public.admin_review_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid) to service_role;

create or replace function machimoa_review.project_published_source_image()
returns trigger language plpgsql security definer set search_path='' as $fn$
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
end $fn$;
-- Retains the existing image trigger and its ACL. No UPDATE/backfill of existing rows.
notify pgrst,'reload schema';
commit;
