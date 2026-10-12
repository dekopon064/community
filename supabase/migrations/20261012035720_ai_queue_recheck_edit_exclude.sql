begin;
set local lock_timeout='5s';set local statement_timeout='30s';
-- Local additive contract. No backfill, collection, AI or candidate/content writes.

do $$ declare r record;f record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 for r in select * from (values ('public.admin_program_detail(uuid)','9878f867470debaf110d825e596eac53215d29668db7bc13e94b20d8414ceda6',true,true),
('public.admin_myseoul_program_detail(uuid)','f24d143b3e57d74e9455d813771a00cea89b1592382b608e23fd8f8c9f6b0ba9',true,true),
('public.admin_program_save(uuid,text,text,jsonb,text[],text,uuid)','76e440e025037fef5a3774476ab78b22ec818b2d7578a3a97fb5080505454a8b',true,true),
('public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid)','6893a3debf5321edf8426fc06b27a8c61a1419e0e7fcea87e289714e82409835',true,true),
('machimoa_review.admin_review_item(text,uuid)','12a3edb6569ee665e5752fd660764e03290ccc7f2cfe8796358d3c6dc6a1e76e',true,false),
('public.admin_review_save_facts(uuid,text,text,jsonb,uuid)','5d0514031e49d345f16586feb2b7799423e266338c4a3326b8ea1d7642e5dae8',true,true),
('public.admin_review_exclude_reason(uuid,text,text,text,text,uuid,uuid)','c8cf4963a8febfae571868f7626174d49a07e1f1b89e153bae921aaf903f201b',true,true),
('machimoa_review.ai_recheck_command(uuid,text,text,uuid,text,uuid,text)','5b104167d41a3498e2d76f4205e3f43078c1e7f7b12c3d35dc5d1f4b2b7c226d',true,false),
('public.admin_ai_queue_review_detail(uuid)','81fdcbbd36b79b4f3d94321e98c19e683ec2199fb13e6eba64b513fdba28c9e8',true,true),
('machimoa_review.admin_program_exclude_before_trash(uuid,text,text,text,uuid)','c7b5ca982138b5cff71524e267201fdd3c1fa9af67833461f33e2aeda30ad616',true,false),
('machimoa_review.admin_myseoul_exclude_before_trash(uuid,text,text,text,uuid)','31242bcebf5002945e26d0764ba2d0d4902adfa4d2fb623f4141f9bb9cef7519',true,false),
('machimoa_review.admin_review_exclude_before_trash(uuid,text,text,text,uuid)','73f1dfaa568a1e3afaac7174f39f705e39a5e61f065524836dce81fcb5f54147',true,false)) x(signature,hash,definer,service) loop
 select * into f from pg_proc where oid=to_regprocedure(r.signature);
 if f.oid is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(f.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>r.hash
 or pg_get_userbyid(f.proowner)<>'postgres' or f.proconfig is distinct from array['search_path=""']::text[] or f.prosecdef is distinct from r.definer
 or f.proacl::text is distinct from (case when r.service then '{postgres=X/postgres,service_role=X/postgres}' else '{postgres=X/postgres}' end)
 then raise exception 'ai_recheck_edit_predecessor_changed: %',r.signature;end if;
 end loop;
end $$;
alter table machimoa_review.ai_rechecks drop constraint ai_rechecks_note_check;
alter table machimoa_review.ai_rechecks add constraint ai_rechecks_note_check check(char_length(note)<=1000);
alter table machimoa_review.ai_recheck_receipts drop constraint ai_recheck_receipts_note_check;
alter table machimoa_review.ai_recheck_receipts add constraint ai_recheck_receipts_note_check check(char_length(btrim(note))<=1000);
alter table machimoa_review.ai_recheck_receipts drop constraint ai_recheck_receipts_action_check;
alter table machimoa_review.ai_recheck_receipts add constraint ai_recheck_receipts_action_check check(action in ('request_recheck','complete_recheck','exclude'));
alter table machimoa_review.ai_recheck_receipts add column reason_code text check(reason_code in ('service_not_suitable','region_not_suitable'));
-- The event remains required (actor/time/revision/request), only the user's note is optional.
-- Shared with UI patch whitelists; raw observations/schema/diagnostic flags remain immutable.
create function machimoa_review.ai_recheck_edit_fields(p_source text) returns text[]
language sql immutable security definer set search_path='' as $$
 select case p_source
 when 'seoul_reservation' then array['content_kind','application_actor','delivery_mode','activity_region','activity_evidence','residence_scope','residence_evidence','target_raw','conditions','application_methods','fee_kind','fee_amounts','source_status','period_evidence','periods','official_url','description']
 when 'myseoul_program' then array['description','target','conditions','application_actor','delivery_mode','activity_region','venue','residence_scope','residence','residence_evidence','public_category','purpose','qualification_note','periods','session_evidence','application_methods','application_links','fees','source_status']
 when 'youthcenter_policy' then array['productType','category','scope','regions','evidence','foreignEligibility','delivery','deadlineKind','deadlineOn','eventStart','eventEnd']
 when 'youthcenter_content' then array['productType','category','scope','regions','evidence','foreignEligibility','delivery','deadlineKind','deadlineOn','eventStart','eventEnd']
 else '{}'::text[] end
$$;
-- Called AFTER the existing source -> facts -> jobs locks. Do not relax native validators.
create function machimoa_review.ai_recheck_edit_guard(p_id uuid,p_revision text) returns void
language plpgsql security definer set search_path='' as $$
declare s machimoa_review.source_items%rowtype;legacy text;begin
 if not machimoa_review.ai_recheck_pending(p_id,p_revision) then return;end if;
 select * into s from machimoa_review.source_items where id=p_id;
 select legacy_curation_source into legacy from machimoa_review.ingest_sources where source_id=s.source_id for share;
 if legacy is null then raise sqlstate 'PT409' using message='source_contract_missing';end if;
 perform pg_advisory_xact_lock(hashtextextended(legacy||':'||s.external_key,0));
 perform 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key for update;
 if s.revision_hash is distinct from p_revision or s.disposition='non_target'
 or exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed')
 or exists(select 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key)
 then raise sqlstate 'PT409' using message='recheck_edit_conflict';end if;
end $$;

CREATE OR REPLACE FUNCTION public.admin_program_detail(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare d jsonb;begin
 d:=machimoa_review.ai_recheck_base_program_detail(p_id);
 if d->>'status'<>'excluded' and machimoa_review.ai_recheck_pending(p_id,d->>'revision') then
  d:=d||jsonb_build_object('editableFields',to_jsonb(machimoa_review.ai_recheck_edit_fields('seoul_reservation')),'status','open','result',(d->'result')||jsonb_build_object('reasons',coalesce(d->'result'->'reasons','[]')||jsonb_build_array('ai_recheck_requested')));
 end if;return d;
end $function$
;

CREATE OR REPLACE FUNCTION public.admin_myseoul_program_detail(p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare d jsonb;begin
 d:=machimoa_review.ai_recheck_base_myseoul_detail(p_id);
 if d->>'status'<>'excluded' and machimoa_review.ai_recheck_pending(p_id,d->>'revision') then
  d:=d||jsonb_build_object('editableFields',to_jsonb(machimoa_review.ai_recheck_edit_fields('myseoul_program')),'status','open','result',(d->'result')||jsonb_build_object('reasons',coalesce(d->'result'->'reasons','[]')||jsonb_build_array('ai_recheck_requested')));
 end if;return d;
end $function$
;

CREATE OR REPLACE FUNCTION machimoa_review.admin_review_item(p_kind text, p_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare item jsonb;info jsonb;sid uuid;rev text;begin
 item:=machimoa_review.cf_base_admin_review_item(p_kind,p_id);sid:=machimoa_review.admin_review_source(p_kind,p_id);
 select revision_hash into rev from machimoa_review.source_items where id=sid;
 if p_kind='facts' then
 info:=machimoa_review.content_filter_info(sid,rev);
 if info is not null then item:=item||jsonb_build_object('filterInfo',info);
 if item->>'status'<>'excluded' and jsonb_array_length(info->'missing')>0 then item:=item||jsonb_build_object('status','open','aiStatus','blocked');end if;end if;
 else
 info:=machimoa_review.content_filter_candidate_info(p_id);
 if info is not null then item:=item||jsonb_build_object('filterInfo',info);
 if item ? 'programInfo' and not (info->>'canPublish')::boolean then item:=jsonb_set(item,array['programInfo','canPublish'],'false');end if;end if;
 end if;
 if p_kind='facts' and item->>'status'<>'excluded' and machimoa_review.ai_recheck_pending(sid,rev) then
 item:=item||jsonb_build_object('status','open','aiStatus','cancelled','editableFields',to_jsonb(machimoa_review.ai_recheck_edit_fields(item->'source'->>'name')),
 'reasons',coalesce(item->'reasons','[]')||jsonb_build_array('ai_recheck_requested'));
 end if;return item;
end
$function$
;

CREATE OR REPLACE FUNCTION public.admin_program_save(p_id uuid, p_revision text, p_version text, p_patch jsonb, p_resolve text[], p_note text, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; item jsonb;
 next_facts jsonb; field text; reason text; allowed text[]:='{}'; active text[]; changed text[]:='{}'; d jsonb;
begin
 if p_actor is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or p_version is null or p_version !~ '^[a-f0-9]{64}$'
 or p_patch is null or jsonb_typeof(p_patch)<>'object' or p_resolve is null or cardinality(p_resolve)>30
 or char_length(btrim(coalesce(p_note,''))) not between 1 and 4000 then
 raise exception using errcode='PT422',message='invalid_program_command';end if;
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation' for update;
 if not found then raise exception using errcode='PT404',message='program_not_found';end if;
 if s.revision_hash<>p_revision then raise exception using errcode='PT409',message='source_revision_conflict';end if;
 select * into f from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=p_revision for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 perform 1 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 item:=public.admin_program_detail(p_id);
 if item->>'version'<>p_version then raise exception using errcode='PT409',message='program_version_conflict';end if;
 if item->>'status'<>'open' or not exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage='content_review' and status='queued') then
 raise exception using errcode='PT409',message='program_already_processed';end if;
 if exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and status='claimed') then
 raise exception using errcode='PT409',message='program_processing_active';end if;
 perform machimoa_review.ai_recheck_edit_guard(p_id,p_revision);
 if machimoa_review.ai_recheck_pending(p_id,p_revision) then allowed:=machimoa_review.ai_recheck_edit_fields(s.source_id);end if;
 active:=array(select jsonb_array_elements_text(f.result->'reasons'));
 foreach reason in array active loop allowed:=allowed||machimoa_review.program_reason_fields(reason);end loop;
 for field in select jsonb_object_keys(p_patch) loop
   if not field=any(allowed) then raise exception using errcode='PT422',message='program_field_read_only';end if;
   if p_patch->field is distinct from f.facts->field then changed:=array_append(changed,field);end if;
 end loop;
 if cardinality(changed)=0 then raise exception using errcode='PT422',message='program_change_required';end if;
 next_facts:=f.facts||p_patch;
 foreach reason in array p_resolve loop
   if reason is null or not reason=any(active) or not (changed && machimoa_review.program_reason_fields(reason)) then
   raise exception using errcode='PT422',message='program_reason_not_resolved';end if;
   next_facts:=jsonb_set(next_facts,'{missing}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_facts->'missing') where value#>>'{}'<>reason),'[]'));
   next_facts:=jsonb_set(next_facts,'{conflicts}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_facts->'conflicts') where value#>>'{}'<>reason),'[]'));
 end loop;
 perform machimoa_review.program_validate(next_facts);
 -- A resolution must supply actual facts, not merely remove a diagnostic flag.
 if next_facts->>'official_url'='' and 'missing_source_url'=any(p_resolve) or
 char_length(btrim(next_facts->>'description'))<20 and p_resolve && array['attachment_dependent','program_description_missing'] or
 next_facts->'activity_evidence'='[]'::jsonb and p_resolve && array['activity_location_unknown','delivery_mode_unknown'] or
 next_facts->'residence_evidence'='[]'::jsonb and 'residence_scope_unknown'=any(p_resolve) or
 next_facts->'period_evidence'='[]'::jsonb and p_resolve && array['body_period_needs_confirmation','date_weekday_conflict','body_api_period_conflict','invalid_body_date'] then
 raise exception using errcode='PT422',message='program_evidence_required';end if;
 if p_resolve && array['period_missing_or_unparsed','period_order_conflict','body_period_needs_confirmation','date_weekday_conflict','body_api_period_conflict','invalid_body_date'] then
   for d in select value from jsonb_each(next_facts->'periods') loop
     if d->>'status'<>'ok' then raise exception using errcode='PT422',message='period_still_missing';end if;
   end loop;
   if machimoa_review.program_evaluate(next_facts,clock_timestamp())->'reasons' ? 'period_order_conflict' then
     raise exception using errcode='PT422',message='invalid_period_order';end if;
 end if;
 update machimoa_review.source_item_program_facts set facts=next_facts,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'save_facts',p_actor,p_note,changed||array(select 'resolved:'||x from unnest(p_resolve) x));
 perform machimoa_review.program_refresh(p_id);
 return public.admin_program_detail(p_id);
end $function$
;

CREATE OR REPLACE FUNCTION public.admin_myseoul_program_save_v2(p_id uuid, p_revision text, p_version text, p_patch jsonb, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
<<myseoul_save>>
declare item jsonb; f jsonb; candidate jsonb; r text; k text; axis text; v text; result jsonb;
 changed text[]:='{}'; resolved text[]:='{}'; submitted text[]; before_patch jsonb:='{}'; after_patch jsonb:='{}'; event_id bigint;
begin
 if p_patch is null or jsonb_typeof(p_patch)<>'object' or (p_patch='{}'::jsonb and not machimoa_review.admin_trash_pending(p_id,p_revision)) or octet_length(p_patch::text)>200000 then
 raise exception using errcode='PT422',message='invalid_myseoul_command';end if;
 item:=machimoa_review.myseoul_admin_lock(p_id,p_revision,p_version,p_actor);
 perform machimoa_review.ai_recheck_edit_guard(p_id,p_revision);
 f:=item->'facts';
 submitted:=array(select jsonb_object_keys(p_patch));
 foreach k in array submitted loop
 if not (item->'editableFields') ? k or k='activity_evidence' then
 raise exception using errcode='PT422',message='myseoul_field_read_only';end if;
 before_patch:=before_patch||jsonb_build_object(k,f->k);
 if k='periods' then
 if jsonb_typeof(p_patch->k)<>'object' or p_patch->k='{}'::jsonb or
 exists(select 1 from jsonb_object_keys(p_patch->k) a where a not in ('application','operation')) then
 raise exception using errcode='PT422',message='invalid_myseoul_periods';end if;
 for axis in select jsonb_object_keys(p_patch->'periods') loop
 if not machimoa_review.ai_recheck_pending(p_id,p_revision) and not exists(select 1 from jsonb_array_elements_text(item->'result'->'reasons') q(reason)
 where q.reason in (axis||'_period_unknown','source_fact_conflict:'||axis,'source_change_conflict:'||axis,
 'source_change_conflict:periods','application_state_unknown','source_fact_conflict:status')) then
 raise exception using errcode='PT422',message='myseoul_period_axis_read_only';end if;end loop;
 f:=jsonb_set(f,'{periods}',(f->'periods')||(p_patch->'periods'));
 else f:=jsonb_set(f,array[k],p_patch->k);end if;
 if f->k is distinct from item->'facts'->k then changed:=array_append(changed,k);end if;
 after_patch:=after_patch||jsonb_build_object(k,f->k);
 end loop;

 -- Reuse saved source evidence, never manufacture a source quote from a choice.
 -- The original observedFacts/evidence/conflicts remain unchanged.
 if submitted && array['delivery_mode','venue','activity_region'] then
 for v in select e->>'value' from jsonb_array_elements(item->'facts'->'evidence') e
 where e->>'field' in ('mode','venue') union
 select line from regexp_split_to_table(item->'source'->>'body',E'\n') line
 where btrim(f->>'venue')<>'' and position(f->>'venue' in line)>0 loop
 if char_length(v) between 1 and 4000 and not (f->'activity_evidence') ? v then
 f:=jsonb_set(f,'{activity_evidence}',f->'activity_evidence'||jsonb_build_array(v));end if;
 end loop;end if;
 perform machimoa_review.myseoul_validate(f);
 -- Insert the server audit in this same transaction before scoped evaluation.
 -- Only a complete, valid three-field submission can confirm a venue.
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'save_facts',p_actor,'사실 확인 저장 · 시스템 처리 기록',changed) returning id into event_id;
 insert into machimoa_review.myseoul_fact_edits(event_id,before_patch,after_patch,activity_confirmed)
 values(event_id,before_patch,after_patch,
 submitted @> array['delivery_mode','activity_region','venue'] and
 f->>'delivery_mode' in ('offline','mixed') and f->>'activity_region'='capital' and btrim(f->>'venue')<>'');


 -- Submitted fields are a scoped confirmation, including an unchanged value.
 -- No client resolve list; period axes and fee components stay independent.
 for r in select jsonb_array_elements_text(item->'result'->'reasons') loop
 if not submitted && machimoa_review.myseoul_reason_fields(r) then continue;end if;
 axis:=case when r in ('application_period_unknown','source_fact_conflict:application','source_change_conflict:application') then 'application'
 when r in ('operation_period_unknown','source_fact_conflict:operation','source_change_conflict:operation') then 'operation' end;
 if axis is not null and not coalesce((p_patch->'periods') ? axis,false) then continue;end if;
 if r='source_fact_conflict:mode' and not p_patch ? 'delivery_mode' or
 r='source_fact_conflict:venue' and not p_patch ? 'venue' then continue;end if;
 if r='nationality_or_visa_unresolved' and char_length(btrim(f->>'qualification_note'))<10 then continue;end if;
 if r='category_unresolved' and char_length(btrim(f->>'purpose'))<10 then continue;end if;
 if r='fee_components_unresolved' and exists(select 1 from jsonb_array_elements(f->'fees') fee
 where fee->>'component'='extra_fee' and exists(select 1 from jsonb_array_elements_text(fee->'evidence') value
 where (value ~ '수강료' and value ~ '입장료') or (value ~ '재료비' and value ~ '입장료') or (value ~ '수강료' and value ~ '재료비'))) then continue;end if;
 candidate:=jsonb_set(f,'{issues}',coalesce((select jsonb_agg(value) from jsonb_array_elements(f->'issues') where value->>'code'<>r),'[]'::jsonb));
 result:=machimoa_review.myseoul_evaluate(candidate,clock_timestamp());
 if not (result->'reasons') ? r then
 f:=candidate;resolved:=array_append(resolved,r);end if;
 end loop;
 if cardinality(changed)=0 and cardinality(resolved)=0 and not machimoa_review.admin_trash_pending(p_id,p_revision) then
 raise exception using errcode='PT422',message='myseoul_no_resolved_fact';end if;
 if f->'activity_evidence' is distinct from item->'facts'->'activity_evidence' then
 before_patch:=before_patch||jsonb_build_object('activity_evidence',item->'facts'->'activity_evidence');
 after_patch:=after_patch||jsonb_build_object('activity_evidence',f->'activity_evidence');end if;
 update machimoa_review.source_item_program_facts set facts=f,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 update machimoa_review.admin_review_events
 set changed_fields=changed||array(select 'resolved:'||q.code from unnest(resolved) q(code)) where id=event_id;
 update machimoa_review.myseoul_fact_edits x
 set before_patch=myseoul_save.before_patch,after_patch=myseoul_save.after_patch
 where x.event_id=myseoul_save.event_id;
 update machimoa_review.admin_exclusion_episodes set review_completed_at=clock_timestamp() where source_item_id=p_id and revision_hash=p_revision and restored_at is not null and review_completed_at is null;
 perform machimoa_review.myseoul_refresh(p_id);
 return public.admin_myseoul_program_detail(p_id);
end $function$
;

CREATE OR REPLACE FUNCTION public.admin_review_save_facts(p_id uuid, p_revision text, p_version text, p_facts jsonb, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare item jsonb;begin
 perform machimoa_review.admin_review_lock('facts',p_id,p_revision,p_version,p_actor);
 perform machimoa_review.ai_recheck_edit_guard(p_id,p_revision);
 item:=machimoa_review.cf_base_pub_admin_review_save_facts(p_id,p_revision,p_version,p_facts,p_actor);
 perform machimoa_review.content_filter_after_facts(p_id,p_revision);
 return machimoa_review.admin_review_item('facts',p_id);
end
$function$
;

CREATE OR REPLACE FUNCTION public.admin_review_exclude_reason(p_id uuid, p_revision text, p_version text, p_reason text, p_note text, p_actor uuid, p_request uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype;e machimoa_review.admin_exclusion_episodes%rowtype;
 r machimoa_review.admin_exclusion_requests%rowtype;stamp timestamptz;v_memo text;before_item jsonb;result jsonb;input jsonb;jobs jsonb;decisions jsonb;
begin
 if p_request is null or p_version is null or p_version!~'^[a-f0-9]{64}$' or p_reason is null or p_reason not in ('service_not_suitable','region_not_suitable','custom') then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 perform machimoa_review.admin_trash_lock(p_id,p_revision,p_actor);
 select * into s from machimoa_review.source_items where id=p_id;
 v_memo:=case p_reason when 'service_not_suitable' then '서비스에 적합하지 않음' when 'region_not_suitable' then '대상 지역이 아님' else btrim(p_note) end;
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

CREATE OR REPLACE FUNCTION machimoa_review.ai_recheck_command(p_job_id uuid, p_revision text, p_version text, p_request_id uuid, p_note text, p_actor uuid, p_action text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;
 p machimoa_review.source_item_product_types%rowtype;c machimoa_review.review_classifications%rowtype;codes text[];remaining text[];d jsonb;outcome jsonb;receipt machimoa_review.ai_recheck_receipts%rowtype;legacy text;
begin
 if p_job_id is null or p_request_id is null or p_actor is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$'
 or p_version is null or p_version !~ '^[a-f0-9]{64}$' or p_note is null or char_length(btrim(p_note))>1000
 or p_action is null or p_action not in ('request_recheck','complete_recheck') then raise sqlstate 'PT422' using message='invalid_recheck';end if;
 -- Serialize receipt keys, then lock source -> facts -> jobs -> permission ->
 -- existing canonical candidate fence. Checks happen after the locks.
 perform pg_advisory_xact_lock(hashtextextended('ai-recheck-request:'||p_request_id::text,0));
 select * into receipt from machimoa_review.ai_recheck_receipts where request_id=p_request_id;
 if found then
  if receipt.job_id is distinct from p_job_id or receipt.action is distinct from p_action or receipt.revision is distinct from p_revision
  or receipt.expected_version is distinct from p_version or receipt.actor is distinct from p_actor or receipt.note is distinct from btrim(p_note) or receipt.reason_code is not null
  then raise sqlstate 'PT409' using message='request_id_conflict';end if;
  return receipt.response;
 end if;
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
 if d->>'version' is distinct from p_version or exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and status='claimed')
 or exists(select 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key)
 or p_action='request_recheck' and s.disposition='non_target' then raise sqlstate 'PT409' using message='recheck_conflict';end if;
 if p_action='request_recheck' then
  if d->>'canRecheck'<>'true' then raise sqlstate 'PT409' using message='recheck_conflict';end if;
  insert into machimoa_review.ai_rechecks(id,job_id,source_item_id,revision_hash,actor,note) values(p_request_id,p_job_id,s.id,p_revision,p_actor,btrim(p_note));
  update machimoa_review.processing_jobs set status='cancelled',completed_at=clock_timestamp() where id=p_job_id;
  insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
  values(s.id,p_revision,'content_review','queued',clock_timestamp(),clock_timestamp(),array['ai_recheck_requested'])
  on conflict(source_item_id,revision_hash,processing_stage) do update set status='queued',completed_at=null,
   reason_codes=(case when machimoa_review.processing_jobs.status='queued' then machimoa_review.processing_jobs.reason_codes else '{}'::text[] end)||array['ai_recheck_requested'];
 else
  if d->>'recheckPending'<>'true' or d->>'status'<>'cancelled' then raise sqlstate 'PT409' using message='recheck_conflict';end if;
  select array_remove(reason_codes,'ai_recheck_requested') into remaining from machimoa_review.processing_jobs
   where source_item_id=s.id and revision_hash=p_revision and processing_stage='content_review' and status='queued';
  remaining:=coalesce(remaining,'{}');
  update machimoa_review.ai_rechecks set completed_at=clock_timestamp() where job_id=p_job_id and completed_at is null;
  update machimoa_review.processing_jobs set status='completed',completed_at=clock_timestamp(),reason_codes=array_remove(reason_codes,'ai_recheck_requested')
  where source_item_id=s.id and revision_hash=p_revision and processing_stage='content_review';
  -- Re-evaluate actual facts/filters/time/permission. No forced AI-ready status.
  select * into c from machimoa_review.review_classifications where source_item_id=s.id and revision_hash=p_revision for update;
  if found then
   -- The target classification remains authoritative. Never overwrite its facts,
   -- filters or native snapshot with the native source evaluator.
   codes:=machimoa_review.classification_reasons(s.id,c.facts);
   if c.native_snapshot is distinct from machimoa_review.classification_native(s.id) then codes:=array_append(codes,'classification_input_changed');end if;
   update machimoa_review.processing_jobs set status=case when cardinality(codes)=0 then 'completed' else 'queued' end,
    completed_at=case when cardinality(codes)=0 then clock_timestamp() else null end,reason_codes=codes
    where source_item_id=s.id and revision_hash=p_revision and processing_stage='content_review';
   if machimoa_review.classification_ready(s.id) then
    update machimoa_review.processing_jobs set status='queued',completed_at=null where id=p_job_id;
   end if;
  elsif s.source_id='seoul_reservation' then perform machimoa_review.program_refresh(s.id);
  elsif s.source_id='myseoul_program' then perform machimoa_review.myseoul_refresh(s.id);
  else
   select * into p from machimoa_review.source_item_product_types where source_item_id=s.id and revision_hash=p_revision for update;
   if not found then raise sqlstate 'PT409' using message='facts_missing';end if;
   perform machimoa_review.apply_source_item_evaluation(s.id,p_revision,p.product_type,coalesce(p.reason_codes,'{}'),p.gate_facts);
  end if;
  -- Completion removes only the deliberate hold. Reasons still pending after
  -- the last formal fact save cannot be silently cleared by clicking complete.
  if cardinality(remaining)>0 and exists(select 1 from machimoa_review.source_items where id=s.id and disposition<>'non_target') then
   update machimoa_review.processing_jobs set status='queued',completed_at=null,
    reason_codes=array(select distinct r from unnest(reason_codes||remaining) r order by r)
    where source_item_id=s.id and revision_hash=p_revision and processing_stage='content_review';
  end if;
  -- A native facts refresh can queue before its filter review sync. Only a fully
  -- ready current input may remain queued; no reason/permission bypass here.
  if exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and revision_hash=p_revision and processing_stage<>'ai_enrichment' and status in ('queued','claimed'))
   or exists(select 1 from machimoa_review.source_items where id=s.id and disposition='non_target')
   or not exists(select 1 from machimoa_review.ingest_sources where source_id=s.source_id and enabled and permission_status in ('approved_noncommercial','approved_commercial'))
   or c.source_item_id is null and not machimoa_review.content_filter_ready(s.id,p_revision)
  then
   update machimoa_review.processing_jobs set status='cancelled',completed_at=clock_timestamp() where id=p_job_id and status='queued';
  end if;
 end if;
 outcome:=public.admin_ai_queue_review_detail(p_job_id);
 insert into machimoa_review.ai_recheck_receipts(request_id,job_id,action,revision,expected_version,actor,note,response) values(p_request_id,p_job_id,p_action,p_revision,p_version,p_actor,btrim(p_note),outcome);
 return outcome;
end $function$
;

CREATE OR REPLACE FUNCTION public.admin_ai_queue_review_detail(p_job_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;
 d jsonb;h jsonb;permission jsonb;classification jsonb;ready boolean;exclude_ready boolean;
begin
 select * into j from machimoa_review.processing_jobs where id=p_job_id and processing_stage='ai_enrichment';
 if not found then raise sqlstate 'PT404' using message='ai_job_not_found';end if;
 select * into s from machimoa_review.source_items where id=j.source_item_id;
 if s.revision_hash is distinct from j.revision_hash then raise sqlstate 'PT409' using message='source_revision_conflict';end if;
 if s.source_id='seoul_reservation' then d:=public.admin_program_detail(s.id);
 elsif s.source_id='myseoul_program' then d:=public.admin_myseoul_program_detail(s.id);
 elsif s.source_id in ('youthcenter_policy','youthcenter_content') then d:=public.admin_review_detail('facts',s.id);
 else raise sqlstate 'PT409' using message='unsupported_source';end if;
 classification:=public.admin_review_classification_detail(s.id);
 if classification->>'active'<>'true' then classification:=null;end if;
 select to_jsonb(r) into h from machimoa_review.ai_rechecks r where r.job_id=j.id and r.completed_at is null;
 select jsonb_build_object('enabled',enabled,'permission',permission_status,'legacy',legacy_curation_source) into permission
 from machimoa_review.ingest_sources where source_id=s.source_id;
 ready:=j.status='queued' and j.retry_count=0 and j.next_retry_at is null and j.claimed_at is null
 and j.claimed_by is null and j.claim_lease_until is null and h is null and s.disposition<>'non_target'
 and permission->>'enabled'='true' and permission->>'permission' in ('approved_noncommercial','approved_commercial')
 and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and status='claimed')
 and not exists(select 1 from machimoa_review.curation_candidates c where machimoa_review.canonical_source_id(c.source)=s.source_id and c.source_item_id=s.external_key);
 exclude_ready:=(ready or h is not null and j.status='cancelled') and s.disposition<>'non_target'
 and not exists(select 1 from machimoa_review.processing_jobs where source_item_id=s.id and status='claimed')
 and not exists(select 1 from machimoa_review.curation_candidates c where machimoa_review.canonical_source_id(c.source)=s.source_id and c.source_item_id=s.external_key);
 return jsonb_build_object('jobId',j.id,'sourceItemId',s.id,'sourceName',s.source_id,'revision',s.revision_hash,
 'version',encode(sha256(convert_to(jsonb_build_array('ai-queue-recheck-v2',to_jsonb(j),d->>'version',classification->>'version',h,permission)::text,'UTF8')),'hex'),
 'status',j.status,'canRecheck',coalesce(ready,false),'canExclude',coalesce(exclude_ready,false),'recheckPending',h is not null,'note',coalesce(h->>'note',''),'review',d,'classification',classification);
end $function$
;


-- Native exclusion remains a formal trash transaction. A resolved fact review
-- may be excluded only when its current fresh AI queue DTO permits exclusion.
-- admin_trash_lock has already acquired source/facts/jobs/candidate locks.
create function machimoa_review.ai_queue_native_exclude_ready(p_id uuid,p_revision text,p_version text,p_actor uuid) returns boolean
language plpgsql stable security definer set search_path='' as $$
declare job uuid;d jsonb;begin
 if p_actor is null then return false;end if;
 select id into job from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage='ai_enrichment';
 if job is null then return false;end if;
 d:=public.admin_ai_queue_review_detail(job);
 return d->>'revision'=p_revision and d->'review'->>'version'=p_version and d->>'canExclude'='true';
end $$;
revoke all on function machimoa_review.ai_queue_native_exclude_ready(uuid,text,text,uuid) from public,anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION machimoa_review.admin_program_exclude_before_trash(p_id uuid, p_revision text, p_version text, p_note text, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype; item jsonb;
begin
 if p_actor is null or p_revision is null or p_version is null or char_length(btrim(coalesce(p_note,''))) not between 1 and 4000 then
 raise exception using errcode='PT422',message='invalid_program_command';end if;
 select * into s from machimoa_review.source_items where id=p_id and source_id='seoul_reservation' for update;
 if not found then raise exception using errcode='PT404',message='program_not_found';end if;
 perform 1 from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_id order by revision_hash,processing_stage for update;
 perform 1 from machimoa_review.ingest_sources where source_id=s.source_id for share;
 item:=public.admin_program_detail(p_id);
 if s.revision_hash<>p_revision or item->>'version'<>p_version then raise exception using errcode='PT409',message='program_version_conflict';end if;
 if (item->>'status'<>'open' or not exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage='content_review' and status='queued')) and not machimoa_review.ai_queue_native_exclude_ready(p_id,p_revision,p_version,p_actor) then
 raise exception using errcode='PT409',message='program_already_processed';end if;
 update machimoa_review.source_item_program_facts set manual_excluded=true,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'exclude',p_actor,p_note,array['service_scope']);
 perform machimoa_review.program_refresh(p_id);
 return public.admin_program_detail(p_id);
end $function$
;

CREATE OR REPLACE FUNCTION machimoa_review.admin_myseoul_exclude_before_trash(p_id uuid, p_revision text, p_version text, p_note text, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
 if char_length(btrim(coalesce(p_note,''))) not between 1 and 4000 then raise exception using errcode='PT422',message='invalid_myseoul_command';end if;
 if not machimoa_review.ai_queue_native_exclude_ready(p_id,p_revision,p_version,p_actor) then perform machimoa_review.myseoul_admin_lock(p_id,p_revision,p_version,p_actor);end if;
 update machimoa_review.source_item_program_facts set manual_excluded=true,facts_version=facts_version+1,updated_by=p_actor,updated_at=clock_timestamp()
 where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note,changed_fields)
 values(p_id,p_revision,'exclude',p_actor,p_note,array['service_scope']);
 perform machimoa_review.myseoul_refresh(p_id);
 return public.admin_myseoul_program_detail(p_id);
end $function$
;

CREATE OR REPLACE FUNCTION machimoa_review.admin_review_exclude_before_trash(p_id uuid, p_revision text, p_version text, p_note text, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare v_id uuid; review_type text;
begin
 if exists(select 1 from machimoa_review.source_items where id=p_id and source_id='myseoul_program') then raise exception using errcode='PT409',message='myseoul_specific_contract_required';end if;
  if machimoa_review.ai_queue_native_exclude_ready(p_id,p_revision,p_version,p_actor) then v_id:=p_id;else v_id:=machimoa_review.admin_review_lock('facts',p_id,p_revision,p_version,p_actor);end if;
  if p_note is null or pg_catalog.char_length(pg_catalog.btrim(p_note)) not between 1 and 500 then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  select case when j.processing_stage='content_review' then 'content' else 'product_type' end into review_type
    from machimoa_review.processing_jobs j where j.source_item_id=v_id and j.revision_hash=p_revision
    and j.processing_stage in ('content_review','product_type_review') and j.status in ('queued','claimed') order by j.processing_stage limit 1;
  if review_type is null and machimoa_review.ai_queue_native_exclude_ready(p_id,p_revision,p_version,p_actor) then
    -- An explicit fresh queue exclusion opens the required formal review stage
    -- and rejects it in this same transaction. The trash wrapper already saved
    -- the prior jobs; no hold, AI claim or visible intermediate state is created.
    insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,queued_at,available_at,reason_codes)
    values(p_id,p_revision,'content_review','queued',clock_timestamp(),clock_timestamp(),array['manual_non_target'])
    on conflict(source_item_id,revision_hash,processing_stage) do update set status='queued',completed_at=null;
    review_type:='content';
  end if;
  if review_type is null then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
  perform public.resolve_ingest_review_decision(v_id,p_revision,review_type,'reject','unknown','{}'::text[],array['manual_non_target'],'admin-review-v1',p_actor::text,pg_catalog.btrim(p_note));
  insert into machimoa_review.admin_review_events(source_item_id,revision_hash,action,actor,note) values(v_id,p_revision,'exclude',p_actor,pg_catalog.btrim(p_note));
  return machimoa_review.admin_review_item('facts',p_id);
exception when raise_exception then raise sqlstate 'PT409' using message='review_conflict';
end $function$
;


-- Queue-version command wraps the existing formal exclusion/72h trash/audit contract.
create function public.admin_ai_queue_exclude(p_job_id uuid,p_revision text,p_version text,p_request_id uuid,p_reason text,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare j machimoa_review.processing_jobs%rowtype;s machimoa_review.source_items%rowtype;r machimoa_review.ai_recheck_receipts%rowtype;d jsonb;native jsonb;outcome jsonb;legacy text;begin
 if p_job_id is null or p_request_id is null or p_actor is null or p_revision is null or p_revision!~'^[a-f0-9]{64}$'
 or p_version is null or p_version!~'^[a-f0-9]{64}$' or p_reason is null or p_reason not in ('service_not_suitable','region_not_suitable') then raise sqlstate 'PT422' using message='invalid_recheck_exclude';end if;
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
revoke all on function machimoa_review.ai_recheck_edit_fields(text),machimoa_review.ai_recheck_edit_guard(uuid,text) from public,anon,authenticated,service_role;
revoke all on function public.admin_ai_queue_exclude(uuid,text,text,uuid,text,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_ai_queue_exclude(uuid,text,text,uuid,text,uuid) to service_role;
commit;
