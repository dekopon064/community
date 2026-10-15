begin;
set local lock_timeout='5s'; set local statement_timeout='30s';
-- DDL only. No backfill, content changes, claims or AI execution.
do $$ declare f record; begin
 if current_user<>'postgres' then raise exception 'postgres_required'; end if;
 select * into f from pg_proc where oid=to_regprocedure('public.admin_program_save(uuid,text,text,jsonb,text[],text,uuid)');
 if f.oid is null or pg_get_userbyid(f.proowner)<>'postgres' or not f.prosecdef
 or f.proconfig is distinct from array['search_path=""']::text[]
 or f.proacl::text is distinct from '{postgres=X/postgres,service_role=X/postgres}'
 or encode(sha256(convert_to(replace(replace(pg_get_functiondef(f.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'c3183366eb3bd846ba9d3201255b0b2752dd3271537c8794ba6768ad41fd88a6'
 then raise exception 'same_period_predecessor_changed';end if;
end $$;

-- Deliberately narrow proof: role-labelled date ranges in CURRENT description.
-- Unsupported prose, unknown year, stale evidence and any real conflict stay open.
create function machimoa_review.seoul_same_period_supported(p jsonb) returns boolean
language plpgsql immutable set search_path='' as $$
declare line text; statement text; role_name text; m text[]; a date; b date; k text;
 seen text[]:='{}'; proof_count int:=0; ep jsonb; clock_value text;
 pattern text:='(20[0-9]{2})\s*[.년/-]\s*([0-9]{1,2})\s*[.월/-]\s*([0-9]{1,2})\s*(?:일|\.)?\s*(?:\(\s*([월화수목금토일])(?:요일)?\s*\))?\s*(?:[~～〜–—-]|부터)\s*(?:(20[0-9]{2})\s*[.년/-]\s*)?(?:([0-9]{1,2})\s*[.월/-]\s*)?([0-9]{1,2})\s*(?:일|\.)?\s*(?:\(\s*([월화수목금토일])(?:요일)?\s*\))?';
begin
 perform machimoa_review.program_validate(p);
 if not (p->'missing' ? 'body_period_needs_confirmation')
 or p->'conflicts' ?| array['body_period_needs_confirmation','body_api_period_conflict','date_weekday_conflict','invalid_body_date','period_order_conflict']
 or exists(select 1 from jsonb_each(p->'periods') x where x.value->>'status'<>'ok') then return false;end if;
 for line in select regexp_split_to_table(p->>'description',E'\n') loop
  line:=regexp_replace(btrim(line),'^[[:space:]□■○ㅇ❐•●▪▶▷※*·✅☑✔✓◆◇🔸🔹-]+','');
  line:=regexp_replace(line,'^(?:[0-9]{1,2}[.)]\s*|[①-⑳]\s*)','');
  role_name:=case when line ~ '^(접수기간|신청기간|모집기간)\s*[:：]' then 'RCPT'
                  when line ~ '^(운영기간|진행기간)\s*[:：]' then 'SVCOPN' end;
  if role_name is null then continue;end if;
  statement:=btrim(regexp_replace(line,'^[^:：]+[:：]\s*',''));
  m:=regexp_match(statement,'^'||pattern||'\s*$');
  if m is null then m:=regexp_match(statement,'^'||pattern||'\s+([0-9]{1,2}):([0-5][0-9])\s*$');end if;
  if m is null then return false;end if;
  a:=make_date(m[1]::int,m[2]::int,m[3]::int);
  b:=make_date(coalesce(m[5],m[1])::int,coalesce(m[6],m[2])::int,m[7]::int);
  if a>b or m[4] is not null and m[4]<>substr('월화수목금토일',extract(isodow from a)::int,1)
         or m[8] is not null and m[8]<>substr('월화수목금토일',extract(isodow from b)::int,1) then return false;end if;
  foreach k in array array['BGNDT','ENDDT'] loop
   ep:=p->'periods'->(role_name||k);
   if (case when ep->>'precision'='day' then (ep->>'value')::date
       else ((ep->>'value')::timestamptz at time zone 'Asia/Seoul')::date end)
       is distinct from (case when k='BGNDT' then a else b end) then return false;end if;
  end loop;
  if array_length(m,1)=10 then
   if m[9]::int>23 then return false;end if;
   ep:=p->'periods'->(role_name||'ENDDT');
   clock_value:=lpad(m[9],2,'0')||':'||m[10]||':00';
   if ep->>'precision'<>'second' or to_char((ep->>'value')::timestamptz at time zone 'Asia/Seoul','HH24:MI:SS')<>clock_value then return false;end if;
  end if;
  seen:=array_append(seen,statement);proof_count:=proof_count+1;
 end loop;
 if proof_count=0 or jsonb_array_length(p->'period_evidence')=0 then return false;end if;
 if exists(select 1 from jsonb_array_elements_text(p->'period_evidence') e where not e=any(seen)) then return false;end if;
 return true;
exception when datetime_field_overflow or invalid_datetime_format or invalid_text_representation then return false;
end $$;
revoke all on function machimoa_review.seoul_same_period_supported(jsonb) from public,anon,authenticated,service_role;
CREATE OR REPLACE FUNCTION public.admin_program_save(p_id uuid, p_revision text, p_version text, p_patch jsonb, p_resolve text[], p_note text, p_actor uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare s machimoa_review.source_items%rowtype; f machimoa_review.source_item_program_facts%rowtype; item jsonb;
 next_facts jsonb; field text; reason text; allowed text[]:='{}'; active text[]; changed text[]:='{}'; d jsonb; same_period boolean:=false;
begin
 p_note:=btrim(coalesce(p_note,''));
 if p_actor is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or p_version is null or p_version !~ '^[a-f0-9]{64}$'
 or p_patch is null or jsonb_typeof(p_patch)<>'object' or p_resolve is null or cardinality(p_resolve)>30
 or char_length(btrim(coalesce(p_note,'')))>4000 then
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
 same_period:=cardinality(changed)=0 and p_patch=jsonb_build_object('periods',f.facts->'periods')
 and p_resolve=array['body_period_needs_confirmation']::text[]
 and active @> p_resolve and machimoa_review.seoul_same_period_supported(f.facts);
 if cardinality(changed)=0 and not same_period then raise exception using errcode='PT422',message='program_change_required';end if;
 if same_period then
   perform pg_advisory_xact_lock(hashtextextended('seoul_reservation'||':'||s.external_key,0));
   perform 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key for update;
   if exists(select 1 from machimoa_review.curation_candidates where machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key)
   or exists(select 1 from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=p_revision)
   or exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id and revision_hash=p_revision and processing_stage='ai_enrichment' and status in ('completed','failed'))
   then raise sqlstate 'PT409' using message='program_reconfirmation_blocked';end if;
 end if;
 next_facts:=f.facts||p_patch;
 foreach reason in array p_resolve loop
   if reason is null or not reason=any(active) or not (same_period or changed && array(select x from unnest(machimoa_review.program_reason_fields(reason)) x where x not in ('activity_evidence','residence_evidence','period_evidence'))) then
   raise exception using errcode='PT422',message='program_reason_not_resolved';end if;
   next_facts:=jsonb_set(next_facts,'{missing}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_facts->'missing') where value#>>'{}'<>reason),'[]'));
   next_facts:=jsonb_set(next_facts,'{conflicts}',coalesce((select jsonb_agg(value) from jsonb_array_elements(next_facts->'conflicts') where value#>>'{}'<>reason),'[]'));
 end loop;
 perform machimoa_review.program_validate(next_facts);
 -- A resolution must supply actual facts, not merely remove a diagnostic flag.
 if next_facts->>'official_url'='' and 'missing_source_url'=any(p_resolve) or
 char_length(btrim(next_facts->>'description'))<20 and p_resolve && array['attachment_dependent','program_description_missing'] then
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
 values(p_id,p_revision,'save_facts',p_actor,p_note,(case when same_period then array['reconfirmed:periods'] else changed end)||array(select 'resolved:'||x from unnest(p_resolve) x));
 perform machimoa_review.program_refresh(p_id);
 return public.admin_program_detail(p_id);
end $function$;

commit;
