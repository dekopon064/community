-- Reevaluate only the item explicitly restored. No backfill.
begin;
set local lock_timeout='5s';
set local statement_timeout='30s';

create function machimoa_review.admin_trash_current_item(p_id uuid,p_source text) returns jsonb
language plpgsql stable set search_path='' as $$
begin
 if p_source='seoul_reservation' then return public.admin_program_detail(p_id);
 elsif p_source='myseoul_program' then return public.admin_myseoul_program_detail(p_id);
 else return public.admin_review_detail('facts',p_id);end if;
end $$;
revoke all on function machimoa_review.admin_trash_current_item(uuid,text) from public,anon,authenticated,service_role;

-- Only called while the trash lock is held. Clear the restore-only hold before
-- evaluation, in the same transaction. Keep all original facts and receipts.
create function machimoa_review.admin_trash_reevaluate(e machimoa_review.admin_exclusion_episodes,p_actor uuid) returns void
language plpgsql set search_path='' as $$
declare p machimoa_review.source_item_product_types%rowtype;
begin
 update machimoa_review.admin_exclusion_episodes set review_completed_at=clock_timestamp()
 where id=e.id and restored_at is not null and review_completed_at is null;
 if not found then raise sqlstate 'PT409' using message='review_conflict';end if;

 -- Exclusion closes a deliberate AI hold. The prior job snapshot proves that
 -- this hold was still active at exclusion, so restore that same hold.
 if exists(
   select 1 from jsonb_array_elements(e.prior_jobs) j
   where j->>'status'='queued' and j->'reason_codes' ? 'ai_recheck_requested'
 ) and not machimoa_review.ai_recheck_pending(e.source_item_id,e.revision_hash) then
   update machimoa_review.ai_rechecks set completed_at=null where id=(
     select h.id from machimoa_review.ai_rechecks h
     where h.source_item_id=e.source_item_id and h.revision_hash=e.revision_hash
       and h.completed_at<=e.excluded_at
       and exists(select 1 from jsonb_array_elements(e.prior_jobs) j
                  where j->>'id'=h.job_id::text and j->>'processing_stage'='ai_enrichment')
     order by h.completed_at desc limit 1
   );
   if not found then raise sqlstate 'PT409' using message='review_conflict';end if;
 end if;

 if e.source_name in ('seoul_reservation','myseoul_program') then
   update machimoa_review.source_item_program_facts
   set manual_excluded=false,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
   where source_item_id=e.source_item_id and revision_hash=e.revision_hash and manual_excluded;
   if e.source_name='seoul_reservation' then perform machimoa_review.program_refresh(e.source_item_id);
   else perform machimoa_review.myseoul_refresh(e.source_item_id);end if;
 else
   select * into p from machimoa_review.source_item_product_types
   where source_item_id=e.source_item_id and revision_hash=e.revision_hash;
   perform machimoa_review.apply_source_item_evaluation(e.source_item_id,e.revision_hash,p.product_type,coalesce(p.reason_codes,'{}'),p.gate_facts);
   perform machimoa_review.content_filter_review_sync(e.source_item_id,e.revision_hash);
 end if;

 -- Native evaluation may have no reason to touch the existing review job
 -- when the only remaining reason is a separate AI hold.
 if machimoa_review.ai_recheck_pending(e.source_item_id,e.revision_hash) and exists(
   select 1 from machimoa_review.source_items where id=e.source_item_id and disposition<>'non_target'
 ) then
   insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
   values(e.source_item_id,e.revision_hash,'content_review','queued',clock_timestamp(),clock_timestamp(),array['ai_recheck_requested'])
   on conflict(source_item_id,revision_hash,processing_stage) do update
   set status='queued',completed_at=null,reason_codes=array_append(array_remove(
     case when processing_jobs.status='queued' then processing_jobs.reason_codes else '{}'::text[] end,
     'ai_recheck_requested'),'ai_recheck_requested');
 end if;
end $$;
revoke all on function machimoa_review.admin_trash_reevaluate(machimoa_review.admin_exclusion_episodes,uuid) from public,anon,authenticated,service_role;

