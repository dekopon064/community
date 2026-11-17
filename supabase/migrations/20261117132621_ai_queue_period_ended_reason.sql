begin;
-- Only the operator's exclusion reason is recorded. Source application facts stay intact.
alter table machimoa_review.admin_exclusion_episodes
  drop constraint admin_exclusion_episodes_reason_code_check,
  add constraint admin_exclusion_episodes_reason_code_check check (reason_code in ('service_not_suitable','region_not_suitable','period_ended','online_application_ended','custom'));
alter table machimoa_review.ai_recheck_receipts
  drop constraint ai_recheck_receipts_reason_code_check,
  add constraint ai_recheck_receipts_reason_code_check check (reason_code in ('service_not_suitable','region_not_suitable','period_ended','online_application_ended'));
CREATE OR REPLACE FUNCTION public.admin_review_exclude_reason(p_id uuid, p_revision text, p_version text, p_reason text, p_note text, p_actor uuid, p_request uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype;e machimoa_review.admin_exclusion_episodes%rowtype;
 r machimoa_review.admin_exclusion_requests%rowtype;stamp timestamptz;v_memo text;before_item jsonb;result jsonb;input jsonb;jobs jsonb;decisions jsonb;
begin
 if p_request is null or p_version is null or p_version!~'^[a-f0-9]{64}$' or p_reason is null or p_reason not in ('service_not_suitable','region_not_suitable','period_ended','custom') then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 perform machimoa_review.admin_trash_lock(p_id,p_revision,p_actor);
 select * into s from machimoa_review.source_items where id=p_id;
 v_memo:=case p_reason when 'service_not_suitable' then '서비스에 적합하지 않음' when 'region_not_suitable' then '대상 지역이 아님' when 'period_ended' then '기간·신청 종료'
   else btrim(p_note) end;
 if v_memo is null or char_length(v_memo) not between 1 and (case when s.source_id in ('seoul_reservation','myseoul_program') then 4000 else 500 end)
 or (p_reason<>'custom' and coalesce(p_note,'')<>'') then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 input:=jsonb_build_array('exclude',p_id,p_revision,p_version,p_reason,v_memo);
 select * into r from machimoa_review.admin_exclusion_requests where request_id=p_request;
 if found then
   if r.actor<>p_actor or r.input<>input then raise sqlstate 'PT422' using message='review_invalid_input';end if;
   if not exists(select 1 from machimoa_review.admin_exclusion_episodes where id=r.episode_id and restored_at is null) then raise sqlstate 'PT409' using message='review_conflict';end if;
   return r.response;
 end if;
 before_item:=case when s.source_id='myseoul_program' then public.admin_myseoul_program_detail(p_id) when s.source_id='seoul_reservation' then public.admin_program_detail(p_id) else machimoa_review.admin_review_item('facts',p_id) end;
 if before_item->>'version' is distinct from p_version then raise sqlstate 'PT409' using message='review_conflict';end if;
 select coalesce(jsonb_agg(to_jsonb(j)),'[]') into jobs from machimoa_review.processing_jobs j where source_item_id=p_id and revision_hash=p_revision;
 select coalesce(jsonb_agg(to_jsonb(d)),'[]') into decisions from machimoa_review.ingest_review_decisions d where source_item_id=p_id and revision_hash=p_revision;
 if s.source_id='myseoul_program' then perform machimoa_review.admin_myseoul_exclude_before_trash(p_id,p_revision,p_version,v_memo,p_actor);
 elsif s.source_id='seoul_reservation' then perform machimoa_review.admin_program_exclude_before_trash(p_id,p_revision,p_version,v_memo,p_actor);
 else perform machimoa_review.admin_review_exclude_before_trash(p_id,p_revision,p_version,v_memo,p_actor);end if;
 update machimoa_review.admin_exclusion_episodes set review_completed_at=clock_timestamp() where source_item_id=p_id and revision_hash=p_revision and restored_at is not null and review_completed_at is null;
 update machimoa_review.ingest_review_decisions set revoked_at=null where source_item_id=p_id and revision_hash=p_revision and decision='reject' and 'manual_non_target'=any(reason_codes) and reviewer=p_actor::text and ingest_review_decisions.memo=v_memo;
 -- Exclusion closes a deliberate hold in the SAME transaction. Keep the original hold history.
 update machimoa_review.ai_rechecks set completed_at=clock_timestamp() where source_item_id=p_id and revision_hash=p_revision and completed_at is null;
 stamp:=clock_timestamp();
 insert into machimoa_review.admin_exclusion_episodes(source_item_id,revision_hash,source_name,title,reason_code,note,actor,excluded_at,expires_at,prior_jobs,prior_decisions,decision_ids)
 values(p_id,p_revision,s.source_id,coalesce(before_item->'source'->>'title','제목 확인 필요'),p_reason,v_memo,p_actor,stamp,stamp+interval '72 hours',jobs,decisions,
   array(select id from machimoa_review.ingest_review_decisions where source_item_id=p_id and revision_hash=p_revision and decision='reject' and 'manual_non_target'=any(reason_codes) and reviewer=p_actor::text and ingest_review_decisions.memo=v_memo)) returning * into e;
 result:=jsonb_build_object('episodeId',e.id,'expiresAt',e.expires_at,'item',case when s.source_id='myseoul_program' then public.admin_myseoul_program_detail(p_id) when s.source_id='seoul_reservation' then public.admin_program_detail(p_id) else machimoa_review.admin_review_item('facts',p_id) end);
 insert into machimoa_review.admin_exclusion_requests values(p_request,p_actor,input,e.id,result,stamp);
 return result;
end $function$
;

create or replace function public.admin_ai_queue_exclude(p_job_id uuid,p_revision text,p_version text,p_request_id uuid,p_reason text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;r machimoa_review.ai_recheck_receipts%rowtype;d jsonb;native jsonb;outcome jsonb;legacy text;begin
 if p_job_id is null or p_request_id is null or p_actor is null or p_revision is null or p_revision!~'^[a-f0-9]{64}$'
 or p_version is null or p_version!~'^[a-f0-9]{64}$' or p_reason is null or p_reason not in ('service_not_suitable','region_not_suitable','period_ended') then raise sqlstate 'PT422' using message='invalid_recheck_exclude';end if;
 perform pg_advisory_xact_lock(hashtextextended('ai-recheck-request:'||p_request_id::text,0));
 select * into r from machimoa_review.ai_recheck_receipts where request_id=p_request_id;
 if found then
 if r.job_id is distinct from p_job_id or r.action<>'exclude' or r.revision is distinct from p_revision or r.expected_version is distinct from p_version
 or r.actor is distinct from p_actor or r.reason_code is distinct from p_reason then raise sqlstate 'PT409' using message='request_id_conflict';end if;
 return r.response;end if;
 select * into j from machimoa_review.processing_jobs where id=p_job_id and processing_stage='ai_enrichment';
 if not found then raise sqlstate 'PT404' using message='ai_job_not_found';end if;
 select * into s from machimoa_review.source_items where id=j.source_item_id for update;
 if s.revision_hash is distinct from p_revision or j.revision_hash is distinct from p_revision then raise sqlstate 'PT409' using message='source_revision_conflict';end if;
 perform 1 from machimoa_review.source_item_program_facts where source_item_id=s.id and revision_hash=p_revision for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=s.id order by revision_hash,processing_stage for update;
 select legacy_curation_source into legacy from machimoa_review.ingest_sources where source_id=s.source_id for share;
 if legacy is null then raise sqlstate 'PT409' using message='source_contract_missing';end if;
 perform pg_advisory_xact_lock(hashtextextended(legacy||':'||s.external_key,0));
 perform 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key for update;
 d:=public.admin_ai_queue_review_detail(p_job_id);
 if d->>'version' is distinct from p_version or d->>'canExclude'<>'true' then raise sqlstate 'PT409' using message='recheck_exclude_conflict';end if;
 native:=d->'review';
 perform public.admin_review_exclude_reason(s.id,p_revision,native->>'version',p_reason,'',p_actor,p_request_id);
 outcome:=public.admin_ai_queue_review_detail(p_job_id);
 insert into machimoa_review.ai_recheck_receipts(request_id,job_id,action,revision,expected_version,actor,note,reason_code,response)
 values(p_request_id,p_job_id,'exclude',p_revision,p_version,p_actor,'',p_reason,outcome);
 return outcome;
end $$;
commit;