create or replace function public.admin_review_restore(p_episode uuid,p_revision text,p_version text,p_actor uuid,p_request uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare e machimoa_review.admin_exclusion_episodes%rowtype;r machimoa_review.admin_exclusion_requests%rowtype;
 s machimoa_review.source_items%rowtype;result jsonb;input jsonb;stamp timestamptz;
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
   if e.restored_at is null or exists(
     select 1 from machimoa_review.admin_exclusion_episodes next_exclusion
     where next_exclusion.source_item_id=s.id and next_exclusion.revision_hash=p_revision
       and next_exclusion.excluded_at>e.restored_at
   ) then raise sqlstate 'PT409' using message='review_conflict';end if;
   if e.review_completed_at is null then
     perform machimoa_review.admin_trash_reevaluate(e,p_actor);
   end if;
   return jsonb_set(r.response,'{item}',machimoa_review.admin_trash_current_item(s.id,s.source_id));
 end if;
 stamp:=clock_timestamp(); -- AFTER all source/job/candidate/episode lock waits.
 if e.restored_at is not null then raise sqlstate 'PT409' using message='review_already_processed';end if;
 if stamp>=e.expires_at then raise sqlstate 'PT409' using message='trash_expired';end if;
 if e.revision_hash is distinct from p_revision or machimoa_review.admin_trash_version(e.id) is distinct from p_version then raise sqlstate 'PT409' using message='review_conflict';end if;
 if (s.source_id not in ('seoul_reservation','myseoul_program') and s.disposition<>'non_target')
 or (s.source_id in ('seoul_reservation','myseoul_program') and not exists(
   select 1 from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision and manual_excluded
 )) then raise sqlstate 'PT409' using message='review_conflict';end if;
 update machimoa_review.admin_exclusion_episodes set restored_at=stamp,restored_by=p_actor where id=e.id returning * into e;
 update machimoa_review.ingest_review_decisions set revoked_at=stamp where id=any(e.decision_ids) and decision='reject' and 'manual_non_target'=any(reason_codes);
 perform machimoa_review.admin_trash_reevaluate(e,p_actor);
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note)
 values(s.id,p_revision,'restore',p_actor,'휴지통에서 복구하고 저장된 기준으로 재평가');
 result:=jsonb_build_object('episodeId',e.id,'sourceItemId',s.id,'sourceName',s.source_id,
   'item',machimoa_review.admin_trash_current_item(s.id,s.source_id));
 insert into machimoa_review.admin_exclusion_requests values(p_request,p_actor,input,e.id,result,stamp);
 return result;
end $$;

-- Finish an older restore on its first ordinary filter save. Validate the
-- original version under the same lock before using the freshly evaluated one.
alter function public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid) rename to admin_filter_save_before_restore_flow;
alter function public.admin_filter_save_before_restore_flow(uuid,text,text,bigint,jsonb,uuid) set schema machimoa_review;
revoke all on function machimoa_review.admin_filter_save_before_restore_flow(uuid,text,text,bigint,jsonb,uuid) from public,anon,authenticated,service_role;

create function public.admin_content_filter_save(p_id uuid,p_revision text,p_version text,p_filter_version bigint,p_patch jsonb,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare e machimoa_review.admin_exclusion_episodes%rowtype; d jsonb;
begin
 if machimoa_review.admin_trash_pending(p_id,p_revision) then
   perform machimoa_review.admin_trash_lock(p_id,p_revision,p_actor);
   d:=public.admin_content_filter_detail(p_id);
   if d->>'version' is distinct from p_version or (d->>'filterVersion')::bigint is distinct from p_filter_version
     or d->>'revision' is distinct from p_revision then raise sqlstate 'PT409' using message='review_conflict';end if;
   select * into e from machimoa_review.admin_exclusion_episodes
   where source_item_id=p_id and revision_hash=p_revision and restored_at is not null and review_completed_at is null
   for update;
   if found then
     perform machimoa_review.admin_trash_reevaluate(e,p_actor);
     d:=public.admin_content_filter_detail(p_id);
     p_version:=d->>'version';
     -- If evaluation changed a filter value, reject the original draft.
     if (d->>'filterVersion')::bigint is distinct from p_filter_version then
       raise sqlstate 'PT409' using message='review_conflict';
     end if;
   end if;
 end if;
 return machimoa_review.admin_filter_save_before_restore_flow(p_id,p_revision,p_version,p_filter_version,p_patch,p_actor);
end $$;
revoke all on function public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_content_filter_save(uuid,text,text,bigint,jsonb,uuid) to service_role;

commit;
